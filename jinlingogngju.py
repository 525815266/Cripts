import requests
import os
import json
from datetime import datetime
import time

def sign_in():
    # 记录签到状态的文件路径
    status_file = "sign_in_status.json"
    
    # 检查是否已经签到
    if os.path.exists(status_file):
        with open(status_file, "r") as file:
            status_data = json.load(file)
            last_sign_in = status_data.get("last_sign_in")
            if last_sign_in == datetime.now().strftime("%Y-%m-%d"):
                print("今天已经签到过，无需重复签到。")
                return

    url = "https://api.remeins.com/user/sign"
    headers = {
        "Connection": "keep-alive",
        "Referer": "https://servicewechat.com/wxc523481179a8c541/23/page-frame.html",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.52(0x18003425) NetType/WIFI Language/zh_CN",
        "Host": "api.remeins.com",
        "Accept-Encoding": "gzip,compress,br,deflate",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "adfrom": "user",
        "vtoken": "3f162796a96b59919db4129168f8a035",
        "version": "1.1.8"
    }

    success_count = 0
    failure_count = 0

    try:
        # 签到5次
        for i in range(5):
            response = requests.post(url, headers=headers, data=data)
            if response.status_code == 200:
                response_data = response.json()
                if response_data.get("status") == 0:
                    print(f"第{i+1}次签到成功: ", response_data.get("msg"))
                    success_count += 1
                elif response_data.get("status") == 1:
                    print(f"第{i+1}次签到失败: 重复签到，服务器返回信息: ", response_data.get("msg"))
                    failure_count += 1
                else:
                    print(f"第{i+1}次签到失败: 服务器返回信息: ", response_data.get("msg"))
                    failure_count += 1
            else:
                print(f"第{i+1}次签到失败，状态码: ", response.status_code)
                failure_count += 1

            # 等待15秒以防止请求过快
            time.sleep(15)

        # 获取最终金币数量
        final_coins = get_current_coins()
        if final_coins is not None:
            print(f"签到结束后当前金币数量: {final_coins}")
        else:
            print("无法获取最终金币数量，可能是用户信息未找到或者服务器问题。")

        # 记录签到日期
        with open(status_file, "w") as file:
            json.dump({"last_sign_in": datetime.now().strftime("%Y-%m-%d")}, file)

        # 调用青龙通知程序发送签到结果
        notify_message = f"记灵工具签到任务成功{success_count}次，失败{failure_count}次"
        print(notify_message)
        send_notification(notify_message)
    except Exception as e:
        print("请求出错: ", e)

def get_current_coins():
    url = "https://api.remeins.com/user/myintegral"
    headers = {
        "Connection": "keep-alive",
        "Referer": "https://servicewechat.com/wxc523481179a8c541/23/page-frame.html",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.52(0x18003425) NetType/WIFI Language/zh_CN",
        "Host": "api.remeins.com",
        "Accept-Encoding": "gzip,compress,br,deflate",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get("status") == 0:
                try:
                    coins = int(response_data.get("msg"))
                    return coins
                except ValueError:
                    print("获取金币失败，返回的金币数据无法转换为整数: ", response_data.get("msg"))
            else:
                print("获取金币失败，服务器返回信息: ", response_data.get("msg"))
        else:
            print("获取金币失败，状态码: ", response.status_code)
    except Exception as e:
        print("获取金币请求出错: ", e)
    return None

def send_notification(message):
    # 此处调用青龙的通知程序发送通知
    try:
        # 示例: 调用青龙通知接口发送通知
        # 请根据青龙通知程序的实际接口进行修改
        url = "http://localhost:5700/notify"
        data = {
            "message": message
        }
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print("通知发送成功")
        else:
            print("通知发送失败，状态码: ", response.status_code)
    except Exception as e:
        print("通知发送出错: ", e)

if __name__ == "__main__":
    sign_in()