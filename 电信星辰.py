"""
本电信活动脚本仅用于学习交流，不用于商业及非法用途，使用方自行承担使用风险，与提供方无关。yh-yc
"""
import os
import ssl
import re
import json
import time
import random
import string
import base64
import hashlib
import datetime
import requests
from hashlib import md5
from http import cookiejar
from Crypto.Cipher import AES, DES3
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Util.Padding import pad, unpad

try:
    from notify import send
except ImportError:
    def send(title, content):
        pass
CHANNEL_ID = "156000007810"
CACHE_FILE = "chinaTelecom_cache.json"
ACCOUNTS_STR = os.environ.get("CAILING_ACCOUNTS") or os.environ.get("chinaTelecomAccount") or ""
# 品赞代理配置
PROXY_PACKAGE_NO = ""  # 套餐购买编号
PROXY_EXTRACT_KEY = ""  # 套餐提取密匙
USE_PROXY = False  # 是否使用代理（抽奖时）
USE_PROXY_FOR_REDEEM = False  # 是否在兑换时使用代理（新增开关）
REDEEM_COUNT = 1  # 兑换次数（测试用的10次，现在用1）
# ====================================
context = ssl.create_default_context()
context.set_ciphers('DEFAULT@SECLEVEL=1')
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE

class DESAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

class BlockAll(cookiejar.CookiePolicy):
    return_ok = set_ok = domain_return_ok = path_return_ok = lambda self, *args, **kwargs: False
    netscape = True
    rfc2965 = hide_cookie2 = False

key = b'1234567`90koiuyhgtfrdews'
iv = 8 * b'\0'
public_key_b64 = '''-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBkLT15ThVgz6/NOl6s8GNPofdWzWbCkWnkaAm7O2LjkM1H7dMvzkiqdxU02jamGRHLX/ZNMCXHnPcW/sDhiFCBN18qFvy8g6VYb9QtroI09e176s+ZCtiv7hbin2cCTj99iUpnEloZm19lwHyo69u5UMiPMpq0/XKBO8lYhN/gwIDAQAB
-----END PUBLIC KEY-----'''

requests.packages.urllib3.disable_warnings()
ss = requests.session()
ss.headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 13; 22081212C) AppleWebKit/537.36"}
ss.mount('https://', DESAdapter())
ss.cookies.set_policy(BlockAll())

def encrypt_3des(text):
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(text.encode(), DES3.block_size))
    return ciphertext.hex()

def decrypt_3des(text):
    ciphertext = bytes.fromhex(text)
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext), DES3.block_size)
    return plaintext.decode()

def b64_rsa(plaintext):
    public_key = RSA.import_key(public_key_b64)
    cipher = PKCS1_v1_5.new(public_key)
    ciphertext = cipher.encrypt(plaintext.encode())
    return base64.b64encode(ciphertext).decode()

def encode_phone(text):
    return ''.join(chr(ord(char) + 2) for char in text)

def generate_random_string(length=16):
    return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))

def md5_hash(data):
    return hashlib.md5(data.encode('utf-8')).hexdigest()

def encryptmd5(timestamp, randomnum):
    md5_e = md5_hash(str(timestamp))
    base64_encoded = base64.b64encode((md5_e + randomnum).encode()).decode()
    return md5_hash(base64_encoded + randomnum)

def encrypt_request(data, t, e, i):
    n = json.dumps({k: v for k, v in data.items() if v is not None}, separators=(',', ':'))
    encoded_t = base64.b64encode(t.encode()).decode()
    encoded_e = base64.b64encode(e.encode()).decode()
    s = md5((encoded_t + md5(e.encode()).hexdigest() + i).encode()).hexdigest()[:16]
    o = md5((encoded_e + md5(t.encode()).hexdigest() + i).encode()).hexdigest()[:16]
    cipher = AES.new(s.encode(), AES.MODE_CBC, iv=o.encode())
    padded_data = pad(n.encode(), AES.block_size)
    encrypted_data = cipher.encrypt(padded_data)
    return base64.b64encode(encrypted_data).decode()

def decrypt_response(encrypted_base64, t, e, i):
    encoded_t = base64.b64encode(t.encode()).decode()
    encoded_e = base64.b64encode(e.encode()).decode()
    n = md5((encoded_e + i + md5(t.encode()).hexdigest()).encode()).hexdigest()[:16]
    s = md5((encoded_t + i + md5(e.encode()).hexdigest()).encode()).hexdigest()[:16]
    cipher = AES.new(n.encode(), AES.MODE_CBC, iv=s.encode())
    encrypted_data = base64.b64decode(encrypted_base64)
    decrypted_data = cipher.decrypt(encrypted_data)
    unpadded_data = unpad(decrypted_data, AES.block_size)
    return json.loads(unpadded_data.decode())

def parse_accounts(accounts_str: str) -> list:
    accounts = []
    for part in accounts_str.replace("\n", "&").replace("\r", "").split("&"):
        part = part.strip()
        if "#" in part:
            phone, pwd = part.split("#", 1)
        elif "@" in part:
            phone, pwd = part.split("@", 1)
        else:
            continue
        phone, pwd = phone.strip(), pwd.strip()
        if phone and pwd:
            accounts.append((phone, pwd))
    return accounts

