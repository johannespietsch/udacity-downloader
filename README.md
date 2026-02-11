# Udacity Course Downloader (RSC Backend)

A Python script to download course content from Udacity's Next.js learning platform (learn.udacity.com). This version works with Udacity's React Server Components (RSC) backend and properly handles their new authentication and data structure.

## Features

- ✅ **Complete Course Downloads** - Videos, subtitles, course materials, and text content
- ✅ **RSC Backend Support** - Works with Udacity's Next.js React Server Components API
- ✅ **Proper Authentication** - Uses Cookie-based JWT authentication (not Bearer tokens)
- ✅ **Concept Content Extraction** - Downloads lesson text content as markdown files
- ✅ **Resumable Downloads** - Skip already downloaded files
- ✅ **Progress Tracking** - Real-time progress bars with file sizes
- ✅ **Rate Limiting** - Respectful downloading to avoid overwhelming servers
- ✅ **Error Handling** - Graceful retry logic and comprehensive error reporting
- ✅ **Organized Output** - Clean folder structure by course, part, and lesson
- ✅ **Metadata Preservation** - Saves course and lesson metadata as JSON

## How It Works

This downloader works with Udacity's new Next.js backend that uses React Server Components (RSC):

1. **RSC Authentication** - Uses `Cookie: _jwt=TOKEN` instead of `Authorization: Bearer`
2. **RSC Headers** - Sends proper headers like `Accept: text/x-component`, `RSC: 1`
3. **Redirect Following** - Follows RSC redirects to get full course data
4. **Program Tree Parsing** - Extracts course structure from React Query state
5. **Content Extraction** - Parses T-prefixed lines for lesson text content

## Requirements

- Python 3.7+
- Active Udacity account with enrolled courses
- JWT authentication token from your browser cookies

## Installation

1. Clone or download this repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Getting Your JWT Token

**Important:** This script requires the JWT token from your browser **cookies**, not the Authorization header.

### Method 1: Browser Developer Tools (Recommended)

