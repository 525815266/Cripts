#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import requests

BASE = "https://mxwljsq.com"

def get_auth():
    auth = os.getenv("MXWL_AUTH", "<SENSITIVE>").strip()
    if not auth or "&" not in auth:
        print("[ERROR] 请设置环境变量 MXWL_AUTH，格式：账号&密码")
        sys.exit(1)
    email, passwd = auth.split("&", 1)
    return email.strip(), passwd.strip()

def pick(html: str, pattern: str, default=None):
    m = re.search(pattern, html, re.S | re.I)
    return m.group(1).strip() if m else default

def parse_user_page(html: str) -> dict:
    left_num = pick(html, r"<h4>\s*剩余流量\s*</h4>.*?<span[^>]*class=['\"]counter['\"][^>]*>\s*([\d.]+)\s*</span>")
    left_unit = pick(html, r"<h4>\s*剩余流量\s*</h4>.*?</span>\s*([A-Z]{1,3})\b")
    days = pick(html, r"<h4>\s*会员时长\s*</h4>.*?<span[^>]*class=['\"]counter['\"][^>]*>\s*(\d+)\s*</span>\s*天")
    expire = pick(html, r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*过期")
    today_used = pick(html, r"今日已用\s*[:：]?\s*([\d.]+\s*[KMG]B)")

    # 统一成“数值 + 单位”方便对比显示
    info = {
        "left_num": float(left_num) if left_num else None,
        "left_unit": left_unit or None,
        "days": int(days) if days else None,
        "expire": expire,
        "today_used": (today_used.replace(" ", "") if today_used else None),
    }
    return info

def login(sess, email, passwd, code=""):
    url = f"{BASE}/auth/login"
    data = {"email": email, "passwd": passwd, "code": code, "remember_me": "on"}
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE,
        "Referer": f"{BASE}/auth/login",
        "User-Agent": "Mozilla/5.0",
    }
    r = sess.post(url, data=data, headers=headers, timeout=20)
    return r.json()

def checkin(sess):
    url = f"{BASE}/user/checkin"
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/user",
        "User-Agent": "Mozilla/5.0",
    }
    r = sess.post(url, headers=headers, timeout=20)
    return r.json()

def fetch_user(sess):
    r = sess.get(f"{BASE}/user", timeout=20)
    r.raise_for_status()
    return r.text

def status_badge(ok: bool, msg: str) -> str:
    return f"{'✅' if ok else '❌'} {msg}"

def checkin_badge(msg: str) -> str:
    m = (msg or "").strip()
    if "已经签到" in m or "已签到" in m:
        return "🟡 已签到（无需重复）"
    if "成功" in m:
        return "✅ 签到成功"
    return f"⚠️ {m}" if m else "⚠️ 未知"

def diff_line(before, after, fmt=str, suffix=""):
    if before is None and after is None:
        return None
    if before is None:
        return f"{fmt(after)}{suffix}"
    if after is None:
        return f"{fmt(before)}{suffix}"

    if before == after:
        return f"{fmt(after)}{suffix}"

    # 尝试做增量显示
    try:
        delta = after - before
        sign = "+" if delta >= 0 else ""
        return f"{fmt(before)}{suffix}  →  {fmt(after)}{suffix} ({sign}{delta:.2f}{suffix.strip()})"
    except Exception:
        return f"{fmt(before)}{suffix}  →  {fmt(after)}{suffix}"

def box_print(title: str, lines: list[str]):
    width = max(len(title), *(len(x) for x in lines)) + 2
    top = f"╔{'═'*width}╗"
    mid = f"╟{'─'*width}╢"
    bot = f"╚{'═'*width}╝"
    print(top)
    print("║ " + title.ljust(width-1) + "║")
    print(mid)
    for ln in lines:
        print("║ " + ln.ljust(width-1) + "║")
    print(bot)

def main():
    email, passwd = get_auth()
    code = os.getenv("MXWL_CODE", "").strip()

    sess = requests.Session()

    # 登录
    ret = login(sess, email, passwd, code)
    login_ok = int(ret.get("ret", 0)) == 1
    login_msg = ret.get("msg") or ("登录成功" if login_ok else "登录失败")
    if not login_ok:
        box_print("MXWL 签到报告", [
            f"账号        : {email}",
            f"登录状态    : {status_badge(False, login_msg)}",
        ])
        sys.exit(1)

    # 签到前
    before = parse_user_page(fetch_user(sess))

    # 签到
    ck = checkin(sess)
    ck_msg = ck.get("msg", "")
    ck_line = checkin_badge(ck_msg)

    # 签到后
    after = parse_user_page(fetch_user(sess))

    # 拼输出行
    left_before = before.get("left_num")
    left_after  = after.get("left_num")
    unit = after.get("left_unit") or before.get("left_unit") or ""
    traffic_line = diff_line(left_before, left_after, fmt=lambda x: f"{x:.2f}", suffix=f" {unit}".rstrip())

    days_line = diff_line(before.get("days"), after.get("days"), fmt=lambda x: f"{x}", suffix=" 天")
    expire_line = after.get("expire") or before.get("expire") or "-"
    used_line = after.get("today_used") or before.get("today_used") or "-"

    lines = [
        f"账号        : {email}",
        f"登录状态    : {status_badge(True, login_msg)}",
        f"签到状态    : {ck_line}",
        "────────────────────────────────────────",
        f"剩余流量     : {traffic_line or '-'}",
        f"今日已用     : {used_line}",
        f"会员剩余天数 : {days_line or '-'}",
        f"到期时间     : {expire_line}",
    ]

    box_print("MXWL 签到报告", lines)

if __name__ == "__main__":
    main()
