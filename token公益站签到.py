#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
多站点签到脚本（单文件内置配置版）

说明：
1. 不依赖 HAR
2. 所有站点信息直接写在 SITES 里
3. 支持：
   - new-api-user
   - Authorization: Bearer token
   - Cookie
   - 自定义 headers
4. 适配这类接口：
   - POST /api/user/checkin
   - GET  /api/user/checkin?month=YYYY-MM

安装依赖：
    pip install requests

用法：
    python checkin_all_in_one_v2.py
    python checkin_all_in_one_v2.py --list
    python checkin_all_in_one_v2.py --site vvcode.top
    python checkin_all_in_one_v2.py --status
    python checkin_all_in_one_v2.py --status --month 2026-03
    python checkin_all_in_one_v2.py --json

注意：
1. 401 “未登录且未提供 access token” 说明现在不能只靠 new-api-user，必须补 token 或 cookie。
2. 某些站点如果上了 Cloudflare（比如你贴出来那个 403 challenge 页面），纯 requests 可能过不去，
   需要浏览器里的有效 Cookie，甚至要改成 Playwright/Selenium。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests


DEFAULT_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)


@dataclass
class Site:
    name: str
    base_url: str
    user_id: str

    # 二选一或同时用：
    token: str = ""         # 只填 token 本体，不要带 "Bearer "
    cookie: str = ""        # 直接填完整 Cookie 字符串

    # 可选自定义
    enabled: bool = True
    extra_headers: Dict[str, str] = field(default_factory=dict)

    # 如有特殊接口可单独改
    checkin_path: str = "/api/user/checkin"
    status_path: str = "/api/user/checkin"


# ---------------------------
# 在这里填你的站点配置
# ---------------------------
SITES: List[Site] = [
    Site(
        name="newapi.sorai.me",
        base_url="https://newapi.sorai.me",
        user_id="<SENSITIVE>",
        token="",   # 例如：eyJhbGciOi...
        cookie='<SENSITIVE>',  # 例如：session=xxx; other=yyy
    ),
    Site(
        name="vvcode.top",
        base_url="https://vvcode.top",
        user_id="<SENSITIVE>",
        token="",
        cookie='<SENSITIVE>',
    ),
    Site(
        name="linuxdoapi.223384.xyz",
        base_url="https://linuxdoapi.223384.xyz",
        user_id="<SENSITIVE>",
        token="",
        cookie='wzhteam_consent={"QUQf":true}; session=MTc3MjQzNjg3OHxEWDhFQVFMX2dBQUJFQUVRQUFEX3hQLUFBQVlHYzNSeWFXNW5EQWNBQldkeWIzVndCbk4wY21sdVp3d0pBQWRrWldaaGRXeDBCbk4wY21sdVp3d05BQXR2WVhWMGFGOXpkR0YwWlFaemRISnBibWNNRGdBTWExQmxjbVZNZDBOdFJFWkRCbk4wY21sdVp3d0VBQUpwWkFOcGJuUUVCQUQtTkRZR2MzUnlhVzVuREFvQUNIVnpaWEp1WVcxbEJuTjBjbWx1Wnd3T0FBeHNhVzUxZUdSdlh6WTJPRE1HYzNSeWFXNW5EQVlBQkhKdmJHVURhVzUwQkFJQUFnWnpkSEpwYm1jTUNBQUdjM1JoZEhWekEybHVkQVFDQUFJPXxmQ7PEjXDzM6JP9tp4JbQMxp_6lqpLMdzN6plYW37p2w==',
    ),
    Site(
        name="elysiver.h-e.top",
        base_url="https://elysiver.h-e.top",
        user_id="<SENSITIVE>",
        token="",
        cookie='<SENSITIVE>',  # 如果有 Cloudflare，通常这里可能需要带 cf_clearance 等 Cookie
    ),
    Site(
        name="newapi.sorai.me",
        base_url="https://newapi.sorai.me",
        user_id="<SENSITIVE>",
        token="",
        cookie='<SENSITIVE>',  # 如果有 Cloudflare，通常这里可能需要带 cf_clearance 等 Cookie
    ),
    Site(
        name="codex.hyw.me",
        base_url="https://newapi.sorai.me",
        user_id="<SENSITIVE>",
        token="",
        cookie='<SENSITIVE>',  # 如果有 Cloudflare，通常这里可能需要带 cf_clearance 等 Cookie
    ),
]


