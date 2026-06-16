"""
cron: 30 59 8 * * *
const $ = new Env("翼支付领券");
"""

import asyncio
import gzip

import aiohttp
import aiodns
import json

import redis
import requests

import rsa
import base64
import hashlib
import random
import datetime
import sys
import time
import os
import ssl
import re
from Crypto.Cipher import AES, DES3, PKCS1_v1_5
from Crypto.Util.Padding import pad, unpad
from concurrent.futures import ThreadPoolExecutor
import urllib

# 要抢的权益
# 如果你不知道要领什么权益，复制qg第一行到末尾，只修改权益包名，并且修改dyqy=1，运行脚本就会显示该权益包的所有权益
# qg = {
# '要抢的权益包名':['权益名称 权益名称下面的小字,没有填None', '定时抢券时间，不填写时间会直接领券'],
# '橙翼权益':['话费充值券包 价值9元', '话费充值券包 价值18元', '话费充值券包 价值24元', '爱奇艺 视频月卡','8:59:59'],
# 'N选权益包':['领5元话费券赠170个权益币 None'],
# 'N选权益包-加副-9元': ['领160个权益币 None'],
# '流量权益包-19元': ['领160个权益币 None'],
# '天翼云盘橙意包': ['领160个权益币 None'],
# '5g升级权益合约': ['领腾讯会员周卡赠送100个权益币 None'],
# '河南天翼云盘融云橙翼包': ['领腾讯会员周卡赠送100个权益币 None'],
# '节日促销-权益N选1合约-9元': ['翼支付通用券 18元券包'],
# "河南15元出行权益包":["150个权益币 180天有效期"],
# "15元N选权益小合约":["话费+腾讯周卡券包 10元话费+腾讯周卡"],
# '14.9橙翼权益黑金版（12期）':['生活缴费券包 价值30元', '9:59:59'],
# }
qg = {
      '特惠生活权益包': ['23元话费券包 领取后间隔周期生效'],
      '月返10元权益包（24个月）': ['10元权益金 None'],
      '橙翼权益黄金版（连续包月）': ['话费充值券包 价值9元', '9:00:00'],
    #  '橙翼权益黄金版（24期）': ['话费充值券包 价值9元', '9:00:00'],
    #  '橙翼权益白金版（24期）': ['话费充值券包 价值18元', '9:00:00'],
      '橙翼权益白金版（连续包月）': ['话费充值券包 价值18元', '9:00:00'],
    #  '橙翼权益黑金版（24期）': ['话费充值券包 价值24元', '9:00:00'],
	  '橙翼权益黑金版（连续包月）': ['话费充值券包 价值24元', '9:00:00'],
     '惠享权益包（副卡专用）': ['领充值缴费券包赠忘领无忧保障权益 5元话费券+13元水电煤券包/忘领无忧', '9:00:00'],
}
# 编辑productNo_list或者设置变量yzf，格式：手机号@服务密码,多号&隔开
productNo_list = '<PHONE>@950331&<PHONE>@514564&<PHONE>@514564&<PHONE>@514564'

# 是否打印权益名称方便修改领取列表，1开启0关闭
dyqy = 1

# 是否开启优惠券查询推送，1开启， 0关闭
yhcx = 1
# 是否屏蔽未生效优惠券
sxyh = 1
# 屏蔽的优惠券
yhqhmd = ["北冰洋5元饮品券", "北冰洋15元饮品券", None]

# 开启并发, 1开启0关闭
kqbf = 1
# 并发数量，账号太多可能报错
bfs = 10
# 授权key
api_key = '<SENSITIVE>'
########

cfcs = os.environ.get('yzfcf') or 20  # 重发次数

# 初始化日志字典
logg = {}

# 创建线程池执行器（用于CPU密集型操作）
executor = ThreadPoolExecutor(max_workers=10)
# 初始化参数


ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
ssl_context.set_ciphers('DEFAULT@SECLEVEL=0')

appType = "116"


def encrypt(text):
    key = b'1234567`90koiuyhgtfrdews'
    iv = 8 * b'\0'
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(text.encode(), DES3.block_size))
    return ciphertext.hex()


def decrypt(text):
    key = b'1234567`90koiuyhgtfrdews'
    iv = 8 * b'\0'
    ciphertext = bytes.fromhex(text)
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext), DES3.block_size)
    return plaintext.decode()


def encode_phone(text):
    encoded_chars = []
    for char in text:
        encoded_chars.append(chr(ord(char) + 2))
    return ''.join(encoded_chars)


