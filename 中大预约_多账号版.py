#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中大预约_多账号并发版 (v4-multi-seat)
=================================================
特性总览：
1. 多账号真实并发，ThreadPoolExecutor 同一时刻同时请求接口
2. 每个账号可单独配置 rowNum / colNum，避免所有账号都抢 (0,0) 导致冲突
3. 根据节假日/补班 vs 正常工作日/周末，自动切换时间优先序列
4. 课程筛选策略按优先级匹配 (课程+老师+指定开始时间) → (课程+老师) → (课程)
5. 可选 --allow-full 允许即使 SurplusNum=0 也尝试候补/压接口
6. 可用 --date 指定预约日期，也可用 --next-weekday 指出“下一个周X”
7. 日志中会标出每个账号自己的座位(rowNum/colNum)和预约响应结果

用法示例：
python 中大预约_多账号版_v4-multi-seat.py \
  --date 2025-10-31 \
  --course "小程序-杠铃充电" \
  --teacher "邢丹丹"

允许没名额也冲（候补）：
python 中大预约_多账号版_v4-multi-seat.py \
  --date 2025-10-31 \
  --course "小程序-杠铃充电" \
  --teacher "邢丹丹" \
  --allow-full

不指定 --date，则默认抢“下一个周五”（--next-weekday=4），可改。

cron 示例（每周六早上7点和晚上23点每10分钟开抢一轮）：
*/10 7,23 * * 6 /usr/bin/python3 /path/中大预约_多账号版_v4-multi-seat.py \
  --course "小程序-杠铃充电" \
  --teacher "邢丹丹" >> /path/reserve.log 2>&1

=================================================
非常关键：
- 你必须在 ACCOUNTS 里填多个账号的 OpenID / ClubID / BrandCode / APPID
- rowNum / colNum 是这个账号想占的位置（抢位坐标）
- 如果后端要求 Cookie / Authorization，也能给每个账号各自配置

=================================================
注意：
- 这个脚本假设接口:
    查询课表:  POST https://weixin.jianshenguanli.com/MemberInterface/WebService/Reservation.asmx/GetGroupLessonSchedule
    预约:      POST https://weixin.jianshenguanli.com/MemberInterface/WebService/Reservation.asmx/GroupLessonReservation

- 返回课表通常是 {"d":"[ {...}, {...} ]"} 这种结构，脚本中已自动 json.loads 两次

- 请求头中最关键的是 OpenID，它区分不同账号
- 请求体里最关键的是 groupLessondId (注意这个字段名有个 d)、scheduleId、rowNum、colNum

如果你的场馆接口字段和这里完全一致，那你可以直接跑。
如果不一致，按你的实际抓包字段改。