class CheckinClient:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT, verify_ssl: bool = True):
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.headers.update(
            {
                "accept": "application/json, text/plain, */*",
                "cache-control": "no-store",
                "pragma": "no-cache",
                "user-agent": USER_AGENT,
            }
        )

    def _make_headers(self, site: Site) -> Dict[str, str]:
        headers = {
            "accept": "application/json, text/plain, */*",
            "cache-control": "no-store",
            "pragma": "no-cache",
            "user-agent": USER_AGENT,
            "origin": site.base_url,
            "referer": f"{site.base_url}/console/personal",
            "new-api-user": site.user_id,
        }

        if site.token.strip():
            headers["authorization"] = f"Bearer {site.token.strip()}"

        if site.cookie.strip():
            headers["cookie"] = site.cookie.strip()

        if site.extra_headers:
            headers.update(site.extra_headers)

        return headers

    def _safe_json(self, response: requests.Response) -> Dict[str, Any]:
        try:
            data = response.json()
            if isinstance(data, dict):
                return data
            return {"raw": data}
        except Exception:
            text = response.text.strip()
            return {"raw_text": text[:2000]}

    def checkin(self, site: Site) -> Dict[str, Any]:
        url = f"{site.base_url.rstrip('/')}{site.checkin_path}"
        try:
            response = self.session.post(
                url,
                headers=self._make_headers(site),
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            payload = self._safe_json(response)
            return {
                "ok": response.ok,
                "site": site.name,
                "action": "checkin",
                "status_code": response.status_code,
                "payload": payload,
            }
        except requests.RequestException as e:
            return {
                "ok": False,
                "site": site.name,
                "action": "checkin",
                "status_code": None,
                "error": str(e),
            }

    def status(self, site: Site, month: str) -> Dict[str, Any]:
        url = f"{site.base_url.rstrip('/')}{site.status_path}"
        try:
            response = self.session.get(
                url,
                params={"month": month},
                headers=self._make_headers(site),
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            payload = self._safe_json(response)
            return {
                "ok": response.ok,
                "site": site.name,
                "action": "status",
                "month": month,
                "status_code": response.status_code,
                "payload": payload,
            }
        except requests.RequestException as e:
            return {
                "ok": False,
                "site": site.name,
                "action": "status",
                "month": month,
                "status_code": None,
                "error": str(e),
            }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="多站点签到脚本（单文件内置配置版）")
    parser.add_argument("--site", action="append", help="只执行指定站点，可重复")
    parser.add_argument("--status", action="store_true", help="签到后查询当月状态")
    parser.add_argument("--month", default=datetime.now().strftime("%Y-%m"), help="月份，例如 2026-03")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="请求超时秒数")
    parser.add_argument("--insecure", action="store_true", help="关闭 SSL 校验")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--list", action="store_true", help="列出内置站点")
    return parser.parse_args()


def select_sites(names: Optional[List[str]]) -> List[Site]:
    enabled = [s for s in SITES if s.enabled]
    if not names:
        return enabled

    wanted = {x.strip().lower() for x in names if x.strip()}
    selected = [s for s in enabled if s.name.lower() in wanted]

    found = {s.name.lower() for s in selected}
    missing = sorted(wanted - found)
    if missing:
        print(f"[WARN] 未找到这些站点：{', '.join(missing)}", file=sys.stderr)

    return selected


def has_auth(site: Site) -> bool:
    return bool(site.token.strip() or site.cookie.strip())


def pretty_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return str(data)


def print_result(result: Dict[str, Any]) -> None:
    site = result.get("site", "unknown")
    action = result.get("action", "unknown")
    status_code = result.get("status_code")
    ok = result.get("ok", False)

    prefix = "[OK]" if ok else "[FAIL]"
    print(f"{prefix} {site} | {action} | HTTP {status_code}")

    if "error" in result:
        print(f"  error: {result['error']}")

    if "payload" in result:
        payload_text = pretty_json(result["payload"]).replace("\n", "\n  ")
        print(f"  payload: {payload_text}")


def print_site_list() -> None:
    print("内置站点：")
    for site in SITES:
        auth_state = []
        if site.token.strip():
            auth_state.append("token")
        if site.cookie.strip():
            auth_state.append("cookie")
        auth_text = "<SENSITIVE>".join(auth_state) if auth_state else "未配置认证"

        print(f"- {site.name}")
        print(f"  base_url: {site.base_url}")
        print(f"  user_id  : {site.user_id}")
        print(f"  auth     : {auth_text}")
        print(f"  enabled  : {site.enabled}")


def main() -> int:
    args = parse_args()

    if args.list:
        print_site_list()
        return 0

    sites = select_sites(args.site)
    if not sites:
        print("没有可执行的站点。")
        return 1

    client = CheckinClient(timeout=args.timeout, verify_ssl=not args.insecure)
    all_results: List[Dict[str, Any]] = []

    for site in sites:
        if not has_auth(site):
            result = {
                "ok": False,
                "site": site.name,
                "action": "checkin",
                "status_code": None,
                "error": "未配置 token 或 cookie。该站当前大概率需要登录态，不能只靠 new-api-user。",
            }
            all_results.append(result)
            if not args.json:
                print_result(result)
                print("-" * 72)
            continue

        checkin_result = client.checkin(site)
        all_results.append(checkin_result)

        if not args.json:
            print_result(checkin_result)
            print("-" * 72)

        if args.status:
            status_result = client.status(site, args.month)
            all_results.append(status_result)
            if not args.json:
                print_result(status_result)
                print("=" * 72)

    if args.json:
        print(pretty_json(all_results))

    failed = [r for r in all_results if not r.get("ok")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())