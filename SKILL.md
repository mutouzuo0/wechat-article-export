---
name: wechat-article-export
description: 导出/备份微信公众号文章为 Markdown + 本地图片。当用户要求抓取公众号文章、导出公众号发布记录、备份公众号内容、把公众号文章转成 md、批量下载文章和图片，或提到 mp.weixin.qq.com、appmsgpublish、发布记录、群发记录时使用本技能。也适用于 web_fetch 拿不到公众号后台数据、需要登录态才能访问的场景。Use for exporting WeChat Official Account (gongzhonghao) articles to Markdown with localized images.
---

<!--
# coding:utf-8
# @author      : 木头左
# @create_time        : 2026/09/12 19:55:47
# @update_time        : 2026/09/12 19:55:47
# @description : 微信公众号文章导出技能——经 251 篇文章生产验证的完整流程：登录态复用、列表翻页、正文抓取、图片本地化、Markdown 落盘
-->

# 微信公众号文章导出

把公众号（mp.weixin.qq.com）发布记录里的全部文章导出为本地 Markdown + 本地图片。
完整流程已在生产环境验证：29 页发布记录、422 条记录、去重后 251 篇文章 + 621 张图片，全部落盘校验通过。

**核心思路**：登录态只用于后台列表页（拿文章 URL 清单）；已发布文章本身是公开页，用纯 HTTP 抓取即可。
能用 API/公开页就不碰渲染页面，把对后台的请求数压到最低。

## 输出约定（用户可指定其他位置）

- MD：`E:\8.量化\02_ 文章\01_公众号\{YYYYMMDD}_{标题}.md`
- 图片：`E:\8.量化\02_ 文章\01_公众号\image\{标题}_{YYYYMMDDHHMMSS}.{ext}`（前缀文章名，后缀时间戳）
- 每篇 md 最前面是 frontmatter，`src_url` 字段排第一（指向公众号原文），另有 title/publish_time/author
- 同标题多版本只保留最新一篇（列表最新在前，取首次出现）

## 脚本（scripts/，按顺序执行）

| 脚本 | 作用 | 依赖登录态 |
|---|---|---|
| `wx_login_wait.py` | 打开有头浏览器等扫码，成功后提取 token 存 `wx_token.txt` | ✓（产生登录态） |
| `wx_extract_list.py` | 翻页抓取发布记录全部页面，输出 `wx_articles.json` | ✓（CDP 或登录态会话） |
| `wx_scrape_articles.py` | 批量抓正文+图片，落盘 md（`smoke`=先抓1篇试链路） | ✗ 纯 HTTP |
| `wx_recover.py` | 恢复失败文章；自动区分"可恢复短链"与"已删除不可恢复" | ✗ 纯 HTTP |
| `wx_make_toc.py` | 生成 `文章目录.md`（发布日期 + 标题链接原文，倒序） | ✗ |

数据文件（`wx_token.txt`、`wx_articles.json`）生成在 scripts/ 目录。输出目录在脚本顶部 `SAVE_DIR` 常量修改。

## 执行流程

### 第 0 步：登录态准备（一次性；已配好则跳过）

公众号后台必须登录。本机已有可用方案（按优先级）：

1. **CDP 快捷命令**（用户已配置）：用户用快捷命令启动带调试端口的 Chrome（配置副本 `E:\chrome_scrapling_profile`，
   含公众号登录态）。先探测 `http://localhost:9222/json/version`，通则走 CDP 路线。
2. **配置副本 + scrapling 会话**（无需 CDP 端口）：
   ```python
   DynamicSession(headless=False, executable_path=r"C:\Users\win10\...\chrome.exe",
                  user_data_dir=r"E:\chrome_scrapling_profile", timeout=60000)
   ```
   制作副本：完全关闭 Chrome → robocopy 复制 User Data（排除 Cache/Code Cache/Service Worker/
   GrShaderCache/GraphiteDawnCache/ShaderCache/GPUCache/Crashpad）→ **手动补拷
   `Default/Network/Cookies` 和 `Local State`**（robocopy 常漏拷 Cookies 这个关键文件）。
3. 都没有 → 跑 `wx_login_wait.py` 让用户扫码（配置副本会记住登录，下次不用再扫）。

**硬性限制**：Chrome 136+ 禁止在默认配置目录开 `--remote-debugging-port`（静默忽略），
所以 CDP 必须配 `--user-data-dir`。用户快捷命令：
```
"C:\Users\win10\AppData\Local\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="E:\chrome_scrapling_profile" --no-first-run --no-default-browser-check
```

### 第 1 步：登录拿 token（`wx_login_wait.py`）

后台所有 URL 都要带 token（如 `token=<你的token>`）。token 从已登录页面的
`window.wx.commonData.data.token` 提取。轮询检测 `location.href` 含 `cgi-bin` 即认为登录成功。
**轮询期间绝不重新导航**（会刷新二维码导致扫码失败），用 `page.evaluate` 只读不跳。

