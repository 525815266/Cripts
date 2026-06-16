"""
天翼云电脑 EAI 聊天每日积分 - 纯净稳定版
"""

import time
import random
import json
import threading
import os
import sys
from typing import Union, Optional

from DrissionPage import ChromiumPage, ChromiumOptions
import ddddocr

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PRESET_MESSAGES = [
    "今天北京天气怎么样？（简短回答）",
    "给我讲一个冷笑话。（简短回答）",
    "来一首古诗。（简短回答）",
    "空腹可以吃饭吗？（简短回答）",
    "推荐一部人生必看电影。（简短回答）"
]

def save_cookies(page: ChromiumPage, file_path: str) -> None:
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        cookies = page.cookies()
        if not cookies: return
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=4)
        print(f"[*] Cookie 已成功保存至本地缓存")
    except Exception as e:
        pass

def load_cookies(page: ChromiumPage, file_path: str) -> bool:
    if not os.path.exists(file_path): return False
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
        page.set.cookies(cookies)
        return True
    except: return False

def init_browser_options() -> ChromiumOptions:
    options = ChromiumOptions()
    options.set_argument('--no-sandbox')
    options.set_argument('--disable-gpu')
    options.set_argument('--disable-dev-shm-usage')
    options.headless()
    return options

def fill_credentials(page: ChromiumPage, username: str, password: str) -> None:
    page.ele('css:input[type="text"]').clear()
    page.ele('css:input[type="text"]').input(username)
    page.ele('css:input[type="password"]').clear()
    page.ele('css:input[type="password"]').input(password)

def handle_captcha(page: ChromiumPage) -> None:
    captcha_container = page.ele('css:.fgt-capt-ct', timeout=2)
    if not captcha_container: return
    pic_bytes = captcha_container.ele('css:img').get_screenshot(as_bytes=True)
    ocr_result = get_bytes_numeric_captcha(pic_bytes)
    input_ele = captcha_container.ele('css:input[placeholder="输入图形验证码"]')
    input_ele.clear()
    input_ele.input(ocr_result)

def analyze_login_response(response_body: Union[dict, str, None]) -> int:
    if not response_body or not isinstance(response_body, dict): return 0
    code = response_body.get('code')
    msg = response_body.get('msg', '')
    if code == 51040 and "用户名或密码错误" in msg: return 1
    elif code == 51030: return 2
    elif code == 51040 and "图形验证码" in msg: return 3
    return -1

def execute_login_with_listener(page: ChromiumPage, target_url: str, username: str, password: str, max_retries: int = 3) -> bool:
    page.get(target_url)
    page.wait.load_start()
    fill_credentials(page, username, password)

    for attempt in range(max_retries):
        handle_captcha(page)
        if not page.wait.ele_displayed('css:button.lgm-submit-ct', timeout=5): return False
        login_button = page.ele('css:button.lgm-submit-ct')
        page.listen.start('api/auth/iam/login')
        login_button.click()
        
        packet = page.listen.wait(timeout=5)
        page.listen.stop()
        if not packet: return True
        status_code = analyze_login_response(packet.response.body)

        if status_code == 0:
            return True
        elif status_code in [2, 3]:
            time.sleep(1)
            continue
        else: return False
    return False

def close_announcement_popups(page: ChromiumPage):
    try:
        page.actions.type('\x1b')
        time.sleep(0.5)
        page.actions.type('\x1b')
        
        popups_keywords = ['我知道了', '关闭', '确定', '开始体验', '立即体验', '同意']
        for kw in popups_keywords:
            btn = page.ele(f'text:{kw}', timeout=0.5)
            if btn and btn.is_displayed:
                btn.click()
                time.sleep(1)
                
        close_icons = page.eles('css:[class*="close"]')
        if close_icons:
            for icon in close_icons:
                if icon.is_displayed:
                    icon.click()
                    time.sleep(0.5)
    except:
        pass

