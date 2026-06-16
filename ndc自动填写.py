# -*- coding: utf-8 -*-
"""
ndc_worktime.py (optimized)

在原脚本基础上新增/优化：
1) 自动动态获取当前账号可填报的 projectId（优先从 toFillWork 页面解析默认选中项，其次调用 getFillProjects 列表）。
2) 当提交返回 JSON 且 flag=false（或提交后列表查不到记录）时，自动刷新 projectId 并重试 1 次。
3) 提交响应解析更健壮：优先按 JSON(flag/msg) 判定，再用“列表是否出现新记录”兜底。
4) 钉钉失败消息里带上 usedProjectId / usedProjectName，方便排查。

注意：
- 仍保留你原脚本的：登录、节假日判断、拉取列表核验、钉钉通知、随机任务名/工作内容等能力。
只看缺哪些天 不提交，先验算 python ndc_worktime_cli.py --user <ACCOUNT> --period 2025.12-2026.02 --dry-run

区间补填（你要的：账号 + 时间段）
python ndc_worktime_cli.py --user <ACCOUNT> --period 2025.12-2026.02


"""

import base64
import json
import logging
import os
import random
import time
import hmac
import hashlib
import urllib.parse
import re
from typing import Optional
from datetime import date, timedelta
from collections import defaultdict

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# ---------- logging pretty formatter ----------

