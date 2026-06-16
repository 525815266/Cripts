#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
唯享客：签到 + 查询签到页抽奖机会 + 执行抽奖 + 智能点赞任务
HAR 只用于定位接口，不作为后续运行依赖。
"""

import json
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from http.cookies import SimpleCookie

import requests

# =========================
# 脚本开关（只作用于本脚本）
# =========================
DEBUG = 0
DRAW_WHEN_HAS_CHANCE = True
MAX_DRAW_TIMES = 3
ENABLE_LIKE_TASK = True
LIKE_TARGET_COUNT = 5          # 每天点赞 5 个
LIKE_PAGE_SIZE = 10            # 每页拉取 10 条
LIKE_MAX_PAGES = 3             # 最多翻 3 页找可点赞内容
LIKE_SLEEP_SECONDS = 1.2       # 两次点赞间隔
LIKE_DO_VIEW_BEFORE = True     # 点赞前补一个 content/view，更贴近真实流程

# =========================
# 登录/通用参数（按需更新）
# =========================
API_KEY = "<SENSITIVE>"
APP_NAME = "weixiangke_iphone"
APP_VERSION = "7.00.5"
MARS_CID = "8fee1801daf6476c990f052140b00e0d08d0502c"
FDC_AREA_ID = "105100101"
WAREHOUSE = "VIP_CD"
UCODE = "pkf06pck"
USER_TOKEN = "<SENSITIVE>"

# =========================
# 签到
# =========================
SIGN_URL = "https://wxk.vip.com/api/v1/sign/userSign"
SIGN_HEADERS = {
    "Content-Type": "application/json",
    "Cookie": "<SENSITIVE>",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148_VipUnion VipUnion/6.73.5 (iphone; 2.0.0; 4c2be11ac573be1474d0aed47fe855b6c7800e4d)",
}
SIGN_BODY = {"source": "weixiangke_iphone"}

# =========================
# 签到页抽奖
# =========================
COMMON_FORM = {
    "warehouse": WAREHOUSE,
    "mars_cid": MARS_CID,
    "client": "3",
    "fdc_area_id": FDC_AREA_ID,
    "area_id": FDC_AREA_ID,
    "channel": "app",
    "mobile_platform": "<SENSITIVE>",
    "mobile_channel": "<SENSITIVE>",
    "app_name": APP_NAME,
    "app_version": APP_VERSION,
    "sd_tuijian": "0",
    "standby_id": "ng00010v:al80ssgp:37u8zn0w:ng00010p",
    "is_default_area": "1",
    "sys_version": "26.3.1",
    "cpsCookie": "",
    "api_key": API_KEY,
    "ucode": UCODE,
}

COMMON_POST_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://mst.vip.com",
    "Referer": "https://mst.vip.com/",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 26_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 VipUnion/7.00.5 (iphone; 2.0.0; 8fee1801daf6476c990f052140b00e0d08d0502c)",
}

API_SIGN_GET_ACTIVITY_PRIZE = "0bd1251e26d1bcf24c628e498195a36906b2bed0"
API_SIGN_GET_LOTTERY_RULES = "24361c8abc1cf447a499321f31125cfb3ddce05f"
API_SIGN_GET_AWARD_LIST = "a09e61e16b45a747d6dc7e6c1fd74be6255e1943"
API_SIGN_LOTTERY_DRAW = "434b7822c71d3f46aceee809914de7c44f4f407d"

GET_ACTIVITY_PRIZE_URL = "https://api.union.vip.com/vsp/signTask/getActivityPrize"
GET_LOTTERY_RULES_URL = "https://api.union.vip.com/vsp/luckylottery/getLotteryRules"
GET_AWARD_LIST_URL = "https://api.union.vip.com/vsp/luckylottery/getAwardList"
LOTTERY_DRAW_URL = "https://api.union.vip.com/vsp/luckylottery/lotteryDraw"

# =========================
# 活动报名
# =========================
ENABLE_ACTIVITY_APPLY = True
ACTIVITY_MAX_APPLY = 10

ACTIVITY_FORM = {
    "warehouse": "VIP_CD",
    "mars_cid": MARS_CID,
    "client": "3",
    "fdc_area_id": "105100101",
    "area_id": "105100101",
    "channel": "app",
    "mobile_platform": "<SENSITIVE>",
    "mobile_channel": "<SENSITIVE>",
    "app_name": APP_NAME,
    "app_version": APP_VERSION,
    "sd_tuijian": "0",
    "standby_id": "ng00010v:al80ssgp:37u8zn0w:ng00010p",
    "is_default_area": "1",
    "sys_version": "26.3.1",
    "cpsCookie": "",
    "api_key": "<SENSITIVE>",
}

ACTIVITY_LIST_URL = "https://api.union.vip.com/vsp/task/activityListForH5"
ACTIVITY_APPLY_URL = "https://wxk.vip.com/api/v1/activity/apply/task"
ACTIVITY_PAGE_URL = "https://mst.vip.com/KzVHsMh21I2JkmWYKdxQDw.php?nova_platform=1&sd_tuijian=0&source=app&warehouse=VIP_CD&app_name=weixiangke_iphone&app_version=7.00.5&nova=1&mobile_platform=3&f=CPS&client=iphone&_src=mst&extra_banner=0&mst_page_type=guide&wapid=mst_100081167&mars_cid=8fee1801daf6476c990f052140b00e0d08d0502c&protocol_version=2.0.0&fdc_area_id=105100101&height=2796&width=1290&area_id=105100101"


# =========================
# 唯享圈点赞任务
# =========================
WXQ_BASE_FORM = {
    "api_key": API_KEY,
    "appName": APP_NAME,
    "appVersion": APP_VERSION,
    "app_name": APP_NAME,
    "app_version": APP_VERSION,
    "fdc_area_id": FDC_AREA_ID,
    "marsCid": MARS_CID,
    "mars_cid": MARS_CID,
    "sd_tuijian": "0",
    "ucode": UCODE,
    "userToken": USER_TOKEN,
    "warehouse": WAREHOUSE,
}

WXQ_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": '{"appversion":"7.00.5","platform":"ios"}',
}

API_SIGN_CONTENT_LIST = "9f8851aa5ffbf2e96219a8b9a5cdd9d48385f344"
API_SIGN_CONTENT_VIEW = "69f1cec3ee1265450d09a20b09b3f43a98b38e64"
API_SIGN_CONTENT_LIKE = "e15e90cc7664f9dbe677414d3342c310a499127a"

CONTENT_LIST_URL = "https://api.union.vip.com/api/wxq/content/list"
CONTENT_VIEW_URL = "https://api.union.vip.com/api/wxq/content/view"
CONTENT_LIKE_URL = "https://api.union.vip.com/api/wxq/content/like"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def bj_ts_ms() -> str:
    tz_bj = timezone(timedelta(hours=8))
    return str(int(datetime.now(tz_bj).timestamp() * 1000))


def bj_ts_s() -> str:
    tz_bj = timezone(timedelta(hours=8))
    return str(int(datetime.now(tz_bj).timestamp()))


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def debug(msg: str) -> None:
    if DEBUG:
        log(msg)


def success(msg: str) -> None:
    log(f"✅ {msg}")


def warn(msg: str) -> None:
    log(f"⚠️ {msg}")


def error(msg: str) -> None:
    log(f"❌ {msg}")


def dump_json_compact(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(obj)


def load_cookie_header_to_session(session: requests.Session, cookie_header: str) -> None:
    if not cookie_header:
        return
    c = SimpleCookie()
    c.load(cookie_header)
    for k, morsel in c.items():
        session.cookies.set(k, morsel.value, domain=".vip.com", path="/")


def warmup_activity_session(session: requests.Session) -> None:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "User-Agent": COMMON_POST_HEADERS["User-Agent"],
    }
    resp = session.get(ACTIVITY_PAGE_URL, headers=headers, timeout=20)
    debug(f"[activityPage] HTTP={resp.status_code}")
    vpc = session.cookies.get("vpc_uinfo")
    if DEBUG:
        debug(f"[activityPage] vpc_uinfo={vpc or '无'}")


def post_form(session: requests.Session, url: str, api_sign: str, data: dict, timeout: int = 20):
    headers = dict(COMMON_POST_HEADERS)
    headers["Authorization"] = f"OAuth api_sign={api_sign}"
    body = urlencode(data)
    return session.post(url, headers=headers, data=body, timeout=timeout)


def post_plain_form(session: requests.Session, url: str, data: dict, timeout: int = 20):
    headers = dict(COMMON_POST_HEADERS)
    body = urlencode(data)
    return session.post(url, headers=headers, data=body, timeout=timeout)


def post_wxq_form(session: requests.Session, url: str, api_sign: str, data: dict, timeout: int = 20):
    headers = dict(WXQ_HEADERS)
    headers["Authorization"] = f"OAuth api_sign={api_sign}"
    body = urlencode(data)
    return session.post(url, headers=headers, data=body, timeout=timeout)


def safe_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return None


def summarize_sign(payload: dict) -> tuple[str, int]:
    code = payload.get("code")
    msg = payload.get("msg") or payload.get("message") or ""
    error_flag = payload.get("error")
    data = payload.get("data") or {}

    today_draws = 0
    growth = None
    signed_today = None
    task_day_num = None

    sign_outer = data.get("signMap") or {}
    sign_map = sign_outer.get("signMap") or {}
    task_day_num = sign_outer.get("taskDayNum")
    today_key = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    today_info = sign_map.get(today_key) or {}
    signed_today = today_info.get("signed")
    today_draws = int(today_info.get("numberOfDraws") or 0)

    progress = sign_outer.get("signProgress") or {}
    growth = progress.get("currentSignGrowthValue")

    if code in (0, 200) and (error_flag is False or error_flag is None):
        parts = ["今天已签到" if signed_today else "签到成功"]
        if growth is not None:
            parts.append(f"成长值 +{growth}")
        if task_day_num is not None:
            parts.append(f"本月签到 {task_day_num} 天")
        parts.append(f"抽奖次数 {today_draws}")
        return "，".join(parts), today_draws

    if code == 201:
        return f"今天已签到，抽奖次数 {today_draws}", today_draws

    if code == 403 or "请登录" in msg:
        return "签到失败：登录态无效，请更新 Cookie", today_draws

    return f"签到返回异常：code={code}, msg={msg or '无'}", today_draws


def parse_activity_prize(payload: dict) -> tuple[list, str]:
    if not payload:
        return [], "接口无返回"
    code = payload.get("code")
    msg = payload.get("msg") or ""
    if code != 1:
        return [], f"code={code}, msg={msg or '无'}"
    data = payload.get("data") or {}
    return data.get("lotteryList") or [], ""


def choose_lottery_act(lottery_list: list):
    if not lottery_list:
        return None
    positive = [x for x in lottery_list if int(x.get("remainingTimes") or 0) > 0]
    return positive[0] if positive else lottery_list[0]


def parse_rules(payload: dict) -> tuple[dict, str]:
    if not payload:
        return {}, "接口无返回"
    code = payload.get("code")
    msg = payload.get("msg") or ""
    if code != 1:
        return {}, f"code={code}, msg={msg or '无'}"
    return payload.get("data") or {}, ""


def parse_award_preview(payload: dict) -> tuple[list, str]:
    if not payload:
        return [], "接口无返回"
    code = payload.get("code")
    msg = payload.get("msg") or ""
    if code != 1:
        return [], f"code={code}, msg={msg or '无'}"
    data = payload.get("data") or {}
    return data.get("rewardList") or [], ""


def parse_draw_result(payload: dict) -> tuple[bool, str]:
    if not payload:
        return False, "抽奖返回非 JSON"
    code = payload.get("code")
    msg = payload.get("msg") or ""
    data = payload.get("data") or {}
    if code != 1:
        return False, f"抽奖失败：code={code}, msg={msg or '无'}"
    reward = data.get("reward") or {}
    reward_name = reward.get("plateRewardName") or reward.get("name") or "未知奖励"
    return True, f"获得：{reward_name}"


def parse_content_list(payload: dict) -> tuple[list, str]:
    if not payload:
        return [], "接口无返回"
    code = payload.get("code")
    msg = payload.get("msg") or ""
    if code != 1:
        return [], f"code={code}, msg={msg or '无'}"
    data = payload.get("data") or {}
    return data.get("shareContentInfoList") or [], ""


def collect_unliked_candidates(items: list) -> list:
    results = []
    for item in items:
        info = item.get("shareContentInfo") or {}
        stats = item.get("shareContentStats") or {}
        cid = info.get("id")
        title = info.get("title") or (info.get("shareText") or "").splitlines()[0][:20] or f"内容{cid}"
        interactable = bool(info.get("interactable"))
        is_liked = bool(stats.get("isLiked"))
        if not cid or not interactable or is_liked:
            continue
        results.append({
            "content_id": cid,
            "title": title.strip(),
            "is_liked": is_liked,
            "content_type": info.get("contentType"),
            "like_count": stats.get("likeCount") or 0,
        })
    return results


def call_content_view(session: requests.Session, content_ids: list[int]) -> None:
    if not content_ids:
        return
    form = dict(WXQ_BASE_FORM)
    form["timestamp"] = bj_ts_s()
    form["contentIds"] = ",".join(str(x) for x in content_ids)
    try:
        resp = post_wxq_form(session, CONTENT_VIEW_URL, API_SIGN_CONTENT_VIEW, form, timeout=15)
        payload = safe_json(resp)
        debug(f"[content/view] HTTP={resp.status_code} resp={dump_json_compact(payload or resp.text[:300])}")
    except Exception as exc:
        debug(f"[content/view] 异常：{exc}")


def parse_activity_list(payload: dict) -> tuple[list[dict], str | None]:
    if not isinstance(payload, dict):
        return [], "返回格式异常"
    code = payload.get("code")
    msg = payload.get("msg") or payload.get("message") or ""
    data = payload.get("data") or {}
    rc = (data.get("returnCode") or {}).get("code")
    if code != 1 or rc not in (0, None):
        return [], f"code={code}, msg={msg}"
    items = data.get("activityTaskList") or []
    return items, None


def collect_unenrolled_activities(items: list[dict]) -> list[dict]:
    chosen = []
    for item in items:
        if not isinstance(item, dict):
            continue
        task_no = str(item.get("taskNo") or "").strip()
        name = str(item.get("name") or item.get("taskName") or task_no).strip()
        enroll_state = str(item.get("enrollCheckResult") or "")
        going_status = str(item.get("goingStatus") or "")
        settled = str(item.get("settled") or "")
        if not task_no:
            continue
        if enroll_state != "UN_ENROLL":
            continue
        if going_status not in ("ON_WAY", "NOT_START", "ENROLLING"):
            continue
        if settled == "1":
            continue
        chosen.append({
            "taskNo": task_no,
            "name": name,
            "enrollCheckResult": enroll_state,
            "goingStatus": going_status,
            "enrollEndTime": item.get("enrollEndTime") or "",
        })
    return chosen


def parse_apply_result(payload: dict) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "返回格式异常"
    code = payload.get("code")
    msg = payload.get("msg") or payload.get("message") or ""
    data = payload.get("data") or {}
    rc = (data.get("returnCode") or {}).get("code")
    enroll = data.get("enrollResult") or {}
    result_code = str(enroll.get("resultCode") or "")
    result_msg = enroll.get("resultMsg") or msg or "未知结果"
    if code == 200 and rc == 0 and result_code in ("1000", "1001"):
        return True, result_msg
    return False, f"code={code}, msg={msg or result_msg}"


def do_activity_apply(session: requests.Session) -> None:
    if not ENABLE_ACTIVITY_APPLY:
        warn("已关闭活动报名，跳过")
        return
    log("查询可报名活动...")
    form = dict(ACTIVITY_FORM)
    form.update({
        "pageSize": "10",
        "pageStart": "1",
        "listType": "0",
        "timestamp": str(bj_ts_ms()),
        "source": "weixiangke_iphone",
        "scenario": "specialList",
    })
    try:
        resp = post_plain_form(session, ACTIVITY_LIST_URL, form, timeout=20)
        debug(f"[activityListForH5] HTTP={resp.status_code}")
        payload = safe_json(resp)
        if DEBUG and payload is not None:
            print(dump_json_compact(payload))
        items, err = parse_activity_list(payload or {})
        if not items:
            warn(f"未获取到活动列表{('：' + err) if err else ''}")
            return
        candidates = collect_unenrolled_activities(items)
        log(f"活动列表共 {len(items)} 个，可报名 {len(candidates)} 个")
        if not candidates:
            success("当前没有可报名活动，跳过")
            return
        apply_count = 0
        for idx, act in enumerate(candidates[:ACTIVITY_MAX_APPLY], 1):
            log(f"报名活动 {idx}/{min(len(candidates), ACTIVITY_MAX_APPLY)}：{act['name']}")
            apply_form = dict(ACTIVITY_FORM)
            apply_form.update({
                "timestamp": str(bj_ts_ms()),
                "source": "weixiangke_iphone",
                "taskNo": act["taskNo"],
            })
            try:
                resp = post_plain_form(session, ACTIVITY_APPLY_URL, apply_form, timeout=20)
                debug(f"[apply/task {act['taskNo']}] HTTP={resp.status_code}")
                payload = safe_json(resp)
                if DEBUG and payload is not None:
                    print(dump_json_compact(payload))
                ok, txt = parse_apply_result(payload or {})
                if ok:
                    apply_count += 1
                    success(f"报名成功：{act['name']}（{txt}）")
                else:
                    warn(f"报名失败：{act['name']}（{txt}）")
                time.sleep(1.0)
            except Exception as exc:
                warn(f"报名异常：{act['name']}（{exc}）")
        log(f"活动报名结束：成功 {apply_count}/{min(len(candidates), ACTIVITY_MAX_APPLY)} 个")
    except Exception as exc:
        error(f"查询活动列表异常：{exc}")


def do_like_task(session: requests.Session) -> None:
    if not ENABLE_LIKE_TASK:
        warn("已关闭点赞任务，跳过")
        return

    log("开始执行：点赞任务")
    chosen = []
    seen = set()

    for page in range(1, LIKE_MAX_PAGES + 1):
        form = dict(WXQ_BASE_FORM)
        form.update({
            "timestamp": bj_ts_s(),
            "groupType": "-1",
            "page": str(page),
            "pageSize": str(LIKE_PAGE_SIZE),
            "sceneType": "1",
        })
        try:
            resp = post_wxq_form(session, CONTENT_LIST_URL, API_SIGN_CONTENT_LIST, form, timeout=20)
            payload = safe_json(resp)
            debug(f"[content/list page={page}] HTTP={resp.status_code}")
            if DEBUG and payload is not None:
                print(dump_json_compact(payload))
            items, err = parse_content_list(payload or {})
            if not items:
                warn(f"第 {page} 页未获取到内容列表{('：' + err) if err else ''}")
                continue
            cands = collect_unliked_candidates(items)
            log(f"第 {page} 页获取到 {len(items)} 条内容，可点赞 {len(cands)} 条")
            for c in cands:
                if c["content_id"] in seen:
                    continue
                seen.add(c["content_id"])
                chosen.append(c)
                if len(chosen) >= LIKE_TARGET_COUNT:
                    break
            if len(chosen) >= LIKE_TARGET_COUNT:
                break
        except Exception as exc:
            warn(f"获取第 {page} 页内容异常：{exc}")

    if not chosen:
        warn("未找到可点赞内容，跳过点赞任务")
        return

    log(f"已筛选出 {len(chosen)} 条未点赞内容，计划点赞 {min(LIKE_TARGET_COUNT, len(chosen))} 条")
    if LIKE_DO_VIEW_BEFORE:
        call_content_view(session, [x["content_id"] for x in chosen[:min(4, len(chosen))]])

    success_count = 0
    target = min(LIKE_TARGET_COUNT, len(chosen))
    for idx, item in enumerate(chosen[:target], 1):
        content_id = item["content_id"]
        title = item["title"] or str(content_id)
        form = dict(WXQ_BASE_FORM)
        form.update({
            "timestamp": bj_ts_s(),
            "action": "1",
            "contentId": str(content_id),
            "page": "0",
            "pageSize": "0",
        })
        try:
            log(f"执行点赞 {idx}/{target}：{title}（ID={content_id}）")
            resp = post_wxq_form(session, CONTENT_LIKE_URL, API_SIGN_CONTENT_LIKE, form, timeout=20)
            payload = safe_json(resp)
            debug(f"[content/like {idx}/{target}] HTTP={resp.status_code}")
            if DEBUG and payload is not None:
                print(dump_json_compact(payload))
            if not payload:
                warn(f"第 {idx}/{target} 次点赞返回非 JSON")
                continue
            code = payload.get("code")
            msg = payload.get("msg") or ""
            data = payload.get("data") or {}
            if code == 1 and data.get("liked") is True:
                success_count += 1
                success(f"点赞成功：{msg or '已完成'}")
            elif "已点赞" in msg or "重复" in msg:
                warn(f"该内容可能已点赞：{msg}")
            else:
                warn(f"点赞失败：code={code}, msg={msg or '无'}")
            if idx != target:
                time.sleep(LIKE_SLEEP_SECONDS)
        except Exception as exc:
            warn(f"第 {idx}/{target} 次点赞异常：{exc}")

    log(f"点赞任务结束：成功 {success_count}/{target} 次")


# =========================
# 主流程
# =========================
def main():
    print(f"## 开始执行... {now_str()}")
    session = requests.Session()
    load_cookie_header_to_session(session, SIGN_HEADERS.get("Cookie", ""))

    log("开始签到...")
    try:
        resp = session.post(SIGN_URL, headers=SIGN_HEADERS, json=SIGN_BODY, timeout=20)
        debug(f"[SIGN] HTTP={resp.status_code}")
        sign_payload = safe_json(resp)
        if sign_payload is None:
            error(f"签到返回非 JSON：HTTP={resp.status_code}")
            print((resp.text or "")[:1000])
            return
        if DEBUG:
            print(dump_json_compact(sign_payload))
        sign_text, _today_draws = summarize_sign(sign_payload)
        if "失败" in sign_text or "异常" in sign_text:
            error(sign_text)
            return
        success(sign_text)
    except Exception as exc:
        error(f"签到请求异常：{exc}")
        return

    # 抽奖
    base_form = dict(COMMON_FORM)
    base_form["timestamp"] = bj_ts_ms()

    log("查询签到页抽奖活动...")
    try:
        resp = post_form(session, GET_ACTIVITY_PRIZE_URL, API_SIGN_GET_ACTIVITY_PRIZE, base_form)
        debug(f"[getActivityPrize] HTTP={resp.status_code}")
        act_payload = safe_json(resp)
        if DEBUG and act_payload is not None:
            print(dump_json_compact(act_payload))
        lottery_list, act_err = parse_activity_prize(act_payload or {})
        if not lottery_list:
            warn(f"未获取到可用抽奖活动{('：' + act_err) if act_err else ''}")
        else:
            log(f"发现签到页活动 {len(lottery_list)} 个")
            chosen = choose_lottery_act(lottery_list)
            if not chosen:
                warn("未找到可用活动")
            else:
                act_code = chosen.get("actCode")
                remain_times = int(chosen.get("remainingTimes") or 0)
                end_time = chosen.get("endTime") or ""
                log(f"当前活动：{act_code}，剩余次数 {remain_times}，结束时间 {end_time}")

                rules_form = dict(base_form)
                rules_form["timestamp"] = bj_ts_ms()
                rules_form["actCode"] = act_code

                log("查询抽奖机会...")
                resp = post_form(session, GET_LOTTERY_RULES_URL, API_SIGN_GET_LOTTERY_RULES, rules_form)
                debug(f"[getLotteryRules] HTTP={resp.status_code}")
                rules_payload = safe_json(resp)
                if DEBUG and rules_payload is not None:
                    print(dump_json_compact(rules_payload))
                rules, rule_err = parse_rules(rules_payload or {})
                if not rules:
                    warn(f"未获取到抽奖规则{('：' + rule_err) if rule_err else ''}")
                else:
                    day_remain = int(rules.get("currDayRemainCount") or 0)
                    act_remain = int(rules.get("currActRemainCount") or 0)
                    user_remain = int(rules.get("currUserRemainCount") or 0)
                    is_open = int(rules.get("isOpen") or 0)
                    is_valid_act = bool(rules.get("isValidAct"))
                    is_valid_user = bool(rules.get("isValidUser"))
                    log(f"抽奖机会：今日 {day_remain} 次，活动 {act_remain} 次，用户 {user_remain} 次")
                    if is_open and is_valid_act and is_valid_user and DRAW_WHEN_HAS_CHANCE:
                        award_form = dict(rules_form)
                        award_form["timestamp"] = bj_ts_ms()
                        try:
                            log("查询奖池预览...")
                            resp = post_form(session, GET_AWARD_LIST_URL, API_SIGN_GET_AWARD_LIST, award_form)
                            debug(f"[getAwardList] HTTP={resp.status_code}")
                            award_payload = safe_json(resp)
                            if DEBUG and award_payload is not None:
                                print(dump_json_compact(award_payload))
                            reward_list, _ = parse_award_preview(award_payload or {})
                            preview_names = []
                            for item in reward_list[:8]:
                                name = item.get("plateRewardName") or item.get("name")
                                if name and name not in preview_names:
                                    preview_names.append(name)
                            if preview_names:
                                log("奖池预览：" + "、".join(preview_names))
                        except Exception as exc:
                            warn(f"查询奖池预览失败：{exc}")

                        real_remain = min(day_remain, act_remain, user_remain)
                        if real_remain <= 0:
                            warn("当前没有可用抽奖次数")
                        else:
                            draw_times = min(real_remain, MAX_DRAW_TIMES)
                            log(f"开始抽奖，计划执行 {draw_times} 次...")
                            draw_success = 0
                            for i in range(1, draw_times + 1):
                                draw_form = dict(rules_form)
                                draw_form["timestamp"] = bj_ts_ms()
                                try:
                                    resp = post_form(session, LOTTERY_DRAW_URL, API_SIGN_LOTTERY_DRAW, draw_form)
                                    debug(f"[lotteryDraw {i}/{draw_times}] HTTP={resp.status_code}")
                                    draw_payload = safe_json(resp)
                                    if DEBUG and draw_payload is not None:
                                        print(dump_json_compact(draw_payload))
                                    ok, text = parse_draw_result(draw_payload)
                                    if ok:
                                        draw_success += 1
                                        success(f"第 {i}/{draw_times} 次抽奖：{text}")
                                    else:
                                        error(f"第 {i}/{draw_times} 次抽奖：{text}")
                                        break
                                    if i != draw_times:
                                        time.sleep(1.2)
                                except Exception as exc:
                                    error(f"第 {i}/{draw_times} 次抽奖请求异常：{exc}")
                                    break
                            log(f"抽奖结束：成功 {draw_success}/{draw_times} 次")
                    elif not DRAW_WHEN_HAS_CHANCE:
                        warn("当前设置为只查询不抽奖，跳过抽奖")
                    else:
                        warn("当前活动未开放、无资格或没有剩余次数，跳过抽奖")
    except Exception as exc:
        error(f"查询抽奖活动异常：{exc}")

    # 活动报名
    try:
        do_activity_apply(session)
    except Exception as exc:
        error(f"活动报名异常：{exc}")

    # 点赞
    try:
        do_like_task(session)
    except Exception as exc:
        error(f"点赞任务异常：{exc}")

    print(f"## 执行结束... {now_str()}")


if __name__ == "__main__":
    main()
