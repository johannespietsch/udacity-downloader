#!/usr/bin/env python3
"""
Udacity Course Downloader

Downloads course content from learn.udacity.com including videos, subtitles,
and lesson materials. Supports Udacity's Next.js RSC (React Server Components) backend.

Usage:
    python download.py nd123 nd456 --token YOUR_JWT_TOKEN
    UDACITY_TOKEN=your_token python download.py nd123
"""

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

import requests
from tqdm import tqdm


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('udacity_downloader.log')
    ]
)
logger = logging.getLogger(__name__)


class UdacityDownloader:
    """Downloads Udacity course content from learn.udacity.com using RSC backend"""
    
    def __init__(self, token: str, output_dir: str = "output", rate_limit: float = 1.5):
        """
        Initialize the downloader.
        
        Args:
            token: JWT authentication token (without Bearer prefix)
            output_dir: Directory to save downloaded content
            rate_limit: Seconds to wait between requests
        """
        self.token = token
        self.output_dir = Path(output_dir)
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.last_request_time = 0
        
        # RSC-compatible headers for Next.js backend
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/x-component',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'RSC': '1',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"macOS"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Cookie': f'_jwt={token}',
        })
        
        # Downloaded files tracking for resume capability
        self.downloaded_files: Set[str] = set()

        # Separate session for file downloads (no RSC headers)
        self.download_session = requests.Session()
        self.download_session.headers.update({
            'User-Agent': self.session.headers['User-Agent'],
            'Cookie': self.session.headers['Cookie'],
        })
        
    def _rate_limit(self):
        """Enforce rate limiting between requests"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self.last_request_time = time.time()
        
    def _make_rsc_request(self, url: str, next_url: Optional[str] = None) -> Optional[str]:
        """
        Make a rate-limited RSC request with proper headers.
        
        Args:
            url: URL to request
            next_url: Next-Url header value for RSC routing
            
        Returns:
            Response text or None if failed
        """
        self._rate_limit()
        
        headers = {}
        if next_url:
            headers['Next-Url'] = next_url
        
        try:
            logger.info(f"Making RSC request to: {url}")
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"RSC request failed for {url}: {e}")
            return None
            
    def _parse_rsc_redirect(self, rsc_response: str) -> Optional[str]:
        """
        Parse RSC response for redirect instructions.
        
        Args:
            rsc_response: Raw RSC response text
            
        Returns:
            Redirect URL or None if no redirect found
        """
        # Look for NEXT_REDIRECT pattern
        redirect_pattern = r'E\{"digest":"NEXT_REDIRECT;replace;([^;]+);'
        match = re.search(redirect_pattern, rsc_response)
        if match:
            redirect_path = match.group(1)
            logger.info(f"Found redirect to: {redirect_path}")
            return f"https://learn.udacity.com{redirect_path}"
        return None
        
    def _find_program_tree_in_obj(self, obj: Any) -> Optional[Dict[str, Any]]:
        """Recursively search for programTree query data in a parsed JSON object."""
        if isinstance(obj, dict):
            # Check if this is a React Query state with queries array
            if 'queries' in obj and isinstance(obj['queries'], list):
                for query in obj['queries']:
                    if (isinstance(query, dict) and 
                        query.get('queryKey') == ['programTree'] and
                        'state' in query and 'data' in query['state']):
                        return query['state']['data']
            # Check if this dict directly has programTree-like structure
            if ('parts' in obj or 'lessons' in obj) and 'title' in obj and 'key' in obj:
                return obj
            # Recurse into dict values
            for v in obj.values():
                result = self._find_program_tree_in_obj(v)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._find_program_tree_in_obj(item)
                if result:
                    return result
        return None

    def _extract_rsc_segments(self, rsc_response: str) -> List[str]:
        """
        Extract all RSC segments from response text.
        
        RSC format can pack multiple segments per line. T-prefixed segments
        have a hex length, and the next segment follows immediately after.
        Format: ID:T{hex_length},{content_of_that_length}NEXT_SEGMENT
        """
        segments = []
        for line in rsc_response.split('\n'):
            # Process T-blocks: they have a fixed length and more data may follow
            remaining = line
            while remaining:
                t_match = re.match(r'^([0-9a-fA-F]+):T([0-9a-fA-F]+),', remaining)
                if t_match:
                    hex_len = int(t_match.group(2), 16)
                    content_start = t_match.end()
                    # Skip past the T-block content
                    remaining = remaining[content_start + hex_len:]
                    continue
                
                # Regular RSC segment: hexkey:value
                seg_match = re.match(r'^([0-9a-fA-F]+):', remaining)
                if seg_match:
                    segments.append(remaining)
                    break  # Rest of line is this segment
                else:
                    # Not an RSC-formatted line
                    break
        return segments

    def _parse_rsc_program_tree(self, rsc_response: str) -> Optional[Dict[str, Any]]:
        """
        Parse RSC response to extract programTree data.
        
        The RSC format packs segments together. T-blocks (text content) have
        a hex length prefix, and JSON segments can follow on the same line.
        The programTree is inside a React Query hydration state's queries array.
        """
        segments = self._extract_rsc_segments(rsc_response)
        
        for segment in segments:
            if '"programTree"' not in segment:
                continue
                
            match = re.match(r'^[0-9a-fA-F]+:', segment)
            if not match:
                continue
                
            json_str = segment[match.end():]
            try:
                data = json.loads(json_str)
                result = self._find_program_tree_in_obj(data)
                if result:
                    logger.info(f"Found programTree with {len(result.get('parts', []))} parts")
                    return result
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug(f"Failed to parse RSC segment as JSON: {e}")
                continue
                    
        logger.warning("programTree not found in RSC response")
        return None
        
    def _extract_t_blocks(self, rsc_response: str) -> List[str]:
        """
        Extract T-block text content from RSC response.
        T-blocks span multiple lines: ID:T{hex_length},{content_of_exact_byte_length}
        """
        blocks = []
        # Find all T-block headers in the raw response (not split by newline)
        for m in re.finditer(r'([0-9a-fA-F]+):T([0-9a-fA-F]+),', rsc_response):
            hex_len = int(m.group(2), 16)
            content_start = m.end()
            content = rsc_response[content_start:content_start + hex_len]
            # Skip base64-encoded search keys and other non-content blocks
            if content and not re.match(r'^[A-Za-z0-9+/=]{50,}$', content[:60]):
                blocks.append(content)
        return blocks

    def _extract_concept_atoms(self, rsc_response: str) -> List[Dict]:
        """
        Extract concept atom data (video, text, image, quiz) from RSC response.
        Atoms are in JSON segments with the structure: {atoms: [{semanticType, video/text/...}]}
        """
        atoms = []
        for seg in self._extract_rsc_segments(rsc_response):
            if 'atoms' not in seg:
                continue
            m = re.match(r'^[0-9a-fA-F]+:', seg)
            if not m:
                continue
            try:
                data = json.loads(seg[m.end():])
                def find_atoms(obj):
                    if isinstance(obj, dict):
                        if 'atoms' in obj and isinstance(obj['atoms'], list):
                            return obj['atoms']
                        for v in obj.values():
                            result = find_atoms(v)
                            if result:
                                return result
                    elif isinstance(obj, list):
                        for item in obj:
                            result = find_atoms(item)
                            if result:
                                return result
                    return None
                found = find_atoms(data)
                if found:
                    return found
            except (json.JSONDecodeError, ValueError):
                continue
        return atoms

    def _parse_concept_data(self, rsc_response: str) -> Dict[str, Any]:
        """
        Parse concept page RSC response to extract text content and video info.
        Returns dict with 'text' (markdown), 'video' (dict or None), 'subtitle_url' (str or None).
        """
        result = {'text': '', 'video': None, 'subtitle_url': None}
        
        # Method 1: Extract from atoms (structured data - has video info)
        atoms = self._extract_concept_atoms(rsc_response)
        if atoms:
            text_parts = []
            for atom in atoms:
                st = atom.get('semanticType', '')
                if st == 'VideoAtom' and 'video' in atom:
                    video = atom['video']
                    result['video'] = {
                        'youtube_id': video.get('youtubeId'),
                        'topher_id': video.get('topherId'),
                    }
                    result['subtitle_url'] = video.get('subtitlesUrl')
                elif st == 'TextAtom' and 'text' in atom:
                    text_parts.append(atom['text'])
                elif st == 'ImageAtom' and 'image' in atom:
                    img = atom['image']
                    if isinstance(img, dict) and img.get('url'):
                        text_parts.append(f"![{img.get('caption', 'Image')}]({img['url']})")
            if text_parts:
                result['text'] = '\n\n'.join(text_parts)
                return result
        
        # Method 2: Extract from T-blocks (text content that spans multiple lines)
        t_blocks = self._extract_t_blocks(rsc_response)
        if t_blocks:
            result['text'] = '\n\n'.join(t_blocks)
        
        return result
        
    def _get_course_data(self, course_key: str) -> Optional[Dict[str, Any]]:
        """
        Fetch course data using RSC API.
        
        Args:
            course_key: Course identifier (e.g., 'nd123')
            
        Returns:
            Course data dictionary or None if failed
        """
        # Step 1: Initial RSC request
        initial_url = f"https://learn.udacity.com/{course_key}"
        initial_response = self._make_rsc_request(initial_url, next_url=f"/{course_key}")
        
        if not initial_response:
            return None
            
        # Step 2: Check for redirect
        redirect_url = self._parse_rsc_redirect(initial_response)
        
        if redirect_url:
            # Follow the redirect
            parsed_url = urllib.parse.urlparse(redirect_url)
            redirect_response = self._make_rsc_request(redirect_url, next_url=parsed_url.path)
            if redirect_response:
                program_tree = self._parse_rsc_program_tree(redirect_response)
            else:
                program_tree = None
        else:
            # Try to parse programTree from initial response
            program_tree = self._parse_rsc_program_tree(initial_response)
            
        return program_tree
        
    def _get_concept_content(self, course_key: str, version: str, part_key: str, 
                           lesson_key: str, concept_key: str) -> Dict[str, Any]:
        """
        Fetch individual concept content including text and video data.
        
        Returns:
            Dict with 'text', 'video', 'subtitle_url' keys
        """
        params = f"version={version}&lessonKey={lesson_key}&conceptKey={concept_key}"
        if part_key:
            params = f"version={version}&partKey={part_key}&lessonKey={lesson_key}&conceptKey={concept_key}"
        concept_url = f"https://learn.udacity.com/{course_key}?{params}"
        
        response = self._make_rsc_request(concept_url, next_url=f"/{course_key}")
        if response:
            return self._parse_concept_data(response)
        return {'text': '', 'video': None, 'subtitle_url': None}
        
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem compatibility"""
        # Remove path separators and parent directory references
        filename = filename.replace('..', '_')
        # Replace invalid characters with underscores
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        # Limit length and strip trailing dots/spaces (Windows compat)
        return filename[:100].strip('. ')
        
    def _download_file(self, url: str, filepath: Path, description: str = "") -> bool:
        """
        Download a file with progress bar and resume capability.
        
        Args:
            url: URL to download
            filepath: Local path to save file
            description: Description for progress bar
            
        Returns:
            True if successful, False otherwise
        """
        # Skip if already downloaded
        if str(filepath) in self.downloaded_files or filepath.exists():
            logger.info(f"Skipping {filepath.name} (already exists)")
            self.downloaded_files.add(str(filepath))
            return True
            
        # Create parent directories
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Get file size for progress bar
            self._rate_limit()
            head_response = self.download_session.head(url, timeout=10)
            total_size = int(head_response.headers.get('content-length', 0))
            
            # Download with progress bar
            self._rate_limit()
            response = self.download_session.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            with open(filepath, 'wb') as file, tqdm(
                desc=description or filepath.name[:50],
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                leave=False,
            ) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
                        pbar.update(len(chunk))
                        
            self.downloaded_files.add(str(filepath))
            logger.info(f"Downloaded {filepath.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            # Clean up partial download
            if filepath.exists():
                filepath.unlink()
            return False
            
    def _process_lesson_resources(self, resources: List[Dict], lesson_dir: Path, 
                                lesson_title: str) -> int:
        """
        Download all resources for a lesson.
        
        Args:
            resources: List of resource dictionaries
            lesson_dir: Directory to save resources
            lesson_title: Lesson title for progress descriptions
            
        Returns:
            Number of successfully downloaded resources
        """
        if not resources:
            return 0
            
        success_count = 0
        resources_dir = lesson_dir / "resources"
        
        for resource in resources:
            if not isinstance(resource, dict) or 'uri' not in resource:
                continue
                
            uri = resource['uri']
            name = resource.get('name', 'Unknown Resource')
            
            # Determine filename and subdirectory
            filename = Path(urllib.parse.urlparse(uri).path).name
            if not filename:
                continue
                
            # Organize by resource type — zips in lesson dir, other resources in resources/
            if filename.endswith('.zip'):
                filepath = lesson_dir / filename
            else:
                filepath = resources_dir / filename
                
            if self._download_file(uri, filepath, f"{lesson_title}: {name}"):
                success_count += 1
                
        return success_count
        
    def _save_concept_content(self, concepts: List[Dict], lesson_dir: Path,
                            course_key: str, version: str, part_key: str, 
                            lesson_key: str) -> int:
        """
        Save concept text content as markdown files directly in lesson dir.
        Includes video links (YouTube) and subtitle URLs when available.
        """
        if not concepts:
            return 0
            
        saved_count = 0
        
        for i, concept in enumerate(concepts, 1):
            if not isinstance(concept, dict) or 'key' not in concept:
                continue
                
            concept_key = concept['key']
            concept_title = concept.get('title', f'Concept {i}')
            
            # Create safe filename — directly in lesson dir (no concepts/ subdir)
            safe_title = self._sanitize_filename(concept_title)
            filename = f"{i:02d}_{safe_title}.md"
            filepath = lesson_dir / filename
            
            # Skip if already exists
            if filepath.exists():
                saved_count += 1
                continue
                
            # Fetch concept content
            logger.info(f"Fetching concept content: {concept_title}")
            data = self._get_concept_content(
                course_key, version, part_key, lesson_key, concept_key
            )
            
            text = data.get('text', '')
            video = data.get('video')
            subtitle_url = data.get('subtitle_url')
            
            if text or video:
                # Build markdown file
                md = f"# {concept_title}\n\n"
                
                # Add video info if present
                if video:
                    yt_id = video.get('youtube_id')
                    if yt_id:
                        md += f"🎥 **Video:** [Watch on YouTube](https://www.youtube.com/watch?v={yt_id})\n\n"
                    if subtitle_url:
                        md += f"📝 **Subtitles:** [VTT]({subtitle_url})\n\n"
                    md += "---\n\n"
                
                if text:
                    md += text
                
                filepath.write_text(md, encoding='utf-8')
                logger.info(f"Saved concept: {filename}")
                saved_count += 1
            else:
                logger.warning(f"No content found for concept: {concept_title}")
                
        return saved_count
        
    def download_course(self, course_key: str) -> bool:
        """
        Download a complete course.
        Handles both nanodegree (parts → lessons) and simple course (lessons only) structures.
        """
        print(f"\n🎓 Starting download for course: {course_key}")
        logger.info(f"Starting course download: {course_key}")
        
        # Fetch course data using RSC API
        print(f"🌐 Fetching course structure from Udacity RSC API...")
        course_data = self._get_course_data(course_key)
        
        if not course_data:
            print(f"❌ Failed to fetch course data for {course_key}")
            return False
            
        # Extract course information
        course_title = course_data.get('title', course_key)
        version = course_data.get('version', '1.0.0')
        
        # Course dir: "<id> <title>"
        safe_title = self._sanitize_filename(course_title)
        course_dir = self.output_dir / f"{course_key} {safe_title}"
        course_dir.mkdir(parents=True, exist_ok=True)
        
        # Handle both structures:
        # - Nanodegrees have "parts" containing "lessons"
        # - Simple courses (ud*) have "lessons" directly at top level
        parts = course_data.get('parts') or []
        top_level_lessons = course_data.get('lessons') or []
        
        if not parts and top_level_lessons:
            # Simple course: wrap lessons in a single virtual part
            parts = [{
                'key': '',
                'title': course_title,
                'lessons': top_level_lessons,
            }]
            print(f"📚 Course: {course_title} (simple course)")
            print(f"📄 Found {len(top_level_lessons)} lessons")
        else:
            print(f"📚 Course: {course_title}")
            print(f"📁 Found {len(parts)} parts")
        
        # Save course metadata
        metadata = {
            'course_key': course_key,
            'title': course_title,
            'version': version,
            'parts_count': len(parts),
            'download_date': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        (course_dir / 'course_metadata.json').write_text(
            json.dumps(metadata, indent=2), encoding='utf-8'
        )
        
        # Process each part
        total_lessons = 0
        total_concepts = 0
        total_downloads = 0
        
        for part_idx, part in enumerate(parts, 1):
            if not isinstance(part, dict):
                continue
                
            part_key = part.get('key', '')
            part_title = part.get('title', 'Unknown Part')
            lessons = part.get('lessons') or []
            
            print(f"\n📖 Part {part_idx}: {part_title} ({len(lessons)} lessons)")
            
            # Numbered part directory (skip if single virtual part for simple courses)
            safe_part_title = self._sanitize_filename(part_title)
            if len(parts) > 1:
                part_dir = course_dir / f"{part_idx:02d} {safe_part_title}"
            else:
                part_dir = course_dir  # Simple course: lessons directly in course dir
            
            for lesson_idx, lesson in enumerate(lessons, 1):
                if not isinstance(lesson, dict):
                    continue
                    
                lesson_key = lesson.get('key', '')
                lesson_title = lesson.get('title', 'Unknown Lesson')
                concepts = lesson.get('concepts') or []
                resources = lesson.get('resources') or []
                
                print(f"  📄 {lesson_idx}. {lesson_title} ({len(concepts)} concepts, {len(resources)} resources)")
                total_lessons += 1
                
                # Numbered lesson directory
                safe_lesson_title = self._sanitize_filename(lesson_title)
                lesson_dir = part_dir / f"{lesson_idx:02d} {safe_lesson_title}"
                lesson_dir.mkdir(parents=True, exist_ok=True)
                
                # Download resources
                downloaded_resources = self._process_lesson_resources(
                    resources, lesson_dir, lesson_title
                )
                total_downloads += downloaded_resources
                
                # Save concept content (directly in lesson dir, no concepts/ subdir)
                saved_concepts = self._save_concept_content(
                    concepts, lesson_dir, course_key, version, 
                    part_key, lesson_key
                )
                total_concepts += saved_concepts
                
        # Print summary
        print(f"\n🎉 Course {course_key} download completed!")
        print(f"📊 Summary:")
        print(f"  - Parts: {len(parts)}")
        print(f"  - Lessons: {total_lessons}")
        print(f"  - Concepts: {total_concepts}")
        print(f"  - Downloaded files: {total_downloads}")
        
        logger.info(f"Course download completed: {course_key}")
        return True
        

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Download Udacity courses from learn.udacity.com (RSC backend)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python download.py nd123 --token YOUR_JWT_TOKEN
  UDACITY_TOKEN=token python download.py nd123 nd456
  python download.py nd123 --output-dir ./downloads --rate-limit 2.0
  
Note: Use Cookie JWT token (not Bearer token) from browser DevTools.
        """,
    )
    
    parser.add_argument(
        'courses',
        nargs='+',
        help='Course keys to download (e.g., nd123, nd456)',
    )
    
    parser.add_argument(
        '--token',
        help='JWT authentication token (can also use UDACITY_TOKEN env var)',
    )
    
    parser.add_argument(
        '--output-dir',
        default='output',
        help='Output directory for downloads (default: output)',
    )
    
    parser.add_argument(
        '--rate-limit',
        type=float,
        default=1.5,
        help='Seconds to wait between requests (default: 1.5)',
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging',
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        
    # Get token from argument or environment
    token = args.token or os.getenv('UDACITY_TOKEN')
    if not token:
        print("❌ Error: JWT token required. Use --token argument or UDACITY_TOKEN environment variable.")
        print("💡 Get your token from browser DevTools > Network > Cookie: _jwt=...")
        sys.exit(1)
        
    print("🚀 Udacity Course Downloader (RSC Backend)")
    print(f"📁 Output directory: {args.output_dir}")
    print(f"⏱️  Rate limit: {args.rate_limit} seconds")
    print(f"🎯 Courses to download: {', '.join(args.courses)}")
    
    # Initialize downloader
    downloader = UdacityDownloader(
        token=token,
        output_dir=args.output_dir,
        rate_limit=args.rate_limit,
    )
    
    # Download each course
    success_count = 0
    for course_key in args.courses:
        try:
            if downloader.download_course(course_key):
                success_count += 1
        except KeyboardInterrupt:
            print("\n⏹️  Download interrupted by user")
            break
        except Exception as e:
            print(f"❌ Unexpected error downloading {course_key}: {e}")
            logger.exception(f"Unexpected error downloading {course_key}")
            
    print(f"\n📊 Download Summary: {success_count}/{len(args.courses)} courses successful")
    
    if success_count == len(args.courses):
        print("🎉 All downloads completed successfully!")
    elif success_count > 0:
        print("⚠️  Some downloads failed. Check output above for details.")
    else:
        print("❌ All downloads failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()