async def userLoginNormal(ss, phone, password):
    alphabet = 'abcdef0123456789'
    uuid = [''.join(random.sample(alphabet, 8)), ''.join(random.sample(alphabet, 4)),
            '4' + ''.join(random.sample(alphabet, 3)), ''.join(random.sample(alphabet, 4)),
            ''.join(random.sample(alphabet, 12))]
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    loginAuthCipherAsymmertric = '<SENSITIVE>' + uuid[0] + uuid[1] + phone + timestamp + password[:6] + '0$$$0.'
    public_key_b64 = 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBkLT15ThVgz6/NOl6s8GNPofdWzWbCkWnkaAm7O2LjkM1H7dMvzkiqdxU02jamGRHLX/ZNMCXHnPcW/sDhiFCBN18qFvy8g6VYb9QtroI09e176s+ZCtiv7hbin2cCTj99iUpnEloZm19lwHyo69u5UMiPMpq0/XKBO8lYhN/gwIDAQAB'
    r = await ss.post('https://appgologin.189.cn:9031/login/client/userLoginNormal', json={
        "headerInfos": {"code": "userLoginNormal", "timestamp": timestamp, "broadAccount": "", "broadToken": "",
                        "clientType": "#10.5.0#channel50#iPhone 14 Pro Max#", "shopId": "20002", "source": "110003",
                        "sourcePassword": "<SENSITIVE>", "token": "", "userLoginName": encode_phone(phone)},
        "content": {"attach": "test", "fieldData": {"loginType": "4", "accountType": "",
                                                    "loginAuthCipherAsymmertric": rsa_encrypt(public_key_b64,
                                                                                              loginAuthCipherAsymmertric),
                                                    "deviceUid": uuid[0] + uuid[1] + uuid[2],
                                                    "phoneNum": encode_phone(phone), "isChinatelecom": "<SENSITIVE>",
                                                    "systemVersion": "15.4.0",
                                                    "authentication": encode_phone(password)}}})
    r = await r.json()
    l = r.get('responseData').get('data')

    if l and l.get('loginSuccessResult'):
        l = l.get('loginSuccessResult')
        load_token[phone] = l
        with open(load_token_file, 'w') as f:
            json.dump(load_token, f)
        ticket = await get_ticket(ss, phone, l['userId'], l['token'])

        return ticket
    else:
        print(r)

    return False


async def get_ticket(ss, phone, userId, token):
    r = await ss.post('https://appgologin.189.cn:9031/map/clientXML',
                      data='<Request><HeaderInfos><Code>getSingle</Code><Timestamp>' + datetime.datetime.now().strftime(
                          "%Y%m%d%H%M%S") + '</Timestamp><BroadAccount></BroadAccount><BroadToken></BroadToken><ClientType>#9.6.1#channel50#iPhone 14 Pro Max#</ClientType><ShopId>20002</ShopId><Source>110003</Source><SourcePassword>Sid98s</SourcePassword><Token>' + token + '</Token><UserLoginName>' + phone + '</UserLoginName></HeaderInfos><Content><Attach>test</Attach><FieldData><TargetId>' + encrypt(
                          userId) + '</TargetId><Url>4a6862274835b451</Url></FieldData></Content></Request>',
                      headers={'user-agent': 'CtClient;10.4.1;Android;13;22081212C;NTQzNzgx!#!MTgwNTg1'})
    r = await r.text()
    tk = re.findall('<Ticket>(.*?)</Ticket>', r)
    if len(tk) == 0:
        return False

    return decrypt(tk[0])


def run_Time(sj):
    sj = sj.split(':')
    hour, miute, second = int(sj[0]), int(sj[1]), int(sj[2])
    date = datetime.datetime.now()
    date_zero = datetime.datetime.now().replace(year=date.year, month=date.month, day=date.day, hour=hour, minute=miute,
                                                second=second)
    date_zero_time = int(time.mktime(date_zero.timetuple()))
    return date_zero_time


# 异步HTTP客户端会话
async def create_session():
    resolver = aiohttp.AsyncResolver(nameservers=["119.29.29.29"])
    connector = aiohttp.TCPConnector(limit=1000, ssl=ssl_context)  # 根据需要调整连接池大小
    return aiohttp.ClientSession(connector=connector)


# 同步加密函数（保持同步，通过线程池执行）
def aes_encrypt(plaintext, key):
    cipher = AES.new(key.encode(), AES.MODE_CBC, 16 * b'\0')
    return base64.b64encode(cipher.encrypt(pad(plaintext.encode(), AES.block_size))).decode()


def rsa_encrypt(j_rsakey, string):
    pub_key = rsa.PublicKey.load_pkcs1_openssl_pem(
        f"-----BEGIN PUBLIC KEY-----\n{j_rsakey}\n-----END PUBLIC_KEY-----".encode())
    return base64.b64encode(rsa.encrypt(string.encode(), pub_key)).decode()


