#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""充电守护脚本（统一运行版 v7）

你现在只需要这一种常用运行方式：

    python3 charge_guard_unified_v7.py run --recover-rounds 5

逻辑：
1. 先看当前是不是已经在充
   - 如果已经在充：直接进入监控
2. 如果没在充：
   - 优先从当前页面拿 dev_id / socket_id
   - 拿不到就从“当天缓存”拿
   - 还拿不到才用脚本顶部默认值
   - 然后自动开始充电
   - 再进入监控

也就是说：
- 不再要求你手动传 --dev-id / --socket-id
- 不再保留 start / recover / bugfix 这种你平时不想维护的模式
- 更符合“扫码充电、我只想一键跑”的用法

保留逻辑：
- 高功率保护（>=295W 停充，等待 5~10 分钟后重启）
- 低功率检测（带启动宽限期）
- 跳档检测
- 僵功率检测
- 周期性主动复充
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

COOKIE = "<SENSITIVE>"
BARK_URL = "https://api.day.app/89XP9qZw3CerEANrnG2x4L/"
SHOW_RAW_JSON = False

POLL_INTERVAL = 20.0
REQUEST_TIMEOUT = 15

POWER_THRESHOLD_W = 40.0
MIN_BELOW_COUNT = 2

# 启动宽限：刚开始时功率刷新慢，先不要因为低功率停掉
STARTUP_GRACE_SECONDS = 300
LOW_POWER_MIN_CHARGE_SECONDS = 300
ZERO_POWER_IGNORE_SECONDS = 120
LOW_POWER_REQUIRE_FEE_CHANGE = False

ENABLE_JUMP_DETECT = True
JUMP_DELTA_W = 10.0
STOP_ON_JUMP = True

ENABLE_AUTO_RECOVER = True
AUTO_RECOVER_MAX_ROUNDS = 3
AUTO_RECOVER_WAIT_MIN = 120
AUTO_RECOVER_WAIT_MAX = 180
AUTO_RECOVER_STOP_WAIT = 2
WAIT_AFTER_SUCCESSFUL_RESTART = 5

BLANK_PAGE_CONSECUTIVE_LIMIT = 3
BLANK_PAGE_AUTO_RESTART = True

ENABLE_PERIODIC_REFRESH = True
PERIODIC_REFRESH_INTERVAL_MIN = 90
PERIODIC_REFRESH_MAX_TIMES = 3
PERIODIC_REFRESH_MIN_CHARGE_MIN = 60
PERIODIC_REFRESH_ONLY_WHEN_POWER_LE = 350.0

ENABLE_STABLE_POWER_REFRESH = True
STABLE_POWER_MIN_CHARGE_MIN = 180
STABLE_POWER_WINDOW_SAMPLES = 20
STABLE_POWER_RANGE_W = 3.0
STABLE_POWER_NOT_DROP_W = 1.0
STABLE_POWER_MAX_TRIGGERS = 2

ENABLE_HIGH_POWER_GUARD = True
HIGH_POWER_THRESHOLD_W = 350.0
HIGH_POWER_CONSECUTIVE_COUNT = 1
HIGH_POWER_STOP_WAIT = 2
HIGH_POWER_RESTART_WAIT_MIN = 300
HIGH_POWER_RESTART_WAIT_MAX = 600
HIGH_POWER_MAX_TRIGGERS = 3

# 自动开始前，如果当前已经在充，是否直接监控
RUN_MODE_MONITOR_IF_ALREADY_CHARGING = True

CHARGE_LEN = 999
IS_REMOTE = 1
INSURE_DC = 0
WAIT_START_CONFIRM = True

DEFAULT_DEV_ID = None
DEFAULT_SOCKET_ID = None

DEFAULT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 26_3_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.70(0x18004625) NetType/4G Language/zh_CN"
)

CACHE_FILE = Path("./last_charge_params.json")

BASE = "https://mapi.luxingiot.com"
CHARGE_SAVE_URL = f"{BASE}/mobile/index/charge_save"
CHARGE_IS_URL = f"{BASE}/mobile/index/charge_is"
CHARGE_STOP_URL = f"{BASE}/mobile/index/charge_stop"
ORDER_STOP_URL = f"{BASE}/mobile/order/orders_stop"
ORDER_STATUS_URL = f"{BASE}/mobile/order/orders_abnormal"
CHARGE_HTML_REFERER = f"{BASE}/mobile/index/charge.html"
CHARGE_IS_REFERER = f"{BASE}/mobile/index/charge_is"

