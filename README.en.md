# xhs-mcp

[简体中文](./README.md) | English

`xhs-mcp` provides a unified CLI entry point `xhs-mcp` with a built-in MCP server subcommand. It is a Model Context Protocol (MCP) server and CLI for XiaoHongShu (xiaohongshu.com), supporting login, publishing, search, recommendations and other automation — built on Python + [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) stealth Chromium.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> This project is a rewrite of the original TypeScript + Puppeteer version and **preserves all of its functionality**: identical CLI subcommands and flags, identical MCP tool names and JSON Schemas, identical resource URIs, identical output JSON shapes, and an identical cookie file format (`~/.xhs-mcp/cookies.json`, interchangeable between versions).

## 📦 Install

```bash
pip install xhs-mcp
# or
uv tool install xhs-mcp
```

Requires Python >= 3.10.

## ✨ Features

- Authentication: login, logout, status check
- Publishing: images and videos
  - **Image posts**: title ≤ 20 characters (40 display units), content ≤ 1000, up to 18 images
  - **Video posts**: MP4, MOV, AVI, MKV, WebM, FLV, WMV
  - ⭐ Automatic image download from HTTP/HTTPS URLs
  - ⭐ Precise title width validation (CJK 2 units, ASCII 1 unit)
  - Local image paths supported
  - URLs and local paths can be mixed
  - Smart caching avoids re-downloading
- Discovery: recommendations, search, detail, comments
- User notes: list and delete
- Automation: **CloakBrowser (source-level stealth-patched Chromium)**, headless mode, cookie management
- Validation: publishing validation script with HTML report

## 📋 Available Tools

- `xhs_auth_login`, `xhs_auth_logout`, `xhs_auth_status`
- `xhs_discover_feeds`, `xhs_search_note`, `xhs_get_note_detail`
- `xhs_comment_on_note`
- `xhs_get_user_notes`, `xhs_delete_note`
- `xhs_publish_content` (unified: `type`, `title`, `content`, `media_paths`, `tags`)

## 🚀 Quick Start (MCP)

### Stdio mode (default)

```bash
uvx xhs-mcp mcp

# with debug logging
XHS_ENABLE_LOGGING=true uvx xhs-mcp mcp
```

> First run: if the CloakBrowser stealth Chromium has not been downloaded yet, run
>
> ```bash
> xhs-mcp browser    # checks and downloads Chromium (~200MB), prints the executable path
> ```

Verify the MCP connection:

```bash
echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' | uvx xhs-mcp mcp
```

### HTTP mode

```bash
xhs-mcp mcp --mode http              # default port 3000
xhs-mcp mcp --mode http --port 8080
```

The HTTP server supports:
- **Streamable HTTP** (protocol version 2025-03-26) — endpoint `/mcp`
- **SSE** (protocol version 2024-11-05) — endpoints `/sse` and `/messages`
- **Health check** — endpoint `/health`

See [HTTP Transports](./docs/HTTP_TRANSPORTS.md).

## 🧰 CLI Subcommands

```bash
# Authentication
xhs-mcp login --timeout 120
xhs-mcp logout
xhs-mcp status

# Browser dependency
xhs-mcp browser [--with-deps]

# Discovery
xhs-mcp feeds
xhs-mcp search -k keyword

# Current user's notes
xhs-mcp usernote list [-l 20] [--cursor <cursor>]
xhs-mcp usernote delete --note-id <id>
xhs-mcp usernote delete --last-published

# Interaction
xhs-mcp comment --feed-id <id> --xsec-token <token> -n "Nice!"

# Publishing
xhs-mcp publish --type image --title Title --content Body -m path1.jpg,path2.png --tags a,b
xhs-mcp publish --type image --title Title --content Body -m "https://example.com/img1.jpg,./local/img2.jpg"
xhs-mcp publish --type video --title Title --content Body -m path/to/video.mp4 --tags a,b

# Tooling
xhs-mcp tools [--detailed] [--json]
xhs-mcp mcp [--mode stdio|http] [--port 3000]
```

