#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_holidays.py
获取当前年份的中国大陆节假日信息，并保存到 holidays_YYYY.json 文件。
使用 https://timor.tech/api/holiday/year/{year} 接口。
"""

import requests, datetime, json, os, sys

def main():
    year = datetime.datetime.now().year
    url = f"https://timor.tech/api/holiday/year/{year}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    print(f"正在获取 {year} 年节假日数据...")
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print("获取失败:", e)
        sys.exit(1)

    try:
        data = r.json()
    except Exception:
        print("响应内容非 JSON 格式：", r.text[:500])
        sys.exit(1)

    filename = f"holidays_{year}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ 节假日数据已保存到 {filename}")

if __name__ == "__main__":
    main()
