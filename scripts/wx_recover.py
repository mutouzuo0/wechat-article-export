# coding:utf-8
# @author      : 木头左
# @create_time        : 2026/09/12 19:55:47
# @update_time        : 2026/09/12 19:55:47
# @description : 失败文章恢复——自动比对清单与已落盘 md，找出缺失文章；短链限流失败可重试恢复
#                不可恢复的两类（直接报告跳过）：tempkey 临时链（文章已在微信服务器删除）、小程序卡片页
#                用法: python wx_recover.py

import json
import re
import time
from pathlib import Path

import wx_scrape_articles as W

WORK_DIR = Path(__file__).resolve().parent
items = json.loads((WORK_DIR / "wx_articles.json").read_text(encoding="utf-8"))

# 已落盘的 src_url 集合
existing = set()
for f in W.SAVE_DIR.glob("*.md"):
    m = re.search(r"src_url: (\S+)", f.read_text(encoding="utf-8")[:600])
    if m:
        existing.add(m.group(1))

# 缺失 = 清单去重后有 href 无 md 的文章（清单顺序最新在前，同标题取首个）
seen, missing = set(), []
for it in items:
    key = W.normalize_title(it["title"])
    if key in seen:
        continue
    seen.add(key)
    if it["href"] not in existing:
        missing.append(it)

recoverable = [a for a in missing if "tempkey" not in a["href"]]
dead = [a for a in missing if "tempkey" in a["href"]]
print(f"缺失 {len(missing)} 篇: 可恢复(短链) {len(recoverable)} 篇, "
      f"不可恢复(tempkey已删除) {len(dead)} 篇", flush=True)
for a in dead:
    print(f"  [已删除] {W.normalize_title(a['title'])[:50]}", flush=True)

ok = 0
for i, art in enumerate(recoverable, 1):
    print(f"[{i}/{len(recoverable)}] {W.normalize_title(art['title'])[:50]}", flush=True)
    try:
        if W.process_article(art, i, len(recoverable)):
            ok += 1
    except Exception as e:
        print(f"    !! 异常 {type(e).__name__}: {str(e)[:100]}", flush=True)
    time.sleep(2)

print(f"恢复完成: {ok}/{len(recoverable)}", flush=True)
