"""
cron: 1 56 23 * * *
new Env('电信口令兑换（纯版）');
"""
import os
import re
import sys
import ssl
import time
import json
import httpx
import base64
import random
import certifi
import aiohttp
import asyncio
import datetime
import requests
import binascii
from http import cookiejar
from Crypto.Cipher import AES
from Crypto.Cipher import DES3
from Crypto.PublicKey import RSA
from urllib.parse import quote
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Util.Padding import pad, unpad
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.ssl_ import create_urllib3_context

# ===================== 配置项 =====================
# 飞书机器人配置（环境变量：FSKEY）
FEISHU_WEBHOOK_KEY = os.getenv("FSKEY", "")
MAX_RETRIES = 3

# 口令配置
WELFARE_CODE = os.environ.get('dx_kl') or "三月遇惊喜"
WELFARE_CODES = WELFARE_CODE.split(',')

# ===================== 工具函数 =====================
class BlockAll(cookiejar.CookiePolicy):
    return_ok = set_ok = domain_return_ok = path_return_ok = lambda self, *args, **kwargs: False
    netscape = True
    rfc2965 = hide_cookie2 = False

def printn(m):
    print(f'\n{m}')

def print_time_log(m):
    print(f'⏰{str(datetime.datetime.now())[11:22]} 🌸{m}')

def mask_middle_four(value):
    """手机号脱敏：隐藏中间四位"""
    if isinstance(value, str) and len(value) >= 11:
        return value[:3] + "####" + value[-4:]
    raise ValueError("输入必须是11位以上的字符串")

def get_first_three(value):
    """获取脱敏后的手机号"""
    return mask_middle_four(value)

# ===================== 自定义表格打印函数（替代tabulate） =====================
def print_table(data, headers, tablefmt="grid"):
    if not data:
        print("暂无数据")
        return
    rows = []
    for item in data:
        row = []
        for header in headers:
            val = item.get(header, "")
            row.append(str(val) if val is not None else "")
        rows.append(row)
    col_widths = []
    for i, header in enumerate(headers):
        max_width = len(str(header))
        for row in rows:
            cell_width = len(str(row[i]))
            if cell_width > max_width:
                max_width = cell_width
        col_widths.append(max_width + 2)
    def print_separator():
        line = "+"
        for width in col_widths:
            line += "-" * width + "+"
        print(line)
    print_separator()
    header_line = "|"
    for i, header in enumerate(headers):
        header_line += f" {str(header).ljust(col_widths[i]-2)} |"
    print(header_line)
    print_separator()
    for row in rows:
        row_line = "|"
        for i, cell in enumerate(row):
            row_line += f" {str(cell).ljust(col_widths[i]-2)} |"
        print(row_line)
    print_separator()

# ===================== SSL适配器 =====================
ORIGIN_CIPHERS = ('DEFAULT@SECLEVEL=1')

class DESAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        CIPHERS = ORIGIN_CIPHERS.split(':')
        random.shuffle(CIPHERS)
        self.CIPHERS = ':'.join(CIPHERS) + ':!aNULL:!eNULL:!MD5'
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context(ciphers=self.CIPHERS)
        context.check_hostname = False
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        context = create_urllib3_context(ciphers=self.CIPHERS)
        context.check_hostname = False
        kwargs['ssl_context'] = context
        return super().proxy_manager_for(*args, **kwargs)

# ===================== 加密解密函数 =====================
key = b'1234567`90koiuyhgtfrdews'
iv = 8 * b'\0'

public_key_b64 = '''-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBkLT15ThVgz6/NOl6s8GNPofdWzWbCkWnkaAm7O2LjkM1H7dMvzkiqdxU02jamGRHLX/ZNMCXHnPcW/sDhiFCBN18qFvy8g6VYb9QtroI09e176s+ZCtiv7hbin2cCTj99iUpnEloZm19lwHyo69u5UMiPMpq0/XKBO8lYhN/gwIDAQAB
-----END PUBLIC KEY-----'''

public_key_data = '''-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC+ugG5A8cZ3FqUKDwM57GM4io6JGcStivT8UdGt67PEOihLZTw3P7371+N47PrmsCpnTRzbTgcupKtUv8ImZalYk65dU8rjC/ridwhw9ffW2LBwvkEnDkkKKRi2liWIItDftJVBiWOh17o6gfbPoNrWORcAdcbpk2L+udld5kZNwIDAQAB
-----END PUBLIC KEY-----'''