1. **Open your browser** and go to [learn.udacity.com](https://learn.udacity.com)
2. **Log in** to your Udacity account
3. **Open Developer Tools** (F12)
4. **Go to Application tab** (Chrome) or **Storage tab** (Firefox)
5. **Find Cookies** for `learn.udacity.com`
6. **Look for `_jwt` cookie** and copy its value
7. **Use this value** as your token (without any prefix)

### Method 2: Network Tab

1. **Open Developer Tools** (F12) and go to **Network tab**
2. **Refresh the page** on learn.udacity.com
3. **Find any request** to learn.udacity.com
4. **Look at Request Headers** for `Cookie: _jwt=YOUR_TOKEN_HERE`
5. **Copy the token** (everything after `_jwt=`)

### Method 3: Browser Console

Run this in the browser console on learn.udacity.com:
```javascript
console.log(document.cookie.split(';').find(c => c.includes('_jwt')).split('=')[1])
```

## Usage

### Basic Usage

```bash
# Download a single course
python download.py nd123 --token YOUR_JWT_TOKEN

# Download multiple courses
python download.py nd123 nd456 ud789 --token YOUR_JWT_TOKEN
```

### Using Environment Variable

```bash
# Set token as environment variable (recommended for security)
export UDACITY_TOKEN=your_jwt_token_here
python download.py nd123 nd456

# Or inline
UDACITY_TOKEN=your_jwt_token_here python download.py nd123
```

### Advanced Options

```bash
# Custom output directory
python download.py nd123 --output-dir ./my_courses

# Adjust rate limiting (seconds between requests)
python download.py nd123 --rate-limit 2.0

# Enable debug logging
python download.py nd123 --debug

# Full example with all options
python download.py nd123 nd456 \
  --token YOUR_TOKEN \
  --output-dir ./downloads \
  --rate-limit 1.5 \
  --debug
```

## Output Structure

Downloads are organized in the following hierarchical structure:

```
output/
├── nd123/                              # Course key
│   ├── course_metadata.json            # Course information
│   ├── Test-Driven_Development/        # Part folder
│   │   ├── Introduction_to_Testing/    # Lesson folder
│   │   │   ├── lesson_metadata.json    # Lesson information
│   │   │   ├── Videos.zip               # Lesson videos (if available)
│   │   │   ├── Subtitles.zip           # Video subtitles (if available)
│   │   │   ├── concepts/               # Concept text content
│   │   │   │   ├── 01_What_is_Testing.md
│   │   │   │   ├── 02_Testing_Benefits.md
│   │   │   │   └── 03_Testing_Types.md
│   │   │   └── resources/              # Additional resources
│   │   │       ├── image1.jpeg
│   │   │       └── diagram.png
│   │   └── Writing_Tests/              # Another lesson
│   │       └── ...
│   └── AI_Fundamentals/                # Another part
│       └── ...
└── nd456/                              # Another course
    └── ...
```

## What Gets Downloaded

The script downloads and organizes:

- **📹 Video ZIP files** - Complete lesson videos from zips.udacity-data.com
- **📄 Subtitle ZIP files** - Video subtitles in multiple formats
- **🖼️ Images and Resources** - Diagrams, images, and other lesson materials
- **📚 Concept Content** - Lesson text content extracted and saved as Markdown
- **📋 Metadata** - Course and lesson information in JSON format

## Concept Content Extraction

This version properly extracts lesson text content from Udacity's RSC backend:

- Each concept is fetched individually using RSC API calls
- Text content is parsed from T-prefixed lines in RSC responses
- Content is cleaned and saved as properly formatted Markdown files
- Files are numbered sequentially (01_, 02_, etc.) for easy reading

## Resumable Downloads

The script automatically skips files that already exist, making it safe to:
- Resume interrupted downloads
- Re-run the script to check for new content
- Download additional courses without re-downloading existing ones

## Rate Limiting

Default rate limit is 1.5 seconds between requests to be respectful to Udacity's servers. You can adjust this with `--rate-limit`:

- `--rate-limit 1.0` - Faster (1 second between requests)
- `--rate-limit 2.0` - Slower (2 seconds between requests)
- `--rate-limit 3.0` - Very conservative (good for avoiding rate limits)

## Error Handling & Logging

The script includes comprehensive error handling and logging:

- **Console output** - Progress updates and important messages
- **Log file** - Detailed logs saved to `udacity_downloader.log`
- **Debug mode** - Use `--debug` for verbose logging
- **Graceful failures** - Continues with other content if individual items fail

## Finding Course Keys

Course keys are the identifiers in Udacity URLs:

- `https://learn.udacity.com/nd123` → Course key is `nd123`
- `https://learn.udacity.com/c/course-name` → Course key is `course-name`

You can find these by browsing your enrolled courses on learn.udacity.com.

## Security Notes

- **Keep your JWT token secure** - Don't share it or commit it to version control
- **Tokens expire** - You may need to get a new token periodically (usually after a few hours/days)
- **Use environment variables** - Safer than command-line arguments for tokens
- **Only download enrolled courses** - Respect Udacity's terms of service

## Troubleshooting

### "JWT token required" error
- Make sure you're using the cookie JWT token, not the Authorization header
- Check that your token is valid and not expired
- Get a fresh token from your browser cookies

### Downloads failing / Empty course data
- **Token expired** - Get a new JWT token from your browser
- **Not enrolled** - Verify you're enrolled in the course
- **Rate limiting** - Try increasing rate limit: `--rate-limit 3.0`
- **Network issues** - Check your internet connection

### "programTree not found" errors
- The course might use a different data structure
- Try with `--debug` to see detailed RSC responses
- Some courses might not have downloadable content
- Verify the course key is correct

### RSC parsing issues
- Udacity might have changed their RSC format
- Check the log file for detailed error information
- Try a different course to see if it's course-specific

## Technical Details

### RSC (React Server Components) Format

Udacity uses Next.js with React Server Components, which returns data in a special flight format:

- **Request headers**: `Accept: text/x-component`, `RSC: 1`
- **Authentication**: `Cookie: _jwt=TOKEN` (not Bearer tokens)
- **Response format**: Lines like `KEY:VALUE` with embedded JSON
- **Program tree**: Course structure in React Query state under `["programTree"]`
- **Text content**: In T-prefixed lines like `ID:T{hex_length},{markdown_content}`

### Data Extraction Process

1. **Initial RSC request** to course URL
2. **Follow redirects** if NEXT_REDIRECT is found
3. **Parse programTree** from React Query hydration state
4. **Fetch concept content** for each lesson individually
5. **Extract resources** and download URLs from course structure

### URL Patterns

The script recognizes these Udacity domains:

- `https://zips.udacity-data.com/` - Video and subtitle ZIP files
- `https://video.udacity-data.com/` - Video thumbnails and previews  
- `https://s3.amazonaws.com/` - Additional course resources

## Version History

- **v2.0** - Complete rewrite for RSC backend support
- **v1.0** - Original version (deprecated, incompatible with current Udacity)

## Contributing

Feel free to improve the script:

- Add support for more content types
- Improve RSC parsing robustness  
- Add parallel downloads
- Enhance course structure detection

## License

This script is for educational purposes. Respect Udacity's terms of service and only download content you have legitimate access to through your enrollment.

## Disclaimer

This tool is not affiliated with Udacity. Use responsibly and in accordance with Udacity's terms of service. Only download courses you are enrolled in and have permission to access. The RSC format and API endpoints may change, requiring updates to this script.