class _ColorFormatter(logging.Formatter):
    """更易读的控制台日志格式：HH:MM:SS + 单字母级别。"""
    COLORS = {
        "DEBUG": "\033[36m",   # cyan
        "INFO": "\033[32m",    # green
        "WARNING": "\033[33m", # yellow
        "ERROR": "\033[31m",   # red
        "CRITICAL": "\033[35m" # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        prefix = f"{self.COLORS.get(level, '')}{level[:1]}{self.RESET}"
        record.asctime = time.strftime("%H:%M:%S", time.localtime(record.created))
        base = super().format(record)
        return f"{record.asctime} {prefix} {base}"


def setup_logging(level: int = logging.INFO) -> None:
    """初始化日志：更短、更清晰，并降低 requests/urllib3 的噪音。"""
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    h = logging.StreamHandler()
    h.setLevel(level)
    h.setFormatter(_ColorFormatter("%(message)s"))
    root.addHandler(h)

    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _cut(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"



# ================== 基本配置 ==================

NDC_BASE_URL = "https://ndc.ieisystem.com"

# ================== 钉钉机器人配置 ==================
# (保持你原来的写死方式)
DINGTALK_ACCESS_TOKEN = "<SENSITIVE>"
DINGTALK_SECRET = "<SENSITIVE>"
DINGTALK_BASE_URL = "https://oapi.dingtalk.com/robot/send"

# 账号密码（可通过命令行参数或环境变量覆盖）
DEFAULT_USERNAME = "<ACCOUNT>"
DEFAULT_PASSWORD = "<SENSITIVE>"

# 默认项目/任务信息（projectId 会在运行时动态刷新）
DEFAULT_PROJECT_ID = "337"  # 旧的兜底；如果账号项目发生变化，这个可能失效
DEFAULT_PROJECT_NAME = ""   # 可选：如果你想按名称优先匹配，可以填完整项目名
DEFAULT_TASK_NAME = "固件开发"
DEFAULT_WORK_CONTENT = "固件开发"
DEFAULT_START_TIME = "08:30"  # 每天固定 08:30 开始

# ================== AI 生成配置（sub2api / OpenAI 兼容接口） ==================
# 安全建议：不要把 API key 写死在脚本里。
# Windows PowerShell 示例：$env:NDC_AI_API_KEY="<SENSITIVE>"
# Linux/macOS 示例：export NDC_AI_API_KEY="<SENSITIVE>"
AI_ENABLED = os.getenv("NDC_AI_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
AI_BASE_URL = os.getenv("NDC_AI_BASE_URL", "https://sub2.sn55.cn/v1").rstrip("/")
AI_API_KEY = os.getenv("NDC_AI_API_KEY", "<SENSITIVE>").strip()
AI_MODEL = os.getenv("NDC_AI_MODEL", "gpt-5.4-mini").strip()
AI_TIMEOUT = float(os.getenv("NDC_AI_TIMEOUT", "18"))

# NDC 的 workContent 字段/列表展示对长文本不友好；这里主动收口，避免断在半句话。
WORK_CONTENT_MAX_CHARS = int(os.getenv("NDC_WORK_CONTENT_MAX_CHARS", "118"))
WORK_ITEM_MAX_CHARS = int(os.getenv("NDC_WORK_ITEM_MAX_CHARS", "52"))

# 工时结束时间策略：大多数天按你的真实习惯 20:36-20:49；每个自然周 1 个工作日放宽到旧范围。
REAL_END_TIME_RANGE = ("20:36", "20:49")
LEGACY_END_TIME_RANGE = ("20:00", "22:59")

# 节假日 JSON 所在目录（默认就是脚本所在目录）
HOLIDAY_JSON_DIR = os.path.dirname(os.path.abspath(__file__))
_HOLIDAY_CACHE = {}  # year -> {key: info}

# Project 缓存（一次运行内复用）
_PROJECT_CACHE = {"project_id": None, "project_name": None, "source": None}


# ================== 通用 headers ==================

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ================== 密码加密（跟前端保持一致） ==================

def encrypt_password(plain_password: str) -> str:
    """
    AES-CBC(PKCS7) 加密密码，并返回 base64 文本。
    key: 'UJRJSKEYINSP2021'
    iv : 'PORTAL4353OP2021'
    """
    key = b"UJRJSKEYINSP2021"
    iv = b"PORTAL4353OP2021"
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(plain_password.encode("utf-8"), AES.block_size, style="pkcs7"))
    return base64.b64encode(encrypted).decode("ascii")


# ================== 登录 ==================

def ndc_login(username: str, password: str) -> requests.Session:
    session = requests.Session()

    # 1) GET login.htm
    login_page_url = f"{NDC_BASE_URL}/login.htm"
    r1 = session.get(login_page_url, headers=COMMON_HEADERS, timeout=10)
    logging.info("GET login.htm -> %s", r1.status_code)

    # 2) POST 登录
    encrypted_pwd = encrypt_password(password)
    login_headers = {
        **COMMON_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": NDC_BASE_URL,
        "Referer": login_page_url,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    login_data = {"loginName": username, "password": encrypted_pwd}
    r2 = session.post(login_page_url, headers=login_headers, data=login_data, timeout=10)
    logging.info("POST login.htm -> %s, resp preview=%r", r2.status_code, r2.text[:120])

    # 3) GET newmain.htm 验证登录
    newmain_url = f"{NDC_BASE_URL}/newmain.htm"
    r3 = session.get(newmain_url, headers=COMMON_HEADERS, timeout=10)
    logging.info("GET newmain.htm -> %s, len(html)=%d", r3.status_code, len(r3.text))

    return session


# ================== 节假日 JSON ==================

def _load_holiday_year(year: int):
    if year in _HOLIDAY_CACHE:
        return

    filename = os.path.join(HOLIDAY_JSON_DIR, f"holidays_{year}.json")
    if not os.path.exists(filename):
        _HOLIDAY_CACHE[year] = {}
        logging.warning("未找到节假日文件: %s，默认按工作日/周末判断", filename)
        return

    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        holiday_map = data.get("holiday", {}) or {}
        _HOLIDAY_CACHE[year] = holiday_map
        logging.info("已加载节假日数据: %s (共 %d 条特殊日期)", filename, len(holiday_map))
    except Exception:
        logging.exception("读取节假日文件失败: %s", filename)
        _HOLIDAY_CACHE[year] = {}


def is_workday(d: date) -> bool:
    year = d.year
    _load_holiday_year(year)
    holiday_map = _HOLIDAY_CACHE.get(year, {})

    mmdd = d.strftime("%m-%d")
    ymd = d.strftime("%Y-%m-%d")
    info = holiday_map.get(mmdd) or holiday_map.get(ymd)

    if info is not None:
        if isinstance(info, dict):
            is_holiday = info.get("holiday")
        else:
            is_holiday = bool(info)

        if is_holiday is True:
            return False
        if is_holiday is False:
            return True

    return d.weekday() < 5


# ================== ProjectId 动态获取 ==================

def _parse_project_from_fill_html(html: str):
    """
    从 toFillWork.htm 返回的 HTML 里解析默认选中的 projectId & projectName。
    兼容 value 在前 / id 在前两种写法。
    """
    if not html:
        return None, None

    # projectName 隐藏域
    name = None
    m_name = re.search(r'name\s*=\s*"projectName"[^>]*value\s*=\s*"([^"]*)"', html)
    if m_name:
        name = m_name.group(1).strip()

    # projectId 输入框
    pid = None
    m1 = re.search(r'id\s*=\s*"projectId"[^>]*value\s*=\s*"(\d+)"', html)
    m2 = re.search(r'value\s*=\s*"(\d+)"[^>]*id\s*=\s*"projectId"', html)
    m = m1 or m2
    if m:
        pid = m.group(1).strip()

    return pid, name


def fetch_fill_projects(session: requests.Session):
    """
    POST getFillProjects.htm，返回可填报项目列表（list[dict]），每项通常包含 id/projectName 等字段。
    """
    url = f"{NDC_BASE_URL}/outWorkTimeContController/getFillProjects.htm"
    referer = f"{NDC_BASE_URL}/outWorkTimeContController/toFillWork.htm?fillType=0"
    headers = {
        **COMMON_HEADERS,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": NDC_BASE_URL,
        "Referer": referer,
    }

    r = session.post(url, headers=headers, timeout=10)
    logging.info("POST getFillProjects -> %s, preview=%r", r.status_code, r.text[:120])

    try:
        j = r.json()
        if isinstance(j, list):
            return j
    except Exception:
        pass

    # 有些时候 mimeType/编码怪异，兜底手动 json.loads
    try:
        j = json.loads(r.text)
        if isinstance(j, list):
            return j
    except Exception:
        logging.exception("解析 getFillProjects 返回失败")
    return []


def resolve_project(session: requests.Session, force_refresh: bool = False):
    """
    获取本次运行中应该使用的 projectId/projectName。
    优先级：
    1) 若缓存存在且不强制刷新 -> 直接用缓存
    2) GET toFillWork.htm?fillType=0&_=ts 从 HTML 解析默认选中项
    3) POST getFillProjects 列表：
       - 若 DEFAULT_PROJECT_ID 存在于列表 -> 用它
       - 若 DEFAULT_PROJECT_NAME 匹配 -> 用匹配项
       - 否则取列表第一项
    """
    if (not force_refresh) and _PROJECT_CACHE["project_id"]:
        return _PROJECT_CACHE["project_id"], _PROJECT_CACHE["project_name"], _PROJECT_CACHE["source"]

    # 1) 从 toFillWork 页面解析
    ts = int(time.time() * 1000)
    fill_url = f"{NDC_BASE_URL}/outWorkTimeContController/toFillWork.htm?fillType=0&_={ts}"
    r = session.get(fill_url, headers=COMMON_HEADERS, timeout=10)
    logging.info("GET toFillWork -> %s, len=%d", r.status_code, len(r.text))

    pid, pname = _parse_project_from_fill_html(r.text)
    if pid:
        _PROJECT_CACHE.update({"project_id": pid, "project_name": pname or "", "source": "toFillWork"})
        logging.info("resolve_project: pid=%s pname=%r source=toFillWork", pid, pname)
        return pid, pname or "", "toFillWork"

    # 2) 从 getFillProjects 列表选
    projects = fetch_fill_projects(session)
    if not projects:
        # 兜底：返回 DEFAULT_PROJECT_ID
        _PROJECT_CACHE.update({"project_id": DEFAULT_PROJECT_ID, "project_name": DEFAULT_PROJECT_NAME, "source": "default"})
        logging.warning("resolve_project: 无法拉到项目列表，回退 DEFAULT_PROJECT_ID=%s", DEFAULT_PROJECT_ID)
        return DEFAULT_PROJECT_ID, DEFAULT_PROJECT_NAME, "default"

    # 尝试优先用 DEFAULT_PROJECT_ID
    for p in projects:
        if str(p.get("id")) == str(DEFAULT_PROJECT_ID):
            _PROJECT_CACHE.update({"project_id": str(p.get("id")), "project_name": str(p.get("projectName") or ""), "source": "getFillProjects:byId"})
            return _PROJECT_CACHE["project_id"], _PROJECT_CACHE["project_name"], _PROJECT_CACHE["source"]

    # 尝试按名称匹配
    if DEFAULT_PROJECT_NAME:
        for p in projects:
            if str(p.get("projectName") or "").strip() == DEFAULT_PROJECT_NAME.strip():
                _PROJECT_CACHE.update({"project_id": str(p.get("id")), "project_name": str(p.get("projectName") or ""), "source": "getFillProjects:byName"})
                return _PROJECT_CACHE["project_id"], _PROJECT_CACHE["project_name"], _PROJECT_CACHE["source"]

    # 否则取第一项
    first = projects[0]
    _PROJECT_CACHE.update({"project_id": str(first.get("id")), "project_name": str(first.get("projectName") or ""), "source": "getFillProjects:first"})
    return _PROJECT_CACHE["project_id"], _PROJECT_CACHE["project_name"], _PROJECT_CACHE["source"]


# ================== 工时列表获取 & 打印 ==================

def fetch_worktime_list(session: requests.Session, start: date, end: date):
    """
    调用 selectSelfWorkTimeContList.htm 获取 start~end 的工时记录。
    """
    to_fill_url = f"{NDC_BASE_URL}/outWorkTimeContController/toWorkTimeFill.htm"
    session.get(to_fill_url, headers=COMMON_HEADERS, timeout=10)

    url = f"{NDC_BASE_URL}/outWorkTimeContController/selectSelfWorkTimeContList.htm"
    headers = {
        **COMMON_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": NDC_BASE_URL,
        "Referer": to_fill_url,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    data = {
        "workDateStart": start.strftime("%Y-%m-%d"),
        "workDateEnd": end.strftime("%Y-%m-%d"),
        "sortByInfo[workDate]": "desc",
        "fillType": "0",
        "page": "1",
        "rows": "50",
    }

    r = session.post(url, headers=headers, data=data, timeout=10)
    logging.info("POST selectSelfWorkTimeContList -> %s", r.status_code)
    j = r.json()
    return j.get("rows", [])


def print_worktime_rows(rows):
    """
    表格化输出工时记录，避免一行塞太多字段导致难读。
    """
    if not rows:
        print("（该时间段没有工时记录）")
        return

    headers = ["#", "日期", "项目", "任务", "时间段", "工时", "提交/审批", "内容(截断)"]
    widths  = [3, 10, 16, 18, 13, 6, 10, 34]

    def fmt_row(cols):
        out = []
        for c, w in zip(cols, widths):
            out.append(_cut(str(c), w).ljust(w))
        return " | ".join(out)

    print(fmt_row(headers))
    print("-" * (sum(widths) + 3 * (len(widths) - 1)))

    for i, r in enumerate(rows, 1):
        work_date = (r.get("workDate") or "").split(" ")[0]
        project_name = r.get("projectName", "") or ""
        task_name = r.get("taskName") or ""
        st = (r.get("startTime") or "")[:5]
        et = (r.get("endTime") or "")[:5]
        work_hour = r.get("workHour") or ""
        submit_status = r.get("submitStatus") or ""
        approve_status = r.get("approveStatus") or ""
        work_content = r.get("workContent") or ""

        cols = [
            i,
            work_date,
            project_name,
            task_name,
            f"{st}-{et}" if st and et else "",
            work_hour,
            f"{submit_status}/{approve_status}",
            work_content,
        ]
        print(fmt_row(cols))


def has_today_record(rows, today: date) -> bool:
    today_str = today.strftime("%Y-%m-%d")
    for r in rows:
        wd = (r.get("workDate") or "").split(" ")[0]
        if wd == today_str:
            return True
    return False


def find_today_record_with_time(rows, today: date, start_time: str, end_time: str):
    """
    在列表中根据 日期 + 开始/结束时间 定位记录。
    兼容 08:30 vs 08:30:00 存储差异。
    """
    today_str = today.strftime("%Y-%m-%d")
    for r in rows:
        wd = (r.get("workDate") or "").split(" ")[0]
        st = r.get("startTime") or ""
        et = r.get("endTime") or ""
        if wd != today_str:
            continue
        if not st.startswith(start_time):
            continue
        if not et.startswith(end_time):
            continue
        return r
    return None


# ================== 钉钉通知 ==================

def send_dingtalk_text(content: str):
    timestamp = str(round(time.time() * 1000))
    secret = DINGTALK_SECRET

    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))

    url = (
        f"{DINGTALK_BASE_URL}"
        f"?access_token={DINGTALK_ACCESS_TOKEN}"
        f"&timestamp={timestamp}&sign={sign}"
    )

    headers = {"Content-Type": "application/json; charset=utf-8"}
    payload = {"msgtype": "text", "text": {"content": content}}

    try:
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        logging.info("钉钉通知返回: %s %s", resp.status_code, resp.text[:200])
    except Exception:
        logging.exception("发送钉钉通知失败")


# ================== 自动填报 ==================


def _hhmm_to_minutes(s: str) -> int:
    h, m = [int(x) for x in s.split(":")]
    return h * 60 + m


def _minutes_to_hhmm(v: int) -> str:
    return f"{v // 60:02d}:{v % 60:02d}"


def _stable_week_relaxed_day(d: date) -> int:
    """
    每个 ISO 周稳定选 1 个工作日使用旧随机范围。
    这样区间补填时不会因为重跑脚本导致同一周的放宽日乱跳。
    返回 weekday: 0=周一 ... 4=周五。
    """
    iso_year, iso_week, _ = d.isocalendar()
    seed = f"{iso_year}-{iso_week}-ndc-endtime".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()
    return int(digest[:8], 16) % 5


def random_end_time(work_date: Optional[date] = None) -> str:
    """
    结束时间策略：
    - 每周 1 个工作日在旧范围 20:00~22:59 内随机，模拟偶发加班/离场波动；
    - 其余工作日使用你的实际常见打卡范围 20:36~20:49。
    """
    d = work_date or date.today()
    if d.weekday() == _stable_week_relaxed_day(d):
        lo, hi = LEGACY_END_TIME_RANGE
    else:
        lo, hi = REAL_END_TIME_RANGE
    return _minutes_to_hhmm(random.randint(_hhmm_to_minutes(lo), _hhmm_to_minutes(hi)))


def _unique_sample(items, k: int):
    items = list(items)
    random.shuffle(items)
    return items[: max(0, min(k, len(items)))]


def random_task_name() -> str:
    candidates = [
        "BIOS Bug定位",
        "RC参数联调",
        "XCradle问题澄清",
        "AMI代码维护",
        "平台固件验证",
        "BIOS设计维护",
    ]
    return random.choice(candidates)


BIOS_CONTEXT = {
    # 这些不是“模板大话”，而是用于组合出更像真实日报的细颗粒动作。
    # 尽量包含：模块/文件或阶段 + 具体异常 + 定位动作 + 当天产出。
    "task_names": [
        "BIOS Bug定位", "RC参数联调", "XCradle问题澄清", "AMI代码维护", "平台固件验证", "BIOS设计维护"
    ],
    "scenarios": [
        {
            "task": "RC参数联调",
            "items": [
                "核对XCradle下发的RC policy，修正PCH PCIe ASPM默认值",
                "对比Intel RC默认表，标出Root Port 3/5配置差异",
                "补测Gen4降Gen3链路训练，确认POST卡顿不再复现",
            ],
        },
        {
            "task": "BIOS Bug定位",
            "items": [
                "复现PCIe NVMe冷启动丢盘，截取DXE枚举前后POST码",
                "在AMI PCI Bus路径加调试点，确认BAR分配未越界",
                "整理Root Port复现条件，更新问题单的BIOS侧结论",
            ],
        },
        {
            "task": "XCradle问题澄清",
            "items": [
                "跟踪XCradle模块GPIO表，确认Reset脚极性配置不一致",
                "把BoardId分支和RC policy映射关系补到设计说明",
                "用两版BIOS交叉验证，排除ME FW版本导致的假象",
            ],
        },
        {
            "task": "AMI代码维护",
            "items": [
                "检查Setup选项SuppressIf条件，修正隐藏项仍写NVRAM的问题",
                "调整DXE驱动Depex顺序，避免ACPI表生成早于RC初始化",
                "补充默认值升级兼容处理，保留旧版本变量迁移路径",
            ],
        },
        {
            "task": "平台固件验证",
            "items": [
                "回归S3唤醒后USB键鼠失效，确认xHCI重初始化顺序",
                "比对串口日志中的MRC训练耗时，记录异常DIMM槽位",
                "补跑Secure Boot开关组合，确认PK/KEK清除流程正常",
            ],
        },
        {
            "task": "BIOS设计维护",
            "items": [
                "补写PEI阶段RC policy装载流程，注明BoardId选择逻辑",
                "整理PCIe枚举异常处理分支，加入日志开关和验证点",
                "更新XCradle接口说明，明确BIOS与BMC侧字段边界",
            ],
        },
        {
            "task": "BIOS Bug定位",
            "items": [
                "分析开机偶发停在0xB2，确认卡在PCI Option ROM阶段",
                "关闭外接网卡PXE后复测，缩小到Legacy兼容路径",
                "提交临时规避方案，等待测试侧扩大样本复现",
            ],
        },
        {
            "task": "RC参数联调",
            "items": [
                "调整CPU PCIe bifurcation配置，验证x16拆分后设备顺序",
                "检查RC代码里ClkReq映射，修正XCradle端口表偏移",
                "记录链路训练失败的LTSSM状态，补充到调试说明",
            ],
        },
        {
            "task": "AMI代码维护",
            "items": [
                "清理SMBIOS Type17容量显示逻辑，兼容不同Rank组合",
                "复核DMI字段来源，避免客户定制字符串覆盖默认值",
                "本地编译Release分支，确认warning数量未新增",
            ],
        },
        {
            "task": "平台固件验证",
            "items": [
                "复测BMC发起的远程重启，确认BIOS侧PowerGood判断",
                "抓取AC loss后首次上电日志，检查RTC恢复路径",
                "更新验证记录，把失败样机和BIOS版本号分开统计",
            ],
        },
    ],
}



def _smart_trim_cn(text: str, max_chars: int, min_keep: int = 16) -> str:
    """
    按中文语义边界裁剪，避免出现“方便后”这种半截句。
    不加省略号，提交内容本身看起来更自然。
    """
    text = re.sub(r"\s+", " ", (text or "")).strip(" ；;，,。")
    if len(text) <= max_chars:
        return text

    head = text[:max_chars]
    # 优先在强边界停；其次在逗号/顿号等弱边界停。
    for seps in ("；;。", "，,、：:"):
        pos = max(head.rfind(ch) for ch in seps)
        if pos >= min_keep:
            return head[:pos].rstrip(" ；;，,。")

    return head.rstrip(" ；;，,。")


def _normalize_work_item_text(text: str) -> str:
    """清洗单条日志：去编号、去多余空白、收口单条长度。"""
    text = re.sub(r"^\s*\d+[.、)]\s*", "", str(text or "")).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" -;；，,。")
    return _smart_trim_cn(text, WORK_ITEM_MAX_CHARS, min_keep=14)


def _is_too_generic_item(text: str) -> bool:
    """过滤 AI 生成的空泛句，宁愿走本地具体模板。"""
    t = re.sub(r"\s+", "", text or "")
    concrete_markers = [
        "PEI", "DXE", "MRC", "PCIe", "RootPort", "Root Port", "ACPI", "SMBIOS", "POST", "RCpolicy", "RC policy",
        "Setup", "BMC", "EC", "GPIO", "NVRAM", "NVMe", "xHCI", "PXE", "BootGuard", "SecureBoot",
        "0x", "BAR", "ClkReq", "BoardId", "LTSSM", "DIMM", "Type17", "OptionROM", "Option ROM",
    ]
    concrete = any(m.replace(" ", "") in t for m in concrete_markers)
    vague_phrases = ["影响范围", "保持一致", "相关工作", "联调点", "设计说明", "优化处理", "跟进确认", "问题处理", "功能开发"]
    # 只要没有具体技术锚点，又出现泛化词，就判为太笼统。
    return (not concrete) and any(x in t for x in vague_phrases)


def _join_work_items_safely(items) -> str:
    """
    组装 1~3 条日志，总长度主动限制在 WORK_CONTENT_MAX_CHARS 内。
    如果第三条放不下，就宁愿保留两条完整句，也不硬截断。
    """
    cleaned = []
    seen = set()
    for x in items or []:
        y = _normalize_work_item_text(x)
        if len(y) < 8 or _is_too_generic_item(y):
            continue
        key = re.sub(r"\s+", "", y)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(y)
        if len(cleaned) >= 3:
            break

    if not cleaned:
        return DEFAULT_WORK_CONTENT

    picked = []
    for item in cleaned:
        candidate = "；".join(picked + [item])
        if len(candidate) <= WORK_CONTENT_MAX_CHARS:
            picked.append(item)
        elif not picked:
            picked.append(_smart_trim_cn(item, WORK_CONTENT_MAX_CHARS))
            break
        else:
            break

    return "；".join(picked).rstrip("；;，,。")

def build_fallback_work_items(work_date: Optional[date] = None):
    """本地兜底：从具体 BIOS 场景里抽取 1~3 条，避免“泛泛研发描述”。"""
    d = work_date or date.today()
    # 同一天稳定一些，但每次也保留微小扰动，避免区间补填时全像固定模板。
    seed = f"{d.isoformat()}-{time.time_ns()}-bios-detail"
    rnd = random.Random(seed)
    scenario = rnd.choice(BIOS_CONTEXT["scenarios"])
    n = rnd.randint(1, 3)
    items = scenario["items"][:]
    rnd.shuffle(items)

    # 低概率把不同场景的一条合进来，模拟当天穿插处理多个问题。
    if n >= 2 and rnd.random() < 0.35:
        other = rnd.choice([x for x in BIOS_CONTEXT["scenarios"] if x is not scenario])
        items[-1] = rnd.choice(other["items"])

    return items[:n]


def _normalize_ai_items(obj):
    """
    兼容 AI 返回：list[str] 或 {task_name, items/content}。
    """
    task_name = None
    items = []
    if isinstance(obj, dict):
        task_name = str(obj.get("task_name") or obj.get("taskName") or "").strip() or None
        raw = obj.get("items") or obj.get("contents") or obj.get("content") or []
        if isinstance(raw, str):
            items = [x.strip(" -;；，,\n\t") for x in re.split(r"[\n;；]+", raw) if x.strip()]
        elif isinstance(raw, list):
            items = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(obj, list):
        items = [str(x).strip() for x in obj if str(x).strip()]
    items = [re.sub(r"^\d+[.、)]\s*", "", x).strip() for x in items]
    items = [_normalize_work_item_text(x) for x in items]
    items = [x for x in items if 8 <= len(x) <= WORK_ITEM_MAX_CHARS and not _is_too_generic_item(x)]
    # 去重，保序
    seen = set()
    dedup = []
    for x in items:
        key = re.sub(r"\s+", "", x)
        if key not in seen:
            seen.add(key)
            dedup.append(x)
    return task_name, dedup[:3]


def generate_ai_work_items(work_date: Optional[date] = None):
    """
    通过 sub2api 调 OpenAI 兼容 chat/completions 生成工作内容。
    失败时返回 None，调用方会走本地兜底。
    """
    if not AI_ENABLED:
        return None
    if not AI_API_KEY:
        logging.warning("未设置 NDC_AI_API_KEY，跳过 AI 生成，使用本地模板兜底")
        return None

    d = work_date or date.today()
    url = f"{AI_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "temperature": 0.92,
        "top_p": 0.9,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是BIOS/UEFI固件工程师的工作日志生成器。只输出JSON，不要解释。"
                    "内容要像真实日报里的当天动作，必须包含具体模块、异常现象、定位手段或产出之一。"
                    "禁止空泛表达：影响范围、保持一致、相关工作、优化处理、跟进确认、联调点、设计说明这类词不能单独出现。"
                    "不要编造客户名、机密编号、真实漏洞编号。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"日期：{d.isoformat()}。生成当天1到3条工作内容和一个任务名。"
                    "技术背景：AMI codebase、Intel CPU、Intel RC代码、XCradle模块。"
                    "范围：BIOS功能开发、故障诊断类Bug澄清、bug复现/定位、RC参数联调、设计文档编写、回归验证。"
                    "要求：中文；每条18到36字；总字数不要超过110字；表达不要模板化；可以带少量英文术语如PEI/DXE/MRC/PCIe/ACPI/POST/RC policy；"
                    "只写完整短句，不要写半截铺垫；返回格式：{\"task_name\":\"...\",\"items\":[\"...\",\"...\"]}"
                ),
            },
        ],
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=AI_TIMEOUT)
        logging.info("AI worklog -> %s", r.status_code)
        if r.status_code >= 400:
            logging.warning("AI 返回异常，使用兜底模板：%s", _cut(r.text, 160))
            return None
        j = r.json()
        content = j.get("choices", [{}])[0].get("message", {}).get("content", "")
        content = (content or "").strip()
        # 兼容 ```json ... ```
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        obj = json.loads(content)
        task_name, items = _normalize_ai_items(obj)
        if items:
            return {"task_name": task_name or random_task_name(), "items": items, "source": "ai"}
    except Exception as e:
        logging.warning("AI 生成失败，使用本地模板兜底：%s", e)
    return None


