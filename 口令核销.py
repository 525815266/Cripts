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
import logging
import datetime
import requests
import binascii
import pandas as pd
from http import cookiejar
from Crypto.Cipher import AES
from Crypto.Cipher import DES3
from Crypto.PublicKey import RSA
from urllib.parse import quote 
from urllib.parse import urlparse
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Util.Padding import pad, unpad
from aiohttp import ClientSession, TCPConnector
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

# ===================== 完全复用你的配置 =====================
apptoken = ""
MAX_RETRIES = 3
RATE_LIMIT = 10 
runTime = 0
lock = asyncio.Lock()
event = asyncio.Event()
ready_count = 0  
diffValue = 0 
all_results = []
ip_list = []
load_token_file = '<SENSITIVE>'

# 环境变量（和你的代码完全一致）
WELFARE_CODE=os.environ.get('dx_kl') or "五一福利"
WELFARE_CODES = WELFARE_CODE.split(',') 
PHONES =os.environ.get('chinaTelecomAccount') or "<PHONE>#你的密码#你的uid"  # 这里可直接填账号

# 加载缓存Token
try:
    with open(load_token_file, 'r') as f:
        load_token = json.load(f)
except:
    load_token = {}

# 加密配置（完全复用）
key = b'1234567`90koiuyhgtfrdews'
iv = 8 * b'\0'
public_key_b64 = '''-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBkLT15ThVgz6/NOl6s8GNPofdWzWbCkWnkaAm7O2LjkM1H7dMvzkiqdxU02jamGRHLX/ZNMCXHnPcW/sDhiFCBN18qFvy8g6VYb9QtroI09e176s+ZCtiv7hbin2cCTj99iUpnEloZm19lwHyo69u5UMiPMpq0/XKBO8lYhN/gwIDAQAB
-----END PUBLIC KEY-----'''

public_key_data = '''-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC+ugG5A8cZ3FqUKDwM57GM4io6JGcStivT8UdGt67PEOihLZTw3P7371+N47PrmsCpnTRzbTgcupKtUv8ImZalYk65dU8rjC/ridwhw9ffW2LBwvkEnDkkKKRi2liWIItDftJVBiWOh17o6gfbPoNrWORcAdcbpk2L+udld5kZNwIDAQAB
-----END PUBLIC KEY-----'''

# ===================== 完全复用你的工具函数 =====================
def ttt(hour, minute, second):    
    date = datetime.datetime.now()
    date_zero = datetime.datetime.now().replace(
        year=date.year, 
        month=date.month, 
        day=date.day, 
        hour=hour, 
        minute=int(minute),
        second=int(second)
    )
    date_zero_time = int(time.mktime(date_zero.timetuple()))
    return date_zero_time

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
    
def encrypt_para2(plaintext):
    public_key = RSA.import_key(public_key_data)
    cipher = PKCS1_v1_5.new(public_key)
    ciphertext = cipher.encrypt(plaintext.encode())
    return ciphertext.hex()

def encrypt_para(plaintext):
    if not isinstance(plaintext, str):
        plaintext = json.dumps(plaintext)
    public_key = RSA.import_key(public_key_data)  
    cipher = PKCS1_v1_5.new(public_key)
    ciphertext = cipher.encrypt(plaintext.encode())
    return binascii.hexlify(ciphertext).decode() 

def encode_phone(text):
    encoded_chars = []
    for char in text:
        encoded_chars.append(chr(ord(char) + 2))
    return ''.join(encoded_chars)

def ophone(t):
    key = b'34d7cb0bcdf07523'
    utf8_key = key.decode('utf-8')
    utf8_t = t.encode('utf-8')
    cipher = AES.new(key, AES.MODE_ECB) 
    ciphertext = cipher.encrypt(pad(utf8_t, AES.block_size)) 
    return ciphertext.hex() 

def get_first_three(value):
    return mask_middle_four(value)

def mask_middle_four(value):
    if isinstance(value, str) and len(value) >= 11:
        return value[:3] + "####" + value[-4:]
    return value

def getApiTime(api_url):
    pass

def send(uid,content):
    r = requests.post(
        'https://wxpusher.zjiecode.com/api/send/message',
        json={"appToken":apptoken,"content":content,"contentType":1,"uids":[uid]}
    ).json()
    return r

