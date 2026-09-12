# coding:utf-8
# @author      : 木头左
# @create_time        : 2026/09/12 19:55:47
# @update_time        : 2026/09/12 19:55:47
# @description : 原生 Playwright 连 CDP 取真实上下文（带登录 cookie），翻页抓取公众号发布记录全部页面的文章清单
#                关键点：CDP 隔离上下文没有登录 cookie，必须用 browser.contexts[0]；headless 会被后台拦截

import json
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"                  # 用户 CDP 快捷命令启动的 Chrome
WORK_DIR = Path(__file__).resolve().parent
TOKEN_FILE = WORK_DIR / "wx_token.txt"
OUT_JSON = WORK_DIR / "wx_articles.json"
PAGE_SIZE = 10
MAX_PAGES = 200  # 防御性上限


def page_url(begin, token):
    return (f"https://mp.weixin.qq.com/cgi-bin/appmsgpublish"
            f"?sub=list&begin={begin}&count={PAGE_SIZE}&token={token}&lang=zh_CN")


def extract_items(page):
    return page.eval_on_selector_all(
        "a.weui-desktop-mass-appmsg__title",
        """els => els.map(e => ({
            href: e.href,
            title: e.querySelector('span')?.innerText.trim() || e.innerText.trim()
        }))""")


def main():
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]  # 真实浏览器上下文（含登录态）；browser.new_context() 是隔离的，会 404
        page = ctx.new_page()

        # 第 1 页：渲染并读取总页数
        page.goto(page_url(0, token), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".weui-desktop-mass-appmsg__title", timeout=30000)
        total_pages = page.eval_on_selector_all(
            ".weui-desktop-pagination__num",
            """els => Math.max(0, ...els
                .map(e => parseInt(e.innerText))
                .filter(n => !isNaN(n)))""")
        total_pages = max(total_pages, 1)
        print(f"总页数: {total_pages}", flush=True)

        all_items = extract_items(page)
        print(f"  第 1/{total_pages} 页: {len(all_items)} 篇（累计 {len(all_items)}）", flush=True)

        # 翻页抓取（注意：必须在真实上下文的同一个标签里顺序导航）
        for pg in range(2, min(total_pages, MAX_PAGES) + 1):
            time.sleep(random.uniform(1.5, 2.5))
            page.goto(page_url((pg - 1) * PAGE_SIZE, token),
                      wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector(".weui-desktop-mass-appmsg__title", timeout=15000)
            except Exception:
                print(f"  第 {pg}/{total_pages} 页无内容，停止", flush=True)
                break
            page.wait_for_timeout(1000)
            items = extract_items(page)
            if not items:
                print(f"  第 {pg}/{total_pages} 页为空，停止", flush=True)
                break
            all_items.extend(items)
            print(f"  第 {pg}/{total_pages} 页: {len(items)} 篇（累计 {len(all_items)}）", flush=True)

        page.close()
        browser.close()

    # 同 URL 去重（跨页可能重复）
    dedup = {it["href"]: it for it in all_items}
    items = list(dedup.values())
    OUT_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n全部完成: {len(all_items)} 条记录，去重 URL 后 {len(items)} 篇 -> {OUT_JSON}", flush=True)


if __name__ == "__main__":
    main()
