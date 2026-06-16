#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中大自动约课统一版
=================================================
设计目标：
1. 一个 reserve.py 固定逻辑，不再为不同俱乐部复制脚本
2. 一个 zhongda_booking_config.json 管理：
   - clubs：俱乐部、ClubID、BrandCode、APPID、开抢时间
   - members：会员、OpenID、默认是否代理
   - tasks：谁在哪个俱乐部约哪天几点的课、坐哪个座位
   - proxy：代理 API 和兜底策略
   - global：并发、重试、时间容差等
3. 支持自动按当前时间匹配 club：
   - 例如周六 23:10 启动，只运行 run_schedule 为周六 23:10 的 ClubA
   - 周日 23:15 启动，只运行 ClubB
4. 支持手动调试：
   - --club ClubA
   - --task "小明-A店-周六杠铃-2号位"
   - --dry-run
5. 支持每个 task 单独指定：
   - reserve_weekday：约周几的课
   - class_time：精确开始时间，比如 18:20
   - time_window：时间窗，比如 ["18:00", "19:20"]
   - course：课程名
   - preferred_teacher：优先老师，默认不是硬条件
   - seat：rowNum / colNum
6. 支持代理：
   - task.use_proxy > member.use_proxy > proxy.enabled
   - 代理失败后可自动切回本机 IP