=================================================
"""

import datetime as dt
import json
import sys
import requests
from concurrent.futures import ThreadPoolExecutor

# ========================= 多账号配置 =========================
# ⚠️ 你需要在这里把每个账号的信息填好
# - name: 用来区分日志，比如 "小红", "小明"
# - OpenID: 你抓包看到的 OpenID（不同微信用户不同）
# - ClubID / BrandCode / APPID: 抓包里的对应字段
# - rowNum / colNum: 该账号希望占的座位坐标
#   * 如果你不清楚row/col是什么，就保持 0/0，另外的账号可以设 0/1, 0/2... 避免同一位置冲突
# - Cookie / Authorization: 只有在你的接口请求头里出现这些才需要加；否则可以删掉这两行

ACCOUNTS = [
    # {
    #     "name": "李晨",
    #     "OpenID": "<SENSITIVE>",
    #     "ClubID": "57115e05-ea7e-4411-b062-c2bb5d5f1b36",
    #     "BrandCode": "8961",
    #     "APPID": "wx3bb18aff4f2fe45f",

    #     # 如需鉴权可打开：
    #     # "Cookie": "<SENSITIVE>",
    #     # "Authorization": "<SENSITIVE>",

    #     # 该账号想预定的座位坐标
    #     "rowNum": 0,
    #     "colNum": 2,
    # },
     {
         "name": "刘小果",
         "OpenID": "<SENSITIVE>",
         "ClubID": "57115e05-ea7e-4411-b062-c2bb5d5f1b36",
         "BrandCode": "8961",
         "APPID": "wx3bb18aff4f2fe45f",
         "rowNum": 0,
         "colNum": 2,
     },
    {
        "name": "李娜",
        "OpenID": "<SENSITIVE>",
        "ClubID": "57115e05-ea7e-4411-b062-c2bb5d5f1b36",
        "BrandCode": "8961",
        "APPID": "wx3bb18aff4f2fe45f",

        # 如需鉴权可打开：
        # "Cookie": "<SENSITIVE>",
        # "Authorization": "<SENSITIVE>",

        # 该账号想预定的座位坐标
        "rowNum": 0,
        "colNum": 0,
    },
    {
        "name": "曹剑飞",
        "OpenID": "<SENSITIVE>",
        "ClubID": "57115e05-ea7e-4411-b062-c2bb5d5f1b36",
        "BrandCode": "8961",
        "APPID": "wx3bb18aff4f2fe45f",

        # 如需鉴权可打开：
        # "Cookie": "<SENSITIVE>",
        # "Authorization": "<SENSITIVE>",

        # 该账号想预定的座位坐标
        "rowNum": 1,
        "colNum": 0,
    },
]

# ========================= 课程筛选全局配置 =========================
# 目标课程和老师的名称（默认值，可以用命令行参数覆盖）
TARGET_COURSE_NAME   = "小程序-杠铃充电"  # 对应 GroupLessonName
TARGET_TEACHER_NAME  = "邢丹丹"          # 对应 GLName

# 时间段优先策略：
#   工作日/补班 → 优先这些开始时间
WORKDAY_PREFERRED_TIMES  = ["18:30", "18:20", "19:20"]

#   周末/法定休假 → 优先这些开始时间
HOLIDAY_PREFERRED_TIMES  = ["14:00", "15:00", "16:00", "18:20", "19:20"]

# 默认要求必须有剩余名额 SurplusNum>0 才会尝试
# 如果你想即使剩余=0 也冲（候补/压接口），运行脚本时加 `--allow-full`
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
    最关键的是：OpenID / ClubID / BrandCode / APPID。
    这些值必须是纯 ASCII，不能包含中文，否则 requests 会报 header 编码错误。
    """
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

    # 某些场馆会用 Cookie 或 Authorization 校验身份，如果你抓包里有它们就加
    if "Cookie" in acc and acc["Cookie"]:
        headers["Cookie"] = acc["Cookie"]
    if "Authorization" in acc and acc["Authorization"]:
        headers["Authorization"] = acc["Authorization"]

    # 检查 header 必须是 ASCII，避免 "latin-1 codec" 报错
    for k, v in headers.items():
        if not is_ascii(str(v)):
            raise ValueError(
                f"账号[{acc.get('name')}] 的 {k} 含非 ASCII 字符，请使用真实值（不要留中文占位）。"
            )

    # 确保核心字段都有
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

    支持的 JSON 结构示例：
    1) { "2025-10-01": {"is_workday": false}, ... }
    2) [
         {"date": "2025-10-01", "type": "holiday"},
         {"date": "2025-10-12", "type": "workday"}
       ]
    3) { "days":[{"date":"2025-10-01", "isOffDay":1}, ...] }
       其中 isOffDay=1 表示放假，=0 表示上班/补班

    如果不给 --holiday-json 或解析失败，返回空 {}
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
        # 统一成 YYYY-MM-DD
        # 允许 date_str 是 "YYYY/MM/DD"、"YYYY.MM.DD"
        iso_like = date_str.split(" ")[0].replace(".", "-").replace("/", "-")
        ymd = iso_like.split("-")
        if len(ymd) == 3:
            y, m, d2 = ymd
            try:
                d = dt.date(int(y), int(m), int(d2))
                mapping[d.isoformat()] = bool(is_work)
            except Exception:
                pass

    # dict 情况
    if isinstance(data, dict):
        # 直接 { "2025-10-01": {...}, ... }
        for k, v in data.items():
            if isinstance(v, dict) and ("is_workday" in v or "isOffDay" in v or "type" in v):
                if "is_workday" in v:
                    mark(k, bool(v["is_workday"]))
                elif "isOffDay" in v:
                    mark(k, not bool(int(v["isOffDay"])))
                elif "type" in v:
                    mark(k, str(v["type"]).lower() == "workday")

        # 也可能是 {"days":[...]} / {"list":[...]} / {"data":[...]} / {"holiday":[...]} 等
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

    # list 情况
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
    """
    根据 holiday_map / 自然周 来决定使用哪套时间优先列表。
    返回 True  -> 走工作日策略 (WORKDAY_PREFERRED_TIMES)
         False -> 走周末/休假策略 (HOLIDAY_PREFERRED_TIMES)
    """
    key = target_date.isoformat()
    if key in holiday_map:
        return holiday_map[key]
    # fallback：周一~周五认为工作日，其余认为休假
    return target_date.weekday() < 5

