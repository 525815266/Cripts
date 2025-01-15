import requests

def sign_in():
    url = 'https://webapi.qbb6.com/h5/api/qbean/internal/user/sign/post?trackinfo=YqrixWKtaGy&userCode=&qbeanCode=1VW0xZDdzdFl5d1RkT2FXVThJZUdOQUNxM1pLLnhiMlBYYm5RUTlyLm1HTEhfcl9rY1Vsal9sSGRwWlQwWDBpYQ%253D%253D&accountId=dLtfi7KtaGy'
    
    headers = {
        'Content-Length': '0',
        'Referer': 'https://stlib.qbb6.com/',
        'Accept-Encoding': 'gzip, deflate, br',
        'Host': 'webapi.qbb6.com',
        'Origin': 'https://stlib.qbb6.com',
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
        'Connection': 'keep-alive',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh-Hans;q=0.9'
    }

    try:
        # 发送 POST 请求
        response = requests.post(url, headers=headers)
        response_data = response.json()

        # 处理响应数据
        if response_data.get("rc") == 0:
            sign_serials = response_data.get("signSerials", [])
            if sign_serials:
                for sign in sign_serials:
                    count = sign.get("count")
                    score = sign.get("score")
                    description = sign.get("description", "")
                    if count is not None and score is not None:
                        print(f"{description}，连续签到 {count} 天，当前奖励值：{score}")
            else:
                print("签到成功，但没有签到奖励信息，完整响应如下：", response_data)
        else:
            print("签到失败:", response_data)

    except Exception as e:
        print("请求出错:", e)

# 主程序入口
if __name__ == "__main__":
    sign_in()
