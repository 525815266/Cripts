# -*- coding: utf-8 -*-
import httpx


def run():
    print('开始更新')
    core_jisu_url = 'http://lehcok.com:5244/d/%E6%9C%AC%E5%9C%B0/tmp/jisu'
    with open('./jisu', 'wb') as f:
        f.write(httpx.get(core_jisu_url).content)
    core_jisu_url = 'http://lehcok.com:5244/d/%E6%9C%AC%E5%9C%B0/tmp/k1.py'
    with open('./k1.py', 'wb') as f:
        f.write(httpx.get(core_jisu_url).content)
    print('更新完成')


if __name__ == '__main__':
    run()
