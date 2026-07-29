# xhs-mcp

简体中文 | [English](./README.en.md)

`xhs-mcp` 提供统一的命令行入口 `xhs-mcp`，并内置 MCP 服务器子命令。用于小红书（xiaohongshu.com）的 Model Context Protocol（MCP）服务器与 CLI 工具，支持登录、发布、搜索、推荐等自动化能力（基于 Python + [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) 隐身 Chromium）。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 本项目由原 TypeScript + Puppeteer 版本重写而来，**完整保留了原有的全部功能**：相同的 CLI 子命令与参数、相同的 MCP 工具名与 JSON Schema、相同的资源 URI、相同的输出 JSON 结构，以及相同的 cookies 文件格式（`~/.xhs-mcp/cookies.json`，两版可互换使用）。

## 📦 安装

- 包名: `xhs-mcp`
- 运行 CLI（推荐）: `uvx xhs-mcp <subcommand>`
- 启动 MCP：`uvx xhs-mcp mcp [--mode stdio|http] [--port 3000]`

```bash
pip install xhs-mcp
# 或
uv tool install xhs-mcp
```

要求 Python >= 3.10。

## ✨ 功能

- 认证：登录、登出、状态检查
- 发布：图文和视频发布
  - **图文发布**：标题≤20字符（40显示单位）、内容≤1000、最多18图
  - **视频发布**：支持 MP4、MOV、AVI、MKV、WebM、FLV、WMV 格式
  - ⭐ 支持图片 URL 自动下载（HTTP/HTTPS）
  - ⭐ 标题宽度精确验证（CJK字符2单位，ASCII字符1单位）
  - 支持本地图片路径
  - 支持 URL 和本地路径混合使用
  - 智能缓存机制，避免重复下载
- 发现：推荐、搜索、详情、评论
- 用户笔记：列表查看、删除管理
- 自动化：**CloakBrowser 驱动（源码级隐身补丁 Chromium）**、无头模式、Cookie 管理
- 验证：发布功能验证脚本，支持 HTML 报告生成

## 📋 可用工具

- `xhs_auth_login`、`xhs_auth_logout`、`xhs_auth_status`
- `xhs_discover_feeds`、`xhs_search_note`、`xhs_get_note_detail`
- `xhs_comment_on_note`
- `xhs_get_user_notes`、`xhs_delete_note`（用户笔记管理）
- `xhs_publish_content`（统一发布接口：`type`、`title`、`content`、`media_paths`、`tags`）
  - **图片发布**：1-18个图片文件或URL
  - **视频发布**：恰好1个视频文件
  - **混合使用**：支持图片URL和本地路径混合

## 🚀 快速开始（MCP）

### Stdio 模式（默认）

```bash
uvx xhs-mcp mcp

# 调试日志
XHS_ENABLE_LOGGING=true uvx xhs-mcp mcp
```

> 首次运行提示：如果未下载 CloakBrowser 的隐身 Chromium，先执行
>
> ```bash
> xhs-mcp browser    # 自动检查并下载 Chromium（约 200MB），显示可执行路径
> ```
>
> 输出示例：
> ```json
> {
>   "success": true,
>   "message": "Chromium is ready",
>   "data": {
>     "installed": true,
>     "executablePath": "/path/to/chromium"
>   }
> }
> ```

验证 MCP 连接：

```bash
echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' | uvx xhs-mcp mcp
```

### HTTP 模式

```bash
# 启动 HTTP 服务器（默认端口 3000）
xhs-mcp mcp --mode http

# 指定端口
xhs-mcp mcp --mode http --port 8080

# 调试模式
XHS_ENABLE_LOGGING=true xhs-mcp mcp --mode http
```

HTTP 服务器支持：
- **Streamable HTTP** (协议版本 2025-03-26) - 端点：`/mcp`
- **SSE** (协议版本 2024-11-05) - 端点：`/sse` 和 `/messages`
- **健康检查** - 端点：`/health`

详细文档请参考：[HTTP Transports](./docs/HTTP_TRANSPORTS.md)

## 🧰 CLI 子命令

```bash
# 认证
xhs-mcp login --timeout 120
xhs-mcp logout
xhs-mcp status

# 浏览器依赖
xhs-mcp browser [--with-deps]  # 检查并下载 Chromium，显示可执行路径

# 发现与检索
xhs-mcp feeds [-b /path/to/chromium]
xhs-mcp search -k 关键字 [-b /path/to/chromium]

# 当前用户笔记
xhs-mcp usernote list [-l 20] [--cursor <cursor>] [-b /path/to/chromium]

# 删除用户笔记
xhs-mcp usernote delete --note-id <id> [-b /path/to/chromium]
xhs-mcp usernote delete --last-published [-b /path/to/chromium]

# 互动
xhs-mcp comment --feed-id <id> --xsec-token <token> -n "Nice!" [-b /path/to/chromium]

# 发布
# 使用本地图片
xhs-mcp publish --type image --title 标题 --content 内容 -m path1.jpg,path2.png --tags a,b

# ⭐ 使用图片 URL（自动下载）
xhs-mcp publish --type image --title 标题 --content 内容 -m "https://example.com/img1.jpg,https://example.com/img2.png" --tags a,b

# 混合使用 URL 和本地路径
xhs-mcp publish --type image --title 标题 --content 内容 -m "https://example.com/img1.jpg,./local/img2.jpg" --tags a,b

# 发布视频
xhs-mcp publish --type video --title 视频标题 --content 视频描述 -m path/to/video.mp4 --tags a,b

# 查看可用工具
xhs-mcp tools [--detailed] [--json]

# 启动 MCP
xhs-mcp mcp [--mode stdio|http] [--port 3000]
```

