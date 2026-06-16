# -*- coding: utf-8 -*-
"""
文小白任务自动化 - 青龙面板版
cron: 10 8 * * *
new Env('文小白');
"""
import os
import requests
import time
from datetime import datetime, timezone

# 导入青龙通知服务
try:
    from notify import send
except ImportError:
    print("错误: 未找到青龙的 notify.py 文件。请确保它在脚本同一目录下或'scripts'文件夹中。")
    # 定义一个假的 send 函数，以防止在没有 notify.py 的情况下脚本完全崩溃
    def send(title, content):
        print("--- 通知 ---")
        print(f"标题: {title}")
        # [修复] 兼容旧版Python的f-string语法
        newline = '\n'
        print(f"内容: {content.replace('<br>', newline)}")
        print("------------")

class WenXiaoBai:
    def __init__(self, token):
        self.token = token
        self.device_id = "23a0fecd-aba7-4e01-9620-8d73eef8a64d"
        self.session = requests.Session()
        self.base_headers = {
            'Connection': 'Keep-Alive',
            'accept': 'application/json',
            'accept-language': 'zh',
            'host': 'api-bj.wenxiaobai.com',
            'user-agent': 'wanyu/4.6.0/7040600 (Android 28)',
            'x-yuanshi-appname': 'wanyu',
            'x-yuanshi-appversionname': '4.6.0',
            'x-yuanshi-platform': 'android',
        }
        self.total_rewards = 0
        self.log_messages = []

    def log(self, message):
        """记录并打印日志"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_message = f"[{timestamp}] {message}"
        print(full_message)
        self.log_messages.append(full_message)

    def get_current_gmt(self):
        """获取当前时间的GMT格式字符串"""
        return datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')

    def get_task_list(self):
        """获取任务列表"""
        self.log("获取任务列表中...")
        url = "https://api-bj.wenxiaobai.com/rest/api/task/list2?isOldVersion=false"
        headers = {
            **self.base_headers,
            'x-date': self.get_current_gmt(),
            'x-yuanshi-authorization': f"Bearer {self.token}",
            'x-yuanshi-deviceid': self.device_id
        }
        try:
            response = self.session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.log(f"获取到 {len(data.get('data', []))} 个任务")
                return data.get('data', [])
            else:
                self.log(f"获取任务失败: HTTP {response.status_code}")
                return None
        except Exception as e:
            self.log(f"获取任务列表网络错误: {e}")
            return None

    def complete_task(self, task_id, task_name=""):
        """完成单个任务"""
        self.log(f"执行任务: {task_name or task_id[:8]}...")
        url = "https://api-bj.wenxiaobai.com/rest/api/task/execute"
        headers = {
            **self.base_headers,
            'Content-Type': 'application/x-www-form-urlencoded',
            'x-date': self.get_current_gmt(),
            'x-yuanshi-authorization': f"Bearer {self.token}",
            'x-yuanshi-deviceid': self.device_id
        }
        data = f"taskId={task_id}"
        try:
            response = self.session.post(url, headers=headers, data=data, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 0 and result.get('data', {}).get('success'):
                    rewards_earned = 0
                    rewards_list = result.get('data', {}).get('rewards', [])
                    if rewards_list:
                        rewards_earned = float(rewards_list[0].get('rewardCount', 0))
                    
                    if rewards_earned > 0:
                        self.total_rewards += rewards_earned
                        self.log(f"成功: 获得 {rewards_earned} 蒜粒")
                    else:
                        self.log("任务完成，无蒜粒奖励")
                else:
                    self.log(f"任务执行失败: {result.get('msg', '未知错误')}")
            else:
                self.log(f"任务失败: HTTP {response.status_code}")
        except Exception as e:
            self.log(f"执行任务网络错误: {e}")

    def run(self):
        """主执行逻辑"""
        self.log("开始执行文小白任务...")
        task_list = self.get_task_list()

        if not task_list:
            self.log("未能获取到任务列表，脚本终止。")
            return

        AD_TASK_IDENTIFIER = '浏览广告'
        AD_TASK_EXECUTION_COUNT = 150
        AD_TASK_DELAY = 5

        for task in task_list:
            task_name = task.get('taskName', '未知任务')
            task_id = task.get('taskId')
            status = task.get('status')
            
            # 特殊任务：浏览广告
            if AD_TASK_IDENTIFIER in task_name:
                self.log(f"检测到特殊任务: \"{task_name}\"")
                if status == 3:
                    self.log(f"任务 \"{task_name}\" 已完成 (status: 3)，跳过。")
                    continue
                
                self.log(f"开始执行 \"{task_name}\" {AD_TASK_EXECUTION_COUNT} 次...")
                for i in range(AD_TASK_EXECUTION_COUNT):
                    self.log(f"执行第 {i + 1}/{AD_TASK_EXECUTION_COUNT} 次...")
                    self.complete_task(task_id, task_name)
                    if i < AD_TASK_EXECUTION_COUNT - 1:
                        self.log(f"等待 {AD_TASK_DELAY} 秒...")
                        time.sleep(AD_TASK_DELAY)
                self.log(f"特殊任务 \"{task_name}\" 执行完毕")
                continue

            # 常规任务
            max_times = int(task.get('maxFinishTimes', 0))
            progress = int(task.get('progress', 0))
            
            is_completed = (status == 3) or (status != 1 and max_times == 0) or (max_times > 0 and progress >= max_times)

            if is_completed:
                self.log(f"常规任务 \"{task_name}\" 已完成，跳过")
            else:
                remaining = (max_times - progress) if max_times > 0 else 1
                self.log(f"准备执行常规任务: \"{task_name}\"，需 {remaining} 次")
                for i in range(remaining):
                    self.complete_task(task_id, task_name)
                    if i < remaining - 1:
                        time.sleep(2) # 常规任务间隔2秒

        self.log(f"所有任务执行完毕！今日累计获得 {self.total_rewards:.2f} 蒜粒")
        return self.total_rewards, "\n".join(self.log_messages)


if __name__ == '__main__':
    # 从环境变量中获取 token，支持多账号
    tokens = os.environ.get("WXB_TOKEN")
    if not tokens:
        print("错误: 未找到环境变量 WXB_TOKEN。请在青龙面板中配置。")
        exit()

    token_list = [t.strip() for t in tokens.split('&') if t.strip()]
    if not token_list:
        print("错误: WXB_TOKEN 环境变量值为空。")
        exit()

    print(f"检测到 {len(token_list)} 个账号，开始执行...")
    
    overall_summary = []
    for i, token in enumerate(token_list):
        print(f"\n--- 账号 {i+1} 开始运行 ---")
        try:
            wxb = WenXiaoBai(token)
            total_rewards, log_details = wxb.run()
            summary = f"账号 {i+1}: 获得 {total_rewards:.2f} 蒜粒"
            overall_summary.append(summary)
            print(f"--- 账号 {i+1} 运行结束 ---\n")
        except Exception as e:
            print(f"账号 {i+1} 运行出错: {e}")
            overall_summary.append(f"账号 {i+1}: 运行失败")
    
    # 发送最终通知
    if overall_summary:
        notification_title = "文小白任务完成"
        notification_content = "<br>".join(overall_summary)
        send(notification_title, notification_content)