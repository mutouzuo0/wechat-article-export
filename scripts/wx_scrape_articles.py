# coding:utf-8
# @author      : 木头左
# @create_time        : 2026/09/12 19:55:47
# @update_time        : 2026/09/12 19:55:47
# @description : 公众号文章批量抓取主脚本——列表去重(同标题保留最新) -> 抓正文 -> 图片本地化 -> Markdown 落盘
#                输出: SAVE_DIR\{YYYYMMDD}_{标题}.md（frontmatter 首字段 src_url）
#                      SAVE_DIR\image\{标题}_{YYYYMMDDHHMMSS}.{ext}（图片名去半角括号，防 markdown 链接断裂）
#                特性: PS尾部截断 + 按 src_url 断点续传 + 指数退避 + 随机限速
#                用法: python wx_scrape_articles.py [smoke|all]；文章清单 wx_articles.json 由 wx_extract_list.py 生成

import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from markdownify import markdownify
from scrapling.fetchers import Fetcher

SAVE_DIR = Path(r"E:\8.量化\02_ 文章\01_公众号")   # 输出目录（按需修改）
IMG_DIR = SAVE_DIR / "image"
WORK_DIR = Path(__file__).resolve().parent
ARTICLES_JSON = WORK_DIR / "wx_articles.json"
ARTICLE_DELAY = (1.5, 2.5)   # 文章间隔（秒）
IMG_DELAY = (0.3, 0.8)       # 图片间隔（秒）
MAX_RETRY = 3

WX_HEADERS = {"Referer": "https://mp.weixin.qq.com/"}
FMT_EXT = {"jpeg": "jpeg", "jpg": "jpg", "png": "png", "gif": "gif",
           "svg": "svg", "webp": "webp", "bmp": "bmp"}


def log(msg):
    print(msg, flush=True)


def polite(rng):
    time.sleep(random.uniform(*rng))


def normalize_title(t):
    return re.sub(r"\s+", " ", str(t).replace("\xa0", " ")).strip()


def sanitize(name, maxlen=80):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", normalize_title(name))
    return name.rstrip(". ")[:maxlen] or "untitled"


def pub_date_prefix(pub_time):
    """发布时间 -> YYYYMMDD 前缀；兼容 '2026年9月7日 07:00' 与 '2026-09-07 07:00'"""
    m = re.search(r"(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})", pub_time or "")
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    return "nodate"


def fetch_page(url):
    """抓文章页（已发布文章是公开页，无需登录；带退避重试）"""
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = Fetcher.get(url, headers=WX_HEADERS, impersonate="chrome", timeout=60)
            html = r.body.decode("utf-8", errors="replace") if isinstance(r.body, bytes) else r.body
            if r.status == 200 and "js_content" in html and "环境异常" not in html:
                return html
            last = f"status={r.status} len={len(html)}"
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:80]}"
        log(f"    ! 第{attempt}次失败: {last}")
        time.sleep(min(2 ** attempt, 10))
    return None


def first_text(html, pattern):
    m = re.search(pattern, html, re.S)
    return m.group(1).strip() if m else ""


def parse_article(html):
    """解析标题/时间/作者/正文HTML"""
    title = (first_text(html, r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>')
             or first_text(html, r'<meta property="og:title" content="([^"]*)"')
             or "untitled")
    title = normalize_title(re.sub(r"<[^>]+>", "", title))

    pub_time = first_text(html, r'<em[^>]*id="publish_time"[^>]*>(.*?)</em>')
    pub_time = normalize_title(re.sub(r"<[^>]+>", "", pub_time))
    if not pub_time:
        m = re.search(r'var\s+ct\s*=\s*"(\d{10})"', html)
        if m:
            pub_time = datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d %H:%M")

    # js_name 是 <a> 或 <span> 标签（公众号名），兼容任意标签
    m = re.search(r'id="js_name"[^>]*>(.*?)</', html, re.S)
    author = normalize_title(re.sub(r"<[^>]+>", "", m.group(1))) if m else ""

    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)\s*</div>\s*\n?\s*<script', html, re.S)
    if not m:
        m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*)', html, re.S)
    body = m.group(1) if m else ""
    # 截断到正文结尾的平衡点：js_content 后通常紧跟富媒体尾部标记
    for endmark in ['id="js_tags"', 'id="content_bottom_area"', 'rich_media_tool']:
        pos = body.find(endmark)
        if pos > 0:
            body = body[:body.rfind("<", 0, pos)]
            break
    return title, pub_time, author, body


def truncate_footer(body):
    """截掉文末固定推广尾部（如 'PS: 源码下载，请移步知识星球！' 及其后的二维码等内容）"""
    pos = body.rfind("源码下载，请移步知识星球")
    if pos == -1:
        return body
    hr = body.rfind("<hr", 0, pos)
    if hr != -1 and pos - hr < 500:
        return body[:hr].rstrip()
    block = max(body.rfind("<p", 0, pos), body.rfind("<section", 0, pos))
    return body[:block] if block != -1 else body


def img_ext(url):
    m = re.search(r"wx_fmt=(\w+)", url)
    return FMT_EXT.get(m.group(1).lower(), "jpg") if m else "jpg"


