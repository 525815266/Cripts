#!/usr/bin/env python3

import subprocess
import os
import stat
from pathlib import Path

# 如果ck加代理则是：备注#salt值#cookie值#账号:密码@ip:端口
ck = '备注#salt值#cookie值'
api_token = ''
run_type = '0'  # 0是宝箱 1是ad 2是广告一 3是广告二 4是广告3，可以输入:0123
lunci = '20'  # 跑多少轮停止

# 下面的建议默认
all_coin = '3000000'  # 金币上限多少停止
ad_time = '0'  # 是否开启广告等待？1为开启
sleep_time = '8'  # 轮次间隔时长
status_type = '2'  # 默认类型，如果频繁出现500，服务内部错误，可以尝试改成1

###########################下面的一般不用动###########################
# 当前脚本目录（真实物理路径）
base_dir = Path(os.path.realpath(__file__)).parent
jisu_path = base_dir / "jisu"

os.chmod(jisu_path, os.stat(jisu_path).st_mode | stat.S_IEXEC)

# 再执行
subprocess.run(
    [jisu_path, api_token, ck, run_type, sleep_time, all_coin, ad_time, lunci, status_type],
    text=True
)