def rsa_encrypt(j_rsakey, string):
    rsa_key = f"-----BEGIN PUBLIC KEY-----\n{j_rsakey}\n-----END PUBLIC KEY-----"
    pubkey = rsa.PublicKey.load_pkcs1_openssl_pem(rsa_key.encode())
    result = (base64.b64encode(rsa.encrypt(f'{string}'.encode(), pubkey))).decode()
    return result


def generate_mixed():
    return ''.join(str(random.randint(0, 9)) for _ in range(16))


def trace_log_id():
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ''.join(str(random.randint(0, 9)) for _ in range(18))


def md5_hash(s):
    return hashlib.md5(s.encode()).hexdigest().upper()


def process_data(e):
    param_str = json.dumps(e)
    rk = generate_mixed()
    erk = rsa_encrypt(public_key, rk)
    edata = aes_encrypt(param_str, rk)
    return {
        'encyType': 'C005',
        'data': edata,
        'fromchannelId': 'H5',
        'key': erk,
        'productNo': kproductNo,
        'sign': md5_hash(param_str)
    }


async def ascii_add_2(number_str):
    transformed = ''.join(chr(ord(char) + 2) for char in number_str)
    return transformed


# 异步请求函数
async def async_post(session, url, data):
    try:
        async with session.post(url, json=data) as response:
            # print(await response.json())
            response.raise_for_status()
            return await response.json()
    except Exception as e:
        print(f"请求失败: {url} - {str(e)}")
        return None


async def async_post_new(session, url, headers, data, symmetricKey, method=None):
    try:
        async with session.post(url, headers=headers, data=data) as response:
            # 正确获取响应内容和状态
            content = await response.read()
            result_status = response.headers.get('Result-Status', '')
            tips = response.headers.get('Tips', '')
            print(f"Result-Status: {result_status} {urllib.parse.unquote(tips)}{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")

            # 检查响应是否成功
            if response.status == 200 and result_status == '1000':
                hh = {
                    "symmetricKey": list(symmetricKey),
                    "data": list(content),
                    "decryptType": "2"
                }
                body = {
                    "app": app,
                    "code": result_status,
                    "action": "decrypt",
                    'data': json.dumps(hh)
                }
                # 使用异步请求而不是同步的 requests
                async with session.post(f"{__url}", json=body) as decrypt_response:
                    if decrypt_response.status == 200:
                        res = await decrypt_response.json()
                        # print("解密响应:", method, res)
                        return res
                    else:
                        print(f"解密请求失败: {decrypt_response.status}")
                        return None
            else:
                print(f"请求失败 - 状态码: {response.status}, Result-Status: {result_status}")
                return None
    except Exception as e:
        print(f"请求失败: {url} - {str(e)}")
        return None


# 核心业务逻辑（异步版本）
async def process_product(session, product_no):
    product_no, password = product_no.split('@')
    logg[product_no] = []
    # await asyncio.sleep(sl/5)
    # 获取验证码（需实现具体逻辑）
    # code = ""  # await get_code_async(product_no, password)
    ticket = False
    if product_no in load_token:
        print(f'{product_no} 使用缓存登录')
        ticket = await get_ticket(session, product_no, load_token[product_no]['userId'],
                                  load_token[product_no]['token'])
        # print(ticket)

    if ticket == False:
        print(f'{product_no} 使用密码登录')
        ticket = await userLoginNormal(session, product_no, password)

    if ticket == False:
        print(f"{product_no} 登录失败")
        return
    # 获取会话密钥
    session_result = await get_session_key_async_new(session, product_no, ticket)
    session_key = session_result['sessionKey']
    # print(session_key)
    if not session_key:
        print(f"{product_no} 翼支付session_key获取失败")
        return

    # 查询优惠券列表
    if yhcx:
        yh = await get_queryUserNoUseEquity(session, product_no, session_key)

    # 查询权益包列表
    page_data = await get_page_ordered_sales_async(session, product_no, session_key)

    if not page_data or not page_data.get('result', {}).get('salesProductList'):
        logg[product_no].append("没有权益包")
        return

    # 处理每个权益包
    tasks = []
    for item in page_data['result']['salesProductList']:
        print(item['qyProductName'])

        for i in qg:
            if item['qyProductName'] in i:
                tasks.append(process_equity_package(session, product_no, session_key, item, qg[i], session_result))

    # 确保所有任务完成后再返回
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# 异步会话密钥获取
async def get_session_key_async(session, product_no, code):
    data = process_data(
        {"appType": appType, "agreeId": "20201016030100056487302393758758", "encryptData": code, "systemType": "",
         "imei": "", "mtMac": "", "wifiMac": "", "location": ""})  # ticket方案

    response = await async_post(session, 'https://mapi-welcome.bestpay.com.cn/gapi/AppFusionLogin/authorizeAndRegister',
                                data)

    return response['result']['sessionKey'] if response else None


