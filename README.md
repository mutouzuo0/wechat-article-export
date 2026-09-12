# 微信公众号文章导出工具

把公众号（mp.weixin.qq.com）发布记录里的全部文章批量导出为 **Markdown + 本地图片**。

经生产环境验证：29 页发布记录、422 条记录、去重后 251 篇文章 + 621 张图片，全部落盘并通过完整性校验。

## 功能特性

- **批量导出**：自动翻页抓取发布记录全部页面，一次性导出所有文章
- **图片本地化**：正文图片全部下载到本地 `image/` 目录，以 `文章名_时间戳` 命名，离线可读
- **Markdown 输出**：正文转标准 Markdown，frontmatter 保留 `src_url`（原文链接）、标题、发布时间、作者
- **文件名带日期**：`20260907_文章标题.md`，按发布时间归档一目了然
- **智能去重**：同标题多版本（修改重发）只保留最新一篇
- **断点续传**：中断后重跑自动跳过已下载内容
- **反爬节奏**：固定浏览器 TLS 指纹 + 随机延时 + 周期性长休息，全程温和抓取
- **目录生成**：一键生成 `文章目录.md`（发布日期 + 原文链接，按时间倒序）

## 输出结构

```
输出目录/
├── 文章目录.md                      # 目录：日期 + 原文链接
├── 20260907_文章标题.md
├── 20260904_另一篇文章.md
└── image/
    ├── 文章标题_20260912181033.png
    └── 另一篇文章_20260912181120.jpeg
```

MD 文件开头保留原文信息：

```markdown
---
src_url: https://mp.weixin.qq.com/s/xxxxx
title: "文章标题"
publish_time: "2026-09-07 07:00"
author: "公众号名称"
---
```

## 环境要求

- Python 3.10+
- Chrome 浏览器（本机已安装）
- 微信（用于扫码登录公众号后台，仅需一次）

## 安装

```bash
pip install "scrapling[fetchers]" markdownify
python -m playwright install chromium
```

## 登录态配置（一次性）

公众号后台需要登录。两种方式任选：

### 方式 A：Chrome 配置副本（推荐，无需开放调试端口）

1. **完全关闭** Chrome
2. 复制 Chrome 用户数据到独立目录（Windows 示例，排除缓存减小体积）：

```bat
robocopy "%LOCALAPPDATA%\Google\Chrome\User Data" "E:\chrome_scrapling_profile" /E ^
  /XD Cache "Code Cache" "Service Worker" GrShaderCache GraphiteDawnCache ShaderCache GPUCache Crashpad
```

3. 若复制后无法保持登录，手动补拷两个文件（robocopy 偶尔漏拷）：
   - `User Data\Default\Network\Cookies`
   - `User Data\Local State`
4. 运行 `scripts/wx_login_wait.py`，在弹出的窗口中扫码登录
   登录成功后自动提取 token，登录态保存在配置副本中，之后无需重复扫码

### 方式 B：CDP 调试快捷命令

```bat
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="E:\chrome_scrapling_profile" --no-first-run --no-default-browser-check
```

> Chrome 136+ 禁止在默认配置目录上开调试端口，`--user-data-dir` 不能省。
> 配好后访问 `http://localhost:9222/json/version` 能看到 JSON 即成功。

## 使用步骤

```bash
cd scripts

# ① 登录拿 token（首次或登录过期时；已完成配置 A 的可跳过）
python wx_login_wait.py

# ② 提取发布记录全部文章清单（自动翻页）
python wx_extract_list.py

# ③ 先冒烟测试 1 篇，确认链路正常
python wx_scrape_articles.py smoke

# ④ 全量抓取（支持中断续传，重跑自动跳过已下载）
python wx_scrape_articles.py all

# ⑤ 个别失败的可单独恢复（自动区分可恢复与已删除）
python wx_recover.py

# ⑥ 生成文章目录
python wx_make_toc.py
```

输出目录、Chrome 路径、配置副本路径均在各脚本顶部常量区修改。

## 作为 AI Agent 技能安装

本仓库同时符合 [AgentSkill](https://agentskills.io) 技能规范：`SKILL.md` 封装了完整流程指令与陷阱清单，`scripts/` 为配套脚本。

将仓库克隆到你的 Agent 技能目录即可，例如：

- ZCode：`~/.zcode/skills/wechat-article-export/`
- Claude Code：`~/.claude/skills/wechat-article-export/`

之后 Agent 在处理"导出公众号文章"类任务时会自动加载该技能。

## 已知限制（无法导出的情况）

| 情况 | 表现 | 说明 |
|---|---|---|
| 文章已被删除 | 链接含 `tempkey`，打开提示"该内容已被发布者删除" | 微信服务器上已不存在，无法恢复 |
| 小程序卡片 | 页面提示"微信扫一扫可打开此内容"，无正文 | 不是普通图文文章 |
| 早期临时链接 | 2023 年前后的部分记录存的是临时链接 | 已过期失效 |

`wx_recover.py` 会自动识别以上情况并如实报告，不会误报为成功。

## 实现要点（踩坑总结）

- 公众号后台页面对 headless 浏览器返回错误，需有头模式；且 Playwright 连 CDP 默认创建隔离上下文（无登录 cookie），必须使用真实浏览器上下文
- 正文图片为懒加载（只有 `data-src` 没有 `src`），转 Markdown 前需回填，否则图片链接全部为空
- 图片文件名需去掉半角括号，否则 Markdown 链接会在内部 `)` 处截断
- 全程固定单一浏览器 TLS 指纹不轮换，随机延时 + 周期性长休息，模拟真实阅读节奏

## 免责声明

本工具仅用于**备份自己拥有管理权限的公众号内容**。使用时请遵守微信平台服务条款，控制请求频率，不要用于批量抓取他人内容或任何违规用途。由此产生的一切后果由使用者自行承担。

## License

[MIT](LICENSE)