def userLoginNormal(phone, password, cache: dict = None, force_login: bool = False):
    if not force_login and cache is not None:
        cached = get_cached_login(phone, cache)
        if cached:
            print(f"  ✓ 使用缓存登录 (更新时间: {cached.get('updateTime', '未知')})")
            return cached

    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    rdmstr = ''.join(random.choices('0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ', k=16))
    login_cipher = f'iPhone 14 15.4.{rdmstr[:12]}{phone}{timestamp}{password}0$$$0.'
    payload = {
        "headerInfos": {
            "code": "userLoginNormal", "timestamp": timestamp, "broadAccount": "", "broadToken": "",
            "clientType": "#11.3.0#channel50#iPhone 14 Pro Max#", "shopId": "20002",
            "source": "110003", "sourcePassword": "<SENSITIVE>", "token": "", "userLoginName": encode_phone(phone)
        },
        "content": {
            "attach": "test",
            "fieldData": {
                "loginType": "4", "accountType": "", "loginAuthCipherAsymmertric": b64_rsa(login_cipher),
                "deviceUid": rdmstr, "phoneNum": encode_phone(phone), "isChinatelecom": "<SENSITIVE>",
                "systemVersion": "15.4.0", "authentication": encode_phone(password)
            }
        }
    }
    r = ss.post('https://appgologin.189.cn:9031/login/client/userLoginNormal', json=payload)
    data = r.json()
    response_data = data.get('responseData')
    if response_data:
        data_inner = response_data.get('data')
        if data_inner:
            login_result = data_inner.get('loginSuccessResult')
            if login_result:
                if cache is not None:
                    update_cache_login(phone, login_result, cache)
                    print(f"  ✓ 登录成功并更新缓存")
                return login_result
    print(f"登录响应: {data}")
    return None

def get_ticket(phone, userId, token):
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    xml_data = f'<Request><HeaderInfos><Code>getSingle</Code><Timestamp>{timestamp}</Timestamp>' \
               f'<BroadAccount></BroadAccount><BroadToken></BroadToken>' \
               f'<ClientType>#9.6.1#channel50#iPhone 14 Pro Max#</ClientType><ShopId>20002</ShopId>' \
               f'<Source>110003</Source><SourcePassword>Sid98s</SourcePassword><Token>{token}</Token>' \
               f'<UserLoginName>{phone}</UserLoginName></HeaderInfos><Content><Attach>test</Attach>' \
               f'<FieldData><TargetId>{encrypt_3des(userId)}</TargetId>' \
               f'<Url>4a6862274835b451</Url></FieldData></Content></Request>'
    r = ss.post('https://appgologin.189.cn:9031/map/clientXML', data=xml_data,
                headers={'user-agent': 'CtClient;10.4.1;Android;13;22081212C;NTQzNzgx!#!MTgwNTg1'})

    if '过期' in r.text or '校验错误' in r.text:
        return None, True 

    tk = re.findall('<Ticket>(.*?)</Ticket>', r.text)
    if tk:
        return decrypt_3des(tk[0]), False  
    return None, False

def sso_login_v2(ticket):
    payload = {"portal": "45", "channelId": CHANNEL_ID, "ticket": ticket}
    headers = {
        'User-Agent': "CtClient;11.3.0;Android;12;Redmi K60;NTU1NTU1!#!MTU1NTU",
        'Content-Type': "application/json"
    }
    r = requests.post("https://ai.imusic.cn/vapi/vue_login/sso_login_v2",
                      data=json.dumps(payload), headers=headers)
    if r.status_code == 200:
        data = r.json()
        if data.get("token"):
            return data.get("token"), r.cookies.get_dict()
    return None, None


def load_cache() -> dict:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"⚠ 加载缓存失败: {str(e)}")
        return {}


def save_cache(cache: dict):
    """保存登录缓存"""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠ 保存缓存失败: {str(e)}")


def get_cached_login(phone: str, cache: dict) -> dict:
    return cache.get(phone)


def update_cache_login(phone: str, login_result: dict, cache: dict):
    cache[phone] = {
        **login_result, 
        'updateTime': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 额外添加更新时间
    }
    save_cache(cache)


# ============= 品赞代理相关函数 =============
def get_proxy_ip() -> str:
    """获取品赞代理IP"""
    if not USE_PROXY:
        return None

    try:
        url = "https://service.ipzan.com/core-extract"
        params = {
            "no": PROXY_PACKAGE_NO,
            "secret": PROXY_EXTRACT_KEY,
            "num": 1,
            "minute": 1,
            "pool": "quality",
            "protocol": 1,
            "mode": "whitelist",
            "format": "txt",
            "repeat": 1,
        }
        response = requests.get(url, params=params, timeout=10)
        ip = response.text.strip()
        return ip
    except Exception as e:
        print(f"  ⚠ 获取代理IP失败: {str(e)}")
        return None


def validate_proxy_ip(ip: str) -> bool:
    if not ip:
        return False
    pattern = r'^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?):(\d{1,5})$'
    return bool(re.match(pattern, ip))
# ============================================