async def get_session_key_async_new(session, product_no, ticket):
    body = {
        "app": app,
        "action": "encryptLogin",
        "code": product_no,
        'data': ticket
    }
    res = await async_post(session, f"{__url}", body)
    if res["status"] == 200:
        res = json.loads(res['data'])

    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'appid': res['appid'],
        'cache-control': 'no-cache',
        'content-type': 'application/json',
        'operation-type': 'com.bestpay.mbp.mbpprovinceplatform.service.api.fusionLogin.queryAuthorizedUserPopup',
        'origin': 'https://h5.bestpay.cn',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': 'https://h5.bestpay.cn/',
        'sec-ch-ua': '""',
        'sec-ch-ua-mobile': '<SENSITIVE>',
        'sec-ch-ua-platform': '""',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'cross-site',
        'sign': res['signHeaders']['sign'],
        'signtype': 'md5',
        'ts': f"{res['signHeaders']['Ts']}",
        'user-agent': 'CtClient;12.0.0;Android;13;PENM00;NDE5NDIx!#!MTkzMjY/CtClient/gi',
        'workspaceid': 'PRD',
        'x-cors-fc1902c211615-prd': '1',
    }

    byte_values = [res['data'][str(i)] for i in range(len(res['data']))]
    processed_data = bytes(byte_values)
    byte_values = [res['symmetricKey'][str(i)] for i in range(len(res['symmetricKey']))]
    symmetricKey = bytes(byte_values)
    response = await async_post_new(session, 'https://spanner.bestpay.com.cn:10081', headers, processed_data,
                                    symmetricKey)
    response = json.loads(response['data'])
    response = json.loads(response['data'])
    return response['result'] if response else None




async def get_queryUserNoUseEquity(session, productNo, sessionKey):
    queryUserNoUseEquity = await async_post(session,
                                            'https://mapi-h5.bestpay.com.cn/gapi/5gproduct/vipProduct/equitySpecialZoneService/queryUserNoUseEquity',
                                            process_data({"encyType": "C005", "appType": appType,
                                                          "agreeId": "20210518030100134138528408797188",
                                                          "fromchannelId": "H5", "fromChannelId": "H5",
                                                          "traceLogId": "", "productNo": productNo,
                                                          "sessionKey": sessionKey, "pageNo": "1", "pageSize": "100"}))

    Equity = []

    for i in queryUserNoUseEquity['result']['queryNoUserInfoList']:
        Equity += i['batchList']

    for i in Equity:
        if i['batchName'] in yhqhmd:
            continue

        srq = i["couponStartDate"].split(' ')[0].replace('-', '')

        if int(srq) > int(rq.replace('-', '')) and sxyh:
            continue

        msg = f"{i['batchName']} {i['minConsume']}-{i['denomination']}\n开始: {i['couponStartDate']}\n过期: {i['couponEndDate']}"
        logg[productNo].append(msg)
        print(msg)

        if qlts == 1:

            if i['couponStartDate'].split(' ')[0] == rq:
                msg = f"{productNo} 翼支付有优惠券今日可用\n{i['batchName']} {i['minConsume']}-{i['denomination']}\n开始: {i['couponStartDate']}\n过期: {i['couponEndDate']}"
                send(msg, msg)

            if i['couponEndDate'].split(' ')[0] == rq:
                msg = f"{productNo} 翼支付有优惠券今日到期\n{i['batchName']} {i['minConsume']}-{i['denomination']}\n开始: {i['couponStartDate']}\n过期: {i['couponEndDate']}"

                send(msg, msg)


# 异步权益包查询
async def get_page_ordered_sales_async(session, product_no, session_key):
    data = process_data({
        "encyType": "C005",
        "appType": appType,
        "fromchannelId": "H5",
        "productNo": product_no,
        "sessionKey": session_key,
        "currentPage": 1,
        "displayOrderType": "DEFAULT",
        "pageSize": 70
    })
    return await async_post(session, 'https://mapi-h5.bestpay.com.cn/gapi/5gproduct/vipProduct/query/pageOrderedSales',
                            data)


