import requests
import json

# 请求的 URL
sign_url = "https://api.sfjiayuan.com/api/gold/sign"
watch_url = "https://api.sfjiayuan.com/api/gold/watch"

# 请求头部
headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.55(0x1800372b) NetType/4G Language/zh_CN",
    "Cache-Control": "max-age=10",
    "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjE3Mzc0MTk1MTYsInVzZXJpbmZvIjp7ImlkIjo1NjY5NDgsInRpbWUiOjE3MzY4MTQ3MTZ9fQ.GTz6PTgTvL6urrNPppxw5-AVMeMFZ7qWzC5IrjFhwRc",  # 替换为有效 token
    "Referer": "https://servicewechat.com/wxf01186dfa3e03bc0/42/page-frame.html",
    "Content-Length": "2",
    "content-type": "application/json",
    "Accept-Encoding": "gzip,compress,br,deflate",
    "Host": "api.sfjiayuan.com",
    "Connection": "keep-alive"
}

# 请求数据
data = {}

# 发送签到请求（第一个请求）
def sign_in():
    response = requests.post(sign_url, headers=headers, data=json.dumps(data))
    response_json = response.json()
    if response_json.get("code") == 200:
        print("签到执行成功!")
    else:
        print(f"签到执行失败: {response_json.get('msg', 'Unknown error')}")

# 发送获取金币请求（第二个请求，三次执行）
def watch_gold():
    for i in range(3):  # 每天可以执行三次
        response = requests.post(watch_url, headers=headers, data=json.dumps(data))
        response_json = response.json()
        if response_json.get("code") == 200:
            print(f"【成功】看视频得金币第 {i+1} 次: {response_json['data']['gold']}")
        else:
            print(f"【失败】看视频得金币第 {i+1} 次: {response_json.get('msg', 'Unknown error')}")

# 执行签到请求
sign_in()

# 执行获取金币的三次请求
watch_gold()
