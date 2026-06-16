#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立版保单监控脚本：不依赖 HAR 文件即可运行。

用途：
1. 按 HAR 中的链路执行：APP 登录 -> loginLoadPage -> queryMinePage -> H5 预热 -> 保单列表
2. 打印整理后的保单列表
3. 使用本地 JSON 缓存识别“新增保单”
4. 通过控制台 / 通用 Webhook / 自定义命令发送新增保单通知

说明：
- 这份脚本已经把 HAR 里的关键接口、头、默认参数、签名规则固化到代码里。
- 运行时不再读取 HAR。
- 仍然支持用命令行参数或环境变量覆盖账号、密码、设备号、H5 签名上下文等信息。

注意：
- 当前 H5 鉴权由前端 JS 决定，实际使用的是 SAAS_TOKEN + SAAS_SECRET。
- 从 HAR 校验可知：你这次抓包的 listPolicy / commissionRateStatistics 可以用“APP 登录 token + 空 secret”算出正确 Authorization。
- 但如果你当前环境跑出来仍然是 401，可尝试额外传入：
  --h5-saas-token / --h5-saas-secret / --h5-fixed-authorization
  因为你设备里的 H5 上下文，未必永远等于 APP 登录 token + 空 secret。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests

# =========================
# 1) 固化自 HAR 的模板配置
# =========================
CONFIG: Dict[str, Any] = {
    "timeout": 30,
    "verify_tls": True,
    "app": {
        "base_url": "https://gmfs-insurer-commander.gmfs.cn",
        "user_agent": "XinShan/3.5.3 (com.gmfs.xs; build:19; iOS 26.3.1) Alamofire/5.8.0",
        "accept_language": "zh-Hans-CN;q=1.0",
        "login_payload": {
            # 默认值来自 HAR；也可用命令行或环境变量覆盖。
            "password": "<SENSITIVE>",
            "appFlag": "",
            "loginType": "1",
            "deviceNumber": "89418F0C-1340-42D4-922A-BD692DE8C90D",
            "ip": "",
            "captchaCode": "",
            "loginName": "<PHONE>",
        },
        "endpoints": {
            "login": "/api/app/login",
            "login_load_page": "/api/app/loginLoadPage",
            "query_mine_page": "/api/app/queryMinePage",
        },
    },
    "h5": {
        "base_url": "https://gmfs-insurer-h5.gmfs.cn",
        "origin": "https://gmfs-insurer-h5.gmfs.cn",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 ICBC-AXA-XMS",
        "accept_language": "zh-CN,zh-Hans;q=0.9",
        "referer_path": "/index/policyQuery",
        # 来自 HAR 的 Referer 查询模板
        "referer_query_template": {
            "acceptDateEnd": "2026-03-31",
            "acceptDateStart": "2026-03-01",
            "commissionStatus": "",
            "customerNoticeStatus": "",
            "keywords": "",
            "policyStatus": "0",
            "policyType": "0",
            "productType": "",
            "receiptStatus": "",
            "revisitStatus": "",
            "sortOrder": "1",
            "sortType": "acceptDate",
        },
        # 来自 HAR 的 H5 预热字典请求
        "query_dict_info": {
            "path": "/api/app/queryDictInfo",
            "payload": [
                "GENDER",
                "MARRIAGE_STATUS",
                "DEGREE",
                "CUSTOMER_SOURCE",
                "CERT_TYPE_XINTAI",
                "BANK",
                "PRODUCT_TAG",
                "CALANDER_MOLD",
                "NATION",
                "POLITICS",
                "RESIDENCY_TYPE",
                "AGENT_BENEFICIATY",
                "EMERGENCY_CONTACT",
                "AREA",
                "CERT_TYPE",
            ],
        },
        "list_policy": {
            "path": "/api/app/policy/v1/listPolicy",
            "payload": {
                "pageNum": 1,
                "pageSize": 10,
                "productType": "",
                "receiptStatus": "",
                "revisitStatus": "",
                "commissionStatus": "",
                "customerNoticeStatus": "",
                "keywords": "",
                "sort": "AD",
                "policyStatus": "",
                "acceptDateStart": "2026-03-01",
                "acceptDateEnd": "2026-03-31",
            },
        },
        "commission": {
            "path": "/api/app/policy/v1/commissionRateStatistics",
            "payload": {
                "policyType": "0",
                "productType": "",
                "receiptStatus": "",
                "revisitStatus": "",
                "commissionStatus": "",
                "customerNoticeStatus": "",
                "keywords": "",
                "sort": "AD",
                "policyStatus": "",
                "acceptDateStart": "2026-03-01",
                "acceptDateEnd": "2026-03-31",
            },
        },
    },
    "cache": {
        "version": 1,
        "max_seen_policies": 5000,
    },
}

SENSITIVE_KEYS = {
    "password",
    "pwd",
    "token",
    "authorization",
    "cookie",
    "set-cookie",
    "certino",
    "certno",
    "cert_no",
    "idcard",
    "mobile",
    "phone",
    "loginname",
}


class FlowError(Exception):
    pass


class NotifyError(Exception):
    pass


@dataclass
class StepResult:
    name: str
    status_code: int
    json_data: Optional[Dict[str, Any]]
    text: str


@dataclass
class PolicyFetchResult:
    pages: List[StepResult]
    rows: List[Dict[str, Any]]
    total: Optional[int]