### 第 2 步：提取文章清单（`wx_extract_list.py`）

发布列表 URL：`/cgi-bin/appmsgpublish?sub=list&begin={0,10,20,...}&count=10&token=X&lang=zh_CN`

**必须用原生 Playwright 连 CDP 并取 `browser.contexts[0]`**（真实上下文，带登录 cookie）。
scrapling 的 `DynamicSession(cdp_url=...)` 会创建隔离上下文——没有 cookie，页面一律返回
`系统错误(200004)`。这是本项目最大的坑。

- 列表是 JS 渲染：`wait_for_selector(".weui-desktop-mass-appmsg__title")` 后再提取锚点的 href+title
- 总页数从 `.weui-desktop-pagination__num` 标签取最大数字；begin 按 10 递增翻页，页间随机延时 1.5~2.5s
- 旧记录的文章链接可能是 **tempkey 临时链**（`&tempkey=...`）——已过期不可抓，恢复阶段自动识别跳过

### 第 3 步：批量抓取（`wx_scrape_articles.py`）

先 `smoke`（1 篇）验证链路，再 `all`。要点：

- **已发布文章是公开页**：纯 `Fetcher.get(impersonate="chrome")` 即可，无需登录态
- 解析：标题 `h1#activity-name`（备选 og:title）、时间 `em#publish_time`（备选 `var ct` 时间戳）、
  作者 `id="js_name"`（**是 `<a>` 标签不是 span**）、正文 `div#js_content`
- 文件名：`{YYYYMMDD}_{安全化标题}.md`，日期从 publish_time 归一（兼容 `2026年9月7日` 和 `2026-09-07`）
- frontmatter `src_url` 排第一，用户明确要求过
- 同标题去重保留最新（列表最新在前取首次出现）；按 src_url 断点续传，重跑自动跳过已抓

### 第 4 步：恢复失败项（`wx_recover.py`）

失败分两类，处理方式完全不同：
- **短链限流失败**（status=501/超时）：可恢复，直接重试即可
- **tempkey 临时链**：文章已在微信服务器删除，浏览器打开也显示"该内容已被发布者删除"——**不可恢复**，直接报告跳过
- **小程序卡片页**（页面含"微信扫一扫可打开此内容"、无 js_content div）：不可作为文章抓取，跳过

### 第 5 步：生成目录（`wx_make_toc.py`）

输出 `文章目录.md`：两列表格（发布日期 | 标题链接公众号原文），按发布时间倒序。

## 陷阱清单（每条都实测踩过）

| 陷阱 | 事实 | 正确做法 |
|---|---|---|
| CDP 隔离上下文 | Playwright 连 CDP 后 `new_context()` 无登录 cookie，后台页报 `系统错误(200004)` | 用 `browser.contexts[0]` |
| headless 被拦 | 公众号后台对 headless 返回 200004，有头正常 | 后台页面一律 headless=False |
| img 无 src | 微信 img 只有 `data-src`；markdownify 只认 `src` → 图片链接全空 | 下载后把本地路径回填/插入到 `src` |
| 图片名含半角括号 | 标题如 `(附python代码)`，markdown 链接在内部 `)` 截断 | 图片文件名剥掉 `(` `)`（md 文件名可保留） |
| `page.body` 是 bytes | 直接正则会报 TypeError | 先 `.decode("utf-8", errors="replace")` |
| `css_first` 不存在 | scrapling 0.4.15 无此方法 | `page.css('sel::text').get()` |
| API 分页参数 | 放 JSON body → 400 | 放 URL 查询串 `?limit=100&offset=0` |
| `parentDocumentId` 类型 | 传页面短 id → 400 | 传 UUID（树节点 `id` 字段） |
| Chrome 136+ CDP 限制 | 默认配置目录开调试端口被静默忽略 | 必须配 `--user-data-dir` |
| 配置副本漏 Cookies | robocopy 常漏拷 `Default/Network/Cookies`（1.2MB 关键文件） | 复制后手动补拷 Cookies + Local State |
| 同秒图片重名 | 多张图片同一秒下载 | 文件名冲突时自动加 `_2` `_3` 序号 |
| 旧记录临时链 | 2023 年前后的记录存 `tempkey` 链接，已过期且文章多已删除 | 恢复阶段识别跳过，如实报告 |

## 反爬节奏

- 全程固定单一 `impersonate="chrome"` TLS 指纹（不轮换，同会话指纹跳变反而是机器人特征）
- 文章间隔 1.5~2.5s、图片间隔 0.3~0.8s 随机延时；每 10~18 篇插入 15~40s"阅读休息"
- 403/429/503 视为反爬信号：全局冷却 60s 起指数翻倍，连续命中主动中止保护 IP（大批量时启用）
- 尊重内容版权：仅导出用户自己拥有/获授权的公众号内容
