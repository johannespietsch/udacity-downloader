#!/usr/bin/env python3
"""
Udacity Course Downloader (GraphQL API)

Downloads course content from learn.udacity.com including videos, subtitles,
and lesson materials via the classroom-content GraphQL API.

DISCLAIMER: This tool is intended solely as a personal backup utility for
enrolled Udacity students who wish to keep an offline copy of course materials
they have legitimately paid for and have access to. This tool is not affiliated
with, endorsed by, or associated with Udacity, Inc. in any way.

Users are solely responsible for ensuring their use of this tool complies with
Udacity's Terms of Use (https://www.udacity.com/legal/terms-of-use) and all
applicable laws. Do not use this tool to redistribute, sell, or share downloaded
content. Do not use this tool if you are not enrolled in the courses you intend
to download.

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
from typing import Any, Dict, List, Optional, Set

import requests
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("udacity_downloader.log"),
    ],
)
logger = logging.getLogger(__name__)

GRAPHQL_ENDPOINT = "https://learn.udacity.com/api/classroom-content/v1/graphql"

# ---------------------------------------------------------------------------
# GraphQL query fragments
# ---------------------------------------------------------------------------

# Structure-only queries (no atoms – keeps payloads small)
NANODEGREE_STRUCTURE_QUERY = """
query NanodegreeStructure($key: String!) {
  nanodegree(key: $key) {
    id key title version semantic_type
    parts {
      key title
      modules {
        key title
        lessons {
          key title
          concepts { key title }
          resources { files { uri name } }
        }
      }
    }
  }
}
"""

COURSE_STRUCTURE_QUERY = """
query CourseStructure($key: String!) {
  course(key: $key) {
    id key title version semantic_type
    lessons {
      key title
      concepts { key title }
      resources { files { uri name } }
    }
  }
}
"""

CONCEPT_ATOMS_QUERY = """
query ConceptAtoms($key: String!) {
  concept(key: $key) {
    key title
    atoms {
      ... on TextAtom { semantic_type text }
      ... on VideoAtom {
        semantic_type
        video { youtube_id topher_id subtitles_vtt_url }
      }
      ... on ImageAtom { semantic_type url caption }
    }
  }
}
"""


class UdacityDownloader:
    """Downloads Udacity course content via the classroom-content GraphQL API."""

    def __init__(self, token: str, output_dir: str = "output", rate_limit: float = 1.5):
        self.token = token
        self.output_dir = Path(output_dir)
        self.rate_limit = rate_limit
        self.last_request_time = 0.0
        self.downloaded_files: Set[str] = set()

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        # Separate session for file downloads (no JSON headers)
        self.download_session = requests.Session()
        self.download_session.headers.update({
            "User-Agent": self.session.headers["User-Agent"],
            "Cookie": f"_jwt={token}",
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _wait(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self.last_request_time = time.time()

    def _graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a GraphQL query and return the `data` dict (or raise)."""
        self._wait()
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        logger.debug("GraphQL request: %s", json.dumps(payload, indent=2)[:500])
        resp = self.session.post(GRAPHQL_ENDPOINT, json=payload, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        if "errors" in body:
            logger.debug("GraphQL errors: %s", body["errors"])
            raise ValueError(body["errors"])
        return body.get("data", {})

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        name = name.replace("..", "_")
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, "_")
        return name[:100].strip(". ")

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _get_course_data(self, course_key: str) -> Optional[Dict[str, Any]]:
        """
        Fetch course structure via GraphQL.

        Tries nanodegree first, then course.  Returns a normalised dict with
        keys: title, version, semantic_type, parts (list of dicts with lessons).
        For plain courses the lessons are wrapped in a single virtual part.
        """
        # --- Try nanodegree first ---
        try:
            data = self._graphql(NANODEGREE_STRUCTURE_QUERY, {"key": course_key})
            nd = data.get("nanodegree")
            if nd:
                logger.info("Fetched nanodegree: %s", nd.get("title"))
                # Flatten modules into lessons per part
                parts = []
                for part in nd.get("parts") or []:
                    lessons = []
                    for module in part.get("modules") or []:
                        lessons.extend(module.get("lessons") or [])
                    parts.append({
                        "key": part["key"],
                        "title": part.get("title", "Untitled Part"),
                        "lessons": lessons,
                    })
                return {
                    "title": nd["title"],
                    "version": nd.get("version", "1.0.0"),
                    "semantic_type": nd.get("semantic_type"),
                    "parts": parts,
                }
        except (ValueError, requests.RequestException) as exc:
            logger.debug("Nanodegree query failed for %s: %s", course_key, exc)

        # --- Fall back to course ---
        try:
            data = self._graphql(COURSE_STRUCTURE_QUERY, {"key": course_key})
            course = data.get("course")
            if course:
                logger.info("Fetched course: %s", course.get("title"))
                return {
                    "title": course["title"],
                    "version": course.get("version", "1.0.0"),
                    "semantic_type": course.get("semantic_type"),
                    "lessons": course.get("lessons") or [],
                }
        except (ValueError, requests.RequestException) as exc:
            logger.error("Course query also failed for %s: %s", course_key, exc)

        return None

    def _get_concept_atoms(self, concept_key: str) -> Dict[str, Any]:
        """Fetch atoms for a single concept.  Returns parsed concept dict."""
        try:
            data = self._graphql(CONCEPT_ATOMS_QUERY, {"key": concept_key})
            return data.get("concept") or {}
        except (ValueError, requests.RequestException) as exc:
            logger.error("Failed to fetch atoms for concept %s: %s", concept_key, exc)
            return {}

    # ------------------------------------------------------------------
    # Downloading helpers
    # ------------------------------------------------------------------

    def _download_file(self, url: str, filepath: Path, description: str = "") -> bool:
        if str(filepath) in self.downloaded_files or filepath.exists():
            logger.info("Skipping %s (already exists)", filepath.name)
            self.downloaded_files.add(str(filepath))
            return True

        filepath.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._wait()
            head = self.download_session.head(url, timeout=10, allow_redirects=True)
            total_size = int(head.headers.get("content-length", 0))

            self._wait()
            resp = self.download_session.get(url, stream=True, timeout=60)
            resp.raise_for_status()

            with open(filepath, "wb") as fh, tqdm(
                desc=description or filepath.name[:50],
                total=total_size,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                leave=False,
            ) as pbar:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        fh.write(chunk)
                        pbar.update(len(chunk))

            self.downloaded_files.add(str(filepath))
            logger.info("Downloaded %s", filepath.name)
            return True
        except Exception as exc:
            logger.error("Failed to download %s: %s", url, exc)
            if filepath.exists():
                filepath.unlink()
            return False

    def _process_lesson_resources(self, resources: List[Dict], lesson_dir: Path,
                                  lesson_title: str) -> int:
        if not resources:
            return 0

        success = 0
        resources_dir = lesson_dir / "resources"

        for res in resources:
            files = res.get("files") if isinstance(res, dict) else None
            if not files:
                continue
            for f in files:
                uri = f.get("uri")
                name = f.get("name", "file")
                if not uri:
                    continue
                filename = Path(urllib.parse.urlparse(uri).path).name or name
                if filename.endswith(".zip"):
                    fpath = lesson_dir / filename
                else:
                    fpath = resources_dir / filename
                if self._download_file(uri, fpath, f"{lesson_title}: {name}"):
                    success += 1
        return success

    # ------------------------------------------------------------------
    # Concept → Markdown
    # ------------------------------------------------------------------

    def _save_concept_content(self, concepts: List[Dict], lesson_dir: Path) -> int:
        if not concepts:
            return 0

        saved = 0
        for i, concept in enumerate(concepts, 1):
            concept_key = concept.get("key")
            concept_title = concept.get("title", f"Concept {i}")
            safe_title = self._sanitize_filename(concept_title)
            filepath = lesson_dir / f"{i:02d}_{safe_title}.md"

            if filepath.exists():
                saved += 1
                continue

            logger.info("Fetching atoms for concept: %s", concept_title)
            atom_data = self._get_concept_atoms(concept_key)
            atoms = atom_data.get("atoms") or []

            text_parts: List[str] = []
            videos: List[Dict[str, Any]] = []
            subtitle_urls: List[str] = []

            for atom in atoms:
                st = atom.get("semantic_type", "")
                if st == "VideoAtom" and "video" in atom:
                    vid = atom["video"]
                    videos.append({
                        "youtube_id": vid.get("youtube_id"),
                        "topher_id": vid.get("topher_id"),
                    })
                    sub_url = vid.get("subtitles_vtt_url")
                    if sub_url:
                        subtitle_urls.append(sub_url)
                elif st == "TextAtom" and atom.get("text"):
                    text_parts.append(atom["text"])
                elif st == "ImageAtom" and atom.get("url"):
                    caption = atom.get("caption", "Image")
                    text_parts.append(f"![{caption}]({atom['url']})")

            if not text_parts and not videos:
                logger.warning("No content for concept: %s", concept_title)
                continue

            md = f"# {concept_title}\n\n"
            if videos:
                for vid in videos:
                    yt_id = vid.get("youtube_id")
                    if yt_id and re.match(r"^[\w-]+$", yt_id):
                        md += f"🎥 **Video:** [Watch on YouTube](https://www.youtube.com/watch?v={yt_id})\n\n"
                for sub_url in subtitle_urls:
                    md += f"📝 **Subtitles:** [VTT]({sub_url})\n\n"
                md += "---\n\n"
            if text_parts:
                md += "\n\n".join(text_parts)

            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(md, encoding="utf-8")
            logger.info("Saved concept: %s", filepath.name)
            saved += 1

        return saved

    # ------------------------------------------------------------------
    # Main download logic
    # ------------------------------------------------------------------

    def download_course(self, course_key: str) -> bool:
        print(f"\n🎓 Starting download for course: {course_key}")
        logger.info("Starting course download: %s", course_key)

        print("🌐 Fetching course structure via GraphQL API...")
        course_data = self._get_course_data(course_key)
        if not course_data:
            print(f"❌ Failed to fetch course data for {course_key}")
            return False

        course_title = course_data.get("title", course_key)
        version = course_data.get("version", "1.0.0")

        safe_title = self._sanitize_filename(course_title)
        course_dir = self.output_dir / f"{course_key} {safe_title}"
        course_dir.mkdir(parents=True, exist_ok=True)

        # Normalise to parts list
        parts = course_data.get("parts") or []
        top_lessons = course_data.get("lessons") or []
        if not parts and top_lessons:
            parts = [{"key": "", "title": course_title, "lessons": top_lessons}]
            print(f"📚 Course: {course_title} (simple course)")
            print(f"📄 Found {len(top_lessons)} lessons")
        else:
            total_lessons = sum(len(p.get("lessons", [])) for p in parts)
            print(f"📚 Nanodegree: {course_title}")
            print(f"📁 Found {len(parts)} parts, {total_lessons} lessons")

        # Save metadata
        metadata = {
            "course_key": course_key,
            "title": course_title,
            "version": version,
            "parts_count": len(parts),
            "download_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (course_dir / "course_metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        total_lessons = 0
        total_concepts = 0
        total_downloads = 0

        for part_idx, part in enumerate(parts, 1):
            part_title = part.get("title", "Untitled Part")
            lessons = part.get("lessons") or []
            print(f"\n📖 Part {part_idx}: {part_title} ({len(lessons)} lessons)")

            safe_part = self._sanitize_filename(part_title)
            part_dir = (course_dir / f"{part_idx:02d} {safe_part}") if len(parts) > 1 else course_dir

            for lesson_idx, lesson in enumerate(lessons, 1):
                lesson_title = lesson.get("title", "Untitled Lesson")
                concepts = lesson.get("concepts") or []
                resources = lesson.get("resources") or []
                print(f"  📄 {lesson_idx}. {lesson_title} ({len(concepts)} concepts, {len(resources)} resources)")
                total_lessons += 1

                safe_lesson = self._sanitize_filename(lesson_title)
                lesson_dir = part_dir / f"{lesson_idx:02d} {safe_lesson}"
                lesson_dir.mkdir(parents=True, exist_ok=True)

                lesson_meta = {
                    "lesson_key": lesson.get("key", ""),
                    "title": lesson_title,
                    "part_title": part_title,
                    "concepts_count": len(concepts),
                    "resources_count": len(resources),
                }
                (lesson_dir / "lesson_metadata.json").write_text(
                    json.dumps(lesson_meta, indent=2), encoding="utf-8"
                )

                total_downloads += self._process_lesson_resources(resources, lesson_dir, lesson_title)
                total_concepts += self._save_concept_content(concepts, lesson_dir)

        print(f"\n🎉 Course {course_key} download completed!")
        print(f"📊 Summary:")
        print(f"  - Parts: {len(parts)}")
        print(f"  - Lessons: {total_lessons}")
        print(f"  - Concepts saved: {total_concepts}")
        print(f"  - Resource files: {total_downloads}")
        logger.info("Course download completed: %s", course_key)
        return True


# ======================================================================
# CLI
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Download Udacity courses via the classroom-content GraphQL API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python download.py nd123 --token YOUR_JWT_TOKEN
  UDACITY_TOKEN=token python download.py nd123 nd456
  python download.py ud777 --output-dir ./downloads --rate-limit 2.0
""",
    )

    parser.add_argument("courses", nargs="+", help="Course keys to download (e.g. nd123, ud777)")
    parser.add_argument("--token", help="JWT token (or set UDACITY_TOKEN env var)")
    parser.add_argument("--output-dir", default="output", help="Output directory (default: output)")
    parser.add_argument("--rate-limit", type=float, default=1.5, help="Seconds between requests (default: 1.5)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    token = args.token or os.getenv("UDACITY_TOKEN")
    if not token:
        print("❌ Error: JWT token required. Use --token or set UDACITY_TOKEN env var.")
        print("💡 Get your token from browser DevTools → Application → Cookies → _jwt")
        sys.exit(1)

    print("🚀 Udacity Course Downloader (GraphQL API)")
    print(f"📁 Output directory: {args.output_dir}")
    print(f"⏱️  Rate limit: {args.rate_limit}s")
    print(f"🎯 Courses: {', '.join(args.courses)}")

    downloader = UdacityDownloader(token=token, output_dir=args.output_dir, rate_limit=args.rate_limit)

    success = 0
    for key in args.courses:
        try:
            if downloader.download_course(key):
                success += 1
        except KeyboardInterrupt:
            print("\n⏹️  Interrupted by user")
            break
        except Exception as exc:
            print(f"❌ Error downloading {key}: {exc}")
            logger.exception("Error downloading %s", key)

    print(f"\n📊 Result: {success}/{len(args.courses)} courses successful")
    if success == len(args.courses):
        print("🎉 All downloads completed!")
    elif success > 0:
        print("⚠️  Some downloads failed.")
    else:
        print("❌ All downloads failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