# =========================
# 2) 通用工具函数
# =========================
def log(step: str, message: str = "") -> None:
    prefix = f"\n[{step}]"
    print(prefix if not message else f"{prefix} {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def info(message: str) -> None:
    print(f"[INFO] {message}")


def now_local_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_str() -> str:
    return date.today().isoformat()


def default_date_start(days_back: int) -> str:
    return (date.today() - timedelta(days=days_back)).isoformat()


def mask_text(value: Any, keep_left: int = 4, keep_right: int = 4) -> str:
    if value is None:
        return ""
    s = str(value)
    if len(s) <= keep_left + keep_right + 3:
        return "*" * len(s)
    return f"{s[:keep_left]}***{s[-keep_right:]}"


def mask_person_name(name: Any) -> str:
    if name is None:
        return ""
    s = str(name).strip()
    if not s:
        return s
    if len(s) == 1:
        return s
    if len(s) == 2:
        return s[0] + "*"
    return s[0] + ("*" * (len(s) - 2)) + s[-1]


def is_sensitive_key(key: str) -> bool:
    k = key.lower().strip()
    if k in SENSITIVE_KEYS:
        return True
    return any(token in k for token in ["token", "auth", "password", "cookie", "phone", "mobile", "cert"])


def mask_obj(data: Any) -> Any:
    if isinstance(data, dict):
        out: Dict[str, Any] = {}
        for k, v in data.items():
            out[k] = mask_text(v) if is_sensitive_key(k) else mask_obj(v)
        return out
    if isinstance(data, list):
        return [mask_obj(i) for i in data]
    return data


def pretty(data: Any) -> str:
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False, indent=2)
    return str(data)


