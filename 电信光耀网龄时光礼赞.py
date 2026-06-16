#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中国电信 - 光耀网龄 时光礼赞

账号来源：
1. 优先读取环境变量 chinaTelecomAccount，格式：手机号#密码&手机号#密码
2. 未配置环境变量时，读取 chinaTelecom_cache.json 中的缓存 token 账号

功能：
1. 中国电信 App 登录态换取 nstars 活动登录态
2. 7 天签到活动：签到，并在有抽奖机会时抽奖
3. 组队活动：账号数足够组满 3 人时，按账号顺序加入第一个账号队伍，并在有抽奖机会时抽奖
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import random
import re
import ssl
import sys
import time
import urllib.parse
from dataclasses import dataclass
from http import cookiejar
from pathlib import Path
from typing import Any

import requests
from Crypto.Cipher import DES3, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


CHANNEL = "HGOKHD"
PROMOID = "63db914eb803c94c"
ACTIVITY_URL = (
    "https://apps.telefen.com/nstars/iage"
    f"?promoid={PROMOID}&channel={CHANNEL}"
)
MIDDLEPARSE_URL = "https://apps.telefen.com/middleparse/api/access/ticket"
API_BASE = "https://apps.telefen.com/nstars"
CACHE_FILE = Path("chinaTelecom_cache.json")
ACCOUNT_ENV = "<SENSITIVE>"

SIGN_APP_ID = "JGSUDOKU-cvoVMkUa"
TEAM_APP_ID = "JGSUDOKU-CbrUm8TX"
TEAM_REQUIRED_SIZE = 3
RETRYABLE_ERR_CODES = {"0003", "1200"}
BUSY_RETRY_DELAYS = (2, 5, 10)
RATE_LIMIT_RETRY_DELAYS = (15, 30, 60, 120)
TEAM_REQUEST_INTERVAL = 1.5
LOTTERY_REQUEST_INTERVAL = 2.0

LOGIN_KEY = b"1234567`90koiuyhgtfrdews"
LOGIN_IV = 8 * b"\0"

