# 移植说明：TypeScript + Puppeteer → Python + CloakBrowser

本文件记录本次重写中**所有与原实现存在可观察差异的地方**，以及为什么。除此之外的行为均为逐行等价移植。

## 0. 已验证的等价性

| 项目 | 验证方式 | 结果 |
| --- | --- | --- |
| MCP 工具与资源 Schema | 与 TS 源码 `XHS_TOOL_SCHEMAS` / `XHS_RESOURCE_SCHEMAS` 做 JSON 结构对比 | **完全一致** |
| 标题显示宽度算法 | 用真实 npm `string-width@8` 生成 57 条语料的宽度表（含 CJK/emoji/ZWJ/旗帜/组合符/全角/歧义宽度/ANSI） | 整串 57/57、逐码点 331/331 **全部一致** |
| 图片缓存文件名 | 用原 Node 实现生成 hash 文件名表 | **完全一致**（缓存目录跨版本可复用） |
| Cookies 文件格式 | `~/.xhs-mcp/cookies.json`，JSON 数组，同字段 | **可与 TS 版互换** |
| 错误码序列化 | 见下文第 5 节 | **完全一致** |

## 1. `browser_path` 参数不再生效（重要）

原实现把 `executablePath` 传给 `puppeteer.launch()`，支持指定自定义 Chromium。

CloakBrowser 的 `launch()` / `launch_context_async()` **在内部硬编码 `executable_path=<自带的隐身二进制>`**（见 `cloakbrowser/browser.py`），并未暴露该参数；从 `**kwargs` 传入会导致重复关键字错误。更根本的是，指向普通 Chrome 会绕开 CloakBrowser 的 71 处 C++ 层指纹补丁——那正是本次迁移的目的。

**处理方式**：为保持接口兼容，以下位置**全部保留该参数**，但传入时仅记录一条警告并忽略：

- MCP 工具 Schema 中的 `browser_path`
- CLI 的 `-b, --browser-path`
- 所有 service 方法的 `browser_path` 形参

## 2. Chromium 启动参数

原实现传入 Puppeteer 常见的加固参数：`--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage --disable-accelerated-2d-canvas --no-first-run --no-zygote --disable-gpu`。

其中多项（尤其 `--disable-gpu`、`--no-zygote`）本身就是明显的自动化特征，会抵消 CloakBrowser 的指纹伪装。因此默认改为使用 CloakBrowser 的隐身默认参数（`stealth_args=True`）。

**需要时可通过环境变量追加**（逗号分隔），例如在容器中以 root 运行：

```bash
XHS_BROWSER_ARGS='--no-sandbox,--disable-dev-shm-usage' xhs-mcp status
```

## 3. `browser` 子命令语义

原来是"检查/安装 Puppeteer 的 Chromium"，现在是"检查/下载 CloakBrowser 的隐身 Chromium"（首次约 200MB，缓存在 `~/.cloakbrowser/`）。

输出结构不变：`{"success": true, "message": "Chromium is ready", "data": {"installed": true, "executablePath": "..."}}`。

`--with-deps` 保留但无对应操作——CloakBrowser 的二进制是自包含的。

## 4. `slowmo` 不再生效

`config.browser.slowmo` 在原实现中恒为 `0`，且没有任何环境变量可以修改它。Playwright 的 `slow_mo` 属于 launch 级选项，而 CloakBrowser 的 `launch_context_async()` 只把 `**kwargs` 转发给 `new_context()`，无法传递。字段保留，非零时会记录一条警告。

## 5. 错误码继承（已刻意保留原行为）

原实现中 `AuthenticationError` 向父类传入字面量 `'AuthenticationError'`，而 `LoginTimeoutError` / `LoginFailedError` / `NotLoggedInError` 调用的是三参数的 `super()`，因此**它们序列化出的 `error` 字段都是 `"AuthenticationError"`**，而不是各自的类名。

同理：

| 子类 | 序列化的 `error` |
| --- | --- |
| `BrowserLaunchError` / `BrowserNavigationError` | `BrowserError` |
| `FeedNotFoundError` / `FeedParsingError` | `FeedError` |
| `InvalidImageError` / `PublishFailedError` | `PublishError` |
| `ProfileError` / `NoteParsingError` | `NoteError` |