def ttt(hour, minute, second):
    date = datetime.datetime.now()
    date_zero = date.replace(hour=hour, minute=int(minute), second=int(second))
    return int(time.mktime(date_zero.timetuple()))

def encrypt(text):
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(text.encode(), DES3.block_size))
    return ciphertext.hex()

def decrypt(text):
    ciphertext = bytes.fromhex(text)
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext), DES3.block_size)
    return plaintext.decode()

def b64(plaintext):
    public_key = RSA.import_key(public_key_b64)
    cipher = PKCS1_v1_5.new(public_key)
    ciphertext = cipher.encrypt(plaintext.encode())
    return base64.b64encode(ciphertext).decode()

def encrypt_para(plaintext):
    if not isinstance(plaintext, str):
        plaintext = json.dumps(plaintext)
    public_key = RSA.import_key(public_key_data)
    cipher = PKCS1_v1_5.new(public_key)
    ciphertext = cipher.encrypt(plaintext.encode())
    return binascii.hexlify(ciphertext).decode()

def encode_phone(text):
    return ''.join(chr(ord(char) + 2) for char in text)

async def ascii_add_2(number_str):
    return ''.join(chr(ord(char) + 2) for char in number_str)

def ophone(t):
    key = b'34d7cb0bcdf07523'
    utf8_t = t.encode('utf8')
    cipher = AES.new(key, AES.MODE_ECB)
    ciphertext = cipher.encrypt(pad(utf8_t, AES.block_size))
    return ciphertext.hex()

# ===================== 飞书消息推送（纯文本，兼容所有机器人） =====================
def send_feishu_notification(content):
    if not FEISHU_WEBHOOK_KEY:
        print_time_log("FSKEY 未设置，跳过推送")
        return None
    feishu_url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{FEISHU_WEBHOOK_KEY}"
    payload = {
        "msg_type": "text",
        "content": {
            "text": content
        }
    }
    try:
        response = requests.post(feishu_url, json=payload, timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("code") == 0:
                print_time_log("✅ 飞书推送成功")
            else:
                print_time_log(f"❌ 推送失败：{res_json.get('msg')}")
        return response.json() if response else None
    except Exception as e:
        print_time_log(f"💥 推送异常：{e}")
        return None

def send(phone, content):
    msg = f"【电信口令兑换】{phone}\n{content}"
    return send_feishu_notification(msg)

# ===================== 登录认证 =====================
requests.packages.urllib3.disable_warnings()
ss = requests.Session()
ss.headers = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; 22081212C Build/TKQ1.220829.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.97 Mobile Safari/537.36",
    "Referer": "https://wapact.189.cn:9001/JinDouMall/JinDouMall_independentDetails.html"
}
ss.mount('https://', DESAdapter())
ss.cookies.set_policy(BlockAll())

load_token_file = '<SENSITIVE>'
try:
    with open(load_token_file, 'r') as f:
        load_token = json.load(f)
except:
    load_token = {}

def userLoginNormal(phone, password):
    alphabet = 'abcdef0123456789'
    uuid = [
        ''.join(random.sample(alphabet, 8)),
        ''.join(random.sample(alphabet, 4)),
        '4' + ''.join(random.sample(alphabet, 3)),
        ''.join(random.sample(alphabet, 4)),
        ''.join(random.sample(alphabet, 12))
    ]
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    loginAuthCipherAsymmertric = '<SENSITIVE>' + uuid[0] + uuid[1] + phone + timestamp + password[:6] + '0$$$0.'
    try:
        r = ss.post(
            'https://appgologin.189.cn:9031/login/client/userLoginNormal',
            json={
                "headerInfos": {
                    "code": "userLoginNormal",
                    "timestamp": timestamp,
                    "broadAccount": "",
                    "broadToken": "",
                    "clientType": "#10.5.0#channel50#iPhone 14 Pro Max#",
                    "shopId": "20002",
                    "source": "110003",
                    "sourcePassword": "<SENSITIVE>",
                    "token": "",
                    "userLoginName": encode_phone(phone)
                },
                "content": {
                    "attach": "test",
                    "fieldData": {
                        "loginType": "4",
                        "accountType": "",
                        "loginAuthCipherAsymmertric": b64(loginAuthCipherAsymmertric),
                        "deviceUid": uuid[0] + uuid[1] + uuid[2],
                        "phoneNum": encode_phone(phone),
                        "isChinatelecom": "<SENSITIVE>",
                        "systemVersion": "15.4.0",
                        "authentication": encode_phone(password)
                    }
                }
            }
        ).json()
    except:
        return False
    try:
        l = r.get('responseData', {}).get('data', {}).get('loginSuccessResult')
    except:
        return False
    if l:
        load_token[phone] = l
        with open(load_token_file, 'w') as f:
            json.dump(load_token, f)
        ticket = get_ticket(phone, l['userId'], l['token'])
        return ticket
    return False

