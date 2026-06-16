#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-reserve / 健小侠私教自动预约 - 全局时间变量版 (vFinal)
=================================================================
核心特性：
1. 预约目标默认为“明天”的私教时段。
2. 统一的全局时间配置：
   - WORKDAY_START_TIME = 工作日 / 补班日使用的起始时间
   - HOLIDAY_START_TIME = 休假日 / 周末使用的起始时间
   - DURATION_MINUTES    = 单节课时长（分钟）
3. 节假日/补班逻辑：
   - 如果节假日表标记“补班”，则认为是工作日 → WORKDAY_START_TIME
   - 如果节假日表标记“休假”，则认为是休息日 → HOLIDAY_START_TIME
   - 否则 fallback：周一~周五 → 工作日；周六周日 → 休假
4. 自动根据规则生成 startTime / endTime；并向后端下预约请求。
5. 请求结果通过 Bark 推送手机通知。
6. 日志会清楚告诉你：今天是按哪条规则走的、WORKDAY_START_TIME/HOLIDAY_START_TIME 分别是多少。

使用方法：
- 将 holidays_YYYY.json 放在本脚本同目录下（可选）
- 运行：python3 auto_reserve.py
- 可通过环境变量覆盖 START_TIME（手动指定今天想用的起始时间，优先级最高）

