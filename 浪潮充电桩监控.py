#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
QingLong Headless EV Charging Monitor (no GUI)
- 读取 charging_monitor_config.json（兼容你现有字段）
- stdout 日志：时间/级别/关键字段，适合青龙
- 低功率提醒（Bark，可选）
- 低功率持续 N 分钟：自动 stopCharging + 两次复检（每次观察 2~3 分钟）
- Bug 工具（可选）：随机等待 2~3 分钟，检测扣费立即停止；统计写 bug_stats.json
"""

import os, sys, json, time, math, random, threading, logging
from datetime import datetime, date
from urllib.parse import urlencode

import requests

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "charging_monitor_config.json")
BUG_STATS_FILE = os.path.join(APP_DIR, "bug_stats.json")

# ------------------- 日志 -------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("charging_monitor_ql")

def jdump(obj):
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)

# ------------------- 配置（兼容你的 config） -------------------
DEFAULT_CONFIG = {
    "bark_key": "",
    "bark_server": "https://api.day.app",
    "power_threshold_w": 30,
    "auto_stop_minutes_below_threshold": 3,
    "poll_seconds": 10,
    "token": "",
    "api_url": "https://jinjuli.sfjiayuan.com/api/OrderCharging/OrderChargingList",
    "user_info_url": "https://jinjuli.sfjiayuan.com/api/user/getUserInfo",
    "stop_url": "https://jinjuli.sfjiayuan.com/api/g/gateway/charging/stopCharging",
    "start_url": "https://jinjuli.sfjiayuan.com/api/g/gateway/charging/startCharging",
    "auto_stop_enabled": True,
    "bug_hour_limit": 3,
    "bug_wait_min_sec": 120,
    "bug_wait_max_sec": 180,
    # 青龙运行控制：默认跑 1 小时就退出（cron 周期运行更稳）
    "run_seconds": 3600,
}

def ensure_config_file():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)

def load_config():
    ensure_config_file()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 兼容你现有 env 覆盖（你原脚本就这样做）:contentReference[oaicite:4]{index=4}
    cfg["bark_key"] = os.getenv("BARK_KEY", cfg.get("bark_key", "<SENSITIVE>"))
    cfg["bark_server"] = os.getenv("BARK_SERVER", cfg.get("bark_server", DEFAULT_CONFIG["bark_server"]))
    cfg["power_threshold_w"] = int(os.getenv("POWER_THRESHOLD_W", cfg.get("power_threshold_w", DEFAULT_CONFIG["power_threshold_w"])))
    cfg["poll_seconds"] = int(os.getenv("POLL_SECONDS", cfg.get("poll_seconds", DEFAULT_CONFIG["poll_seconds"])))
    cfg["token"] = os.getenv("JINJULI_TOKEN", cfg.get("token", "<SENSITIVE>"))
    cfg["api_url"] = os.getenv("JINJULI_ORDER_URL", cfg.get("api_url", DEFAULT_CONFIG["api_url"]))
    cfg["user_info_url"] = os.getenv("JINJULI_USER_URL", cfg.get("user_info_url", DEFAULT_CONFIG["user_info_url"]))
    cfg["stop_url"] = os.getenv("JINJULI_STOP_URL", cfg.get("stop_url", DEFAULT_CONFIG["stop_url"]))
    cfg["start_url"] = os.getenv("JINJULI_START_URL", cfg.get("start_url", DEFAULT_CONFIG["start_url"]))

    # 青龙运行时长（可写死在 json 或用 env 覆盖）
    cfg["run_seconds"] = int(os.getenv("RUN_SECONDS", cfg.get("run_seconds", DEFAULT_CONFIG["run_seconds"])))

    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg

# ------------------- bug stats（沿用你原逻辑结构） -------------------
def load_bug_stats():
    if not os.path.exists(BUG_STATS_FILE):
        return {"by_day": {}, "by_month": {}}
    try:
        with open(BUG_STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"by_day": {}, "by_month": {}}

def save_bug_stats(stats):
    try:
        with open(BUG_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def add_bug_record(minutes, saved):
    stats = load_bug_stats()
    day = date.today().strftime("%Y-%m-%d")
    month = date.today().strftime("%Y-%m")
    d = stats["by_day"].setdefault(day, {"count": 0, "minutes": 0.0, "saved": 0.0})
    d["count"] += 1
    d["minutes"] += float(minutes)
    d["saved"] += float(saved)

    m = stats["by_month"].setdefault(month, {"count": 0, "minutes": 0.0, "saved": 0.0})
    m["count"] += 1
    m["minutes"] += float(minutes)
    m["saved"] += float(saved)
    save_bug_stats(stats)
    return stats

# ------------------- 工具函数 -------------------
def parse_number(v):
    try:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            return float(v.strip().replace(",", ""))
    except Exception:
        return None

def pick(d, *names, default=None):
    if not isinstance(d, dict):
        return default
    for n in names:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return default

def bark_push(bark_server, bark_key, title, body, **params):
    if not bark_key:
        return False, "No BARK_KEY"
    from requests.utils import quote
    url = f"{bark_server.rstrip('/')}/{bark_key}/{quote(title)}/{quote(body)}"
    if params:
        url += "?" + urlencode(params)
    try:
        r = requests.get(url, timeout=8)
        return (r.status_code == 200), f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

# ------------------- 核心类 -------------------
class QLChargingMonitor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sess = requests.Session()
        self.running = False

        self._below_thr_secs = 0
        self._alerted = False
        self._busy = False
        self._last_active_item = None
        self._last_power = None

        # bug mode
        self.bug_attempt_timestamps = []
        self.bug_stop = threading.Event()

    def _headers(self):
        h = {"content-type": "application/json"}
        if self.cfg.get("token"):
            h["token"] = self.cfg["token"]
        return h

    def fetch_user_info(self):
        try:
            r = self.sess.post(self.cfg["user_info_url"], headers=self._headers(), json={}, timeout=12)
            r.raise_for_status()
            js = r.json()
            data = pick(js, "data", default={})
            um = parse_number(pick(data, "user_money"))
            umz = parse_number(pick(data, "user_money_zs"))
            sm = parse_number(pick(data, "money_sum"))
            return {"sum": sm, "recharge": um, "gift": umz}
        except Exception as e:
            log.warning(f"余额请求失败: {e}")
            return None

    def fetch_orders(self, page=1, pagenum=10):
        try:
            payload = {"page": page, "pagenum": pagenum}
            r = self.sess.post(self.cfg["api_url"], headers=self._headers(), json=payload, timeout=12)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning(f"订单请求失败: {e}")
            return None

    def parse_active_order(self, js):
        data = pick(js, "data", "rows", "list", default=[])
        if isinstance(data, dict):
            data = pick(data, "data", "rows", "list", "items", default=[])
        items = data if isinstance(data, list) else []
        active = None
        for it in items:
            status = pick(it, "order_status", "status")
            try:
                if int(status) == 1:
                    active = it
                    break
            except Exception:
                pass
        return active, items

    def stop_charging(self, station_number, order_id, reason=""):
        payload = {
            "station_number": str(station_number),
            "command_code": "6",
            "error_code": 0,
            "order_id": int(order_id),
            "data": {"id": int(order_id), "token": ""},
        }
        try:
            r = self.sess.post(self.cfg["stop_url"], headers=self._headers(), json=payload, timeout=12)
            txt = (r.text or "")[:200].replace("\n", " ")
            ok = (r.status_code == 200)
            log.info(f"stopCharging => HTTP {r.status_code} ok={ok} {reason} resp={txt}")
            if self.cfg.get("bark_key"):
                bark_push(self.cfg["bark_server"], self.cfg["bark_key"],
                          "已发起停止充电", f"HTTP {r.status_code} {reason}", sound="shake", group="charging")
            return ok
        except Exception as e:
            log.warning(f"stopCharging 异常: {e}")
            return False

    def start_charging(self, station_sn, port):
        payload = {"station_sn": str(station_sn), "port": str(port),
                   "charging_type": 0, "value": 0, "is_full_stop": 0, "refer": 1}
        try:
            r = self.sess.post(self.cfg["start_url"], headers=self._headers(), json=payload, timeout=12)
            txt = (r.text or "")[:200].replace("\n", " ")
            log.info(f"startCharging => HTTP {r.status_code} resp={txt}")
            if r.status_code == 200:
                js = r.json()
                od = pick(js, "data", default={})
                order_id = pick(od, "order_id")
                return int(order_id) if order_id is not None else None
        except Exception as e:
            log.warning(f"startCharging 异常: {e}")
        return None

    def get_today_last_station_info(self):
        js = self.fetch_orders(page=1, pagenum=20)
        if not js:
            return None
        data = pick(js, "data", "rows", "list", default=[])
        if isinstance(data, dict):
            data = pick(data, "data", "rows", "list", "items", default=[])
        items = data if isinstance(data, list) else []

        today = str(date.today())
        today_items = [it for it in items if (pick(it, "start_time", "startTime", "") or "").startswith(today)]
        if not today_items:
            return None

        # 取列表里最新一条即可（你原 GUI 版也是“当日最后订单”思路）
        it = today_items[0]
        station_sn = str(pick(it, "station_code", "station_number", "station_sn") or "")
        port = str(pick(it, "socket_number", "port") or "")
        if station_sn and port:
            return {"station_sn": station_sn, "port": port}
        return None

    def auto_stop_with_recheck(self, active):
        if self._busy:
            return
        self._busy = True
        try:
            order_id = pick(active, "id", "order_id", "orderId")
            station_sn = pick(active, "station_code", "station_number", "station_sn")
            port = pick(active, "socket_number", "port")

            if not station_sn or not port:
                info = self.get_today_last_station_info()
                if info:
                    station_sn, port = info["station_sn"], info["port"]

            if order_id and station_sn:
                self.stop_charging(station_sn, order_id, reason="[auto stop trigger]")
                time.sleep(2)

            # 两次复检：每次 start -> 观察 2~3min -> 看功率 -> 决策 stop
            for i in range(2):
                info = self.get_today_last_station_info()
                if not info:
                    log.warning("复检：找不到当日订单用于定位设备/插座，结束复检。")
                    break
                station_sn, port = info["station_sn"], info["port"]
                new_order = self.start_charging(station_sn, port)
                if not new_order:
                    log.warning(f"复检{i+1}/2：startCharging 失败，跳过。")
                    continue

                wait_s = random.randint(120, 180)
                log.info(f"复检{i+1}/2：开始观察 {wait_s}s（心跳每 10s 输出一次）")
                end = time.time() + wait_s
                while time.time() < end:
                    js = self.fetch_orders(page=1, pagenum=10)
                    a, _ = self.parse_active_order(js) if js else (None, None)
                    p = parse_number(pick(a, "power")) if a else None
                    spend = parse_number(pick(a, "order_money")) if a else None
                    log.info(f"复检{i+1}/2 心跳：power={p}W spent={spend} order={pick(a,'id','order_id','orderId') if a else '--'}")
                    time.sleep(10)

                js = self.fetch_orders(page=1, pagenum=10)
                a, _ = self.parse_active_order(js) if js else (None, None)
                p = parse_number(pick(a, "power")) if a else None
                thr = int(self.cfg.get("power_threshold_w", 30))
                log.info(f"复检{i+1}/2 结果：power={p}W thr={thr}W")
                if p is None or p < thr:
                    self.stop_charging(station_sn, new_order, reason=f"[recheck{i+1}] p={p}")
                else:
                    log.info("复检功率正常，结束复检流程。")
                    break
        finally:
            self._below_thr_secs = 0
            self._alerted = False
            self._busy = False

    def poll_once(self):
        # 余额心跳
        bal = self.fetch_user_info()
        if bal:
            log.info(f"余额：sum={bal['sum']} recharge={bal['recharge']} gift={bal['gift']}")

        js = self.fetch_orders(page=1, pagenum=10)
        if not js:
            log.info("订单：无返回（请求失败），本轮结束。")
            return

        active, _ = self.parse_active_order(js)
        self._last_active_item = active

        if not active:
            if self._below_thr_secs:
                log.info("订单：无活动订单，清空低功率计时。")
            self._below_thr_secs = 0
            self._alerted = False
            log.info("状态：空闲/未充电")
            return

        # 活动订单信息
        order_id = pick(active, "id", "order_id", "orderId")
        station = pick(active, "station_code", "station_number", "station_sn")
        port = pick(active, "socket_number", "port")
        power = parse_number(pick(active, "power")) or 0.0
        spent = parse_number(pick(active, "order_money"))
        self._last_power = power

        log.info(f"状态：充电中 order={order_id} station={station} port={port} power={power}W spent={spent}")

        thr = int(self.cfg.get("power_threshold_w", 30))
        poll_s = max(2, int(self.cfg.get("poll_seconds", 10)))

        if power < thr:
            self._below_thr_secs += poll_s
            if not self._alerted and self.cfg.get("bark_key"):
                ok, msg = bark_push(self.cfg["bark_server"], self.cfg["bark_key"],
                                    "低功率提醒",
                                    f"功率 {int(power)}W < 阈值 {thr}W",
                                    sound="alarm", group="charging")
                log.info(f"Bark：ok={ok} msg={msg}")
                self._alerted = True
            log.info(f"低功率计时：{self._below_thr_secs}s / {int(self.cfg['auto_stop_minutes_below_threshold'])*60}s")
        else:
            if self._below_thr_secs:
                log.info("功率恢复正常，清空低功率计时。")
            self._below_thr_secs = 0
            self._alerted = False

        if self.cfg.get("auto_stop_enabled", True):
            hold_secs = int(self.cfg.get("auto_stop_minutes_below_threshold", 3)) * 60
            if self._below_thr_secs >= hold_secs and (not self._busy):
                log.warning(f"触发自动停止：power<{thr}W 已持续 {hold_secs}s")
                threading.Thread(target=self.auto_stop_with_recheck, args=(active,), daemon=True).start()

    # ------------------- Bug 模式（可选） -------------------
    def bug_mode_once(self):
        now = time.time()
        self.bug_attempt_timestamps = [t for t in self.bug_attempt_timestamps if now - t < 3600]
        if len(self.bug_attempt_timestamps) >= int(self.cfg.get("bug_hour_limit", 3)):
            log.warning("卡Bug：达到小时上限，本次跳过。")
            return

        info = self.get_today_last_station_info()
        if not info:
            log.warning("卡Bug：找不到当日订单用于定位 station/port。")
            return

        station_sn, port = info["station_sn"], info["port"]
        order_id = self.start_charging(station_sn, port)
        if not order_id:
            log.warning("卡Bug：startCharging 失败。")
            return
        self.bug_attempt_timestamps.append(time.time())

        mn = int(self.cfg.get("bug_wait_min_sec", 120))
        mx = int(self.cfg.get("bug_wait_max_sec", 180))
        wait_s = random.randint(mn, mx)

        start_ts = time.time()
        last_rate = None  # 如果你未来要根据阶梯价更精确，这里可以扩展

        for sec in range(wait_s):
            if self.bug_stop.is_set():
                break
            js = self.fetch_orders(page=1, pagenum=10)
            active, _ = self.parse_active_order(js) if js else (None, None)
            power = parse_number(pick(active, "power")) if active else None
            spend = parse_number(pick(active, "order_money")) if active else None
            left = wait_s - sec
            log.info(f"卡Bug倒计时：{left:>3}s power={power}W spent={spend}")
            if spend and spend > 0:
                log.warning(f"卡Bug：检测到已扣费 ¥{spend}，立即停止！")
                break
            time.sleep(1)

        duration_min = (time.time() - start_ts) / 60.0
        self.stop_charging(station_sn, order_id, reason="[bug mode]")

        # 你原脚本的计费周期/节省估算：30分钟一档；省=阶梯价/2×ceil(minutes/30)（UI版描述）:contentReference[oaicite:5]{index=5}
        # 这里如果没解析到阶梯价，就只统计分钟，不算 saved（避免瞎算）
        blocks = max(1, math.ceil(duration_min / 30.0))
        saved = 0.0
        add_bug_record(duration_min, saved)
        log.info(f"卡Bug结算：观察 {duration_min:.1f}min，计费块 {blocks}，saved={saved:.2f}（如需按阶梯价精算我可以继续补上）")

    def run(self, enable_bug=False):
        self.running = True
        start = time.time()
        run_seconds = int(self.cfg.get("run_seconds", 3600))

        log.info(f"启动：poll={self.cfg['poll_seconds']}s thr={self.cfg['power_threshold_w']}W auto_stop={self.cfg['auto_stop_enabled']} "
                 f"hold={self.cfg['auto_stop_minutes_below_threshold']}min run_seconds={run_seconds} bug={enable_bug}")

        while self.running and (time.time() - start) < run_seconds:
            try:
                self.poll_once()
                if enable_bug and (not self._busy):
                    # Bug 模式：每轮 poll 后尝试一次
                    self.bug_mode_once()
            except Exception as e:
                log.exception(f"主循环异常: {e}")
            time.sleep(max(2, int(self.cfg.get("poll_seconds", 10))))

        log.info("退出：达到运行时长或被停止。")

def main():
    cfg = load_config()

    # 命令行：python charging_monitor_ql.py bug
    enable_bug = (len(sys.argv) >= 2 and sys.argv[1].lower() in ("bug", "bugmode", "bug_mode"))

    mon = QLChargingMonitor(cfg)
    mon.run(enable_bug=enable_bug)

if __name__ == "__main__":
    main()
