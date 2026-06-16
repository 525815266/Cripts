import requests, json, os, sys, time, random

ENVIRON = 'lhtj'
NAME = '龙湖༒天街'
session = requests.Session()
TIMEOUT = 20

# 说明：
# 1) HAR 仅用于排查接口，不作为运行依赖
# 2) 目前签到接口实际命中时，X-LF-DXRisk-Token 在 HAR 中为一个动态指纹值，而不是脚本里写死的 "1"
# 3) 因此这里将其做成“可选环境变量”，便于后续按需更新，而不强绑定 HAR
# 4) 环境变量格式：
#    lhtj="手机号#token[#risk_token]"
#    多账号换行分隔
#    token 用 lmToken 或 X-LF-UserToken 均可

COMMON_HEADERS = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Content-Type': 'application/json;charset=UTF-8',
    'Host': 'gw2c-hw-open.longfor.com',
    'Origin': 'https://longzhu.longfor.com',
    'Referer': 'https://longzhu.longfor.com/',
    'User-Agent': (
        'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
        'MicroMessenger/8.0.69(0x1800452e) NetType/WIFI Language/zh_CN '
        'miniProgram/wx50282644351869da'
    ),
    'X-LF-Channel': 'C2',
    'X-LF-Bu-Code': 'C20400',
}

SIGN_ACTIVITY_NO = '11111111111686241863606037740000'
SIGN_GAIA_KEY = 'c06753f1-3e68-437d-b592-b94656ea5517'

LOTTERY_COMPONENT_NO = 'CK09N57J55N28XF0'
LOTTERY_ACTIVITY_NO = 'AP25W011M67ROK5Z'
LOTTERY_GAIA_KEY = '2f9e3889-91d9-4684-8ff5-24d881438eaf'


def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {'code': 'HTTP_%s' % resp.status_code, 'message': resp.text[:300], 'data': {}}


def build_auth_headers(token, gaia_key=None, risk_token=None):
    headers = COMMON_HEADERS.copy()
    headers.update({
        'token': token,
        'X-LF-UserToken': token,
    })
    if gaia_key:
        headers['X-GAIA-API-KEY'] = gaia_key
    if risk_token:
        headers['X-LF-DXRisk-Source'] = '5'
        headers['X-LF-DXRisk-Captcha-Token'] = 'undefined'
        headers['X-LF-DXRisk-Token'] = risk_token
    return headers


def build_info_headers(token):
    return {
        'Accept': '*/*',
        'Content-Type': 'application/json',
        'lmToken': token,
        'X-Gaia-Api-Key': '98717e7a-a039-46af-8143-be7558a089c0',
        'X-LF-Api-Version': 'v1_23_0',
        'X-LF-Bucode': 'C20400',
        'X-LF-Channel': 'C2',
        'xweb_xhr': '1',
        'Host': 'gw2c-hw-open.longfor.com',
        'Accept-Language': 'zh-CN,zh;q=0.9'
    }


def request_json(method, url, **kwargs):
    resp = session.request(method, url, timeout=TIMEOUT, **kwargs)
    return safe_json(resp)


def get_sign_page_info(token):
    url = 'https://gw2c-hw-open.longfor.com/lmarketing-task-api-mvc-prod/openapi/task/v1/signature/page-info'
    headers = build_auth_headers(token, gaia_key=SIGN_GAIA_KEY)
    data = request_json('POST', url, headers=headers, json={'activity_no': SIGN_ACTIVITY_NO})
    return data


def print_sign_page_state(page_info, title='签到页状态'):
    data = page_info.get('data') or {}
    if not data:
        print(f'🌥️{title}：接口无数据')
        return

    sign_again_num = data.get('sign_again_num')
    day_rewards = data.get('day_received_rewards') or []
    seven_days = data.get('seven_days_signs') or []

    today_signed = False
    if seven_days:
        today = seven_days[0]
        today_signed = str(today.get('sign_status')) == '20'

    print(f'🌥️{title}：今日{"已签" if today_signed else "未签"}，剩余补签提示次数/连签计数字段={sign_again_num}')
    if day_rewards:
        rewards = []
        for item in day_rewards:
            rewards.append(f"{item.get('reward_num')}{'珑珠' if item.get('reward_type') == 10 else '成长值'}")
        print(f'🌥️今日已领：{"，".join(rewards)}')


def sign(token, risk_token=''):
    print_sign_page_state(get_sign_page_info(token), '签到前')

    url = 'https://gw2c-hw-open.longfor.com/lmarketing-task-api-mvc-prod/openapi/task/v1/signature/clock'
    headers = build_auth_headers(token, gaia_key=SIGN_GAIA_KEY, risk_token=risk_token)
    payload = {'activity_no': SIGN_ACTIVITY_NO}
    response = request_json('POST', url, headers=headers, json=payload)

    code = str(response.get('code', ''))
    message = response.get('message', '')
    data = response.get('data') or {}

    if code == '0000':
        if data.get('is_popup') == 1:
            rewards = []
            for item in data.get('reward_info', []):
                num = item.get('reward_num')
                reward_type = item.get('reward_type')
                reward_name = '珑珠' if reward_type == 10 else '成长值'
                rewards.append(f'{num}{reward_name}')
            print(f"✅签到成功：{', '.join(rewards) if rewards else '有奖励弹窗，但未解析到明细'}")
        else:
            print('✅签到成功：已签到/无弹窗')
    elif '已签到' in message:
        print('🌥️签到：今天已经签过了')
    elif '未登录' in message:
        print('⭕签到失败：token 已失效')
    elif '火爆' in message:
        print('⭕签到失败：活动火爆')
    elif '风控' in message or '风险' in message or 'captcha' in message.lower():
        print(f'⭕签到失败：疑似风控，message={message}')
        if not risk_token:
            print('💡当前脚本未提供 X-LF-DXRisk-Token；HAR 显示该值为动态指纹，不能再写死为 1')
    else:
        print(f'⭕签到失败：code={code} message={message} raw={json.dumps(response, ensure_ascii=False)[:500]}')

    print_sign_page_state(get_sign_page_info(token), '签到后')