## 🔧 客户端接入（Cursor）

### Stdio 模式

`.cursor/mcp.json`：

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

### HTTP 模式

`.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "xhs-mcp-http": {
      "command": "uvx",
      "args": ["xhs-mcp", "mcp", "--mode", "http", "--port", "3000"],
      "env": { "XHS_ENABLE_LOGGING": "true" }
    }
  }
}
```

或者使用 HTTP 客户端直接连接：

```json
{
  "mcpServers": {
    "xhs-mcp-http": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

## ⚙️ 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `XHS_ENABLE_LOGGING` | `false` | 设为 `true` 时向 stderr 输出调试日志 |
| `XHS_HEADLESS` | `true` | 默认无头模式 |
| `XHS_BROWSER_TIMEOUT` | `30000` | 浏览器默认超时（毫秒） |
| `XHS_LOGIN_TIMEOUT` | `300` | 登录超时（秒） |
| `XHS_SERVER_NAME` | `xhs-mcp` | MCP 服务器名称 |
| `XHS_HOST` | `127.0.0.1` | 默认主机 |
| `XHS_PORT` | `8000` | 默认端口 |
| `XHS_LOG_LEVEL` | `INFO` | 日志级别 |
| `XHS_LOG_FILE` | `false` | 是否写入日志文件 |
| `XHS_BROWSER_ARGS` | 空 | 追加的 Chromium 参数（逗号分隔），如 `--no-sandbox` |
| `XHS_USER_DATA_DIR` | 空 | 设为一个目录即启用**持久化 profile 模式**，见下 |

### 🔐 登录态的两种保存方式

**默认（cookie 文件模式）**：每次启动都是全新的无痕浏览器，登录态存在 `~/.xhs-mcp/cookies.json`，下次运行再注入回去。

**持久化 profile 模式**（推荐，设 `XHS_USER_DATA_DIR` 即启用）：

```bash
export XHS_USER_DATA_DIR=~/.xhs-mcp/profile
xhs-mcp login      # 扫一次码
xhs-mcp status     # 之后直接复用，无需再扫
```

用真实的 Chromium 用户目录，cookie / localStorage / IndexedDB 全部自动保留。

| | cookie 文件（默认） | 持久化 profile |
| --- | --- | --- |
| 反检测 | 每次都是全新无痕环境 | **更像真人**，可绕过无痕检测 |
| 保存范围 | 仅 cookie | cookie + localStorage + IndexedDB |
| 体积 | 几 KB | 约 10-50 MB |
| 与 TS 版 cookies.json 互换 | ✅ | ✅（首次启动会自动从 cookies.json 迁移） |
| 并发 | 可多进程共用 | 同一目录同时只能被一个进程打开 |

说明：
- 首次启用时，若已有 `cookies.json`，会自动导入到新 profile，**无需重新登录**。
- profile 已有 cookie 后就以 profile 为准，不再从文件覆盖（避免用过期数据盖掉浏览器刷新过的 cookie）。
- `xhs-mcp logout` 会**同时删除** cookies.json 和 profile 目录；为防误删，只会删除带 `.xhs-mcp-profile` 标记文件的目录（该文件由本工具创建）。
- 多个进程并发时，请给每个进程分配不同的 `XHS_USER_DATA_DIR`。

## ⚠️ 注意事项

- **图文发布**：标题≤20、内容≤1000、图片≤18
- **视频发布**：支持多种格式，文件大小建议≤500MB
- 避免同账号多端同时网页登录
- 合理控制发帖频率
- 图片 URL 自动下载到 `./temp_images/` 目录（自动缓存）
- 图片 URL 支持格式：JPEG、PNG、GIF、WebP、BMP
- **`-b/--browser-path` / `browser_path` 参数保留但不生效**：CloakBrowser 始终使用自带的隐身 Chromium，指向普通 Chrome 会破坏其指纹补丁。详见 [移植说明](./docs/PORTING_NOTES.md)。

## 📖 文档和示例

### 📚 文档
- [完整使用指南](./docs/USAGE_GUIDE.md) - 详细的使用说明和最佳实践
- [HTTP 传输文档](./docs/HTTP_TRANSPORTS.md) - HTTP/SSE 模式配置
- [移植说明](./docs/PORTING_NOTES.md) - 从 TypeScript/Puppeteer 到 Python/CloakBrowser 的对照

### 🧪 测试
- 运行所有测试：`pytest`
- **验证脚本**: `python scripts/cli_validation.py` - 发布功能验证测试，生成 HTML 报告

## 🛠️ 开发

```bash
uv venv
uv pip install -e ".[dev]"
pytest
ruff check src tests
```

## 🙏 致谢

基于 [xhs-mcp](https://github.com/Algovate/xhs-mcp)（TypeScript + Puppeteer）重写为 Python + CloakBrowser；原项目基于 [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)。