def try_json_loads(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except Exception:
        return None


def json_dumps_compact(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def normalize_signature_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        text = re.sub(r'"[^"]*":null,?', "", text)
        text = re.sub(r",(?=})", "", text)
        return text
    return str(value)


def merge_payload(template: Dict[str, Any], **updates: Any) -> Dict[str, Any]:
    body = copy.deepcopy(template)
    for key, value in updates.items():
        if value is not None:
            body[key] = value
    return body


def get_runtime_credential(cli_value: Optional[str], env_name: str, default_value: str) -> str:
    if cli_value not in (None, ""):
        return cli_value
    env_value = os.getenv(env_name)
    if env_value not in (None, ""):
        return env_value
    return default_value


def env_or_default(cli_value: Optional[str], env_name: str, default_value: str = "") -> str:
    if cli_value not in (None, ""):
        return cli_value
    env_value = os.getenv(env_name)
    if env_value not in (None, ""):
        return env_value
    return default_value


def parse_dateish(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    # 常见格式：2026-03-12 00:00:00.0 / 2026-03-12 / 2026-03-01T00:00:00.000+0800
    patterns = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ]
    for pattern in patterns:
        try:
            return datetime.strptime(text, pattern)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def to_money_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)


def clip_text(value: Any, max_len: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# =========================
# 3) H5 鉴权（按前端 JS 真实逻辑）
# =========================
def extract_signed_value_list(
    method: str,
    url_or_path: str,
    body: Optional[Any] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    对齐 H5 前端 JS：
    1) 先解析 URL query 为 dict
    2) 合并 params
    3) 如果 method != GET 且 body 是“普通对象(dict)”，再合并 body
    4) 对 key 排序后，取 value 列表；null/undefined => ""；对象 => JSON 压缩并剔除 null 字段

    关键差异：如果 body 是 list（比如 queryDictInfo），前端不会把 list body 参与签名。
    所以 queryDictInfo 的签名等于 md5(SAAS_TOKEN + path + SAAS_SECRET)。
    """
    split = urlsplit(url_or_path)
    query_items = sorted(parse_qsl(split.query, keep_blank_values=True))
    merged: Dict[str, Any] = {k: v for k, v in query_items}
    if params:
        merged.update(params)
    if method.lower() != "get" and isinstance(body, dict):
        merged.update(body)
    values = [normalize_signature_value(merged[k]) for k in sorted(merged.keys())]
    return values


def normalize_sign_path(url_or_path: str) -> str:
    split = urlsplit(url_or_path)
    path = split.path or url_or_path
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("/api/"):
        path = path[len("/api") :]
    return path


def build_h5_authorization(
    saas_token: str,
    url_or_path: str,
    body: Optional[Any] = None,
    params: Optional[Dict[str, Any]] = None,
    secret: str = "",
    method: str = "POST",
) -> str:
    sign_path = normalize_sign_path(url_or_path)
    values = extract_signed_value_list(method=method, url_or_path=url_or_path, body=body, params=params)
    raw = f"{saas_token}{sign_path}{''.join(values)}{secret}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# =========================
# 4) 请求头 / 日志打印
# =========================
def build_app_headers(json_body: bool = False, token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "Accept": "*/*",
        "User-Agent": CONFIG["app"]["user_agent"],
        "Connection": "keep-alive",
        "Accept-Language": CONFIG["app"]["accept_language"],
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    if token:
        headers["token"] = token
    return headers


def build_referer_from_filters(filters: Dict[str, Any]) -> str:
    q = copy.deepcopy(CONFIG["h5"]["referer_query_template"])
    mapping = {
        "acceptDateStart": filters.get("acceptDateStart"),
        "acceptDateEnd": filters.get("acceptDateEnd"),
        "commissionStatus": filters.get("commissionStatus"),
        "customerNoticeStatus": filters.get("customerNoticeStatus"),
        "keywords": filters.get("keywords"),
        "policyStatus": filters.get("policyStatus"),
        "productType": filters.get("productType"),
        "receiptStatus": filters.get("receiptStatus"),
        "revisitStatus": filters.get("revisitStatus"),
    }
    for key, value in mapping.items():
        if value is not None:
            q[key] = str(value)
    return f"{CONFIG['h5']['origin']}{CONFIG['h5']['referer_path']}?{urlencode(q)}"


def build_h5_headers(
    *,
    saas_token: str,
    secret: str,
    api_path: str,
    body: Optional[Any],
    referer: str,
    fixed_authorization: Optional[str] = None,
    add_token_header: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    method: str = "POST",
) -> Dict[str, str]:
    authorization = fixed_authorization or build_h5_authorization(
        saas_token=saas_token,
        url_or_path=api_path,
        body=body,
        secret=secret,
        method=method,
    )
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
        "User-Agent": CONFIG["h5"]["user_agent"],
        "Sec-Fetch-Dest": "empty",
        "Authorization": authorization,
        "Sec-Fetch-Mode": "cors",
        "Connection": "keep-alive",
        "Sec-Fetch-Site": "same-origin",
        "Content-Type": "application/json",
        "Accept-Language": CONFIG["h5"]["accept_language"],
        "Origin": CONFIG["h5"]["origin"],
    }
    if add_token_header:
        headers["token"] = add_token_header
    if extra_headers:
        headers.update(extra_headers)
    return headers


def build_h5_page_headers(referer: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": CONFIG["h5"]["user_agent"],
        "Accept-Language": CONFIG["h5"]["accept_language"],
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def print_request_preview(step: str, method: str, url: str, headers: Dict[str, str], body: Optional[Any]) -> None:
    log(step, f"{method.upper()} {url}")
    print("- headers:")
    print(pretty(mask_obj(headers)))
    print("- body:")
    print(pretty(mask_obj(body)))


def print_response_preview(resp: requests.Response) -> Optional[Dict[str, Any]]:
    print(f"- http_status: {resp.status_code}")
    try:
        data = resp.json()
        print("- response:")
        print(pretty(mask_obj(data)))
        return data if isinstance(data, dict) else None
    except Exception:
        print("- response_text:")
        print(resp.text[:1600])
        return None


# =========================
# 5) 缓存 / 通知
# =========================
def load_cache(cache_path: Path) -> Dict[str, Any]:
    if not cache_path.exists():
        return {
            "version": CONFIG["cache"]["version"],
            "created_at": now_local_iso(),
            "last_run_at": None,
            "last_success_at": None,
            "seen_policies": {},
            "last_snapshot": [],
        }
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("cache is not object")
        data.setdefault("version", CONFIG["cache"]["version"])
        data.setdefault("seen_policies", {})
        data.setdefault("last_snapshot", [])
        return data
    except Exception as exc:
        raise FlowError(f"读取缓存失败: {cache_path} -> {exc}")


def save_cache(cache_path: Path, data: Dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(cache_path.parent)) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    tmp_path.replace(cache_path)


def make_policy_key(row: Dict[str, Any]) -> str:
    policy_id = row.get("policyId")
    policy_no = row.get("policyNo")
    if policy_id not in (None, ""):
        return f"policyId:{policy_id}"
    if policy_no not in (None, ""):
        return f"policyNo:{policy_no}"
    digest = hashlib.md5(json_dumps_compact(row).encode("utf-8")).hexdigest()
    return f"digest:{digest}"


def normalize_policy_row(row: Dict[str, Any]) -> Dict[str, Any]:
    item = copy.deepcopy(row)
    item["_policyKey"] = make_policy_key(item)
    return item


def sort_policy_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(item: Dict[str, Any]) -> Tuple[int, float, str]:
        dt = parse_dateish(item.get("acceptDate")) or parse_dateish(item.get("issueTime")) or parse_dateish(item.get("commencementTime"))
        ts = dt.timestamp() if dt else 0.0
        return (0 if dt else 1, -ts, str(item.get("policyNo") or item.get("policyId") or ""))

    return sorted(rows, key=sort_key)


def trim_seen_policies(seen: Dict[str, Dict[str, Any]], max_entries: int) -> Dict[str, Dict[str, Any]]:
    if len(seen) <= max_entries:
        return seen

    def sort_key(pair: Tuple[str, Dict[str, Any]]) -> Tuple[float, str]:
        key, value = pair
        dt = parse_dateish(value.get("_lastSeenAt")) or parse_dateish(value.get("acceptDate")) or parse_dateish(value.get("issueTime"))
        ts = dt.timestamp() if dt else 0.0
        return (-ts, key)

    kept = dict(sorted(seen.items(), key=sort_key)[:max_entries])
    return kept


def diff_new_policies(
    cache: Dict[str, Any],
    current_rows: Sequence[Dict[str, Any]],
    *,
    notify_on_first_run: bool,
    now_iso: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    old_seen = cache.get("seen_policies") or {}
    if not isinstance(old_seen, dict):
        old_seen = {}

    current_map: Dict[str, Dict[str, Any]] = {}
    new_rows: List[Dict[str, Any]] = []

    for raw in current_rows:
        row = normalize_policy_row(raw)
        key = row["_policyKey"]
        current_map[key] = row
        if key not in old_seen:
            new_rows.append(row)

    if not old_seen and not notify_on_first_run:
        new_rows = []

    merged_seen: Dict[str, Dict[str, Any]] = copy.deepcopy(old_seen)
    for key, row in current_map.items():
        if key in merged_seen and isinstance(merged_seen[key], dict):
            existing = merged_seen[key]
            existing.update(row)
            existing.setdefault("_firstSeenAt", now_iso)
            existing["_lastSeenAt"] = now_iso
        else:
            row["_firstSeenAt"] = now_iso
            row["_lastSeenAt"] = now_iso
            merged_seen[key] = row

    merged_seen = trim_seen_policies(merged_seen, int(CONFIG["cache"]["max_seen_policies"]))
    new_rows = sort_policy_rows(new_rows)
    return new_rows, merged_seen


def format_policy_line(row: Dict[str, Any], index: Optional[int] = None, *, full_policy_no: bool = False) -> str:
    accept_dt = parse_dateish(row.get("acceptDate"))
    accept_text = accept_dt.strftime("%Y-%m-%d") if accept_dt else (str(row.get("acceptDate") or "")[:10])
    policy_no = str(row.get("policyNo") or "")
    policy_no_show = policy_no if full_policy_no else mask_text(policy_no, 6, 4)
    holder = mask_person_name(row.get("holderName"))
    insured = mask_person_name(row.get("insuredName"))
    premium = to_money_text(row.get("premium"))
    insurer = str(row.get("insurerName") or "")
    product = clip_text(row.get("productName") or "", 42)
    status = str(row.get("policyStatusDetail") or row.get("policyStatus") or "")
    prefix = f"{index:02d}. " if index is not None else "- "
    line1 = f"{prefix}{accept_text} | {policy_no_show} | {insurer} | {product}"
    line2 = f"    投保人:{holder} 被保人:{insured} 保费:{premium} 状态:{status}"
    return f"{line1}\n{line2}"


def print_policy_table(rows: Sequence[Dict[str, Any]], *, limit: int = 20, full_policy_no: bool = False) -> None:
    ordered = sort_policy_rows(rows)
    count = len(ordered)
    if count == 0:
        print("- policy_list: 空")
        return
    show = ordered if limit <= 0 else ordered[:limit]
    print(f"- policy_list_total: {count}")
    if limit > 0 and count > limit:
        print(f"- policy_list_shown: {len(show)}（其余 {count - len(show)} 条未展开）")
    else:
        print(f"- policy_list_shown: {len(show)}")
    for idx, row in enumerate(show, 1):
        print(format_policy_line(row, idx, full_policy_no=full_policy_no))


def build_notification_payload(
    new_rows: Sequence[Dict[str, Any]],
    current_rows: Sequence[Dict[str, Any]],
    filters: Dict[str, Any],
    *,
    full_policy_no: bool = False,
) -> Dict[str, Any]:
    ordered_new = sort_policy_rows(new_rows)
    title = f"新增保单 {len(ordered_new)} 笔"
    lines = [title]
    lines.append(f"查询范围: {filters.get('acceptDateStart', '')} ~ {filters.get('acceptDateEnd', '')}")
    lines.append(f"当前保单总数: {len(current_rows)}")
    lines.append("")
    for idx, row in enumerate(ordered_new[:10], 1):
        lines.append(format_policy_line(row, idx, full_policy_no=full_policy_no))
    if len(ordered_new) > 10:
        lines.append("")
        lines.append(f"其余 {len(ordered_new) - 10} 笔未展开")
    text = "\n".join(lines).strip()
    payload = {
        "title": title,
        "text": text,
        "count": len(ordered_new),
        "generated_at": now_local_iso(),
        "query": filters,
        "current_total": len(current_rows),
        "policies": ordered_new,
    }
    return payload


class Notifier:
    def __init__(self, webhook_url: Optional[str], notify_command: Optional[str], timeout: int = 20) -> None:
        self.webhook_url = webhook_url.strip() if webhook_url else ""
        self.notify_command = notify_command.strip() if notify_command else ""
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url or self.notify_command)

    def send(self, payload: Dict[str, Any]) -> None:
        failures: List[str] = []
        if self.webhook_url:
            try:
                self._send_webhook(payload)
            except Exception as exc:
                failures.append(f"webhook 失败: {exc}")
        if self.notify_command:
            try:
                self._send_command(payload)
            except Exception as exc:
                failures.append(f"notify-command 失败: {exc}")
        if failures:
            raise NotifyError("；".join(failures))

    def _send_webhook(self, payload: Dict[str, Any]) -> None:
        resp = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
        if resp.status_code >= 400:
            raise NotifyError(f"HTTP {resp.status_code}: {resp.text[:400]}")

    def _send_command(self, payload: Dict[str, Any]) -> None:
        payload_text = json.dumps(payload, ensure_ascii=False)
        env = os.environ.copy()
        env["POLICY_NOTIFY_TITLE"] = str(payload.get("title") or "")
        env["POLICY_NOTIFY_TEXT"] = str(payload.get("text") or "")
        env["POLICY_NOTIFY_JSON"] = payload_text
        proc = subprocess.run(
            self.notify_command,
            shell=True,
            input=payload_text.encode("utf-8"),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            raise NotifyError((proc.stderr or proc.stdout).decode("utf-8", errors="replace")[:800])


# =========================
# 6) 主流程客户端
# =========================
class PolicyMonitorClient:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.timeout = int(args.timeout)
        self.session = requests.Session()
        self.session.verify = bool(CONFIG.get("verify_tls", True)) and not bool(args.insecure)
        self.session.headers.update({"Connection": "keep-alive"})

        self.login_token: Optional[str] = None
        self.h5_saas_token: Optional[str] = None
        self.h5_saas_secret: str = env_or_default(args.h5_saas_secret, "H5_SAAS_SECRET", "")
        self.mine_page_data: Optional[Dict[str, Any]] = None
        self.notifier = Notifier(
            webhook_url=env_or_default(args.notify_webhook_url, "POLICY_NOTIFY_WEBHOOK_URL", ""),
            notify_command=env_or_default(args.notify_command, "POLICY_NOTIFY_COMMAND", ""),
            timeout=int(args.notify_timeout),
        )

    def app_url(self, path: str) -> str:
        return f"{CONFIG['app']['base_url']}{path}"

    def h5_url(self, path: str) -> str:
        return f"{CONFIG['h5']['base_url']}{path}"

    def current_filters(self) -> Dict[str, Any]:
        return {
            "pageNum": self.args.page_num,
            "pageSize": self.args.page_size,
            "productType": self.args.product_type,
            "receiptStatus": self.args.receipt_status,
            "revisitStatus": self.args.revisit_status,
            "commissionStatus": self.args.commission_status,
            "customerNoticeStatus": self.args.customer_notice_status,
            "keywords": self.args.keywords,
            "sort": self.args.sort,
            "policyStatus": self.args.policy_status,
            "policyType": self.args.policy_type,
            "acceptDateStart": self.args.accept_date_start,
            "acceptDateEnd": self.args.accept_date_end,
        }

    def send_json(
        self,
        step: str,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[Any],
        *,
        print_log: bool = True,
    ) -> StepResult:
        if print_log:
            print_request_preview(step, method, url, headers, body)

        if self.args.dry_run:
            print("- dry_run: True（未实际发请求）")
            return StepResult(name=step, status_code=0, json_data=None, text="")

        method = method.upper()
        if method == "POST":
            if body is None:
                resp = self.session.post(url, headers=headers, timeout=self.timeout)
            else:
                resp = self.session.post(url, json=body, headers=headers, timeout=self.timeout)
        elif method == "GET":
            resp = self.session.get(url, headers=headers, timeout=self.timeout)
        else:
            raise FlowError(f"暂不支持的方法: {method}")

        data = print_response_preview(resp)
        return StepResult(name=step, status_code=resp.status_code, json_data=data, text=resp.text)

    def build_login_payload(self) -> Dict[str, Any]:
        tpl = CONFIG["app"]["login_payload"]
        return {
            "password": get_runtime_credential(self.args.password, "APP_PASSWORD", tpl["password"]),
            "appFlag": tpl.get("appFlag", ""),
            "loginType": self.args.login_type if self.args.login_type is not None else tpl.get("loginType", "1"),
            "deviceNumber": get_runtime_credential(self.args.device_number, "APP_DEVICE_NUMBER", tpl["deviceNumber"]),
            "ip": self.args.ip if self.args.ip is not None else tpl.get("ip", ""),
            "captchaCode": self.args.captcha_code if self.args.captcha_code is not None else tpl.get("captchaCode", ""),
            "loginName": get_runtime_credential(self.args.login_name, "APP_LOGIN_NAME", tpl["loginName"]),
        }

    def extract_login_token(self, data: Optional[Dict[str, Any]]) -> str:
        if not isinstance(data, dict):
            raise FlowError("登录响应不是 JSON 对象")
        token = ((data.get("data") or {}).get("token") if isinstance(data, dict) else None) or ""
        if not token:
            raise FlowError("登录成功但未从响应里拿到 token")
        return token

    def ensure_h5_saas_token(self) -> str:
        if self.h5_saas_token:
            return self.h5_saas_token
        env_token = env_or_default(self.args.h5_saas_token, "H5_SAAS_TOKEN", "")
        if env_token:
            self.h5_saas_token = env_token
            return self.h5_saas_token
        if self.login_token:
            self.h5_saas_token = self.login_token
            return self.h5_saas_token
        raise FlowError("缺少 H5 SAAS token：请先登录，或手动传入 --h5-saas-token / H5_SAAS_TOKEN")

    def login(self) -> str:
        path = CONFIG["app"]["endpoints"]["login"]
        url = self.app_url(path)
        body = self.build_login_payload()
        headers = build_app_headers(json_body=True)
        result = self.send_json("LOGIN", "POST", url, headers, body)
        if self.args.dry_run:
            self.login_token = self.args.login_token or "<DRY_RUN_APP_TOKEN>"
            return self.login_token
        self.login_token = self.extract_login_token(result.json_data)
        return self.login_token

    def login_load_page(self) -> None:
        if not self.login_token:
            raise FlowError("还没有 APP 登录 token，不能请求 loginLoadPage")
        path = CONFIG["app"]["endpoints"]["login_load_page"]
        url = self.app_url(path)
        headers = build_app_headers(json_body=False, token=self.login_token)
        self.send_json("LOGIN_LOAD_PAGE", "POST", url, headers, None)

    def query_mine_page(self) -> None:
        if not self.login_token:
            raise FlowError("还没有 APP 登录 token，不能请求 queryMinePage")
        path = CONFIG["app"]["endpoints"]["query_mine_page"]
        url = self.app_url(path)
        headers = build_app_headers(json_body=False, token=self.login_token)
        result = self.send_json("QUERY_MINE_PAGE", "POST", url, headers, None)
        self.mine_page_data = (result.json_data or {}).get("data") if isinstance(result.json_data, dict) else None
        self.print_policy_permission_hint()

    def print_policy_permission_hint(self) -> None:
        data = self.mine_page_data or {}
        icons = data.get("iconResultVOs") or []
        found = None
        if isinstance(icons, list):
            for item in icons:
                if not isinstance(item, dict):
                    continue
                if item.get("iconCode") == "policyquery" or item.get("name") == "保单查询" or item.get("url") == "/index/policyQuery":
                    found = item
                    break
        if found:
            print("- mine_policy_entry: 已在 queryMinePage 中发现『保单查询』入口")
            print("  " + pretty(mask_obj(found)).replace("\n", "\n  "))
        else:
            warn("queryMinePage 返回里没有发现『保单查询』入口；后续 H5 401 时要重点怀疑权限本身")

    def h5_prewarm_page(self) -> StepResult:
        url = f"{CONFIG['h5']['origin']}{CONFIG['h5']['referer_path']}"
        headers = build_h5_page_headers()
        return self.send_json("H5_OPEN_POLICY_PAGE", "GET", url, headers, None)

    def h5_query_dict_info(self) -> StepResult:
        saas_token = self.ensure_h5_saas_token()
        path = CONFIG["h5"]["query_dict_info"]["path"]
        url = self.h5_url(path)
        body = copy.deepcopy(CONFIG["h5"]["query_dict_info"]["payload"])
        referer = f"{CONFIG['h5']['origin']}{CONFIG['h5']['referer_path']}"
        headers = build_h5_headers(
            saas_token=saas_token,
            secret=self.h5_saas_secret,
            api_path=path,
            body=body,
            referer=referer,
            fixed_authorization=None,
            add_token_header=self.login_token if self.args.h5_add_token_header else None,
            method="POST",
        )
        return self.send_json("H5_QUERY_DICT_INFO", "POST", url, headers, body)

    def build_list_policy_body(self, page_num: Optional[int] = None) -> Dict[str, Any]:
        tpl = CONFIG["h5"]["list_policy"]["payload"]
        body = merge_payload(
            tpl,
            pageNum=page_num if page_num is not None else self.args.page_num,
            pageSize=self.args.page_size,
            acceptDateStart=self.args.accept_date_start,
            acceptDateEnd=self.args.accept_date_end,
            keywords=self.args.keywords,
            policyStatus=self.args.policy_status,
            productType=self.args.product_type,
            receiptStatus=self.args.receipt_status,
            revisitStatus=self.args.revisit_status,
            commissionStatus=self.args.commission_status,
            customerNoticeStatus=self.args.customer_notice_status,
            sort=self.args.sort,
        )
        return body

    def build_commission_body(self) -> Dict[str, Any]:
        tpl = CONFIG["h5"]["commission"]["payload"]
        body = merge_payload(
            tpl,
            policyType=self.args.policy_type,
            acceptDateStart=self.args.accept_date_start,
            acceptDateEnd=self.args.accept_date_end,
            keywords=self.args.keywords,
            policyStatus=self.args.policy_status,
            productType=self.args.product_type,
            receiptStatus=self.args.receipt_status,
            revisitStatus=self.args.revisit_status,
            commissionStatus=self.args.commission_status,
            customerNoticeStatus=self.args.customer_notice_status,
            sort=self.args.sort,
        )
        return body

    def print_h5_auth_hint(self, api_path: str, body: Any, auth: str) -> None:
        if not self.args.trace_auth:
            return
        token = self.ensure_h5_saas_token()
        sign_path = normalize_sign_path(api_path)
        values = extract_signed_value_list("POST", api_path, body=body)
        print("- h5_auth_trace:")
        print(pretty(mask_obj({
            "saasToken": token,
            "saasSecret": self.h5_saas_secret,
            "signPath": sign_path,
            "valuesCount": len(values),
            "values": values,
            "authorization": auth,
        })))

    def list_policy_page(self, page_num: int) -> Tuple[StepResult, List[Dict[str, Any]], Optional[int]]:
        saas_token = self.ensure_h5_saas_token()
        path = CONFIG["h5"]["list_policy"]["path"]
        url = self.h5_url(path)
        body = self.build_list_policy_body(page_num=page_num)
        referer = build_referer_from_filters(body)
        fixed_authorization = env_or_default(self.args.h5_fixed_authorization, "H5_FIXED_AUTHORIZATION", "") or None
        headers = build_h5_headers(
            saas_token=saas_token,
            secret=self.h5_saas_secret,
            api_path=path,
            body=body,
            referer=referer,
            fixed_authorization=fixed_authorization,
            add_token_header=self.login_token if self.args.h5_add_token_header else None,
            method="POST",
        )
        self.print_h5_auth_hint(path, body, headers["Authorization"])
        result = self.send_json("LIST_POLICY", "POST", url, headers, body)
        rows, total = self.summarize_policy_response(result.json_data)
        return result, rows, total

    def summarize_policy_response(self, data: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        if not isinstance(data, dict):
            return [], None
        payload = data.get("data") or {}
        rows = payload.get("datas") or []
        total = payload.get("total")
        page_num = payload.get("pageNum")
        page_size = payload.get("pageSize")
        if total is not None:
            print(f"- policy_total: {total}")
        if page_num is not None and page_size is not None:
            print(f"- page: {page_num} / page_size={page_size}")
        if rows:
            print("- policy_brief_preview:")
            for idx, item in enumerate(rows[:5], 1):
                print(format_policy_line(item, idx, full_policy_no=False))
            if len(rows) > 5:
                print(f"  ... 其余 {len(rows) - 5} 条未展开")
        return rows if isinstance(rows, list) else [], int(total) if total not in (None, "") else None

    def fetch_all_policies(self) -> PolicyFetchResult:
        pages: List[StepResult] = []
        rows_all: List[Dict[str, Any]] = []
        total: Optional[int] = None

        first_result, first_rows, total = self.list_policy_page(page_num=self.args.page_num)
        pages.append(first_result)
        rows_all.extend(first_rows)

        if self.args.auto_page and not self.args.dry_run and total and self.args.page_size > 0:
            page_count = math.ceil(total / self.args.page_size)
            max_pages = self.args.max_pages if self.args.max_pages and self.args.max_pages > 0 else page_count
            for page in range(self.args.page_num + 1, min(page_count, max_pages) + 1):
                log("AUTO_PAGE", f"继续查询第 {page} 页")
                result, rows, _ = self.list_policy_page(page_num=page)
                pages.append(result)
                rows_all.extend(rows)

        rows_all = sort_policy_rows(rows_all)
        return PolicyFetchResult(pages=pages, rows=rows_all, total=total)

    def commission(self) -> StepResult:
        saas_token = self.ensure_h5_saas_token()
        path = CONFIG["h5"]["commission"]["path"]
        url = self.h5_url(path)
        body = self.build_commission_body()
        referer = build_referer_from_filters(body)
        fixed_authorization = env_or_default(self.args.h5_fixed_authorization, "H5_FIXED_AUTHORIZATION", "") or None
        headers = build_h5_headers(
            saas_token=saas_token,
            secret=self.h5_saas_secret,
            api_path=path,
            body=body,
            referer=referer,
            fixed_authorization=fixed_authorization,
            add_token_header=self.login_token if self.args.h5_add_token_header else None,
            method="POST",
        )
        self.print_h5_auth_hint(path, body, headers["Authorization"])
        result = self.send_json("COMMISSION", "POST", url, headers, body)
        data = (result.json_data or {}).get("data") if isinstance(result.json_data, dict) else None
        if data:
            print("- commission_summary:")
            print(pretty(data))
        return result

    def assert_policy_fetch_ok(self, fetch: PolicyFetchResult) -> None:
        if not fetch.pages:
            raise FlowError("没有拿到任何保单查询响应")
        first = fetch.pages[0]
        if first.status_code == 401:
            raise FlowError(
                "H5 listPolicy 返回 401。\n"
                "建议依次排查：\n"
                "1) 你的 H5 SAAS_TOKEN 可能不等于 APP 登录 token，尝试传 --h5-saas-token\n"
                "2) 你的设备里可能存在 SAAS_SECRET，尝试传 --h5-saas-secret\n"
                "3) 先用 --h5-fixed-authorization 验证当前环境下是否只差签名上下文\n"
                "4) 可加 --h5-add-token-header 试试把 APP token 一并带给 H5\n"
                "5) queryMinePage 虽然出现『保单查询』入口，但不代表 H5 后端一定放行"
            )
        if first.status_code >= 400:
            raise FlowError(f"保单查询失败，HTTP {first.status_code}")
        if not isinstance(first.json_data, dict):
            raise FlowError("保单查询响应不是 JSON 对象")
        code = first.json_data.get("code")
        success = first.json_data.get("success")
        if code not in (None, "10000") and success is not True:
            raise FlowError(f"保单查询业务失败: {pretty(mask_obj(first.json_data))}")

    def export_snapshot_json(self, rows: Sequence[Dict[str, Any]]) -> None:
        if not self.args.output_json:
            return
        output_path = Path(self.args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        info(f"已输出当前保单快照: {output_path}")

    def run(self) -> int:
        now_iso = now_local_iso()
        cache_path = Path(self.args.cache_file)
        cache = load_cache(cache_path)
        cache["last_run_at"] = now_iso

        if not self.args.skip_login:
            self.login()
            self.login_load_page()
            self.query_mine_page()
            self.h5_saas_token = env_or_default(self.args.h5_saas_token, "H5_SAAS_TOKEN", "") or self.login_token
            log("SIGN", "已准备 H5 SAAS_TOKEN / SAAS_SECRET，用于后续 Authorization 计算")
        else:
            self.login_token = env_or_default(self.args.login_token, "APP_LOGIN_TOKEN", "") or None
            self.h5_saas_token = env_or_default(self.args.h5_saas_token, "H5_SAAS_TOKEN", "") or self.login_token
            log("LOGIN", "按参数要求跳过 APP 登录")
            if self.h5_saas_token:
                info("已使用外部传入的 H5 SAAS token")

        if self.args.h5_prewarm and not self.args.skip_h5_prewarm:
            self.h5_prewarm_page()
            self.h5_query_dict_info()

        fetch = self.fetch_all_policies()
        if self.args.dry_run:
            log("POLICY_LIST", "dry-run 结束：已打印请求模板，未进入真实保单解析 / 缓存 / 通知阶段")
            if not self.args.skip_commission:
                self.commission()
            log("DONE", "dry-run 流程执行结束")
            return 0

        self.assert_policy_fetch_ok(fetch)

        log("POLICY_LIST", "整理后的保单列表")
        print_policy_table(fetch.rows, limit=self.args.print_limit, full_policy_no=self.args.full_policy_no)
        self.export_snapshot_json(fetch.rows)

        if not self.args.skip_commission:
            self.commission()

        new_rows, merged_seen = diff_new_policies(
            cache=cache,
            current_rows=fetch.rows,
            notify_on_first_run=self.args.notify_on_first_run,
            now_iso=now_iso,
        )

        if new_rows:
            log("NEW_POLICY", f"检测到新增保单 {len(new_rows)} 笔")
            print_policy_table(new_rows, limit=0, full_policy_no=self.args.full_policy_no)
            payload = build_notification_payload(
                new_rows=new_rows,
                current_rows=fetch.rows,
                filters=self.current_filters(),
                full_policy_no=self.args.full_policy_no,
            )
            print("- notify_preview:")
            print(payload["text"])
            if self.notifier.enabled:
                self.notifier.send(payload)
                info("新增保单通知已发送")
            else:
                info("未配置外部通知通道；本次只打印新增保单")
        else:
            log("NEW_POLICY", "本次没有新增保单")

        cache["last_success_at"] = now_iso
        cache["last_snapshot"] = fetch.rows
        cache["seen_policies"] = merged_seen
        cache["last_filters"] = self.current_filters()
        cache["last_total"] = fetch.total if fetch.total is not None else len(fetch.rows)
        save_cache(cache_path, cache)
        info(f"缓存已更新: {cache_path}")

        log("DONE", "流程执行结束")
        return 0


# =========================
# 7) 命令行
# =========================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="独立版保单监控脚本（保单列表 + JSON 缓存 + 新增保单通知）"
    )

    # 凭证 / 登录
    parser.add_argument("--login-name", help="覆盖 CONFIG 中的 loginName，也支持环境变量 APP_LOGIN_NAME")
    parser.add_argument("--password", help="覆盖 CONFIG 中的 password，也支持环境变量 APP_PASSWORD")
    parser.add_argument("--device-number", help="覆盖 CONFIG 中的 deviceNumber，也支持环境变量 APP_DEVICE_NUMBER")
    parser.add_argument("--login-type", help="覆盖 loginType，默认沿用 HAR 模板")
    parser.add_argument("--ip", help="覆盖 ip")
    parser.add_argument("--captcha-code", help="覆盖 captchaCode")
    parser.add_argument("--login-token", help="跳过登录时，手工传入 APP 登录 token，也支持 APP_LOGIN_TOKEN")

    # H5 签名上下文
    parser.add_argument("--h5-saas-token", help="手工指定 H5 SAAS_TOKEN，也支持 H5_SAAS_TOKEN")
    parser.add_argument("--h5-saas-secret", help="手工指定 H5 SAAS_SECRET，也支持 H5_SAAS_SECRET")
    parser.add_argument(
        "--h5-fixed-authorization",
        help="直接指定 H5 Authorization，用于验证当前环境下是否仅差签名，也支持 H5_FIXED_AUTHORIZATION",
    )
    parser.add_argument("--h5-add-token-header", action="store_true", help="给 H5 请求额外带上 token 头，便于排查 401")
    parser.add_argument("--trace-auth", action="store_true", help="打印 H5 签名明细（会做脱敏）")

    # 查询条件
    parser.add_argument("--page-num", type=int, default=1, help="listPolicy.pageNum，默认 1")
    parser.add_argument("--page-size", type=int, default=100, help="listPolicy.pageSize，默认 100")
    parser.add_argument("--accept-date-start", default=default_date_start(31), help="acceptDateStart，默认今天往前 31 天")
    parser.add_argument("--accept-date-end", default=today_str(), help="acceptDateEnd，默认今天")
    parser.add_argument("--keywords", default="", help="keywords")
    parser.add_argument("--policy-status", default="", help="policyStatus")
    parser.add_argument("--policy-type", default="0", help="commission.policyType，默认 0")
    parser.add_argument("--product-type", default="", help="productType")
    parser.add_argument("--receipt-status", default="", help="receiptStatus")
    parser.add_argument("--revisit-status", default="", help="revisitStatus")
    parser.add_argument("--commission-status", default="", help="commissionStatus")
    parser.add_argument("--customer-notice-status", default="", help="customerNoticeStatus")
    parser.add_argument("--sort", default="AD", help="sort，默认 AD")

    # 运行方式
    parser.add_argument("--skip-login", action="store_true", help="跳过 APP 登录")
    parser.add_argument("--skip-commission", action="store_true", help="跳过佣金汇总请求")
    parser.add_argument("--h5-prewarm", action="store_true", default=True, help="先打开 H5 页面并请求 queryDictInfo（默认开启）")
    parser.add_argument("--skip-h5-prewarm", action="store_true", help="关闭 H5 预热")
    parser.add_argument("--auto-page", action="store_true", default=True, help="根据 total 自动翻页（默认开启）")
    parser.add_argument("--max-pages", type=int, default=0, help="auto-page 时最多查询多少页；0 表示不限制")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要发送的请求，不实际发出")
    parser.add_argument("--timeout", type=int, default=int(CONFIG.get("timeout", 30)), help="请求超时秒数")
    parser.add_argument("--insecure", action="store_true", help="关闭 TLS 证书校验")

    # 输出 / 缓存
    parser.add_argument("--print-limit", type=int, default=20, help="整理后的保单列表最多打印多少条；0 表示全打")
    parser.add_argument("--full-policy-no", action="store_true", help="打印和通知里显示完整保单号")
    parser.add_argument("--cache-file", default="./policy_monitor_cache.json", help="本地 JSON 缓存文件路径")
    parser.add_argument("--output-json", help="把本次整理后的保单列表导出成 JSON 文件")

    # 通知
    parser.add_argument("--notify-on-first-run", action="store_true", help="第一次建立缓存时，也把当前保单视作新增并通知")
    parser.add_argument("--notify-webhook-url", help="通用 webhook 地址，也支持 POLICY_NOTIFY_WEBHOOK_URL")
    parser.add_argument(
        "--notify-command",
        help="自定义通知命令，也支持 POLICY_NOTIFY_COMMAND；命令会从 stdin 收到 JSON，并注入 POLICY_NOTIFY_* 环境变量",
    )
    parser.add_argument("--notify-timeout", type=int, default=20, help="通知请求超时秒数")

    return parser.parse_args()


# =========================
# 8) 主入口
# =========================
def main() -> int:
    args = parse_args()
    client = PolicyMonitorClient(args)
    return client.run()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] 用户中断")
        raise SystemExit(130)
    except NotifyError as exc:
        print(f"\n[NOTIFY_ERROR] {exc}")
        raise SystemExit(4)
    except FlowError as exc:
        print(f"\n[ERROR] {exc}")
        raise SystemExit(2)
    except requests.RequestException as exc:
        print(f"\n[NETWORK_ERROR] {exc}")
        raise SystemExit(3)