def download_image(url, base_name, used_names):
    """下载图片为 {文章名}_{时间戳}.{ext}，同秒冲突自动加序号"""
    ext = img_ext(url)
    ts = time.strftime("%Y%m%d%H%M%S")
    name = f"{base_name}_{ts}.{ext}"
    k = 2
    while name in used_names:
        name = f"{base_name}_{ts}_{k}.{ext}"
        k += 1
    dest = IMG_DIR / name
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = Fetcher.get(url, headers=WX_HEADERS, impersonate="chrome", timeout=60)
            if r.status == 200 and len(r.body) > 100:
                dest.write_bytes(r.body)
                used_names.add(name)
                return name
            log(f"    ! 图片 status={r.status}（第{attempt}次）")
        except Exception as e:
            log(f"    ! 图片异常 {type(e).__name__}: {str(e)[:60]}（第{attempt}次）")
        time.sleep(min(2 ** attempt, 8))
    return None


def process_article(art, idx, total):
    url, raw_title = art["href"], art["title"]
    log(f"[{idx}/{total}] {normalize_title(raw_title)[:50]}")
    html = fetch_page(url)
    if not html:
        return None
    title, pub_time, author, body = parse_article(html)
    if not body:
        log("    ! 未解析到正文，跳过")
        return None
    body = truncate_footer(body)
    safe = sanitize(title)
    # 图片名额外去掉半角括号：markdown 链接会在内部 ) 处截断
    img_base = re.sub(r"[()]", "_", safe)
    used = set()

    # ① 图片本地化：data-src/src -> 下载 -> 改写为相对路径
    img_urls = re.findall(r'(?:data-src|src)="(https?://mmbiz\.qpic\.cn/[^"]+)"', body)
    seen = {}
    for iu in dict.fromkeys(img_urls):
        polite(IMG_DELAY)
        name = download_image(iu, img_base, used)
        if name:
            seen[iu] = f"image/{name}"
    body = re.sub(r'(data-src|src)="(https?://mmbiz\.qpic\.cn/[^"]+)"',
                  lambda m: f'{m.group(1)}="{seen.get(m.group(2), m.group(2))}"', body)

    # markdownify 只认 src 属性：微信 img 常常只有 data-src 没有 src，需回填/插入
    def fix_img(m):
        tag = m.group(0)
        ds = re.search(r'data-src="([^"]+)"', tag)
        if ds:
            if re.search(r'\ssrc="', tag):
                tag = re.sub(r'\ssrc="[^"]*"', f' src="{ds.group(1)}"', tag)
            else:
                tag = tag.replace("<img", f'<img src="{ds.group(1)}"', 1)
        return tag
    body = re.sub(r"<img[^>]*>", fix_img, body)
    # 视频/iframe 转链接提示
    body = re.sub(r'<iframe[^>]*data-src="([^"]+)"[^>]*>.*?</iframe>',
                  r'<p>[视频: \1]</p>', body, flags=re.S)
    # 正文 HTML 转 Markdown
    text = markdownify(body, heading_style="ATX", bullets="-")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # ② frontmatter：src_url 排第一
    fm = (f"---\nsrc_url: {url}\ntitle: \"{title}\"\n"
          f"publish_time: \"{pub_time}\"\nauthor: \"{author}\"\n---\n\n"
          f"# {title}\n\n{text}\n")
    dest = SAVE_DIR / f"{pub_date_prefix(pub_time)}_{safe}.md"
    n = 2
    while dest.exists():
        dest = SAVE_DIR / f"{pub_date_prefix(pub_time)}_{safe}_{n}.md"
        n += 1
    dest.write_text(fm, encoding="utf-8")
    log(f"    ✔ {dest.name}（本地图片 {len(seen)}/{len(dict.fromkeys(img_urls))}）")
    return dest


def main(mode="all"):
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    items = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))

    # 同标题仅保留最新一篇（列表顺序最新在前，取首次出现）
    seen, articles = set(), []
    for it in items:
        key = normalize_title(it["title"])
        if key not in seen:
            seen.add(key)
            articles.append(it)
    log(f"清单: {len(items)} 篇 -> 去重后 {len(articles)} 篇")

    # 断点续传：已落盘文章（按 src_url 识别）直接跳过
    existing = set()
    for f in SAVE_DIR.glob("*.md"):
        m = re.search(r"src_url: (\S+)", f.read_text(encoding="utf-8")[:600])
        if m:
            existing.add(m.group(1))
    articles = [a for a in articles if a["href"] not in existing]
    log(f"已有 {len(existing)} 篇，本次待抓 {len(articles)} 篇")

    todo = articles[:1] if mode == "smoke" else articles
    ok, fail = 0, []
    for i, art in enumerate(todo, 1):
        try:
            if process_article(art, i, len(todo)):
                ok += 1
            else:
                fail.append(art["href"])
        except Exception as e:
            log(f"    !! 异常 {type(e).__name__}: {str(e)[:100]}")
            fail.append(art["href"])
        if i < len(todo):
            polite(ARTICLE_DELAY)

    log(f"\n===== 完成: 成功 {ok}/{len(todo)}, 失败 {len(fail)} =====")
    if fail:
        log("失败清单（区分可恢复性见 SKILL.md）:")
        for u in fail:
            log(f"  {u}")
    md_cnt = len(list(SAVE_DIR.glob("*.md")))
    img_cnt = len(list(IMG_DIR.glob("*")))
    log(f"落盘校验: {md_cnt} 个 md, {img_cnt} 张图片")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
