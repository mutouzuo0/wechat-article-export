# coding:utf-8
# @author      : 木头左
# @create_time        : 2026/09/12 19:55:47
# @update_time        : 2026/09/12 19:55:47
# @description : 扫描输出目录全部文章 md 的 frontmatter，生成文章目录（两列：发布日期 | 标题链接公众号原文），按时间倒序

import re
from pathlib import Path

SAVE_DIR = Path(r"E:\8.量化\02_ 文章\01_公众号")
TOC = SAVE_DIR / "文章目录.md"


def main():
    rows = []
    for f in SAVE_DIR.glob("*.md"):
        if f.name == "文章目录.md":
            continue
        text = f.read_text(encoding="utf-8")
        src_m = re.search(r"src_url: (\S+)", text)
        title = re.search(r'title: "([^"]+)"', text)
        pub = re.search(r'publish_time: "([^"]+)"', text)
        rows.append({
            "title": title.group(1) if title else f.stem,
            "pub": pub.group(1) if pub else "",
            "src": src_m.group(1) if src_m else "",
            "date": f.stem[:8],  # 文件名日期前缀 YYYYMMDD
        })

    rows.sort(key=lambda r: r["date"], reverse=True)  # 最新在前

    lines = ["# 公众号文章目录", "",
             f"> 共 {len(rows)} 篇，按发布时间倒序。文章名点击跳转公众号原文。", "",
             "| 发布日期 | 文章 |",
             "| --- | --- |"]
    for r in rows:
        pub_date = r["pub"].split(" ")[0] if r["pub"] else r["date"]
        lines.append(f"| {pub_date} | [{r['title']}]({r['src']}) |")

    TOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"目录已生成: {TOC}（{len(rows)} 篇）")


if __name__ == "__main__":
    main()
