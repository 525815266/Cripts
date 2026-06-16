#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
中大约课：军悦店固定2节任务版（快速代理切换优化版）
=================================================
功能说明：
1. 多账号并发：账号之间并发执行
2. 账号内任务并发：同一账号的固定2节任务也并发执行
3. 固定2个任务：
   - 下一个周二：小程序-Zumba (优先教练: 邢丹丹，上课时间窗:11:40-12:20)
   - 下一个周六：小程序-Zumba (优先教练: 邢丹丹，上课时间窗:16:40-17:20)
4. 课程筛选规则：
   - 课程名必须匹配
   - 老师名只做优先匹配，不是硬条件（防止临时换老师）
   - 时间只限制在对应时间窗内，不要求精确到某一分钟
5. 代理逻辑：
   - PROXY_SWITCH = 1：开启代理
   - PROXY_SWITCH = 0：关闭代理，全部走本机 IP
   - 每“1节课任务”使用 1 个主代理
   - 每个任务会后台预取 1 个备用代理
   - 同一节课的查课 / 提交 / 重试，都尽量复用当前代理
   - 如果代理 API 获取失败：立即放弃代理模式，后续全部改用本机 IP
   - 如果代理在任务过程中连接失败：坏代理立即判死，优先切备用代理，不在同一个坏代理上长时间傻等
6. 业务结果判定：
   - 仅 code=1 视为预约成功
   - 其余 code 明确打印失败原因
