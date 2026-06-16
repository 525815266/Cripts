import os
import uuid
import hashlib
import base64
import time
import requests
from datetime import datetime
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

class FanClubAutoBot:
    def __init__(self, phone, password):
        self.session = requests.Session()
        self.phone = phone
        self.password = password
        self.ocr_url = os.environ.get("TY_OCR_URL")
        
        # 伪装请求头
        self.headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json"
        }
        self.session.headers.update(self.headers)
        self.base_url = "https://h5.nty.tv189.com"
        
        # 老板挖出的前台 RSA 公钥，完美还原 JS 加密逻辑
        self.public_key_str = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwWIDoeH/mqK8BDTy+dq0
SeLkjq6cpqnjVlcQAYqKEGEhX0PwOGsudcU/kiNMJNVzTj6aJaLcOIF1q+tMGu6+
G6aJdiI8VNPois1N5U97V5X1J0Ur/MCS1eiSC0+qlMq3J9PDLYSsXogEDzK97Cqz
h+ssPOmkNmNcaqI1X1hFmKmsd33w8aXjExzlK3bU2qzak3xkk0Uw8lX7rcvrjpce
EHqpeDArQEPxfP1EK7lMY6u50PXAuQYgSbvhEHyQh4ybGgv80/kEMV92T6sljVcW
BZQXQ+DM1odt6+gaQlKjnAz4D3WFvtO8LJ9APagdOFSYgMC5+oOXLl8LHnESAhy7
vwIDAQAB
-----END PUBLIC KEY-----"""

    def _generate_clt_params(self):
        """核心验签：生成 cltrid, cltts, cltkey"""
        cltrid = str(uuid.uuid4())
        cltts = datetime.now().strftime("%Y%m%d%H%M%S")
        
        # 拼接签名字符串并 MD5
        sign_str = f"cltrid={cltrid}&cltts={cltts}&"
        cltkey = hashlib.md5(sign_str.encode('utf-8')).hexdigest()
        
        return {
            "cltrid": cltrid,
            "cltts": cltts,
            "cltkey": cltkey
        }

    def encrypt_payload(self, text):
        """还原 JSEncrypt 的 RSA 加密逻辑"""
        try:
            rsa_key = RSA.import_key(self.public_key_str)
            cipher = PKCS1_v1_5.new(rsa_key)
            encrypted_bytes = cipher.encrypt(text.encode('utf-8'))
            return base64.b64encode(encrypted_bytes).decode('utf-8')
        except Exception as e:
            print(f"[-] 严重致命错误！加密模块崩溃，请确认是否执行了 pip install pycryptodome: {e}")
            exit(1)

    def fetch_and_recognize_captcha(self):
        if not self.ocr_url:
            print("[-] 严重警告：遇到风控，但未配置 TY_OCR_URL，无法自动打码！")
            return None
            
        # 【神仙级护航】：自动帮老板补全 xzxxn777/ddddocr 的专属接口后缀
        ocr_api_url = self.ocr_url.rstrip('/')
        if not ocr_api_url.endswith('/classification'):
            ocr_api_url += '/classification'
            
        timestamp = int(time.time() * 1000)
        url = f"{self.base_url}/bff/apis/gen/captcha?t={timestamp}"
        print(f"[*] 正在向服务器拉取图形验证码...")
        
        try:
            res = self.session.get(url, timeout=10)
            if res.status_code == 200:
                image_bytes = res.content
                print(f"[*] 验证码拉取成功，提交给专属接口 [{ocr_api_url}] 进行识别...")
                
                # 【完美兼容】：严格按照 xzxxn777 项目源码要求的 JSON + Base64 格式传参
                img_base64 = base64.b64encode(image_bytes).decode('utf-8')
                payload = {"image": img_base64}
                
                ocr_res = requests.post(ocr_api_url, json=payload, timeout=10)
                
                if ocr_res.status_code != 200:
                    print(f"[-] 致命拦截！您的 ddddocr 接口返回了 {ocr_res.status_code} 错误！")
                    print(f"[-] 报错内容摘要: {ocr_res.text[:100].strip()}...")
                    return None
                
                try:
                    ocr_data = ocr_res.json()
                    # 源码里写明了返回格式就是 {"result": "识别结果"}
                    code = ocr_data.get('result')
                except Exception:
                    code = None
                    
                if code:
                    print(f"[+] ddddocr 神兵天降！自动识别结果: [{code}]")
                    return str(code)
                else:
                    print(f"[-] ddddocr 识别返回为空，可能是图片太模糊。返回原文: {ocr_res.text}")
                    return None
            else:
                print(f"[-] 拉取验证码图片失败，HTTP状态码: {res.status_code}")
                return None
        except Exception as e:
            print(f"[-] 验证码处理流程遭遇网络异常: {e}")
            return None

    def login(self, imgcode=None):
        sign_params = self._generate_clt_params()
        url = f"{self.base_url}/bff/apis/user/acclogin"
        
        # 针对手机号和密码进行独立的 RSA 加密
        encrypted_uname = self.encrypt_payload(self.phone)
        encrypted_upass = self.encrypt_payload(self.password)
        
        payload = {
            "uname": encrypted_uname,
            "upass": encrypted_upass
        }
        
        if imgcode:
            payload["imgcode"] = imgcode
            
        try:
            if imgcode:
                print(f"[*] 正在携带验证码 [{imgcode}] 重新冲锋...")
            else:
            print(f"[*] 正在尝试全自动登录账号: {self.phone[:3]}****{self.phone[-4:]}")
                
            res = self.session.post(url, params=sign_params, json=payload, timeout=10)
            data = res.json()
            
            if data.get("code") == 0:
                print("[+] 登录大成功！已经为您拿到了最新的持久化 Token，会话保持中。")
                return True
            elif data.get("code") == -104:
                print(f"[-] 触发风控: {data.get('msg')}。启动自动打码应急预案！")
                code = self.fetch_and_recognize_captcha()
                if code:
                    return self.login(imgcode=code)
                return False
            else:
                print(f"[-] 老板，登录失败了，接口返回: {data}")
                return False
        except Exception as e:
            print(f"[-] 登录请求异常，网络可能抽风了: {e}")
            return False

    def claim_red_packet(self):
        """卡点自动抢红包"""
        url = f"{self.base_url}/api/zt2024/fanclub-getnew"
        params = {
            "p": "/clt4/xtysxkhd/hd/2024/fsjlbnew/index.json",
            "type": "2"
        }
        
        print(f"[*] 准备就绪，正在向服务器发送抢包请求...")
        try:
            res = self.session.get(url, params=params, timeout=10)
            res.encoding = 'utf-8'
            data = res.json()
            
            if data.get("code") == 0:
                print(f"[+] 恭喜老板！红包到手了！返回信息: {data}")
            else:
                print(f"[-] 抢包失败 (时段限制或已领完): {data.get('msg')}")
                
        except Exception as e:
            print(f"[-] 抢包请求遇到异常: {e}")

if __name__ == "__main__":
    # 为了保护您的隐私，强烈建议从环境变量读取
    # 测试时也可以直接把 "您的手机号" 改成真实号码
    USER_PHONE = "<PHONE>"
    USER_PASS = "2019@memeda"
    
    if USER_PHONE == "您的手机号" or USER_PASS == "您的密码":
        print("[-] 提示：老板，您还没有配置环境变量 TY_PHONE 和 TY_PASSWORD 呢！")
        exit(1)

    bot = FanClubAutoBot(USER_PHONE, USER_PASS)
    
    # 完美业务闭环：登录 -> 成功则执行抢包
    if bot.login():
        bot.claim_red_packet()