def query_schedule_for_date(schedule_date_iso: str, headers: dict):
    """
    查询指定日期的全部课程列表。
    POST: GetGroupLessonSchedule
    body: {"scheduleDate": "YYYY-MM-DD"}

    典型返回：
        {"d":"[ {...}, {...} ]"}
    也可能是直接 list

    返回：list[dict]，每个dict类似：
        {
          "ScheduleID": "...",
          "GroupLessonID": "...",
          "GroupLessonName": "小程序-杠铃充电",
          "GLName": "邢丹丹",
          "StartTime": "18:20",
          "EndTime": "19:10",
          "SurplusNum": "0",
          ...
        }
    """
    payload = {"scheduleDate": schedule_date_iso}
    r = requests.post(URL_QUERY, json=payload, headers=headers, timeout=TIMEOUT_QUERY, verify=VERIFY_TLS)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} during GetGroupLessonSchedule: {r.text[:300]}")

    try:
        j = r.json()
    except Exception:
        j = json.loads(r.text)

    # 有的返回是 {"d": "...string json..."}
    if isinstance(j, dict) and "d" in j:
        data = json.loads(j["d"])
    else:
        data = j

    # 有时候 data 是 dict 里嵌 list
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
    # Step 1: 课程+老师+时间
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

    # Step 2: 课程+老师
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

    # Step 3: 仅课程名
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
    这里用该账号自己的 rowNum / colNum，避免全部账号抢同一个(0,0)。
    Body 结构遵循你之前抓包的格式：
        {
            "colNum": X,
            "groupLessondId": "<GroupLessonID>",
            "rowNum": Y,
            "scheduleDate": "YYYY-MM-DD",
            "scheduleId": "<ScheduleID>"
        }
    注意 groupLessondId 这个 key 带 d

    返回: (status_code, text)。如果连续多次都未拿到响应会抛异常，由上层处理。
    """
    rowNum = acc.get("rowNum", 0)
    colNum = acc.get("colNum", 0)

    body = {
        "colNum": colNum,
        "groupLessondId": picked_item["GroupLessonID"],  # 注意: groupLessondId (有个 d)
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

            # 如果返回的是json，也打印一下方便检查
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
                continue  # 继续下一轮重试
        except requests.RequestException as e:
            last_exc = e
            log(acc_name, f"预约请求异常 (第 {attempt} 次)：{e}")
            if attempt < MAX_RESERVE_RETRY:
                continue

    # 跑到这里说明尝试了 MAX_RESERVE_RETRY 次都没拿到响应
    raise RuntimeError(f"连续 {MAX_RESERVE_RETRY} 次预约都未拿到有效响应，最后异常: {last_exc}")

def pick_schedule_for_account(acc, schedule_date_iso, course_name, teacher_name,
                              preferred_times, require_surplus):
    """
    单账号完整流程（除真正提交预约）：
    1. 根据账号构造 headers
    2. 查询这一天的课表
    3. 打印前几条课表，方便调试
    4. 根据策略挑出目标课程条目
    """
    acc_name = acc["name"]
    headers = build_headers_for_account(acc)

    schedule_list = query_schedule_for_date(schedule_date_iso, headers)
    if not schedule_list:
        log(acc_name, f"{schedule_date_iso} 没拿到任何课程。")
        return None, headers

    # 打课表预览（前8条）
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
        # 打前三个完整JSON，方便你对比
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
    - 决定这个账号用哪套时间优先列表
    - 查课程并锁定目标
    - 带上这个账号的 rowNum/colNum 去发预约（带重试）
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
        # 这里不再向外抛，避免主线程打印 FATAL；但把信息打详细一点
        log(acc_name, f"预约流程异常（可能已成功但未拿到回执）：{e}")
        log(acc_name, "建议手动在小程序里确认该账号的预约状态。")

def compute_target_date(args):
    """
    决定要预约哪一天：
    1) 如果传了 --date YYYY-MM-DD，就直接用
    2) 否则根据 --next-weekday (0=周一..6=周日，默认4=周五)，计算“下一个对应星期几”
       举例：今天周四，--next-weekday=4 表示下一个周五，也就是明天
             今天周五，--next-weekday=4 表示下一个周五，也就是+7天
    """
    if args.date:
        return dt.date.fromisoformat(args.date)

    today = dt.date.today()
    offset = (args.next_weekday - today.weekday()) % 7 or 7
    return today + dt.timedelta(days=offset)

def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="中大预约_多账号并发版 v4-multi-seat")
    p.add_argument("--date", help="预约日期 YYYY-MM-DD；不传则按 --next-weekday 算", default=None)
    p.add_argument(
        "--next-weekday",
        type=int,
        default=4,
        help="0=周一 ... 6=周日；默认4=周五 (=下一个周五)"
    )
    p.add_argument("--course", help="课程名（默认 TARGET_COURSE_NAME）", default=None)
    p.add_argument("--teacher", help="老师名（默认 TARGET_TEACHER_NAME）", default=None)
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

    # 1. 计算目标日期
    schedule_date = compute_target_date(args).isoformat()

    # 2. 解析节假日/补班表（可选）
    holiday_map = load_holiday_map(args.holiday_json)

    # 3. 判断今天用哪套时间优先列表
    workday_rule = is_workday_rule(dt.date.fromisoformat(schedule_date), holiday_map)
    preferred_times_for_info = WORKDAY_PREFERRED_TIMES if workday_rule else HOLIDAY_PREFERRED_TIMES

    # 4. 课程名/老师名/名额策略
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

    # 5. 真正并发：所有账号同时开打
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

        # 等线程全部结束。异常在 worker 内部已记录，这里只等待即可。
        for f in futures:
            f.result()

    print("=== 全部账号尝试结束 ===")

if __name__ == "__main__":
    main()