Cron 示例（每周六 07:00-07:50 & 23:00-23:50 每10分钟一次）：
*/10 7,23 * * 6 /usr/bin/python3 /path/auto_reserve.py >> /path/reserve.log 2>&1
"""

import os, sys, json, time, random, datetime as dt
import requests

# ======== 全局变量：门店、教练、课程、鉴权等固定配置 ========
WXAPPCHATID = "<SENSITIVE>"
CLUB_ID     = "2649"
COURSE_ID   = 146933
TRAINER_ID  = 12824681
DEPOSIT_ID  = 49172024
BASE_URL    = "https://www.forzadata.cn"

NAMES = {
    "club":    "健小侠-华信银座店",
    "trainer": "李明鑫",
    "course":  "至尊卡",
}

# ======== 全局变量：上课时间策略（你只要改这里） ========
WORKDAY_START_TIME   = "12:00"  # 工作日 / 补班日 默认起始时间
HOLIDAY_START_TIME   = "14:00"  # 休假日 / 周末 默认起始时间
DURATION_MINUTES     = 45       # 单节课时长分钟数

"""
规则说明（日志/推送里也会引用这组变量）：
- 工作日/补班：使用 WORKDAY_START_TIME
- 休假/周末 ：使用 HOLIDAY_START_TIME
- 结束时间 = 开始时间 + DURATION_MINUTES
如果某天你想硬约别的时间段，可以在运行时临时设置环境变量 START_TIME，
比如：START_TIME=15:00 python3 auto_reserve.py
优先级：环境变量 START_TIME > 节假日/补班判断 > 周几判断
"""

def log(msg):
    print(f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

# ===== Bark 推送 =====
def bark_url():
    env_base = os.getenv("BARK_URL", "").strip()
    default_base = "https://api.day.app/tEtZkUo5EQwWCYuYcAXdMP"
    base = env_base or default_base
    return base.rstrip("/")

def bark_push(title: str, body: str, group="预约机器人", level="active"):
    url = bark_url()
    payload = {
        "title": title,
        "body": body,
        "group": group,
        "level": level
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code
    except Exception as e:
        log(f"Bark 推送失败：{e}")
        return None

# ===== 通用小工具 =====
def compute_target_date():
    """
    预约日期使用【明天】。
    返回 (target_datetime对象, yyyymmdd数字)
    """
    now = dt.datetime.now()
    target = now + dt.timedelta(days=1)
    yyyymmdd = target.year * 10000 + target.month * 100 + target.day
    return target, yyyymmdd

def add_minutes(timestr, minutes):
    """
    "HH:MM" + minutes -> 新的 "HH:MM"
    """
    t = dt.datetime.strptime(timestr, "%H:%M")
    t2 = t + dt.timedelta(minutes=minutes)
    return t2.strftime("%H:%M")

# ===== 读取节假日表 =====
def load_holiday_dict_for_year(year: int):
    """
    读取与脚本同目录下的 holidays_YYYY.json
    预期结构：
    {
      "holiday": {
        "10-01": {
          "date": "2025-10-01",
          "name": "国庆节",
          "holiday": true
        },
        "10-12": {
          "date": "2025-10-12",
          "name": "国庆补班",
          "holiday": false
        }
      }
    }
    - holiday=true   表示休假日
    - holiday=false  表示工作日/可能补班
    """
    fname = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"holidays_{year}.json")
    if not os.path.exists(fname):
        log(f"【节假日】未找到 {os.path.basename(fname)}，将按自然周判断工作日/周末（工作日={WORKDAY_START_TIME} 休假={HOLIDAY_START_TIME}）。")
        return None

    try:
        with open(fname, "r", encoding="utf-8") as f:
            data = json.load(f)
        holiday_dict = data.get("holiday", {})
        if not isinstance(holiday_dict, dict):
            log("【节假日】JSON 格式异常：'holiday' 不是 dict。忽略节假日判断，将按自然周。")
            return None
        return holiday_dict
    except Exception as e:
        log(f"【节假日】读取失败：{e}。忽略节假日判断，将按自然周。")
        return None

# ===== 基本规则（不看节假日） =====
def base_rule_start_time_by_weekday(target_dt: dt.datetime):
    """
    没有节假日信息时：
    - 周一~周五 → 工作日 → WORKDAY_START_TIME
    - 周六周日 → 休息日 → HOLIDAY_START_TIME
    """
    if target_dt.weekday() <= 4:  # 0=Mon ... 4=Fri
        return WORKDAY_START_TIME
    else:
        return HOLIDAY_START_TIME

# ===== 综合节假日/补班逻辑 =====
def pick_start_time_by_holiday_logic(target_dt: dt.datetime, holiday_dict: dict):
    """
    根据节假日表 + 规则，决定开课时间，并给出解释字符串。
    逻辑：
    1. 如果节假日表里找到 target_dt：
       - 如果是补班日(holiday=false 且 name 包含“补班”) → 走工作日时间 WORKDAY_START_TIME
       - 如果是休假日(holiday=true)               → 走休假时间 HOLIDAY_START_TIME
       - 其他情况                                 → 回退到自然周规则
    2. 找不到该日期 → 回退到自然周规则

    返回 (start_time, reason)
    """
    iso_date = target_dt.date().isoformat()  # YYYY-MM-DD
    mmdd     = target_dt.strftime("%m-%d")   # MM-DD
    info     = None

    if holiday_dict:
        # 直接 key 命中 "MM-DD"
        if mmdd in holiday_dict:
            info = holiday_dict.get(mmdd)
        else:
            # 回退：遍历找 date == YYYY-MM-DD
            for maybe in holiday_dict.values():
                if isinstance(maybe, dict) and maybe.get("date") == iso_date:
                    info = maybe
                    break

    # 【未找到该日期在节假日表里】 → 按自然周
    if not info:
        base_t = base_rule_start_time_by_weekday(target_dt)
        reason = (
            f"未在节假日表中→按自然周: 工作日={WORKDAY_START_TIME} 休假={HOLIDAY_START_TIME} "
            f"→ {base_t}"
        )
        return base_t, reason

    is_holiday_flag = bool(info.get("holiday"))   # True=法定休假, False=工作/补班
    name            = str(info.get("name", ""))
    is_makeup_day   = (not is_holiday_flag) and ("补班" in name)

    if is_makeup_day:
        # 补班 → 当成工作日
        start_t = WORKDAY_START_TIME
        reason = f"命中补班《{name}》→ 使用工作日时间 {WORKDAY_START_TIME}"
        return start_t, reason

    if is_holiday_flag:
        # 法定休假 → 当成休假日
        start_t = HOLIDAY_START_TIME
        reason = f"命中休假《{name}》→ 使用休假时间 {HOLIDAY_START_TIME}"
        return start_t, reason

    # 其他状态：按自然周
    base_t = base_rule_start_time_by_weekday(target_dt)
    reason = (
        f"节假日表命中《{name}》但未归类为补班/休假→按自然周: "
        f"工作日={WORKDAY_START_TIME} 休假={HOLIDAY_START_TIME} → {base_t}"
    )
    return base_t, reason

# ===== 主流程 =====
def main():
    # 1. 计算预约目标日（明天）
    target_dt, date_val = compute_target_date()
    date_iso   = target_dt.date().isoformat()
    weekday_cn = ["周一","周二","周三","周四","周五","周六","周日"][target_dt.weekday()]

    # 2. 读取节假日表
    holiday_dict = load_holiday_dict_for_year(target_dt.year)

    # 3. 决定 start_time / end_time
    manual_start_time = os.getenv("START_TIME", "").strip()
    if manual_start_time:
        start_time = manual_start_time
        time_choice_reason = (
            f"检测到环境变量 START_TIME={manual_start_time} → 强制使用该时间 "
            f"(忽略工作日={WORKDAY_START_TIME}/休假={HOLIDAY_START_TIME} 规则)"
        )
    else:
        if holiday_dict is not None:
            start_time, time_choice_reason = pick_start_time_by_holiday_logic(target_dt, holiday_dict)
        else:
            start_time = base_rule_start_time_by_weekday(target_dt)
            time_choice_reason = (
                f"无节假日文件→按自然周规则: 工作日={WORKDAY_START_TIME} 休假={HOLIDAY_START_TIME} "
                f"→ {start_time}"
            )

    end_time = add_minutes(start_time, DURATION_MINUTES)

    # 4. 准备请求体
    payload = {
        "courseId":   COURSE_ID,
        "trainerId":  TRAINER_ID,
        "date":       date_val,      # yyyymmdd 数字
        "startTime":  start_time,
        "endTime":    end_time,
        "depositId":  DEPOSIT_ID,
        "remark":     ""
    }

    # 5. 请求参数
    url = f"{BASE_URL}/api/wx/addPrivateCourse/{CLUB_ID}/reserve"
    headers = {
        "content-type": "application/json",
        "WXAPPCHATID":  WXAPPCHATID,
        "Referer":      "https://servicewechat.com/wx3e933eed6525f934/19/page-frame.html",
        "User-Agent":   (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
            "MicroMessenger/8.0.62(0x18003e35) NetType/WIFI Language/zh_CN"
        ),
    }

    human_title = f"{NAMES['club']} | {NAMES['trainer']} | {NAMES['course']}"
    human_slot  = f"{date_iso} {start_time}~{end_time}"

    # 6. 打印日志（带全局变量）
    log("=== 预约任务开始 ===")
    log(f"门店：{NAMES['club']} (ID {CLUB_ID})")
    log(f"教练：{NAMES['trainer']} (ID {TRAINER_ID})")
    log(f"课程：{NAMES['course']} (ID {COURSE_ID})")
    log(f"目标日期：{date_iso}（{weekday_cn}）")
    log(f"全局时间策略：工作日={WORKDAY_START_TIME} / 休假={HOLIDAY_START_TIME} / 时长={DURATION_MINUTES}分钟")
    log(f"本次使用时段：{start_time}~{end_time}")
    log(f"时间段选择依据：{time_choice_reason}")

    # 给服务器一点随机抖动，避免所有实例并发同一毫秒打过去
    time.sleep(random.uniform(0.2, 0.8))

    # 7. 发送预约请求
    try:
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
    except requests.RequestException as e:
        log(f"请求失败：{e}")
        bark_push(
            "预约失败",
            f"{human_title}\n{human_slot}\n网络异常：{e}\n"
            f"(工作日={WORKDAY_START_TIME}, 休假={HOLIDAY_START_TIME}, 时长={DURATION_MINUTES}min)",
            group="健小侠",
            level="active"
        )
        sys.exit(2)

    status_code = resp.status_code
    try:
        data = resp.json()
    except Exception:
        data = {"text": resp.text}

    backend_status = data.get("status") if isinstance(data, dict) else None
    backend_msg    = data.get("message") if isinstance(data, dict) else None

    ok_guess = (
        200 <= status_code < 300 and
        (
            backend_status in (0, "0", None)
            or str(backend_status).lower() in ("ok", "success", "200")
        )
    )

    if ok_guess:
        log(f"✅ 成功：{human_title} 预约成功（{human_slot}）")
        if backend_msg:
            log(f"返回信息：{backend_msg}")
        bark_push(
            "预约成功",
            f"{human_title}\n{human_slot}\n"
            f"策略：工作日={WORKDAY_START_TIME} / 休假={HOLIDAY_START_TIME} / 时长={DURATION_MINUTES}min",
            group="健小侠",
            level="timeSensitive"
        )
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0)
    else:
        log(f"❌ 失败：{human_title} 预约失败（{human_slot}）")
        if backend_msg:
            log(f"原因：{backend_msg}")
        else:
            log(f"HTTP 状态：{status_code}，平台原始响应如下：")

        bark_push(
            "预约失败",
            f"{human_title}\n{human_slot}\n"
            f"原因：{backend_msg or '无具体原因'}\n"
            f"策略：工作日={WORKDAY_START_TIME} / 休假={HOLIDAY_START_TIME} / 时长={DURATION_MINUTES}min",
            group="健小侠",
            level="active"
        )
        print(json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, dict) else data)
        sys.exit(1)

if __name__ == "__main__":
    main()
