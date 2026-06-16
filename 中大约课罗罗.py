#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
中大约课：固定4节任务版（多账号并发 + 账号内任务并发 + 代理开关 + 本机IP兜底 + 备用代理预取）
=================================================
功能说明：
1. 多账号并发：账号之间并发执行
2. 账号内任务并发：同一账号的固定任务也并发执行
3. 固定4个任务：
   - 下一个周三：小程序-杠铃充电（晚上第一节）
   - 下一个周三：小程序-有氧战斗（晚上第二节）
   - 下一个周五：小程序-杠铃充电（晚上第一节）
   - 下一个周五：小程序-有氧战斗（晚上第二节）
4. 课程筛选规则：
   - 课程名必须匹配
   - 老师名只做优先匹配，不是硬条件（防止临时换老师）
   - 时间只限制在晚上对应时间窗内，不要求精确到某一分钟
5. 代理逻辑（优化版）：
   - PROXY_SWITCH = 1：开启代理模式
   - PROXY_SWITCH = 0：关闭代理模式，全部走本机 IP
   - 每“1节课任务”使用 1 个主代理 + 1 个后台预取备用代理
   - 同一节课的查课 / 提交，都尽量复用当前代理
   - 如果当前代理出现连接错误/连接超时/代理拒绝：立即判死，不再在同一坏代理上重试
   - 切换到后台预取好的备用代理；若备用代理也不可用，则切回本机 IP
   - 如果代理 API 获取失败：立即放弃代理模式，后续全部改用本机 IP
6. 业务码判定：
   - 只有返回 code=1 才算预约成功
   - code=-2 / -3 等都会明确打印失败原因，不再只看 HTTP 200
   - 最后会输出每个账号的任务汇总
