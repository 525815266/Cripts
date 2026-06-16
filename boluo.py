#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfjiayuan_auto.py
- 从 HAR 中提取到的最新 token 已写入 INITIAL_TOKEN。
- 自动判断 token 是否过期；如提供 WX_LOGIN_CODE 环境变量可自动刷新。
- 观看视频后打印：账号X，本次获取xx，总共xx金币。
"""

import os
import json
import time
import base64
import requests
from datetime import datetime

BASE_URL = "https://jinjuli.sfjiayuan.com"
SIGN_URL = f"{BASE_URL}/api/gold/sign"
WATCH_URL = f"{BASE_URL}/api/gold/watch"
GOLD_LIST_URL = f"{BASE_URL}/api/gold/list"
WX_LOGIN_URL = f"{BASE_URL}/api/index/wx_login_new"

# 直接写入你最新的 JWT（来自 HAR）
INITIAL_TOKEN = "<JWT_TOKEN>"

TOKEN_STORE = "<SENSITIVE>"
ACCOUNT_NAME = "<SENSITIVE>"

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.55(0x1800372b) NetType/4G Language/zh_CN",
    "Referer": "https://servicewechat.com/wx5ad596084809877e/138/page-frame.html",
    "content-type": "application/json",
    "Accept-Encoding": "gzip,compress,br,deflate",
    "Connection": "keep-alive",
}

def load_token():
    if os.path.exists(TOKEN_STORE):
        with open(TOKEN_STORE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"token": INITIAL_TOKEN, "exp": decode_exp_from_jwt(INITIAL_TOKEN)}

def save_token(token: str, exp: int):
    with open(TOKEN_STORE, "w", encoding="utf-8") as f:
        json.dump({"token": token, "exp": exp}, f, ensure_ascii=False, indent=2)

def decode_exp_from_jwt(token: str):
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        return int(payload.get("exp") or 0)
    except Exception:
        return 0

def token_is_valid(exp: int, skew: int = 300):
    if not exp:
        return True
    return time.time() + skew < exp

def try_refresh_token_from_env():
    wx_code = os.environ.get("WX_LOGIN_CODE", "").strip()
    if not wx_code:
        return None
    headers = COMMON_HEADERS.copy()
    headers["token"] = ""
    resp = requests.post(WX_LOGIN_URL, headers=headers, data=json.dumps({"code": wx_code}))
    data = resp.json()
    if data.get("code") == 1 and "data" in data:
        token = data["data"]["token"]
        exp = int(data["data"].get("exp") or decode_exp_from_jwt(token))
        save_token(token, exp)
        print(f"已用 WX_LOGIN_CODE 刷新 token，过期时间：{datetime.fromtimestamp(exp)}")
        return {"token": token, "exp": exp}
    else:
        print(f"刷新 token 失败：{data}")
    return None

def authed_headers(token: str):
    h = COMMON_HEADERS.copy()
    h["token"] = token
    return h

def get_balance(token: str) -> int:
    resp = requests.get(GOLD_LIST_URL, headers=authed_headers(token))
    js = resp.json()
    if js.get("code") == 200:
        return int(js["data"].get("gold", 0))
    elif js.get("code") == 10001:
        raise PermissionError("TOKEN_EXPIRED")
    else:
        raise RuntimeError(f"查询余额失败: {js}")

def guarded_post(url: str, token_state: dict, payload: dict | None = None):
    token = token_state["token"]
    resp = requests.post(url, headers=authed_headers(token), data=json.dumps(payload or {}))
    js = resp.json()
    if js.get("code") == 10001:
        refreshed = try_refresh_token_from_env()
        if not refreshed:
            raise PermissionError("TOKEN_EXPIRED_AND_NO_CODE")
        resp = requests.post(url, headers=authed_headers(refreshed["token"]), data=json.dumps(payload or {}))
        js = resp.json()
        token_state.update(refreshed)
    return js

def do_sign(token_state: dict):
    js = guarded_post(SIGN_URL, token_state, {})
    if js.get("code") in (1, 200):
        print("✅ 签到成功！")
    elif js.get("code") == 10002:
        print("ℹ️ 今日已签到。")
    else:
        print(f"❌ 签到失败：{js}")

def watch_and_report(token_state: dict, times: int = 3, account_name: str = "账号1"):
    for i in range(times):
        try:
            old_bal = get_balance(token_state["token"])
        except PermissionError:
            refreshed = try_refresh_token_from_env()
            if not refreshed:
                print("❌ 查询余额时 token 过期且无 WX_LOGIN_CODE，终止。")
                return
            token_state.update(refreshed)
            old_bal = get_balance(token_state["token"])

        js = guarded_post(WATCH_URL, token_state, {})
        if js.get("code") in (1, 200):
            new_bal = get_balance(token_state["token"])
            delta = new_bal - old_bal
            print(f"✅ {account_name}，第 {i+1} 次：本次获取 {delta}，总共 {new_bal} 金币")
        else:
            print(f"❌ {account_name}，第 {i+1} 次观看失败：{js}")

def main():
    token_state = load_token()

    if not token_is_valid(token_state.get("exp", 0)):
        refreshed = try_refresh_token_from_env()
        if refreshed:
            token_state = refreshed
        else:
            try:
                exp_human = datetime.fromtimestamp(token_state.get("exp", 0))
                print(f"⚠️ 本地 token 可能已过期（exp={exp_human}），未提供 WX_LOGIN_CODE，将尝试直接调用接口。")
            except Exception:
                print("⚠️ 本地 token 可能已过期，未提供 WX_LOGIN_CODE，将尝试直接调用接口。")

    do_sign(token_state)
    watch_and_report(token_state, times=3, account_name=ACCOUNT_NAME)

if __name__ == "__main__":
    main()