# 异步权益包处理
async def process_equity_package(session, product_no, session_key, item, qgi, session_result):
    order_no = item["orderNo"]
    qyProductName = item['qyProductName']
    # logg[product_no].append(f'[{qyProductName}]')
    detail_data = await get_query_equity_package_detail_async(session, product_no, session_key, order_no)
    # print(detail_data)
    for module in detail_data.get("result", {}).get("equityModuleInfoDTOList", []):
        equityPackageId = detail_data['result']['equityPackageId']
        bindEquityList = []
        unit_ids = []
        module_id = module['moduleId']
        moduleName = f"{module['moduleShowConfigDTO']['moduleName']}"
        if type(qgi) == dict:
            if moduleName not in qgi:
                continue
            else:
                qgim = qgi[moduleName]
        elif type(qgi) == list:
            qgim = qgi
        else:
            print("格式错误")
            return
        # print(qgim)
        if ':' in qgim[-1]:
            wt = run_Time(qgim[-1])
        else:
            wt = 0

        if module.get("classifyDTOList"):
            for c in module["classifyDTOList"]:  # ["lineDTOList"]
                lineDTOList = c["lineDTOList"]
                for m in lineDTOList:
                    bindEquityList += m["bindEquityList"]
        if module.get('bindEquityList'):
            bindEquityList += module["bindEquityList"]

        for n in bindEquityList:
            unit_ids.append(n['unitEquityId'])

        if unit_ids == []:
            continue

        if unit_ids:
            # r = await get_queryOrderedEquityPackage_async(session, product_no, session_key, order_no, module_id,
            #                                               unit_ids)
            r = await get_queryOrderedEquityPackage_async_new(session, product_no, session_result, order_no, module_id,equityPackageId,
                                                              unit_ids)
            # print(r)
            for n in r["result"]:

                qy = f"{n['bindEquityConfig']['equityMainTitle']} {n['bindEquityConfig']['equitySubTitle']}"
                if dyqy:
                    print(f"'{qyProductName}': ['{qy}'],")

                if qy not in qgim:
                    continue

                unitEquityId = n['unitEquityId']
                equityNo = n['equityId']
                if n['bindEquityConfig']['equitySubTitle'] == None:
                    n['bindEquityConfig']['equitySubTitle'] = ""

                qyn = f"{qyProductName} {qy}"

                if n['lastDistributeStatus'] != "SUCCESS":
                    if wt != 0 and abs(wt - time.time()) > 600:
                        msg = f"{product_no} [{qyProductName}]不在抢券时间"
                        print(msg)
                        logg[product_no].append(msg)
                        return
                    msg = f"{product_no}【开始领取】{qyn}"
                    print(msg)
                    logg[product_no].append(msg)

                    await process_equity_receive_new(session, product_no, session_result, order_no, module_id,
                                                     unitEquityId, equityNo, qyn, wt)
                else:
                    # print(product_no, "【已领取】", qyn)
                    msg = f"{product_no}【已领取】{qyn}"
                    # print(msg)
                    logg[product_no].append(msg)


# 异步权益详情查询
async def get_query_equity_package_detail_async(session, product_no, session_key, order_no):
    data = process_data({
        "encyType": "C005",
        "orderNo": order_no,
        "appType": appType,
        "agreeId": "20211216030100210919654787383364",
        "productNo": product_no,
        "phoneNo": product_no,
        "requestNo": generate_mixed(),
        "requestDate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sessionKey": session_key,
        "requestSystem": "equity-novel-h5",
        "operator": "",
        "traceLogId": ""
    })
    return await async_post(session,
                            'https://mapi-h5.bestpay.com.cn/gapi/ep-product-center/EquityPackageService/queryEquityPackageDetailCustomer',
                            data)


# 异步权益详情查询
async def get_queryOrderedEquityPackage_async(session, product_no, session_key, order_no, moduleId, unitEquityIdList):
    data = process_data({
        "encyType": "C005",
        "orderNo": order_no,
        "appType": appType,
        "agreeId": "20211216030100210919654787383364",
        "productNo": product_no,
        "phoneNo": product_no,
        "sessionKey": session_key,
        "unitEquityIdList": unitEquityIdList,
        "currentPeriodsNumber": "1",
        "moduleId": moduleId
    })

    return await async_post(session,
                            'https://mapi-h5.bestpay.com.cn/gapi/op-product-system/EquityPackageService/queryOrderedEquityPackage',
                            data)