=================================================
"""

import datetime as dt
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, Tuple, List

import requests
from requests.exceptions import ProxyError, ConnectTimeout, ReadTimeout, ConnectionError, SSLError, RequestException

# ========================= 多账号配置 =========================
ACCOUNTS = [
    # {
    #     "name": "李晨",
    #     "OpenID": "<SENSITIVE>",
    #     "ClubID": "57115e05-ea7e-4411-b062-c2bb5d5f1b36",
    #     "BrandCode": "8961",
    #     "APPID": "wx3bb18aff4f2fe45f",
    #     "rowNum": 0,
    #     "colNum": 2,
    # },
    {
        "name": "文嘉",
        "OpenID": "<SENSITIVE>",
        "ClubID": "01756162-8680-4890-99c4-c5f20f60e6fe",  # 军悦店
        "BrandCode": "8961",
        "APPID": "wx3bb18aff4f2fe45f",
        "rowNum": 0,
        "colNum": 1,
    },
]

# ========================= 固定任务配置 =========================
# weekday: 0=周一 ... 1=周二 ... 5=周六
FIXED_RESERVATION_TASKS = [
    {
        "label": "周二-Zumba",
        "weekday": 1,
        "course": "小程序-Zumba",
        "preferred_teacher": "邢丹丹",
        "time_window": ("11:40", "12:20"),
    },
    {
        "label": "周六-Zumba",
        "weekday": 5,
        "course": "小程序-Zumba",
        "preferred_teacher": "邢丹丹",
        "time_window": ("16:40", "17:20"),
    },
]

# ========================= 代理配置 =========================
PROXY_SWITCH = 1

PROXY_API_URL = (
    "http://v2.api.juliangip.com/company/postpay/getips"
    "?auto_white=1&num=1&pt=1&result_type=json2"
    "&trade_no=6032883265129567"
    "&sign=0981aff8ce96c51ecf5770f136c9bb71"
)

PROXY_EXPIRE_SECONDS = 30
PROXY_API_TIMEOUT = 5

# 一旦代理 API 获取失败，就全局切本机
_PROXY_RUNTIME_ENABLED = True
_PROXY_RUNTIME_LOCK = threading.Lock()

# ========================= 接口地址 =========================
BASE_URL = "https://weixin.jianshenguanli.com/MemberInterface/WebService/Reservation.asmx"
URL_QUERY = f"{BASE_URL}/GetGroupLessonSchedule"
URL_RESERVE = f"{BASE_URL}/GroupLessonReservation"
VERIFY_TLS = True

# ========================= 超时 / 重试 =========================
# 这里做了“连接超时”和“读超时”拆分：
# 坏代理通常死在连接阶段，所以连接超时压短，避免卡太久
TIMEOUT_QUERY = (2, 5)
TIMEOUT_RESERVE = (2, 6)

MAX_QUERY_RETRY = 2
MAX_RESERVE_RETRY = 2

REQUIRE_SURPLUS_DEFAULT = True
RETRY_SLEEP_SECONDS = 0.25

# 每个任务最多换几次代理，避免死循环
MAX_PROXY_ROTATE_PER_TASK = 2

# ========================= 日志与工具 =========================
def log(acc_name: str, msg: str):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}][{acc_name}] {msg}", flush=True)

def is_ascii(s):
    if s is None:
        return True
    try:
        str(s).encode("ascii")
        return True
    except Exception:
        return False

def safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default

def parse_hhmm(s: str):
    parts = s.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])

def compute_next_weekday_date(target_weekday: int) -> dt.date:
    today = dt.date.today()
    offset = (target_weekday - today.weekday()) % 7 or 7
    return today + dt.timedelta(days=offset)

def build_headers_for_account(acc: dict):
    headers = {
        "Referer": "https://servicewechat.com/wx3bb18aff4f2fe45f/218/page-frame.html",
        "OpenID": acc["OpenID"],
        "BrandCode": acc["BrandCode"],
        "ClubID": acc["ClubID"],
        "IsNewAPP": "1",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X)",
        "APPID": acc["APPID"],
        "content-type": "application/json",
    }

    if "Cookie" in acc and acc["Cookie"]:
        headers["Cookie"] = acc["Cookie"]
    if "Authorization" in acc and acc["Authorization"]:
        headers["Authorization"] = acc["Authorization"]

    for k, v in headers.items():
        if not is_ascii(v):
            raise ValueError(f"账号[{acc.get('name')}] 的请求头 {k} 含非 ASCII 字符。")
    for need in ["OpenID", "ClubID", "BrandCode", "APPID"]:
        if not headers.get(need):
            raise ValueError(f"账号[{acc.get('name')}] 缺少必要头: {need}")
    return headers

# ========================= 代理相关 =========================
def is_proxy_runtime_enabled():
    with _PROXY_RUNTIME_LOCK:
        return PROXY_SWITCH == 1 and _PROXY_RUNTIME_ENABLED

def disable_proxy_runtime(reason: str, acc_name: str = "SYSTEM"):
    global _PROXY_RUNTIME_ENABLED
    with _PROXY_RUNTIME_LOCK:
        if _PROXY_RUNTIME_ENABLED:
            _PROXY_RUNTIME_ENABLED = False
            log(acc_name, f"代理模式已关闭，后续全部使用本机 IP。原因：{reason}")

def fetch_proxy_from_api(acc_name: str):
    if not is_proxy_runtime_enabled():
        return None

    try:
        r = requests.get(PROXY_API_URL, timeout=PROXY_API_TIMEOUT)
        r.raise_for_status()
        j = r.json()
    except Exception as e:
        disable_proxy_runtime(f"代理 API 请求失败：{e}", acc_name)
        return None

    # 新接口：code=200 表示成功
    code = j.get("code")
    msg = j.get("msg", "")
    if code != 200:
        disable_proxy_runtime(f"代理 API 返回失败：code={code}, msg={msg}")
        return None

    data = j.get("data", {})
    proxy_list = data.get("proxy_list", [])
    if not proxy_list or not isinstance(proxy_list, list):
        disable_proxy_runtime(f"代理 API proxy_list 为空：{j}", acc_name)
        return None

    first = proxy_list[0]
    ip = first.get("ip")
    port = first.get("port")
    if not ip or not port:
        disable_proxy_runtime(f"代理 API 缺少 ip/port：{j}", acc_name)
        return None

    raw = f"{ip}:{port}"
    proxy_url = f"http://{raw}"
    now = time.time()

    info = {
        "http": proxy_url,
        "https": proxy_url,
        "_raw": raw,
        "_born": now,
        "_expire_at": now + PROXY_EXPIRE_SECONDS,
    }

    log(acc_name, f"已获取代理：{raw}")
    return info

def proxy_expired(proxy_info):
    if not proxy_info:
        return True
    return time.time() >= proxy_info.get("_expire_at", 0)

def request_with_optional_proxy(method, url, *, headers=None, json_body=None, timeout=(2, 5), proxy_info=None):
    kwargs = {
        "headers": headers,
        "timeout": timeout,
        "verify": VERIFY_TLS,
    }
    if json_body is not None:
        kwargs["json"] = json_body

    if is_proxy_runtime_enabled() and proxy_info:
        kwargs["proxies"] = {
            "http": proxy_info["http"],
            "https": proxy_info["https"],
        }

    return requests.request(method, url, **kwargs)

def is_bad_proxy_error(e: Exception) -> bool:
    """
    这些错误大概率说明当前代理本身不可用：
    - ProxyError
    - ConnectTimeout
    - ConnectionError（network unreachable / refused）
    - SSL 握手超时
    """
    text = str(e).lower()
    if isinstance(e, (ProxyError, ConnectTimeout, ConnectionError, SSLError)):
        return True
    markers = [
        "cannot connect to proxy",
        "proxyerror",
        "connect timeout",
        "connection refused",
        "network unreachable",
        "failed to establish a new connection",
        "handshake operation timed out",
    ]
    return any(m in text for m in markers)

class TaskProxyContext:
    """
    单个任务的代理上下文：
    - current_proxy：当前正在使用的代理
    - standby_proxy：后台预取的备用代理
    """
    def __init__(self, acc_name: str, task_label: str):
        self.acc_name = acc_name
        self.task_label = task_label
        self.current_proxy = None
        self.standby_proxy = None
        self.proxy_born = 0.0
        self.rotate_count = 0
        self._standby_thread = None

    def init_main_proxy(self):
        if is_proxy_runtime_enabled():
            self.current_proxy = fetch_proxy_from_api(self.acc_name)
            if self.current_proxy:
                self.proxy_born = time.time()
                self.prefetch_standby_async()
            else:
                log(self.acc_name, f"代理获取失败，任务 {self.task_label} 自动改用本机 IP")

    def prefetch_standby_async(self):
        if not is_proxy_runtime_enabled():
            return
        if self._standby_thread and self._standby_thread.is_alive():
            return

        def _worker():
            proxy = fetch_proxy_from_api(self.acc_name)
            if proxy:
                self.standby_proxy = proxy
                log(self.acc_name, f"任务 {self.task_label} 备用代理已就绪：{proxy['_raw']}")

        self._standby_thread = threading.Thread(target=_worker, daemon=True)
        self._standby_thread.start()

    def current_mark(self):
        return self.current_proxy["_raw"] if (is_proxy_runtime_enabled() and self.current_proxy) else "LOCAL"

    def expire_rotate_if_needed(self):
        if self.current_proxy and proxy_expired(self.current_proxy):
            self.rotate_due_to_bad_proxy("代理超过有效期，立即切换")

    def rotate_due_to_bad_proxy(self, reason: str):
        if not is_proxy_runtime_enabled():
            self.current_proxy = None
            self.standby_proxy = None
            return

        if self.rotate_count >= MAX_PROXY_ROTATE_PER_TASK:
            log(self.acc_name, f"任务 {self.task_label} 已达到最大换代理次数，改用本机 IP。原因：{reason}")
            self.current_proxy = None
            self.standby_proxy = None
            return

        self.rotate_count += 1

        if self.standby_proxy and not proxy_expired(self.standby_proxy):
            old = self.current_mark()
            self.current_proxy = self.standby_proxy
            self.standby_proxy = None
            self.proxy_born = time.time()
            log(self.acc_name, f"任务 {self.task_label} 立即切到备用代理：{self.current_proxy['_raw']} | 原因：{reason} | 原代理={old}")
            self.prefetch_standby_async()
            return

        new_proxy = fetch_proxy_from_api(self.acc_name)
        if new_proxy:
            old = self.current_mark()
            self.current_proxy = new_proxy
            self.standby_proxy = None
            self.proxy_born = time.time()
            log(self.acc_name, f"任务 {self.task_label} 换新代理继续：{new_proxy['_raw']} | 原因：{reason} | 原代理={old}")
            self.prefetch_standby_async()
        else:
            self.current_proxy = None
            self.standby_proxy = None
            log(self.acc_name, f"任务 {self.task_label} 代理不可用，已改用本机 IP | 原因：{reason}")

# ========================= 查课 / 选课 =========================
def query_schedule_for_date_with_retry(schedule_date_iso: str, headers: dict, acc_name: str, proxy_ctx: TaskProxyContext):
    payload = {"scheduleDate": schedule_date_iso}
    last_exc = None

    for attempt in range(1, MAX_QUERY_RETRY + 1):
        proxy_ctx.expire_rotate_if_needed()
        try:
            log(acc_name, f"查询课表，第 {attempt}/{MAX_QUERY_RETRY} 次：{schedule_date_iso} | 网络={proxy_ctx.current_mark()}")
            r = request_with_optional_proxy(
                "POST",
                URL_QUERY,
                headers=headers,
                json_body=payload,
                timeout=TIMEOUT_QUERY,
                proxy_info=proxy_ctx.current_proxy
            )

            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} during GetGroupLessonSchedule: {r.text[:300]}")

            try:
                j = r.json()
            except Exception:
                j = json.loads(r.text)

            if isinstance(j, dict) and "d" in j:
                data = json.loads(j["d"])
            else:
                data = j

            if not isinstance(data, list) and isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break

            if not isinstance(data, list):
                raise RuntimeError(f"unexpected schedule format: {type(data)} {str(data)[:200]}")

            return data

        except Exception as e:
            last_exc = e
            log(acc_name, f"查询课表失败（第 {attempt} 次）：{e}")

            # 坏代理立即切换，不在同一个坏代理上死等
            if proxy_ctx.current_proxy and is_bad_proxy_error(e):
                proxy_ctx.rotate_due_to_bad_proxy(f"查询阶段代理失败：{e}")
            elif attempt < MAX_QUERY_RETRY:
                time.sleep(RETRY_SLEEP_SECONDS)

    raise RuntimeError(f"连续 {MAX_QUERY_RETRY} 次查询课表失败，最后异常：{last_exc}")

def preview_schedule(acc_name, schedule_list, limit=12):
    lines = []
    for i, it in enumerate(schedule_list[:limit], 1):
        lines.append(
            f"{i}. {it.get('GroupLessonName')} / {it.get('GLName')} "
            f"{it.get('StartTime')}-{it.get('EndTime')} "
            f"剩余:{it.get('SurplusNum')} | SID={it.get('ScheduleID')}"
        )
    if lines:
        log(acc_name, "当日课表预览：\n" + "\n".join(lines))
    else:
        log(acc_name, "当日课表为空。")

def within_time_window(start_time: str, time_window):
    try:
        st = parse_hhmm(start_time[:5])
        left = parse_hhmm(time_window[0])
        right = parse_hhmm(time_window[1])
        return left <= st <= right
    except Exception:
        return False

def choose_best_slot(schedule_list, task, require_surplus):
    course = task["course"]
    preferred_teacher = task.get("preferred_teacher")
    time_window = task["time_window"]

    candidates = []
    for it in schedule_list:
        if it.get("GroupLessonName") != course:
            continue

        start_time = str(it.get("StartTime", ""))[:5]
        if not within_time_window(start_time, time_window):
            continue

        surplus = safe_int(it.get("SurplusNum", "0"), 0)
        if require_surplus and surplus <= 0:
            continue

        teacher = it.get("GLName", "")
        teacher_match = 1 if preferred_teacher and teacher == preferred_teacher else 0

        try:
            time_score = abs(parse_hhmm(start_time) - parse_hhmm(time_window[0]))
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

    candidates.sort(
        key=lambda x: (
            -x["teacher_match"],
            -x["surplus"],
            x["time_score"],
        )
    )
    return candidates[0]["raw"]

# ========================= 预约业务码判定 =========================
def parse_business_result_from_text(text: str) -> Tuple[Optional[int], str, Dict[str, Any]]:
    """
    解析接口返回里的业务码：
    典型格式：
    {"d":"{\"code\":1,\t\"msg\": \"预约成功。\", \"isExp\": \"-1\"}"}
    """
    try:
        outer = json.loads(text)
    except Exception:
        return None, f"非 JSON 响应：{text[:200]}", {}

    try:
        if isinstance(outer, dict) and "d" in outer:
            inner = outer["d"]
            if isinstance(inner, str):
                inner_obj = json.loads(inner)
            elif isinstance(inner, dict):
                inner_obj = inner
            else:
                return None, f"无法解析 d 字段：{str(inner)[:200]}", {}
        else:
            inner_obj = outer if isinstance(outer, dict) else {}
    except Exception:
        return None, f"无法解析业务响应：{text[:200]}", {}

    code = inner_obj.get("code")
    msg = str(inner_obj.get("msg", ""))
    return code, msg, inner_obj

def normalize_business_message(code, msg: str) -> str:
    if code == 1:
        return msg or "预约成功"
    if code == -2:
        return f"超过总部限制的最大预约数量：{msg}"
    if code == -3:
        return f"已预约过或已加入备选：{msg}"
    if code == 0:
        return msg or "业务返回 code=0"
    if code is None:
        return msg or "无法解析业务返回"
    return msg or f"业务返回 code={code}"

# ========================= 预约 =========================
def do_reservation_with_retry(acc, acc_name: str, schedule_date_iso: str, picked_item: dict, headers: dict, proxy_ctx: TaskProxyContext):
    rowNum = acc.get("rowNum", 0)
    colNum = acc.get("colNum", 0)

    body = {
        "colNum": colNum,
        "groupLessondId": picked_item["GroupLessonID"],
        "rowNum": rowNum,
        "scheduleDate": schedule_date_iso,
        "scheduleId": picked_item["ScheduleID"],
    }

    log(acc_name, "提交预约 BODY:")
    log(acc_name, json.dumps(body, ensure_ascii=False, indent=2))

    last_exc = None
    for attempt in range(1, MAX_RESERVE_RETRY + 1):
        proxy_ctx.expire_rotate_if_needed()
        try:
            log(acc_name, f"预约提交，第 {attempt}/{MAX_RESERVE_RETRY} 次尝试 | 网络={proxy_ctx.current_mark()}")

            r = request_with_optional_proxy(
                "POST",
                URL_RESERVE,
                headers=headers,
                json_body=body,
                timeout=TIMEOUT_RESERVE,
                proxy_info=proxy_ctx.current_proxy,
            )

            log(acc_name, f"预约响应 HTTP {r.status_code}")
            log(acc_name, "预约响应内容片段: " + r.text[:1200])

            code, msg, business_obj = parse_business_result_from_text(r.text)
            if business_obj:
                log(acc_name, "预约业务响应:\n" + json.dumps(business_obj, ensure_ascii=False, indent=2))

            return r.status_code, r.text, code, msg

        except Exception as e:
            last_exc = e
            log(acc_name, f"预约失败（第 {attempt} 次）：{e}")

            if proxy_ctx.current_proxy and is_bad_proxy_error(e):
                proxy_ctx.rotate_due_to_bad_proxy(f"预约阶段代理失败：{e}")
            elif attempt < MAX_RESERVE_RETRY:
                time.sleep(RETRY_SLEEP_SECONDS)

    raise RuntimeError(f"连续 {MAX_RESERVE_RETRY} 次预约都未拿到有效响应，最后异常：{last_exc}")

# ========================= 任务执行与结果汇总 =========================
def make_task_result(label: str, status: str, detail: str):
    return {"label": label, "status": status, "detail": detail}

def reserve_one_task_for_account(acc, task, require_surplus):
    acc_name = acc["name"]
    schedule_date = compute_next_weekday_date(task["weekday"])
    schedule_date_iso = schedule_date.isoformat()
    headers = build_headers_for_account(acc)

    proxy_ctx = TaskProxyContext(acc_name, task["label"])
    proxy_ctx.init_main_proxy()

    while True:
        try:
            proxy_ctx.expire_rotate_if_needed()

            log(
                acc_name,
                f"开始任务：{task['label']} | 日期={schedule_date_iso} | "
                f"课程={task['course']} | 优先老师={task.get('preferred_teacher')} | "
                f"时间窗={task['time_window'][0]}~{task['time_window'][1]} | 网络={proxy_ctx.current_mark()}"
            )

            schedule_list = query_schedule_for_date_with_retry(schedule_date_iso, headers, acc_name, proxy_ctx)
            preview_schedule(acc_name, schedule_list)

            picked = choose_best_slot(schedule_list, task, require_surplus)
            if picked is None:
                detail = (
                    f"未找到可预约课程：{task['course']} | 时间窗={task['time_window']} "
                    f"| require_surplus={require_surplus}"
                )
                log(acc_name, f"{task['label']} - {detail}")
                try:
                    debug_json = json.dumps(schedule_list[:5], ensure_ascii=False, indent=2)
                    log(acc_name, "调试样例:\n" + debug_json)
                except Exception:
                    pass
                return make_task_result(task["label"], "NO_SLOT", detail)

            log(
                acc_name,
                "命中课程: "
                f"{picked.get('GroupLessonName')} / {picked.get('GLName')} / "
                f"{picked.get('StartTime')}-{picked.get('EndTime')} / "
                f"剩余 {picked.get('SurplusNum')} | SID={picked.get('ScheduleID')}"
            )
            log(acc_name, f"使用座位 rowNum={acc.get('rowNum',0)} colNum={acc.get('colNum',0)}")

            http_code, _, biz_code, biz_msg = do_reservation_with_retry(
                acc, acc_name, schedule_date_iso, picked, headers, proxy_ctx
            )

            normalized = normalize_business_message(biz_code, biz_msg)
            if biz_code == 1:
                log(acc_name, f"任务成功：{task['label']} | HTTP {http_code} | {normalized}")
                return make_task_result(task["label"], "SUCCESS", normalized)

            log(acc_name, f"任务失败：{task['label']} | HTTP {http_code} | {normalized}")
            return make_task_result(task["label"], "FAILED", normalized)

        except Exception as e:
            log(acc_name, f"任务异常：{task['label']} | {e}")
            if proxy_ctx.current_proxy and is_proxy_runtime_enabled():
                proxy_ctx.rotate_due_to_bad_proxy(f"任务整体异常：{e}")
            else:
                return make_task_result(task["label"], "FAILED", str(e))

def worker_run_for_account(acc, require_surplus):
    """
    每个账号内部：2个固定任务并发执行
    多个账号之间：仍然并发
    """
    acc_name = acc["name"]
    results = []
    try:
        log(acc_name, f"账号启动，固定任务数={len(FIXED_RESERVATION_TASKS)}，模式=账号内并发")

        with ThreadPoolExecutor(max_workers=len(FIXED_RESERVATION_TASKS)) as inner_pool:
            futures = []
            for idx, task in enumerate(FIXED_RESERVATION_TASKS, 1):
                log(acc_name, f"提交第 {idx}/{len(FIXED_RESERVATION_TASKS)} 个任务到线程池：{task['label']}")
                futures.append(inner_pool.submit(reserve_one_task_for_account, acc, task, require_surplus))

            for f in futures:
                try:
                    r = f.result()
                    if r:
                        results.append(r)
                except Exception as e:
                    results.append(make_task_result("UNKNOWN", "FAILED", str(e)))

    except Exception as e:
        log(acc_name, f"账号整体流程异常：{e}")
        log(acc_name, "建议手动到小程序里确认该账号实际预约状态。")
        results.append(make_task_result("ACCOUNT", "FAILED", str(e)))

    return {"account": acc_name, "results": results}

def print_summary(all_results: List[Dict[str, Any]]):
    print("\n==================== 任务结果汇总 ====================")
    for item in all_results:
        acc_name = item["account"]
        results = item["results"]
        success = sum(1 for r in results if r["status"] == "SUCCESS")
        failed = sum(1 for r in results if r["status"] == "FAILED")
        no_slot = sum(1 for r in results if r["status"] == "NO_SLOT")

        print(f"账号：{acc_name} | 成功={success} | 失败={failed} | 无可约课程={no_slot}")
        for r in results:
            print(f"  - [{r['status']}] {r['label']} -> {r['detail']}")
    print("=====================================================")

# ========================= 命令行 =========================
def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="中大约课：军悦店固定2节任务版（快速代理切换优化版）")
    p.add_argument(
        "--allow-full",
        action="store_true",
        help="即使 SurplusNum=0 也尝试预约"
    )
    return p.parse_args()

def main():
    args = parse_args()
    require_surplus = REQUIRE_SURPLUS_DEFAULT if not args.allow_full else False

    print("=====================================================")
    print("军悦店固定2节预约任务启动")
    print(f"账号数={len(ACCOUNTS)}")
    print(f"需名额? {require_surplus}")
    print(f"代理开关 PROXY_SWITCH = {PROXY_SWITCH} （1=开，0=关）")
    print("并发模式：账号之间并发；每个账号内部2个任务也并发执行")
    print("网络优化：短连接超时 + 坏代理立即切换 + 备用代理后台预取")
    print("任务清单：")
    for idx, task in enumerate(FIXED_RESERVATION_TASKS, 1):
        date_preview = compute_next_weekday_date(task["weekday"]).isoformat()
        print(
            f"{idx}. {task['label']} | 日期={date_preview} | "
            f"课程={task['course']} | 优先老师={task.get('preferred_teacher')} | "
            f"时间窗={task['time_window'][0]}~{task['time_window'][1]}"
        )
    print("=====================================================")

    if not ACCOUNTS:
        print("没有启用任何账号，请先在 ACCOUNTS 中填写。")
        return

    all_results = []
    with ThreadPoolExecutor(max_workers=len(ACCOUNTS)) as pool:
        futures = [pool.submit(worker_run_for_account, acc, require_surplus) for acc in ACCOUNTS]
        for f in futures:
            all_results.append(f.result())

    print_summary(all_results)
    print("=== 全部账号尝试结束 ===")

if __name__ == "__main__":
    main()