class InviteAPI:
    """API"""
    BASE_URL = "https://ai.imusic.cn"

    def __init__(self, token: str, cookies: dict = None):
        self.token = token
        self.session = requests.Session()
        self.session.mount('https://', DESAdapter())
        if cookies:
            self.session.cookies.update(cookies)
        self.session.headers.update({
            "User-Agent": "CtClient;11.3.0;Android;12;Redmi K60;NTU1NTU1!#!MTU1NTU",
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Origin": self.BASE_URL,
            "Authorization": f"Bearer {token}",
            "Referer": f"{self.BASE_URL}/h5v/fusion/2026-new-year?ca=dljA&cc={CHANNEL_ID}&isshare=0&utm_scha=utm_ch-010001002009.utm_sch-100103-1.utm_af-1000000037.utm_as-273035500001.utm_sd1-default",
            "X-Requested-With": "com.ct.client",
            "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Android WebView";v="140"',
            "sec-ch-ua-mobile": "<SENSITIVE>",
            "sec-ch-ua-platform": '"Android"',
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
        })

    def get_share_task_code(self, mobile: str, activity_id: str = "ai090") -> dict:
        params = {
            "apiName": "act/ActApi/doubleEggGetShareTaskCode",
            "mobile": mobile,
            "activityId": activity_id
        }
        return self.request_encrypted("/hapi/en/api", params)

    def get_share_task_info(self, mobile: str, task_code: str) -> dict:
        params = {
            "apiName": "act/ActApi/doubleEggGetShareTaskInfo",
            "mobile": mobile,
            "taskCode": task_code
        }
        return self.request_encrypted("/hapi/en/api", params)

    def share_lottery(self, mobile: str, task_code: str) -> dict:
        params = {
            "apiName": "act/ActApi/doubleEggSpringShareLottery",
            "taskCode": task_code,
            "mobile": mobile
        }
        return self.request_encrypted("/hapi/en/api", params)

    def first_login_lottery(self, mobile: str, activity_id: str = "ai090") -> dict:
        params = {
            "apiName": "act/ActApi/loginTaskFinish",
            "mobile": mobile,
            "activityId": activity_id
        }
        return self.request_encrypted("/hapi/en/api", params)

    def request_plain(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.BASE_URL}{endpoint}"
        response = self.session.post(url, params=params, timeout=30)
        return response.json()

    def request_encrypted(self, endpoint: str, params: dict, proxies: dict = None) -> dict:
        self.session.headers["imencrypt"] = "1"
        imrandomnum = generate_random_string(16)
        imtimestamp = str(int(time.time() * 1000))
        imencryptkey = encryptmd5(imtimestamp, imrandomnum)

        form_data = {"channelId": CHANNEL_ID, "portal": "45"}
        form_data.update(params)
        encrypted_form = encrypt_request(form_data, imrandomnum, imtimestamp, imencryptkey)

        headers = {
            "imencryptkey": imencryptkey,
            "imrandomnum": imrandomnum,
            "imtimestamp": imtimestamp,
        }
        url = f"{self.BASE_URL}{endpoint}"

        if proxies:
            response = self.session.post(url, params={"formData": encrypted_form}, headers=headers, timeout=30, proxies=proxies)
        else:
            response = self.session.post(url, params={"formData": encrypted_form}, headers=headers, timeout=30)

        new_auth = response.headers.get("Authorization")
        if new_auth:
            self.token = new_auth
            self.session.headers["Authorization"] = f"Bearer {new_auth}"

        try:
            return decrypt_response(response.text, imrandomnum, imtimestamp, imencryptkey)
        except:
            return {"raw": response.text}

    def get_user_info(self, mobile: str) -> dict:
        params = {"channelId": CHANNEL_ID, "portal": "45", "mobile": mobile}
        return self.request_plain("/vapi/new_member/get_user_info", params)

    def check_user_state(self, mobile: str) -> dict:
        params = {"mobile": mobile, "is4G": "1", "is5G": "1", "isDX": "1", "channelId": CHANNEL_ID, "portal": "45"}
        return self.request_plain("/vapi/vrbt/check_user_state", params)

    def send_stat_message(self, mobile: str, actname: str, actparam: str) -> dict:
        params = {
            "mobile": mobile,
            "actname": actname,
            "actparam": actparam
        }
        return self.request_encrypted("/vapi/vue_stat/sendMessage", params)



    def do_egg_lottery(self, mobile: str, activity_id: str = "1611", use_proxy: bool = False, max_retries: int = 2) -> dict:
        params = {
            "activityId": activity_id,
            "mobile": mobile,
            "apiName": "act/ActApi/doubleEggLottery"
        }

        # 如果需要使用代理，尝试多次
        for retry in range(max_retries):
            proxies = None

            if use_proxy and USE_PROXY:
                proxy_ip = get_proxy_ip()
                if proxy_ip and validate_proxy_ip(proxy_ip):
                    proxies = {
                        'http': f'http://{proxy_ip}',
                        'https': f'http://{proxy_ip}'
                    }
                    if retry == 0:
                        print(f"  🔄 使用代理: {proxy_ip}")
                    else:
                        print(f"  🔄 重试 {retry}/{max_retries-1} - 使用新代理: {proxy_ip}")
                else:
                    print(f"  ⚠ 代理IP无效，使用本地IP")

            try:
                return self.request_encrypted("/hapi/en/api", params, proxies=proxies)
            except (requests.exceptions.ProxyError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.ReadTimeout,
                    requests.exceptions.Timeout) as e:
                if retry < max_retries - 1:
                    print(f"  ⚠ 代理连接失败，正在重试...")
                    time.sleep(1)  # 等待1秒后重试
                    continue
                else:
                    print(f"  ⚠ 代理多次失败，使用本地IP")
                    return self.request_encrypted("/hapi/en/api", params, proxies=None)
            except Exception as e:
                raise e

        return self.request_encrypted("/hapi/en/api", params, proxies=None)

    def get_lottery_times(self, mobile: str, activity_id: str = "1611") -> dict:
        """获取抽奖次数"""
        params = {
            "mobile": mobile,
            "activityId": activity_id
        }
        return self.request_encrypted("/hapi/activity/au/get_act_lottery_times", params)

    def query_new_year_templates(self, page_no: int = 1, page_size: int = 500) -> dict:
        params = {
            "pageNo": page_no,
            "pageSize": page_size,
            "activityId": "0090_2",
            "apiName": "diy/DiyVideoApi/queryActRecommendTemplateList",
            "channelId": CHANNEL_ID,
            "portal": "45"
        }
        return self.request_plain("/hapi/de/api", params)

    def make_new_year_video(self, mobile: str, template_data: dict) -> dict:
        import random

        template_id = template_data.get("templateId", "")
        template_conf_id = template_data.get("configId", "") or template_data.get("templateConfId", "")
        video_name = template_data.get("videoName", "")
        user_words = template_data.get("userWords", "")
        arrange_id = template_data.get("arrangeId", "")

        random_suffix = random.randint(100000, 999999)
        video_name_with_suffix = f"{video_name}{random_suffix}"

        params = {
            "mobile": mobile,
            "openId": "",
            "background": template_id,
            "userPhotos": "",
            "userWords": user_words,
            "templateName": "",
            "videoName": video_name_with_suffix,
            "templateId": template_id,
            "templateConfId": template_conf_id,
            "aid": "ai090",
            "inviterMobile": "",
            "arrangeId": arrange_id,
            "autoOrderUgc": 0,
            "aiGatewayImagMakeId": "",
            "fromType": "",
            "sessionId": ""
        }
        return self.request_encrypted("/hapi/diy_video/au/template_make_add_v2", params)

    def ai_agent_chat(self, mobile: str, content: str, agent_id: str = "", from_act: str = "cny", session_id: str = "") -> dict:
        params = {
            "apiName": "diy/AiAgentChatApi/aiAgentChat",
            "content": content,
            "mobile": mobile,
            "agentId": agent_id,
            "fromAct": from_act,
            "sessionId": session_id
        }
        return self.request_encrypted("/hapi/en/api", params)

    def control_confirm_submit(self, mobile: str, session_id: str, confirm_id: int, text_list: list,
                               agent_id: str = "text_to_image", from_act: str = "cny") -> dict:
        params = {
            "apiName": "diy/AiAgentChatApi/controlConfirmSubmit",
            "content": "",
            "mobile": mobile,
            "sessionId": session_id,
            "confirmId": confirm_id,
            "channelId": "",
            "portal": "45",
            "agentId": agent_id,
            "triggerSource": "card_submit",
            "textList": text_list,
            "fromAct": from_act
        }
        return self.request_encrypted("/hapi/en/api", params)

    def check_ai_agent_result(self, mobile: str, task_id: str) -> dict:
        params = {
            "apiName": "diy/AiAgentChatApi/checkAiAgentResult",
            "mobile": mobile,
            "taskId": task_id
        }
        return self.request_encrypted("/hapi/en/api", params)

    def query_person_tasks(self, mobile: str, activity_id: str = "ai090") -> dict:
        params = {
            "apiName": "act/ActApi/queryPersonTasks",
            "mobile": mobile,
            "activityId": activity_id
        }
        return self.request_encrypted("/hapi/en/api", params)

    def query_red_packet_balance(self, mobile: str, activity_id: str = "1611") -> dict:
        params = {
            "apiName": "act/ActApi/doubleEggCostRedeemInfo",
            "mobile": mobile,
            "activityId": activity_id
        }
        return self.request_encrypted("/hapi/en/api", params)

    def redeem_red_packet(self, mobile: str, cost_value: float, activity_id: str = "1611", use_proxy: bool = False) -> dict:
        params = {
            "apiName": "act/ActApi/doubleEggCostRedeem",
            "mobile": mobile,
            "activityId": activity_id,
            "costValue": cost_value
        }

        proxies = None
        if use_proxy and USE_PROXY:
            proxy_ip = get_proxy_ip()
            if proxy_ip and validate_proxy_ip(proxy_ip):
                proxies = {
                    'http': f'http://{proxy_ip}',
                    'https': f'http://{proxy_ip}'
                }

        return self.request_encrypted("/hapi/en/api", params, proxies=proxies)