=================================================
"""

import argparse
import datetime as dt
import json
import os
import queue
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ========================= 常量 =========================
BASE_URL = "https://weixin.jianshenguanli.com/MemberInterface/WebService/Reservation.asmx"
URL_QUERY = f"{BASE_URL}/GetGroupLessonSchedule"
URL_RESERVE = f"{BASE_URL}/GroupLessonReservation"

WEEKDAY_CN = {
    0: "周一",
    1: "周二",
    2: "周三",
    3: "周四",
    4: "周五",
    5: "周六",
    6: "周日",
}

RESULTS_LOCK = threading.Lock()
TASK_RESULTS = []


# ========================= 基础工具 =========================
def now_str():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(scope, msg):
    print(f"[{now_str()}][{scope}] {msg}", flush=True)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def is_ascii(s):
    try:
        str(s).encode("ascii")
        return True
    except Exception:
        return False


def parse_hhmm(s):
    if not s:
        raise ValueError("empty time")
    s = str(s).strip()[:5]
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


def minutes_to_hhmm(m):
    m = m % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def compute_next_weekday_date(target_weekday, include_today=False):
    today = dt.date.today()
    offset = (int(target_weekday) - today.weekday()) % 7
    if offset == 0 and not include_today:
        offset = 7
    return today + dt.timedelta(days=offset)


def normalize_timeout(value, default):
    if isinstance(value, list) and len(value) == 2:
        return (float(value[0]), float(value[1]))
    if isinstance(value, tuple) and len(value) == 2:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return default


def record_result(item):
    with RESULTS_LOCK:
        TASK_RESULTS.append(item)


# ========================= 配置校验 / 合并 =========================
def get_global(config):
    return config.get("global", {})


def get_proxy_config(config):
    return config.get("proxy", {})


def build_headers(club, member):
    headers = {
        "Referer": club.get("Referer", f"https://servicewechat.com/{club['APPID']}/218/page-frame.html"),
        "OpenID": member["OpenID"],
        "BrandCode": club["BrandCode"],
        "ClubID": club["ClubID"],
        "IsNewAPP": "1",
        "User-Agent": club.get("User-Agent", "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X)"),
        "APPID": club["APPID"],
        "content-type": "application/json",
    }

    # 可选：如果会员配置里有 Cookie / Authorization，就加上
    for optional_key in ("Cookie", "Authorization"):
        if member.get(optional_key):
            headers[optional_key] = member[optional_key]

    for k, v in headers.items():
        if not is_ascii(v):
            raise ValueError(f"请求头 {k} 含非 ASCII 字符，请检查 OpenID/ClubID/BrandCode/APPID/Cookie。")

    for need in ["OpenID", "ClubID", "BrandCode", "APPID"]:
        if not headers.get(need):
            raise ValueError(f"缺少必要请求头：{need}")

    return headers


def resolve_task(config, task):
    clubs = config.get("clubs", {})
    members = config.get("members", {})

    club_name = task.get("club")
    member_name = task.get("member")

    if club_name not in clubs:
        raise KeyError(f"任务[{task.get('label')}]引用的 club 不存在：{club_name}")
    if member_name not in members:
        raise KeyError(f"任务[{task.get('label')}]引用的 member 不存在：{member_name}")

    club = clubs[club_name]
    member = members[member_name]

    return club_name, club, member_name, member


def should_use_proxy(config, task, member):
    proxy_cfg = get_proxy_config(config)

    # 优先级：task.use_proxy > member.use_proxy > proxy.enabled
    if "use_proxy" in task:
        return bool(task["use_proxy"])
    if "use_proxy" in member:
        return bool(member["use_proxy"])
    return bool(proxy_cfg.get("enabled", False))


# ========================= 自动按时间匹配 club =========================
def club_run_schedules(club):
    """
    支持两种格式：
    1) "run_schedule": {"weekday": 5, "time": "23:10"}
    2) "run_schedules": [{"weekday": 5, "time": "23:10"}, ...]
    """
    if isinstance(club.get("run_schedules"), list):
        return club["run_schedules"]
    if isinstance(club.get("run_schedule"), dict):
        return [club["run_schedule"]]
    return []


def match_clubs_by_current_time(config, now_dt=None):
    now_dt = now_dt or dt.datetime.now()
    current_weekday = now_dt.weekday()
    current_minute = now_dt.hour * 60 + now_dt.minute

    global_cfg = get_global(config)
    window = int(global_cfg.get("match_window_minutes", 2))

    matched = []
    for club_name, club in config.get("clubs", {}).items():
        for sched in club_run_schedules(club):
            try:
                sched_weekday = int(sched["weekday"])
                sched_minute = parse_hhmm(sched["time"])
            except Exception:
                continue

            if sched_weekday != current_weekday:
                continue

            diff = abs(current_minute - sched_minute)
            if diff <= window:
                matched.append({
                    "club_name": club_name,
                    "display_name": club.get("display_name", club_name),
                    "scheduled_time": sched.get("time"),
                    "diff_minutes": diff,
                })

    return matched


def select_tasks(config, args):
    tasks = [t for t in config.get("tasks", []) if t.get("enabled", True)]

    if args.task:
        selected = [t for t in tasks if t.get("label") == args.task]
        return selected, f"手动指定任务：{args.task}"

    if args.club:
        selected = [t for t in tasks if t.get("club") == args.club]
        return selected, f"手动指定俱乐部：{args.club}"

    if args.run_all:
        return tasks, "手动运行全部 enabled 任务"

    matched = match_clubs_by_current_time(config)

    if not matched:
        return [], "自动模式：当前时间没有匹配到任何 club"

    # 如果同一时间多个 club 匹配，则全部运行；也可以在 config 里把时间错开
    matched_names = {x["club_name"] for x in matched}
    selected = [t for t in tasks if t.get("club") in matched_names]

    info = "自动模式匹配到 club：" + ", ".join(
        f"{x['club_name']}({x['scheduled_time']}, 差{x['diff_minutes']}分钟)" for x in matched
    )
    return selected, info


# ========================= 代理相关 =========================
def fetch_proxy(proxy_cfg, scope):
    api_url = proxy_cfg.get("api_url", "")
    if not proxy_cfg.get("enabled", False) or not api_url:
        return None

    timeout = float(proxy_cfg.get("api_timeout", 4))
    try:
        r = requests.get(api_url, timeout=timeout)
        r.raise_for_status()
        j = r.json()
    except Exception as e:
        log(scope, f"代理 API 请求失败：{e}")
        return None

    # 兼容聚量 json2：{"code":200, "data":{"proxy_list":[{"ip":"x","port":"y"}]}}
    if isinstance(j, dict) and j.get("code") == 200:
        data = j.get("data", {})
        proxy_list = data.get("proxy_list", [])
        if proxy_list:
            first = proxy_list[0]
            ip = first.get("ip")
            port = first.get("port")
            if ip and port:
                raw = f"{ip}:{port}"
                proxy_url = f"http://{raw}"
                log(scope, f"已获取代理：{raw}")
                return {
                    "http": proxy_url,
                    "https": proxy_url,
                    "_raw": raw,
                    "_expire_at": time.time() + int(proxy_cfg.get("expire_seconds", 30)),
                }

    # 兼容一些普通格式：{"data":["ip:port"]} 或 ["ip:port"]
    candidates = []
    if isinstance(j, dict):
        if isinstance(j.get("data"), list):
            candidates = j["data"]
        elif isinstance(j.get("proxy_list"), list):
            candidates = j["proxy_list"]
    elif isinstance(j, list):
        candidates = j

    if candidates:
        first = candidates[0]
        raw = None
        if isinstance(first, str):
            raw = first
        elif isinstance(first, dict):
            ip = first.get("ip")
            port = first.get("port")
            if ip and port:
                raw = f"{ip}:{port}"

        if raw:
            proxy_url = f"http://{raw}"
            log(scope, f"已获取代理：{raw}")
            return {
                "http": proxy_url,
                "https": proxy_url,
                "_raw": raw,
                "_expire_at": time.time() + int(proxy_cfg.get("expire_seconds", 30)),
            }

    log(scope, f"代理 API 返回格式无法解析：{str(j)[:300]}")
    return None


def proxy_expired(proxy):
    return not proxy or time.time() >= proxy.get("_expire_at", 0)


def is_bad_proxy_error(exc):
    msg = str(exc).lower()
    if isinstance(exc, (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout)):
        return True
    keywords = [
        "cannot connect to proxy",
        "failed to establish a new connection",
        "connection refused",
        "network unreachable",
        "connect timeout",
        "proxyerror",
        "newconnectionerror",
    ]
    return any(k in msg for k in keywords)


class NetworkContext:
    def __init__(self, config, task_label, use_proxy):
        self.config = config
        self.proxy_cfg = get_proxy_config(config)
        self.task_label = task_label
        self.use_proxy = use_proxy and bool(self.proxy_cfg.get("enabled", False))
        self.current_proxy = None
        self.disabled = False
        self.swap_count = 0
        self.max_swap = int(self.proxy_cfg.get("max_swap_per_task", 2))
        self.fallback_to_local = bool(self.proxy_cfg.get("fallback_to_local", True))
        self.standby = queue.Queue(maxsize=1)

    def mark(self):
        if self.use_proxy and not self.disabled and self.current_proxy:
            return self.current_proxy.get("_raw", "PROXY")
        return "LOCAL"

    def ensure(self):
        if not self.use_proxy or self.disabled:
            return
        if not self.current_proxy:
            self.current_proxy = fetch_proxy(self.proxy_cfg, self.task_label)
            if self.current_proxy:
                self.start_prefetch()
            else:
                self.disable_or_local("首次代理获取失败")

    def start_prefetch(self):
        if not self.use_proxy or self.disabled:
            return
        if not self.standby.empty():
            return

        def worker():
            p = fetch_proxy(self.proxy_cfg, self.task_label)
            if p:
                try:
                    self.standby.put_nowait(p)
                    log(self.task_label, f"备用代理已就绪：{p['_raw']}")
                except queue.Full:
                    pass

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def refresh_if_needed(self):
        if not self.use_proxy or self.disabled:
            return
        if proxy_expired(self.current_proxy):
            self.switch("代理已过期")

    def disable_or_local(self, reason):
        self.current_proxy = None
        if self.fallback_to_local:
            self.disabled = True
            log(self.task_label, f"改用本机 IP：{reason}")
        else:
            raise RuntimeError(f"代理不可用，且未允许本机兜底：{reason}")

    def switch(self, reason):
        if not self.use_proxy or self.disabled:
            self.disable_or_local(reason)
            return

        if self.swap_count >= self.max_swap:
            self.disable_or_local(f"代理切换次数达到上限：{reason}")
            return

        new_proxy = None
        try:
            new_proxy = self.standby.get(timeout=float(self.proxy_cfg.get("prefetch_wait", 1.2)))
            log(self.task_label, f"切换到备用代理：{new_proxy['_raw']} | 原因：{reason}")
        except queue.Empty:
            log(self.task_label, f"备用代理未就绪，现场拉取新代理 | 原因：{reason}")
            new_proxy = fetch_proxy(self.proxy_cfg, self.task_label)

        if new_proxy:
            self.current_proxy = new_proxy
            self.swap_count += 1
            self.start_prefetch()
        else:
            self.disable_or_local(f"新代理获取失败：{reason}")


def request_with_context(method, url, net_ctx, **kwargs):
    net_ctx.refresh_if_needed()
    if net_ctx.use_proxy and not net_ctx.disabled and net_ctx.current_proxy:
        kwargs["proxies"] = {
            "http": net_ctx.current_proxy["http"],
            "https": net_ctx.current_proxy["https"],
        }
    return requests.request(method, url, **kwargs)


# ========================= 课表查询 / 选课 =========================
def parse_schedule_response(text):
    try:
        outer = json.loads(text)
    except Exception:
        raise RuntimeError(f"课表响应不是 JSON：{text[:300]}")

    if isinstance(outer, dict) and "d" in outer:
        data = json.loads(outer["d"])
    else:
        data = outer

    if not isinstance(data, list) and isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break

    if not isinstance(data, list):
        raise RuntimeError(f"课表响应格式异常：{type(data)} {str(data)[:300]}")

    return data


def query_schedule(schedule_date_iso, headers, config, net_ctx):
    global_cfg = get_global(config)
    timeout = normalize_timeout(global_cfg.get("query_timeout"), (2, 5))
    retry = int(global_cfg.get("max_query_retry", 2))
    verify_tls = bool(global_cfg.get("verify_tls", True))

    payload = {"scheduleDate": schedule_date_iso}
    last_exc = None

    for attempt in range(1, retry + 1):
        try:
            log(net_ctx.task_label, f"查询课表 {schedule_date_iso}，第 {attempt}/{retry} 次 | 网络={net_ctx.mark()}")
            r = request_with_context(
                "POST",
                URL_QUERY,
                net_ctx,
                json=payload,
                headers=headers,
                timeout=timeout,
                verify=verify_tls,
            )
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            return parse_schedule_response(r.text)
        except Exception as e:
            last_exc = e
            log(net_ctx.task_label, f"查询课表失败：{e}")
            if is_bad_proxy_error(e) and net_ctx.current_proxy:
                net_ctx.switch(f"查询阶段代理失败：{e}")
                continue
            if attempt < retry:
                time.sleep(float(global_cfg.get("retry_sleep_seconds", 0.3)))

    raise RuntimeError(f"连续 {retry} 次查询课表失败，最后异常：{last_exc}")


def preview_schedule(scope, schedule_list, limit=10):
    lines = []
    for i, it in enumerate(schedule_list[:limit], 1):
        lines.append(
            f"{i}. {it.get('GroupLessonName')} / {it.get('GLName')} "
            f"{it.get('StartTime')}-{it.get('EndTime')} "
            f"剩余:{it.get('SurplusNum')} | SID={it.get('ScheduleID')}"
        )
    if lines:
        log(scope, "当日课表预览：\n" + "\n".join(lines))


def within_task_time(start_time, task):
    start = str(start_time or "")[:5]
    if not start:
        return False

    # 精确时间模式：class_time = "18:20"
    if task.get("class_time"):
        return start == str(task["class_time"])[:5]

    # 多个优先精确时间：class_times = ["18:20", "18:30"]
    if isinstance(task.get("class_times"), list) and task["class_times"]:
        return start in [str(x)[:5] for x in task["class_times"]]

    # 时间窗模式：time_window = ["18:00", "19:20"]
    if isinstance(task.get("time_window"), list) and len(task["time_window"]) == 2:
        try:
            st = parse_hhmm(start)
            left = parse_hhmm(task["time_window"][0])
            right = parse_hhmm(task["time_window"][1])
            return left <= st <= right
        except Exception:
            return False

    # 没配置时间时，不限制，但不推荐
    return True


def choose_best_slot(schedule_list, task, require_surplus):
    course = task.get("course")
    preferred_teacher = task.get("preferred_teacher", "")
    hard_teacher = bool(task.get("teacher_required", False))

    candidates = []
    for it in schedule_list:
        if course and it.get("GroupLessonName") != course:
            continue

        if not within_task_time(it.get("StartTime"), task):
            continue

        teacher = it.get("GLName", "")
        if hard_teacher and preferred_teacher and teacher != preferred_teacher:
            continue

        surplus = safe_int(it.get("SurplusNum", 0), 0)
        if require_surplus and surplus <= 0:
            continue

        teacher_match = 1 if preferred_teacher and teacher == preferred_teacher else 0

        # 时间排序：如果有 class_time，用离 class_time 最近排序；否则用离 time_window 左侧最近排序
        start = str(it.get("StartTime", ""))[:5]
        try:
            st_min = parse_hhmm(start)
            if task.get("class_time"):
                time_score = abs(st_min - parse_hhmm(task["class_time"]))
            elif isinstance(task.get("class_times"), list) and task["class_times"]:
                time_score = min(abs(st_min - parse_hhmm(x)) for x in task["class_times"])
            elif isinstance(task.get("time_window"), list) and len(task["time_window"]) == 2:
                time_score = abs(st_min - parse_hhmm(task["time_window"][0]))
            else:
                time_score = 0
        except Exception:
            time_score = 9999

        candidates.append({
            "raw": it,
            "teacher_match": teacher_match,
            "surplus": surplus,
            "time_score": time_score,
        })

    if not candidates:
        return None

    candidates.sort(key=lambda x: (-x["teacher_match"], -x["surplus"], x["time_score"]))
    return candidates[0]["raw"]


# ========================= 预约提交 =========================
def parse_business_result(text):
    result = {"ok": False, "code": None, "msg": "", "raw": None}
    try:
        outer = json.loads(text)
        result["raw"] = outer
    except Exception:
        result["msg"] = f"非 JSON 响应：{text[:200]}"
        return result

    inner = outer
    if isinstance(outer, dict) and "d" in outer:
        try:
            inner = json.loads(outer["d"])
        except Exception:
            result["msg"] = f"外层 JSON 正常，但 d 不是合法 JSON：{outer.get('d', '')[:200]}"
            return result

    if not isinstance(inner, dict):
        result["msg"] = f"业务响应格式异常：{str(inner)[:200]}"
        return result

    code = inner.get("code")
    msg = str(inner.get("msg", "")).strip()

    result["code"] = code
    result["msg"] = msg
    result["raw"] = inner
    result["ok"] = (code == 1)
    return result


def code_meaning(code, msg):
    mapping = {
        1: "预约成功",
        -1: "业务失败/被拒绝",
        -2: "超过总部限制的最大预约数量",
        -3: "已经预约过或已加入备选，不能再次预约",
    }
    prefix = mapping.get(code, f"未知业务码 {code}")
    return f"{prefix}：{msg}" if msg else prefix


def submit_reservation(schedule_date_iso, picked, headers, config, task, net_ctx):
    global_cfg = get_global(config)
    timeout = normalize_timeout(global_cfg.get("reserve_timeout"), (2, 6))
    retry = int(global_cfg.get("max_reserve_retry", 2))
    verify_tls = bool(global_cfg.get("verify_tls", True))

    seat = task.get("seat", {})
    row_num = seat.get("rowNum", task.get("rowNum", 0))
    col_num = seat.get("colNum", task.get("colNum", 0))

    body = {
        "colNum": col_num,
        "groupLessondId": picked["GroupLessonID"],
        "rowNum": row_num,
        "scheduleDate": schedule_date_iso,
        "scheduleId": picked["ScheduleID"],
    }

    log(net_ctx.task_label, "提交预约 BODY:")
    log(net_ctx.task_label, json.dumps(body, ensure_ascii=False, indent=2))

    last_exc = None
    for attempt in range(1, retry + 1):
        try:
            log(net_ctx.task_label, f"提交预约，第 {attempt}/{retry} 次 | 网络={net_ctx.mark()}")
            r = request_with_context(
                "POST",
                URL_RESERVE,
                net_ctx,
                json=body,
                headers=headers,
                timeout=timeout,
                verify=verify_tls,
            )
            log(net_ctx.task_label, f"预约响应 HTTP {r.status_code}")
            log(net_ctx.task_label, "预约响应内容片段：" + r.text[:1200])

            biz = parse_business_result(r.text)
            return {
                "http_status": r.status_code,
                "response_text": r.text,
                "biz": biz,
                "body": body,
            }
        except Exception as e:
            last_exc = e
            log(net_ctx.task_label, f"预约提交失败：{e}")
            if is_bad_proxy_error(e) and net_ctx.current_proxy:
                net_ctx.switch(f"预约阶段代理失败：{e}")
                continue
            if attempt < retry:
                time.sleep(float(global_cfg.get("retry_sleep_seconds", 0.3)))

    raise RuntimeError(f"连续 {retry} 次预约未拿到有效响应，最后异常：{last_exc}")


# ========================= 单任务流程 =========================
def reserve_one_task(config, task, args):
    task_label = task.get("label") or f"{task.get('member')}->{task.get('club')}->{task.get('course')}"
    scope = task_label

    try:
        club_name, club, member_name, member = resolve_task(config, task)
        headers = build_headers(club, member)

        use_proxy = should_use_proxy(config, task, member)
        net_ctx = NetworkContext(config, task_label, use_proxy)
        net_ctx.ensure()

        # 预约哪一天的课：优先 args.date，其次 task.reserve_date，其次 task.reserve_weekday
        if args.date:
            schedule_date = dt.date.fromisoformat(args.date)
        elif task.get("reserve_date"):
            schedule_date = dt.date.fromisoformat(task["reserve_date"])
        else:
            reserve_weekday = int(task.get("reserve_weekday", task.get("weekday", dt.date.today().weekday())))
            include_today = bool(task.get("include_today", False))
            schedule_date = compute_next_weekday_date(reserve_weekday, include_today=include_today)

        schedule_date_iso = schedule_date.isoformat()
        require_surplus = bool(get_global(config).get("require_surplus", True))
        if args.allow_full:
            require_surplus = False
        if "require_surplus" in task:
            require_surplus = bool(task["require_surplus"])

        time_desc = task.get("class_time") or task.get("class_times") or task.get("time_window") or "不限时间"
        log(scope, (
            f"开始任务 | club={club_name} | member={member_name} | 日期={schedule_date_iso} "
            f"({WEEKDAY_CN.get(schedule_date.weekday(), schedule_date.weekday())}) | "
            f"课程={task.get('course')} | 目标时间={time_desc} | "
            f"优先老师={task.get('preferred_teacher','')} | "
            f"座位={task.get('seat', {})} | 需名额={require_surplus} | 代理={use_proxy}"
        ))

        if args.dry_run:
            record_result({
                "task": task_label,
                "status": "DRY_RUN",
                "detail": "只演练，不提交预约",
                "club": club_name,
                "member": member_name,
                "date": schedule_date_iso,
            })
            return

        schedule_list = query_schedule(schedule_date_iso, headers, config, net_ctx)
        preview_schedule(scope, schedule_list)

        picked = choose_best_slot(schedule_list, task, require_surplus)
        if picked is None:
            detail = f"未找到可预约课程：{task.get('course')} | 目标时间={time_desc} | require_surplus={require_surplus}"
            log(scope, detail)
            try:
                log(scope, "调试样例：\n" + json.dumps(schedule_list[:5], ensure_ascii=False, indent=2))
            except Exception:
                pass
            record_result({
                "task": task_label,
                "status": "NO_SLOT",
                "detail": detail,
                "club": club_name,
                "member": member_name,
                "date": schedule_date_iso,
            })
            return

        log(scope, (
            "命中课程："
            f"{picked.get('GroupLessonName')} / {picked.get('GLName')} / "
            f"{picked.get('StartTime')}-{picked.get('EndTime')} / "
            f"剩余 {picked.get('SurplusNum')} | SID={picked.get('ScheduleID')}"
        ))

        result = submit_reservation(schedule_date_iso, picked, headers, config, task, net_ctx)
        biz = result["biz"]
        if biz["ok"]:
            detail = code_meaning(biz["code"], biz["msg"])
            status = "SUCCESS"
        else:
            detail = code_meaning(biz["code"], biz["msg"])
            status = "FAILED"

        log(scope, f"任务结束：{status} | HTTP {result['http_status']} | {detail}")

        record_result({
            "task": task_label,
            "status": status,
            "detail": detail,
            "club": club_name,
            "member": member_name,
            "date": schedule_date_iso,
            "course": picked.get("GroupLessonName"),
            "teacher": picked.get("GLName"),
            "start": picked.get("StartTime"),
            "seat": result["body"],
            "http_status": result["http_status"],
            "biz_code": biz["code"],
        })

    except Exception as e:
        log(scope, f"任务异常：{e}")
        record_result({
            "task": task_label,
            "status": "ERROR",
            "detail": str(e),
        })


# ========================= 输出汇总 =========================
def print_selected_tasks(config, tasks, reason):
    print("=====================================================")
    print("中大统一预约脚本启动")
    print(f"当前时间：{now_str()} | {WEEKDAY_CN.get(dt.date.today().weekday())}")
    print(f"选择原因：{reason}")
    print(f"待执行任务数：{len(tasks)}")
    for idx, task in enumerate(tasks, 1):
        club = task.get("club")
        member = task.get("member")
        course = task.get("course")
        reserve_weekday = task.get("reserve_weekday", task.get("weekday", "未配置"))
        time_desc = task.get("class_time") or task.get("class_times") or task.get("time_window") or "不限时间"
        print(
            f"{idx}. {task.get('label')} | club={club} | member={member} | "
            f"约课星期={WEEKDAY_CN.get(reserve_weekday, reserve_weekday)} | "
            f"课程={course} | 上课时间={time_desc} | 座位={task.get('seat', {})}"
        )
    print("=====================================================")


def print_summary():
    print("\n==================== 任务结果汇总 ====================")
    if not TASK_RESULTS:
        print("没有任何任务结果。")
        return

    counts = {}
    for item in TASK_RESULTS:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    print("状态统计：" + " | ".join(f"{k}={v}" for k, v in counts.items()))

    for item in TASK_RESULTS:
        print(f"- [{item['status']}] {item.get('task')} -> {item.get('detail')}")
        more = []
        for k in ("club", "member", "date", "course", "teacher", "start", "http_status", "biz_code"):
            if item.get(k) not in (None, ""):
                more.append(f"{k}={item[k]}")
        if more:
            print("  " + " | ".join(more))
    print("=====================================================")


# ========================= 主入口 =========================
def parse_args():
    p = argparse.ArgumentParser(description="中大统一自动约课脚本")
    p.add_argument("--config", default="zhongda_booking_config.json", help="配置文件路径，默认 zhongda_booking_zhongda_booking_config.json")
    p.add_argument("--club", default=None, help="手动指定只运行某个 club 的任务")
    p.add_argument("--task", default=None, help="手动指定只运行某个 label 的任务")
    p.add_argument("--date", default=None, help="手动指定预约日期 YYYY-MM-DD，会覆盖 task.reserve_weekday")
    p.add_argument("--run-all", action="store_true", help="运行所有 enabled=true 的任务")
    p.add_argument("--dry-run", action="store_true", help="只打印将要执行的任务，不查询/不预约")
    p.add_argument("--allow-full", action="store_true", help="即使 SurplusNum=0 也尝试预约")
    return p.parse_args()


def main():
    args = parse_args()
    config = load_json(args.config)

    tasks, reason = select_tasks(config, args)
    print_selected_tasks(config, tasks, reason)

    if not tasks:
        print("没有匹配到任务。自动模式下请检查 clubs.*.run_schedule 与当前星期/时间是否对应。")
        return

    if args.dry_run:
        # dry-run 仍然走一下 reserve_one_task，用来显示解析结果，但不查课/不提交
        pass

    global_cfg = get_global(config)
    max_workers = int(global_cfg.get("max_workers", min(8, max(1, len(tasks)))))
    max_workers = max(1, min(max_workers, len(tasks)))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(reserve_one_task, config, task, args) for task in tasks]
        for f in as_completed(futures):
            f.result()

    print_summary()
    print("=== 全部任务结束 ===")


if __name__ == "__main__":
    main()