# 异步权益详情查询
async def get_queryOrderedEquityPackage_async_new(session, product_no, session_result, order_no, moduleId, equityPackageId, unitEquityIdList):
    # data = process_data({
    #     "encyType": "C005",
    #     "orderNo": order_no,
    #     "appType": appType,
    #     "agreeId": "20211216030100210919654787383364",
    #     "productNo": product_no,
    #     "phoneNo": product_no,
    #     "sessionKey": session_key,
    #     "unitEquityIdList": unitEquityIdList,
    #     "currentPeriodsNumber": "1",
    #     "moduleId": moduleId
    # })
    # return await async_post(session,
    #                     'https://mapi-h5.bestpay.com.cn/gapi/op-product-system/EquityPackageService/queryOrderedEquityPackage',
    #                     data)

    h = {
        "operationType": "com.bestpay.opproduct.service.api.plus.EquityPackagePlusService.queryOrderedEquityPackage",
        "data": {
            "orderNo": order_no,
            "appType": appType,
            "currentPeriodsNumber": "1",
            "moduleId": moduleId,
            "equityPackageId": equityPackageId,
            "isPackageInfoQuery": "Y",
            "equityGroupId": equityPackageId,
            "encyType": "C005",
            "agreeId": "20211216030100210919654787383364",
            "fromChannelId": "h5",
            "timestamp": int(time.time() * 1000),
            "moduleType":"FULL_CHOOSE_EQUITY",
            "productNo": product_no,
            "phoneNo": product_no,
            "requestNo": generate_mixed(),
            "requestDate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sessionKey": session_result['sessionKey'],
            "requestSystem": "equity-novel-h5",
            "operator": "3178037417179194",
            "unitEquityIdList": unitEquityIdList,
            "traceLogId": ""
        }
    }
    # print(h)
    # 执行加密操作
    body = {
        "app": app,
        "action": "encrypt",
        "code": product_no,
        'data': json.dumps(h)
    }
    res = await async_post(session, f"{__url}", body)
    if res["status"] == 200:
        res = json.loads(res['data'])
    # print(res)
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'appid': res['appid'],
        'authssucode': '<SENSITIVE>',
        'cache-control': 'no-cache',
        'content-type': 'application/json',
        'event-context': json.dumps({
            "session_key": session_result['sessionKey'],  # 使用动态传入的 session_key
            "ip_rid": session_result['memberTypeList'][0]['ipRid'],
            "ip_tid": session_result['ipTid'],
            "auth_ssu_code": "<SENSITIVE>",
            "queryType": "SUCCESS",
            "tnt_id": "0101",
            "env": ""
        }),
        'operation-type': 'com.bestpay.opproduct.service.api.plus.EquityPackagePlusService.queryOrderedEquityPackage',
        'origin': 'https://h5.bestpay.com.cn',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': 'https://h5.bestpay.com.cn',
        'sec-ch-ua': '""',
        'sec-ch-ua-mobile': '<SENSITIVE>',
        'sec-ch-ua-platform': '""',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'cross-site',
        'sessionkey': session_result['sessionKey'],
        'sign': res['signHeaders']['sign'],
        'signtype': 'md5',
        'ts': f"{res['signHeaders']['Ts']}",
        'user-agent': 'CtClient;12.0.0;Android;13;PENM00;NDE5NDIx!#!MTkzMjY/CtClient/gi',
        'workspaceid': 'PRD',
        'x-cors-fc1902c211615-prd': '1',
        'version': '2'
    }
    # print(headers)
    # 方法1：使用列表推导式
    byte_values = [res['data'][str(i)] for i in range(len(res['data']))]
    processed_data = bytes(byte_values)
    byte_values = [res['symmetricKey'][str(i)] for i in range(len(res['symmetricKey']))]
    symmetricKey = bytes(byte_values)
    response =  await async_post_new(session, 'https://spanner.bestpay.com.cn:10081', headers, processed_data, symmetricKey)
    response = json.loads(response['data'])
    response = json.loads(response['data'])
    # print(response)
    return response


# 异步权益领取
async def process_equity_receive(session, product_no, session_key, order_no, module_id, unitEquityId, equityNo, qyn,
                                 wt):
    while wt - time.time() > 1:
        await asyncio.sleep(0.6)
        print('时间没到')
    # 构建领取请求参数
    data = process_data({
        "equityNo": equityNo,
        "orderNo": order_no,
        "equityModuleId": module_id,
        "appId": None,
        "encyType": "C005",
        "appType": appType,
        "agreeId": "20211216030100210919654787383364",
        "fromChannelId": "h5",
        "timestamp": int(time.time() * 1000),
        "priceType": "SALES_PRICE",
        "unitEquityId": unitEquityId,
        "productNo": product_no,
        "phoneNo": product_no,
        "requestNo": generate_mixed(),
        "requestDate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sessionKey": session_key,
        "requestSystem": "equity-novel-h5",
        "operator": "",
        "traceLogId": ""
    })

    # 执行领取操作

    for _ in range(cfcs):
        try:
            response = await async_post(session,
                                        'https://mapi-h5.bestpay.com.cn/gapi/ep-product-center/RebateService/manualReceiveEquity',
                                        data)
            rebateFailReason = response.get('errorMsg')

            if response and response.get('success'):
                # 处理领取结果
                r = await check_receipt_status(session, product_no, response['result']['rebateDetailNo'], session_key)
                rebateFailReason = r.get('result', {}).get('rebateFailReason')
            msg = f'{product_no}[{qyn}]{rebateFailReason}'
            print(msg)
            if '登录' in msg:
                return
            if '9.9元视频会员权益包' in msg and '限额' in msg:
                continue

            if '已达上限' in str(rebateFailReason) or '次数已用完' in str(rebateFailReason) or '限额' in str(
                    rebateFailReason) or '风控' in str(rebateFailReason) or '黑名单' in str(rebateFailReason):
                logg[product_no].append(msg)
                return
            if '成功' in str(rebateFailReason):
                logg[product_no].append(msg)
                if qlts:
                    send(msg, msg)
                return

        except Exception as e:
            print(e)
            pass