def get_ticket(phone, userId, token):
    try:
        r = ss.post(
            'https://appgologin.189.cn:9031/map/clientXML',
            data='<Request><HeaderInfos><Code>getSingle</Code><Timestamp>' + datetime.datetime.now().strftime("%Y%m%d%H%M%S") +
                 '</Timestamp><BroadAccount></BroadAccount><BroadToken></BroadToken><ClientType>#9.6.1#channel50#iPhone 14 Pro Max#</ClientType>' +
                 '<ShopId>20002</ShopId><Source>110003</Source><SourcePassword>Sid98s</SourcePassword><Token>' + token +
                 '</Token><UserLoginName>' + phone + '</UserLoginName></HeaderInfos><Content><Attach>test</Attach>' +
                 '<FieldData><TargetId>' + encrypt(userId) + '</TargetId><Url>4a6862274835b451</Url></FieldData></Content></Request>',
            headers={'user-agent': 'CtClient;10.4.1;Android;13;22081212C;NTQzNzgx!#!MTgwNTg1'}
        )
        tk = re.findall('<Ticket>(.*?)</Ticket>', r.text)
        return decrypt(tk[0]) if tk else False
    except:
        return False

# ===================== 口令兑换核心 =====================
all_results = []

async def dxTask(phone, ticket, uid):
    retry_count = 0
    max_retries = 3
    results = []
    masked_phone = get_first_three(phone)

    def format_message(msg):
        if msg is None:
            return "响应为空"
        if isinstance(msg, dict):
            msg = msg.get('errorMsg') or msg.get('err') or str(msg)
        if "省编码校验失败" in msg:
            return "非本号省口令"
        elif "券码已使用" in msg:
            return "已使用"
        return msg

    while retry_count < max_retries:
        try:
            async with httpx.AsyncClient(verify=ssl.create_default_context(cafile=certifi.where()), timeout=60) as s:
                payload = {"appType": "02", "authCode": ticket, "loginType": "1"}
                s.headers.update({
                    'Accept': "application/json, text/plain, */*",
                    'Cache-Control': "no-cache",
                    'appType': "02",
                    'Content-Type': "application/json;charset=UTF-8",
                    'Origin': "https://wapact.189.cn:9001",
                    'Referer': "https://wapact.189.cn:9001/flcj1/",
                })
                response = await s.post('https://waphub.189.cn/yzf1/dispatch/login', data=json.dumps(payload))
                if response.status_code != 200:
                    retry_count +=1
                    continue
                login = response.json()
                if not login.get('success'):
                    retry_count +=1
                    continue
                useridv = login["result"]["userId"]
                sessionKey = login["result"]["sessionKey"]
                productNo = login["result"]["productNo"]
                s.headers.update({'userId': useridv, 'sessionKey': sessionKey})

                for code in WELFARE_CODES:
                    print_time_log(f"📱{masked_phone} 兑换口令: {code}")
                    convertpayload = {"userId": useridv, "code": code, "telephone": productNo, "isNewUser": "0"}
                    response = await s.post('https://waphub.189.cn/yzf1/welfare/convert', data=json.dumps(convertpayload))
                    convert = response.json()
                    if convert.get('success'):
                        results.append({'phone': masked_phone, 'code': code, 'status': '✓', 'message': '成功', 'time': datetime.datetime.now().strftime("%H:%M:%S")})
                        send(phone, f"{code} 兑换成功✨")
                        continue
                    provinceCode = login["result"]["provinceCode"]
                    provinceName = login["result"]["province"]
                    cityCode = login["result"]["cityCode"]
                    cityName = login["result"]["city"]
                    convertpayload2 = {
                        "code": code,"userId": useridv,"mob": productNo,
                        "provinceCode": provinceCode,"provinceName": provinceName,
                        "cityCode": cityCode,"cityName": cityName,"isNewUser": "0","source": "P201020101"
                    }
                    await asyncio.sleep(1)
                    response2 = await s.post('https://wapact.189.cn:9001/yzf/code/writeOff', data=json.dumps(convertpayload2))
                    convert2 = response2.json()
                    if convert2.get('success') or convert2.get('code') == 0:
                        results.append({'phone': masked_phone, 'code': code, 'status': '✓', 'message': '成功', 'time': datetime.datetime.now().strftime("%H:%M:%S")})
                        send(phone, f"{code} 兑换成功✨")
                    else:
                        results.append({'phone': masked_phone, 'code': code, 'status': '✗', 'message': format_message(convert2), 'time': datetime.datetime.now().strftime("%H:%M:%S")})

                await asyncio.sleep(3)
                welfarelistUrl = f"https://waphub.189.cn/yzf1/welfare/list?userId={useridv}&telephone={quote(productNo)}&state=0"
                response = await s.get(welfarelistUrl)
                if response.status_code == 200:
                    datavv = response.json()
                    if datavv.get('success') and datavv.get('result'):
                        for item in datavv['result']:
                            if '元' in item.get('name','') and '话费' in item.get('name',''):
                                taskId = item["id"]
                                print_time_log(f"📱{masked_phone} 领取: {item['name']}")
                                verifypayload = {"userId": useridv, "id": taskId, "telephone": productNo, "source": "1"}
                                await asyncio.sleep(1)
                                verify_resp = await s.post('https://waphub.189.cn/yzf1/welfare/verify', data=json.dumps(verifypayload))
                                verify = verify_resp.json()
                                if verify.get('success'):
                                    results.append({'phone': masked_phone, 'code': item['name'], 'status': '✓', 'message': '成功', 'time': datetime.datetime.now().strftime("%H:%M:%S")})
                                    send(phone, f"{item['name']} 领取成功✨")
                                else:
                                    results.append({'phone': masked_phone, 'code': item['name'], 'status': '✗', 'message': format_message(verify), 'time': datetime.datetime.now().strftime("%H:%M:%S")})
            break
        except Exception as e:
            retry_count +=1
            print_time_log(f"📱{masked_phone} 错误：{e}，重试 {retry_count}/{max_retries}")
            await asyncio.sleep(3*retry_count)
    if results:
        global all_results
        all_results.extend(results)

