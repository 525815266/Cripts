# 当前脚本来自于 http://script.345yun.cn 脚本库下载！
# 脚本库官方QQ群: 429274456
# 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
# 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
# 您在使用脚本库下载的脚本时自行检查判断风险。
# 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。

import os
import sys
import time
import random
import json
import requests
from datetime import datetime
from urllib.parse import quote

    
BASE_URL = "https://sxs-consumer.nfsq.com.cn"
LOTTERY_API = "/geement.marketinglottery/api/v1/marketinglottery"
RECEIVE_API = "/geement.actjextra/api/v1/act/win/goods/160goods/receive"            

         
TASK_LIST_API = "/geement.marketingplay/api/v1/task"
TASK_JOIN_API = "/geement.marketingplay/api/v1/task/join"
ACT_CHECK_API = "/geement.actjextra/api/v1/act/check"
LOTTERY_COUNT_API = "/geement.actjextra/api/v1/act/lottery/data/todaycount"            
WIN_LIST_API = "/geement.actjextra/api/v1/act/win/goods/simple"          

      
SCENE_CODE_1 = "SCENE-2510301508361"             
SCENE_CODE_2 = "SCENE-2510301509021"             
GROUP_ID = "2510301511011"         
ACT_CODE = "ACT2510301507191"             
ACT_CODE_2 = "ACT2510301505581"             

                    
                                 

          
WINNING_POSITIONS_FILE = "winning_positions.json"

                    
USER_AGENTS = [
            
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42(0x18002a2d) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.43(0x18002b2f) NetType/4G Language/zh_CN",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38(0x18002626) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.41(0x18002929) NetType/5G Language/zh_CN",
    
             
    "Mozilla/5.0 (Linux; Android 13; SM-G9980 Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.42.2480(0x28002A37) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (Linux; Android 12; Mi 12 Build/SKQ1.211006.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.40.2420(0x28002829) NetType/4G Language/zh_CN",
    "Mozilla/5.0 (Linux; Android 11; HUAWEI P50 Build/HUAWEIANA-AN00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.39.2340(0x28002739) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (Linux; Android 14; OPPO Find X6 Pro Build/TP1A.220905.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.43.2501(0x28002B45) NetType/5G Language/zh_CN",
    "Mozilla/5.0 (Linux; Android 13; vivo X90 Pro+ Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.41.2400(0x28002929) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (Linux; Android 12; OnePlus 11 Build/SKQ1.221119.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.38.2340(0x28002626) NetType/4G Language/zh_CN",
]

def parse_custom_locations(location_str):
           
    if not location_str:
        return []
    
    locations = []
               
    lines = location_str.replace('@', '\n').strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split(',')
        if len(parts) >= 5:
            try:
                lng = float(parts[0].strip())
                lat = float(parts[1].strip())
                province = parts[2].strip()
                city = parts[3].strip()
                area = parts[4].strip()
                
                locations.append({
                    "province": province,
                    "city": city,
                    "area": area,
                    "lng_range": (lng - 0.01, lng + 0.01),         
                    "lat_range": (lat - 0.01, lat + 0.01)
                })
            except:
                pass
    
    return locations

                                     
