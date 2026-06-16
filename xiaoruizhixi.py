#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
由 HAR 自动生成的签到脚本（直接使用你抓包中的参数）。
仅在你**拥有或被授权的账户/服务**上使用。请遵循服务条款与当地法律法规。
"""
import requests

URL = "https://app.xiaoruizhixi.com.cn/vv/signin/api/index/signin?token=9c4d1c35-ed64-4fe3-b3fb-e96bcdb41073"
METHOD = "GET"

# 直接采用 HAR 中的请求头（已过滤常见无用/冲突项，如 Content-Length/Host）
HEADERS = {
    "content-type": "application/json",
"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.64(0x1800402b) NetType/WIFI Language/zh_CN",
"Referer": "https://servicewechat.com/wx875e875866201462/199/page-frame.html"
}

# 根据 HAR 判定的请求体类型：raw
FORM_DATA = {}
JSON_DATA = None
RAW_DATA = ""

def main():
    session = requests.Session()
    if METHOD in ("POST","PUT","PATCH"):
        if JSON_DATA is not None and JSON_DATA != None:
            resp = session.request(METHOD, URL, headers=HEADERS, json=JSON_DATA, timeout=30)
        elif FORM_DATA:
            resp = session.request(METHOD, URL, headers=HEADERS, data=FORM_DATA, timeout=30)
        elif RAW_DATA is not None:
            resp = session.request(METHOD, URL, headers=HEADERS, data=RAW_DATA, timeout=30)
        else:
            resp = session.request(METHOD, URL, headers=HEADERS, timeout=30)
    else:
        resp = session.request(METHOD, URL, headers=HEADERS, timeout=30)

    print("Status:", resp.status_code)
    print("Response (first 1000 chars):\n", resp.text[:1000])

if __name__ == "__main__":
    main()