=================================================
"""

import datetime as dt
import json
import time
import threading
import queue
import requests
from concurrent.futures import ThreadPoolExecutor

# ========================= 多账号配置 =========================
ACCOUNTS = [
    {
        "name": "罗罗",
        "OpenID": "<SENSITIVE>",
        "ClubID": "57115e05-ea7e-4411-b062-c2bb5d5f1b36",
        "BrandCode": "8961",
        "APPID": "wx3bb18aff4f2fe45f",
        "rowNum": 0,
        "colNum": 1,
    },
]

# ========================= 固定任务配置 =========================
FIXED_RESERVATION_TASKS = [
    {
        "label": "周三-杠铃充电",
        "weekday": 2,
        "course": "小程序-杠铃充电",
        "preferred_teacher": "王晓悦",
        "time_window": ("17:50", "19:15"),
    },
    {
        "label": "周三-有氧战斗",
        "weekday": 2,
        "course": "小程序-有氧战斗",
        "preferred_teacher": "王晓悦",
        "time_window": ("19:10", "20:20"),
    },
    {
        "label": "周五-杠铃充电",
        "weekday": 4,
        "course": "小程序-杠铃充电",
        "preferred_teacher": "邢丹丹",
        "time_window": ("17:50", "19:15"),
    },
    {
        "label": "周五-有氧战斗",
        "weekday": 4,
        "course": "小程序-有氧战斗",
        "preferred_teacher": "邢丹丹",
        "time_window": ("19:10", "20:20"),
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
PROXY_API_TIMEOUT = 4
PROXY_PREFETCH_WAIT = 1.2        # 等备用代理就绪的最长等待
PROXY_MAX_SWAP_PER_TASK = 2      # 单任务最多换几次代理，避免无限折腾
_PROXY_RUNTIME_ENABLED = True
_PROXY_RUNTIME_LOCK = threading.Lock()

# ========================= 接口地址 =========================
BASE_URL = "https://weixin.jianshenguanli.com/MemberInterface/WebService/Reservation.asmx"
URL_QUERY = f"{BASE_URL}/GetGroupLessonSchedule"
URL_RESERVE = f"{BASE_URL}/GroupLessonReservation"
VERIFY_TLS = True

# ========================= 超时 / 重试 =========================
# 用 (连接超时, 读超时) 的 tuple，坏代理尽快判死
TIMEOUT_QUERY = (2, 5)
TIMEOUT_RESERVE = (2, 6)

# 代理相关错误不在同一代理上多次重试；业务请求类错误最多小重试
MAX_QUERY_RETRY = 2
MAX_RESERVE_RETRY = 2
REQUIRE_SURPLUS_DEFAULT = True
RETRY_SLEEP_SECONDS = 0.3

# ========================= 结果汇总 =========================
_RESULTS_LOCK = threading.Lock()
TASK_RESULTS = {}  # {acc_name: [result_dict, ...]}

# ========================= 工具函数 =========================
def log(acc_name, msg):
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


def record_task_result(acc_name, task_label, status, detail, extra=None):
    item = {
        "task": task_label,
        "status": status,
        "detail": detail,
        "extra": extra or {},
    }
    with _RESULTS_LOCK:
        TASK_RESULTS.setdefault(acc_name, []).append(item)


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


def proxy_is_expired(proxy_info):
    return (not proxy_info) or time.time() >= proxy_info.get("_expire_at", 0)


def request_with_optional_proxy(method, url, *, headers=None, json_body=None, timeout=(2, 5), proxy_info=None):
    kwargs = {"headers": headers, "timeout": timeout, "verify": VERIFY_TLS}
    if json_body is not None:
        kwargs["json"] = json_body
    if is_proxy_runtime_enabled() and proxy_info:
        kwargs["proxies"] = {"http": proxy_info["http"], "https": proxy_info["https"]}
    return requests.request(method, url, **kwargs)


def is_bad_proxy_error(exc: Exception) -> bool:
    """
    这些错误说明代理本身不可用，不应该在同一坏代理上继续空等。
    """
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


class TaskNetworkContext:
    """
    单个任务的网络上下文：
    - current_proxy: 当前在用代理
    - standby_queue: 后台预取的备用代理
    优化目的：
    - 坏代理一旦判死，尽快切备用代理或本机 IP
    """
    def __init__(self, acc_name: str, task_label: str):
        self.acc_name = acc_name
        self.task_label = task_label
        self.current_proxy = None
        self.standby_queue = queue.Queue(maxsize=1)
        self.proxy_swap_count = 0
        self.proxy_disabled_for_this_task = False

    def network_mark(self):
        if is_proxy_runtime_enabled() and self.current_proxy and not self.proxy_disabled_for_this_task:
            return self.current_proxy["_raw"]
        return "LOCAL"

    def _prefetch_worker(self):
        proxy = fetch_proxy_from_api(self.acc_name)
        if proxy:
            try:
                self.standby_queue.put_nowait(proxy)
                log(self.acc_name, f"任务 {self.task_label} 备用代理已就绪：{proxy['_raw']}")
            except queue.Full:
                pass

    def start_prefetch(self):
        if not is_proxy_runtime_enabled() or self.proxy_disabled_for_this_task:
            return
        if not self.standby_queue.empty():
            return
        t = threading.Thread(target=self._prefetch_worker, daemon=True)
        t.start()

    def ensure_initial_proxy(self):
        if not is_proxy_runtime_enabled() or self.proxy_disabled_for_this_task:
            return
        if self.current_proxy is None:
            self.current_proxy = fetch_proxy_from_api(self.acc_name)
            if self.current_proxy is None:
                self.proxy_disabled_for_this_task = True
                log(self.acc_name, f"任务 {self.task_label} 首次代理获取失败，改用本机 IP")
            else:
                self.start_prefetch()

    def refresh_if_expired(self):
        if not is_proxy_runtime_enabled() or self.proxy_disabled_for_this_task:
            return
        if self.current_proxy and proxy_is_expired(self.current_proxy):
            log(self.acc_name, f"任务 {self.task_label} 当前代理已过期，立即切换")
            self.switch_proxy(reason="当前代理过期")

    def switch_proxy(self, reason: str):
        """
        优先切换到已经预取好的备用代理，拿不到就现场取一个；
        都失败则切本机 IP。
        """
        if not is_proxy_runtime_enabled() or self.proxy_disabled_for_this_task:
            self.current_proxy = None
            self.proxy_disabled_for_this_task = True
            return

        if self.proxy_swap_count >= PROXY_MAX_SWAP_PER_TASK:
            self.current_proxy = None
            self.proxy_disabled_for_this_task = True
            log(self.acc_name, f"任务 {self.task_label} 代理切换次数已达上限，改用本机 IP。原因：{reason}")
            return

        new_proxy = None
        try:
            new_proxy = self.standby_queue.get(timeout=PROXY_PREFETCH_WAIT)
            log(self.acc_name, f"任务 {self.task_label} 立即切到备用代理：{new_proxy['_raw']} | 原因：{reason}")
        except queue.Empty:
            log(self.acc_name, f"任务 {self.task_label} 没等到备用代理，现场拉新代理 | 原因：{reason}")
            new_proxy = fetch_proxy_from_api(self.acc_name)

        if new_proxy:
            self.current_proxy = new_proxy
            self.proxy_swap_count += 1
            self.start_prefetch()
        else:
            self.current_proxy = None
            self.proxy_disabled_for_this_task = True
            log(self.acc_name, f"任务 {self.task_label} 新代理获取失败，改用本机 IP。原因：{reason}")


# ========================= 查询 / 选课 =========================
def query_schedule_for_date_with_retry(schedule_date_iso: str, headers: dict, acc_name: str, net_ctx=None):
    payload = {"scheduleDate": schedule_date_iso}
    last_exc = None

    for attempt in range(1, MAX_QUERY_RETRY + 1):
        try:
            if net_ctx:
                net_ctx.refresh_if_expired()
                proxy_info = net_ctx.current_proxy
                proxy_mark = net_ctx.network_mark()
            else:
                proxy_info = None
                proxy_mark = "LOCAL"

            log(acc_name, f"查询课表，第 {attempt}/{MAX_QUERY_RETRY} 次：{schedule_date_iso} | 网络={proxy_mark}")
            r = request_with_optional_proxy(
                "POST", URL_QUERY, headers=headers, json_body=payload,
                timeout=TIMEOUT_QUERY, proxy_info=proxy_info
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

            # 代理本身坏了：立即切换，不在同一坏代理上空等多次
            if net_ctx and is_bad_proxy_error(e) and net_ctx.current_proxy:
                net_ctx.switch_proxy(reason=f"查询阶段代理失败：{e}")
                continue

            if attempt < MAX_QUERY_RETRY:
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

    candidates.sort(key=lambda x: (-x["teacher_match"], -x["surplus"], x["time_score"]))
    return candidates[0]["raw"]


# ========================= 业务响应解析 =========================
def parse_business_result(text: str):
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


# ========================= 预约 =========================
def do_reservation_with_retry(acc, acc_name: str, schedule_date_iso: str, picked_item: dict, headers: dict, net_ctx=None):
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
        try:
            if net_ctx:
                net_ctx.refresh_if_expired()
                proxy_info = net_ctx.current_proxy
                proxy_mark = net_ctx.network_mark()
            else:
                proxy_info = None
                proxy_mark = "LOCAL"

            log(acc_name, f"预约提交，第 {attempt}/{MAX_RESERVE_RETRY} 次尝试 | 网络={proxy_mark}")
            r = request_with_optional_proxy(
                "POST", URL_RESERVE, headers=headers, json_body=body,
                timeout=TIMEOUT_RESERVE, proxy_info=proxy_info,
            )
            log(acc_name, f"预约响应 HTTP {r.status_code}")
            log(acc_name, "预约响应内容片段: " + r.text[:1200])

            biz = parse_business_result(r.text)
            if biz["raw"] is not None:
                try:
                    log(acc_name, "预约业务响应:\n" + json.dumps(biz["raw"], ensure_ascii=False, indent=2))
                except Exception:
                    pass

            return {
                "http_status": r.status_code,
                "response_text": r.text,
                "biz": biz,
            }

        except Exception as e:
            last_exc = e
            log(acc_name, f"预约失败（第 {attempt} 次）：{e}")

            if net_ctx and is_bad_proxy_error(e) and net_ctx.current_proxy:
                net_ctx.switch_proxy(reason=f"预约阶段代理失败：{e}")
                continue

            if attempt < MAX_RESERVE_RETRY:
                time.sleep(RETRY_SLEEP_SECONDS)

    raise RuntimeError(f"连续 {MAX_RESERVE_RETRY} 次预约都未拿到有效响应，最后异常：{last_exc}")


# ========================= 单任务 / 单账号流程 =========================
def reserve_one_task_for_account(acc, task, require_surplus):
    acc_name = acc["name"]
    schedule_date = compute_next_weekday_date(task["weekday"])
    schedule_date_iso = schedule_date.isoformat()
    headers = build_headers_for_account(acc)

    net_ctx = TaskNetworkContext(acc_name, task["label"])
    net_ctx.ensure_initial_proxy()

    while True:
        try:
            net_mark = net_ctx.network_mark()
            log(
                acc_name,
                f"开始任务：{task['label']} | 日期={schedule_date_iso} | "
                f"课程={task['course']} | 优先老师={task.get('preferred_teacher')} | "
                f"时间窗={task['time_window'][0]}~{task['time_window'][1]} | 网络={net_mark}"
            )

            schedule_list = query_schedule_for_date_with_retry(schedule_date_iso, headers, acc_name, net_ctx=net_ctx)
            preview_schedule(acc_name, schedule_list)

            picked = choose_best_slot(schedule_list, task, require_surplus)
            if picked is None:
                detail = f"未找到可预约课程：{task['course']} | 时间窗={task['time_window']} | require_surplus={require_surplus}"
                log(acc_name, f"{task['label']} - {detail}")
                try:
                    debug_json = json.dumps(schedule_list[:5], ensure_ascii=False, indent=2)
                    log(acc_name, "调试样例:\n" + debug_json)
                except Exception:
                    pass
                record_task_result(acc_name, task["label"], "NO_SLOT", detail)
                return

            log(
                acc_name,
                "命中课程: "
                f"{picked.get('GroupLessonName')} / {picked.get('GLName')} / "
                f"{picked.get('StartTime')}-{picked.get('EndTime')} / "
                f"剩余 {picked.get('SurplusNum')} | SID={picked.get('ScheduleID')}"
            )
            log(acc_name, f"使用座位 rowNum={acc.get('rowNum',0)} colNum={acc.get('colNum',0)}")

            reserve_result = do_reservation_with_retry(
                acc, acc_name, schedule_date_iso, picked, headers, net_ctx=net_ctx
            )
            biz = reserve_result["biz"]
            http_status = reserve_result["http_status"]

            if biz["ok"]:
                detail = code_meaning(biz["code"], biz["msg"])
                log(acc_name, f"任务成功：{task['label']} | HTTP {http_status} | {detail}")
                record_task_result(
                    acc_name, task["label"], "SUCCESS", detail,
                    extra={
                        "http_status": http_status,
                        "biz_code": biz["code"],
                        "course": picked.get("GroupLessonName"),
                        "teacher": picked.get("GLName"),
                        "start": picked.get("StartTime"),
                        "date": schedule_date_iso,
                    }
                )
            else:
                detail = code_meaning(biz["code"], biz["msg"])
                log(acc_name, f"任务失败：{task['label']} | HTTP {http_status} | {detail}")
                record_task_result(
                    acc_name, task["label"], "FAILED", detail,
                    extra={
                        "http_status": http_status,
                        "biz_code": biz["code"],
                        "course": picked.get("GroupLessonName"),
                        "teacher": picked.get("GLName"),
                        "start": picked.get("StartTime"),
                        "date": schedule_date_iso,
                    }
                )
            return

        except Exception as e:
            log(acc_name, f"任务异常：{task['label']} | {e}")
            # 异常后尽快切换到备用代理或本机，不在坏代理上拖太久
            if is_proxy_runtime_enabled():
                net_ctx.switch_proxy(reason=f"任务整体异常：{e}")
            else:
                net_ctx.proxy_disabled_for_this_task = True
                net_ctx.current_proxy = None
            time.sleep(0.2)


def worker_run_for_account(acc, require_surplus):
    """
    每个账号内部：4个固定任务并发执行
    多个账号之间：仍然并发
    """
    acc_name = acc["name"]
    try:
        log(acc_name, f"账号启动，固定任务数={len(FIXED_RESERVATION_TASKS)}，模式=账号内并发")
        with ThreadPoolExecutor(max_workers=len(FIXED_RESERVATION_TASKS)) as inner_pool:
            futures = []
            for idx, task in enumerate(FIXED_RESERVATION_TASKS, 1):
                log(acc_name, f"提交第 {idx}/{len(FIXED_RESERVATION_TASKS)} 个任务到线程池：{task['label']}")
                futures.append(inner_pool.submit(reserve_one_task_for_account, acc, task, require_surplus))
            for f in futures:
                f.result()
    except Exception as e:
        log(acc_name, f"账号整体流程异常：{e}")
        log(acc_name, "建议手动到小程序里确认该账号实际预约状态。")


# ========================= 命令行 =========================
def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="中大约课：固定4节任务版（代理优化 + 业务码判定）")
    p.add_argument("--allow-full", action="store_true", help="即使 SurplusNum=0 也尝试预约")
    return p.parse_args()


def print_summary():
    print("\n==================== 任务结果汇总 ====================")
    if not TASK_RESULTS:
        print("没有记录到任何任务结果。")
        return

    for acc_name, items in TASK_RESULTS.items():
        success_cnt = sum(1 for x in items if x["status"] == "SUCCESS")
        failed_cnt = sum(1 for x in items if x["status"] == "FAILED")
        no_slot_cnt = sum(1 for x in items if x["status"] == "NO_SLOT")
        print(f"账号：{acc_name} | 成功={success_cnt} | 失败={failed_cnt} | 无可约课程={no_slot_cnt}")
        for item in items:
            print(f"  - [{item['status']}] {item['task']} -> {item['detail']}")
    print("=====================================================")


def main():
    args = parse_args()
    require_surplus = REQUIRE_SURPLUS_DEFAULT if not args.allow_full else False

    print("=====================================================")
    print("固定4节预约任务启动")
    print(f"账号数={len(ACCOUNTS)}")
    print(f"需名额? {require_surplus}")
    print(f"代理开关 PROXY_SWITCH = {PROXY_SWITCH} （1=开，0=关）")
    print("并发模式：账号之间并发；每个账号内部4个任务也并发执行")
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

    with ThreadPoolExecutor(max_workers=len(ACCOUNTS)) as pool:
        futures = [pool.submit(worker_run_for_account, acc, require_surplus) for acc in ACCOUNTS]
        for f in futures:
            f.result()

    print_summary()
    print("=== 全部账号尝试结束 ===")


if __name__ == "__main__":
    main()
