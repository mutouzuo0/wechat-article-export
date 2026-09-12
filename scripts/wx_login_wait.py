# coding:utf-8
# @author      : 木头左
# @create_time        : 2026/09/12 19:55:47
# @update_time        : 2026/09/12 19:55:47
# @description : 打开公众号登录窗口等待扫码，登录成功后自动提取 token 落盘（轮询不导航，避免二维码失效）
#                依赖：本机 Chrome + 已复制的配置副本（见 SKILL.md 前置条件）

import re
import time
from pathlib import Path

from scrapling.fetchers import DynamicSession

CHROME = r"C:\Users\win10\AppData\Local\Google\Chrome\Application\chrome.exe"
PROFILE = r"E:\chrome_scrapling_profile"      # Chrome 配置副本（含登录态）
WORK_DIR = Path(__file__).resolve().parent
TOKEN_FILE = WORK_DIR / "wx_token.txt"
MAX_WAIT_SECONDS = 600

holder = {}


def page_setup(page):
    """把 playwright 页面对象暴露给主循环，用于无导航轮询"""
    holder["page"] = page


with DynamicSession(headless=False, executable_path=CHROME, user_data_dir=PROFILE,
                    timeout=60000) as session:
    session.fetch("https://mp.weixin.qq.com/", page_setup=page_setup, network_idle=True)
    page = holder["page"]
    print("窗口已打开，请扫码登录...（轮询中，不刷新页面）", flush=True)

    token = None
    start = time.time()
    while time.time() - start < MAX_WAIT_SECONDS:
        time.sleep(5)
        try:
            url = page.evaluate("() => location.href")
        except Exception:
            continue  # 页面短暂跳转中
        if "cgi-bin" not in url:
            continue  # 还在登录页
        # 已进入后台：提取新 token（commonData / 页面源 双路找）
        try:
            token = page.evaluate("() => window.wx.commonData?.data?.token || ''")
        except Exception:
            token = None
        if not token:
            try:
                html = page.content()
                m = (re.search(r'"token"\s*:\s*"?(\d+)"?', html)
                     or re.search(r"token[=:]\s*['\"]?(\d{6,})", html))
                token = m.group(1) if m else None
            except Exception:
                token = None
        if token:
            TOKEN_FILE.write_text(token, encoding="utf-8")
            print(f"LOGIN_OK token={token}", flush=True)
            break
        print(f"  已进入后台但暂未拿到token: {url[:80]}", flush=True)
    else:
        print("LOGIN_TIMEOUT", flush=True)
