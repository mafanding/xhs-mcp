# xhs-mcp

[简体中文](./README.md) | English

`xhs-mcp` provides a unified CLI entry point `xhs-mcp` with a built-in MCP server subcommand. It is a Model Context Protocol (MCP) server and CLI for XiaoHongShu (xiaohongshu.com), supporting login, publishing, search, recommendations and other automation — built on Python + [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) stealth Chromium.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> This project is a rewrite of the original TypeScript + Puppeteer version and **preserves all of its functionality**: identical CLI subcommands and flags, identical MCP tool names and JSON Schemas, identical resource URIs and identical output JSON shapes.
>
> One deliberate difference: **the session is a persistent browser profile rather than `cookies.json`** — the original's inject-cookies-into-a-fresh-incognito-context pattern is a strong automation signal. Existing setups migrate automatically; see the [porting notes](./docs/PORTING_NOTES.md).

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
- Automation: **CloakBrowser (source-level stealth-patched Chromium)**, headless mode, **persistent browser profile for the session**
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
| `XHS_SHARE_BROWSER` | `true` | Allow attaching to a browser another process already runs; `false` makes this process exclusive |
| `XHS_USER_DATA_DIR` | `~/.xhs-mcp/profile` | Browser profile directory holding the session (see below) |

### 🏗 Architecture: entry layer / instance manager / browser layer

```
Entry layer      CLI  ·  MCP stdio  ·  MCP HTTP(SSE)
                            │   (issue requests; never touch a browser)
Instance manager  BrowserSessionManager
                            │   enforces "one profile == one browser instance"
Browser layer     BrowserManager → CloakBrowser + Playwright
```

Entry points never launch a browser; they ask the instance manager for the one
belonging to a profile. It keys instances by profile directory:

- **In-process**: the same profile reuses one instance (reference counted), with tabs running in parallel
- **Cross-process**: Chromium records its debugging port in the profile's `DevToolsActivePort`, so a later process **attaches to the running instance** instead of launching a second one and failing
- **Ownership**: whoever launched it closes it; an attached process only disconnects — so a one-off `xhs-mcp status` can never kill a long-running MCP server's browser
- **Launch races**: when two processes start at once, the loser attaches to the winner rather than erroring

Entry points can therefore come and go without touching this layer, and the
browser layer can assume it is the only instance for that profile.

> To make a process take a browser exclusively, set `XHS_SHARE_BROWSER=false` and give it its own `XHS_USER_DATA_DIR`.

### 🔐 The session lives in a persistent browser profile

Login state is kept in a real Chromium user data directory (`~/.xhs-mcp/profile` by default), so cookies, localStorage and IndexedDB are all managed by the browser itself:

```bash
xhs-mcp login      # scan the QR code once
xhs-mcp status     # reuses the profile, no re-scan
```

**Why not a cookie file**: earlier versions (and the TypeScript original this was ported from) stored the session in `~/.xhs-mcp/cookies.json` and injected it into a fresh incognito-like context on every run. A real user's browser is never a brand-new private window each time — that is a strong automation signal and an easy thing for risk control to flag. **That mode has been removed.**

Notes:
- **Existing installs do not need to log in again**: a legacy `cookies.json` is imported into the profile on first run and then retired — nothing is ever written back to it.
- `xhs-mcp logout` deletes the whole profile directory, but **only when it carries the `.xhs-mcp-profile` marker** this tool writes. If you point `XHS_USER_DATA_DIR` at a real Chrome profile, logout refuses and tells you why.
- **Concurrency**: tabs run in parallel within a process (three tool calls issued at once all succeed, taking about as long as the slowest rather than their sum); across processes the instance manager attaches to the same browser — see the architecture above.
- Expect the profile to be ~10-50 MB.
- `cookieCount` in `xhs://cookies` is read from the on-disk Chromium cookie database. While a browser is running it can read low, because Chromium buffers cookies in memory and flushes periodically; it settles once the browser exits. Informational only.

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