async def process_equity_receive_new(session, product_no, session_result, order_no, module_id, unitEquityId, equityNo, qyn,
                                     wt):
    while wt - time.time() > 0.5:
        await asyncio.sleep(0.2)
        print(f"时间没到{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
    # 构建领取请求参数
    # data = process_data({
    #     "equityNo": equityNo,
    #     "orderNo": order_no,
    #     "equityModuleId": module_id,
    #     "appId": None,
    #     "encyType": "C005",
    #     "appType": appType,
    #     "agreeId": "20211216030100210919654787383364",
    #     "fromChannelId": "h5",
    #     "timestamp": int(time.time() * 1000),
    #     "priceType": "SALES_PRICE",
    #     "unitEquityId": unitEquityId,
    #     "productNo": product_no,
    #     "phoneNo": product_no,
    #     "requestNo": generate_mixed(),
    #     "requestDate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    #     "sessionKey": session_key,
    #     "requestSystem": "equity-novel-h5",
    #     "operator": "",
    #     "traceLogId": ""
    # })

    h = {
        "operationType": "com.bestpay.opproduct.service.api.EquityService.manualReceiveEquity",
        "data": {
            "equityNo": equityNo,
            "orderNo": order_no,
            "equityModuleId": module_id,
            "appId": None,
            "encyType": "C005",
            "appType": appType,
            "agreeId": "20211216030100210919654787383364",
            "fromChannelId": "h5",
            "timestamp": int(time.time() * 1000),
            "priceType": "SALES_PRICE",
            "unitEquityId": unitEquityId,
            "productNo": product_no,
            "phoneNo": product_no,
            "requestNo": generate_mixed(),
            "requestDate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sessionKey": session_result['sessionKey'],
            "requestSystem": "equity-novel-h5",
            "operator": "",
            "traceLogId": ""
        }
    }

    # 执行领取操作
    body = {
        "app": app,
        "action": "encrypt",
        "code": product_no,
        'data': json.dumps(h)
    }
    res = await async_post(session, f"{__url}", body)
    if res["status"] == 200:
        res = json.loads(res['data'])

    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'appid': res['appid'],
        'authssucode': '<SENSITIVE>',
        'cache-control': 'no-cache',
        'content-type': 'application/json',
        'event-context': json.dumps({
            "session_key": session_result['sessionKey'],  # 使用动态传入的 session_key
            "ip_rid": session_result['memberTypeList'][0]['ipRid'],
            "ip_tid": session_result['ipTid'],
            "auth_ssu_code": "<SENSITIVE>",
            "queryType": "SUCCESS",
            "tnt_id": "0101",
            "env": ""
        }),
        'operation-type': 'com.bestpay.opproduct.service.api.EquityService.manualReceiveEquity',
        'origin': 'https://h5.bestpay.com.cn',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': 'https://h5.bestpay.com.cn',
        'sec-ch-ua': '""',
        'sec-ch-ua-mobile': '<SENSITIVE>',
        'sec-ch-ua-platform': '""',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'cross-site',
        'sessionkey': session_result['sessionKey'],
        'sign': res['signHeaders']['sign'],
        'signtype': 'md5',
        'ts': f"{res['signHeaders']['Ts']}",
        'user-agent': 'CtClient;12.0.0;Android;13;PENM00;NDE5NDIx!#!MTkzMjY/CtClient/gi',
        'workspaceid': 'PRD',
        'x-cors-fc1902c211615-prd': '1',
    }

    # 方法1：使用列表推导式
    byte_values = [res['data'][str(i)] for i in range(len(res['data']))]
    processed_data = bytes(byte_values)
    byte_values = [res['symmetricKey'][str(i)] for i in range(len(res['symmetricKey']))]
    symmetricKey = bytes(byte_values)
    # 控制并发请求数量和间隔
    async def delayed_request(delay, index):
        """带延迟的请求函数"""
        await asyncio.sleep(delay * index)  # 每个请求间隔指定时间
        response = await async_post_new(session, 'https://spanner.bestpay.com.cn:10081', headers, processed_data, symmetricKey)
        response = json.loads(response['data'])
        response = json.loads(response['data'])
        print(f"{qyn} {product_no} {response} {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
        return response


    # 创建带间隔的并发任务
    interval = 0.2  # 每个请求间隔0.1秒
    tasks = [delayed_request(interval, i) for i in range(cfcs)]
    # 确保所有任务完成后再返回
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    for _ in range(1):
        try:
            print(f"{qyn} {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
            response = await async_post_new(session, 'https://spanner.bestpay.com.cn:10081', headers, processed_data,
                                            symmetricKey, qyn)
            response = json.loads(response['data'])
            response = json.loads(response['data'])
            rebateFailReason = response.get('errorMsg')

            if response and response.get('success'):
                # 处理领取结果
                r = await check_receipt_status(session, product_no, response['result']['rebateDetailNo'], session_result['sessionKey'])
                rebateFailReason = r.get('result', {}).get('rebateFailReason')
            msg = f'{product_no}[{qyn}]{rebateFailReason}'
            print(msg)
            logg[product_no].append(msg)
            if '登录' in msg:
                return
            if '9.9元视频会员权益包' in msg and '限额' in msg:
                continue

            if '已达上限' in str(rebateFailReason) or '次数已用完' in str(rebateFailReason) or '限额' in str(
                    rebateFailReason) or '风控' in str(rebateFailReason) or '黑名单' in str(rebateFailReason):
                logg[product_no].append(msg)
                break
            if '成功' in str(rebateFailReason):
                logg[product_no].append(msg)
                if qlts:
                    send(msg, msg)
                break

        except Exception as e:
            print(e)
            pass


# 异步状态检查
async def check_receipt_status(session, product_no, rebate_detail_no, session_key):
    data = process_data({"rebateDetailNo": rebate_detail_no, "encyType": "C005", "appType": appType,
                         "agreeId": "20211216030100210919654787383364", "fromChannelId": "H5",
                         "timestamp": int(time.time() * 1000), "requestNo": generate_mixed(),
                         "requestSystem": "equity-novel-h5",
                         "requestDate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "productNo": product_no,
                         "sessionKey": session_key, "phoneNo": product_no, "operator": "", "traceLogId": ""})
    receiveStatus = "PENDING"

    while receiveStatus == "PENDING":
        response = await async_post(session,
                                    'https://mapi-h5.bestpay.com.cn/gapi/ep-product-center/RebateService/queryUserEquityReceiveStatus',
                                    data)
        receiveStatus = response.get('result', {}).get('receiveStatus')
        if response and receiveStatus == "SUCCESS":
            # logg[product_no].append(f"领取成功: {rebate_detail_no}")
            response['result']['rebateFailReason'] = "领取成功"
            break
        await asyncio.sleep(1)  # 等待重试
    return response


# 主函数
async def process_product2(session, product_no, sem):
    async with sem:
        for _ in range(1):
            try:
                await process_product(session, product_no)

            except:
                await asyncio.sleep(1)  # 等待重试


async def main():
    global kproductNo, public_key

    # 初始化参数
    kproductNo = str(int(datetime.datetime.now().timestamp()))

    # 创建会话
    async with await create_session() as session:
        # 获取初始参数
        public_key = await async_post(session, 'https://mapi-h5.bestpay.com.cn/gapi/mapi-gateway/applyLoginFactor', {
            "productNo": kproductNo,
            "requestType": "H5",
            "traceLogId": trace_log_id()
        })
        public_key = public_key['result']['nonce']

        # 并发处理所有产品
        productNo_lists = os.environ.get('yzf') or productNo_list
        productNo_lists = productNo_lists.split('&')

        # 并发处理所有产品
        sem = asyncio.Semaphore(bfs)
        if kqbf:

            tasks = [process_product2(session, p, sem) for p in productNo_lists]

            # tasks = [process_product(session, p) for p in productNo_lists.split('&')]
            await asyncio.gather(*tasks)

        else:
            for p in productNo_lists:
                await process_product2(session, p, sem)
        print(f"执行结束{datetime.datetime.now().__format__('%Y-%m-%d %H:%M:%S.%f')}")
        # await asyncio.sleep(10)  # 等待执行完毕
        # print(f"执行结束{datetime.datetime.now().__format__('%Y-%m-%d %H:%M:%S.%f')}")
        print("")
        # 输出日志
        for p in logg:
            print(f"{p} 日志:")
            for entry in logg[p]:
                print(entry.replace(p, '    '))
            print("")
        sys.exit(0)



app = "yzf"
__url = f"http://1.95.74.90:5566/invoke?api_key={api_key}"
if __name__ == "__main__":
    rq = datetime.datetime.now().strftime("%Y-%m-%d")
    load_token_file = '<SENSITIVE>'
    try:
        from notify import send

        qlts = 1
        print("加载青龙通知服务成功！")
    except:
        qlts = 0

    try:
        with open(load_token_file, 'r') as f:
            load_token = json.load(f)
    except:
        load_token = {}
    # 配置事件循环策略（Windows需要）
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # 启动异步主函数
    asyncio.run(main())
