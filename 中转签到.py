import requests
from datetime import datetime
from urllib.parse import urljoin

# 在这里配置：base 域名 + user_id + cookie / token（二选一或都填）
SITES = [
    {
        "name": "elysiver",
        "base": "https://elysia.h-e.top",
        "user_id": "<SENSITIVE>",
        # 重要：Cloudflare 站点一般必须有 cf_clearance / __cf_bm 等 Cookie
        "cookie": '<SENSITIVE>',
    },
    {
        "name": "linuxdoapi",
        "base": "https://linuxdoapi.223384.xyz",
        "user_id": "<SENSITIVE>",
        # 二选一：
        # 1) 直接填 Cookie（最通用）
        "cookie": 'wzhteam_consent={"QUQf":true}; session=MTc3MjQzNjg3OHxEWDhFQVFMX2dBQUJFQUVRQUFEX3hQLUFBQVlHYzNSeWFXNW5EQWNBQldkeWIzVndCbk4wY21sdVp3d0pBQWRrWldaaGRXeDBCbk4wY21sdVp3d05BQXR2WVhWMGFGOXpkR0YwWlFaemRISnBibWNNRGdBTWExQmxjbVZNZDBOdFJFWkRCbk4wY21sdVp3d0VBQUpwWkFOcGJuUUVCQUQtTkRZR2MzUnlhVzVuREFvQUNIVnpaWEp1WVcxbEJuTjBjbWx1Wnd3T0FBeHNhVzUxZUdSdlh6WTJPRE1HYzNSeWFXNW5EQVlBQkhKdmJHVURhVzUwQkFJQUFnWnpkSEpwYm1jTUNBQUdjM1JoZEhWekEybHVkQVFDQUFJPXxmQ7PEjXDzM6JP9tp4JbQMxp_6lqpLMdzN6plYW37p2w==',
        # 2) 或者填 Bearer token（如果站点用 Authorization）
        # "bearer": "YOUR_ACCESS_TOKEN",
    },
]

TIMEOUT = 25

def build_headers(site: dict) -> dict:
    base = site["base"].rstrip("/")
    h = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "cache-control": "no-store",
        "pragma": "no-cache",
        "origin": base,
        "referer": base + "/console/personal",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "new-api-user": str(site["user_id"]),
    }

    # 如果站点需要 Bearer token
    if site.get("bearer"):
        h["authorization"] = f"Bearer {site['bearer']}"

    # 允许额外 headers 覆盖
    h.update(site.get("headers", {}))
    return h

def safe_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return resp.text[:300]

def checkin(site: dict):
    base = site["base"].rstrip("/")
    headers = build_headers(site)

    post_url = urljoin(base + "/", "api/user/checkin")
    month = datetime.now().strftime("%Y-%m")
    get_url = post_url + f"?month={month}"

    s = requests.Session()

    # 如果配置了 cookie 字符串，就直接作为 Cookie 头发出去（最稳）
    cookie = site.get("cookie")
    if cookie:
        headers["cookie"] = cookie

    r1 = s.post(post_url, headers=headers, data="", timeout=TIMEOUT)
    r2 = s.get(get_url, headers=headers, timeout=TIMEOUT)
    return r1, r2

def main():
    print(f"Running check-in for {len(SITES)} site(s)...\n")
    for site in SITES:
        name = site.get("name", site["base"])
        try:
            r1, r2 = checkin(site)
            print(f"=== {name} ({site['base']}) ===")
            print("POST /api/user/checkin:", r1.status_code, safe_json(r1))
            print("GET  /api/user/checkin?month=YYYY-MM:", r2.status_code, safe_json(r2))
            print()
        except Exception as e:
            print(f"=== {name} ({site['base']}) ===")
            print("ERROR:", repr(e))
            print()

if __name__ == "__main__":
    main()