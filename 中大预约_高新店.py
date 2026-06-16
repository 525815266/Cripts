#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中大预约_多账号并发版 (v4-multi-seat, for 小程序-Zumba-邢丹丹 19:20, 默认下周四)
=================================================
在原版基础上的改动：
1. 默认目标课程改为：小程序-Zumba / 邢丹丹
2. 时间优先序列仅保留：19:20（工作日 + 节假日都只抢这节）
3. 默认 --next-weekday 改为 3 （下一个周四）
4. 预约接口增加重试逻辑：
   - 遇到网络超时/连接异常自动重试多次
   - 只要有一次拿到 HTTP 响应（不管成功/已预约/无座位），就停止重试
5. 子线程内部捕获异常并打印详细日志，不再在主线程输出 [FATAL] 子线程异常

注意：
- ACCOUNTS 使用你提供的高新店账号信息
"""

import datetime as dt
import json
import sys
import requests
from concurrent.futures import ThreadPoolExecutor

# ========================= 多账号配置 =========================
#   - name      : 日志里展示的昵称
#   - OpenID    : 抓包里的 OpenID
#   - ClubID    : 抓包里的 ClubID（高新店）
#   - BrandCode : 抓包里的 BrandCode
#   - APPID     : 抓包里的 APPID
#   - rowNum / colNum : 座位坐标
ACCOUNTS = [
    {
        "name": "李晨",
        "OpenID": "<SENSITIVE>",
        "ClubID": "184a8ef2-0319-40a7-9cbe-09369c0bc7a3",
        "BrandCode": "8961",
        "APPID": "wx0bb8b12e3625b643",

        # 如需鉴权可打开：
        # "Cookie": "<SENSITIVE>",
        # "Authorization": "<SENSITIVE>",

        # 该账号想预定的座位坐标
        "rowNum": 0,
        "colNum": 2,

        # 可选：指定自己的 Referer（否则用 APPID 拼一个通用的）
        # "Referer": "https://servicewechat.com/wx0bb8b12e3625b643/8/page-frame.html",
    },

    # 如需旧店/其他账号，可继续追加
]

# ========================= 课程筛选全局配置 =========================
# 目标课程和老师的名称（默认值，可以用命令行参数覆盖）
TARGET_COURSE_NAME   = "小程序-Zumba"  # 对应 GroupLessonName
TARGET_TEACHER_NAME  = "邢丹丹"       # 对应 GLName

# 时间优先策略：只抢 19:20 那节
WORKDAY_PREFERRED_TIMES  = ["19:20"]
HOLIDAY_PREFERRED_TIMES  = ["19:20"]

# 默认要求必须有剩余名额 SurplusNum>0 才会尝试
REQUIRE_SURPLUS_DEFAULT  = True

# ========================= 接口地址 =========================
BASE_URL    = "https://weixin.jianshenguanli.com/MemberInterface/WebService/Reservation.asmx"
URL_QUERY   = f"{BASE_URL}/GetGroupLessonSchedule"
URL_RESERVE = f"{BASE_URL}/GroupLessonReservation"
VERIFY_TLS  = True

# 查询课表/预约各自的超时时间（秒）
TIMEOUT_QUERY   = 20
TIMEOUT_RESERVE = 25   # 预约阶段稍微放宽一点

# 预约接口最大重试次数（超时/网络异常会重试）
MAX_RESERVE_RETRY = 5

# ========================= 工具函数 =========================
def log(acc_name, msg):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}][{acc_name}] {msg}", flush=True)

def is_ascii(s):
    if s is None:
        return True
    try:
        s.encode("ascii")
        return True
    except Exception:
        return False

def build_headers_for_account(acc: dict):
    """
    构造该账号要用的请求头。
    - OpenID / ClubID / BrandCode / APPID 必须来自 ACCOUNTS
    - Referer：
        * 若账号配置了 Referer 字段 → 优先用账号自己的
        * 否则默认用 "https://servicewechat.com/{APPID}/8/page-frame.html"
    """
    referer = acc.get(
        "Referer",
        f"https://servicewechat.com/{acc['APPID']}/8/page-frame.html"
    )

    headers = {
        "Referer": referer,
        "OpenID": acc["OpenID"],
        "BrandCode": acc["BrandCode"],
        "ClubID": acc["ClubID"],
        "IsNewAPP": "1",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6_2 like Mac OS X)",
        "APPID": acc["APPID"],
        "content-type": "application/json",
    }

    if "Cookie" in acc and acc["Cookie"]:
        headers["Cookie"] = acc["Cookie"]
    if "Authorization" in acc and acc["Authorization"]:
        headers["Authorization"] = acc["Authorization"]

    for k, v in headers.items():
        if not is_ascii(str(v)):
            raise ValueError(
                f"账号[{acc.get('name')}] 的 {k} 含非 ASCII 字符，请使用真实值（不要留中文占位）。"
            )

    for need in ["OpenID", "ClubID", "BrandCode", "APPID"]:
        if not headers.get(need):
            raise ValueError(f"账号[{acc.get('name')}] 缺少必要头: {need}")

    return headers

def load_holiday_map(path: str):
    """
    解析节假日/补班 JSON 文件并返回:
        { "YYYY-MM-DD": True/False, ... }

    返回值含义：
        True  -> 这天走“工作日策略”（WORKDAY_PREFERRED_TIMES）
        False -> 这天走“周末/休假策略”（HOLIDAY_PREFERRED_TIMES）
    """
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    mapping = {}

    def mark(date_str: str, is_work: bool):
        iso_like = date_str.split(" ")[0].replace(".", "-").replace("/", "-")
        ymd = iso_like.split("-")
        if len(ymd) == 3:
            y, m, d2 = ymd
            try:
                d = dt.date(int(y), int(m), int(d2))
                mapping[d.isoformat()] = bool(is_work)
            except Exception:
                pass

    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict) and ("is_workday" in v or "isOffDay" in v or "type" in v):
                if "is_workday" in v:
                    mark(k, bool(v["is_workday"]))
                elif "isOffDay" in v:
                    mark(k, not bool(int(v["isOffDay"])))
                elif "type" in v:
                    mark(k, str(v["type"]).lower() == "workday")

        for bucket in ("days", "list", "data", "holiday"):
            if bucket in data and isinstance(data[bucket], list):
                for rec in data[bucket]:
                    if not isinstance(rec, dict):
                        continue
                    dstr = rec.get("date") or rec.get("day")
                    if not dstr:
                        continue
                    if "is_workday" in rec:
                        mark(dstr, bool(rec["is_workday"]))
                    elif "isOffDay" in rec:
                        mark(dstr, not bool(int(rec["isOffDay"])))
                    elif "type" in rec:
                        mark(dstr, str(rec["type"]).lower() == "workday")

    if isinstance(data, list):
        for rec in data:
            if not isinstance(rec, dict):
                continue
            dstr = rec.get("date") or rec.get("day")
            if not dstr:
                continue
            if "is_workday" in rec:
                mark(dstr, bool(rec["is_workday"]))
            elif "isOffDay" in rec:
                mark(dstr, not bool(int(rec["isOffDay"])))
            elif "type" in rec:
                mark(dstr, str(rec["type"]).lower() == "workday")

    return mapping

def is_workday_rule(target_date: dt.date, holiday_map: dict) -> bool:
    key = target_date.isoformat()
    if key in holiday_map:
        return holiday_map[key]
    return target_date.weekday() < 5

def query_schedule_for_date(schedule_date_iso: str, headers: dict):
    payload = {"scheduleDate": schedule_date_iso}
    r = requests.post(URL_QUERY, json=payload, headers=headers, timeout=TIMEOUT_QUERY, verify=VERIFY_TLS)
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

    if not isinstance(data, list):
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    data = v
                    break

    if not isinstance(data, list):
        raise RuntimeError(f"unexpected schedule format: {type(data)} {str(data)[:200]}")

    return data

def pick_slot(schedule_list, course_name, teacher_name, preferred_times, require_surplus):
    """
    选课逻辑（返回1条字典 picked_item）：
    1. 优先匹配：课程名 + 老师名 + StartTime 在 preferred_times 里的
    2. 如果没找到：匹配 课程名 + 老师名
    3. 如果还没找到：匹配 课程名
    默认只要 SurplusNum>0，除非 require_surplus=False
    """
    for t in preferred_times:
        for it in schedule_list:
            if (it.get("GroupLessonName") == course_name and
                it.get("GLName") == teacher_name and
                it.get("StartTime") == t):
                if require_surplus:
                    try:
                        if int(it.get("SurplusNum", "0")) <= 0:
                            continue
                    except:
                        continue
                return it

    for it in schedule_list:
        if (it.get("GroupLessonName") == course_name and
            it.get("GLName") == teacher_name):
            if require_surplus:
                try:
                    if int(it.get("SurplusNum", "0")) <= 0:
                        continue
                except:
                    continue
            return it

    for it in schedule_list:
        if it.get("GroupLessonName") == course_name:
            if require_surplus:
                try:
                    if int(it.get("SurplusNum", "0")) <= 0:
                        continue
                except:
                    continue
            return it

    return None

def do_reservation(acc, acc_name: str, schedule_date_iso: str, picked_item: dict, headers: dict):
    """
    真正发起预约（带重试）。
    使用该账号自己的 rowNum / colNum。
    Body:
        {
            "colNum": X,
            "groupLessondId": "<GroupLessonID>",
            "rowNum": Y,
            "scheduleDate": "YYYY-MM-DD",
            "scheduleId": "<ScheduleID>"
        }
    """
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
            log(acc_name, f"第 {attempt}/{MAX_RESERVE_RETRY} 次尝试预约……")
            r = requests.post(
                URL_RESERVE,
                json=body,
                headers=headers,
                timeout=TIMEOUT_RESERVE,
                verify=VERIFY_TLS,
            )
            log(acc_name, f"预约响应 HTTP {r.status_code}")
            log(acc_name, "预约响应内容片段: " + r.text[:1500])

            try:
                jr = r.json()
                log(acc_name, "预约响应 JSON:\n" + json.dumps(jr, ensure_ascii=False, indent=2))
            except Exception:
                pass

            # 只要成功拿到 HTTP 响应，就认为“有回执了”，不再重试
            return r.status_code, r.text

        except requests.exceptions.Timeout as e:
            last_exc = e
            log(acc_name, f"预约超时 (第 {attempt} 次)：{e}")
            if attempt < MAX_RESERVE_RETRY:
                continue
        except requests.RequestException as e:
            last_exc = e
            log(acc_name, f"预约请求异常 (第 {attempt} 次)：{e}")
            if attempt < MAX_RESERVE_RETRY:
                continue

    # 跑到这里说明尝试了 MAX_RESERVE_RETRY 次都没拿到响应
    raise RuntimeError(f"连续 {MAX_RESERVE_RETRY} 次预约都未拿到有效响应，最后异常: {last_exc}")

def pick_schedule_for_account(acc, schedule_date_iso, course_name, teacher_name,
                              preferred_times, require_surplus):
    acc_name = acc["name"]
    headers = build_headers_for_account(acc)

    schedule_list = query_schedule_for_date(schedule_date_iso, headers)
    if not schedule_list:
        log(acc_name, f"{schedule_date_iso} 没拿到任何课程。")
        return None, headers

    preview_lines = []
    for i, it in enumerate(schedule_list[:8], 1):
        preview_lines.append(
            f"{i}. {it.get('GroupLessonName')} / {it.get('GLName')} "
            f"{it.get('StartTime')}-{it.get('EndTime')} "
            f"剩余:{it.get('SurplusNum')} | SID={it.get('ScheduleID')}"
        )
    log(acc_name, "当日课表（前8条）：\n" + "\n".join(preview_lines))

    picked = pick_slot(schedule_list, course_name, teacher_name, preferred_times, require_surplus)
    if picked is None:
        log(acc_name, "未找到符合策略的条目（可能已满或时间不匹配）。")
        try:
            debug_json = json.dumps(schedule_list[:3], ensure_ascii=False, indent=2)
        except Exception:
            debug_json = str(schedule_list[:3])
        log(acc_name, "样例调试:\n" + debug_json)
        return None, headers

    log(acc_name,
        "命中课程: "
        f"{picked.get('GroupLessonName')} / {picked.get('GLName')} "
        f"{picked.get('StartTime')}-{picked.get('EndTime')} "
        f"剩余 {picked.get('SurplusNum')} | SID={picked.get('ScheduleID')}"
    )

    log(acc_name, f"使用座位 rowNum={acc.get('rowNum',0)} colNum={acc.get('colNum',0)}")

    return picked, headers

def worker_run_for_account(acc, schedule_date_iso, course_name, teacher_name,
                           workday_rule, require_surplus):
    """
    线程内执行的单账号全流程：
    - 决定时间优先列表
    - 查课程并锁定目标
    - 带上该账号的 rowNum/colNum 去发预约（带重试）
    """
    acc_name = acc["name"]
    try:
        preferred_times = WORKDAY_PREFERRED_TIMES if workday_rule else HOLIDAY_PREFERRED_TIMES
        log(acc_name, f"开始处理账号，使用时间优先序列: {preferred_times} (工作日策略={workday_rule})")

        picked, headers = pick_schedule_for_account(
            acc,
            schedule_date_iso,
            course_name,
            teacher_name,
            preferred_times,
            require_surplus
        )

        if picked is None:
            log(acc_name, "未能选中目标课程，放弃预约")
            return

        status_code, _ = do_reservation(acc, acc_name, schedule_date_iso, picked, headers)
        log(acc_name, f"预约完成，HTTP {status_code}")
    except Exception as e:
        # 软错误日志，不抛到主线程
        log(acc_name, f"预约流程异常（可能已成功但未拿到回执）：{e}")
        log(acc_name, "建议手动在小程序里确认该账号的预约状态。")

def compute_target_date(args):
    """
    决定要预约哪一天：
    1) 如果传了 --date YYYY-MM-DD，就直接用
    2) 否则根据 --next-weekday (0=周一..6=周日)，计算“下一个对应星期几”
       默认 next-weekday=3 (= 周四)
    """
    if args.date:
        return dt.date.fromisoformat(args.date)

    today = dt.date.today()
    offset = (args.next_weekday - today.weekday()) % 7 or 7
    return today + dt.timedelta(days=offset)

def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="中大预约_多账号并发版 v4-multi-seat (Zumba 周四 19:20)")
    p.add_argument("--date", help="预约日期 YYYY-MM-DD；不传则按 --next-weekday 算", default=None)
    p.add_argument(
        "--next-weekday",
        type=int,
        default=3,  # 默认周四
        help="0=周一 ... 6=周日；默认3=周四 (=下一个周四)"
    )
    p.add_argument("--course", help="课程名（默认 小程序-Zumba）", default=None)
    p.add_argument("--teacher", help="老师名（默认 邢丹丹）", default=None)
    p.add_argument(
        "--allow-full",
        action="store_true",
        help="即使剩余名额=0 也尝试预约（候补/压接口用）"
    )
    p.add_argument(
        "--holiday-json",
        help="节假日JSON路径（可选，用于判断是不是补班/假日，从而决定用哪套时间优先序列）",
        default=None
    )
    return p.parse_args()

def main():
    args = parse_args()

    schedule_date = compute_target_date(args).isoformat()

    holiday_map = load_holiday_map(args.holiday_json)

    workday_rule = is_workday_rule(dt.date.fromisoformat(schedule_date), holiday_map)
    preferred_times_for_info = WORKDAY_PREFERRED_TIMES if workday_rule else HOLIDAY_PREFERRED_TIMES

    course_name    = args.course   or TARGET_COURSE_NAME
    teacher_name   = args.teacher  or TARGET_TEACHER_NAME
    require_surplus = REQUIRE_SURPLUS_DEFAULT if not args.allow_full else False

    print("=====================================================")
    print(f"并发预约任务启动：目标日期={schedule_date}")
    print(f"课程={course_name} / 老师={teacher_name}")
    print(f"工作日策略? {workday_rule}")
    print(f"时间优先序列={preferred_times_for_info}")
    print(f"需名额? {require_surplus}")
    print(f"账号数={len(ACCOUNTS)}")
    print("并发模式：ThreadPoolExecutor，同步提交全部账号任务，每个账号各自查课并下单。")
    print("=====================================================")

    with ThreadPoolExecutor(max_workers=len(ACCOUNTS)) as pool:
        futures = []
        for acc in ACCOUNTS:
            futures.append(pool.submit(
                worker_run_for_account,
                acc,
                schedule_date,
                course_name,
                teacher_name,
                workday_rule,
                require_surplus
            ))

        # 异常在 worker 内部已记录，这里只等待即可
        for f in futures:
            f.result()

    print("=== 全部账号尝试结束 ===")

if __name__ == "__main__":
    main()