PUBLIC_KEY_B64 = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBkLT15ThVgz6/NOl6s8GNPofdWzWbCkWnkaAm7O2LjkM1H7dMvzkiqdxU02jamGRHLX/ZNMCXHnPcW/sDhiFCBN18qFvy8g6VYb9QtroI09e176s+ZCtiv7hbin2cCTj99iUpnEloZm19lwHyo69u5UMiPMpq0/XKBO8lYhN/gwIDAQAB
-----END PUBLIC KEY-----"""


class BlockAll(cookiejar.CookiePolicy):
    return_ok = set_ok = domain_return_ok = path_return_ok = (
        lambda self, *args, **kwargs: False
    )
    netscape = True
    rfc2965 = hide_cookie2 = False


SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.set_ciphers("DEFAULT@SECLEVEL=1")
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


class DESAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = SSL_CONTEXT
        return super().init_poolmanager(*args, **kwargs)


requests.packages.urllib3.disable_warnings()


def now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(message: str) -> None:
    print(f"[{now()}] {message}")


def mask_phone(phone: str) -> str:
    if len(phone) == 11:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def json_from_response(response: requests.Response) -> dict[str, Any]:
    text = response.content.decode("utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"接口返回不是 JSON: {response.status_code} {text[:300]}") from exc
    return data


def require_success(name: str, data: dict[str, Any]) -> None:
    if data.get("errCode") != "0000":
        raise RuntimeError(f"{name}失败: {compact_json(data)}")


def get_set_cookie_header(response: requests.Response) -> str:
    set_cookie = response.headers.get("Set-Cookie", "")
    raw_headers = getattr(getattr(response, "raw", None), "headers", None)
    if raw_headers:
        get_all = getattr(raw_headers, "get_all", None) or getattr(
            raw_headers, "getlist", None
        )
        if get_all:
            cookies = get_all("Set-Cookie")
            if cookies:
                set_cookie = "<SENSITIVE>".join(cookies)
    return set_cookie


def extract_newmallsession(set_cookie: str) -> str:
    match = re.search(r"(newmallsession=[^;]+;)", set_cookie or "")
    return match.group(1) if match else ""


def query_param(url: str, key: str) -> str:
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(url or "").query,
        keep_blank_values=True,
    )
    values = query.get(key)
    return values[0] if values else ""


def normalize_cookie(cookie: str) -> str:
    return (cookie or "").strip().rstrip(";")


def encode_phone(text: str) -> str:
    return "".join(chr(ord(char) + 2) for char in text)


def encrypt_3des(text: str) -> str:
    cipher = DES3.new(LOGIN_KEY, DES3.MODE_CBC, LOGIN_IV)
    ciphertext = cipher.encrypt(pad(text.encode(), DES3.block_size))
    return ciphertext.hex()


def decrypt_3des(text: str) -> str:
    ciphertext = bytes.fromhex(text)
    cipher = DES3.new(LOGIN_KEY, DES3.MODE_CBC, LOGIN_IV)
    plaintext = unpad(cipher.decrypt(ciphertext), DES3.block_size)
    return plaintext.decode()


def rsa_b64(plaintext: str) -> str:
    public_key = RSA.import_key(PUBLIC_KEY_B64)
    cipher = PKCS1_v1_5.new(public_key)
    ciphertext = cipher.encrypt(plaintext.encode())
    return base64.b64encode(ciphertext).decode()


def make_login_session(block_cookies: bool = False) -> requests.Session:
    session = requests.Session()
    session.mount("https://", DESAdapter())
    session.verify = False
    if block_cookies:
        session.cookies.set_policy(BlockAll())
    return session


def load_token_cache() -> dict[str, dict[str, Any]]:
    if not CACHE_FILE.exists():
        return {}
    with CACHE_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"{CACHE_FILE} 必须是 JSON 对象")
    return data


def save_token_cache(cache: dict[str, dict[str, Any]]) -> None:
    with CACHE_FILE.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        f.write("\n")


def user_login_normal(
    phone: str,
    password: str,
    token_cache: dict[str, dict[str, Any]],
) -> str:
    session = make_login_session(block_cookies=True)
    session.headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; 22081212C Build/TKQ1.220829.002) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.97 "
            "Mobile Safari/537.36"
        ),
        "Referer": "https://wapact.189.cn:9001/JinDouMall/JinDouMall_independentDetails.html",
    }

    alphabet = "abcdef0123456789"
    uuid = [
        "".join(random.sample(alphabet, 8)),
        "".join(random.sample(alphabet, 4)),
        "4" + "".join(random.sample(alphabet, 3)),
        "".join(random.sample(alphabet, 4)),
        "".join(random.sample(alphabet, 12)),
    ]
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    login_auth = (
        "iPhone 14 15.4."
        + uuid[0]
        + uuid[1]
        + phone
        + timestamp
        + password[:6]
        + "0$$$0."
    )

    response = session.post(
        "https://appgologin.189.cn:9031/login/client/userLoginNormal",
        json={
            "headerInfos": {
                "code": "userLoginNormal",
                "timestamp": timestamp,
                "broadAccount": "",
                "broadToken": "",
                "clientType": "#12.2.0#channel50#iPhone 14 Pro Max#",
                "shopId": "20002",
                "source": "110003",
                "sourcePassword": "<SENSITIVE>",
                "token": "",
                "userLoginName": encode_phone(phone),
            },
            "content": {
                "attach": "test",
                "fieldData": {
                    "loginType": "4",
                    "accountType": "",
                    "loginAuthCipherAsymmertric": rsa_b64(login_auth),
                    "deviceUid": uuid[0] + uuid[1] + uuid[2],
                    "phoneNum": encode_phone(phone),
                    "isChinatelecom": "<SENSITIVE>",
                    "systemVersion": "15.4.0",
                    "authentication": encode_phone(password),
                },
            },
        },
        timeout=20,
    )
    result = json_from_response(response)
    data = ((result.get("responseData") or {}).get("data") or {})
    login_result = data.get("loginSuccessResult")
    if not login_result:
        raise RuntimeError(f"账号密码登录失败: {compact_json(result)}")

    token_cache[phone] = login_result
    save_token_cache(token_cache)
    return get_ticket(phone, login_result["userId"], login_result["token"])


def get_ticket(phone: str, user_id: str, token: str) -> str:
    session = make_login_session(block_cookies=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    xml = (
        "<Request><HeaderInfos><Code>getSingle</Code><Timestamp>"
        + timestamp
        + "</Timestamp><BroadAccount></BroadAccount><BroadToken></BroadToken>"
        + "<ClientType>#9.6.1#channel50#iPhone 14 Pro Max#</ClientType>"
        + "<ShopId>20002</ShopId><Source>110003</Source>"
        + "<SourcePassword>Sid98s</SourcePassword><Token>"
        + token
        + "</Token><UserLoginName>"
        + phone
        + "</UserLoginName></HeaderInfos><Content><Attach>test</Attach>"
        + "<FieldData><TargetId>"
        + encrypt_3des(user_id)
        + "</TargetId><Url>4a6862274835b451</Url></FieldData></Content></Request>"
    )
    response = session.post(
        "https://appgologin.189.cn:9031/map/clientXML",
        data=xml,
        headers={
            "user-agent": "CtClient;10.4.1;Android;13;22081212C;NTQzNzgx!#!MTgwNTg1",
            "Content-Type": "application/xml;charset=utf-8",
        },
        timeout=20,
    )
    tickets = re.findall("<Ticket>(.*?)</Ticket>", response.text)
    if not tickets:
        raise RuntimeError(f"获取 Ticket 失败: {response.text[:300]}")
    return decrypt_3des(tickets[0])


@dataclass
class AccountSpec:
    phone: str
    password: str | None = None


class IageClient:
    def __init__(self, phone: str, ticket: str) -> None:
        self.phone = phone
        self.masked_phone = mask_phone(phone)
        self.ticket = ticket
        self.session = make_login_session()
        self.token = ""
        self.referer = ""
        self.cookie = ""
        self.user_payload: dict[str, Any] = {}
        self.login_type = ""
        self.age_year = 0
        self.team_record: list[dict[str, Any]] = []
        self.team_code = ""

    def enter_activity(self) -> None:
        headers = {
            "User-Agent": "CtClient;13.2.0;Android;14;22021211RC;",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Encoding": "gzip, deflate, br",
            "Upgrade-Insecure-Requests": "1",
            "X-Requested-With": "com.ct.client",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        response = self.session.get(
            MIDDLEPARSE_URL,
            params={
                "channel": CHANNEL,
                "action": "2",
                "rdurl": ACTIVITY_URL,
                "promoid": PROMOID,
                "ticket": self.ticket,
            },
            headers=headers,
            allow_redirects=False,
            timeout=20,
        )
        if response.status_code not in (301, 302, 303, 307, 308):
            raise RuntimeError(
                f"活动 SSO 首跳失败: {response.status_code} {response.text[:300]}"
            )

        first_cookie = extract_newmallsession(get_set_cookie_header(response))
        location = response.headers.get("Location", "")
        if not location:
            raise RuntimeError("活动 SSO 首跳没有 Location")

        dock_response = self.session.get(
            location,
            headers=headers,
            allow_redirects=False,
            timeout=20,
        )
        if dock_response.status_code not in (301, 302, 303, 307, 308):
            raise RuntimeError(
                f"活动 SSO 二跳失败: {dock_response.status_code} {dock_response.text[:300]}"
            )

        second_cookie = extract_newmallsession(get_set_cookie_header(dock_response))
        self.cookie = normalize_cookie(first_cookie or second_cookie)
        self.referer = dock_response.headers.get("Location", "")
        self.token = query_param(self.referer, "Token")
        if not self.cookie:
            raise RuntimeError("活动 SSO 未取得 newmallsession")
        if not self.token:
            raise RuntimeError(f"活动 SSO 未取得 Token: {self.referer}")

        page_response = self.session.get(
            self.referer,
            headers=self.page_headers(location),
            allow_redirects=True,
            timeout=20,
        )
        if page_response.status_code != 200:
            raise RuntimeError(
                f"活动页加载失败: {page_response.status_code} {page_response.text[:300]}"
            )

    def page_headers(self, referer: str = "") -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
                "Mobile/15E148 Safari/604.1"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": self.cookie,
            "Referer": referer,
            "Upgrade-Insecure-Requests": "1",
        }

    def api_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json;charset=UTF-8",
            "Cookie": self.cookie,
            "Host": "apps.telefen.com",
            "Origin": "https://apps.telefen.com",
            "Referer": self.referer,
            "SSOToken": self.token,
            "ssotoken": self.token,
            "appCode": CHANNEL,
            "appcode": CHANNEL,
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
                "Mobile/15E148 Safari/604.1"
            ),
        }

    def api_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.get(
            API_BASE + path,
            params=params,
            headers=self.api_headers(),
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(f"GET {path} HTTP {response.status_code}: {response.text[:300]}")
        return json_from_response(response)

    def api_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            API_BASE + path,
            json=payload,
            headers=self.api_headers(),
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(f"POST {path} HTTP {response.status_code}: {response.text[:300]}")
        return json_from_response(response)

    def load_user_info(self) -> None:
        data = self.api_get("/api/account/must", {"noload": "true"})
        require_success("登录态检查", data)
        self.user_payload = data.get("data") or {}
        user_info = self.user_payload.get("userInfo") or {}
        prod_info = self.user_payload.get("prodInfo") or {}
        self.login_type = str(user_info.get("loginType") or "")
        self.age_year = int(prod_info.get("ageYear") or 0)
        log(
            f"{self.masked_phone} 登录成功: loginType={self.login_type} "
            f"网龄={prod_info.get('age') or str(self.age_year) + '年'}"
        )

    def sign_status(self) -> dict[str, Any]:
        return self.api_post("/api/active/getSignIn", {"appId": SIGN_APP_ID})

    def sign_in(self) -> dict[str, Any]:
        return self.api_post(
            "/api/active/signIn",
            {"appId": SIGN_APP_ID, "appCode": CHANNEL},
        )

    def free_count(self, app_id: str) -> int:
        data = self.api_get(
            "/api/game/freeCount",
            {
                "appId": app_id,
                "mchId": 0,
                "appCode": CHANNEL,
                "noload": "true",
            },
        )
        require_success("查询抽奖次数", data)
        return int(data.get("data") or 0)

    def free_count_payload(self, app_id: str) -> dict[str, Any]:
        return self.api_get(
            "/api/game/freeCount",
            {
                "appId": app_id,
                "mchId": 0,
                "appCode": CHANNEL,
                "noload": "true",
            },
        )

    def lottery(self, app_id: str, out_order_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "noload": "true",
            "appId": app_id,
            "mchId": 0,
            "appCode": CHANNEL,
        }
        if out_order_id:
            params["outOrderId"] = out_order_id
        return self.api_get("/api/game/lottery", params)

    def game_record(self, app_id: str) -> list[dict[str, Any]]:
        data = self.api_get(
            "/api/game/getRecord",
            {
                "noload": "true",
                "appId": app_id,
                "mchId": 0,
                "appCode": CHANNEL,
            },
        )
        require_success("查询奖品记录", data)
        records = data.get("data")
        return records if isinstance(records, list) else []

    def get_team_code(self) -> str:
        data = retry_api_get(
            self,
            "/api/invitation/getCode",
            {
                "noload": "true",
                "mchId": 0,
                "channel": CHANNEL,
                "activeId": TEAM_APP_ID,
            },
            "获取组队邀请码",
        )
        require_success("获取组队邀请码", data)
        code = str(data.get("data") or "").strip()
        if not code:
            raise RuntimeError("获取组队邀请码失败: 接口 data 为空")
        self.team_code = code
        return code

    def get_team_record(self) -> list[dict[str, Any]]:
        data = retry_api_get(
            self,
            "/api/invitation/getRecord",
            {
                "noload": "true",
                "mchId": 0,
                "appCode": CHANNEL,
                "activeId": TEAM_APP_ID,
            },
            "查询组队记录",
        )
        require_success("查询组队记录", data)
        records = data.get("data")
        self.team_record = records if isinstance(records, list) else []
        return self.team_record

    def check_team_code(self, invite_code: str) -> dict[str, Any]:
        return retry_api_get(
            self,
            "/api/invitation/checkCode",
            {
                "appCode": CHANNEL,
                "inviteCode": invite_code,
                "activeId": TEAM_APP_ID,
            },
            "校验组队邀请码",
        )

    def join_team(self, invite_code: str) -> dict[str, Any]:
        return retry_api_post(
            self,
            "/api/invitation/joinTeam",
            {
                "appCode": CHANNEL,
                "inviteCode": invite_code,
                "activeId": TEAM_APP_ID,
            },
            "加入组队",
        )


def build_account_specs(token_cache: dict[str, dict[str, Any]]) -> list[AccountSpec]:
    env_value = os.environ.get(ACCOUNT_ENV, "").strip()
    if env_value:
        specs: list[AccountSpec] = []
        for item in re.split(r"[&\n@]", env_value):
            item = item.strip()
            if not item:
                continue
            parts = item.split("#", 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise RuntimeError(f"{ACCOUNT_ENV} 账号格式错误: {item}")
            specs.append(AccountSpec(phone=parts[0], password=parts[1]))
        if not specs:
            raise RuntimeError(f"{ACCOUNT_ENV} 未解析到有效账号")
        return specs

    if token_cache:
        return [AccountSpec(phone=phone) for phone in token_cache.keys()]

    raise RuntimeError(f"未配置 {ACCOUNT_ENV}，且 {CACHE_FILE} 没有可用账号")


def login_account(
    spec: AccountSpec,
    token_cache: dict[str, dict[str, Any]],
) -> str:
    if spec.phone in token_cache:
        cache_entry = token_cache[spec.phone]
        if "userId" not in cache_entry or "token" not in cache_entry:
            raise RuntimeError(f"{mask_phone(spec.phone)} 缓存缺少 userId/token")
        return get_ticket(spec.phone, cache_entry["userId"], cache_entry["token"])

    if not spec.password:
        raise RuntimeError(f"{mask_phone(spec.phone)} 没有缓存 token，也没有密码")
    return user_login_normal(spec.phone, spec.password, token_cache)


def draw_available(client: IageClient, app_id: str, label: str) -> None:
    count = retry_free_count(client, app_id, label)
    if count is None:
        return
    log(f"{client.masked_phone} {label}抽奖次数: {count}")
    for index in range(count):
        result = retry_lottery(client, app_id, label)
        if is_not_won(result):
            log(f"{client.masked_phone} {label}抽奖 {index + 1}/{count}: 未中奖")
            time.sleep(LOTTERY_REQUEST_INTERVAL)
            continue
        if result.get("errCode") != "0000":
            log(f"{client.masked_phone} {label}抽奖失败: {compact_json(result)}")
            break
        prize = result.get("data")
        if prize:
            name = prize.get("productName") or prize.get("awardName") or compact_json(prize)
            log(f"{client.masked_phone} {label}抽奖 {index + 1}/{count}: 中奖 {name}")
        else:
            log(f"{client.masked_phone} {label}抽奖 {index + 1}/{count}: 未中奖")
        time.sleep(LOTTERY_REQUEST_INTERVAL)


def run_sign_task(client: IageClient) -> None:
    if client.login_type != "7":
        log(f"{client.masked_phone} 签到跳过: 非中国电信手机用户")
        return
    if client.age_year < 2:
        log(f"{client.masked_phone} 签到跳过: 网龄不足 2 年")
        return

    status = client.sign_status()
    require_success("查询签到状态", status)
    sign_data = status.get("data") or {}
    signed_count = int(sign_data.get("totalCount") or 0)
    signed_today = int(sign_data.get("canSignIn") or 0) == 1
    log(
        f"{client.masked_phone} 签到状态: 累计{signed_count}天 "
        f"今日{'已签到' if signed_today else '未签到'}"
    )

    out_order_id = None
    if not signed_today:
        result = client.sign_in()
        if result.get("errCode") != "0000":
            log(f"{client.masked_phone} 签到失败: {compact_json(result)}")
            return
        current = result.get("data") or {}
        signed_count = int(current.get("totalCount") or 0)
        out_order_id = current.get("outOrderId")
        log(f"{client.masked_phone} 签到成功: 累计{signed_count}天")
        if signed_count in (1, 4, 7):
            lottery_result = client.lottery(SIGN_APP_ID, out_order_id=out_order_id)
            if lottery_result.get("errCode") == "0000":
                prize = lottery_result.get("data")
                if prize:
                    name = prize.get("productName") or prize.get("awardName") or compact_json(prize)
                    log(f"{client.masked_phone} 签到里程碑抽奖: 中奖 {name}")
                else:
                    log(f"{client.masked_phone} 签到里程碑抽奖: 未中奖")
            elif is_not_won(lottery_result):
                log(f"{client.masked_phone} 签到里程碑抽奖: 未中奖")
            else:
                log(f"{client.masked_phone} 签到里程碑抽奖失败: {compact_json(lottery_result)}")

    draw_available(client, SIGN_APP_ID, "签到")


def eligible_for_team(client: IageClient) -> bool:
    if client.login_type != "7":
        log(f"{client.masked_phone} 组队跳过: 非中国电信手机用户")
        return False
    if client.age_year < 1:
        log(f"{client.masked_phone} 组队跳过: 网龄不足 1 年")
        return False
    return True


def team_member_count(client: IageClient) -> int:
    return len(client.team_record) if client.team_record else 0


def team_effective_count(client: IageClient) -> int:
    return team_member_count(client) or 1


def err_msg(data: dict[str, Any]) -> str:
    return str(data.get("errMsg") or "")


def is_retryable_busy(data: dict[str, Any]) -> bool:
    code = str(data.get("errCode") or "")
    message = err_msg(data)
    return code in RETRYABLE_ERR_CODES or "活动火爆" in message or "请求过于频繁" in message


def is_rate_limited(data: dict[str, Any]) -> bool:
    code = str(data.get("errCode") or "")
    message = err_msg(data)
    return code == "1200" or "请求过于频繁" in message


def retry_delays_for(data: dict[str, Any]) -> tuple[int, ...]:
    return RATE_LIMIT_RETRY_DELAYS if is_rate_limited(data) else BUSY_RETRY_DELAYS


def is_not_won(data: dict[str, Any]) -> bool:
    return data.get("errCode") == "9999" and "未中奖" in str(data.get("errMsg") or "")


def retry_free_count(client: IageClient, app_id: str, label: str) -> int | None:
    result = client.free_count_payload(app_id)
    delays = retry_delays_for(result)
    attempt = 0
    while is_retryable_busy(result) and attempt < len(delays):
        delay = delays[attempt]
        log(
            f"{client.masked_phone} {label}抽奖次数查询返回{err_msg(result) or result.get('errCode')}，"
            f"{delay} 秒后重试 {attempt + 1}/{len(delays)}"
        )
        time.sleep(delay)
        result = client.free_count_payload(app_id)
        attempt += 1
    if result.get("errCode") != "0000":
        log(f"{client.masked_phone} {label}抽奖次数查询失败: {compact_json(result)}")
        return None
    return int(result.get("data") or 0)


def retry_api_get(
    client: IageClient,
    path: str,
    params: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    result = client.api_get(path, params)
    delays = retry_delays_for(result)
    attempt = 0
    while is_retryable_busy(result) and attempt < len(delays):
        delay = delays[attempt]
        log(
            f"{client.masked_phone} {label}返回{err_msg(result) or result.get('errCode')}，"
            f"{delay} 秒后重试 {attempt + 1}/{len(delays)}"
        )
        time.sleep(delay)
        result = client.api_get(path, params)
        attempt += 1
    return result


def retry_api_post(
    client: IageClient,
    path: str,
    payload: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    result = client.api_post(path, payload)
    delays = retry_delays_for(result)
    attempt = 0
    while is_retryable_busy(result) and attempt < len(delays):
        delay = delays[attempt]
        log(
            f"{client.masked_phone} {label}返回{err_msg(result) or result.get('errCode')}，"
            f"{delay} 秒后重试 {attempt + 1}/{len(delays)}"
        )
        time.sleep(delay)
        result = client.api_post(path, payload)
        attempt += 1
    return result


def retry_lottery(client: IageClient, app_id: str, label: str) -> dict[str, Any]:
    result = client.lottery(app_id)
    delays = retry_delays_for(result)
    attempt = 0
    while is_retryable_busy(result) and attempt < len(delays):
        delay = delays[attempt]
        log(
            f"{client.masked_phone} {label}抽奖返回{err_msg(result) or result.get('errCode')}，"
            f"{delay} 秒后重试 {attempt + 1}/{len(delays)}"
        )
        time.sleep(delay)
        result = client.lottery(app_id)
        attempt += 1
    return result


def retry_team_check(helper: IageClient, invite_code: str) -> dict[str, Any]:
    result = helper.check_team_code(invite_code)
    delays = retry_delays_for(result)
    attempt = 0
    while is_retryable_busy(result) and attempt < len(delays):
        delay = delays[attempt]
        log(
            f"{helper.masked_phone} 邀请码校验返回{err_msg(result) or result.get('errCode')}，"
            f"{delay} 秒后重试 {attempt + 1}/{len(delays)}"
        )
        time.sleep(delay)
        result = helper.check_team_code(invite_code)
        attempt += 1
    return result


def retry_team_join(helper: IageClient, invite_code: str) -> dict[str, Any]:
    result = helper.join_team(invite_code)
    delays = retry_delays_for(result)
    attempt = 0
    while is_retryable_busy(result) and attempt < len(delays):
        delay = delays[attempt]
        log(
            f"{helper.masked_phone} 加入组队返回{err_msg(result) or result.get('errCode')}，"
            f"{delay} 秒后重试 {attempt + 1}/{len(delays)}"
        )
        time.sleep(delay)
        result = helper.join_team(invite_code)
        attempt += 1
    return result


def select_joinable_helpers(
    captain: IageClient,
    invite_code: str,
    helper_pool: list[IageClient],
    required_count: int,
) -> tuple[list[tuple[IageClient, dict[str, Any]]], bool]:
    selected: list[tuple[IageClient, dict[str, Any]]] = []
    for helper in list(helper_pool):
        if helper is captain:
            continue
        check = retry_team_check(helper, invite_code)
        time.sleep(TEAM_REQUEST_INTERVAL)
        if check.get("errCode") == "0000":
            selected.append((helper, check))
            log(f"{helper.masked_phone} 邀请码校验通过")
            if len(selected) >= required_count:
                break
            continue

        if is_retryable_busy(check):
            log(f"{helper.masked_phone} 邀请码校验仍被限频，停止本轮组队: {compact_json(check)}")
            return selected, True

        log(f"{helper.masked_phone} 邀请码校验失败，换下一个候选: {compact_json(check)}")
        refreshed_record = helper.get_team_record()
        time.sleep(TEAM_REQUEST_INTERVAL)
        if helper in helper_pool:
            helper_pool.remove(helper)
            reason = "已存在队伍记录" if refreshed_record else "本轮校验未通过"
            log(f"{helper.masked_phone} {reason}，从未组队候选池移除")
    return selected, False


def join_selected_helpers(
    captain: IageClient,
    invite_code: str,
    selected_helpers: list[tuple[IageClient, dict[str, Any]]],
    helper_pool: list[IageClient],
) -> bool:
    for helper, check in selected_helpers:
        inviter = ((check.get("data") or {}).get("deviceNo")) or captain.masked_phone
        log(f"{helper.masked_phone} 确认加入 {inviter} 的队伍")
        join_result = retry_team_join(helper, invite_code)
        time.sleep(TEAM_REQUEST_INTERVAL)
        if join_result.get("errCode") == "0000":
            if helper in helper_pool:
                helper_pool.remove(helper)
            log(f"{helper.masked_phone} 组队成功")
            continue

        if is_retryable_busy(join_result):
            log(f"{helper.masked_phone} 加入组队仍被限频，停止本轮组队: {compact_json(join_result)}")
            return True

        log(f"{helper.masked_phone} 加入组队失败: {compact_json(join_result)}")
        refreshed_record = helper.get_team_record()
        time.sleep(TEAM_REQUEST_INTERVAL)
        if helper in helper_pool:
            helper_pool.remove(helper)
            reason = "已存在队伍记录" if refreshed_record else "本轮加入失败"
            log(f"{helper.masked_phone} {reason}，从未组队候选池移除")
    return False


def run_team_task(clients: list[IageClient]) -> None:
    team_clients = [client for client in clients if eligible_for_team(client)]
    if not team_clients:
        log("组队跳过: 没有符合条件的账号")
        return

    for client in team_clients:
        client.get_team_record()
        log(f"{client.masked_phone} 当前队伍人数: {team_member_count(client)}")
        time.sleep(TEAM_REQUEST_INTERVAL)

    unteamed_clients = [client for client in team_clients if not client.team_record]
    incomplete_captains = [
        client
        for client in team_clients
        if 0 < team_member_count(client) < TEAM_REQUIRED_SIZE
    ]
    captain_queue = incomplete_captains + list(unteamed_clients)

    for captain in captain_queue:
        if team_member_count(captain) >= TEAM_REQUIRED_SIZE:
            continue
        if not captain.team_record and captain not in unteamed_clients:
            continue
        if captain in unteamed_clients:
            unteamed_clients.remove(captain)

        current_count = team_effective_count(captain)
        required_helpers = TEAM_REQUIRED_SIZE - current_count
        if required_helpers <= 0:
            continue
        if len(unteamed_clients) < required_helpers:
            log(
                f"{captain.masked_phone} 组队跳过自动加入: "
                f"未组队候选不足 {required_helpers} 人，避免账号被锁在未满队伍"
            )
            continue

        invite_code = captain.get_team_code()
        log(f"{captain.masked_phone} 开始组队: 当前{current_count}人，还需{required_helpers}人")
        time.sleep(TEAM_REQUEST_INTERVAL)

        selected_helpers, rate_limited = select_joinable_helpers(
            captain,
            invite_code,
            unteamed_clients,
            required_helpers,
        )
        if rate_limited:
            log(f"{captain.masked_phone} 组队暂停: 服务端限频未恢复")
            break
        if len(selected_helpers) < required_helpers:
            log(
                f"{captain.masked_phone} 组队跳过加入: "
                f"通过邀请码校验的候选不足 {required_helpers} 人"
            )
            continue

        rate_limited = join_selected_helpers(
            captain,
            invite_code,
            selected_helpers,
            unteamed_clients,
        )
        captain.get_team_record()
        log(f"{captain.masked_phone} 组队后人数: {team_member_count(captain)}")
        time.sleep(TEAM_REQUEST_INTERVAL)
        if rate_limited:
            log(f"{captain.masked_phone} 组队暂停: 服务端限频未恢复")
            break

        while 0 < team_member_count(captain) < TEAM_REQUIRED_SIZE and unteamed_clients:
            invite_code = captain.get_team_code()
            selected_helpers, rate_limited = select_joinable_helpers(
                captain,
                invite_code,
                unteamed_clients,
                1,
            )
            if rate_limited:
                log(f"{captain.masked_phone} 补齐组队暂停: 服务端限频未恢复")
                break
            if not selected_helpers:
                break
            rate_limited = join_selected_helpers(
                captain,
                invite_code,
                selected_helpers,
                unteamed_clients,
            )
            captain.get_team_record()
            log(f"{captain.masked_phone} 补齐组队后人数: {team_member_count(captain)}")
            time.sleep(TEAM_REQUEST_INTERVAL)
            if rate_limited:
                log(f"{captain.masked_phone} 补齐组队暂停: 服务端限频未恢复")
                break

    for client in team_clients:
        record = client.get_team_record()
        count_display = len(record) if record else 0
        log(f"{client.masked_phone} 组队记录人数: {count_display}")
        time.sleep(TEAM_REQUEST_INTERVAL)
        if len(record) >= 3:
            draw_available(client, TEAM_APP_ID, "组队")
        else:
            log(f"{client.masked_phone} 组队抽奖跳过: 队伍未满 3 人")
        time.sleep(LOTTERY_REQUEST_INTERVAL)


def main() -> None:
    token_cache = load_token_cache()
    specs = build_account_specs(token_cache)
    log(f"检测到 {len(specs)} 个账号")

    clients: list[IageClient] = []
    for index, spec in enumerate(specs, start=1):
        log(f"开始处理第 {index}/{len(specs)} 个账号: {mask_phone(spec.phone)}")
        try:
            ticket = login_account(spec, token_cache)
            client = IageClient(spec.phone, ticket)
            client.enter_activity()
            client.load_user_info()
            run_sign_task(client)
            clients.append(client)
        except Exception as exc:
            log(f"{mask_phone(spec.phone)} 处理失败: {exc}")
        if index < len(specs):
            time.sleep(2)

    run_team_task(clients)
    log("任务结束")


if __name__ == "__main__":
    main()
