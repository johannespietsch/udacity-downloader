# Udacity Course Downloader (GraphQL API)

> ⚠️ **Legal Disclaimer:** This tool is an independent personal backup utility for enrolled Udacity students. It is **not affiliated with, endorsed by, or associated with Udacity, Inc.** Users are solely responsible for ensuring their use complies with [Udacity's Terms of Use](https://www.udacity.com/legal/terms-of-use) and all applicable laws. **Do not** use this tool to redistribute, sell, or share downloaded content. Only download courses you are actively enrolled in and have paid for.

A Python script to download course content from Udacity's learning platform (`learn.udacity.com`). Uses Udacity's classroom-content GraphQL API to fetch course structure and content directly.

## Features

- ✅ **GraphQL API** — Fetches structured course data directly (no HTML/RSC parsing)
- ✅ **Complete Downloads** — Videos (YouTube links), subtitles, text content, images, resources
- ✅ **Nanodegree & Course Support** — Handles both `nd*` nanodegrees and `ud*/cd*` courses
- ✅ **Concept Content** — Each concept saved as a Markdown file with video links and text
- ✅ **Resumable** — Skips already-downloaded files automatically
- ✅ **Progress Bars** — Real-time download progress with tqdm
- ✅ **Rate Limiting** — Configurable delay between API requests
- ✅ **Organized Output** — Clean folder hierarchy: course → parts → lessons → concepts

## How It Works

1. **Fetch structure** — Queries the GraphQL API for the full course tree (parts → modules → lessons → concepts)
2. **Fetch atoms** — For each concept, fetches its atoms (text, video, image) individually for progress tracking
3. **Save content** — Writes Markdown files for concepts; downloads resource files (ZIPs, images, etc.)

## Requirements

- Python 3.7+
- Active Udacity account with enrolled courses
- JWT authentication token from your browser

## Installation

```bash
pip install -r requirements.txt
```

## Getting Your JWT Token

The script needs the JWT token from your `_jwt` browser cookie.

### Browser DevTools (Recommended)

1. Go to [learn.udacity.com](https://learn.udacity.com) and log in
2. Open DevTools (F12) → **Application** tab → **Cookies** → `learn.udacity.com`
3. Find the `_jwt` cookie and copy its value

### Browser Console

```javascript
console.log(document.cookie.split(';').find(c => c.includes('_jwt')).split('=')[1])
```

## Usage

```bash
# Single course
python download.py nd123 --token YOUR_JWT_TOKEN

# Multiple courses
python download.py nd123 ud777 --token YOUR_JWT_TOKEN

# Using environment variable (recommended)
export UDACITY_TOKEN=your_jwt_token
python download.py nd123 ud777

# All options
python download.py nd123 \
  --token YOUR_TOKEN \
  --output-dir ./downloads \
  --rate-limit 2.0 \
  --debug
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--token` | `$UDACITY_TOKEN` | JWT authentication token |
| `--output-dir` | `output` | Where to save downloads |
| `--rate-limit` | `1.5` | Seconds between API requests |
| `--debug` | off | Verbose logging |

## Output Structure

```
output/
├── nd123 Course_Title/
│   ├── course_metadata.json
│   ├── 01 Part_One/
│   │   ├── 01 Lesson_One/
│   │   │   ├── lesson_metadata.json
│   │   │   ├── 01_First_Concept.md
│   │   │   ├── 02_Second_Concept.md
│   │   │   ├── Videos.zip
│   │   │   └── resources/
│   │   │       └── diagram.png
│   │   └── 02 Lesson_Two/
│   │       └── ...
│   └── 02 Part_Two/
│       └── ...
└── ud777 Another_Course/
    ├── course_metadata.json
    ├── 01 First_Lesson/
    │   ├── 01_Intro.md
    │   └── ...
    └── ...
```

Simple courses (no parts) put lessons directly in the course directory.

## Concept Markdown Format

Each concept file includes:

- **Title** as heading
- **YouTube video links** (🎥) when available
- **Subtitle URLs** (📝 VTT links) when available
- **Text content** from TextAtoms
- **Images** from ImageAtoms (as Markdown image links)

## Resumable Downloads

Safe to re-run — existing files are automatically skipped. This means you can:
- Resume interrupted downloads
- Re-run to check for new content
- Download additional courses without re-downloading

## Troubleshooting

### Token errors
- Make sure you're using the `_jwt` cookie value, not an Authorization header
- Tokens expire — get a fresh one if downloads fail

### Empty course data
- Verify you're enrolled in the course
- Check the course key matches the URL (e.g. `learn.udacity.com/nd123` → key is `nd123`)
- Try `--debug` for detailed API responses

### Rate limiting
- Increase delay: `--rate-limit 3.0`

## Security Notes

- **Keep tokens private** — don't commit them to version control
- **Use env vars** — `UDACITY_TOKEN` is safer than `--token` on the command line
- **Tokens expire** — refresh from your browser periodically
- **Only download enrolled courses** — respect Udacity's terms

## Version History

- **v3.0** — Rewrite using classroom-content GraphQL API (current)
- **v2.0** — RSC backend support (deprecated — Udacity changed their rendering)
- **v1.0** — Original version (deprecated)

## License

MIT License — see [LICENSE](LICENSE) for details.

This license applies to the **tool's source code only**, not to any content downloaded using it. Downloaded course materials remain the intellectual property of Udacity, Inc. and its licensors.

## Legal Notice & Disclaimer

**This tool is not affiliated with, endorsed by, or associated with Udacity, Inc.**

This is an independent personal backup utility. By using this tool, you acknowledge and agree that:

- You are solely responsible for your use of this tool and any content you download
- You will only download courses you are actively enrolled in and have legitimately paid for
- You will not redistribute, sell, rent, publicly display, or share any downloaded content
- You will not use downloaded content for any commercial purpose
- You will comply with [Udacity's Terms of Use](https://www.udacity.com/legal/terms-of-use) and all applicable laws
- The authors of this tool accept no liability for misuse or any consequences arising from use of this tool

Downloaded content is intended for **personal, offline study only** as a backup of materials you already have access to through your paid enrollment.