这是 MCP 返回给客户端的线上格式，**Python 版完整保留**（见 `tests/test_errors.py`）。

## 6. `:contains()` 选择器保持为"死代码"

`shared/selectors.py` 中的 `button:contains("确认")`、`:contains("删除")` 等是 jQuery 语法而非合法 CSS，`querySelector` 与 Playwright 都会抛错。它们在原实现里从未匹配到任何元素——只在所有真实选择器都未命中后才会被访问到，抛出的错误由调用方 `catch` 掉。

**保持原样**。Playwright 支持 `:has-text()`，但改写会让它们开始匹配从未匹配过的元素，从而改变实际点击的按钮。

## 7. `page.evaluate` 保持为 JavaScript

所有 `page.evaluate` 的函数体都原样保留在 `shared/js_snippets.py` 中，而非改写成 Python DOM 操作。这样页面内语义（包括非法选择器如何抛错、DOM 怪癖如何解析）与原实现逐字一致。

**唯一例外**：原实现在三处浏览器端 `catch` 块里调用了 `logger.warn(...)`，但 `logger` 在页面上下文中并不存在，一旦进入该分支只会抛出 `ReferenceError`。移植版把这些调用替换为原本意图的 `continue` / `return null`。这是本次移植中**唯一一处刻意修正的原实现缺陷**。

## 8. 共享 BrowserManager 的 headless 语义（原样保留）

`ToolHandlers` 让所有 service 共用同一个 `BrowserManager`，而 `create_page()` 会缓存浏览器实例：

```python
if self._context is None:
    self._context = await self._launch_context(headless, executable_path)
```

因此**第一次调用决定了整个进程生命周期的 headless 模式**——若先调用 `xhs_auth_status`（headless=True），随后的 `xhs_publish_content`（期望 headed）也会跑在无头模式下。这是原实现的既有行为，已原样保留。CLI 每条命令各自新建 service，不受影响。

## 9. Puppeteer → Playwright API 对照

| Puppeteer | Playwright |
| --- | --- |
| `page.$$(sel)` | `page.query_selector_all(sel)` |
| `page.$x(xpath)` | `page.query_selector_all(f"xpath={xpath}")` |
| `page.setCookie(...)` | `context.add_cookies([...])` |
| `page.cookies()` | `page.context.cookies()` |
| `elementHandle.uploadFile(...)` | `element.set_input_files([...])` |
| `elementHandle.isIntersectingViewport()` | 无等价 API，见下 |
| `waitUntil: 'networkidle0'/'networkidle2'` | `wait_until="networkidle"` |
| `waitForSelector(sel, {visible: false})` | `state="attached"`（Puppeteer 的 `visible:false` 是"存在于 DOM"，不是"隐藏"） |
| `browser.createBrowserContext()` | `browser.new_context()` |

**`isIntersectingViewport` 没有 Playwright 等价物**，且在发布流程中出现约 10 次。不能用 `is_visible()` 替代——后者忽略滚动位置，会让屏幕外元素被判定为可见，从而改变发布流程选中的元素。实现在 `js_snippets.IS_INTERSECTING_VIEWPORT`，用 `getBoundingClientRect()` 与视口尺寸比较。

**Cookie 键过滤**：Puppeteer 写入的 cookie 含 `size` / `session` / `sourceScheme` / `partitionKey` 等字段，Playwright 的 `add_cookies` 会拒绝未知键，因此加载时会过滤到白名单字段；非法的 `sameSite` 值也会被剔除，`expires: -1`（会话 cookie）语义保留。

## 10. SSE 端点的查询参数名

原 Node SDK 的 SSE 传输使用 `/messages?sessionId=<id>`，Python SDK 使用 `/messages?session_id=<id>`。客户端是从 SSE 的 `endpoint` 事件中读取该 URL 的，因此两端自洽、不影响互通。这是 MCP SDK 层面的差异，非本项目代码差异。

## 11. 浏览器连接池

`BrowserPoolService`（原 536 行）在原实现的**所有代码路径中都不可达**：`getBrowserManager(usePool=false)`，且 `ToolHandlers` 与 `BaseService` 都直接构造 `new BrowserManager(config)`。但它属于公开导出接口，因此**已完整移植**（`BrowserPoolService`、`get_browser_pool`、`cleanup_browser_pool`），可通过 `BrowserManager(config, use_pool=True)` 主动启用。