def chat_and_earn_points(page: ChromiumPage) -> None:
    time.sleep(3) 
    
    real_input = page.ele('tag:textarea', timeout=3) or \
                 page.ele('css:div.input-box.input-wrap', timeout=3) or \
                 page.ele('@placeholder:有问题尽管问我', timeout=3)
                 
    if not real_input:
        print("[!] 未找到聊天输入框，任务终止。")
        return

    message = random.choice(PRESET_MESSAGES)
    real_input.click()
    time.sleep(1)
    
    real_input.input(message)
    time.sleep(0.5)
    real_input.input('\n')
    
    print(f"[*] 发送问题: {message}")
    time.sleep(8) 

    reply_elements = page.eles('css:.markdown-body') or page.eles('css:.markdown-content') or page.eles('css:.message-content') or page.eles('tag:p')
    
    if reply_elements:
        latest_reply = reply_elements[-1]
        previous_text = ""
        stable_count = 0

        for _ in range(60):
            current_text = latest_reply.text
            if current_text and current_text == previous_text:
                stable_count += 1
            else:
                stable_count = 0
                previous_text = current_text
            if stable_count >= 3: break
            time.sleep(1)

        print("[*] AI 回复:")
        reply_text = latest_reply.text.strip().replace('\n', '  ')
        print(reply_text[:100] + "..." if len(reply_text) > 100 else reply_text)
        print("[*] 🎉 积分任务通关！")
    else:
        print("[*] 消息已发送，任务完成。")

class NumericOcrSolver:
    _instance: Optional["NumericOcrSolver"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "NumericOcrSolver":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_engine()
        return cls._instance

    def _init_engine(self) -> None:
        self.ocr = ddddocr.DdddOcr(show_ad=False)
        self.ocr.set_ranges(0)

    def solve(self, image_data: bytes) -> str:
        try: return self.ocr.classification(image_data)
        except Exception as e: return f"Error: {str(e)}"

def get_bytes_numeric_captcha(image_bytes: bytes) -> str:
    return NumericOcrSolver().solve(image_bytes)

def process_account(username, password):
    print(f"\n======================================")
    print(f"执行账号: {username}")
    print(f"======================================")
    
    login_url = "https://desk.ctyun.cn/cloudB/dy/iam/api/auth/iam/cas/login?service=https%3A%2F%2Feaichat.ctyun.cn%3A443%2Fchat%2F%23%2Faichat&consent=false"
    chat_url = "https://eaichat.ctyun.cn/chat/#/aichat"
    cookie_file = f"/ql/data/scripts/ctyun_cookies_{username}.json"

    page = ChromiumPage(addr_or_opts=init_browser_options())

    try:
        is_logged_in = False
        page.get(chat_url)
        time.sleep(1)

        if load_cookies(page, cookie_file):
            page.get(chat_url)
            time.sleep(3)
            close_announcement_popups(page)
            
            if page.ele('tag:textarea', timeout=3) or page.ele('css:div.input-box.input-wrap', timeout=3):
                print(f"[*] {username} 免密登录成功")
                is_logged_in = True
            else:
                print("[-] 缓存失效，执行账密登录...")

        if not is_logged_in:
            if execute_login_with_listener(page, login_url, username, password):
                time.sleep(5) 
                page.get(chat_url)
                time.sleep(4) 
                
                close_announcement_popups(page)
                
                if page.ele('tag:textarea', timeout=4) or page.ele('css:div.input-box.input-wrap', timeout=4):
                    print("[*] 登录成功并进入聊天室")
                    save_cookies(page, cookie_file)
                    is_logged_in = True
                else:
                    print("[!] 无法定位聊天输入框")
            else:
                print(f"[!] 登录失败")

        if is_logged_in:
            chat_and_earn_points(page)
            
    except Exception as e:
        print(f"[!] 执行异常: {e}")
    finally:
        page.quit()
        time.sleep(2)

def main() -> None:
    env_accounts = os.getenv('TIANYI_ACCOUNTS')
    if not env_accounts:
        print("未检测到环境变量 TIANYI_ACCOUNTS")
        sys.exit(1)

    accounts = env_accounts.split('&')
    
    for index, account_info in enumerate(accounts):
        try:
            username, password = account_info.split('@')
            process_account(username.strip(), password.strip())
        except ValueError:
            pass

if __name__ == "__main__":
    main()
