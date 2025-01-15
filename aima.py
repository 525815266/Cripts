import requests
import json

# 账号信息列表，每个账号用字典表示
accounts = [
    {
        "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvTFZEVGp1S0FrdDMteTFQNHBpZURWMlBpUXBNIiwib3BlbmlkIjoib0JPOGM0NUM5NnNMOHRabUJjeU9OTGlkanpyNCIsIm1vYmlsZSI6IjE3ODUzNTYwMjYxIiwidXNlclR5cGUiOiJNRU1CRVIiLCJleHAiOjE3MzUyMjY5MDEsImJlbG9uZ1RvSWQiOjEsImlhdCI6MTczMjYzNDkwMSwibWVtYmVySWQiOjEzMjgxOTM4MX0.zU_YX5iG1E6ETn0K9XVqLxla81ALVWnh2Z89qYGw5bg",
        "sign": "2da163f2a1298884111edcde079218c1",
        "referer": "https://servicewechat.com/wx2dcfb409fd5ddfb4/190/page-frame.html"
    },
    {
        "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvTFZEVGprTFJFakZXbk9qSlkxUlZQUU5XNjVrIiwib3BlbmlkIjoib0JPOGM0MHdvM09RT2ZCajEyWXlNZmtyRUZVcyIsIm1vYmlsZSI6IjE3ODUzNTYwMjYyIiwidXNlclR5cGUiOiJNRU1CRVIiLCJleHAiOjE3MzUyNzA0NTEsImJlbG9uZ1RvSWQiOjEsImlhdCI6MTczMjY3ODQ1MSwibWVtYmVySWQiOjEzMjgxNDU3N30.yP4ORZyLthBtJeXSKPI9xnqVaHtUzI-WeOHnIDTO4PA",
        "sign": "1a497c207d76d434c20cd2f8d12260aa",
        "referer": "https://servicewechat.com/wx2dcfb409fd5ddfb4/190/page-frame.html"
    }
]

# 默认的活动 ID
DEFAULT_ACTIVITY_ID = 100000994

def get_activity_id(access_token, last_activity_id):
    """ 获取活动 ID，筛选符合条件的活动 """
    url = "https://scrm.aimatech.com/aima/wxclient/mkt/activities/locations:search"
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.53(0x18003531) NetType/4G Language/zh_CN',
        'Content-Type': 'application/json',
        'Access-Token': access_token,
        'Referer': "https://servicewechat.com/wx2dcfb409fd5ddfb4/190/page-frame.html"
    }

    try:
        # 请求活动列表
        response = requests.post(url, headers=headers, json={"locations": [0, 1, 2]})
        response_data = response.json()

        # 错误码检查
        if response_data.get("code") != 200:
            print(f"获取活动 ID 出错: {response_data.get('chnDesc')}, 使用默认活动 ID")
            return DEFAULT_ACTIVITY_ID

        # 获取活动列表
        activities = response_data.get("content", [])
        if not activities:
            print("未找到活动数据，返回默认活动 ID")
            return DEFAULT_ACTIVITY_ID
        
        # 遍历活动列表，查找包含“签到”字眼的活动
        for activity in activities:
            activity_name = activity.get("name", "")
            template_name = activity.get("templateName", "")
            
            # 只打印出与"签到"字眼相关的活动
            if '签到' in activity_name or '签到' in template_name:
                # 如果活动 ID 与上次相同，不再打印
                if activity['activityId'] == last_activity_id:
                    return last_activity_id  # 如果相同，返回上次的活动 ID，避免重复打印
                print(f"找到符合条件的活动: {activity_name}，活动ID: {activity['activityId']}")
                return activity['activityId']
        
        # 如果未找到符合条件的活动，返回默认活动 ID
        print("未找到符合条件的活动，返回默认活动 ID")
        return DEFAULT_ACTIVITY_ID

    except Exception as e:
        print(f"获取活动 ID 出错: {e}, 使用默认活动 ID")
        return DEFAULT_ACTIVITY_ID



def sign_in(account, index, last_activity_id):
    # 获取活动 ID
    activity_id = get_activity_id(account["access_token"], last_activity_id)
    
    url = "https://scrm.aimatech.com/aima/wxclient/mkt/activities/sign:join"
    
    headers = {
        'Content-Length': '49',
        'App-Id': 'scrm',
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.53(0x18003531) NetType/4G Language/zh_CN',
        'Connection': 'keep-alive',
        'Time-Stamp': '1732721186000',
        'Accept-Encoding': 'gzip,compress,br,deflate',
        'TraceLog-Id': 'f5c6aa1a-cfea-441c-9928-a4ba70884493',
        'Access-Token': account["access_token"],
        'Sign': account["sign"],
        'content-type': 'application/json',
        'Referer': account["referer"]
    }
    
    # POST 请求体数据
    data = {
        "activityId": activity_id,
        "activitySceneId": None
    }
    
    try:
        # 发送 POST 请求
        response = requests.post(url, headers=headers, json=data)
        response_data = response.json()

        # 获取返回的 code 和内容
        code = response_data.get("code")
        content = response_data.get("content", {})

        # 判断返回的 code 是否为 200，表示成功
        if code == 200:
            sign_record_id = content.get("signRecordId")
            member_id = content.get("memberId")
            points = content.get("point")
            description = content.get("description")

            # 输出签到成功的信息
            print(f"\n账号{index} 签到成功！")
            print(f"签到记录ID: {sign_record_id}")
            print(f"成员ID: {member_id}")
            print(f"获得积分: {points}")
            print(f"活动描述: {description}")
        elif code == 920101:
            print(f"\n账号{index} 今日已签到，无法再次签到！")
        else:
            print(f"\n账号{index} 签到失败，错误码: {code}, 详细信息: {response_data.get('detail')}")

    except Exception as e:
        print(f"账号{index} 请求出错:", e)

# 主程序入口
if __name__ == "__main__":
    last_activity_id = None  # 用来存储上一次获取到的活动ID
    # 遍历所有账号并依次执行签到操作，传入递增的账号编号
    for index, account in enumerate(accounts, start=1):
        last_activity_id = sign_in(account, index, last_activity_id)