# ===================== 完全复用你的登录逻辑 =====================
def userLoginNormal(phone,password):
    alphabet = 'abcdef0123456789'
    uuid = [
        ''.join(random.sample(alphabet, 8)),
        ''.join(random.sample(alphabet, 4)),
        '4'+''.join(random.sample(alphabet, 3)),
        ''.join(random.sample(alphabet, 4)),
        ''.join(random.sample(alphabet, 12))
    ]
    timestamp=datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    loginAuthCipherAsymmertric = '<SENSITIVE>' + uuid[0] + uuid[1] + phone + timestamp + password[:6] + '0$$$0.'
    r = ss.post(
        'https://appgologin.189.cn:9031/login/client/userLoginNormal',
        json={
            "headerInfos": {
                "code": "userLoginNormal", 
                "timestamp": timestamp, 
                "broadAccount": "", 
                "broadToken": "", 
                "clientType": "#11.3.0#channel50#iPhone 16 Pro Max#", 
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
        },
        verify=certifi.where()
    ).json()
    try:
        l = r.get('responseData', {}).get('data', {}).get('loginSuccessResult')
    except AttributeError:
        print("userLoginNormal对象为空或格式不正确，无法获取登录成功结果")
        l = None  
    if l:
        load_token[phone] = l
        with open(load_token_file, 'w') as f:
            json.dump(load_token, f)
        ticket = get_ticket(phone,l['userId'],l['token']) 
        return ticket
    return False

def get_ticket(phone,userId,token):
    r = ss.post(
        'https://appgologin.189.cn:9031/map/clientXML',
        data='<Request><HeaderInfos><Code>getSingle</Code><Timestamp>'+datetime.datetime.now().strftime("%Y%m%d%H%M%S")+'</Timestamp><BroadAccount></BroadAccount><BroadToken></BroadToken><ClientType>#9.6.1#channel50#iPhone 14 Pro Max#</ClientType><ShopId>20002</ShopId><Source>110003</Source><SourcePassword>Sid98s</SourcePassword><Token>'+token+'</Token><UserLoginName>'+phone+'</UserLoginName></HeaderInfos><Content><Attach>test</Attach><FieldData><TargetId>'+encrypt(userId)+'</TargetId><Url>4a6862274835b451</Url></FieldData></Content></Request>',
        headers={'user-agent': 'CtClient;10.4.1;Android;13;22081212C;NTQzNzgx!#!MTgwNTg1'},
        verify=certifi.where()
    )
    tk = re.findall('<Ticket>(.*?)</Ticket>',r.text)
    if len(tk) == 0:        
        return False
    return decrypt(tk[0])

# ===================== 完全复用你的异步/SSL配置 =====================
class RateLimiter:
    def __init__(self, rate_limit):
        self.rate_limit = rate_limit
        self.tokens = rate_limit
        self.updated_at = time.monotonic()

    async def acquire(self):
        while self.tokens < 1:
            self.add_new_tokens()
            await asyncio.sleep(0.1)
        self.tokens -= 1

    def add_new_tokens(self):
        now = time.monotonic()
        time_since_update = now - self.updated_at
        new_tokens = time_since_update * self.rate_limit
        if new_tokens > 1:
            self.tokens = min(self.tokens + new_tokens, self.rate_limit)
            self.updated_at = now

class AsyncSessionManager:
    def __init__(self, timeout=None):
        self.client = None
        self.timeout = timeout or httpx.Timeout(60.0, connect=30.0, read=30.0, write=30.0)

    async def __aenter__(self):
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        ssl_context.set_ciphers('DEFAULT@SECLEVEL=1')
        
        self.client = httpx.AsyncClient(
            verify=ssl_context,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            timeout=self.timeout
        )
        return self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

class BlockAll(cookiejar.CookiePolicy):
    return_ok = set_ok = domain_return_ok = path_return_ok = lambda self, *args, **kwargs: False
    netscape = True
    rfc2965 = hide_cookie2 = False
    
def printn(m):  
    print(f'\n{m}')

context = ssl.create_default_context()
context.set_ciphers('DEFAULT@SECLEVEL=1') 
context.check_hostname = False  
context.verify_mode = ssl.CERT_NONE 

class DESAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

requests.packages.urllib3.disable_warnings()
ss = requests.session()
ss.headers={
    "User-Agent":"Mozilla/5.0 (Linux; Android 13; 22081212C Build/TKQ1.220829.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.97 Mobile Safari/537.36",
    "Referer":"https://wapact.189.cn:9001/JinDouMall/JinDouMall_independentDetails.html"
}    
ss.mount('https://', DESAdapter())       
ss.cookies.set_policy(BlockAll())

# ===================== 核心：瑞数验证+完整登录链路（你的代码里的关键逻辑） =====================
async def getSign(ticket,SS,ckvalue):
    try:
        response_data =await SS.get('https://wapside.189.cn:9001/jt-sign/ssoHomLogin?ticket=' + ticket,cookies=ckvalue)
        response_data = response_data.json()
        if response_data.get('resoultCode') == '0':
            sign = response_data.get('sign')
            return sign
        else:
            print(f"获取sign失败[{response_data.get('resoultCode')}]: {response_data}")
    except Exception as e:
        print(e)
    return None

async def parse_cookies(ck,rsCK):
    cookies = {}
    for part in ck.split(';'):
        part = part.strip()
        if '=' in part:
            key, value = part.split('=', 1)
            if 'path' not in key and 'expires' not in key and 'Secure' not in key and 'SameSite' not in key:
                cookies[key] = value
    cookies["yiUIIlbdQT3fO"] = rsCK           
    return cookies

async def xbkset_request(ss,url):
    response=await ss.get(url)
    if response.status_code == 200:
        rsCK = re.findall('SESSION=([^;]+)',response.headers['Set-Cookie'])[0]
        return  response.json(), rsCK
    else:
        print("瑞数失败")   
        return  response.json(),None
    return  response.json(), None

async def addVotingRecord(session,phone, ticket):
        codeValue="ACTCODE20241212V8LHJF5Y"
        restfulurl="https://wapact.189.cn:9001/mas-pub-web/spm/restful"
        restfulurl+=f"?method=setRedisPagesJson&activityCode={codeValue}&pageId=&activityId=&phoneNum=&previewType=&subPageLinkCode=&isPreview="
        session.headers.update({
            'activityCode': codeValue,
            'yxai': codeValue,
            'ticket': ticket,
            })
        dataxb, SESSION = await xbkset_request(session, restfulurl)
        
        url = "https://wapact.189.cn:9001/mas-pub-web/component/addVotingRecord"
        payload = {
        "groupId": 2067,
        "contentId": "1b7b42c3a7824005bad832d3a2d925a5"
        }
        headers = {
        'Host': "wapact.189.cn:9001",
        'User-Agent': "CtClient;11.3.0;Android;12;Redmi K30 Pro;MDM3MzE2!#!MTMxODk",
        'Accept': "application/json, text/plain, */*",
        'Accept-Encoding': "gzip, deflate, br, zstd",
        'Content-Type': "application/json",
        'sec-ch-ua-platform': "\"Android\"",
        'activityCode': "ACTCODE20241212V8LHJF5Y",
        'sec-ch-ua': "\"Android WebView\";v=\"131\", \"Chromium\";v=\"131\", \"Not_A Brand\";v=\"24\"",
        'sec-ch-ua-mobile': "<SENSITIVE>",
        'id': "",
        'wyopenid': "",
        'Content-Type': "application/json;charset=UTF-8",
        'activityId': "",
        'ticket': str(ticket),
        'wyDataStr': "",
        'masEnv': "android",
        'yxai': "ACTCODE20241212V8LHJF5Y",
        'wycorpId': "",
        'Origin': "https://wapact.189.cn:9001",
        'X-Requested-With': "com.ct.client",
        'Sec-Fetch-Site': "same-origin",
        'Sec-Fetch-Mode': "cors",
        'Sec-Fetch-Dest': "empty",
        'Accept-Language': "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        'Cookie': f'SESSION={SESSION}'
        }
        res=await session.post(url, data=json.dumps(payload), headers=headers)
        if res.status_code == 200:
            res = res.json()
            if res.get("code") is not None:
                if res.get("msg") is not None:
                    print("👍")
                    pass
        time.sleep(3)

async def AI_Yun1(phone, ticket):
    global diffValue, ready_count
    timeout_config = httpx.Timeout(30.0, connect=60.0, read=60.0) 
    async with AsyncSessionManager( timeout=timeout_config) as session:
        await addVotingRecord(session,phone, ticket)
        await asyncio.sleep(0.1) 

async def ascii_add_2(number_str):
    transformed = ''.join(chr(ord(char) + 2) for char in number_str)
    return transformed

# ===================== 核心修改：纯福利查询函数（保留你的完整登录链路） =====================
# ===================== 查询 + 自动领取 =====================
async def query_welfare_only(phone, ticket, phoneV):
    masked_phone = mask_middle_four(phone)
    print(f"\n[{masked_phone}] 开始查询并自动领取福利...")
    
    try:
        async with AsyncSessionManager() as s:
            # 瑞数验证
            currtime = datetime.datetime.now()
            if currtime < datetime.datetime.strptime("2025-02-21 00:00:00", "%Y-%m-%d %H:%M:%S"):
                await AI_Yun1(phone, ticket)
            
            # dispatch 登录
            payload = {
                "appType": "02",
                "authCode": ticket,
                "loginType": "1"
            }
            s.headers.update({
                'Accept': "application/json, text/plain, */*",
                'Cache-Control': "no-cache",
                'appType': "02",
                'userId': "",
                'Content-Type': "application/json;charset=UTF-8",
                'sessionKey': "",
                'Origin': "https://wapact.189.cn:9001",
                'Referer': "https://wapact.189.cn:9001/flcj1/",
                'User-Agent': "CtClient;11.3.0;Android;12;Redmi K30 Pro;MDM3MzE2!#!MTMxODk"
            })

            response=await s.post('https://wapact.189.cn:9001/yzf1/dispatch/login', data=json.dumps(payload))
            if response.status_code == 200:
                login = response.json()
                if login.get('success') == True:
                    useridv = login["result"]["userId"]
                    sessionKey = login["result"]["sessionKey"]
                    productNo = login["result"]["productNo"]

                    s.headers.update({
                        'userId': useridv,
                        'sessionKey': sessionKey,
                    })

                    # 查询福利列表
                    welfarelistUrl = f"https://waphub.189.cn/yzf1/welfare/list?userId={useridv}&telephone={quote(productNo)}&state=0"
                    await asyncio.sleep(1)
                    response = await s.get(welfarelistUrl)

                    if response.status_code == 200:
                        datavv = response.json()
                        if datavv.get('success') == True and datavv.get('result'):
                            welfare_list = datavv['result']
                            print(f"[{masked_phone}] 查到 {len(welfare_list)} 个可领取福利")

                            # ===================== 自动领取 =====================
                            for welfare in welfare_list:
                                welfare_id = welfare.get("id")
                                welfare_name = welfare.get("name", "未知福利")
                                print(f"[{masked_phone}] 准备领取: {welfare_name} (ID: {welfare_id})")

                                if not welfare_id:
                                    continue

                                # 领取接口
                                verifypayload = {
                                    "userId": useridv,
                                    "id": welfare_id,
                                    "telephone": productNo,
                                    "source": "1"
                                }

                                await asyncio.sleep(1)
                                res = await s.post(
                                    "https://wapact.189.cn:9001/yzf1/welfare/verify",
                                    data=json.dumps(verifypayload)
                                )

                                result = res.json()
                                if result.get("success") == True:
                                    print(f"✅ [{masked_phone}] 领取成功: {welfare_name}")
                                else:
                                    msg = result.get("errorMsg", "未知错误")
                                    print(f"❌ [{masked_phone}] 领取失败: {msg}")

                        else:
                            print(f"[{masked_phone}] 未查到可领福利")
    except Exception as e:
        print(f"[{masked_phone}] 异常: {e}")

# ===================== 主函数：纯福利查询（复用你的账号处理逻辑） =====================
async def main():
    tasks = []
    phone_list = PHONES.split('&') 
    total_tasks = len(phone_list)
    print(f"总查询任务数：{total_tasks}")
    semaphore = asyncio.Semaphore(5)
    
    async def wrapped_task(phone, ticket, productNo, phoneV):
        async with semaphore:
            await query_welfare_only(phone, ticket, phoneV)
    
    for index, phoneV in enumerate(phone_list, start=1):
        value = re.split(r'[#]', phoneV)
        print(f"\n正在处理查询任务 {index}/{total_tasks}")
        
        if len(value)<2:
            print('格式错误:', phoneV)
            continue
            
        phone, password = value[0], value[1]
        ticket = False 
        
        # 复用你的缓存登录逻辑
        if phone in load_token:
            printn(f'{get_first_three(phone)} 使用缓存登录')
            ticket = get_ticket(phone, load_token[phone]['userId'], load_token[phone]['token'])
        
        # 复用你的密码登录逻辑
        if not ticket:
            printn(f'{get_first_three(phone)} 使用密码登录')
            ticket = userLoginNormal(phone, password)
        
        # 登录成功则查询福利
        if ticket:
            productNo = await ascii_add_2(phone)
            tasks.append(asyncio.create_task(wrapped_task(phone, ticket, productNo, phoneV)))
            await asyncio.sleep(1)
        else:
            printn(f'{phone} 登录失败，跳过查询')
    
    # 执行所有查询任务
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # 输出最终结果
    if all_results:
        df = pd.DataFrame(all_results)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', 50)
        
        print("\n" + "="*100)
        print("福利查询最终结果汇总")
        print("="*100)
        print(df.to_string(index=False))
        
        # 保存结果
        csv_filename = f"电信福利查询结果_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存到: {csv_filename}")
    else:
        print("\n未查询到任何福利数据")

# ===================== 运行入口 =====================
if __name__ == "__main__":
    # 日志配置（和你的代码一致）
    log_filename = f'.电信等级权益日志.log'
    logging.basicConfig(
        level=logging.CRITICAL,
        format='%(asctime)s -- %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        filename=log_filename, 
        filemode='a', 
        encoding='utf-8'
    )
    logger = logging.getLogger(__name__)
    
    # 运行主函数
    asyncio.run(main())