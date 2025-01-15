import requests
import time
import random

# 设置请求头
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer 55266|QEqX4ENkwpeCPtWXozSc7AjBKJ22Sm3PkVlrYP8i80f31b87",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42(0x18002a32) NetType/WIFI Language/zh_CN",
    "Referer": "https://servicewechat.com/wx9939a74ee8a8522a/9/page-frame.html",
    "x-provider-id": "wx9939a74ee8a8522a"
}

# 定义Bark API URL和密钥
bark_api_url = "https://api.day.app/tEtZkUo5EQwWCYuYcAXdMP"
bark_push_key = "tEtZkUo5EQwWCYuYcAXdMP"

# 定义青龙通知URL
qinglong_notify_url = "http://localhost:5700/api/send"

# 定义GraphQL签到的mutation查询
sign_in_query = '''
    mutation activity($activity_id: Int!) {
        activityPush(id: $activity_id) {
            code
            message
            reward_log {
                action
                reward_type
                amount
                balance
            }
        }
    }
'''

# 结合两个HAR文件的数据
har_data = [
    {"activity_id": 1},  # 第一个签到请求
    {"activity_id": 2},  # 第一个奖励请求
    {"activity_id": 2},  # 第二个奖励请求
    {"activity_id": 2}   # 第三个奖励请求
]

success_count = 0
final_message = ""

for index, data in enumerate(har_data):
    # 随机等待25-30秒模拟观看视频所需时间
    wait_duration = random.randint(25, 30)
    print(f"步骤 {index + 1}: 等待 {wait_duration} 秒后继续...", flush=True)
    time.sleep(wait_duration)

    if index == 0:
        print("正在签到", flush=True)
        final_message += "正在签到\n"
    else:
        print(f"正在看第 {index} 个视频", flush=True)
        final_message += f"正在看第 {index} 个视频\n"

    retry_count = 0
    while retry_count < 3:  # 最多重试3次
        payload = {
            "query": sign_in_query,
            "variables": data,
            "operationName": "activity"
        }

        try:
            # 发送POST请求
            response = requests.post("https://mimeng.feichi.cn/graphql", headers=headers, json=payload)
            json_response = response.json()

            # 处理响应结果
            if "data" in json_response:
                activity_push = json_response["data"]["activityPush"]
                code = activity_push["code"]
                message = activity_push["message"]
                reward_log = activity_push.get("reward_log")

                print(f"步骤 {index + 1}:")
                if message != "任务已完成":
                    print("Code:", code)
                    print("Message:", message)

                    if reward_log is not None:
                        print("Reward Log:")
                        print(" - Action:", reward_log.get("action"))
                        print(" - Reward Type:", reward_log.get("reward_type"))
                        print(" - Amount:", reward_log.get("amount"))
                        print(" - Balance:", reward_log.get("balance"))

                        success_count += 1
                else:
                    print("任务已完成。跳过后续步骤。")
                    final_message += "任务已完成，跳过后续步骤。\n"
                    break

            else:
                print("Error:", json_response)

            break

        except requests.exceptions.RequestException as e:
            print(f"网络错误：{e}")

        retry_count += 1

    if reward_log is None or message == "任务已完成":
        final_message += f"\n无积分记录\n成功操作次数：{success_count}\n签到状态：{message}"
    else:
        final_message += f"\n总积分：{reward_log['balance']}\n成功操作次数：{success_count}\n签到状态：{message}"

print(final_message, flush=True)

# 发送Bark通知
bark_title = f"充电桩任务[{'执行完成' if '任务已完成' in final_message else '执行中'}]+{reward_log['balance']}积分余额"
requests.get(bark_api_url + f"/{bark_title}/{final_message}")

# 检查积分是否超过1000
if reward_log is not None and reward_log["balance"] >= 999999:
    # 随机等待5-10秒模拟兑换所需时间
    wait_duration = random.randint(5, 10)
    print(f"兑换1000积分成功！等待 {wait_duration} 秒后继续...", flush=True)
    time.sleep(wait_duration)

    # 发送兑换请求
    response = requests.post("https://mimeng.feichi.cn/graphql", json={
        "query": "mutation CouponExchange($index: Int!) {\n  couponExchange(index: $index)\n}",
        "variables": {
            "index": 0
        },
        "operationName": "CouponExchange"
    }, headers=headers)

    # 检查兑换请求的响应
    if response.status_code == 200:
        json_response = response.json()
        if "data" in json_response and json_response["data"]["couponExchange"] == 1:
            exchange_message = "兑换1000积分成功！"

            # 发送青龙通知请求
            notify_payload = {
                "title": "积分兑换",
                "content": exchange_message,
                "channel": "Bark"  # 这里可以根据实际需要选择通知渠道
            }
            qinglong_notify_response = requests.post(qinglong_notify_url, json=notify_payload)

            # 检查青龙通知请求的响应
            if qinglong_notify_response.status_code == 200:
                print("青龙通知发送成功")
            else:
                print("青龙通知发送失败")
        else:
            exchange_message = "兑换1000积分失败"
            print(exchange_message)
    else:
        exchange_message = "兑换1000积分请求失败"
        print(exchange_message)

    # 发送Bark通知
    bark_exchange_title = f"充电桩任务[{'执行完成' if '任务已完成' in final_message else '执行中'}]+{reward_log['balance']}积分余额"
    requests.get(bark_api_url + f"/{bark_exchange_title}/{exchange_message}")
else:
    print("积分未达到1000，无法兑换")