def process_new_year_lottery(phone: str, password: str, account_idx: int = 0, total_accounts: int = 0, cache: dict = None):
    """处理2026星辰活动（任务1+任务2+抽奖）- 支持缓存"""
    print(f"\n{'='*50}")
    print(f"处理账号: {phone} ({account_idx}/{total_accounts})")
    print(f"活动: 2026电信星辰")
    print(f"{'='*50}")

    fail_summary = {"phone": phone, "success": False, "awards": [], "red_packet": 0.0, "redeemed": "0", "balance": "0"}

    print("\n[1] 账密登录...")
    login_result = userLoginNormal(phone, password, cache=cache)
    if not login_result:
        print("❌ 登录失败")
        return fail_summary

    print("\n[2] 获取ticket...")
    ticket, is_expired = get_ticket(phone, login_result['userId'], login_result['token'])

    if is_expired:
        print("  ⚠ Token已过期，重新登录...")
        login_result = userLoginNormal(phone, password, cache=cache, force_login=True)
        if not login_result:
            print("❌ 重新登录失败")
            return fail_summary
        print("  ✓ 重新登录成功")

        ticket, is_expired = get_ticket(phone, login_result['userId'], login_result['token'])

    if not ticket:
        print("❌ 获取ticket失败")
        return fail_summary
    print("✓ 获取ticket成功")

    print("\n[3] SSO登录...")
    token, cookies = sso_login_v2(ticket)
    if not token:
        print("❌ SSO登录失败")
        return fail_summary
    print(f"✓ SSO登录成功")

    api = InviteAPI(token, cookies)

    print("\n[4] 查询任务状态...")
    tasks_result = api.query_person_tasks(phone)

    task1_completed = False 
    task2_completed = False  
    first_login_completed = False  

    if tasks_result.get("code") == "0000":
        tasks = tasks_result.get("data", {}).get("tasks", [])
        print(f"✓ 获取到 {len(tasks)} 个任务\n")

        for task in tasks:
            task_name = task.get("taskName", "")
            task_type = task.get("taskType", "")
            task_state = task.get("taskState", 0)  # 0=未完成, 1=已完成
            current_progress = task.get("currentProgress", 0)
            target_progress = task.get("targetProgress", 0)
            lottery_count = task.get("lotteryCount", 0)

            state_text = "✓ 已完成" if task_state == 1 else "○ 未完成"
            print(f"  {state_text} {task_name} ({current_progress}/{target_progress}) - 奖励: +{lottery_count}次")

            if task_type == "video_make":
                task1_completed = (task_state == 1)
            elif task_type == "ai_agent_chat":
                task2_completed = (task_state == 1)
            elif task_type == "login" or "首次登录" in task_name:
                first_login_completed = (task_state == 1)

        print()
    else:
        print(f"⚠ 查询失败，继续执行任务\n")

    if not first_login_completed:
        print("\n[4.5] 执行首次登录任务...")
        login_task_result = api.first_login_lottery(phone)
        if login_task_result.get("code") == "0000":
            print("  ✓ 首次登录任务完成，获得5次抽奖机会")
        else:
            msg = login_task_result.get("desc", login_task_result.get("message", "未知错误"))
            print(f"  ⚠ 首次登录任务失败: {msg}")
    else:
        print("\n[4.5] 首次登录任务已完成，跳过")

    print("\n[5] 查询初始抽奖次数...")
    lottery_times_result = api.get_lottery_times(phone)
    if lottery_times_result.get("code") == "0000":
        initial_times = lottery_times_result.get("data", 0)
        print(f"✓ 当前抽奖次数: {initial_times}")
    else:
        print(f"⚠ 查询失败")
        initial_times = 0

    # ========== 任务1: 制作同款视频 ==========
    print("\n" + "="*50)
    print("【任务1】制作同款视频（获得抽奖次数）")
    print("="*50)

    if task1_completed:
        print("\n✓ 任务1已完成，跳过")
        task1_success = True
    else:
        print("\n[6] 查询新年模板列表...")
        templates_result = api.query_new_year_templates()
        if templates_result.get("code") != "0000":
            print(f"❌ 获取模板列表失败: {templates_result}")
            task1_success = False
        else:
            template_list = templates_result.get("data", {}).get("list", [])
            if not template_list:
                print("❌ 模板列表为空")
                task1_success = False
            else:
                print(f"✓ 获取到 {len(template_list)} 个模板")
                if template_list:
                    t0 = template_list[0]
                    print(f"  📋 模板字段: {list(t0.keys())}")
                    print(f"  📋 第1个模板: videoName={t0.get('videoName','')}, templateId={t0.get('templateId','')}, configId={t0.get('configId','')}, templateConfId={t0.get('templateConfId','')}, arrangeId={t0.get('arrangeId','')}")

                print(f"\n[7] 开始制作视频 (共3次)...")
                task1_success_count = 0

                import random
                available_templates = template_list.copy()

                success_count = 0
                attempt_count = 0
                max_attempts = min(len(available_templates), 10)  # 最多尝试10次

                while success_count < 3 and attempt_count < max_attempts and available_templates:
                    attempt_count += 1

                    template = random.choice(available_templates)
                    video_name = template.get("videoName", "")
                    template_id = template.get("templateId", "")
                    template_conf_id = template.get("configId", "") or template.get("templateConfId", "")
                    user_words = template.get("userWords", "")

                    print(f"\n  制作第 {success_count + 1}/3 次 (尝试 {attempt_count})...")
                    print(f"  模板: {video_name} (ID: {template_id}, ConfID: {template_conf_id})")

                    if not template_id or not user_words or not template_conf_id:
                        missing = []
                        if not template_id: missing.append("templateId")
                        if not template_conf_id: missing.append("configId")
                        if not user_words: missing.append("userWords")
                        print(f"  ⚠ 模板缺少必要字段({','.join(missing)})，跳过此模板")
                        available_templates.remove(template)
                        continue

                    template_num = template_id.replace("ve_", "") if template_id.startswith("ve_") else template_id
                    stat_actparam = f"_activityID_ai090_templateID_{template_num}_entrance_{CHANNEL_ID}_templateconfID_{template_conf_id}_location_马上拜年_ca_dljA"
                    api.send_stat_message(phone, "activity_vring_make_1.9", stat_actparam)

                    result = api.make_new_year_video(phone, template)
                    code = result.get("code", "")
                    msg = result.get("message", result.get("desc", str(result)))

                    available_templates.remove(template)

                    if code == "0000":
                        data = result.get("data", {})
                        add_lottery_times = data.get("addLotteryTimes", 0)
                        add_huango_times = data.get("addHuanGoLotteryTimes", "0")
                        print(f"  ✓ 制作成功! 获得抽奖次数: {add_lottery_times}, 换购次数: {add_huango_times}")
                        success_count += 1
                        task1_success_count += 1
                    else:
                        print(f"  ✗ 制作失败: {msg}，尝试下一个模板")

                    if success_count < 3 and available_templates:
                        time.sleep(1)  # 制作间隔

                print(f"\n任务1完成: {success_count}/3 成功 (共尝试 {attempt_count} 次)")
                task1_success = success_count > 0

    print("\n[8] 查询任务1后的抽奖次数...")
    lottery_times_result = api.get_lottery_times(phone)
    if lottery_times_result.get("code") == "0000":
        after_task1_times = lottery_times_result.get("data", 0)
        print(f"✓ 当前抽奖次数: {after_task1_times}")
    else:
        print(f"⚠ 查询失败")
        after_task1_times = initial_times

    print("\n" + "="*50)
    print("【任务2】去智能体创作（获得抽奖次数）")
    print("="*50)

    if task2_completed:
        print("\n✓ 任务2已完成，跳过")
        task2_success_count = 3
    else:
        # AI对话内容列表（可以自定义这个玩意，无所谓的）
        ai_prompts = [
            "生成一张马年春节窗花剪纸的图片",
            "生成一张新年祝福的中国风图片",
            "生成一张春节喜庆氛围的图片"
        ]

        print(f"\n[9] 开始AI对话生成图片 (共3次)...")
        task2_success_count = 0
        session_id = "" 

        for chat_idx in range(3):
            prompt = ai_prompts[chat_idx % len(ai_prompts)]
            print(f"\n  === 第 {chat_idx + 1}/3 次生成 ===")
            print(f"  提示词: {prompt}")

            print(f"  [1/3] 发起AI对话...")
            result1 = api.ai_agent_chat(phone, prompt, session_id=session_id)
            code1 = result1.get("code", "")

            if code1 != "0000":
                msg = result1.get("desc", result1.get("message", "未知错误"))
                print(f"  ✗ 对话失败: {msg}")
                continue

            data1 = result1.get("data", {})
            session_id = data1.get("sessionId", "")
            confirm_id = data1.get("id", 0)
            card_params = data1.get("cardParameterList", {})
            text_list = card_params.get("textList", [])

            print(f"  ✓ 对话成功，confirmId: {confirm_id}")

            if not text_list:
                print(f"  ⚠ textList为空，跳过此次生成")
                continue

            print(f"  [2/3] 确认提交生成...")
            result2 = api.control_confirm_submit(phone, session_id, confirm_id, text_list)
            code2 = result2.get("code", "")

            if code2 != "0000":
                msg = result2.get("desc", result2.get("message", "未知错误"))
                print(f"  ✗ 提交失败: {msg}")
                continue

            data2 = result2.get("data", {})
            task_id = data2.get("taskId", "")
            content = data2.get("content", "")

            print(f"  ✓ 提交成功，taskId: {task_id}")
            print(f"  响应: {content[:80]}..." if len(content) > 80 else f"  响应: {content}")

            print(f"  [3/3] 等待生成完成...这步冗余，保留了")
            max_check_times = 15  # 最多检查15次
            check_interval = 2    # 每次间隔2秒

            for check_idx in range(max_check_times):
                time.sleep(check_interval)

                result3 = api.check_ai_agent_result(phone, task_id)
                code3 = result3.get("code", "")
                desc3 = result3.get("desc", "")

                if code3 == "0000":
                    print(f"  ✓ 生成完成! ({check_idx + 1}次检查)")
                    task2_success_count += 1
                    break
                elif code3 == "10008":
                    print(f"  ⏳ 制作中... ({check_idx + 1}/{max_check_times})")
                    continue
                else:
                    # 其他可能错误自己搞去吧
                    print(f"  ✗ 生成失败: {desc3}")
                    break
            else:
                # 超时
                print(f"  ⚠ 等待超时，跳过")

            if chat_idx < 2:
                print(f"  等待2秒后进行下一次生成...")
                time.sleep(2)  # 下一次生成前的间隔

        print(f"\n任务2完成: {task2_success_count}/3 成功")

    print("\n" + "="*50)
    print("【抽奖环节】")
    print("="*50)

    print("\n[9] 查询最终抽奖次数...")
    lottery_times_result = api.get_lottery_times(phone)
    if lottery_times_result.get("code") == "0000":
        final_times = lottery_times_result.get("data", 0)
        print(f"✓ 最终抽奖次数: {final_times}")
    else:
        print(f"⚠ 查询失败，跳过抽奖")
        final_times = 0

    account_summary = {"phone": phone, "success": False, "awards": [], "red_packet": 0.0, "redeemed": "0", "balance": "0"}
    total_red_packet = 0.0
    if final_times > 0:
        print(f"\n[10] 开始抽奖 (共{final_times}次)...")
        lottery_success = 0
        awards = []

        for lottery_idx in range(final_times):
            print(f"\n  第 {lottery_idx + 1}/{final_times} 次抽奖...")
            lottery_result = api.do_egg_lottery(phone, use_proxy=True)

            if lottery_result.get("code") == "0000":
                data = lottery_result.get("data", {})
                award_name = data.get("awardName", "未知奖品")
                awards.append(award_name)
                print(f"  ✓ {award_name}")
                lottery_success += 1

                import re
                money_match = re.search(r'(\d+\.?\d*)元', award_name)
                if money_match:
                    money = float(money_match.group(1))
                    total_red_packet += money
            else:
                msg = lottery_result.get("desc", lottery_result.get("message", "未知错误"))
                print(f"  ✗ 抽奖失败: {msg}")

            if lottery_idx < final_times - 1:
                time.sleep(0.5)  # 抽奖间隔

        print(f"\n抽奖完成: {lottery_success}/{final_times} 成功")
        if awards:
            print(f"获得奖品: {', '.join(awards)}")
            account_summary["awards"] = awards
        if total_red_packet > 0:
            print(f"累计红包: {total_red_packet:.2f}元")
            account_summary["red_packet"] = total_red_packet
    else:
        print(f"\n[10] 跳过抽奖 (抽奖次数为0)")

    print(f"\n[11] 查询红包余额...")

    balance_result = api.query_red_packet_balance(phone)
    if balance_result.get("code") == "0000":
        data = balance_result.get("data", {})
        already_redeem = data.get("alreadyRedeemValue", "0")
        balance_cost = data.get("balanceCostValue", "0")
        already_redeem_costs = data.get("alreadyRedeemCosts", [])

        print(f"  ✓ 查询成功!")
        print(f"  累计已兑换: {already_redeem}元")
        print(f"  剩余可兑换: {balance_cost}元")
        account_summary["redeemed"] = already_redeem
        account_summary["balance"] = balance_cost

        if already_redeem_costs:
            print(f"  已兑换记录:")
            for record in already_redeem_costs:
                award_name = record.get("awardName", "")
                update_date = record.get("updateDate", "")
                print(f"    - {award_name} ({update_date})")

        try:
            balance_float = float(balance_cost)
            if balance_float >= 2.0:
                proxy_status = "使用代理" if USE_PROXY_FOR_REDEEM else "不使用代理"
                print(f"\n  💰 可兑换金额已满2元，开始多次兑换...")
                print(f"  🚀 准备顺序发送{REDEEM_COUNT}次兑换请求（{proxy_status}）...")

                success_count = 0
                fail_count = 0
                total_extract = 0.0
                results = []

                for i in range(REDEEM_COUNT):
                    print(f"\n  [{i+1}/{REDEEM_COUNT}] 兑换中...", end=" ")

                    try:
                        result = api.redeem_red_packet(phone, balance_float, use_proxy=USE_PROXY_FOR_REDEEM)
                        results.append((i+1, result))

                        if result.get("code") == "0000":
                            redeem_data = result.get("data", {})
                            extract_value = redeem_data.get("extractValue", "0")
                            try:
                                extract_float = float(extract_value)
                                total_extract += extract_float
                                print(f"✓ 成功 - 提取{extract_value}元")
                                success_count += 1
                            except:
                                print(f"✓ 成功")
                                success_count += 1
                        else:
                            msg = result.get("desc", result.get("message", "未知错误"))
                            print(f"✗ 失败 - {msg}")
                            fail_count += 1

                            if "余额不足" in msg or "balanceCostValue不足" in msg:
                                print(f"  ⚠ 余额不足，停止兑换")
                                break
                    except Exception as e:
                        print(f"✗ 异常 - {str(e)}")
                        fail_count += 1
                        results.append((i+1, {"code": "error", "message": str(e)}))

                    if i < REDEEM_COUNT - 1:
                        time.sleep(0.5)

                print(f"\n  📈 总计: 成功{success_count}次, 失败{fail_count}次")
                if total_extract > 0:
                    print(f"  💰 累计提取: {total_extract:.2f}元")

                print(f"\n  🔄 重新查询余额...")
                balance_result2 = api.query_red_packet_balance(phone)
                if balance_result2.get("code") == "0000":
                    data2 = balance_result2.get("data", {})
                    new_already_redeem = data2.get("alreadyRedeemValue", "0")
                    new_balance = data2.get("balanceCostValue", "0")
                    print(f"  ✓ 累计已兑换: {new_already_redeem}元")
                    print(f"  ✓ 剩余可兑换: {new_balance}元")
                    account_summary["redeemed"] = new_already_redeem
                    account_summary["balance"] = new_balance
            else:
                print(f"  ℹ️  需满2元才能兑换（还差{2.0 - balance_float:.2f}元）")
        except Exception as e:
            print(f"  ⚠ 处理失败: {e}")
    else:
        msg = balance_result.get("desc", balance_result.get("message", "未知错误"))
        print(f"  ✗ 查询失败: {msg}")
    print(f"\n[12] 发送统计埋点...")
    stat_result = api.send_stat_message(
        phone,
        "activity_2512new-year-2026_30.1",
        "activityID_ai090_ca_dljA"
    )
    if stat_result.get("code") == "0000":
        print(f"  ✓ 埋点发送成功")
    else:
        print(f"  ⚠ 埋点发送失败: {stat_result.get('desc', '')}")

    print(f"\n{'='*50}")
    print(f"账号 {phone} 处理完成")
    print(f"{'='*50}")

    account_summary["success"] = task1_success or task2_success_count > 0
    return account_summary