由于 Python 无法在同步构造函数中创建 asyncio 任务，健康检查/清理定时器改为**首次 `acquire_browser()` 时惰性启动**（原实现在构造函数中 `setInterval`）。

**该模块未经实际运行验证**，与原实现的状态一致。

## 12. 依赖版本

针对 `cloakbrowser==0.5.2`、`mcp==2.0.0`、`playwright>=1.40` 开发与测试。MCP SDK 2.0 采用回调式 API（`on_list_tools` / `on_call_tool` …）而非 1.x 的装饰器 API；协议层面对客户端无差异。

## 13. 两处标识字符串

以下两个字段的值随实现语言改变（在 `xhs://config` 与 `xhs://status` 中可见）：

| 字段 | TS | Python |
| --- | --- | --- |
| `framework` | `MCP TypeScript` | `MCP Python` |
| `server.description` | `XiaoHongShu MCP Server - TypeScript Version` | `XiaoHongShu MCP Server - Python Version` |

字段名与结构不变，仅取值反映当前实现。

## 14. `undefined` → 省略键（已对齐）

`JSON.stringify` 会**丢弃**值为 `undefined` 的属性，而 Python 的 `json.dumps` 会输出 `null`。为保持输出结构一致，以下字段在无值时**同样省略该键**（见 `shared/utils.py::omit_none` 与 `tests/test_json_key_omission.py`）：

| 位置 | 省略的键 |
| --- | --- |
| `CookiesInfo`（`xhs://cookies`） | `lastModified` |
| `PublishResult` | `noteId` |
| `LoginResult` / `StatusResult` | `profile` |
| `UserNotesResult` | `nextCursor` |
| CLI `print_error` | `code` |
| CLI `print_success` 包装分支 | `message` |

⚠️ 注意 `DeleteResult.data` 在原实现中是**显式的 `null`**（成功与失败分支都是），必须保留，因此没有采用"统一剔除所有 None"的做法。

## 15. 空 `media_paths` + `type=video`

`validate_required_params` 不会拒绝空数组（TS 同样如此：`[] === ''` 为 false），因此 `{"type":"video","media_paths":[]}` 会走到 `media_paths[0]`。JS 取到 `undefined` 后由 `validateVideoInputs` 抛出 `PublishError("Video path is required")`；Python 直接索引会抛 `IndexError`。已改为传入 `""`，让校验逻辑给出与原实现相同的错误。

## 16. 验证脚本的 HTML 转义

`scripts/cli_validation.py` 在把命令输出写入 HTML 报告时会做 HTML 转义；原 `scripts/cli-validation.js` 直接做字符串插值。报告内容来自本地 CLI 的输出，风险很低，但转义是无损的改进，故予以保留。

## 17. 新增能力：持久化 profile 模式（原实现没有）

原实现只有 cookie 文件一种登录态保存方式。本版新增可选的 `XHS_USER_DATA_DIR`，启用后改用 `launch_persistent_context_async()`，把登录态放在真实的 Chromium 用户目录里。

**默认不启用，不设该变量时行为与原实现完全一致**（包括 `xhs://config` 的 `paths` 仍只有 `appDataDir` / `cookiesFile` 两个键、`logout` 返回值不含 `profileCleared`）。

实测依据（为什么需要两种模式并存）：

- 小红书的关键登录 cookie `web_session` 是**有效期 365 天的持久 cookie**，因此 profile 目录足以保住登录态。
- 但 `unread` / `webBuild` 是**会话 cookie**，Chrome 正常退出即丢弃，profile 也留不住 —— 这类非关键 UI 状态由站点在下次访问时重新下发。
- 因此 profile 模式下仍会继续写 `cookies.json`（保持 `xhs://cookies` 资源与跨版本互换可用），但**只在 profile 为空时**从文件回灌，避免用过期数据覆盖浏览器刷新过的 cookie。

安全设计：`logout` 需要删除 profile 目录（否则删掉 cookies.json 仍是登录状态）。由于该路径来自用户配置，可能被指向真实的 Chrome profile，因此本工具在创建目录时会写入 `.xhs-mcp-profile` 标记文件，**只有带此标记的目录才会被删除**，否则拒绝删除并在返回消息中说明。