CHINA_CITIES = [
         
    {"province": "北京市", "city": "北京市", "area": "朝阳区", "lng_range": (116.20, 116.60), "lat_range": (39.80, 40.10)},
    {"province": "北京市", "city": "北京市", "area": "海淀区", "lng_range": (116.20, 116.40), "lat_range": (39.90, 40.10)},
    {"province": "上海市", "city": "上海市", "area": "浦东新区", "lng_range": (121.30, 121.80), "lat_range": (31.00, 31.40)},
    {"province": "上海市", "city": "上海市", "area": "徐汇区", "lng_range": (121.40, 121.50), "lat_range": (31.15, 31.25)},
    {"province": "天津市", "city": "天津市", "area": "和平区", "lng_range": (117.15, 117.25), "lat_range": (39.08, 39.15)},
    {"province": "天津市", "city": "天津市", "area": "南开区", "lng_range": (117.10, 117.20), "lat_range": (39.10, 39.18)},
    {"province": "重庆市", "city": "重庆市", "area": "渝中区", "lng_range": (106.50, 106.60), "lat_range": (29.52, 29.60)},
    {"province": "重庆市", "city": "重庆市", "area": "江北区", "lng_range": (106.52, 106.62), "lat_range": (29.55, 29.63)},
    
          
    {"province": "江苏省", "city": "南京市", "area": "玄武区", "lng_range": (118.70, 119.00), "lat_range": (31.90, 32.20)},
    {"province": "江苏省", "city": "苏州市", "area": "姑苏区", "lng_range": (120.55, 120.70), "lat_range": (31.25, 31.40)},
    {"province": "江苏省", "city": "无锡市", "area": "梁溪区", "lng_range": (120.25, 120.35), "lat_range": (31.50, 31.60)},
    {"province": "江苏省", "city": "常州市", "area": "天宁区", "lng_range": (119.90, 120.05), "lat_range": (31.75, 31.85)},
    {"province": "浙江省", "city": "杭州市", "area": "西湖区", "lng_range": (120.00, 120.30), "lat_range": (30.10, 30.40)},
    {"province": "浙江省", "city": "宁波市", "area": "海曙区", "lng_range": (121.50, 121.65), "lat_range": (29.82, 29.92)},
    {"province": "浙江省", "city": "温州市", "area": "鹿城区", "lng_range": (120.60, 120.70), "lat_range": (28.00, 28.10)},
    {"province": "浙江省", "city": "嘉兴市", "area": "南湖区", "lng_range": (120.70, 120.85), "lat_range": (30.70, 30.82)},
    {"province": "安徽省", "city": "合肥市", "area": "蜀山区", "lng_range": (117.20, 117.35), "lat_range": (31.80, 31.90)},
    {"province": "安徽省", "city": "芜湖市", "area": "镜湖区", "lng_range": (118.35, 118.45), "lat_range": (31.32, 31.42)},
    {"province": "福建省", "city": "福州市", "area": "鼓楼区", "lng_range": (119.28, 119.38), "lat_range": (26.05, 26.15)},
    {"province": "福建省", "city": "厦门市", "area": "思明区", "lng_range": (118.00, 118.20), "lat_range": (24.40, 24.60)},
    {"province": "福建省", "city": "泉州市", "area": "丰泽区", "lng_range": (118.55, 118.65), "lat_range": (24.88, 24.98)},
    {"province": "江西省", "city": "南昌市", "area": "东湖区", "lng_range": (115.85, 115.95), "lat_range": (28.65, 28.75)},
    {"province": "江西省", "city": "赣州市", "area": "章贡区", "lng_range": (114.90, 115.00), "lat_range": (25.80, 25.90)},
    {"province": "山东省", "city": "济南市", "area": "历下区", "lng_range": (116.90, 117.20), "lat_range": (36.60, 36.80)},
    {"province": "山东省", "city": "青岛市", "area": "市南区", "lng_range": (120.35, 120.45), "lat_range": (36.05, 36.15)},
    {"province": "山东省", "city": "烟台市", "area": "芝罘区", "lng_range": (121.35, 121.45), "lat_range": (37.50, 37.60)},
    {"province": "山东省", "city": "潍坊市", "area": "奎文区", "lng_range": (119.08, 119.18), "lat_range": (36.68, 36.78)},
    
          
    {"province": "广东省", "city": "广州市", "area": "天河区", "lng_range": (113.20, 113.50), "lat_range": (23.00, 23.30)},
    {"province": "广东省", "city": "深圳市", "area": "南山区", "lng_range": (113.90, 114.10), "lat_range": (22.50, 22.70)},
    {"province": "广东省", "city": "深圳市", "area": "福田区", "lng_range": (114.03, 114.13), "lat_range": (22.52, 22.62)},
    {"province": "广东省", "city": "东莞市", "area": "南城区", "lng_range": (113.70, 113.85), "lat_range": (23.00, 23.10)},
    {"province": "广东省", "city": "佛山市", "area": "禅城区", "lng_range": (113.08, 113.18), "lat_range": (23.00, 23.10)},
    {"province": "广东省", "city": "珠海市", "area": "香洲区", "lng_range": (113.52, 113.62), "lat_range": (22.22, 22.32)},
    {"province": "广西壮族自治区", "city": "南宁市", "area": "青秀区", "lng_range": (108.30, 108.45), "lat_range": (22.78, 22.88)},
    {"province": "广西壮族自治区", "city": "桂林市", "area": "秀峰区", "lng_range": (110.25, 110.35), "lat_range": (25.25, 25.35)},
    {"province": "海南省", "city": "海口市", "area": "龙华区", "lng_range": (110.28, 110.38), "lat_range": (20.02, 20.12)},
    {"province": "海南省", "city": "三亚市", "area": "吉阳区", "lng_range": (109.45, 109.60), "lat_range": (18.22, 18.32)},
    
          
    {"province": "湖北省", "city": "武汉市", "area": "武昌区", "lng_range": (114.20, 114.50), "lat_range": (30.50, 30.70)},
    {"province": "湖北省", "city": "武汉市", "area": "江汉区", "lng_range": (114.25, 114.35), "lat_range": (30.58, 30.68)},
    {"province": "湖北省", "city": "宜昌市", "area": "西陵区", "lng_range": (111.25, 111.35), "lat_range": (30.68, 30.78)},
    {"province": "湖南省", "city": "长沙市", "area": "岳麓区", "lng_range": (112.80, 113.10), "lat_range": (28.10, 28.30)},
    {"province": "湖南省", "city": "长沙市", "area": "芙蓉区", "lng_range": (113.00, 113.10), "lat_range": (28.18, 28.28)},
    {"province": "湖南省", "city": "株洲市", "area": "荷塘区", "lng_range": (113.10, 113.20), "lat_range": (27.80, 27.90)},
    {"province": "河南省", "city": "郑州市", "area": "金水区", "lng_range": (113.50, 113.80), "lat_range": (34.70, 34.90)},
    {"province": "河南省", "city": "洛阳市", "area": "西工区", "lng_range": (112.40, 112.50), "lat_range": (34.65, 34.75)},
    {"province": "河南省", "city": "开封市", "area": "龙亭区", "lng_range": (114.30, 114.40), "lat_range": (34.78, 34.88)},
    
          
    {"province": "河北省", "city": "石家庄市", "area": "长安区", "lng_range": (114.40, 114.70), "lat_range": (38.00, 38.20)},
    {"province": "河北省", "city": "唐山市", "area": "路北区", "lng_range": (118.15, 118.25), "lat_range": (39.60, 39.70)},
    {"province": "河北省", "city": "保定市", "area": "莲池区", "lng_range": (115.45, 115.55), "lat_range": (38.85, 38.95)},
    {"province": "山西省", "city": "太原市", "area": "小店区", "lng_range": (112.50, 112.65), "lat_range": (37.70, 37.85)},
    {"province": "山西省", "city": "大同市", "area": "平城区", "lng_range": (113.25, 113.40), "lat_range": (40.05, 40.15)},
    {"province": "内蒙古自治区", "city": "呼和浩特市", "area": "新城区", "lng_range": (111.60, 111.75), "lat_range": (40.80, 40.95)},
    {"province": "内蒙古自治区", "city": "包头市", "area": "昆都仑区", "lng_range": (109.80, 109.95), "lat_range": (40.62, 40.72)},
    
          
    {"province": "辽宁省", "city": "沈阳市", "area": "和平区", "lng_range": (123.30, 123.60), "lat_range": (41.70, 41.90)},
    {"province": "辽宁省", "city": "大连市", "area": "中山区", "lng_range": (121.60, 121.70), "lat_range": (38.90, 39.00)},
    {"province": "辽宁省", "city": "鞍山市", "area": "铁东区", "lng_range": (122.95, 123.05), "lat_range": (41.08, 41.18)},
    {"province": "吉林省", "city": "长春市", "area": "朝阳区", "lng_range": (125.25, 125.40), "lat_range": (43.82, 43.95)},
    {"province": "吉林省", "city": "吉林市", "area": "船营区", "lng_range": (126.50, 126.65), "lat_range": (43.80, 43.92)},
    {"province": "黑龙江省", "city": "哈尔滨市", "area": "南岗区", "lng_range": (126.60, 126.75), "lat_range": (45.70, 45.82)},
    {"province": "黑龙江省", "city": "齐齐哈尔市", "area": "建华区", "lng_range": (123.90, 124.00), "lat_range": (47.32, 47.42)},
    
          
    {"province": "四川省", "city": "成都市", "area": "武侯区", "lng_range": (103.90, 104.30), "lat_range": (30.50, 30.80)},
    {"province": "四川省", "city": "成都市", "area": "锦江区", "lng_range": (104.05, 104.15), "lat_range": (30.62, 30.72)},
    {"province": "四川省", "city": "绵阳市", "area": "涪城区", "lng_range": (104.65, 104.75), "lat_range": (31.45, 31.55)},
    {"province": "贵州省", "city": "贵阳市", "area": "南明区", "lng_range": (106.65, 106.80), "lat_range": (26.55, 26.68)},
    {"province": "贵州省", "city": "遵义市", "area": "红花岗区", "lng_range": (106.88, 106.98), "lat_range": (27.68, 27.78)},
    {"province": "云南省", "city": "昆明市", "area": "五华区", "lng_range": (102.65, 102.80), "lat_range": (25.00, 25.15)},
    {"province": "云南省", "city": "大理市", "area": "大理镇", "lng_range": (100.20, 100.30), "lat_range": (25.58, 25.68)},
    {"province": "西藏自治区", "city": "拉萨市", "area": "城关区", "lng_range": (91.10, 91.20), "lat_range": (29.62, 29.72)},
    
          
    {"province": "陕西省", "city": "西安市", "area": "雁塔区", "lng_range": (108.80, 109.10), "lat_range": (34.10, 34.40)},
    {"province": "陕西省", "city": "西安市", "area": "碑林区", "lng_range": (108.90, 109.00), "lat_range": (34.22, 34.32)},
    {"province": "陕西省", "city": "咸阳市", "area": "秦都区", "lng_range": (108.68, 108.78), "lat_range": (34.32, 34.42)},
    {"province": "甘肃省", "city": "兰州市", "area": "城关区", "lng_range": (103.75, 103.90), "lat_range": (36.02, 36.15)},
    {"province": "甘肃省", "city": "天水市", "area": "秦州区", "lng_range": (105.68, 105.78), "lat_range": (34.55, 34.65)},
    {"province": "青海省", "city": "西宁市", "area": "城东区", "lng_range": (101.70, 101.85), "lat_range": (36.58, 36.70)},
    {"province": "宁夏回族自治区", "city": "银川市", "area": "兴庆区", "lng_range": (106.20, 106.35), "lat_range": (38.45, 38.58)},
    {"province": "新疆维吾尔自治区", "city": "乌鲁木齐市", "area": "天山区", "lng_range": (87.55, 87.70), "lat_range": (43.75, 43.88)},
    {"province": "新疆维吾尔自治区", "city": "喀什市", "area": "喀什镇", "lng_range": (75.95, 76.10), "lat_range": (39.45, 39.58)},
]