def build_work_content(work_date: Optional[date] = None):
    """
    AI 优先，本地模板兜底。返回 (task_name, work_content, source)。
    workContent 内每天 1~3 条，以“；”分隔，避免旧脚本一条模板句过于生硬。
    """
    ai = generate_ai_work_items(work_date)
    if ai:
        items = ai["items"]
        task_name = ai["task_name"]
        source = "ai"
    else:
        items = build_fallback_work_items(work_date)
        task_name = random_task_name()
        source = "fallback"

    # 控制长度，避免 NDC 列表/字段把内容截成半句话。
    content = _join_work_items_safely(items)
    return task_name[:30], content, source


# 兼容旧函数名，避免其它地方引用时报错
def build_random_work_content(work_date: Optional[date] = None):
    return build_work_content(work_date)[1]


def _try_parse_submit_json(text: str):
    """
    尝试把提交响应解析成 JSON：
    常见结构：{"flag":true/false,"msg":"...","obj":...}
    """
    if not text:
        return None
    try:
        j = json.loads(text)
        if isinstance(j, dict) and ("flag" in j or "msg" in j):
            return j
    except Exception:
        return None
    return None


def submit_worktime_today(
    session: requests.Session,
    work_date: date,
    project_id: str,
    project_name: str = "",
    task_name: str = DEFAULT_TASK_NAME,
    work_content: str = DEFAULT_WORK_CONTENT,
    start_time: str = DEFAULT_START_TIME,
    end_time: 'Optional[str]' = None,
):
    """
    提交一条工时。
    返回 (status_code, resp_text, meta, resp_json_or_none)
    """
    url = f"{NDC_BASE_URL}/outWorkTimeContController/toSubmitFillWork.htm"
    to_fill_url = f"{NDC_BASE_URL}/outWorkTimeContController/toWorkTimeFill.htm"

    headers = {
        **COMMON_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": NDC_BASE_URL,
        "Referer": to_fill_url,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    if end_time is None:
        end_time = random_end_time(work_date)

    data = {
        "id": "",
        "projectName": project_name or "",
        "projectId": str(project_id),
        "fillType": "0",
        "workDate": work_date.strftime("%Y-%m-%d"),
        "workTime": "0",
        "isWorkTime": "1",
        "workTimeType": "1",
        "workLocation": "",
        "taskCode": "",
        "taskName": task_name,
        "taskWbs": "",
        "workContent": work_content,
        "taskStartTime": "",
        "taskEndTime": "",
        "startTime": start_time,
        "endTime": end_time,
    }

    r = session.post(url, headers=headers, data=data, timeout=10)
    resp_text = r.text or ""
    resp_json = _try_parse_submit_json(resp_text)

    logging.info("POST toSubmitFillWork -> %s", r.status_code)
    logging.debug("submit resp preview: %r", resp_text[:200])

    meta = {
        "work_date": work_date.strftime("%Y-%m-%d"),
        "start_time": start_time,
        "end_time": end_time,
        "task_name": task_name,
        "work_content": work_content,
        "project_id": str(project_id),
        "project_name": project_name or "",
    }
    return r.status_code, resp_text, meta, resp_json


def _verify_new_record(session: requests.Session, d: date, meta: dict):
    """
    重新查询当天列表，尝试按时间段匹配新记录。
    """
    rows_after = fetch_worktime_list(session, d, d)
    rec = find_today_record_with_time(rows_after, d, meta["start_time"], meta["end_time"])
    return rec


# ================== main ==================


def _month_last_day(y: int, m: int) -> int:
    import calendar
    return calendar.monthrange(y, m)[1]


def parse_period(period: str):
    """
    period 支持：
    - "2025.12-2026.02"
    - "2025-12~2026-2"
    - "2025/12 - 2026/02"
    语义：按“月份区间”，自动展开为：
    start = 起始月份1号
    end   = 结束月份最后一天（若超过今天则截断到今天）
    """
    if not period:
        raise ValueError("period 不能为空，例如：2025.12-2026.02")

    p = period.strip()
    # 统一分隔符
    p = p.replace("~", "-").replace("—", "-").replace("–", "-")
    # 提取两端年月
    ms = re.findall(r'(\d{4})\s*[.\-/]\s*(\d{1,2})', p)
    if len(ms) < 2:
        raise ValueError(f"无法解析 period={period!r}，期望类似 2025.12-2026.02")

    (y1, m1), (y2, m2) = ms[0], ms[1]
    y1, m1 = int(y1), int(m1)
    y2, m2 = int(y2), int(m2)
    if not (1 <= m1 <= 12 and 1 <= m2 <= 12):
        raise ValueError(f"月份不合法：{m1}, {m2}")

    start = date(y1, m1, 1)
    end = date(y2, m2, _month_last_day(y2, m2))

    if end < start:
        raise ValueError(f"period 结束时间早于开始时间：{start} - {end}")

    today = date.today()
    if end > today:
        end = today

    return start, end


def fetch_worktime_list_all(session: requests.Session, start: date, end: date):
    """
    拉取 start~end 的全部工时记录（自动翻页）。
    """
    all_rows = []
    page = 1
    while True:
        to_fill_url = f"{NDC_BASE_URL}/outWorkTimeContController/toWorkTimeFill.htm"
        session.get(to_fill_url, headers=COMMON_HEADERS, timeout=10)

        url = f"{NDC_BASE_URL}/outWorkTimeContController/selectSelfWorkTimeContList.htm"
        headers = {
            **COMMON_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": NDC_BASE_URL,
            "Referer": to_fill_url,
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        data = {
            "workDateStart": start.strftime("%Y-%m-%d"),
            "workDateEnd": end.strftime("%Y-%m-%d"),
            "sortByInfo[workDate]": "desc",
            "fillType": "0",
            "page": str(page),
            "rows": "50",
        }

        r = session.post(url, headers=headers, data=data, timeout=10)
        logging.info("POST selectSelfWorkTimeContList page=%s -> %s", page, r.status_code)
        j = r.json()
        rows = j.get("rows", []) or []
        all_rows.extend(rows)

        # 经验：rows 少于请求 rows 时基本到尾；再用 total/pageSize 兜底
        total = j.get("total")
        if not rows:
            break
        if len(rows) < 50:
            break
        if isinstance(total, int) and len(all_rows) >= total:
            break

        page += 1
        if page > 50:  # 防止异常死循环
            logging.warning("分页超过 50 页仍未结束，停止继续拉取（请检查接口返回）")
            break

    return all_rows


def _date_set_from_rows(rows):
    s = set()
    for r in rows or []:
        wd = (r.get("workDate") or "").split(" ")[0]
        if wd:
            s.add(wd)
    return s


def backfill_worktime(session: requests.Session, start: date, end: date):
    """
    自动检查并补填 start~end 内缺失的工作日工时。
    - 工作日判断：沿用 is_workday()
    - 已填判断：同一天存在任意记录即认为已填（沿用你脚本原逻辑）
    - 填写规则：沿用随机 task/work_content + 固定开始时间 + 随机结束时间等
    """
    logging.info("开始检查并补填：%s ~ %s", start, end)

    # 先解析/获取本账号当前 projectId
    project_id, project_name, psrc = resolve_project(session, force_refresh=False)
    logging.info("将使用项目: id=%s name=%r (source=%s)", project_id, project_name, psrc)

    # 拉取区间内已有记录（一次性）
    rows = fetch_worktime_list_all(session, start, end)
    filled_dates = _date_set_from_rows(rows)

    need_fill = []
    d = start
    while d <= end:
        if is_workday(d):
            if d.strftime("%Y-%m-%d") not in filled_dates:
                need_fill.append(d)
        d += timedelta(days=1)

    logging.info("区间内已有记录 %d 条，缺失工作日 %d 天", len(rows), len(need_fill))

    # 逐天补填
    success_days = []
    failed_days = []

    for d in need_fill:
        task_name, work_content, content_source = build_work_content(d)
        logging.info("%s 工作内容来源：%s，任务=%s，内容=%s", d, content_source, task_name, _cut(work_content, 80))

        for attempt in range(1, 3):
            status_code, resp_text, meta, resp_json = submit_worktime_today(
                session,
                d,
                project_id=project_id,
                project_name=project_name,
                task_name=task_name,
                work_content=work_content,
            )

            new_record = _verify_new_record(session, d, meta)

            json_flag = None
            json_msg = ""
            if isinstance(resp_json, dict):
                json_flag = resp_json.get("flag")
                json_msg = str(resp_json.get("msg") or "")

            success_by_json = (json_flag is True)
            success_by_list = (new_record is not None)
            is_success = (status_code == 200) and (success_by_json or success_by_list)

            if is_success:
                success_days.append(d)
                logging.info("✅ %s 补填成功 (attempt=%s)", d, attempt)
                break

            if attempt == 1:
                old_pid = project_id
                project_id, project_name, psrc = resolve_project(session, force_refresh=True)
                logging.warning(
                    "❗ %s 提交失败，刷新 projectId 重试：old=%s new=%s (source=%s) msg=%r",
                    d, old_pid, project_id, psrc, json_msg or (resp_text or "")[:80],
                )
                continue

            # attempt==2 仍失败
            failed_days.append((d, json_msg or (resp_text or "")[:120]))
            logging.error("❌ %s 补填失败 (status=%s msg=%r)", d, status_code, json_msg or (resp_text or "")[:80])

        # 避免太快触发风控
        time.sleep(random.uniform(0.6, 1.4))

    # 汇总通知（钉钉一次性发）
    lines = [
        f"🧾 NDC 工时区间补填结果：{start} ~ {end}",
        f"- 成功：{len(success_days)} 天",
        f"- 失败：{len(failed_days)} 天",
    ]
    if success_days:
        lines.append("- 成功日期：" + ", ".join([d.strftime("%Y-%m-%d") for d in success_days[:30]]) + (" ..." if len(success_days) > 30 else ""))
    if failed_days:
        lines.append("- 失败日期：")
        for d, msg in failed_days[:15]:
            lines.append(f"  * {d.strftime('%Y-%m-%d')}：{_cut(msg, 60)}")
        if len(failed_days) > 15:
            lines.append("  * ...（失败太多，仅展示前 15 条）")

    msg = "\n".join(lines)
    print(msg)
    send_dingtalk_text(msg)


def main():
    setup_logging(logging.INFO)

    import argparse

    parser = argparse.ArgumentParser(description="NDC 工时自动填写/补填脚本")
    parser.add_argument("--user", required=False, help="账号（loginName）。例如：<ACCOUNT>")
    parser.add_argument("--period", required=False, help="月份区间。例如：2025.12-2026.02")
    parser.add_argument("--password", required=False, help="密码（可选；也可用环境变量 NDC_PASSWORD）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印缺失日期，不提交（调试用）")
    parser.add_argument("--ai-key", required=False, help="sub2api/OpenAI 兼容接口 API key；也可用环境变量 NDC_AI_API_KEY")
    parser.add_argument("--ai-base-url", required=False, help="AI接口Base URL，默认 https://sub2.sn55.cn/v1")
    parser.add_argument("--ai-model", required=False, help="AI模型名，默认读取 NDC_AI_MODEL 或 gpt-5.4-mini")
    parser.add_argument("--no-ai", action="store_true", help="关闭AI生成，只用本地BIOS模板兜底")
    args = parser.parse_args()

    global AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_ENABLED
    if args.ai_key:
        AI_API_KEY = args.ai_key.strip()
    if args.ai_base_url:
        AI_BASE_URL = args.ai_base_url.rstrip("/")
    if args.ai_model:
        AI_MODEL = args.ai_model.strip()
    if args.no_ai:
        AI_ENABLED = False

    username = args.user or os.getenv("NDC_USERNAME") or DEFAULT_USERNAME
    password = args.password or os.getenv("NDC_PASSWORD") or DEFAULT_PASSWORD

    session = ndc_login(username=username, password=password)

    # 如果传了 period -> 走区间补填；否则保持原本“只填今天”的逻辑
    if args.period:
        start, end = parse_period(args.period)

        if args.dry_run:
            rows = fetch_worktime_list_all(session, start, end)
            filled_dates = _date_set_from_rows(rows)
            miss = []
            d = start
            while d <= end:
                if is_workday(d) and d.strftime("%Y-%m-%d") not in filled_dates:
                    miss.append(d.strftime("%Y-%m-%d"))
                d += timedelta(days=1)
            print(f"DRY RUN：{start} ~ {end} 缺失工作日 {len(miss)} 天：")
            print(", ".join(miss))
            return

        backfill_worktime(session, start, end)
        return

    # ====== 原逻辑：只检查/填今天 ======
    today = date.today()

    # 1) 打印最近一周工时记录（包含今天）
    start = today - timedelta(days=6)
    rows = fetch_worktime_list(session, start, today)
    print("=== 最近一周工时记录 ===")
    print_worktime_rows(rows)

    # 2) 判断今天是否工作日
    if not is_workday(today):
        print(f"{today} 不是工作日/调休，不自动填报。")
        return

    # 3) 今天是否已有记录
    if has_today_record(rows, today):
        print(f"{today} 已经有工时记录，不重复填报。")
        return

    # 4) 解析/获取本账号当前 projectId
    project_id, project_name, psrc = resolve_project(session, force_refresh=False)
    logging.info("将使用项目: id=%s name=%r (source=%s)", project_id, project_name, psrc)

    # 5) 自动填报（允许最多 2 次尝试：第一次用当前 projectId，失败则刷新 projectId 再试一次）
    print(f"{today} 是工作日且未填报，准备自动填报……")

    task_name, work_content, content_source = build_work_content(today)
    logging.info("今日工作内容来源：%s，任务=%s，内容=%s", content_source, task_name, _cut(work_content, 80))

    attempts = []
    for attempt in range(1, 3):
        status_code, resp_text, meta, resp_json = submit_worktime_today(
            session,
            today,
            project_id=project_id,
            project_name=project_name,
            task_name=task_name,
            work_content=work_content,
        )

        new_record = _verify_new_record(session, today, meta)

        # 判定成功：1) JSON flag==True 或 2) 列表能找到新记录（更可靠）
        json_flag = None
        json_msg = ""
        if isinstance(resp_json, dict):
            json_flag = resp_json.get("flag")
            json_msg = str(resp_json.get("msg") or "")

        success_by_json = (json_flag is True)
        success_by_list = (new_record is not None)
        is_success = (status_code == 200) and (success_by_json or success_by_list)

        attempts.append({
            "attempt": attempt,
            "status_code": status_code,
            "json_flag": json_flag,
            "json_msg": json_msg,
            "meta": meta,
            "resp_preview": (resp_text[:120] if resp_text else ""),
            "found_record": bool(new_record),
        })

        if is_success:
            proj_name = new_record.get("projectName", "") if new_record else (project_name or "")
            task_name2 = new_record.get("taskName", "") if new_record else meta["task_name"]
            work_content2 = new_record.get("workContent", "") if new_record else meta["work_content"]
            st = new_record.get("startTime", "") if new_record else meta["start_time"]
            et = new_record.get("endTime", "") if new_record else meta["end_time"]
            work_hour = new_record.get("workHour", "") if new_record else ""

            msg = (
                f"✅ NDC 工时自动填报成功：{meta['work_date']}\n"
                f"- 项目: {proj_name}\n"
                f"- usedProjectId: {meta['project_id']}\n"
                f"- 任务: {task_name2}\n"
                f"- 内容: {work_content2}\n"
                f"- 时间: {st} - {et}\n"
                f"- 投入工时(小时): {work_hour}\n"
                f"- HTTP 状态码: {status_code}"
            )
            print(msg)
            send_dingtalk_text(msg)
            return

        # 失败：按你的需求 -> 触发动态刷新 projectId 并重试
        if attempt == 1:
            old_pid = project_id
            project_id, project_name, psrc = resolve_project(session, force_refresh=True)
            logging.warning(
                "提交失败，刷新 projectId 后准备重试：old=%s new=%s (source=%s) msg=%r",
                old_pid, project_id, psrc, json_msg or resp_text[:80],
            )
            continue

    # 两次都失败：钉钉里带足够信息，便于你定位
    last = attempts[-1]
    meta = last["meta"]
    resp_has_success_word = ("成功" in (last["resp_preview"] or "")) or ("success" in (last["resp_preview"] or "").lower())

    lines = [
        f"❌ NDC 自动填报疑似失败：{meta['work_date']}",
        f"- usedProjectId: {meta['project_id']} / usedProjectName: {meta['project_name']}",
        f"- HTTP 状态码: {last['status_code']}",
        f"- 响应中是否含“成功”: {'是' if resp_has_success_word else '否'}",
        f"- 响应 JSON flag: {last['json_flag']}",
        f"- 响应 msg: {last['json_msg'] or '(空)'}",
        f"- 是否在工时列表中找到刚提交那条: {'是' if last['found_record'] else '否'}",
        f"- 提交时间段: {meta['start_time']} - {meta['end_time']}",
        f"- 响应前 120 字符: {last['resp_preview']}",
        "",
        "（调试信息：本次共尝试 2 次，第二次已强制刷新 projectId。）",
    ]
    msg = "\n".join(lines)
    print(msg)
    send_dingtalk_text(msg)


if __name__ == "__main__":
    main()

