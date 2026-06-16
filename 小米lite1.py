#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小米米粉节自动化脚本 v3.1 多账号版

功能：
1. 动态获取当前活动任务列表，不再依赖写死 taskId
2. 自动完成可执行的浏览任务
3. 刷新任务状态后自动执行抽奖
4. 支持多账号运行：XIAOMI_COOKIE 一行一个账号

环境变量：
- XIAOMI_COOKIE: 必填，多账号时一行一个完整 Cookie
- XIAOMI_ACTIVITY_URL: 建议填写，当前活动页链接
- XIAOMI_PAGE_ID / XIAOMI_PAGE_SIGN: 可选，不想传完整 URL 时可直接传这两个
- XIAOMI_CLIENT_ID: 可选，默认 180100041089

青龙多账号示例：
XIAOMI_COOKIE="<SENSITIVE>"
"""

import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse, parse_qs

import requests

# ==================== 基础配置 ====================

COOKIE_ENV = os.getenv("XIAOMI_COOKIE", "<SENSITIVE>")
CURRENT_COOKIE = ""
CLIENT_ID = os.getenv("XIAOMI_CLIENT_ID", "<SENSITIVE>")

ACTIVITY_URL = os.getenv(
    "XIAOMI_ACTIVITY_URL",
    "https://m.mi.com/mfbs/dghd/m_universal?_rt=rn&pageid=18610&pdl=mishop&sign=e13789c7433164aaf34b91b1991dfc89"
)
PAGE_ID = os.getenv("XIAOMI_PAGE_ID", "")
PAGE_SIGN = os.getenv("XIAOMI_PAGE_SIGN", "")

BASE_URL_MI = "https://m.mi.com/mtop"
VENUE_PAGE_API = f"{BASE_URL_MI}/navi/venue/page"
VENUE_BATCH_API = f"{BASE_URL_MI}/navi/venue/batch"
INFINITE_DO_API = f"{BASE_URL_MI}/mf/act/infinite/do"
INFINITE_DONE_API = f"{BASE_URL_MI}/mf/act/infinite/done"

HEADERS = {
    "Connection": "keep-alive",
    "content-type": "application/json;charset=utf-8",
    "x-user-agent": "channel/mishop platform/mishop.wxlite",
    "Mishop-Client-Id": CLIENT_ID,
    "charset": "utf-8",
    "Referer": "https://servicewechat.com/wx17ea87763491620f/1866/page-frame.html",
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 9; MI 8 UD Build/PKQ1.180729.001; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/138.0.7204.180 Mobile Safari/537.36 XWEB/1380327 "
        "MMWEBSDK/20241101 MMWEBID/8490 MicroMessenger/8.0.54.2760(0x28003636) "
        "WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android"
    ),
    "Accept-Encoding": "gzip, deflate, br",
}

REQUIRED_COOKIE_KEYS = [
    "client_id", "channel_id", "serviceToken", "nickName", "avatar",
    "lat", "lng", "share_user", "wx_business_user", "share_channel",
    "platform", "model", "brand", "version", "system", "SDKVersion",
    "mishop_wx_version", "masid", "gdt_vid", "weixinadinfo", "user_token",
    "sign_token", "rawData", "signature", "rebate_invite_code", "mstuid", "client_version"
]

# ==================== 工具函数 ====================


def log(msg: str, level: str = "INFO") -> None:
    print(f"[{level}] {msg}")


def random_sleep(min_sec: float = 1, max_sec: float = 2) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def split_accounts(cookie_env: str) -> List[str]:
    """按行分割多账号，一行一个账号"""
    if not cookie_env:
        return []

    lines = cookie_env.replace("\r", "\n").split("\n")
    accounts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        accounts.append(line)
    return accounts


def extract_cookie(cookie_str: str) -> str:
    if not cookie_str:
        return ""

    cookie_str = cookie_str.strip().replace("\n", "").replace("\r", "")
    parts = cookie_str.split(";")
    extracted = []
    ignored = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key = part.split("=", 1)[0].strip()
            if key in REQUIRED_COOKIE_KEYS:
                extracted.append(part)
            else:
                ignored.append(key)
        else:
            extracted.append(part)

    if ignored:
        log(f"忽略自定义变量: {', '.join(ignored[:3])}{'...' if len(ignored) > 3 else ''}")

    return "; ".join(extracted)


def validate_cookie(cookie_str: str) -> Tuple[bool, str]:
    if not cookie_str:
        return False, "Cookie为空"
    required = ["serviceToken", "user_token"]
    missing = [k for k in required if k not in cookie_str]
    if missing:
        return False, f"缺少必要字段: {', '.join(missing)}"
    return True, "OK"


def encode_cookie(cookie_str: str) -> str:
    try:
        cookie_str.encode("latin-1")
        return cookie_str
    except UnicodeEncodeError:
        parts = []
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                try:
                    value.encode("latin-1")
                    parts.append(f"{key}={value}")
                except UnicodeEncodeError:
                    parts.append(f"{key}={quote(value, safe='')}")
            else:
                parts.append(item)
        return "; ".join(parts)


def mask_cookie(cookie_str: str) -> str:
    try:
        for part in cookie_str.split(";"):
            part = part.strip()
            if part.startswith("user_token="):
                value = part.split("=", 1)[1]
                if len(value) >= 12:
                    return value[:6] + "***" + value[-6:]
                return value[:3] + "***"
            if part.startswith("serviceToken="):
                value = part.split("=", 1)[1]
                if len(value) >= 12:
                    return value[:6] + "***" + value[-6:]
                return value[:3] + "***"
    except Exception:
        pass
    return "unknown"


def get_headers(cookie_str: Optional[str] = None) -> Dict[str, str]:
    headers = HEADERS.copy()
    ck = cookie_str or CURRENT_COOKIE
    if ck:
        headers["cookie"] = encode_cookie(ck)
    return headers


def request_json(method: str, url: str, *, params: Optional[Dict[str, Any]] = None,
                 json_data: Optional[Any] = None, timeout: int = 30,
                 cookie_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.request(
            method=method,
            url=url,
            params=params,
            json=json_data,
            headers=get_headers(cookie_str),
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.InvalidHeader:
        log("Cookie格式错误，请重新抓包获取", "ERROR")
        return None
    except requests.exceptions.HTTPError as e:
        log(f"HTTP错误: {e}", "ERROR")
        return None
    except Exception as e:
        log(f"请求失败: {str(e)[:120]}", "ERROR")
        return None


def parse_activity_entry() -> Tuple[str, str]:
    page_id = PAGE_ID.strip()
    sign = PAGE_SIGN.strip()
    if page_id and sign:
        return page_id, sign

    if not ACTIVITY_URL.strip():
        return "", ""

    parsed = urlparse(ACTIVITY_URL)
    qs = parse_qs(parsed.query)
    page_id = qs.get("pageid", [""])[0] or qs.get("page_id", [""])[0]
    sign = qs.get("sign", [""])[0]
    return page_id, sign


# ==================== 动态获取任务 ====================


def fetch_venue_page(page_id: str, sign: str) -> Optional[Dict[str, Any]]:
    params = {"page_id": page_id, "pdl": "mishop", "sign": sign}
    return request_json("GET", VENUE_PAGE_API, params=params)


def fetch_venue_batch(page_id: str, sign: str, query_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    params = {"page_id": page_id, "pdl": "mishop", "sign": sign}
    payload = {"query_list": query_list}
    return request_json("POST", VENUE_BATCH_API, params=params, json_data=payload)


def extract_infinite_query_list(page_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    query_list: List[Dict[str, Any]] = []
    floors = page_data.get("data", {}).get("floors", [])

    for floor in floors:
        for item in floor.get("query_list", []):
            if item.get("resolver") == "infinite-task":
                query_list.append(item)

    dedup = []
    seen = set()
    for item in query_list:
        key = (item.get("resolver"), item.get("sign"), item.get("parameter"))
        if key not in seen:
            seen.add(key)
            dedup.append(item)
    return dedup


def extract_tasks_from_batch(batch_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    tasks = []
    seen = set()
    result_list = batch_data.get("data", {}).get("result_list", [])

    for block in result_list:
        for comp in block.get("components", []):
            task_id = comp.get("taskId")
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            tasks.append(comp)

    return tasks


def dynamic_fetch_tasks() -> Tuple[Optional[str], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    page_id, sign = parse_activity_entry()
    if not page_id or not sign:
        log("缺少活动入口。请设置 XIAOMI_ACTIVITY_URL 或 XIAOMI_PAGE_ID + XIAOMI_PAGE_SIGN", "ERROR")
        return None, [], None

    log(f"活动入口: page_id={page_id}")
    page_data = fetch_venue_page(page_id, sign)
    if not page_data or page_data.get("code") != 0:
        msg = (page_data or {}).get("msg", (page_data or {}).get("message", "获取活动页面失败"))
        log(msg, "ERROR")
        return None, [], None

    query_list = extract_infinite_query_list(page_data)
    if not query_list:
        log("活动页中未找到 infinite-task 查询配置", "ERROR")
        return None, [], None

    log(f"发现 {len(query_list)} 组任务查询")
    batch_data = fetch_venue_batch(page_id, sign, query_list)
    if not batch_data or batch_data.get("code") != 0:
        msg = (batch_data or {}).get("msg", (batch_data or {}).get("message", "批量获取任务失败"))
        log(msg, "ERROR")
        return None, [], None

    tasks = extract_tasks_from_batch(batch_data)
    if not tasks:
        log("未获取到任务列表", "ERROR")
        return None, [], None

    act_id = None
    lottery_task = None
    for task in tasks:
        if not act_id and task.get("actId"):
            act_id = task.get("actId")
        if task.get("taskType") == 128 and not lottery_task:
            lottery_task = task

    return act_id, tasks, lottery_task


# ==================== 任务执行 ====================


def get_task_token(act_id: str, task_id: str) -> Optional[Dict[str, Any]]:
    payload = [{}, {"actId": act_id, "taskId": task_id}]
    return request_json("POST", INFINITE_DO_API, json_data=payload)


def do_task(act_id: str, task_token: str, task_type: int) -> Optional[Dict[str, Any]]:
    payload = [{}, {"actId": act_id, "taskToken": task_token, "taskType": int(task_type)}]
    return request_json("POST", INFINITE_DONE_API, json_data=payload)


def should_run_task(task: Dict[str, Any]) -> bool:
    if task.get("taskType") != 200:
        return False
    if not task.get("canDo", False):
        return False

    status = task.get("status")
    if status not in (1, 2, None):
        return False

    finished = int(task.get("finishedNumber", 0) or 0)
    total = int(task.get("totalNumber", 1) or 1)
    if total > 0 and finished >= total:
        return False

    return True


def process_task(act_id: str, task: Dict[str, Any]) -> str:
    task_id = task.get("taskId", "")
    task_name = task.get("taskName", "未知任务")
    task_type = int(task.get("taskType", 200) or 200)
    duration = int(task.get("duration", 5) or 5)

    log(f"处理: {task_name}")

    token_result = get_task_token(act_id, task_id)
    if not token_result:
        return "failed"

    code = token_result.get("code")
    if code != 0:
        msg = token_result.get("msg", token_result.get("message", "未知错误"))
        if "未登陆" in msg:
            log("  Cookie已失效，请重新抓包获取", "ERROR")
            return "auth_error"
        if "任务已结束" in msg:
            log("  失败: 任务已结束")
            return "expired"
        log(f"  失败: {msg}")
        return "failed"

    task_token = token_result.get("data", {}).get("taskToken", "")
    if not task_token:
        log("  未获取到 taskToken", "ERROR")
        return "failed"

    log(f"  等待 {duration} 秒...")
    time.sleep(duration)

    done_result = do_task(act_id, task_token, task_type)
    if not done_result:
        return "failed"

    code = done_result.get("code")
    if code == 0:
        award_list = done_result.get("data", {}).get("awardList", [])
        if award_list:
            awards = [a.get("awardName", "未知") for a in award_list]
            log(f"  完成! 获得: {', '.join(awards)}")
        else:
            log("  完成!")
        return "completed"

    if code == 200001:
        log("  已完成（达到上限）")
        return "already_done"

    msg = done_result.get("msg", done_result.get("message", "未知错误"))
    if "任务已结束" in msg:
        log("  失败: 任务已结束")
        return "expired"
    log(f"  失败: {msg}")
    return "failed"


def process_all_tasks(act_id: str, tasks: List[Dict[str, Any]]) -> bool:
    browse_tasks = [t for t in tasks if should_run_task(t)]

    log("=" * 40)
    log("开始执行浏览任务")
    log("=" * 40)
    log(f"动态获取到 {len(tasks)} 个任务，可执行浏览任务 {len(browse_tasks)} 个")
    log("-" * 40)

    if not browse_tasks:
        log("没有可执行的浏览任务")
        return True

    stats = {
        "completed": 0,
        "already_done": 0,
        "expired": 0,
        "failed": 0,
        "auth_error": 0,
    }

    for task in browse_tasks:
        result = process_task(act_id, task)
        stats[result] = stats.get(result, 0) + 1
        if result == "auth_error":
            log("账号 Cookie 失效，中止当前账号", "WARN")
            break
        random_sleep(1, 2)

    log("-" * 40)
    log(
        "任务统计: "
        f"完成={stats.get('completed', 0)} "
        f"已完成={stats.get('already_done', 0)} "
        f"过期={stats.get('expired', 0)} "
        f"失败={stats.get('failed', 0)}"
    )

    return stats.get("auth_error", 0) == 0


def refresh_lottery_task() -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    act_id, tasks, lottery_task = dynamic_fetch_tasks()
    _ = tasks
    return act_id, lottery_task


def parse_draw_result_text(result: Dict[str, Any]) -> str:
    """尽量从返回里提取抽奖结果文案"""
    data = result.get("data", {}) or {}
    for key in ["toast", "toastMsg", "resultDesc", "awardDesc", "desc", "message", "msg"]:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ["msg", "message"]:
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def do_draw(act_id: str, lottery_task_id: str) -> Optional[Dict[str, Any]]:
    token_result = get_task_token(act_id, lottery_task_id)
    if not token_result or token_result.get("code") != 0:
        msg = (token_result or {}).get("msg", (token_result or {}).get("message", "获取抽奖token失败"))
        log(f"获取抽奖token失败: {msg}", "ERROR")
        return None

    task_token = token_result.get("data", {}).get("taskToken", "")
    if not task_token:
        log("未获取到抽奖 taskToken", "ERROR")
        return None

    result = do_task(act_id, task_token, 128)
    if not result:
        return None

    code = result.get("code")
    if code == 0:
        award_list = result.get("data", {}).get("awardList", []) or []
        if award_list:
            awards = []
            for a in award_list:
                name = a.get("awardName") or a.get("name") or "未知奖品"
                value = a.get("awardValue") or a.get("value") or 1
                awards.append(f"{name}x{value}")
            log(f"抽奖结果: {', '.join(awards)}")
        else:
            result_text = parse_draw_result_text(result)
            if any(x in result_text for x in ["谢谢", "未中奖", "再接再厉", "空气", "未抽中"]):
                log(f"抽奖结果: {result_text}")
            elif result_text:
                log(f"抽奖结果: 未拿到奖品字段，接口提示：{result_text}")
            else:
                log("抽奖结果: 未中奖")
        return result

    if code == 200002:
        log("抽奖次数已用完")
        return result

    msg = result.get("msg", result.get("message", "未知错误"))
    log(f"抽奖失败: {msg}")
    return result


def do_all_draws() -> None:
    log("-" * 40)
    log("刷新任务状态，准备抽奖")
    log("-" * 40)

    act_id, lottery_task = refresh_lottery_task()
    if not act_id or not lottery_task:
        log("未找到抽奖任务", "WARN")
        return

    rest_scores = int(lottery_task.get("scores", 0) or 0)
    single_cost = int(lottery_task.get("singleCostScores", 1) or 1)
    finished = int(lottery_task.get("finishedNumber", 0) or 0)
    upper_limit = int(lottery_task.get("upperLimit", 0) or 0)

    by_score = rest_scores // max(single_cost, 1)
    by_limit = max(upper_limit - finished, 0) if upper_limit else by_score
    draw_times = min(by_score, by_limit) if by_limit else by_score

    log(
        f"当前抽奖任务: {lottery_task.get('taskName', '未知')} | "
        f"剩余积分={rest_scores} 单次消耗={single_cost} 可抽={draw_times}"
    )

    if draw_times <= 0:
        log("暂无可用抽奖次数")
        return

    success_count = 0
    for _ in range(draw_times):
        result = do_draw(act_id, lottery_task["taskId"])
        if not result:
            break
        if result.get("code") == 0:
            success_count += 1
        elif result.get("code") == 200002:
            break
        random_sleep(1, 2)

    log(f"抽奖完成，共成功 {success_count} 次")


# ==================== 多账号执行 ====================


def run_one_account(cookie_str: str, index: int, total: int) -> None:
    global CURRENT_COOKIE

    log("")
    log("=" * 48)
    log(f"开始账号 {index}/{total}")
    log(f"账号标识: {mask_cookie(cookie_str)}")
    log("=" * 48)

    CURRENT_COOKIE = extract_cookie(cookie_str)
    valid, msg = validate_cookie(CURRENT_COOKIE)
    if not valid:
        log(f"账号{index} Cookie验证失败: {msg}", "ERROR")
        return

    act_id, tasks, lottery_task = dynamic_fetch_tasks()
    if not act_id or not tasks:
        log(f"账号{index} 获取任务失败，跳过", "WARN")
        return

    log(f"当前 actId: {act_id}")
    if lottery_task:
        log(f"抽奖任务ID: {lottery_task.get('taskId')}")

    ok = process_all_tasks(act_id, tasks)
    if ok:
        log("")
        do_all_draws()

    log(f"账号{index} 执行完毕")


# ==================== 主程序 ====================


def run() -> None:
    log("=" * 48)
    log("小米米粉节自动化脚本 v3.1 多账号版")
    log("=" * 48)

    if not COOKIE_ENV:
        log("错误: 请配置环境变量 XIAOMI_COOKIE", "ERROR")
        log("多账号格式：一行一个账号 Cookie")
        log('示例: export XIAOMI_COOKIE="<SENSITIVE>"')
        return

    accounts = split_accounts(COOKIE_ENV)
    if not accounts:
        log("未读取到有效账号", "ERROR")
        return

    log(f"共检测到 {len(accounts)} 个账号")

    for idx, account_cookie in enumerate(accounts, 1):
        try:
            run_one_account(account_cookie, idx, len(accounts))
        except KeyboardInterrupt:
            log("用户中断执行", "WARN")
            break
        except Exception as e:
            log(f"账号{idx} 执行异常: {str(e)[:200]}", "ERROR")

        if idx < len(accounts):
            log("切换下一个账号...")
            time.sleep(2)

    log("")
    log("=" * 48)
    log("全部账号执行完毕!")
    log("=" * 48)


if __name__ == "__main__":
    run()