HTML_PATTERNS = {
    "port_label": r'<div class="duankou">\s*([^<]+?)\s*</div>',
    "base_electric_price": r'基础电价：<span[^>]*>([^<]+)</span>',
    "service_fee_mode": r'服务费计费方式：<span[^>]*>([^<]+)</span>',
}

JS_VAR_PATTERNS = {
    "dev_id": r'var\s+dev_id\s*=\s*"([^"]*)"',
    "socket_id": r'var\s+socket_id\s*=\s*"([^"]*)"',
    "order_no": r'var\s+order_no\s*=\s*"([^"]*)"',
    "seconds": r'var\s+seconds\s*=\s*"([^"]*)"',
    "rate_seconds": r'var\s+rate_seconds\s*=\s*"([^"]*)"',
    "rate": r'var\s+rate\s*=\s*"([^"]*)"',
    "rate_money": r'var\s+rate_money\s*=\s*"([^"]*)"',
    "kwh": r'var\s+kwh\s*=\s*"([^"]*)"',
    "power": r'var\s+power\s*=\s*"([^"]*)"',
    "voltage": r'var\s+v\s*=\s*"([^"]*)"',
}

POWER_TIERS = [
    (100.0, "0.06元/小时", "100W以下"),
    (150.0, "0.08元/小时", "150W以下"),
    (400.0, "0.13元/小时", "400W以下"),
    (3000.0, "0.28元/小时", "3000W以下"),
]


@dataclass
class ChargePageState:
    dev_id: Optional[str] = None
    socket_id: Optional[str] = None
    order_no: Optional[str] = None
    seconds: Optional[str] = None
    rate_seconds: Optional[str] = None
    rate: Optional[str] = None
    rate_money: Optional[str] = None
    kwh: Optional[str] = None
    power: Optional[float] = None
    voltage: Optional[str] = None
    port_label: Optional[str] = None
    base_electric_price: Optional[str] = None
    service_fee_mode: Optional[str] = None
    raw_html: str = ""


@dataclass
class CachedChargeParams:
    dev_id: Optional[str] = None
    socket_id: Optional[str] = None
    order_no: Optional[str] = None
    cached_date: Optional[str] = None
    updated_at: Optional[str] = None


class ChargeGuardError(RuntimeError):
    pass


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def bark_push(title: str, body: str, timeout: int = 10) -> None:
    if not BARK_URL:
        return
    url = f"{BARK_URL.rstrip('/')}/{quote(title)}/{quote(body)}"
    try:
        requests.get(url, timeout=timeout)
    except Exception as exc:
        print(f"[{now_text()}] [Bark 推送失败] {exc}", file=sys.stderr)


def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": DEFAULT_UA,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": BASE,
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    if COOKIE:
        s.headers["Cookie"] = COOKIE
    return s


def set_form_headers(session: requests.Session, referer: str) -> None:
    session.headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    session.headers["Referer"] = referer


def set_html_headers(session: requests.Session, referer: str) -> None:
    session.headers.pop("Content-Type", None)
    session.headers["Referer"] = referer


