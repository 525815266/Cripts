# csj_auto_signin.py （修复 CSRF 问题版）
import requests
import json

# ====== 请根据你的 HAR 文件填写以下内容 ======

# 1. 完整 Cookie 字符串（从 HAR 的 Request Headers -> Cookie 复制）
COOKIE_STR = "<SENSITIVE>"

# 2. 从 HAR 的 Request Headers 中复制 X-CSRF-Token 的值
CSRF_TOKEN = "<SENSITIVE>"  # ← 替换成你的真实值！

# ==============================================

URL = "https://www.csjplatform.com/union_pangle/api/growth_diag/sign_in"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.csjplatform.com/union_pangle/growth",
    "Origin": "https://www.csjplatform.com",
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    # 关键：添加 CSRF Token 头
    "X-CSRF-Token": CSRF_TOKEN,
}

# 转换 Cookie 字符串为字典
COOKIES = {}
for item in COOKIE_STR.strip().split(";"):
    if "=" in item:
        key, val = item.strip().split("=", 1)
        COOKIES[key] = val

def auto_sign_in():
    print("🚀 正在执行穿山甲平台自动签到（含 CSRF Token）...")
    
    try:
        response = requests.post(
            url=URL,
            headers=HEADERS,
            cookies=COOKIES,
            json={},  # 穿山甲签到通常不需要 body
            timeout=10
        )
        
        print(f"状态码: {response.status_code}")
        resp_json = response.json()
        print("响应内容:")
        print(json.dumps(resp_json, ensure_ascii=False, indent=2))
        
        code = resp_json.get("code")  # 注意：是小写 code！
        if code == "0":
            print("✅ 签到成功！")
        elif code == "PG0002":
            print("ℹ️ 今日已签到")
        elif code == "PG0001":
            print("❌ 未登录，请更新 Cookie")
        elif code == "PG9997":
            print("❌ CSRF Token 无效！请检查 X-CSRF-Token 和 Cookie 是否匹配且最新")
        else:
            print("⚠️ 其他错误，请查看 message")
            
    except Exception as e:
        print(f"💥 请求出错: {e}")

if __name__ == "__main__":
    auto_sign_in()