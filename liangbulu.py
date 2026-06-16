#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2bulu helper script (robust)

Fixes vs original:
- finishTask 的 taskId / uid 自动从 signIn 响应里取（优先），避免“第一步看起来成功但任务没真正完成”
- finishTask 自动补齐 uid 参数（如果 signIn 返回）
- finishTask 的 psign 支持按 taskId 自动选默认值（可用环境变量覆盖）
- 对常见失败场景增加重试/更清晰的日志（HTTP / errCode / errMsg）

⚠️ 说明：
- psign 可能会随版本/参数变化而失效；如仍失败，请用最新抓包值覆盖对应环境变量（如 BULU_DAILYREAD_*_PSIGN / BULU_FINISH_PSIGN）。
"""

import os
import sys
import time
import random
import traceback
import json
import re
import urllib.parse
from typing import Any, Dict, Optional, Tuple
import requests


DEBUG = 0  # 0=简洁日志，1=详细调试日志（仅作用于本脚本）


def _now_str() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


def _emit(msg: str) -> None:
    print(f"[{_now_str()}] {msg}", flush=True)


def section(title: str) -> None:
    _emit(title)


def info(msg: str) -> None:
    _emit(msg)


def success(msg: str) -> None:
    _emit(f"✅ {msg}")


def warn(msg: str) -> None:
    _emit(f"⚠️ {msg}")


def _should_print(msg: str) -> bool:
    if DEBUG:
        return True

    msg = str(msg)

    always_prefixes = (
        "STEP0 dailyRead:",
        "STEP1 signIn",
        "STEP2 finishTask",
        "STEP2.5 videoTask",
        "STEP3 ",
        "TASK LIST",
        "ALL DONE",
        "EXCEPTION:",
    )
    if msg.startswith(always_prefixes):
        return True

    always_contains = (
        "disabled by BULU_ENABLE_DAILY_READ=0",
        "dailyRead task status:",
        "dailyRead reward claimed",
        "dailyRead reward not claimed",
        "dailyRead task not found",
        "dailyRead done",
        "videoTask initial status:",
        "videoTask progress after #",
        "videoTask summary:",
        "videoTask: today already finished, skip",
        "videoTask: reached today's limit",
        "signIn OK",
        "signIn 已完成/重复",
        "signIn failed:",
        "finishTask OK",
        "finishTask 已完成/重复",
        "finishTask failed:",
        "queryTasks failed:",
        "pre-check exception",
        "post-signin check exception",
        "final sign check exception",
        "final queryTasks exception",
        "dailyRead exception",
        "videoTask exception",
    )
    if any(x in msg for x in always_contains):
        return True

    if msg.startswith("- taskId="):
        m = re.search(r"taskId=(\d+)", msg)
        return bool(m and m.group(1) in {"2", "15", "17"})

    quiet_prefixes = (
        "queryTasks status=",
        "queryTasks resp:",
        "welfare(",
        "signInfoList(",
        "updateClickViewNum[",
        "queryTravelArticle[",
        "queryCommunityComment[",
        "addViewActivity[",
        "getFreeAdDuration[",
        "finishTask(taskId=17) status=",
        "finishTask(taskId=17) resp:",
        "finishTask status=",
        "finishTask resp:",
        "signIn status=",
        "signIn resp:",
        "signIn URL:",
        "status=",
        "resp:",
        "sleep ",
        "videoTask gap sleep",
        "fetched article ids via webapi:",
        "scraped article ids from web:",
        "built dynamic READ_ARTICLES from live list",
        "dailyRead[",
    )
    if msg.startswith(quiet_prefixes):
        return False

    quiet_contains = (
        "resolved viewId=",
        "simulate rewarded video wait",
        "本次实际成功记账",
        "接口返回成功",
        "诊断建议：",
    )
    if any(x in msg for x in quiet_contains):
        return False

    return True


def log(msg: str):
    if _should_print(msg):
        print(f"[调试 {_now_str()}] {msg}", flush=True)


def debug_log(msg: str):
    if DEBUG:
        print(f"[调试 {_now_str()}] {msg}", flush=True)


def truncate(s: str, n: int = 500) -> str:
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= n else s[:n] + f"...(truncated, len={len(s)})"


def safe_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def build_session() -> requests.Session:
    s = requests.Session()

    ua = os.getenv(
        "BULU_UA",
        "region:CN;lan:zh-Hans;OutdoorAssistantApplication/8.1.5 "
        "(lolaage.2bulu.zhushou; build:8.1.5.1; iOS 26.3.1) Alamofire/5.9.1",
    )

    headers = {
        "Encrypt-Type": os.getenv("BULU_ENCRYPT_TYPE", "1"),
        "User-Agent": ua,
        "Accept": os.getenv("BULU_ACCEPT", "*/*"),
        "Accept-Language": os.getenv("BULU_ACCEPT_LANGUAGE", "zh-Hans;q=1.0, zh-Hans-CN;q=0.9"),
        "Accept-Encoding": os.getenv("BULU_ACCEPT_ENCODING", "br;q=1.0, gzip;q=0.9, deflate;q=0.8"),
        "Connection": "keep-alive",
        "Host": "helper.2bulu.com",
    }

    origin = os.getenv("BULU_ORIGIN", "")
    referer = os.getenv("BULU_REFERER", "")
    if origin:
        headers["Origin"] = origin
    if referer:
        headers["Referer"] = referer

    cookie = os.getenv("BULU_COOKIE", "<SENSITIVE>").strip()
    if cookie:
        headers["Cookie"] = cookie

    token = os.getenv("BULU_TOKEN", "<SENSITIVE>").strip()
    if token:
        headers["token"] = token

    authorization = os.getenv("BULU_AUTHORIZATION", "<SENSITIVE>").strip()
    if authorization:
        headers["Authorization"] = authorization

    s.headers.update(headers)

    proxy = os.getenv("BULU_PROXY", "")
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})

    return s


def build_url(base: str, params: Dict[str, Any]) -> str:
    q = []
    for k, v in params.items():
        if v is None:
            continue
        v = str(v)
        if re.search(r"%[0-9A-Fa-f]{2}", v):
            enc_v = v
        else:
            enc_v = requests.utils.quote(v, safe="")
        q.append(f"{k}={enc_v}")
    return base + ("?" + "&".join(q) if q else "")


def fetch_article_ids_via_webapi(max_ids: int = 10) -> list:
    api = "https://www.2bulu.com/api/communityArticle/queryList"
    params = {
        "type": "1",
        "queryName": urllib.parse.quote("全部"),
        "queryType": "5",
        "cityName": urllib.parse.quote("驴友大厅"),
        "orderType": "",
        "isjinghua": "0",
        "currPageIndex": "1",
        "pageSize": str(max(1, min(50, int(max_ids)))),
        "moduleCategorysId": "undefined",
        "moduleId": "undefined",
        "isHomeRecommend": "1",
    }
    url = api + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
    headers = {
        "User-Agent": os.getenv("BULU_WEB_UA", "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) -2buluOI-8.1.5"),
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.2bulu.com/mc/community/home",
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        j = safe_json(r.text)
        ids = []
        for it in ((j or {}).get("data", {}) or {}).get("list", []) or []:
            _id = it.get("id")
            if isinstance(_id, int):
                ids.append(_id)
            elif isinstance(_id, str) and _id.isdigit():
                ids.append(int(_id))
        seen = set()
        out = []
        for x in ids:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out[:max_ids]
    except Exception as e:
        log(f"fetch_article_ids_via_webapi exception: {e}")
        return []


def fetch_target_ids_from_web(max_ids: int = 10) -> list:
    candidates = [
        "https://www.2bulu.com/community/index.htm",
        "https://www.2bulu.com/",
        "https://app.2bulu.com/community/index.htm",
        "https://app.2bulu.com/",
    ]
    headers = {
        "User-Agent": os.getenv("BULU_WEB_UA", "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) -2buluOI-8.1.5"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Connection": "keep-alive",
    }

    ids = []
    seen = set()
    pat = re.compile(r"gotohuatinfo\.htm\?id=([0-9]{6,})")
    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code != 200:
                continue
            for m in pat.finditer(r.text):
                tid = m.group(1)
                if tid not in seen:
                    seen.add(tid)
                    ids.append(int(tid))
                    if len(ids) >= max_ids:
                        return ids
        except Exception:
            continue
    return ids


READ_ARTICLES = [
    {'targetId': 76002878, 'viewId': '3a134aa359584f5c97847d3299436660', 'psign': 'a1680d1ef68e0c0fcccae0e7a2e8521c', 'updateClickViewNum_psign': '<PHONE>a59ed6f6aa68226e3dd46', 'queryTravelArticle_psign': '4d42524fe4f322a65e7daa7cc47ab933', 'queryCommunityComment_psign': '910e373ac908933106089a79e3327f64'},
    {'targetId': 76011935, 'viewId': '4358a0c5c9fa42d29c9c8ce60b5f0e6e', 'psign': 'd64b34edd0502fc005974f271b5d115d', 'updateClickViewNum_psign': '4ed7078e7e564ba32be86b59321d64e0', 'queryTravelArticle_psign': 'c4b707b92cdb76e67946fef92f37718a', 'queryCommunityComment_psign': '77afa8fef438672bbd6b06aee8294043'},
    {'targetId': 76012924, 'viewId': 'bfe83cff595b42bebf2340342bcbcdc3', 'psign': '0d0569905a71fc4499140cd84d3fa4b3', 'updateClickViewNum_psign': 'a8fd70e171b9c2d1c3f91216928e3c71', 'queryTravelArticle_psign': '857c40119841cab238ded753a2d162cc', 'queryCommunityComment_psign': 'c8bda309982c07b5c6dae44d896b95a0'},
    {'targetId': 76012943, 'viewId': '4993127d91a94ae79f9a5dbf090c81de', 'psign': 'e8072c5b9706aa20542f177587d59e2b', 'updateClickViewNum_psign': '545999471b9c8411ae1229113d7d2d78', 'queryTravelArticle_psign': '12ab5dded9cc20111d1d94b409699d16', 'queryCommunityComment_psign': '983875b4c18f681f1196e2ae280d40f4'},
    {'targetId': 76012873, 'viewId': 'aa7ecf80207a42518874fa81f866b467', 'psign': '3b865f84d8802d8a3d0d8cd507191f34', 'updateClickViewNum_psign': '46a0d248c883ebcd04a8e6405c1df50e', 'queryTravelArticle_psign': 'f27906b33ac5a7953fddcc06407ff4a0', 'queryCommunityComment_psign': '696798624b80ad0ee6072d991c241bdd'},
]


def load_read_articles() -> list:
    raw = (os.getenv("BULU_READ_ARTICLES_JSON", "") or os.getenv("BULU_READ_ARTICLES", "")).strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                log(f"loaded READ_ARTICLES from env JSON (count={len(data)})")
                return data
        except Exception as e:
            log(f"invalid BULU_READ_ARTICLES_JSON: {e}")

    cache = {int(a.get("targetId")): a for a in READ_ARTICLES if isinstance(a, dict) and a.get("targetId")}

    ids_raw = (os.getenv("BULU_ARTICLE_IDS", "") or os.getenv("BULU_READ_TARGET_IDS", "")).strip()
    ids: list[int] = []
    if ids_raw:
        for part in re.split(r"[ ,;]+", ids_raw):
            part = part.strip()
            if not part:
                continue
            if part.isdigit():
                ids.append(int(part))
        ids = [x for i, x in enumerate(ids) if x not in ids[:i]]

    if not ids:
        ids = fetch_article_ids_via_webapi(max_ids=10)
        if ids:
            log(f"fetched article ids via webapi: {ids[:10]}")

    if not ids:
        ids = fetch_target_ids_from_web(max_ids=10)
        if ids:
            log(f"scraped article ids from web: {ids[:10]}")

    if os.getenv("BULU_DAILYREAD_DYNAMIC", "1").strip() not in ("0", "false", "False"):
        need = int(os.getenv("BULU_DAILYREAD_COUNT", "5") or "5")
        uc_psign = os.getenv("BULU_DAILYREAD_UCVN_PSIGN", "add3016e33ec580da9f628371ae37a0f").strip()
        qa_psign = os.getenv("BULU_DAILYREAD_QTA_PSIGN", "3f6af5c4497ba272680ab7d3c241378d").strip()
        qc_psign = os.getenv("BULU_DAILYREAD_QCC_PSIGN", "61717d23a56fb67cb1375dc6e56b6cb7").strip()
        ava_psign = os.getenv("BULU_DAILYREAD_AVA_PSIGN", "932298d78674d6e210973f0d8f8aff8b").strip()
        out = []
        for tid in ids[:max(1, need)]:
            out.append({
                "targetId": int(tid),
                "updateClickViewNum_psign": uc_psign,
                "queryTravelArticle_psign": qa_psign,
                "queryCommunityComment_psign": qc_psign,
                "psign": ava_psign,
            })
        if out:
            log(f"built dynamic READ_ARTICLES from live list (count={len(out)})")
            return out

    out = []
    for tid in ids:
        a = cache.get(int(tid))
        if a:
            out.append(a)
        else:
            out.append({"targetId": int(tid)})

    if not out:
        log("WARNING: no ids found from web/env, fallback to built-in READ_ARTICLES (may be stale)")
        return READ_ARTICLES

    need = int(os.getenv("BULU_DAILYREAD_COUNT", "5") or "5")
    return out[:max(1, need)]


def request_get(session: requests.Session, url: str, timeout: float = 20.0) -> Tuple[requests.Response, float]:
    t0 = time.time()
    r = session.get(url, timeout=timeout)
    dt = (time.time() - t0) * 1000
    return r, dt


def get_err(j: Any) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(j, dict):
        return None, None
    err_code = j.get("errCode")
    err_msg = j.get("errMsg") or j.get("msg") or j.get("message")
    return None if err_code is None else str(err_code), None if err_msg is None else str(err_msg)


def request_with_retry(session: requests.Session, url: str, name: str, retries: int = 2) -> Tuple[requests.Response, float, Any]:
    last_exc = None
    for i in range(retries + 1):
        try:
            r, dt = request_get(session, url)
            j = safe_json(r.text)
            if r.status_code >= 500 and i < retries:
                log(f"{name} HTTP {r.status_code}, retry {i+1}/{retries}...")
                time.sleep(1.0 + i)
                continue
            return r, dt, j
        except Exception as e:
            last_exc = e
            if i < retries:
                log(f"{name} exception, retry {i+1}/{retries}: {e}")
                time.sleep(1.0 + i)
                continue
            raise
    raise last_exc


def query_tasks(session: requests.Session, *, auth_code: str, auth_type: str, device_name: str,
               app_ver: str, product_type: str, terminal_type: str, user_id: str, p_user_id: str,
               sdk_level: str, psign: str) -> Any:
    url = build_url(
        "https://helper.2bulu.com/greenPea/queryTasks",
        {
            "authCode": auth_code,
            "authType": auth_type,
            "deviceName": device_name,
            "p_appVersion": app_ver,
            "p_productType": product_type,
            "p_terminalType": terminal_type,
            "p_userId": p_user_id,
            "sdkLevel": sdk_level,
            "userId": user_id,
            "psign": psign,
        },
    )
    r, dt, j = request_with_retry(session, url, name="queryTasks", retries=1)
    log(f"queryTasks status={r.status_code} time_ms={dt:.0f}")
    log(f"queryTasks resp: {truncate(r.text)}")
    return j


def query_simple(session: requests.Session, name: str, base: str, params: Dict[str, Any]) -> Any:
    url = build_url(base, params)
    r, dt, j = request_with_retry(session, url, name=name, retries=1)
    log(f"{name} status={r.status_code} time_ms={dt:.0f}")
    log(f"{name} resp: {truncate(r.text)}")
    return j


def _extract_task_list(j: object) -> list:
    if not isinstance(j, dict):
        return []
    tasks = j.get("tasks")
    if isinstance(tasks, list):
        return tasks
    data = j.get("data")
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        return data.get("tasks")
    return []


def print_task_list(j: object, *, header: str = "TASK LIST") -> None:
    tasks = _extract_task_list(j)
    if DEBUG:
        log(f"{header}: count={len(tasks)}")
    else:
        info("当前任务概览：")
    if not tasks:
        warn("未获取到任务列表")
        return
    key_ids = {2, 15, 17}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        task_id = t.get("taskId")
        title = t.get("title") or t.get("name") or ""
        state = t.get("state")
        curr = t.get("currNum")
        up = t.get("upNum")
        reward = t.get("rewardNum") or t.get("reward")
        if DEBUG:
            log(f"- taskId={task_id} state={state} progress={curr}/{up} reward={reward} title={title}")
        else:
            if task_id in key_ids:
                status = "已完成" if str(state) == "2" else "进行中"
                info(f"  - {title}: {curr}/{up}，状态：{status}")


def find_task(j: object, task_id: int = None, title_keyword: str = None) -> Optional[Dict[str, Any]]:
    tasks = _extract_task_list(j)
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if task_id is not None and str(t.get("taskId")) == str(task_id):
            return t
        if title_keyword and isinstance(t.get("title"), str) and title_keyword in t.get("title"):
            return t
    return None


def is_already_done(err_msg: Optional[str]) -> bool:
    if not err_msg:
        return False
    keywords = ["已经领取", "已领取", "已完成", "已签到", "今日已", "重复", "already"]
    return any(k in err_msg for k in keywords)


def get_finish_psign(task_id: str) -> str:
    env = os.getenv("BULU_FINISH_PSIGN", "").strip()
    if env:
        return env
    if str(task_id) == "16":
        return "62cc1cb9f2883ef55ec093dccab28e06"
    if str(task_id) == "17":
        return os.getenv("BULU_FINISH_PSIGN_17", "1ca7c68dd61e92e5875d681b9d1b81c4").strip()
    if str(task_id) == "15":
        return "24cb42eccc2a0e9db97a1b80c93f7d2c"
    return os.getenv("BULU_FINISH_PSIGN_FALLBACK", "6f72fb54b44abd017e85f46f4fccaa32").strip()


def claim_task(session: requests.Session, *, auth_code: str, auth_type: str, device_name: str,
               app_ver: str, product_type: str, terminal_type: str, user_id: str, p_user_id: str,
               sdk_level: str, task_id: str, uid: Optional[str] = None) -> Tuple[bool, Any]:
    psign = get_finish_psign(task_id)
    params = {
        "authCode": auth_code,
        "authType": auth_type,
        "deviceName": device_name,
        "p_appVersion": app_ver,
        "p_productType": product_type,
        "p_terminalType": terminal_type,
        "p_userId": p_user_id,
        "sdkLevel": sdk_level,
        "taskId": task_id,
        "userId": user_id,
        "psign": psign,
    }
    if uid:
        params["uid"] = uid
    url = build_url("https://helper.2bulu.com/greenPea/finishTask", params)
    r, dt, j = request_with_retry(session, url, name="finishTask", retries=1)
    log(f"finishTask(taskId={task_id}) status={r.status_code} time_ms={dt:.0f}")
    log(f"finishTask(taskId={task_id}) resp: {truncate(r.text)}")
    err_code, err_msg = get_err(j)
    if not err_code or err_code == "0" or is_already_done(err_msg):
        return True, j
    return False, j


def do_daily_read(session: requests.Session, auth_code: str, auth_type: str, device_name: str,
                  app_version: str, product_type: str, terminal_type: str, user_id: str, sdk_level: str,
                  per_article_seconds: int = 11) -> None:
    enabled = os.getenv("BULU_ENABLE_DAILY_READ", "1").strip() not in ("0", "false", "False")
    if not enabled:
        info("已关闭每日阅读功能")
        return

    def _call_and_log(label: str, url: str, retries: int = 1):
        r, dt, j = request_with_retry(session, url, name=label, retries=retries)
        err = None
        if isinstance(j, dict):
            err = j.get("errCode")
        log(f"{label} status={r.status_code} time_ms={int(dt)} errCode={err} url={url}")
        return j

    before_tasks = query_tasks(
        session,
        auth_code=auth_code,
        auth_type=auth_type,
        device_name=device_name,
        app_ver=app_version,
        product_type=product_type,
        terminal_type=terminal_type,
        user_id=user_id,
        p_user_id=user_id,
        sdk_level=sdk_level,
        psign=os.getenv("BULU_QUERYTASKS_PSIGN", ""),
    )
    before_curr = None
    before_up = None
    before_state = None
    try:
        for t in (before_tasks or {}).get("tasks", []):
            if t.get("taskId") == 15 or t.get("title") == "每日阅读":
                before_curr = t.get("currNum")
                before_up = t.get("upNum")
                before_state = t.get("state")
                break
    except Exception:
        pass

    section("开始执行：每日阅读任务")
    info(f"当前阅读进度：{before_curr}/{before_up}，任务状态：{before_state}")
    if (isinstance(before_curr, int) and isinstance(before_up, int) and before_up > 0 and before_curr >= before_up) or str(before_state) == "2":
        success("每日阅读已完成，跳过阅读流程")
        return

    articles = load_read_articles()
    info(f"准备随机阅读 {len(articles)} 篇文章，每篇停留 {per_article_seconds} 秒")

    web_headers = {
        "User-Agent": os.getenv("BULU_WEB_UA", "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) -2buluOI-8.1.5"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Connection": "keep-alive",
    }

    for idx, a in enumerate(articles, start=1):
        tid = int(a["targetId"])
        view_id = (a.get("viewId") or "").strip() if isinstance(a.get("viewId"), str) else a.get("viewId")
        psign = (a.get("psign") or "").strip()

        article_url = f"https://www.2bulu.com/community/gotohuatinfo.htm?id={tid}"
        info(f"阅读第 {idx}/{len(articles)} 篇文章（ID: {tid}）")
        log(f"dailyRead[{idx}/{len(articles)}] open article {tid}")
        try:
            r = requests.get(article_url, headers=web_headers, timeout=20, allow_redirects=True)
            log(f"dailyRead[{idx}/{len(articles)}] web status={r.status_code}")
        except Exception as e:
            log(f"dailyRead[{idx}/{len(articles)}] open article exception: {e}")

        uc_psign = (a.get("updateClickViewNum_psign") or os.getenv("BULU_DAILYREAD_UCVN_PSIGN", "")).strip()
        qa_psign = (a.get("queryTravelArticle_psign") or os.getenv("BULU_DAILYREAD_QTA_PSIGN", "")).strip()
        qc_psign = (a.get("queryCommunityComment_psign") or os.getenv("BULU_DAILYREAD_QCC_PSIGN", "")).strip()

        if not (uc_psign and qa_psign and qc_psign):
            log(
                f"dailyRead[{idx}/{len(articles)}] WARNING: 缺少前置接口 psign："
                f"updateClickViewNum_psign={bool(uc_psign)} "
                f"queryTravelArticle_psign={bool(qa_psign)} "
                f"queryCommunityComment_psign={bool(qc_psign)} "
                f"（缺少时可能不计入每日阅读）"
            )

        if uc_psign:
            u1 = build_url(
                "https://helper.2bulu.com/communityArticle/updateClickViewNum",
                {
                    "authCode": auth_code,
                    "authType": auth_type,
                    "deviceName": device_name,
                    "id": tid,
                    "p_appVersion": app_version,
                    "p_productType": product_type,
                    "p_terminalType": terminal_type,
                    "p_userId": user_id,
                    "sdkLevel": sdk_level,
                    "userId": user_id,
                    "psign": uc_psign,
                },
            )
            _call_and_log(f"updateClickViewNum[{idx}]", u1, retries=1)

        j2 = None
        if qa_psign:
            u2 = build_url(
                "https://helper.2bulu.com/article/queryTravelArticle",
                {
                    "articleId": tid,
                    "authCode": auth_code,
                    "authType": auth_type,
                    "deviceName": device_name,
                    "p_appVersion": app_version,
                    "p_productType": product_type,
                    "p_terminalType": terminal_type,
                    "p_userId": user_id,
                    "sdkLevel": sdk_level,
                    "userId": user_id,
                    "psign": qa_psign,
                },
            )
            j2 = _call_and_log(f"queryTravelArticle[{idx}]", u2, retries=1)

            if not view_id and isinstance(j2, dict):
                try:
                    travel = j2.get("travelArticleInfo") or {}
                    view_id = (
                        travel.get("viewId")
                        or ((travel.get("baseInfo") or {}).get("viewId"))
                        or ""
                    )
                    view_id = str(view_id).strip()
                    if view_id:
                        log(f"dailyRead[{idx}/{len(articles)}] resolved viewId={view_id}")
                except Exception:
                    pass

        if qc_psign:
            u3 = build_url(
                "https://helper.2bulu.com/communityArticle/queryCommunityComment",
                {
                    "authCode": auth_code,
                    "authType": auth_type,
                    "currPageIndex": 1,
                    "deviceName": device_name,
                    "id": tid,
                    "lookSelf": 0,
                    "orderType": 0,
                    "p_appVersion": app_version,
                    "p_productType": product_type,
                    "p_terminalType": terminal_type,
                    "p_userId": user_id,
                    "pageSize": 20,
                    "sdkLevel": sdk_level,
                    "userId": user_id,
                    "psign": qc_psign,
                },
            )
            _call_and_log(f"queryCommunityComment[{idx}]", u3, retries=1)

        try:
            time.sleep(max(1, int(per_article_seconds)))
        except Exception:
            pass

        if not view_id:
            log(
                f"dailyRead[{idx}/{len(articles)}] SKIP: 无法获取 viewId（targetId={tid}）。"
                f" 建议检查 queryTravelArticle 是否返回 viewId，或改用抓包参数覆盖。"
            )
            continue

        if not psign:
            psign = os.getenv("BULU_DAILYREAD_AVA_PSIGN", "932298d78674d6e210973f0d8f8aff8b").strip() or os.getenv("BULU_ADDVIEWACTIVITY_PSIGN", "").strip()

        if not psign:
            log(
                f"dailyRead[{idx}/{len(articles)}] SKIP: 缺少 addViewActivity psign（targetId={tid}, viewId={view_id}）。"
                f" 请设置 BULU_DAILYREAD_AVA_PSIGN 或在 BULU_READ_ARTICLES_JSON 里提供。"
            )
            continue

        u4 = build_url(
            "https://helper.2bulu.com/activity/addViewActivity",
            {
                "authCode": auth_code,
                "authType": auth_type,
                "deviceName": device_name,
                "p_appVersion": app_version,
                "p_productType": product_type,
                "p_terminalType": terminal_type,
                "p_userId": user_id,
                "sdkLevel": sdk_level,
                "targetId": tid,
                "targetType": 2,
                "userId": user_id,
                "viewId": view_id,
                "psign": psign,
            },
        )
        j4 = _call_and_log(f"addViewActivity[{idx}]", u4, retries=1)
        err4, msg4 = get_err(j4)
        if not err4 or err4 == "0":
            success(f"第 {idx} 篇阅读上报成功")
        else:
            warn(f"第 {idx} 篇阅读上报失败：{msg4 or err4}")

    after_tasks = query_tasks(
        session,
        auth_code=auth_code,
        auth_type=auth_type,
        device_name=device_name,
        app_ver=app_version,
        product_type=product_type,
        terminal_type=terminal_type,
        user_id=user_id,
        p_user_id=user_id,
        sdk_level=sdk_level,
        psign=os.getenv("BULU_QUERYTASKS_PSIGN", ""),
    )
    after_curr = None
    after_up = None
    try:
        for t in (after_tasks or {}).get("tasks", []):
            if t.get("taskId") == 15 or t.get("title") == "每日阅读":
                after_curr = t.get("currNum")
                after_up = t.get("upNum")
                break
    except Exception:
        pass

    info(f"阅读任务结果：{after_curr}/{after_up}")
    if isinstance(after_curr, int) and isinstance(after_up, int) and after_curr >= after_up:
        success("每日阅读任务已完成")
    else:
        warn("每日阅读任务未完成")
    log(f"STEP0 dailyRead done (dailyRead currNum={after_curr}/{after_up})")

    if before_curr is not None and after_curr is not None and str(before_curr) == str(after_curr):
        log("诊断：dailyRead currNum 未变化。若 addViewActivity 仍返回 errCode=0，通常是 viewId/psign 已被复用或已失效（需要抓取新的 viewId/psign 组合）。")


def perform_video_task(session: requests.Session, *, auth_code: str, auth_type: str, device_name: str,
                       app_ver: str, product_type: str, terminal_type: str, user_id: str, p_user_id: str,
                       sdk_level: str, max_times: int = 3) -> None:
    if max_times <= 0:
        info("视频任务已关闭")
        return

    query_psign = os.getenv("BULU_QUERYTASKS_PSIGN", "8530ad747ed4efb06d3965d58630f376").strip()
    wait_seconds = int(os.getenv("BULU_VIDEO_WAIT_SECONDS", "22"))

    section("开始执行：视频任务")
    info(f"本次最多尝试 {max_times} 次视频任务")
    jt = query_tasks(
        session,
        auth_code=auth_code, auth_type=auth_type, device_name=device_name,
        app_ver=app_ver, product_type=product_type, terminal_type=terminal_type,
        user_id=user_id, p_user_id=p_user_id, sdk_level=sdk_level, psign=query_psign,
    )
    video_task = find_task(jt, task_id=17, title_keyword="看视频")
    if not video_task:
        log("videoTask: queryTasks 未找到 taskId=17 / 看视频赚绿豆")
        return

    start_curr = int(video_task.get("currNum") or 0)
    curr = start_curr
    up = int(video_task.get("upNum") or max_times)
    state = str(video_task.get("state"))
    info(f"当前视频进度：{curr}/{up}，任务状态：{state}")

    target_runs = min(max_times, max(0, up - curr))
    if target_runs <= 0 or state == "2":
        success("视频任务今日已完成，跳过")
        return

    base_params = {
        "authCode": auth_code,
        "authType": auth_type,
        "deviceName": device_name,
        "p_appVersion": app_ver,
        "p_productType": product_type,
        "p_terminalType": terminal_type,
        "p_userId": p_user_id,
        "sdkLevel": sdk_level,
        "userId": user_id,
        "psign": query_psign,
    }

    success_runs = 0
    for i in range(1, target_runs + 1):
        before_curr = curr
        try:
            query_simple(session, f"getFreeAdDuration[{i}]", "https://helper.2bulu.com/getFreeAdDuration", base_params)
        except Exception as e:
            log(f"videoTask precheck[{i}] exception (ignored): {e}")

        info(f"开始第 {i}/{target_runs} 次视频任务，模拟观看 {wait_seconds} 秒")
        time.sleep(wait_seconds)

        ok, resp = claim_task(
            session,
            auth_code=auth_code, auth_type=auth_type, device_name=device_name,
            app_ver=app_ver, product_type=product_type, terminal_type=terminal_type,
            user_id=user_id, p_user_id=p_user_id, sdk_level=sdk_level, task_id="17", uid=None,
        )
        err_code, err_msg = get_err(resp)
        if ok:
            success(f"第 {i} 次视频任务提交成功")
        else:
            warn(f"第 {i} 次视频任务提交失败：{err_msg or err_code}")

        jt = query_tasks(
            session,
            auth_code=auth_code, auth_type=auth_type, device_name=device_name,
            app_ver=app_ver, product_type=product_type, terminal_type=terminal_type,
            user_id=user_id, p_user_id=p_user_id, sdk_level=sdk_level, psign=query_psign,
        )
        video_task = find_task(jt, task_id=17, title_keyword="看视频")
        if not video_task:
            warn("视频任务复查时未找到任务信息")
            break
        new_curr = int(video_task.get("currNum") or 0)
        new_up = int(video_task.get("upNum") or up)
        new_state = str(video_task.get("state"))
        delta = new_curr - before_curr

        info(f"视频任务进度：{new_curr}/{new_up}（本次 +{max(delta,0)}）")

        if delta > 0:
            success_runs += delta
            success(f"第 {i} 次视频任务记账成功")
        else:
            if ok:
                warn("视频任务接口返回成功，但进度未增长，本次不计为成功")
            else:
                warn("视频任务进度未增长，本次未完成")
            break

        curr = new_curr
        up = new_up
        if curr >= up or new_state == "2":
            success("视频任务已达到今日上限")
            break

        if i < target_runs:
            gap = random.uniform(8, 15)
            log(f"videoTask gap sleep {gap:.2f}s")
            time.sleep(gap)

    info(f"视频任务汇总：初始 {start_curr}，最终 {curr}，本次成功 {success_runs} 次")


def finish_task_three_times(session: requests.Session, finish_url: str):
    log("STEP3 finishTask 额外提交 3 次开始")
    for i in range(1, 4):
        try:
            log(f"extra finishTask 第 {i} 次提交")
            r, dt, j = request_with_retry(session, finish_url, name=f"extra finishTask#{i}", retries=1)
            log(f"status={r.status_code} time_ms={dt:.0f}")
            log(f"resp: {truncate(r.text)}")
            err_code, err_msg = get_err(j)
            if err_code and err_code != "0":
                log(f"extra finishTask#{i} errCode={err_code} errMsg={err_msg}")
        except Exception:
            log("extra finishTask 异常：")
            log(traceback.format_exc())

        if i < 3:
            sleep_time = random.uniform(15, 20)
            log(f"sleep {sleep_time:.2f}s")
            time.sleep(sleep_time)
    log("STEP3 完成")


def main():
    section("--- 两步路 账号开始运行 ---")
    info("日志模式：详细调试" if DEBUG else "日志模式：简洁模式")

    signin_psign = os.getenv("BULU_SIGNIN_PSIGN", "8a7ea87afed98619f2ecdf88c0e62031").strip()

    user_id = os.getenv("BULU_USER_ID", "<SENSITIVE>").strip()
    p_user_id = os.getenv("BULU_P_USER_ID", "<SENSITIVE>").strip()
    auth_code = os.getenv("BULU_AUTH_CODE", "<SENSITIVE>").strip()
    auth_type = os.getenv("BULU_AUTH_TYPE", "<SENSITIVE>").strip()
    device_name = os.getenv("BULU_DEVICE_NAME", "iPhone 15 Pro Max").strip()
    app_ver = os.getenv("BULU_APP_VERSION", "8.1.5").strip()
    product_type = os.getenv("BULU_PRODUCT_TYPE", "0").strip()
    terminal_type = os.getenv("BULU_TERMINAL_TYPE", "3").strip()
    sdk_level = os.getenv("BULU_SDK_LEVEL", "26.3.1").strip()

    fallback_task_id = os.getenv("BULU_TASK_ID", "15").strip()

    signin_url = build_url(
        "https://helper.2bulu.com/signIn",
        {
            "authCode": auth_code,
            "authType": auth_type,
            "deviceName": device_name,
            "p_appVersion": app_ver,
            "p_productType": product_type,
            "p_terminalType": terminal_type,
            "p_userId": p_user_id,
            "sdkLevel": sdk_level,
            "userId": user_id,
            "psign": signin_psign,
        },
    )

    session = build_session()

    try:
        do_daily_read(
            session,
            auth_code=auth_code,
            auth_type=auth_type,
            device_name=device_name,
            app_version=app_ver,
            product_type=product_type,
            terminal_type=terminal_type,
            user_id=user_id,
            sdk_level=sdk_level,
            per_article_seconds=int(os.getenv("BULU_READ_SECONDS", "11")),
        )
    except Exception as e:
        log(f"dailyRead exception (ignored): {e}")

    try:
        query_psign = os.getenv("BULU_QUERYTASKS_PSIGN", "8530ad747ed4efb06d3965d58630f376").strip()
        jt = query_tasks(
            session,
            auth_code=auth_code,
            auth_type=auth_type,
            device_name=device_name,
            app_ver=app_ver,
            product_type=product_type,
            terminal_type=terminal_type,
            user_id=user_id,
            p_user_id=p_user_id,
            sdk_level=sdk_level,
            psign=query_psign,
        )
        try:
            print_task_list(jt, header="TASK LIST (after dailyRead)")
        except Exception:
            pass
        err_code, err_msg = get_err(jt)
        if err_code and err_code != "0":
            warn(f"获取任务列表失败：{err_msg or err_code}")
        else:
            tasks = jt.get("tasks") if isinstance(jt, dict) else None
            read_task = None
            if isinstance(tasks, list):
                for t in tasks:
                    if str(t.get("taskId")) == "15" or (isinstance(t.get("title"), str) and "每日阅读" in t.get("title")):
                        read_task = t
                        break
            if read_task:
                curr = read_task.get("currNum")
                up = read_task.get("upNum")
                state = read_task.get("state")
                log(f"dailyRead task status: taskId={read_task.get('taskId')} currNum={curr} upNum={up} state={state}")
                if (isinstance(curr, int) and isinstance(up, int) and curr >= up) and str(state) != "2":
                    uid_env = os.getenv("BULU_UID", "").strip() or None
                    ok, _ = claim_task(
                        session,
                        auth_code=auth_code,
                        auth_type=auth_type,
                        device_name=device_name,
                        app_ver=app_ver,
                        product_type=product_type,
                        terminal_type=terminal_type,
                        user_id=user_id,
                        p_user_id=p_user_id,
                        sdk_level=sdk_level,
                        task_id=str(read_task.get("taskId")),
                        uid=uid_env,
                    )
                    if ok:
                        log("dailyRead reward claimed (finishTask).")
                    else:
                        log("dailyRead reward not claimed (finishTask failed).")
            else:
                log("dailyRead task not found in queryTasks.")
    except Exception as e:
        log(f"queryTasks/claim exception (ignored): {e}")

    base_params = {
        "deviceName": device_name,
        "p_appVersion": app_ver,
        "p_productType": product_type,
        "p_terminalType": terminal_type,
        "p_userId": p_user_id,
        "sdkLevel": sdk_level,
        "psign": signin_psign,
    }
    try:
        query_simple(session, "welfare(before)", "https://helper.2bulu.com/greenPea/welfare", base_params)
        query_simple(session, "signInfoList(before)", "https://helper.2bulu.com/signInfoList", base_params)
    except Exception as e:
        log(f"pre-check exception (ignored): {e}")

    section("开始执行：每日签到")
    r1, dt1, j1 = request_with_retry(session, signin_url, name="signIn", retries=2)
    log(f"signIn status={r1.status_code} time_ms={dt1:.0f}")
    log(f"signIn resp: {truncate(r1.text)}")

    err_code, err_msg = get_err(j1)
    sign_ok = False
    if r1.status_code != 200:
        log("signIn failed: http status not 200")
    elif err_code and err_code != "0":
        if is_already_done(err_msg):
            success(f"签到状态：{err_msg or '今日已完成'}")
            sign_ok = True
        else:
            warn(f"签到返回：{err_msg or err_code}")
    else:
        log("signIn OK")
        sign_ok = True

    if not sign_ok:
        log(f"signIn URL: {signin_url}")
        if err_msg == "请求参数有误":
            log("诊断建议：请确认 BULU_DEVICE_NAME 等参数不要手动写成 %XX 形式；保持原始字符串（如 'iPhone 15 Pro Max'）。")

    uid = None
    task_id = fallback_task_id
    if isinstance(j1, dict):
        uid = j1.get("uid") or j1.get("uId") or j1.get("UID")
        if j1.get("taskId") is not None:
            task_id = str(j1.get("taskId"))
    if uid:
        log(f"signIn 返回 uid={uid}")
    log(f"finishTask 将使用 taskId={task_id}（fallback={fallback_task_id}）")

    finish_psign = get_finish_psign(task_id)

    finish_url = build_url(
        "https://helper.2bulu.com/greenPea/finishTask",
        {
            "authCode": auth_code,
            "authType": auth_type,
            "deviceName": device_name,
            "p_appVersion": app_ver,
            "p_productType": product_type,
            "p_terminalType": terminal_type,
            "p_userId": p_user_id,
            "sdkLevel": sdk_level,
            "taskId": task_id,
            "uid": uid,
            "userId": user_id,
            "psign": finish_psign,
        },
    )

    try:
        query_simple(session, "signInfoList(after signIn)", "https://helper.2bulu.com/signInfoList", base_params)
        query_simple(session, "welfare(after signIn)", "https://helper.2bulu.com/greenPea/welfare", base_params)
    except Exception as e:
        log(f"post-signin check exception (ignored): {e}")

    section("开始执行：签到奖励领取")
    r2, dt2, j2 = request_with_retry(session, finish_url, name="finishTask", retries=2)
    log(f"finishTask status={r2.status_code} time_ms={dt2:.0f}")
    log(f"finishTask resp: {truncate(r2.text)}")

    err_code2, err_msg2 = get_err(j2)
    finish_ok = False
    if r2.status_code != 200:
        log("finishTask failed: http status not 200")
    elif err_code2 and err_code2 != "0":
        if is_already_done(err_msg2):
            log(f"finishTask 已完成/重复：errCode={err_code2} errMsg={err_msg2}")
            finish_ok = True
        else:
            log(f"finishTask failed: errCode={err_code2} errMsg={err_msg2}")
            log("提示：如果 errCode 表示签名/参数问题，请用抓包值设置 BULU_FINISH_PSIGN，并确认 taskId/uid 是否一致。")
    else:
        log("finishTask OK")
        finish_ok = True

    if not finish_ok:
        finish_task_three_times(session, finish_url)

    try:
        perform_video_task(
            session,
            auth_code=auth_code, auth_type=auth_type, device_name=device_name,
            app_ver=app_ver, product_type=product_type, terminal_type=terminal_type,
            user_id=user_id, p_user_id=p_user_id, sdk_level=sdk_level,
            max_times=int(os.getenv("BULU_VIDEO_TIMES", "3")),
        )
    except Exception as e:
        log(f"videoTask exception (ignored): {e}")

    try:
        query_simple(session, "welfare(final)", "https://helper.2bulu.com/greenPea/welfare", base_params)
        query_simple(session, "signInfoList(final)", "https://helper.2bulu.com/signInfoList", base_params)
    except Exception as e:
        log(f"final sign check exception (ignored): {e}")

    try:
        query_psign = os.getenv("BULU_QUERYTASKS_PSIGN", "8530ad747ed4efb06d3965d58630f376").strip()
        jt2 = query_tasks(
            session,
            auth_code=auth_code,
            auth_type=auth_type,
            device_name=device_name,
            app_ver=app_ver,
            product_type=product_type,
            terminal_type=terminal_type,
            user_id=user_id,
            p_user_id=p_user_id,
            sdk_level=sdk_level,
            psign=query_psign,
        )
        print_task_list(jt2, header="TASK LIST (final)")
    except Exception as e:
        log(f"final queryTasks exception (ignored): {e}")

    section("--- 运行结束 ---")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log("EXCEPTION:\n" + traceback.format_exc())
        sys.exit(2)
