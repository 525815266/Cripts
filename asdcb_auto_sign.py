# -*- coding: utf-8 -*-
"""
阿水大杯茶 自动签到脚本 —— 已填充你的当前账户信息（来自 HAR）
- 运行时无需再传参数，直接：  python asdcb_auto_sign_filled.py
- 如需覆盖，依然支持 CLI 参数 / 环境变量（优先生效）
依赖：pip install httpx
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

import httpx

# === 已从 HAR 填充的默认值（可被参数/环境覆盖） ===
DEFAULTS = {
    "token": "<SENSITIVE>",
    "appid": "wxf4b12e079bb99abc",
    "activity_id": "100820000000000663",
    "mobile": "<PHONE>",
    "user_name": "<ACCOUNT>",
    "store_id": "203192",
    "scene": "1089"
}

BASE = "https://webapi.qmai.cn"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
      "MicroMessenger/8.0.63(0x18003f28) NetType/WIFI Language/zh_CN")
DEFAULT_REFERER = "https://servicewechat.com/" + DEFAULTS["appid"] + "/293/page-frame.html"

def getenv_or(default: Optional[str], env: str) -> Optional[str]:
    return os.environ.get(env) or default

def build_headers(token: str, store_id: Optional[str], scene: Optional[str]) -> Dict[str, str]:
    h = {
        "Accept": "v=1.0",
        "content-type": "application/json",
        "User-Agent": UA,
        "Qm-From": "wechat",
        "Qm-From-Type": "catering",
        "Qm-User-Token": token,
        "Referer": DEFAULT_REFERER,
        "Accept-Language": "zh-CN",
    }
    if store_id:
        h["store-id"] = store_id
    if scene:
        h["scene"] = scene
    return h

def api_post(path: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{BASE}{path}"
    with httpx.Client(timeout=20.0, headers=headers) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        return r.json()

def sign_detail(headers: Dict[str, str], appid: str) -> Dict[str, Any]:
    return api_post("/web/catering/integral/sign/detail", headers, {"appid": appid})

def sign_in(headers: Dict[str, str], appid: str, activity_id: str, mobile: str, user_name: str) -> Dict[str, Any]:
    payload = {
        "activityId": activity_id,
        "mobilePhone": mobile,
        "userName": user_name,
        "appid": appid
    }
    return api_post("/web/catering/integral/sign/signIn", headers, payload)

def total_points(headers: Dict[str, str]) -> Optional[int]:
    try:
        data = api_post("/web/catering/crm/total-points", headers, {})
        if isinstance(data, dict) and data.get("status"):
            return data.get("data")
    except Exception:
        pass
    return None

def main():
    ap = argparse.ArgumentParser(description="阿水大杯茶-自动签到脚本（已填充）")
    ap.add_argument("--token", help="Qm-User-Token（也可用环境变量 QM_USER_TOKEN）")
    ap.add_argument("--appid", help="小程序 appid（也可用环境变量 APPID）")
    ap.add_argument("--activity-id", help="签到活动ID（也可用环境变量 ACTIVITY_ID）")
    ap.add_argument("--mobile", help="手机号码（也可用环境变量 MOBILE）")
    ap.add_argument("--user", dest="user_name", help="用户昵称/姓名（也可用环境变量 USER_NAME）")
    ap.add_argument("--store-id", help="store-id Header（也可用环境变量 STORE_ID）")
    ap.add_argument("--scene", help="scene Header（也可用环境变量 SCENE）")
    ap.add_argument("--dry-run", action="store_true", help="只检查是否已签到，不执行签到")
    args = ap.parse_args()

    # 顺序：ENV > CLI > DEFAULTS
    token = getenv_or(args.token or DEFAULTS["token"], "QM_USER_TOKEN")
    appid = getenv_or(args.appid or DEFAULTS["appid"], "APPID")
    activity_id = getenv_or(args.activity_id or DEFAULTS["activity_id"], "ACTIVITY_ID")
    mobile = getenv_or(args.mobile or DEFAULTS["mobile"], "MOBILE")
    user_name = getenv_or(args.user_name or DEFAULTS["user_name"], "USER_NAME")
    store_id = getenv_or(args.store_id or DEFAULTS["store_id"], "STORE_ID")
    scene = getenv_or(args.scene or DEFAULTS["scene"], "SCENE")

    missing = [k for k, v in {"token": token, "appid": appid, "activity_id": activity_id, "mobile": mobile, "user_name": user_name}.items() if not v]
    if missing:
        print("[ERR] 缺少必要参数：", missing)
        sys.exit(3)

    headers = build_headers(token, store_id, scene)

    # 先查详情
    try:
        detail = sign_detail(headers, appid)
        ok = bool(detail.get("status"))
        if not ok:
            print("[WARN] 详情查询失败：", detail)
        else:
            d = detail.get("data") or {}
            intra = d.get("intraDay")
            act_id = d.get("activityId") or activity_id
            print(f"[INFO] 今日签到状态 intraDay={intra}（1=已签到，0=未签到），activityId={act_id}")
            activity_id = act_id
            if intra == 1:
                print("[OK] 今天已签到。")
                pts = total_points(headers)
                if pts is not None:
                    print(f"[INFO] 当前积分：{pts}")
                sys.exit(0)
    except httpx.HTTPStatusError as e:
        print("[ERR] 详情请求失败：HTTP", e.response.status_code, e.response.text)
    except Exception as e:
        print("[ERR] 详情请求异常：", e)

    if args.dry_run:
        print("[DRY] 只检查不签到；退出。")
        sys.exit(0)

    # 执行签到
    try:
        resp = sign_in(headers, appid, activity_id, mobile, user_name)
        print("[SIGN]", resp)
        if isinstance(resp, dict):
            if resp.get("status") and resp.get("code") in ("0", 0):
                print("[OK] 签到成功！")
            else:
                print("[INFO] 签到返回：", resp.get("message") or resp)
        pts = total_points(headers)
        if pts is not None:
            print(f"[INFO] 当前积分：{pts}")
    except httpx.HTTPStatusError as e:
        print("[ERR] 签到失败：HTTP", e.response.status_code, e.response.text)
        sys.exit(10)
    except Exception as e:
        print("[ERR] 签到异常：", e)
        sys.exit(11)

if __name__ == "__main__":
    main()