def safe_json_or_text(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text


def format_hms(seconds: Optional[str]) -> str:
    try:
        total = int(float(seconds or 0))
    except (TypeError, ValueError):
        return "--:--:--"
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_seconds(seconds: Optional[str]) -> int:
    try:
        return int(float(seconds or 0))
    except (TypeError, ValueError):
        return 0


def parse_rate_money_cent(rate_money: Optional[str]) -> int:
    try:
        return int(float(rate_money or 0))
    except (TypeError, ValueError):
        return 0


def format_rate_money(rate_money: Optional[str]) -> str:
    if rate_money in (None, "", "-"):
        return "-"
    try:
        return f"{(Decimal(str(rate_money)) / Decimal('100')):.2f}"
    except (InvalidOperation, ValueError):
        return str(rate_money)


def get_service_rate(power: Optional[float]) -> str:
    if power is None:
        return "-"
    for upper, fee, _label in POWER_TIERS:
        if power < upper:
            return fee
    return "档位未知"


def get_tier_label(power: Optional[float]) -> str:
    if power is None:
        return "未知档位"
    for upper, _fee, label in POWER_TIERS:
        if power < upper:
            return label
    return ">=3000W"


def parse_charge_page(html: str) -> ChargePageState:
    values: dict[str, Optional[str]] = {}
    for key, pat in JS_VAR_PATTERNS.items():
        m = re.search(pat, html)
        values[key] = m.group(1) if m else None

    extras: dict[str, Optional[str]] = {}
    for key, pat in HTML_PATTERNS.items():
        m = re.search(pat, html)
        extras[key] = m.group(1).strip() if m else None

    power_value = None
    if values.get("power") not in (None, "", "-"):
        try:
            power_value = float(values["power"])
        except ValueError:
            power_value = None

    return ChargePageState(
        dev_id=values.get("dev_id"),
        socket_id=values.get("socket_id"),
        order_no=values.get("order_no"),
        seconds=values.get("seconds"),
        rate_seconds=values.get("rate_seconds"),
        rate=values.get("rate"),
        rate_money=values.get("rate_money"),
        kwh=values.get("kwh"),
        power=power_value,
        voltage=values.get("voltage"),
        port_label=extras.get("port_label"),
        base_electric_price=extras.get("base_electric_price"),
        service_fee_mode=extras.get("service_fee_mode"),
        raw_html=html,
    )


def infer_current_rate(state: ChargePageState) -> str:
    if state.service_fee_mode and "按功率" not in state.service_fee_mode:
        return f"{state.service_fee_mode}"
    base = state.base_electric_price or "0.555元/度"
    return f"基础电价 {base} + 服务费 {get_service_rate(state.power)}"


def human_summary(state: ChargePageState) -> str:
    device_port = state.port_label or (f"{state.socket_id}设备端口" if state.socket_id else "未知设备端口")
    charge_time = format_hms(state.seconds)
    power_text = f"{state.power:.1f}W" if state.power is not None else "-"
    fee_text = format_rate_money(state.rate_money)
    current_rate = infer_current_rate(state)
    return (
        f"{device_port} | 充电时间 {charge_time} | 计费功率 {power_text} | "
        f"当前费率：{current_rate} | 当前费用：{fee_text}元"
    )


def print_state(prefix: str, state: ChargePageState) -> None:
    print(f"\n{prefix}")
    print(f"[{now_text()}] {human_summary(state)}")


def save_last_params(dev_id: Optional[str], socket_id: Optional[str], order_no: Optional[str]) -> None:
    data = CachedChargeParams(
        dev_id=str(dev_id) if dev_id else None,
        socket_id=str(socket_id) if socket_id else None,
        order_no=str(order_no) if order_no else None,
        cached_date=today_text(),
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    try:
        CACHE_FILE.write_text(json.dumps(asdict(data), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[{now_text()}] [缓存保存失败] {exc}", file=sys.stderr)


def load_last_params_today() -> Optional[CachedChargeParams]:
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[{now_text()}] [缓存读取失败] {exc}", file=sys.stderr)
        return None
    if data.get("cached_date") != today_text():
        return None
    return CachedChargeParams(
        dev_id=data.get("dev_id"),
        socket_id=data.get("socket_id"),
        order_no=data.get("order_no"),
        cached_date=data.get("cached_date"),
        updated_at=data.get("updated_at"),
    )


def update_cache_from_state(state: ChargePageState) -> None:
    if state.dev_id or state.socket_id or state.order_no:
        save_last_params(state.dev_id, state.socket_id, state.order_no)


def fetch_charge_page(session: requests.Session) -> ChargePageState:
    set_html_headers(session, f"{BASE}/mobile/personal.html")
    resp = session.get(CHARGE_IS_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return parse_charge_page(resp.text)


def fetch_current_state_safely(session: requests.Session) -> Optional[ChargePageState]:
    try:
        state = fetch_charge_page(session)
        update_cache_from_state(state)
        return state
    except Exception as exc:
        print(f"[{now_text()}] [提示] 读取当前充电状态失败：{exc}", file=sys.stderr)
        return None


def is_actively_charging(state: Optional[ChargePageState]) -> bool:
    if state is None:
        return False
    # 有订单号 + 设备参数即可视为当前处于充电页/充电态，避免 seconds=0 时误判为未充
    return bool(state.order_no and state.dev_id and state.socket_id)


def start_charge(session: requests.Session, dev_id: int | str, socket_id: int | str) -> dict[str, Any]:
    set_form_headers(session, CHARGE_HTML_REFERER)
    resp = session.post(
        CHARGE_SAVE_URL,
        data={
            "dev_id": str(dev_id),
            "socket_id": str(socket_id),
            "charge_len": str(CHARGE_LEN),
            "is_remote": str(IS_REMOTE),
            "insure_dc": str(INSURE_DC),
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return safe_json_or_text(resp)


def query_order_status(session: requests.Session, order_no: str) -> dict[str, Any]:
    set_form_headers(session, CHARGE_HTML_REFERER)
    resp = session.post(ORDER_STATUS_URL, data={"order_no": order_no}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return safe_json_or_text(resp)


def stop_charge(session: requests.Session, dev_id: str, socket_id: str, order_no: str) -> dict[str, Any]:
    set_form_headers(session, CHARGE_IS_REFERER)
    resp = session.post(
        CHARGE_STOP_URL,
        data={"dev_id": dev_id, "socket_id": socket_id, "order_no": order_no},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return safe_json_or_text(resp)


def confirm_stop(session: requests.Session, order_no: str) -> Any:
    set_form_headers(session, CHARGE_IS_REFERER)
    resp = session.post(ORDER_STOP_URL, data={"order_no": order_no}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return resp.text


def stop_and_confirm(session: requests.Session, state: ChargePageState) -> int:
    if not (state.dev_id and state.socket_id and state.order_no):
        raise ChargeGuardError("页面里缺少 dev_id/socket_id/order_no，无法自动停止。")
    print(f"\n[{now_text()}] [动作] 发起结束充电。")
    stop_charge(session, state.dev_id, state.socket_id, state.order_no)
    time.sleep(16)
    confirm_stop(session, state.order_no)
    return 0


def maybe_extract_order_no(start_resp: Any) -> Optional[str]:
    if isinstance(start_resp, dict) and start_resp.get("code") == 1 and start_resp.get("msg"):
        return str(start_resp["msg"])
    return None


def wait_until_charge_started(session: requests.Session, order_no: Optional[str]) -> bool:
    if not WAIT_START_CONFIRM or not order_no:
        return True
    for i in range(1, 6):
        if i > 1:
            time.sleep(2)
        status = query_order_status(session, order_no)
        if isinstance(status, dict) and status.get("socket_startstatus") == "00":
            print(f"\n[{now_text()}] 充电已正常开始。")
            return True
    print(f"[{now_text()}] [提示] 未确认到“正常开始”，继续后续观察。")
    return False


def restart_charge(session: requests.Session, dev_id: str, socket_id: str) -> Optional[str]:
    print(f"\n[{now_text()}] [动作] 尝试重新开始充电：dev_id={dev_id}, socket_id={socket_id}")
    try:
        start_resp = start_charge(session, dev_id, socket_id)
    except requests.RequestException as exc:
        print(f"[{now_text()}] [重启失败] {exc}", file=sys.stderr)
        bark_push("充电自动重启失败", str(exc))
        return None
    print("[restart charge_save response]")
    print(json.dumps(start_resp, ensure_ascii=False, indent=2))
    order_no = maybe_extract_order_no(start_resp)
    if order_no:
        print(f"[{now_text()}] [动作] 重启成功，订单号：{order_no}")
        save_last_params(dev_id, socket_id, order_no)
        bark_push("充电已自动重启", f"订单号：{order_no}")
    wait_until_charge_started(session, order_no)
    return order_no


def observe_after_restart(session: requests.Session, seconds: int) -> Optional[ChargePageState]:
    print(f"[{now_text()}] [复检] 重启后观察 {seconds} 秒。")
    deadline = time.time() + max(1, seconds)
    last_state: Optional[ChargePageState] = None
    while time.time() < deadline:
        try:
            state = fetch_charge_page(session)
        except requests.RequestException:
            time.sleep(min(POLL_INTERVAL, 3))
            continue
        last_state = state
        update_cache_from_state(state)
        print_state("[复检监控]", state)
        if state.power is not None and state.power >= POWER_THRESHOLD_W:
            return state
        sleep_s = min(max(1.0, POLL_INTERVAL), max(1.0, deadline - time.time()))
        time.sleep(sleep_s)
    return last_state


def auto_recover_flow(session: requests.Session, state: ChargePageState, trigger_reason: str, recover_rounds: int) -> bool:
    if not ENABLE_AUTO_RECOVER:
        stop_and_confirm(session, state)
        return False
    if not (state.dev_id and state.socket_id):
        raise ChargeGuardError("当前页面缺少 dev_id/socket_id，无法执行自动重启复检。")

    total_rounds = max(1, recover_rounds)
    print(f"\n[{now_text()}] [触发] {trigger_reason}")
    bark_push("充电守护触发自动启停", trigger_reason)
    stop_and_confirm(session, state)
    time.sleep(max(0, AUTO_RECOVER_STOP_WAIT))

    last_state: Optional[ChargePageState] = None
    for round_no in range(1, total_rounds + 1):
        print(f"\n[{now_text()}] [自动复检] 第 {round_no}/{total_rounds} 轮")
        new_order_no = restart_charge(session, state.dev_id, state.socket_id)
        if not new_order_no:
            print(f"[{now_text()}] [自动复检] 本轮未拿到新订单号。")

        wait_s = random.randint(min(AUTO_RECOVER_WAIT_MIN, AUTO_RECOVER_WAIT_MAX),
                                max(AUTO_RECOVER_WAIT_MIN, AUTO_RECOVER_WAIT_MAX))
        recovered_state = observe_after_restart(session, wait_s)
        last_state = recovered_state
        if recovered_state is None:
            print(f"[{now_text()}] [自动复检] 本轮复检未拿到页面状态。")
            continue
        if recovered_state.power is not None and recovered_state.power >= POWER_THRESHOLD_W:
            print(f"[{now_text()}] [自动复检] 已恢复成功，当前功率 {recovered_state.power:.1f}W。")
            if WAIT_AFTER_SUCCESSFUL_RESTART > 0:
                time.sleep(WAIT_AFTER_SUCCESSFUL_RESTART)
            return True

        bad_power_text = "-" if recovered_state.power is None else f"{recovered_state.power:.1f}W"
        print(f"[{now_text()}] [自动复检] 本轮未恢复，复检结束功率：{bad_power_text}。")
        if recovered_state.dev_id and recovered_state.socket_id and recovered_state.order_no:
            stop_and_confirm(session, recovered_state)
        time.sleep(max(0, AUTO_RECOVER_STOP_WAIT))

    last_power_text = "-"
    if last_state is not None and last_state.power is not None:
        last_power_text = f"{last_state.power:.1f}W"
    msg = f"自动复检失败：{trigger_reason}；已尝试 {total_rounds} 轮，最后功率 {last_power_text}"
    print(f"[{now_text()}] [自动复检失败] {msg}", file=sys.stderr)
    bark_push("充电自动复检失败", msg)
    return False


def high_power_guard_needed(state: ChargePageState, hit_count: int, trigger_count: int) -> bool:
    if not ENABLE_HIGH_POWER_GUARD or trigger_count >= HIGH_POWER_MAX_TRIGGERS or state.power is None:
        return False
    return hit_count >= HIGH_POWER_CONSECUTIVE_COUNT and state.power >= HIGH_POWER_THRESHOLD_W


def high_power_guard_flow(session: requests.Session, state: ChargePageState) -> int:
    if not (state.dev_id and state.socket_id):
        raise ChargeGuardError("高功率保护时缺少 dev_id/socket_id，无法重启。")
    msg = f"检测到高功率 {state.power:.1f}W >= {HIGH_POWER_THRESHOLD_W:.1f}W，停止并延迟重启"
    print(f"\n[{now_text()}] [高功率保护] {msg}")
    bark_push("高功率保护触发", msg)
    stop_and_confirm(session, state)
    time.sleep(max(0, HIGH_POWER_STOP_WAIT))
    wait_s = random.randint(min(HIGH_POWER_RESTART_WAIT_MIN, HIGH_POWER_RESTART_WAIT_MAX),
                            max(HIGH_POWER_RESTART_WAIT_MIN, HIGH_POWER_RESTART_WAIT_MAX))
    print(f"[{now_text()}] [高功率保护] 等待 {wait_s} 秒后重新开始充电。")
    time.sleep(wait_s)
    restart_charge(session, state.dev_id, state.socket_id)
    if WAIT_AFTER_SUCCESSFUL_RESTART > 0:
        time.sleep(WAIT_AFTER_SUCCESSFUL_RESTART)
    return 0


def periodic_refresh_needed(state: ChargePageState, periodic_refresh_count: int, last_periodic_refresh_charge_sec: int) -> bool:
    if not ENABLE_PERIODIC_REFRESH or periodic_refresh_count >= PERIODIC_REFRESH_MAX_TIMES or state.power is None:
        return False
    charge_sec = parse_seconds(state.seconds)
    if charge_sec < PERIODIC_REFRESH_MIN_CHARGE_MIN * 60:
        return False
    if state.power > PERIODIC_REFRESH_ONLY_WHEN_POWER_LE:
        return False
    if last_periodic_refresh_charge_sec <= 0:
        return charge_sec >= PERIODIC_REFRESH_INTERVAL_MIN * 60
    return (charge_sec - last_periodic_refresh_charge_sec) >= PERIODIC_REFRESH_INTERVAL_MIN * 60


def stable_power_trigger_reason(power_samples: deque[float], state: ChargePageState, stable_trigger_count: int) -> Optional[str]:
    if not ENABLE_STABLE_POWER_REFRESH or stable_trigger_count >= STABLE_POWER_MAX_TRIGGERS or state.power is None:
        return None
    charge_sec = parse_seconds(state.seconds)
    if charge_sec < STABLE_POWER_MIN_CHARGE_MIN * 60 or len(power_samples) < STABLE_POWER_WINDOW_SAMPLES:
        return None
    values = list(power_samples)[-STABLE_POWER_WINDOW_SAMPLES:]
    p_min, p_max = min(values), max(values)
    p_first, p_last = values[0], values[-1]
    p_range = p_max - p_min
    drop = p_first - p_last
    if p_range <= STABLE_POWER_RANGE_W and drop <= STABLE_POWER_NOT_DROP_W:
        window_min = int(STABLE_POWER_WINDOW_SAMPLES * POLL_INTERVAL / 60)
        return (
            f"功率疑似被卡住：最近约 {window_min} 分钟保持在 "
            f"{p_min:.1f}~{p_max:.1f}W，起点 {p_first:.1f}W，终点 {p_last:.1f}W，"
            f"当前已充 {format_hms(state.seconds)}"
        )
    return None


def low_power_allowed(state: ChargePageState, first_charge_seen_ts: float, first_fee_cent: int) -> tuple[bool, str]:
    charge_sec = parse_seconds(state.seconds)
    if charge_sec < LOW_POWER_MIN_CHARGE_SECONDS:
        return False, f"实际充电时长未到 {LOW_POWER_MIN_CHARGE_SECONDS} 秒"
    runtime_sec = time.time() - first_charge_seen_ts
    if runtime_sec < STARTUP_GRACE_SECONDS:
        return False, f"启动宽限期未到 {STARTUP_GRACE_SECONDS} 秒"
    if (state.power or 0) <= 0 and charge_sec < ZERO_POWER_IGNORE_SECONDS:
        return False, f"前 {ZERO_POWER_IGNORE_SECONDS} 秒的 0W 视为刷新延迟"
    if LOW_POWER_REQUIRE_FEE_CHANGE:
        current_fee_cent = parse_rate_money_cent(state.rate_money)
        if current_fee_cent <= first_fee_cent:
            return False, "费用未变化，暂不做低功率判定"
    return True, ""


def is_blank_idle_state(state: ChargePageState) -> bool:
    return not any([state.dev_id, state.socket_id, state.order_no]) and state.power is None and parse_seconds(state.seconds) == 0


def try_restart_from_cache_or_raise(session: requests.Session, reason: str) -> None:
    dev_id, socket_id = resolve_params_for_auto_start(session)
    print(f"[{now_text()}] [兜底拉起] {reason}，尝试重新开始：dev_id={dev_id}, socket_id={socket_id}")
    start_resp = start_charge(session, dev_id, socket_id)
    print("[charge_save response]")
    print(json.dumps(start_resp, ensure_ascii=False, indent=2))

    order_no = maybe_extract_order_no(start_resp)
    if not order_no:
        raise ChargeGuardError(f"{reason}，兜底重启时未拿到订单号。")

    save_last_params(dev_id, socket_id, order_no)
    bark_push("空闲页后已自动重启", f"订单号：{order_no}")
    wait_until_charge_started(session, order_no)


def resolve_params_for_auto_start(session: requests.Session) -> tuple[str, str]:
    # 1. 先从当前页面拿
    current_state = fetch_current_state_safely(session)
    if current_state and current_state.dev_id and current_state.socket_id:
        print(f"[{now_text()}] [run] 已从当前页面拿到当天参数。")
        return current_state.dev_id, current_state.socket_id

    # 2. 再从当天缓存拿
    cached = load_last_params_today()
    if cached and cached.dev_id and cached.socket_id:
        print(f"[{now_text()}] [run] 已从当天缓存拿到参数。")
        return cached.dev_id, cached.socket_id

    # 3. 最后兜底默认值
    if DEFAULT_DEV_ID is not None and DEFAULT_SOCKET_ID is not None:
        print(f"[{now_text()}] [run] 已从脚本默认值拿到参数。")
        return str(DEFAULT_DEV_ID), str(DEFAULT_SOCKET_ID)

    raise ChargeGuardError("当前未在充电，且没有可用的当天参数/默认参数，无法自动开始。")


def unified_run(session: requests.Session) -> None:
    current_state = fetch_current_state_safely(session)

    if RUN_MODE_MONITOR_IF_ALREADY_CHARGING and is_actively_charging(current_state):
        print(f"[{now_text()}] [run] 检测到当前已经在充电，直接进入监控。")
        bark_push("已检测到充电中", "直接进入监控")
        return

    dev_id, socket_id = resolve_params_for_auto_start(session)
    print(f"[{now_text()}] [run] 当前未在充电，准备自动开始：dev_id={dev_id}, socket_id={socket_id}")

    start_resp = start_charge(session, dev_id, socket_id)
    print("[charge_save response]")
    print(json.dumps(start_resp, ensure_ascii=False, indent=2))

    order_no = maybe_extract_order_no(start_resp)
    if order_no:
        print(f"\n[{now_text()}] 检测到订单号: {order_no}")
        save_last_params(dev_id, socket_id, order_no)
        bark_push("充电已开始", f"订单号：{order_no}")
        wait_until_charge_started(session, order_no)
    else:
        print(f"[{now_text()}] [提示] start 接口未返回可识别订单号，继续监控。")


def monitor_until_stop(session: requests.Session, recover_rounds: int, max_checks: int) -> int:
    below_count = 0
    high_power_hit_count = 0
    high_power_trigger_count = 0
    checks = 0
    previous_power: Optional[float] = None
    previous_tier: Optional[str] = None
    last_periodic_refresh_charge_sec = 0
    periodic_refresh_count = 0
    power_samples: deque[float] = deque(maxlen=max(STABLE_POWER_WINDOW_SAMPLES, 60))
    stable_trigger_count = 0
    blank_idle_count = 0

    first_charge_seen_ts = time.time()
    first_fee_cent: Optional[int] = None

    while True:
        checks += 1
        try:
            state = fetch_charge_page(session)
        except requests.RequestException as exc:
            print(f"[{now_text()}] [监控请求失败] {exc}", file=sys.stderr)
            if max_checks and checks >= max_checks:
                return 2
            time.sleep(POLL_INTERVAL)
            continue

        update_cache_from_state(state)
        print_state(f"[监控 #{checks}]", state)

        if is_blank_idle_state(state):
            blank_idle_count += 1
            print(f"[{now_text()}] [空闲页检测] 连续 {blank_idle_count}/{BLANK_PAGE_CONSECUTIVE_LIMIT} 次。")
            if BLANK_PAGE_AUTO_RESTART and blank_idle_count >= BLANK_PAGE_CONSECUTIVE_LIMIT:
                try_restart_from_cache_or_raise(session, "检测到页面持续处于未充电空闲态")
                blank_idle_count = 0
                below_count = 0
                high_power_hit_count = 0
                previous_power = None
                previous_tier = None
                first_charge_seen_ts = time.time()
                first_fee_cent = None
                power_samples.clear()
                time.sleep(max(3, WAIT_AFTER_SUCCESSFUL_RESTART))
                continue
        else:
            blank_idle_count = 0

        charge_sec = parse_seconds(state.seconds)
        fee_cent = parse_rate_money_cent(state.rate_money)
        if first_fee_cent is None:
            first_fee_cent = fee_cent

        if state.power is not None:
            power_samples.append(state.power)

        if state.power is not None and state.power >= HIGH_POWER_THRESHOLD_W:
            high_power_hit_count += 1
        else:
            high_power_hit_count = 0

        if high_power_guard_needed(state, high_power_hit_count, high_power_trigger_count):
            high_power_trigger_count += 1
            high_power_hit_count = 0
            high_power_guard_flow(session, state)
            blank_idle_count = 0
            first_charge_seen_ts = time.time()
            first_fee_cent = None
            power_samples.clear()
            previous_power = None
            previous_tier = None
            time.sleep(max(3, WAIT_AFTER_SUCCESSFUL_RESTART))
            continue

        if periodic_refresh_needed(state, periodic_refresh_count, last_periodic_refresh_charge_sec):
            msg = (
                f"按实际充电时长触发周期复充：当前已充 {format_hms(state.seconds)}，"
                f"当前功率 {state.power:.1f}W，"
                f"第 {periodic_refresh_count + 1}/{PERIODIC_REFRESH_MAX_TIMES} 次"
            )
            print(f"[{now_text()}] [周期复充] {msg}")
            periodic_refresh_count += 1
            last_periodic_refresh_charge_sec = charge_sec
            if not auto_recover_flow(session, state, f"周期复充触发：{msg}", recover_rounds=recover_rounds):
                try_restart_from_cache_or_raise(session, "周期复充后复检失败")
            blank_idle_count = 0
            first_charge_seen_ts = time.time()
            first_fee_cent = None
            power_samples.clear()
            previous_power = None
            previous_tier = None
            time.sleep(max(3, WAIT_AFTER_SUCCESSFUL_RESTART))
            continue

        stable_reason = stable_power_trigger_reason(power_samples, state, stable_trigger_count)
        if stable_reason:
            print(f"[{now_text()}] [僵功率检测] {stable_reason}")
            stable_trigger_count += 1
            if not auto_recover_flow(session, state, stable_reason, recover_rounds=recover_rounds):
                try_restart_from_cache_or_raise(session, "僵功率复检失败")
            blank_idle_count = 0
            first_charge_seen_ts = time.time()
            first_fee_cent = None
            power_samples.clear()
            previous_power = None
            previous_tier = None
            time.sleep(max(3, WAIT_AFTER_SUCCESSFUL_RESTART))
            continue

        if state.power is not None:
            current_tier = get_tier_label(state.power)
            if ENABLE_JUMP_DETECT and previous_power is not None and previous_tier is not None:
                jumped = current_tier != previous_tier and state.power - previous_power >= JUMP_DELTA_W
                if jumped:
                    msg = (
                        f"检测到功率跳档：{previous_power:.1f}W({previous_tier}) -> "
                        f"{state.power:.1f}W({current_tier})"
                    )
                    print(f"[{now_text()}] [告警] {msg}")
                    if STOP_ON_JUMP:
                        if not auto_recover_flow(session, state, f"跳档触发：{msg}", recover_rounds=recover_rounds):
                            try_restart_from_cache_or_raise(session, "跳档复检失败")
                        blank_idle_count = 0
                        first_charge_seen_ts = time.time()
                        first_fee_cent = None
                        power_samples.clear()
                        previous_power = None
                        previous_tier = None
                        time.sleep(max(3, WAIT_AFTER_SUCCESSFUL_RESTART))
                        continue
            previous_power = state.power
            previous_tier = current_tier

        if state.power is None:
            print(f"[{now_text()}] [提示] 当前页面未解析出功率，跳过这次判定。", file=sys.stderr)
        elif state.power < POWER_THRESHOLD_W:
            allowed, reason = low_power_allowed(state, first_charge_seen_ts, first_fee_cent or 0)
            if not allowed:
                print(f"[{now_text()}] [低功率宽限] 功率 {state.power:.1f}W，暂不判停：{reason}")
                below_count = 0
            else:
                below_count += 1
                msg = (
                    f"功率 {state.power:.1f}W < 阈值 {POWER_THRESHOLD_W:.1f}W，"
                    f"连续低于阈值次数：{below_count}/{MIN_BELOW_COUNT}"
                )
                print(f"[{now_text()}] [提示] {msg}")
                if below_count >= MIN_BELOW_COUNT:
                    below_count = 0
                    if not auto_recover_flow(session, state, f"低功率触发：{state.power:.1f}W", recover_rounds=recover_rounds):
                        try_restart_from_cache_or_raise(session, "低功率复检失败")
                    blank_idle_count = 0
                    first_charge_seen_ts = time.time()
                    first_fee_cent = None
                    power_samples.clear()
                    previous_power = None
                    previous_tier = None
                    time.sleep(max(3, WAIT_AFTER_SUCCESSFUL_RESTART))
                    continue
        else:
            if below_count:
                print(f"[{now_text()}] [提示] 功率恢复正常，低功率计数清零。")
            below_count = 0

        if max_checks and checks >= max_checks:
            print(f"\n[{now_text()}] [结束] 已达到最大监控次数，未触发自动动作。")
            return 0

        time.sleep(POLL_INTERVAL)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="充电守护脚本（统一运行版）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="一键运行：已在充电就监控，未充就自动开始后监控")
    p_run.add_argument("--recover-rounds", type=int, default=AUTO_RECOVER_MAX_ROUNDS)
    p_run.add_argument("--max-checks", type=int, default=0)

    p_monitor = sub.add_parser("monitor", help="只监控当前充电")
    p_monitor.add_argument("--recover-rounds", type=int, default=AUTO_RECOVER_MAX_ROUNDS)
    p_monitor.add_argument("--max-checks", type=int, default=0)

    sub.add_parser("show-last", help="查看当天缓存的最后一次参数")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not COOKIE:
        print(f"[{now_text()}] [提示] 你还没在脚本顶部填 COOKIE。", file=sys.stderr)

    session = build_session()

    try:
        if args.cmd == "show-last":
            cached = load_last_params_today()
            if cached is None:
                print("当天没有可用缓存。")
                return 0
            print(json.dumps(asdict(cached), ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "run":
            unified_run(session)
            return monitor_until_stop(session, recover_rounds=args.recover_rounds, max_checks=args.max_checks)

        if args.cmd == "monitor":
            return monitor_until_stop(session, recover_rounds=args.recover_rounds, max_checks=args.max_checks)

        parser.error("未知命令")
        return 2

    except requests.HTTPError as exc:
        print(f"[{now_text()}] [HTTP ERROR] {exc}", file=sys.stderr)
        if exc.response is not None:
            print(exc.response.text, file=sys.stderr)
        return 2
    except requests.RequestException as exc:
        print(f"[{now_text()}] [REQUEST ERROR] {exc}", file=sys.stderr)
        return 2
    except ChargeGuardError as exc:
        print(f"[{now_text()}] [脚本错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