def main():
    print("=" * 50)
    print("加载登录缓存...")
    cache = load_cache()
    print(f"✓ 缓存加载完成，已缓存 {len(cache)} 个账号")
    print("=" * 50)
    accounts = parse_accounts(ACCOUNTS_STR)
    if not accounts:
        print("错误: 未配置账号")
        return
    print("\n" + "=" * 50)
    print("2026新年星辰活动")
    print(f"渠道ID: {CHANNEL_ID}")
    print(f"共 {len(accounts)} 个账号")
    print("=" * 50)
    print("\n活动说明:")
    print("  任务1: 制作新年视频 (3次) → 获得抽奖次数")
    print("  任务2: AI对话生成图片 (3次) → 获得抽奖次数")
    print("  分享任务: 智能分配邀请码，互相助力")
    print("  最后: 使用获得的次数进行抽奖")
    print("=" * 50)

    total = len(accounts)
    success_count = 0
    invite_codes = {}
    account_results = []
    for idx, (phone, password) in enumerate(accounts):
        print(f"\n{'='*50}")
        print(f"处理账号 {idx + 1}/{total}: {phone}")
        print(f"{'='*50}")

        result = process_new_year_lottery(phone, password, idx + 1, total, cache=cache)
        if isinstance(result, dict):
            account_results.append(result)
            is_success = result.get("success", False)
        else:
            is_success = bool(result)
        if is_success:
            success_count += 1
        if is_success:
            try:
                print(f"\n[额外] 获取账号 {phone} 的邀请码...")
                login_result = userLoginNormal(phone, password, cache=cache)
                if login_result:
                    ticket, is_expired = get_ticket(phone, login_result['userId'], login_result['token'])
                    if is_expired:
                        login_result = userLoginNormal(phone, password, cache=cache, force_login=True)
                        if login_result:
                            ticket, is_expired = get_ticket(phone, login_result['userId'], login_result['token'])
                    if ticket:
                        token, cookies = sso_login_v2(ticket)
                        if token:
                            api = InviteAPI(token, cookies)
                            code_result = api.get_share_task_code(phone)
                            if code_result.get("code") == "0000":
                                task_code = code_result.get("data", {}).get("taskCode", "")
                                if task_code:
                                    invite_codes[phone] = task_code
                                    print(f"  ✓ 邀请码: {task_code[:20]}...")
                                else:
                                    print(f"  ⚠ 未获取到邀请码")
                            else:
                                print(f"  ⚠ 获取邀请码失败: {code_result.get('desc', '')}")
            except Exception as e:
                print(f"  ⚠ 获取邀请码异常: {str(e)}")

        if idx < len(accounts) - 1:
            print(f"\n等待3秒后处理下一个账号...")
            time.sleep(3)

    if len(invite_codes) >= 2:
        print(f"\n{'='*50}")
        print(f"开始智能分配邀请任务")
        print(f"共获取到 {len(invite_codes)} 个邀请码")
        print(f"分享规则: 每个账号的邀请码被5个不同账号触发")
        print(f"{'='*50}")

        account_list = list(accounts)
        total_accounts = len(account_list)

        for idx in range(total_accounts):
            current_phone, current_password = account_list[idx]

            if current_phone not in invite_codes:
                continue
            task_code = invite_codes[current_phone]
            print(f"\n{'='*50}")
            print(f"账号 {current_phone} 的邀请码: {task_code[:20]}...")
            print(f"{'='*50}")

            success_count = 0
            for offset in range(1, min(6, total_accounts)):  # 最多5个，或者账号总数-1
                helper_idx = (idx + offset) % total_accounts
                helper_phone, helper_password = account_list[helper_idx]
                if helper_phone == current_phone:
                    continue
                print(f"\n  [{offset}/5] 账号 {helper_phone} 触发邀请...")
                try:
                    login_result = userLoginNormal(helper_phone, helper_password, cache=cache)
                    if not login_result:
                        print(f"    ✗ 登录失败")
                        continue
                    ticket, is_expired = get_ticket(helper_phone, login_result['userId'], login_result['token'])
                    if is_expired:
                        login_result = userLoginNormal(helper_phone, helper_password, cache=cache, force_login=True)
                        if login_result:
                            ticket, is_expired = get_ticket(helper_phone, login_result['userId'], login_result['token'])
                    if not ticket:
                        print(f"    ✗ 获取ticket失败")
                        continue
                    token, cookies = sso_login_v2(ticket)
                    if not token:
                        print(f"    ✗ SSO登录失败")
                        continue
                    api = InviteAPI(token, cookies)
                    info_result = api.get_share_task_info(helper_phone, task_code)
                    if info_result.get("code") == "0000":
                        task_state = info_result.get("data", {}).get("taskState", "0")
                        # if task_state == "1":
                        #     print(f"    ⚠ 已经触发过此邀请，跳过")
                        #     continue

                    # 领取邀请奖励
                    lottery_result = api.share_lottery(helper_phone, task_code)
                    if lottery_result.get("code") == "0000":
                        award_name = lottery_result.get("data", {}).get("awardName", "未知")
                        print(f"    ✓ 领取成功: {award_name}")
                        success_count += 1
                    else:
                        desc = lottery_result.get("desc", "")
                        print(f"    ⚠ 领取失败: {desc}")

                    time.sleep(1)

                except Exception as e:
                    print(f"    ✗ 处理异常: {str(e)}")

            print(f"\n  账号 {current_phone} 完成: {success_count}/5 个助力")

            if idx < total_accounts - 1:
                time.sleep(2)

    print(f"\n{'='*50}")
    print(f"全部处理完成: {success_count}/{total} 成功")
    print(f"{'='*50}")

    notify_lines = [f"全部处理完成: {success_count}/{total} 成功\n"]
    for r in account_results:
        p = r.get("phone", "未知")
        status = "✓" if r.get("success") else "✗"
        redeemed = r.get("redeemed", "0")
        balance = r.get("balance", "0")
        notify_lines.append(f"{status} {p}")
        notify_lines.append(f"  已兑换: {redeemed}元 | 未兑换: {balance}元")
        awards = r.get("awards", [])
        if awards:
            notify_lines.append(f"  奖品: {', '.join(awards)}")
        red_packet = r.get("red_packet", 0)
        if red_packet > 0:
            notify_lines.append(f"  本次红包: {red_packet:.2f}元")
    send("2026电信星辰活动", "\n".join(notify_lines))


if __name__ == "__main__":
    main()

