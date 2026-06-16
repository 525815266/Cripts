
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-account unified script (all accounts share identical request config except token).

What changed vs previous:
- Single GLOBAL config for domain, headers (UA / referer / x-provider-id), and workflow.
- Each account only needs a name and Authorization (Bearer token). Everything else is shared.
- Still supports ENV-based accounts via ACCOUNTS_JSON. You can keep just "name" and "authorization".

ENV examples:
  export BARK_PUSH_KEY="xxxxx"
  export ACCOUNTS_JSON='[
    {"name":"账号1","authorization":"<SENSITIVE>"},
    {"name":"账号2","authorization":"<SENSITIVE>"}
  ]'
"""
import os
import time
import random
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import requests

# ===== Global, shared config for ALL accounts =====
GRAPHQL_URL = "https://shd.luxingiot.com/graphql"
REFERER = "https://servicewechat.com/wx9939a74ee8a8522a/16/page-frame.html"
X_PROVIDER_ID = "wx9939a74ee8a8522a"
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.42(0x18002a32) NetType/WIFI Language/zh_CN"
)
CONTENT_TYPE = "application/json"

# Shared notification (optional)
BARK_API_BASE = os.getenv("BARK_API_BASE", "https://api.day.app")
BARK_PUSH_KEY_DEFAULT = os.getenv("BARK_PUSH_KEY", "")
QINGLONG_NOTIFY_URL = os.getenv("QINGLONG_NOTIFY_URL", "")

# GraphQL
SIGN_QUERY = (
    "mutation activity($activity_id: Int!) {"
    "  activityPush(id: $activity_id) {"
    "    code message"
    "    reward_log { action reward_type amount balance }"
    "  }"
    "}"
)
EXCHANGE_QUERY = 'mutation CouponExchange($index: Int!){ couponExchange(index: $index) }'

# Workflow: 签到 + 3 次视频
HAR_STEPS = [
    {"activity_id": 1},
    {"activity_id": 2},
    {"activity_id": 2},
    {"activity_id": 2},
]

# 统一的兑换阈值（如需更改，直接改这里）
EXCHANGE_THRESHOLD = int(os.getenv("EXCHANGE_THRESHOLD", "10000000"))

@dataclass
class Account:
    name: str
    authorization: str
    bark_key: Optional[str] = None  # 可选：单账号覆盖 Bark key

    def headers(self) -> Dict[str, str]:
        return {
            "Content-Type": CONTENT_TYPE,
            "Authorization": self.authorization,
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "x-provider-id": X_PROVIDER_ID,
        }

def sleep_between(min_s: int, max_s: int) -> None:
    t = random.randint(min_s, max_s)
    print(f"  ⏳ 等待 {t} 秒...", flush=True)
    time.sleep(t)

def gql_request(query: str, variables: Dict[str, Any], headers: Dict[str, str], retries: int = 3) -> Optional[Dict[str, Any]]:
    payload = {"query": query, "variables": variables}
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(GRAPHQL_URL, headers=headers, json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"    第 {attempt}/{retries} 次请求失败：{e}")
            if attempt < retries:
                sleep_between(2, 4)
    return None

def push_bark(title: str, body: str, bark_key: Optional[str]) -> None:
    key = bark_key or BARK_PUSH_KEY_DEFAULT
    if not key:
        return
    url = f"{BARK_API_BASE}/{key}/{title}/{body}"
    try:
        requests.get(url, timeout=15)
    except Exception as e:
        print(f"  ⚠️ Bark 推送失败：{e}")

def notify_qinglong(title: str, content: str) -> None:
    if not QINGLONG_NOTIFY_URL:
        return
    try:
        requests.post(
            QINGLONG_NOTIFY_URL,
            json={"title": title, "content": content, "channel": "Bark"},
            timeout=15,
        )
    except Exception as e:
        print(f"  ⚠️ 青龙通知失败：{e}")

def run_account(acc: Account) -> Dict[str, Any]:
    print(f"▶ 开始账号：{acc.name}")
    success_ops = 0
    final_lines: List[str] = []
    last_balance: Optional[int] = None
    last_message: str = ""

    for idx, step in enumerate(HAR_STEPS, start=1):
        # 签到等待较短，视频较长
        sleep_between(3 if idx == 1 else 25, 5 if idx == 1 else 30)
        action_tip = "正在签到" if idx == 1 else f"正在看第 {idx-1} 个视频"
        print(f"  {action_tip}")
        final_lines.append(action_tip)

        resp = gql_request(SIGN_QUERY, step, acc.headers())
        if resp is None:
            final_lines.append("请求失败（网络或服务异常）")
            continue

        data = resp.get("data", {})
        ap = data.get("activityPush") if data else None
        if ap is None:
            final_lines.append("返回异常")
            continue

        
        last_message = ap.get("message", "")
        rlog = ap.get("reward_log")
        code = ap.get("code")
        if code == 0 and rlog:
            success_ops += 1
            last_balance = rlog.get("balance")
            # 新增：如果是观看视频，则显示“账号x，本次获取xx，总共xx金币”
            action = rlog.get("action")
            amount = rlog.get("amount")
            if str(action) == "观看视频":
                msg_line = f"🎬 {acc.name} 本次获取 {amount}，总共 {last_balance} 金币"
                print("  " + msg_line)
                final_lines.append(msg_line)
            final_lines.append(f"余额：{last_balance} / 状态：{last_message or 'OK'}")
        else:
            final_lines.append(f"无积分记录 / 状态：{last_message or code}")
    # Push
    summary = "\n".join(final_lines)
    title = "充电桩任务(完成)"
    push_bark(title, summary, acc.bark_key)

    # 统一阈值兑换
    exchange_result = None
    if last_balance is not None and last_balance >= EXCHANGE_THRESHOLD:
        print(f"  ✅ 达到兑换阈值（{EXCHANGE_THRESHOLD}），尝试兑换1000积分券...")
        sleep_between(5, 10)
        resp = gql_request(EXCHANGE_QUERY, {"index": 0}, acc.headers())
        if resp and resp.get("data", {}).get("couponExchange") == 1:
            exchange_result = "兑换1000积分成功！"
            notify_qinglong("积分兑换", exchange_result)
            push_bark(title, exchange_result, acc.bark_key)
        else:
            exchange_result = "兑换1000积分失败"
            push_bark(title, exchange_result, acc.bark_key)
    else:
        print("  积分未达到统一阈值，跳过兑换。")

    return {
        "name": acc.name,
        "success_ops": success_ops,
        "last_message": last_message,
        "last_balance": last_balance,
        "summary": summary,
        "exchange_result": exchange_result,
    }

def load_accounts_from_env() -> List[Account]:
    acc_json = os.getenv("ACCOUNTS_JSON", "<SENSITIVE>").strip()
    if not acc_json:
        return []
    try:
        items = json.loads(acc_json)
        out = []
        for it in items:
            out.append(Account(
                name=it["name"],
                authorization=it["authorization"],
                bark_key=it.get("bark_key"),
            ))
        return out
    except Exception as e:
        print("读取 ACCOUNTS_JSON 失败：", e)
        return []

def main():
    # ===== Only token differs across accounts =====
    accounts: List[Account] = [
        Account(name="账号1", authorization="<SENSITIVE>"),
        Account(name="账号2", authorization="<SENSITIVE>"),
        Account(name="账号3", authorization="<SENSITIVE>"),
    ]

    env_accounts = load_accounts_from_env()
    if env_accounts:
        accounts = env_accounts

    results = []
    for acc in accounts:
        print("="*60)
        results.append(run_account(acc))

    print("\n===== 全部账号执行结果 =====")
    for r in results:
        print(f"- {r['name']}: ops={r['success_ops']} balance={r['last_balance']} msg={r['last_message']}")

if __name__ == "__main__":
    main()