# ===================== 主函数 =====================
async def main():
    PHONES = os.environ.get('chinaTelecomAccount') or os.environ.get('PHONES1') or '''<PHONE>@899900'''
    phone_list = re.split(r'[\n&%!@]', PHONES)
    total_tasks = len(phone_list)
    print_time_log(f"💖检测到 {total_tasks} 个账号")
    semaphore = asyncio.Semaphore(5)

    async def process_account(phone_info):
        async with semaphore:
            value = re.split(r'[#,@]', phone_info.strip())
            if len(value) <2:
                print_time_log(f"格式错误: {phone_info}")
                return
            phone = value[0].strip()
            pwd = value[1].strip()
            masked_phone = get_first_three(phone)
            ticket = False
            if phone in load_token:
                print_time_log(f"📱{masked_phone} 使用缓存")
                ticket = get_ticket(phone, load_token[phone]['userId'], load_token[phone]['token'])
            if not ticket:
                print_time_log(f"📱{masked_phone} 密码登录")
                ticket = userLoginNormal(phone, pwd)
            if not ticket:
                print_time_log(f"📱{masked_phone} 登录失败")
                return
            await dxTask(phone, ticket, "")

    tasks = []
    for info in phone_list:
        if info.strip():
            tasks.append(process_account(info))
    await asyncio.gather(*tasks, return_exceptions=True)

    if all_results:
        # 纯文本汇总消息
        msg = "【电信口令兑换结果】\n"
        msg += f"口令：{', '.join(WELFARE_CODES)}\n\n"
        
        for r in all_results:
            msg += f"{r['phone']} | {r['code']} | {r['status']} | {r['message']}\n"
        
        ok = len([r for r in all_results if r['status']=='✓'])
        no = len(all_results)-ok
        msg += f"\n总计：成功 {ok} 次，失败 {no} 次"

        print("\n=== 兑换结果 ===")
        print_table(all_results, ['phone','code','status','message','time'])

        stats = {}
        for r in all_results:
            p = r['phone']
            if p not in stats: stats[p] = [0,0]
            if r['status'] == '✓': stats[p][0]+=1
            else: stats[p][1]+=1
        stat_data = [{'phone':p, '统计结果':f"成功{s[0]} 失败{s[1]}"} for p,s in stats.items()]
        print("\n=== 统计 ===")
        print_table(stat_data, ['phone','统计结果'])

        # 推送纯文本
        send_feishu_notification(msg)

# ===================== 入口 =====================
if __name__ == "__main__":
    print("开始执行兑换任务")
    asyncio.run(main())
    print("\n=== 任务完成 ===")