class NongFuShanQuan:
    def __init__(self, unique_identity, apitoken, custom_locations=None):
        self.unique_identity = unique_identity
        self.apitoken = apitoken
        self.session = requests.Session()
        self.log_ids = []
        self.winning_positions = self.load_winning_positions()
        self.first_prize_count = 0         
        self.completed_tasks = 0          
        self.task_rewards = 0             
        self.prize_list = []              
        self.user_agent = random.choice(USER_AGENTS)                  
        self.custom_locations = custom_locations or []           
        
    def get_headers(self, content_type="application/json"):
                   
        return {
            "unique_identity": self.unique_identity,
            "apitoken": self.apitoken,
            "User-Agent": self.user_agent,
            "Content-Type": content_type,
            "Accept": "*/*",
            "Referer": "https://servicewechat.com/"
        }
    
    def log(self, msg):
                  
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")
    
    def check_activity(self):
                    
        url = f"{BASE_URL}{ACT_CHECK_API}?act_code={ACT_CODE}"
        
        try:
            response = self.session.get(url, headers=self.get_headers(), timeout=30)
            result = response.json()
            
            if result.get("success"):
                data = result.get("data", {})
                max_count = data.get('user_max_scan_count_perday', 0)
                self.log(f"✅ 活动进行中, 每日基础次数: {max_count}")
                return max_count
            else:
                self.log(f"❌ 活动检查失败: {result.get('msg')}")
                return 0
                
        except Exception as e:
            self.log(f"❌ 活动检查异常: {str(e)}")
            return 0
    
    def get_today_lottery_count(self):
                       
        url = f"{BASE_URL}{LOTTERY_COUNT_API}?act_code={ACT_CODE}"
        
        try:
            response = self.session.get(url, headers=self.get_headers(), timeout=30)
            result = response.json()
            
            if result.get("success"):
                used_count = result.get("data", 0)
                self.log(f"✅ 基础已使用: {used_count}次")
                return used_count
            else:
                self.log(f"❌ 查询今日抽奖次数失败: {result.get('msg')}")
                return 0
                
        except Exception as e:
            self.log(f"❌ 查询今日抽奖次数异常: {str(e)}")
            return 0
    
    def get_task_list(self):
                    
        url = f"{BASE_URL}{TASK_LIST_API}?pageNum=1&pageSize=10&task_status=2&status=1&group_id={GROUP_ID}&is_db=1"
        
        try:
            response = self.session.get(url, headers=self.get_headers(), timeout=30)
            result = response.json()
            
            if result.get("success"):
                tasks = result.get("data", [])
                self.log(f"✅ 获取任务: {len(tasks)}个")
                return tasks
            else:
                self.log(f"❌ 获取任务列表失败: {result.get('msg')}")
                return []
                
        except Exception as e:
            self.log(f"❌ 获取任务列表异常: {str(e)}")
            return []
    
    def join_task(self, task_id, task_name):
                  
        action_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        action_time_encoded = quote(action_time)
        url = f"{BASE_URL}{TASK_JOIN_API}?action_time={action_time_encoded}&task_id={task_id}"
        
        try:
            response = self.session.get(url, headers=self.get_headers(), timeout=30)
            result = response.json()
            
            if result.get("success"):
                self.log(f"  ✅ 任务完成: {task_name}")
                data = result.get("data", {})
                if isinstance(data, dict):
                    reward_count = data.get("reward_count", 0)
                    if reward_count > 0:
                        self.log(f"  🎁 获得 {reward_count} 次抽奖机会")
                        self.task_rewards += reward_count
                return True
            else:
                msg = result.get('msg', '未知错误')
                if '已完成' in msg or '已参与' in msg:
                    self.log(f"  ℹ️ {task_name}: {msg}")
                else:
                    self.log(f"  ❌ {task_name} 失败: {msg}")
                return False
                
        except Exception as e:
            self.log(f"  ❌ {task_name} 异常: {str(e)}")
            return False
    
    def do_all_tasks(self):
                    
        self.log(f"📋 阶段1: 执行任务")
        
                
        max_count = self.check_activity()
        if max_count == 0:
            self.log("⚠️ 活动状态异常，跳过任务执行")
            return max_count
        
        time.sleep(2)
        
                
        tasks = self.get_task_list()
        
        if not tasks:
            self.log("⚠️ 没有可执行的任务")
            return max_count
        
        self.log(f"🎯 任务总数: {len(tasks)}")
        
        for task in tasks:
            task_id = task.get("id")
            task_name = task.get("name", "未知任务")
            complete_status = task.get("complete_status", 0)
            complete_count = task.get("complete_count", 0)
            allow_complete_count = task.get("allow_complete_count", 1)
            
                          
            if complete_status == 0 and complete_count < allow_complete_count:
                self.log(f"▶️ {task_name}...")
                if self.join_task(task_id, task_name):
                    self.completed_tasks += 1
                    self.log(f"  ✅ 完成")
                
                      
                time.sleep(random.uniform(2, 4))
        
        if self.completed_tasks > 0:
            self.log(f"✅ 完成任务: {self.completed_tasks}个, 增加抽奖次数: +{self.completed_tasks}")
        
        return max_count
    
    def load_winning_positions(self):
                      
        try:
            if os.path.exists(WINNING_POSITIONS_FILE):
                with open(WINNING_POSITIONS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.log(f"加载中奖位置记录失败: {str(e)}")
        return []
    
    def save_winning_position(self, position_data):
                    
        try:
            self.winning_positions.append(position_data)
            with open(WINNING_POSITIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.winning_positions, f, ensure_ascii=False, indent=2)
            self.log(f"✅ 已保存中奖位置到数据库")
        except Exception as e:
            self.log(f"保存中奖位置失败: {str(e)}")
    
    def generate_random_location(self, use_winning=False):
                      
                     
        if self.custom_locations:
            city_data = random.choice(self.custom_locations)
            self.log(f"📍 使用自定义位置: {city_data['province']} {city_data['city']}")
                      
        elif use_winning and self.winning_positions:
            position = random.choice(self.winning_positions)
            self.log(f"🎯 使用已验证的中奖位置: {position['province']} {position['city']}")
            return position
        else:
                       
            city_data = random.choice(CHINA_CITIES)
        
                        
        longitude = round(random.uniform(city_data["lng_range"][0], city_data["lng_range"][1]), 14)
        latitude = round(random.uniform(city_data["lat_range"][0], city_data["lat_range"][1]), 14)
        
                 
        street_num = random.randint(1, 999)
        
        location = {
            "province": city_data["province"],
            "city": city_data["city"],
            "area": city_data["area"],
            "address": f"{city_data['province']} {city_data['city']}{city_data['area']}第{street_num}号",
            "longitude": longitude,
            "latitude": latitude
        }
        
        return location
    
    def lottery(self, location, lottery_count):
                   
        url = BASE_URL + LOTTERY_API
        
                            
        scene_code = SCENE_CODE_1 if lottery_count <= 3 else SCENE_CODE_2
        
        data = {
            "code": scene_code,
            "provice_name": location["province"],
            "city_name": location["city"],
            "area_name": location["area"],
            "address": location["address"],
            "longitude": location["longitude"],
            "dimension": location["latitude"]
        }
        
        scene_type = "SCENE1" if lottery_count <= 3 else "SCENE2"
        self.log(f"📍 {location['city']} {location['area']} [{scene_type}]")
        
        try:
            response = self.session.post(url, json=data, headers=self.get_headers(), timeout=30)
            result = response.json()
            
            if result.get("success"):
                
                        
                data = result.get("data", {})
                if isinstance(data, dict):
                                            
                    prizedto = data.get("prizedto", {})
                    if prizedto:
                        prize_name = prizedto.get("prize_name", "未知奖品")
                        prize_level = prizedto.get("prize_level", "")
                        prize_type = prizedto.get("prize_type", "")
                        
                                            
                        goods = prizedto.get("goods", [])
                        if goods and len(goods) > 0:
                            log_id = goods[0].get("log_id")
                            goods_name = goods[0].get("goods_name", prize_name)
                            
                            if log_id:
                                self.log_ids.append(log_id)
                                self.prize_list.append(f"{prize_name} ({prize_level})" if prize_level else prize_name)
                                self.log(f"🎉 {prize_name} ({prize_level})")
                                
                                          
                                if "一等奖" in prize_level or "一等奖" in prize_name:
                                    self.first_prize_count += 1
                                    self.log(f"🏆🏆🏆 一等奖！！！已中 {self.first_prize_count} 次一等奖")
                                    
                                               
                                    winning_info = location.copy()
                                    winning_info.update({
                                        "prize_name": prize_name,
                                        "prize_level": prize_level,
                                        "prize_type": prize_type,
                                        "log_id": log_id,
                                        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                    })
                                    self.save_winning_position(winning_info)
                                
                                return True
                        else:
                            self.log(f"ℹ️ 抽奖结果: {prize_name} ({prize_level})")
                    else:
                        self.log(f"ℹ️ 抽奖结果: {data}")
                
                return True
            else:
                msg = result.get('msg', '未知错误')
                
                                 
                if "今日活动抽奖次数已经达到最大" in msg or "抽奖次数已用完" in msg:
                    self.log(f"❌ 抽奖失败: {msg}")
                    return "LIMIT_REACHED"
                elif "资格卡券" in msg and "不足" in msg:
                    self.log(f"❌ 抽奖失败: 用户资格卡券不足")
                    return "LIMIT_REACHED"
                else:
                    self.log(f"❌ 抽奖失败: {msg}")
                
                return False
                
        except Exception as e:
            self.log(f"❌ 抽奖异常: {str(e)}")
            return False
    
    def get_win_list(self):
                    
        act_codes = f"{ACT_CODE},{ACT_CODE_2}"
        url = f"{BASE_URL}{WIN_LIST_API}?act_codes={act_codes}"
        
        try:
            response = self.session.get(
                url,
                headers=self.get_headers(),
                timeout=30
            )
            result = response.json()
            
            if result.get("code") == 200:
                data = result.get("data", [])
                                            
                unreceived = [item for item in data if item.get("grant_status") == 10]
                return unreceived
            else:
                self.log(f"❌ 查询中奖列表失败: {result.get('msg', '未知错误')}")
                return []
        except Exception as e:
            self.log(f"❌ 查询中奖列表异常: {str(e)}")
            return []
    
    def receive_prize(self, log_id):
                  
        url = BASE_URL + RECEIVE_API
        data = f"log_ids={log_id}"
        
        try:
            response = self.session.post(
                url, 
                data=data, 
                headers=self.get_headers("application/x-www-form-urlencoded"), 
                timeout=30
            )
            result = response.json()
            
            if result.get("code") == 200:
                self.log(f"✅ 领奖成功")
                return True
            else:
                self.log(f"❌ 领奖失败: {result.get('msg', '未知错误')}")
                return False
                
        except Exception as e:
            self.log(f"❌ 领奖异常: {str(e)}")
            return False
    
    def run(self):
                  
        self.log(f"========== 开始执行 ==========")
        
                                       
        max_daily_count = self.do_all_tasks()
        
                   
        if self.completed_tasks > 0:
            self.log(f"\n⏰ 等待3秒后开始抽奖...\n")
            time.sleep(3)
        
                                          
        self.log(f"📌 阶段2: 查询剩余次数")
        used_count = self.get_today_lottery_count()
        base_remaining = max(0, max_daily_count - used_count)
        max_task_lottery = 4
        total_lottery_count = base_remaining + max_task_lottery
        
        self.log(f"💡 基础: {base_remaining}/{max_daily_count} | 任务: {max_task_lottery} | 总计: {total_lottery_count}次")
        
        if total_lottery_count == 0:
            self.log(f"⚠️ 无可用次数")
            self.log(f"\n========== 执行完成 ==========\n")
            return
        
                                        
        self.log(f"📌 阶段3: 开始抽奖 ({total_lottery_count}次)")
        lottery_stopped = False
        actual_lottery_count = 0
        
        for i in range(total_lottery_count):
            current_lottery_num = used_count + i + 1
            self.log(f"[{i+1}/{total_lottery_count}] 第{current_lottery_num}次")
            
            use_winning = len(self.winning_positions) > 0 and random.random() < 0.5
            location = self.generate_random_location(use_winning=use_winning)
            result = self.lottery(location, current_lottery_num)
            actual_lottery_count += 1
            
            if result == "LIMIT_REACHED":
                self.log(f"⚠️ 已达上限，停止")
                lottery_stopped = True
                break
            
            time.sleep(random.uniform(2, 4))
        
                                        
                          
        unreceived_prizes = self.get_win_list()
        
        if unreceived_prizes:
            self.log(f"📌 阶段4: 领取奖品 ({len(unreceived_prizes)}个)")
            
            for idx, prize in enumerate(unreceived_prizes, 1):
                log_id = prize.get("log_id")
                prize_name = prize.get("win_goods_name", "未知奖品")
                self.log(f"[{idx}/{len(unreceived_prizes)}] {prize_name}")
                self.receive_prize(log_id)
                time.sleep(random.uniform(1, 2))
        elif len(self.log_ids) > 0:
            self.log(f"📌 阶段4: 所有奖品已领取")
        
                                    
        self.log(f"\n📊 统计: 任务{self.completed_tasks} | 抽奖{actual_lottery_count} | 中奖{len(self.log_ids)}")
        
        if actual_lottery_count > 0:
            win_rate = (len(self.log_ids) / actual_lottery_count) * 100
            self.log(f"🎯 中奖率: {win_rate:.2f}%")
        
                  
        if self.prize_list:
            self.log(f"🎁 奖品: {', '.join(self.prize_list)}")
        
        self.log(f"\n========== 执行完成 ==========\n")


def main():
             
            
    tokens = os.getenv("DD_nfsq", "")
    
    if not tokens:
        print("❌ 请设置环境变量 DD_nfsq")
        print("格式: unique_identity&apitoken")
        print("多账号用换行或@分隔")
        print("示例: 2a9d62fd-899e-4981-8b71-44adc739facc&6d412ac633ff4e8f8f642fb234d2fd64a380d4a3568f4fc588fe44dabe1265a2")
        sys.exit(1)
    
                     
    custom_location_str = os.getenv("DD_nfsq_location", "")
    custom_locations = parse_custom_locations(custom_location_str)
    
           
    token_list = tokens.replace("\n", "@").split("@")
    token_list = [t.strip() for t in token_list if t.strip()]
    
    print(f"\n" + "="*60)
    print(f"🚀 山泉启动（任务+抽奖）")
    print(f"="*60)
    print(f"共找到 {len(token_list)} 个账号")
    if custom_locations:
        print(f"已配置 {len(custom_locations)} 个自定义地理位置")
    print(f"="*60 + "\n")
    
          
    for idx, token in enumerate(token_list, 1):
        parts = token.split("&")
        
        if len(parts) < 2:
            print(f"❌ 账号{idx}格式错误，跳过（需要格式: unique_identity&apitoken）")
            continue
        
        try:
            unique_identity = parts[0].strip()
            apitoken = parts[1].strip()
            
            print(f"\n" + "#"*60)
            print(f"账号 {idx}/{len(token_list)}")
            print(f"#"*60 + "\n")
            
            nfsq = NongFuShanQuan(unique_identity, apitoken, custom_locations)
            nfsq.run()
            
                   
            if idx < len(token_list):
                wait_time = random.randint(5, 10)
                print(f"\n等待 {wait_time} 秒后执行下一个账号...\n")
                time.sleep(wait_time)
                
        except Exception as e:
            print(f"❌ 账号{idx}执行异常: {str(e)}")
            continue
    
    print(f"\n{'='*50}")
    print(f"所有账号执行完成")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()

# 当前脚本来自于 http://script.345yun.cn 脚本库下载！
# 脚本库官方QQ群: 429274456
# 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
# 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
# 您在使用脚本库下载的脚本时自行检查判断风险。
# 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。