## 🔧 Client Setup (Cursor)

`.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "xhs-mcp": {
      "command": "uvx",
      "args": ["xhs-mcp", "mcp"],
      "env": { "XHS_ENABLE_LOGGING": "true" }
    }
  }
}
```

## ⚙️ Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `XHS_ENABLE_LOGGING` | `false` | Set to `true` for debug logs on stderr |
| `XHS_HEADLESS` | `true` | Default headless mode |
| `XHS_BROWSER_TIMEOUT` | `30000` | Default browser timeout (ms) |
| `XHS_LOGIN_TIMEOUT` | `300` | Login timeout (seconds) |
| `XHS_SERVER_NAME` | `xhs-mcp` | MCP server name |
| `XHS_HOST` | `127.0.0.1` | Default host |
| `XHS_PORT` | `8000` | Default port |
| `XHS_LOG_LEVEL` | `INFO` | Log level |
| `XHS_LOG_FILE` | `false` | Write logs to a file |
| `XHS_BROWSER_ARGS` | empty | Extra Chromium flags (comma-separated), e.g. `--no-sandbox` |
| `XHS_USER_DATA_DIR` | empty | Set a directory to enable **persistent profile mode** (see below) |

### 🔐 Two ways the session is kept

**Default (cookie file)**: every run starts a fresh, incognito-like browser; the session lives in `~/.xhs-mcp/cookies.json` and is injected back on the next run.

**Persistent profile** (recommended — just set `XHS_USER_DATA_DIR`):

```bash
export XHS_USER_DATA_DIR=~/.xhs-mcp/profile
xhs-mcp login      # scan the QR code once
xhs-mcp status     # reuses the profile, no re-scan
```

Uses a real Chromium user data directory, so cookies, localStorage and IndexedDB all persist.

| | Cookie file (default) | Persistent profile |
| --- | --- | --- |
| Anti-detection | Fresh incognito-like context each run | **Looks more like a real user**; avoids incognito detection |
| Persists | Cookies only | Cookies + localStorage + IndexedDB |
| Size | A few KB | ~10-50 MB |
| Interchangeable with the TS `cookies.json` | ✅ | ✅ (migrates from it on first launch) |
| Concurrency | Shareable across processes | One process per directory |

Notes:
- On first use an existing `cookies.json` is imported into the new profile, so there is **no need to log in again**.
- Once the profile holds cookies it becomes the source of truth; the file no longer overwrites it.
- `xhs-mcp logout` deletes **both** the cookie file and the profile directory — but only if the directory carries the `.xhs-mcp-profile` marker this tool writes, so it can never destroy a real Chrome profile.
- Give each concurrent process its own `XHS_USER_DATA_DIR`.

## ⚠️ Notes

- **Image posts**: title ≤ 20, content ≤ 1000, images ≤ 18
- **Video posts**: several formats; keep files ≤ 500MB
- Avoid signing in to the same account from several web clients at once
- Keep posting frequency reasonable
- Image URLs are downloaded to `./temp_images/` and cached
- Supported URL image formats: JPEG, PNG, GIF, WebP, BMP
- **`-b/--browser-path` / `browser_path` is accepted but has no effect**: CloakBrowser always launches its own stealth Chromium; pointing it at a stock Chrome would defeat the fingerprint patches. See [porting notes](./docs/PORTING_NOTES.md).

## 📖 Documentation

- [Usage Guide](./docs/USAGE_GUIDE.md)
- [HTTP Transports](./docs/HTTP_TRANSPORTS.md)
- [Porting Notes](./docs/PORTING_NOTES.md) — every observable difference from the TypeScript version

## 🛠️ Development

```bash
uv venv
uv pip install -e ".[dev]"
pytest
ruff check src tests
```

## 🙏 Acknowledgements

Rewritten from [xhs-mcp](https://github.com/Algovate/xhs-mcp) (TypeScript + Puppeteer) to Python + CloakBrowser; the original was based on [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp).
