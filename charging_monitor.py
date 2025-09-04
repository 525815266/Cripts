#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EV Charging Monitor
- UI 紧凑：设置区(阈值/监测秒数/持续分钟)；卡Bug独立分区
- 启动即自动开始监控
- Bark 低功率提醒 + 测试（GET/POST 兼容）
- 自动停止：低功率持续 N 分钟后断开，并做两次复检（每次观察 2~3 分钟）
- 历史订单：结构化 + 原始 JSON
- 卡Bug：当日最后订单取设备/插座；随机 2~3 分钟倒计时（每秒日志）；检测到扣费立即停止
- 卡Bug统计：今日/本月 次数/分钟/预计节省（持久化到 bug_stats.json）
- 计费规则：30 分钟为一个计费周期（<30 分钟也按 30 分钟算）。节省=阶梯价/2 × ceil(本次分钟/30)
"""
import json, os, time, threading, random, math
from datetime import datetime, date
from urllib.parse import urlencode
import requests
import tkinter as tk
from tkinter import ttk, messagebox

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "charging_monitor_config.json")
BUG_STATS_FILE = os.path.join(APP_DIR, "bug_stats.json")

DEFAULT_CONFIG = {
    "bark_key": "",
    "bark_server": "https://api.day.app",
    "power_threshold_w": 30,
    "auto_stop_minutes_below_threshold": 3,
    "poll_seconds": 10,
    "token": "",
    "api_url": "https://jinjuli.sfjiayuan.com/api/OrderCharging/OrderChargingList",
    "user_info_url": "https://jinjuli.sfjiayuan.com/api/user/getUserInfo",
    "stop_url": "https://jinjuli.sfjiayuan.com/api/g/gateway/charging/stopCharging",
    "start_url": "https://jinjuli.sfjiayuan.com/api/g/gateway/charging/startCharging",
    "auto_stop_enabled": True,
    # 卡Bug参数
    "bug_hour_limit": 3,          # 1小时内最多次数
    "bug_wait_min_sec": 120,      # 单次最短秒
    "bug_wait_max_sec": 180       # 单次最长秒
}

# ---------------- 配置&统计 ----------------
def ensure_config_file():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)

def load_config():
    ensure_config_file()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # 环境变量可覆盖
    cfg["bark_key"] = os.getenv("BARK_KEY", cfg.get("bark_key", ""))
    cfg["bark_server"] = os.getenv("BARK_SERVER", cfg.get("bark_server", "https://api.day.app"))
    cfg["power_threshold_w"] = int(os.getenv("POWER_THRESHOLD_W", cfg.get("power_threshold_w", 30)))
    cfg["poll_seconds"] = int(os.getenv("POLL_SECONDS", cfg.get("poll_seconds", 10)))
    cfg["token"] = os.getenv("JINJULI_TOKEN", cfg.get("token", ""))
    cfg["api_url"] = os.getenv("JINJULI_ORDER_URL", cfg.get("api_url", DEFAULT_CONFIG["api_url"]))
    cfg["user_info_url"] = os.getenv("JINJULI_USER_URL", cfg.get("user_info_url", DEFAULT_CONFIG["user_info_url"]))
    cfg["stop_url"] = os.getenv("JINJULI_STOP_URL", cfg.get("stop_url", DEFAULT_CONFIG["stop_url"]))
    cfg["start_url"] = os.getenv("JINJULI_START_URL", cfg.get("start_url", DEFAULT_CONFIG["start_url"]))
    for k in ("auto_stop_minutes_below_threshold","auto_stop_enabled","bug_hour_limit","bug_wait_min_sec","bug_wait_max_sec"):
        cfg.setdefault(k, DEFAULT_CONFIG[k])
    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def load_bug_stats():
    if not os.path.exists(BUG_STATS_FILE):
        return {"by_day": {}, "by_month": {}}
    try:
        with open(BUG_STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"by_day": {}, "by_month": {}}

def save_bug_stats(stats):
    try:
        with open(BUG_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def add_bug_record(minutes, saved):
    stats = load_bug_stats()
    day = date.today().strftime("%Y-%m-%d")
    month = date.today().strftime("%Y-%m")
    d = stats["by_day"].setdefault(day, {"count":0,"minutes":0.0,"saved":0.0})
    d["count"] += 1; d["minutes"] += float(minutes); d["saved"] += float(saved)
    m = stats["by_month"].setdefault(month, {"count":0,"minutes":0.0,"saved":0.0})
    m["count"] += 1; m["minutes"] += float(minutes); m["saved"] += float(saved)
    save_bug_stats(stats); return stats

# ---------------- 工具函数 ----------------
def bark_push(bark_server, bark_key, title, body, **params):
    if not bark_key: return False, "No BARK_KEY set"
    from requests.utils import quote
    url = f"{bark_server.rstrip('/')}/{bark_key}/{quote(title)}/{quote(body)}"
    if params: url += "?" + urlencode(params)
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200: return True, "HTTP 200"
    except Exception: pass
    try:
        post_url = f"{bark_server.rstrip('/')}/push"
        payload = {"title":title,"body":body,"device_key":bark_key}; payload.update(params or {})
        r = requests.post(post_url, json=payload, timeout=8)
        return (r.status_code==200), f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

def parse_number(v):
    try:
        if isinstance(v,(int,float)): return float(v)
        if isinstance(v,str): return float(v.strip().replace(",",""))
    except Exception:
        return None

def pick(d, *names, default=None):
    for n in names:
        if isinstance(d, dict) and n in d and d[n] not in (None,""):
            return d[n]
    return default

def parse_tiers(pj):
    lst=[]
    if isinstance(pj,str):
        try: pj=json.loads(pj)
        except Exception: pj=[]
    if isinstance(pj,list):
        for t in pj:
            try:
                lst.append({"start":float(t.get("start_power",0)),
                            "end":float(t.get("end_power",0)),
                            "price":float(t.get("price",0))})
            except Exception:
                pass
    return lst

def resolve_tier_by_power(tiers, power_w, is_jieti=None):
    if power_w is not None and tiers:
        for t in tiers:
            if t["start"] <= power_w <= t["end"]: return t
    if is_jieti and tiers:
        try:
            idx=int(is_jieti)-1
            if 0<=idx<len(tiers): return tiers[idx]
        except Exception:
            pass
    return None

def fmt_money(v):
    x=parse_number(v); return f"{x:.2f}" if x is not None else "--"
def fmt_time(s): return s or "--"

# ---------------- 历史订单窗口 ----------------
class HistoryWindow(tk.Toplevel):
    def __init__(self, master, session, cfg):
        super().__init__(master); self.title("历史订单"); self.geometry("880x520")
        self.session, self.cfg = session, cfg; self.items=[]
        main=ttk.Frame(self, padding=10); main.pack(fill="both", expand=True)
        left=ttk.Frame(main); right=ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=(0,8))
        right.pack(side="right", fill="both", expand=True)
        self.tree=ttk.Treeview(left, columns=("start","end","status","money","place"),
                               show="headings", height=18)
        for key,txt,w in [("start","开始时间",150),("end","结束时间",150),("status","状态",70),("money","消费(¥)",80),("place","位置",180)]:
            self.tree.heading(key, text=txt); self.tree.column(key, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True)
        info=ttk.LabelFrame(right, text="转换后的信息", padding=6); info.pack(fill="both", expand=True)
        raw=ttk.LabelFrame(right, text="原始 JSON", padding=6); raw.pack(fill="both", expand=True, pady=(6,0))
        self.detail=tk.Text(info, height=8); self.detail.pack(fill="both", expand=True)
        self.raw_detail=tk.Text(raw, height=10, font=("Consolas",9)); self.raw_detail.pack(fill="both", expand=True)
        ctl=ttk.Frame(self); ctl.pack(fill="x")
        ttk.Button(ctl, text="刷新列表", command=self.refresh).pack(side="left", padx=8, pady=6)
        ttk.Button(ctl, text="关闭", command=self.destroy).pack(side="right", padx=8, pady=6)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.refresh()

    def _headers(self):
        h={"content-type":"application/json"}; t=self.cfg.get("token")
        if t: h["token"]=t
        return h

    def refresh(self):
        try:
            r=self.session.post(self.cfg["api_url"], headers=self._headers(),
                                json={"page":1,"pagenum":50}, timeout=12)
            r.raise_for_status(); js=r.json()
        except Exception as e:
            self.detail.delete("1.0","end"); self.detail.insert("end", f"加载失败: {e}"); return
        data=pick(js,"data","rows","list", default=[])
        if isinstance(data,dict): data=pick(data,"data","rows","list","items", default=[])
        self.items=data if isinstance(data,list) else []
        for i in self.tree.get_children(): self.tree.delete(i)
        for idx,it in enumerate(self.items):
            st=pick(it,"start_time","startTime",""); et=pick(it,"end_time","stop_time","endTime","")
            money=parse_number(pick(it,"order_money","money","fee"))
            status=pick(it,"order_status","status",""); place=pick(it,"name","station_name","")
            try: s=int(status); status_txt="充电中" if s==1 else "已结束" if s in(0,2) else str(status)
            except Exception: status_txt=str(status)
            self.tree.insert("", "end", iid=str(idx), values=(st,et,status_txt,f"{(money or 0):.2f}",place))
        self.detail.delete("1.0","end"); self.detail.insert("end", f"共 {len(self.items)} 条记录。")

    def on_select(self, _=None):
        sel=self.tree.selection(); 
        if not sel: return
        it=self.items[int(sel[0])]
        start=pick(it,"start_time","startTime"); end=pick(it,"end_time","stop_time","endTime")
        minutes=int(parse_number(pick(it,"time")) or 0)
        money=parse_number(pick(it,"order_money","money","fee"))
        reason=pick(it,"to_user_reason","reason","")
        place=pick(it,"name","station_name","")
        close_flag=pick(it,"close_flag"); status=pick(it,"order_status","status")
        try: s=int(status); status_txt="充电中" if s==1 else "已结束" if s in(0,2) else str(status)
        except Exception: status_txt=str(status)
        dur=f"{minutes} 分钟 ({minutes//60}小时{minutes%60}分)" if minutes else "--"
        lines=[f"状态：{status_txt}", f"充电时长：{dur}"]
        if start: lines.append(f"开始时间：{start}")
        if end: lines.append(f"结束时间：{end}")
        if place: lines.append(f"位置：{place}")
        if money is not None: lines.append(f"消费金额：¥{money:.2f}")
        if close_flag not in (None,""):
            try:
                cf=int(close_flag)
                if cf==3: lines.append("结束标志：余额不足")
                else: lines.append(f"结束判定功率：{cf} W")
            except Exception: lines.append(f"结束标志：{close_flag}")
        if reason: lines.append(f"结束原因：{reason}")
        self.detail.delete("1.0","end"); self.detail.insert("end","\n".join(lines))
        self.raw_detail.delete("1.0","end"); self.raw_detail.insert("end", json.dumps(it, ensure_ascii=False, indent=2))

# ---------------- 主程序 ----------------
class MonitorApp:
    def __init__(self, root):
        self.root=root; self.cfg=load_config(); self.session=requests.Session()
        self.running=False; self.worker=None; self._alerted=False; self._below_thr_secs=0
        self._last_active_item=None; self._last_power=None; self._busy=False
        # Bug 模式状态
        self.bug_running=False; self.bug_stop_event=threading.Event(); self.bug_attempt_timestamps=[]
        # 绑定变量
        self.var_status=tk.StringVar(value="空闲 / 未充电")
        self.var_power=tk.StringVar(value="-- W")
        self.var_tier=tk.StringVar(value="--")
        self.var_rate=tk.StringVar(value="-- ¥/小时")
        self.var_spent=tk.StringVar(value="-- ¥")
        self.var_balance=tk.StringVar(value="-- (总) / -- (充值) / -- (赠送)")
        self.var_start_time=tk.StringVar(value="--")
        self.var_place=tk.StringVar(value="--")
        self.var_order_id=tk.StringVar(value="--")
        self.var_bug_stats=tk.StringVar(value="今日：-- 次 / -- 分钟 / 省 -- 元；本月：-- 次 / -- 分钟 / 省 -- 元")
        # UI
        root.title("EV Charging Monitor"); root.geometry("730x520")
        self._build_ui(); self._refresh_bug_stats_label()
        # 启动即自动监控
        self.start_monitor()

    # ---------- UI ----------
    def _build_ui(self):
        # 账户余额
        top=ttk.LabelFrame(self.root, text="账户余额", padding=8); top.pack(fill="x", padx=10, pady=(10,6))
        ttk.Label(top, textvariable=self.var_balance, font=("Microsoft YaHei",10)).pack(anchor="w")

        # 设置区（两行整齐排布）
        settings=ttk.LabelFrame(self.root, text="设置", padding=8); settings.pack(fill="x", padx=10, pady=6)
        ttk.Label(settings, text="阈值(W)：").grid(row=0,column=0,sticky="e",padx=(0,4),pady=4)
        self.entry_threshold=ttk.Entry(settings,width=8); self.entry_threshold.insert(0,str(self.cfg.get("power_threshold_w",30)))
        self.entry_threshold.grid(row=0,column=1,sticky="w",padx=(0,12),pady=4)
        ttk.Label(settings, text="监测秒数：").grid(row=0,column=2,sticky="e",padx=(0,4),pady=4)
        self.entry_poll=ttk.Entry(settings,width=8); self.entry_poll.insert(0,str(self.cfg.get("poll_seconds",10)))
        self.entry_poll.grid(row=0,column=3,sticky="w",padx=(0,12),pady=4)

        ttk.Label(settings, text="低功率持续(分钟)：").grid(row=1,column=0,sticky="e",padx=(0,4),pady=4)
        self.entry_hold=ttk.Entry(settings,width=8); self.entry_hold.insert(0,str(self.cfg.get("auto_stop_minutes_below_threshold",3)))
        self.entry_hold.grid(row=1,column=1,sticky="w",padx=(0,12),pady=4)
        ttk.Button(settings, text="保存设置", command=self.save_settings).grid(row=1,column=3,sticky="w",padx=6,pady=4)

        # 当前状态
        mid=ttk.LabelFrame(self.root, text="当前充电状态", padding=8); mid.pack(fill="x", padx=10, pady=6)
        left=ttk.Frame(mid); right=ttk.Frame(mid); left.pack(side="left", fill="x", expand=True); right.pack(side="right", fill="x", expand=True)
        ttk.Label(left, text="功率", font=("Microsoft YaHei",10)).pack(anchor="w")
        self.lbl_power_big=tk.Label(left, textvariable=self.var_power, font=("Microsoft YaHei",22,"bold"), fg="#d61e1e", anchor="w"); self.lbl_power_big.pack(anchor="w")
        ttk.Label(left, text="已消费", font=("Microsoft YaHei",10)).pack(anchor="w", pady=(6,0))
        self.lbl_spent_big=tk.Label(left, textvariable=self.var_spent, font=("Microsoft YaHei",18,"bold"), fg="#1e9fff", anchor="w"); self.lbl_spent_big.pack(anchor="w")
        grid=ttk.Frame(right); grid.pack(fill="x", expand=True)
        def row(r,k,v): ttk.Label(grid,text=k,width=10,anchor="e").grid(row=r,column=0,sticky="e",padx=6,pady=3); ttk.Label(grid,textvariable=v,width=36,anchor="w").grid(row=r,column=1,sticky="w")
        row(0,"状态：",self.var_status); row(1,"阶梯/电价：",self.var_tier); row(2,"费率：",self.var_rate); row(3,"开始时间：",self.var_start_time); row(4,"位置：",self.var_place); row(5,"订单ID：",self.var_order_id)

        # 卡Bug分区（参数+按钮+统计）
        bug=ttk.LabelFrame(self.root, text="卡 Bug 工具", padding=8); bug.pack(fill="x", padx=10, pady=6)
        ttk.Label(bug, text="小时上限：").grid(row=0,column=0,sticky="e",padx=(0,4))
        self.entry_buglimit=ttk.Entry(bug,width=6); self.entry_buglimit.insert(0,str(self.cfg.get("bug_hour_limit",3))); self.entry_buglimit.grid(row=0,column=1,sticky="w",padx=(0,12))
        ttk.Label(bug, text="随机秒数：").grid(row=0,column=2,sticky="e",padx=(0,4))
        self.entry_bug_min=ttk.Entry(bug,width=6); self.entry_bug_min.insert(0,str(self.cfg.get("bug_wait_min_sec",120))); self.entry_bug_min.grid(row=0,column=3,sticky="w")
        ttk.Label(bug, text="~").grid(row=0,column=4,sticky="w",padx=2)
        self.entry_bug_max=ttk.Entry(bug,width=6); self.entry_bug_max.insert(0,str(self.cfg.get("bug_wait_max_sec",180))); self.entry_bug_max.grid(row=0,column=5,sticky="w",padx=(0,12))
        ttk.Button(bug, text="保存 Bug 设置", command=self.save_bug_settings).grid(row=0,column=6,sticky="w",padx=6)

        self.btn_bug=ttk.Button(bug, text="开始卡 Bug", command=self.toggle_bug_mode); self.btn_bug.grid(row=1,column=0,columnspan=2,pady=(8,2),sticky="w")
        ttk.Button(bug, text="清零统计", command=self.clear_bug_stats).grid(row=1,column=2,sticky="w",padx=6,pady=(8,2))
        ttk.Label(bug, textvariable=self.var_bug_stats).grid(row=1,column=3,columnspan=4,sticky="w",padx=6,pady=(8,2))

        # 操作按钮
        ops=ttk.Frame(self.root); ops.pack(fill="x", padx=10, pady=(4,6))
        ttk.Button(ops, text="开始监控", command=self.start_monitor).pack(side="left", padx=4)
        ttk.Button(ops, text="停止监控", command=self.stop_monitor).pack(side="left", padx=4)
        ttk.Button(ops, text="手动停止充电", command=self.stop_charging_manual).pack(side="left", padx=8)
        ttk.Button(ops, text="历史订单", command=self.open_history).pack(side="left", padx=8)
        ttk.Button(ops, text="Bark 测试消息", command=self.send_bark_test).pack(side="left", padx=8)

        # 日志
        logf=ttk.LabelFrame(self.root, text="日志", padding=8); logf.pack(fill="both", expand=True, padx=10, pady=(4,10))
        self.log=tk.Text(logf, height=8); self.log.pack(fill="both", expand=True)
        self.log_line("程序已启动。设置修改后点击对应“保存”。系统已自动开始监控。")

    # ---------- 设置保存 ----------
    def save_settings(self):
        try:
            thr=int(self.entry_threshold.get()); poll=int(self.entry_poll.get()); hold=int(self.entry_hold.get())
            if thr<=0 or poll<2 or hold<1: messagebox.showwarning("提示","阈值>0，监测秒数≥2，持续分钟≥1"); return
            self.cfg["power_threshold_w"]=thr; self.cfg["poll_seconds"]=poll; self.cfg["auto_stop_minutes_below_threshold"]=hold
            ok=save_config(self.cfg); self.log_line(f"保存设置：阈值={thr}W，监测={poll}s，持续={hold}min（{'成功' if ok else '失败'}）")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def save_bug_settings(self):
        try:
            limit=int(self.entry_buglimit.get()); mn=int(self.entry_bug_min.get()); mx=int(self.entry_bug_max.get())
            if limit<1 or mn<30 or mx<=mn: messagebox.showwarning("提示","上限≥1；随机秒数下限≥30；上限>下限"); return
            self.cfg["bug_hour_limit"]=limit; self.cfg["bug_wait_min_sec"]=mn; self.cfg["bug_wait_max_sec"]=mx
            ok=save_config(self.cfg); self.log_line(f"保存 Bug 设置：上限/小时={limit}，随机={mn}-{mx}s（{'成功' if ok else '失败'}）")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    # ---------- HTTP ----------
    def _headers(self):
        h={"content-type":"application/json"}; t=self.cfg.get("token")
        if t: h["token"]=t
        return h

    def fetch_user_info(self):
        try:
            r=self.session.post(self.cfg["user_info_url"], headers=self._headers(), json={}, timeout=12)
            r.raise_for_status(); js=r.json(); data=pick(js,"data", default={})
            um=parse_number(pick(data,"user_money")); umz=parse_number(pick(data,"user_money_zs")); sm=parse_number(pick(data,"money_sum"))
            self.var_balance.set(f"{fmt_money(sm)} (总) / {fmt_money(um)} (充值) / {fmt_money(umz)} (赠送)")
        except Exception as e:
            self.log_line(f"获取余额失败：{e}")

    def fetch_orders(self, page=1, pagenum=20):
        try:
            r=self.session.post(self.cfg["api_url"], headers=self._headers(),
                                json={"page":page,"pagenum":pagenum}, timeout=12)
            r.raise_for_status(); return r.json()
        except Exception as e:
            self.log_line(f"获取订单失败：{e}"); return None

    # ---------- 解析 ----------
    def parse_active_order(self, js):
        data=pick(js,"data","rows","list", default=[])
        if isinstance(data,dict): data=pick(data,"data","rows","list","items", default=[])
        items=data if isinstance(data,list) else []
        active=None
        for it in items:
            status=pick(it,"order_status","status")
            try:
                if int(status)==1: active=it; break
            except Exception: pass
        return active, items

    # ---------- UI 更新 ----------
    def update_ui_idle(self):
        self.var_status.set("空闲 / 未充电"); self.var_power.set("-- W"); self.var_tier.set("--"); self.var_rate.set("-- ¥/小时")
        self.var_spent.set("-- ¥"); self.var_start_time.set("--"); self.var_place.set("--"); self.var_order_id.set("--")

    def _tier_and_rate_from_item(self, it):
        power=parse_number(pick(it,"power")); tiers=parse_tiers(pick(it,"power_jieti")); is_jieti=pick(it,"is_jieti")
        cur=resolve_tier_by_power(tiers, power, is_jieti=is_jieti)
        if cur: return f"{int(cur['start'])}-{int(cur['end'])} W", f"{cur['price']} ¥/小时", cur.get("price")
        return "--", "-- ¥/小时", None

    def update_ui_active(self, it):
        power=parse_number(pick(it,"power")); self._last_power=power
        spent=parse_number(pick(it,"order_money")); start=pick(it,"start_time","startTime")
        place=pick(it,"name","station_name"); order_id=pick(it,"order_id","id","orderId")
        tier_txt, rate_txt, _ = self._tier_and_rate_from_item(it)
        self.var_status.set("充电中"); self.var_power.set(f"{int(power) if power is not None else '--'} W")
        self.var_tier.set(tier_txt); self.var_rate.set(rate_txt); self.var_spent.set(f"{fmt_money(spent)} ¥")
        self.var_start_time.set(fmt_time(start)); self.var_place.set(place or "--")
        self.var_order_id.set(str(order_id) if order_id is not None else "--")

    # ---------- 监控循环 ----------
    def start_monitor(self):
        if self.running: self.log_line("监控已在运行中。"); return
        self.running=True; self.worker=threading.Thread(target=self.loop, daemon=True); self.worker.start()
        self.log_line("开始监控。")

    def stop_monitor(self):
        self.running=False; self.log_line("停止监控。")

    def loop(self):
        while self.running:
            try: self.poll_once()
            except Exception as e: self.log_line(f"poll 异常：{e}")
            time.sleep(max(2, int(self.cfg.get("poll_seconds", 10))))

    def poll_once(self):
        self.fetch_user_info()
        js=self.fetch_orders()
        if not js: self.update_ui_idle(); return
        active,_=self.parse_active_order(js); self._last_active_item=active
        if not active:
            if self._below_thr_secs!=0: self.log_line("无活动订单，清空低功率计时。")
            self._below_thr_secs=0; self._alerted=False; self.update_ui_idle(); return
        self.update_ui_active(active)

        thr=int(self.cfg.get("power_threshold_w",30)); power=self._last_power or 0
        if power<thr:
            self._below_thr_secs += int(self.cfg.get("poll_seconds",10))
            if not self._alerted and self.cfg.get("bark_key"):
                ok,msg=bark_push(self.cfg.get("bark_server","https://api.day.app"), self.cfg.get("bark_key",""),
                                 "低功率提醒", f"功率 {int(power)}W < 阈值 {thr}W", sound="alarm", group="charging")
                self.log_line(f"Bark 推送：{ok} {msg}"); self._alerted=True
        else:
            if self._below_thr_secs>0: self.log_line("功率恢复正常，清空低功率计时。")
            self._below_thr_secs=0; self._alerted=False

        if self.cfg.get("auto_stop_enabled",True):
            hold_secs=int(self.cfg.get("auto_stop_minutes_below_threshold",3))*60
            if self._below_thr_secs>=hold_secs and self._last_active_item and not self._busy:
                self.log_line(f"功率低于 {thr}W 达 {hold_secs} 秒，自动停止充电并准备复检。")
                threading.Thread(target=self._auto_stop_with_recheck, daemon=True).start()

    # ---------- 开始/停止 ----------
    def start_charging(self, station_sn, port):
        payload={"station_sn":str(station_sn),"port":str(port),"charging_type":0,"value":0,"is_full_stop":0,"refer":1}
        try:
            r=self.session.post(self.cfg["start_url"], headers=self._headers(), json=payload, timeout=12)
            text=r.text[:200].replace("\n"," "); self.log_line(f"开始充电：HTTP {r.status_code} {text}")
            if r.status_code==200:
                js=r.json(); od=pick(js,"data",default={}); order_id=pick(od,"order_id")
                return int(order_id) if order_id is not None else None
        except Exception as e:
            self.log_line(f"开始充电异常：{e}")
        return None

    def stop_charging(self, station_number, order_id, auto=False, reason=""):
        payload={"station_number":str(station_number),"command_code":"6","error_code":0,
                 "order_id":int(order_id),"data":{"id":int(order_id),"token":""}}
        try:
            r=self.session.post(self.cfg["stop_url"], headers=self._headers(), json=payload, timeout=12)
            text=r.text[:200].replace("\n"," "); self.log_line(f"{'自动' if auto else '手动'}停止：HTTP {r.status_code} {text} {reason}".strip())
            if self.cfg.get("bark_key"):
                bark_push(self.cfg.get("bark_server","https://api.day.app"), self.cfg.get("bark_key",""),
                          "已发起停止充电(自动)" if auto else "已发起停止充电(手动)",
                          f"HTTP {r.status_code}", sound="shake", group="charging")
            return r.status_code==200
        except Exception as e:
            self.log_line(f"停止充电异常：{e}"); return False

    def stop_charging_manual(self):
        if not self._last_active_item:
            self.log_line("没有活动订单可停止。"); messagebox.showinfo("提示","没有活动订单可停止。"); return
        order_id=pick(self._last_active_item,"order_id","id","orderId")
        station_number=pick(self._last_active_item,"station_number","station_code","station_sn")
        if order_id is None or station_number is None:
            self.log_line("活动订单缺少 station/order 信息，已放弃。"); return
        self.stop_charging(station_number, order_id, auto=False)

    # ---------- 自动复检 ----------
    def _auto_stop_with_recheck(self):
        if self._busy: return
        self._busy=True
        try:
            active=self._last_active_item
            if not active: return
            order_id=pick(active,"order_id","id","orderId")
            station_sn=pick(active,"station_sn","station_number","station_code")
            port=pick(active,"socket_number","port")
            if (not station_sn) or (not port) or (not order_id):
                info=self.get_today_last_station_info()
                if info: station_sn, port = info["station_sn"], info["port"]
            if order_id and station_sn:
                self.stop_charging(station_sn, order_id, auto=True, reason="[auto stop trigger]")
                time.sleep(2)
            for i in range(2):
                info=self.get_today_last_station_info()
                if not info: self.log_line("找不到当日订单用于复检，结束。"); break
                station_sn,port=info["station_sn"], info["port"]
                new_order_id=self.start_charging(station_sn, port)
                if not new_order_id: self.log_line("开始充电失败，跳过本次复检。"); continue
                wait_s=random.randint(120,180); self.log_line(f"复检{i+1}/2：等待 {wait_s} 秒观察功率…")
                self._observe_for_seconds(wait_s)
                power=self._get_current_power_of_order(new_order_id)
                thr=int(self.cfg.get("power_threshold_w",30)); p=int(power) if power is not None else None
                self.log_line(f"复检{i+1}/2：{('功率=' + str(p) + 'W') if p is not None else '无法读取功率'}，阈值={thr}W")
                if p is None or p < thr:
                    self.stop_charging(station_sn, new_order_id, auto=True, reason=f"[recheck{i+1}] p={p}")
                else:
                    self.log_line("复检功率正常，结束复检流程。"); break
        finally:
            self._below_thr_secs=0; self._alerted=False; self._busy=False

    # ---------- 卡Bug ----------
    def toggle_bug_mode(self):
        if self.bug_running:
            self.bug_stop_event.set(); self.log_line("已请求停止卡Bug…"); return
        if self._busy:
            self.log_line("当前系统忙（复检/其他流程），稍后再试。"); return
        self.bug_stop_event.clear(); self.bug_running=True; self.btn_bug.config(text="停止卡 Bug")
        threading.Thread(target=self._bug_mode_loop, daemon=True).start()

    def _bug_mode_loop(self):
        self._busy=True
        try:
            while not self.bug_stop_event.is_set():
                # 小时上限
                now=time.time()
                self.bug_attempt_timestamps=[t for t in self.bug_attempt_timestamps if now - t < 3600]
                if len(self.bug_attempt_timestamps) >= int(self.cfg.get("bug_hour_limit",3)):
                    self.log_line("卡Bug：达到小时上限，自动停止。"); break
                info=self.get_today_last_station_info()
                if not info:
                    self.log_line("卡Bug：找不到当日订单，30秒后重试…")
                    for _ in range(30):
                        if self.bug_stop_event.is_set(): break
                        time.sleep(1)
                    if self.bug_stop_event.is_set(): break
                    continue
                station_sn,port=info["station_sn"], info["port"]
                order_id=self.start_charging(station_sn, port)
                if not order_id:
                    self.log_line("卡Bug：开始充电失败，10秒后重试…")
                    for _ in range(10):
                        if self.bug_stop_event.is_set(): break
                        time.sleep(1)
                    if self.bug_stop_event.is_set(): break
                    continue
                self.bug_attempt_timestamps.append(time.time())

                # 倒计时 & 监测扣费
                mn=int(self.cfg.get("bug_wait_min_sec",120)); mx=int(self.cfg.get("bug_wait_max_sec",180))
                wait_s=random.randint(mn, mx); start_ts=time.time(); last_rate=None
                for sec in range(wait_s):
                    if self.bug_stop_event.is_set(): break
                    js=self.fetch_orders(); active,_=self.parse_active_order(js) if js else (None,None)
                    spend_txt="?"; power_txt="?"
                    if active:
                        self.update_ui_active(active)
                        power=parse_number(pick(active,"power")); spend=parse_number(pick(active,"order_money"))
                        tier_txt,rate_txt,rate_val=self._tier_and_rate_from_item(active)
                        if rate_val is not None: last_rate=rate_val
                        power_txt=f"{int(power) if power is not None else '--'}W"; spend_txt=f"{fmt_money(spend)}"
                        if spend and spend>0:
                            self.log_line(f"卡Bug：检测到已扣费 ¥{spend_txt}，立即停止！"); break
                    left=wait_s-sec
                    self.log_line(f"卡Bug倒计时：{left:>3}s | 功率 {power_txt} | 已消费 ¥{spend_txt}")
                    time.sleep(1)

                # 停止与统计（30分钟计费周期）
                duration_min=(time.time()-start_ts)/60.0
                self.stop_charging(station_sn, order_id, auto=True, reason="[bug mode]")
                # 节省金额：按 30 分钟为一个周期，少于 30 分钟也按 30 分钟计
                blocks=max(1, math.ceil(duration_min/30.0))
                saved=(last_rate or 0.0) * 0.5 * blocks
                self.log_line(f"卡Bug结算：观察 {duration_min:.1f} 分钟，计费周期 {blocks} × 30 分钟，按阶梯价 {last_rate or 0:.2f} 元/小时，预计省 ￥{saved:.2f}")
                add_bug_record(duration_min, saved); self._refresh_bug_stats_label()

                if self.bug_stop_event.is_set(): break
                for _ in range(5):
                    if self.bug_stop_event.is_set(): break
                    time.sleep(1)
        finally:
            self.bug_running=False; self._busy=False; self.btn_bug.config(text="开始卡 Bug")
            self.log_line("卡Bug模式已停止。")

    # ---------- 辅助 ----------
    def clear_bug_stats(self):
        save_bug_stats({"by_day":{}, "by_month":{}}); self._refresh_bug_stats_label()
        self.log_line("已清零卡Bug统计。")

    def _observe_for_seconds(self, seconds):
        end=time.time()+seconds
        while time.time()<end:
            try:
                js=self.fetch_orders()
                if js:
                    active,_=self.parse_active_order(js)
                    if active: self.update_ui_active(active)
            except Exception as e:
                self.log_line(f"观察阶段异常：{e}")
            time.sleep(max(1, min(3, int(self.cfg.get("poll_seconds", 10)))))

    def _get_current_power_of_order(self, order_id):
        js=self.fetch_orders()
        if not js: return None
        data=pick(js,"data","rows","list", default=[])
        if isinstance(data,dict): data=pick(data,"data","rows","list","items", default=[])
        items=data if isinstance(data,list) else []
        for it in items:
            if str(pick(it,"order_id","id","orderId"))==str(order_id):
                return parse_number(pick(it,"power"))
        active,_=self.parse_active_order(js)
        if active: return parse_number(pick(active,"power"))
        return None

    def get_today_last_station_info(self):
        js=self.fetch_orders(page=1,pagenum=20)
        if not js: return None
        data=pick(js,"data","rows","list", default=[])
        if isinstance(data,dict): data=pick(data,"data","rows","list","items", default=[])
        items=data if isinstance(data,list) else []
        def s2dt(it):
            s=pick(it,"start_time","startTime","")
            try: return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            except Exception: return None
        today=str(date.today())
        today_items=[it for it in items if (pick(it,"start_time","startTime","") or "").startswith(today)]
        today_items.sort(key=lambda it: s2dt(it) or datetime.min, reverse=True)
        if not today_items: return None
        it=today_items[0]
        station_sn=str(pick(it,"station_code","station_number","station_sn") or "")
        port=str(pick(it,"socket_number","port") or "")
        return {"station_sn":station_sn,"port":port} if station_sn and port else None

    def open_history(self):
        HistoryWindow(self.root, self.session, self.cfg)

    def send_bark_test(self):
        title="充电状态测试"
        body=f"{self.var_status.get()} | {self.var_power.get()} | 阶梯:{self.var_tier.get()} | 费率:{self.var_rate.get()} | 已消费:{self.var_spent.get()} | 余额:{self.var_balance.get()}"
        ok,msg=bark_push(self.cfg.get("bark_server","https://api.day.app"),
                         self.cfg.get("bark_key",""), title, body,
                         sound="telegraph", group="charging")
        self.log_line(f"Bark 测试推送：{ok} {msg}")
        if not ok:
            messagebox.showwarning("Bark 推送失败", f"{msg}\n请检查 charging_monitor_config.json 中的 bark_server 和 bark_key")

    def _refresh_bug_stats_label(self):
        stats=load_bug_stats()
        day=date.today().strftime("%Y-%m-%d"); month=date.today().strftime("%Y-%m")
        d=stats.get("by_day",{}).get(day, {"count":0,"minutes":0.0,"saved":0.0})
        m=stats.get("by_month",{}).get(month, {"count":0,"minutes":0.0,"saved":0.0})
        self.var_bug_stats.set(f"今日：{int(d['count'])} 次 / {d['minutes']:.1f} 分钟 / 省 ￥{d['saved']:.2f}；本月：{int(m['count'])} 次 / {m['minutes']:.1f} 分钟 / 省 ￥{m['saved']:.2f}")

    # ---------- 日志 ----------
    def log_line(self, s):
        ts=datetime.now().strftime("%H:%M:%S")
        try:
            self.log.insert("end", f"[{ts}] {s}\n"); self.log.see("end")
        except Exception:
            print(f"[{ts}] {s}")

# ---------------- 入口 ----------------
def main():
    root=tk.Tk(); MonitorApp(root); root.mainloop()
if __name__=="__main__":
    main()