def lotterysign(token):
    headers = {
        'Host': 'gw2c-hw-open.longfor.com',
        'Connection': 'keep-alive',
        'X-GAIA-API-KEY': LOTTERY_GAIA_KEY,
        'authtoken': token,
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/plain, */*',
        'X-LF-DXRisk-Source': '5',
        'bucode': 'C20400',
        'channel': 'C2',
        'X-LF-DXRisk-Token': '<SENSITIVE>',
        'Origin': 'https://llt.longfor.com',
        'Accept-Language': 'zh-CN,zh;q=0.9'
    }
    try:
        url = 'https://gw2c-hw-open.longfor.com/llt-gateway-prod/api/v1/activity/auth/lottery/sign'
        response = request_json('POST', url, headers=headers, json={
            'component_no': LOTTERY_COMPONENT_NO,
            'activity_no': LOTTERY_ACTIVITY_NO
        })
        if response.get('code') == '0000' or '已签到' in response.get('message', ''):
            print('🌥️抽奖任务：完成')
        elif '火爆' in response.get('message', ''):
            print('⭕抽奖火爆')
            return
        else:
            print(f"🌥️抽奖任务：{response.get('message') or response.get('code')}")

        url = (
            'https://gw2c-hw-open.longfor.com/llt-gateway-prod/api/v1/activity/auth/lottery/chance'
            f'?component_no={LOTTERY_COMPONENT_NO}&activity_no={LOTTERY_ACTIVITY_NO}'
        )
        response = request_json('GET', url, headers=headers)
        if response.get('code') == '0000':
            chance = int(response.get('data', {}).get('chance', 0) or 0)
            print(f'🌥️抽奖次数：{chance}次')
            if chance > 0:
                url = 'https://gw2c-hw-open.longfor.com/llt-gateway-prod/api/v1/activity/auth/lottery/click'
                response = request_json('POST', url, headers=headers, json={
                    'component_no': LOTTERY_COMPONENT_NO,
                    'activity_no': LOTTERY_ACTIVITY_NO,
                    'batch_no': ''
                })
                if response.get('code') == '0000':
                    prize = response.get('data', {})
                    print(f"🌈抽奖获得：{prize.get('prize_name')} x {prize.get('reward_num')}")
        else:
            print(f"🌥️抽奖次数查询失败：{response.get('message') or response.get('code')}")
    except Exception as e:
        print(f'lotterysign error: {e}')


def info(token):
    header = build_info_headers(token)
    try:
        url = 'https://gw2c-hw-open.longfor.com/supera/member/api/bff/pages/v1_23_0/v1/user-info'
        response = request_json('GET', url, headers=header)
        if response.get('code') == '0000':
            level = response['data'].get('level')
            growth_value = response['data'].get('growthValue')
            url = 'https://gw2c-hw-open.longfor.com/supera/member/api/bff/pages/v1_23_0/v2/user-lz-balance'
            response = request_json('GET', url, headers=header)
            balance = response.get('data', {}).get('balance')
            print(f'🌥️账户：{balance}珑珠')
            print(f'🌥️v{level}成长值：{growth_value}点')
        else:
            print(f'⭕会员信息查询失败：{json.dumps(response, ensure_ascii=False)[:300]}')
    except Exception as e:
        print(f'info error: {e}')


def parse_ck_line(line):
    parts = [x.strip() for x in line.split('#') if x.strip()]
    if len(parts) < 2:
        raise ValueError('变量格式错误，应为 手机号#token 或 手机号#token#risk_token')
    phone = parts[0]
    token = parts[1]
    risk_token = parts[2] if len(parts) >= 3 else ''
    return phone, token, risk_token


def main():
    ck = os.environ.get(ENVIRON, '').strip()
    if not ck:
        print('请设置变量')
        print('示例：lhtj="<PHONE>#lmToken[#risk_token]"')
        sys.exit()

    ck_run = [item.strip() for item in ck.split('\n') if item.strip()]
    print(f"{' ' * 10}꧁༺ {NAME} ༻꧂\n")
    for i, line in enumerate(ck_run, 1):
        print(f'\n----------- 🍺账号【{i}/{len(ck_run)}】执行🍺 -----------')
        try:
            phone, token, risk_token = parse_ck_line(line)
            print(f"📱：{phone[:3]}*****{phone[-3:]}")
            if risk_token:
                print('🌥️风控参数：已提供')
            else:
                print('🌥️风控参数：未提供（若签到失败，优先补这个）')
            sign(token, risk_token)
            lotterysign(token)
            info(token)
            time.sleep(random.randint(1, 2))
        except Exception as e:
            print(f'⭕账号处理异常：{e}')

    print('\n----------- 🎊 执 行  结 束 🎊 -----------')


if __name__ == '__main__':
    main()
