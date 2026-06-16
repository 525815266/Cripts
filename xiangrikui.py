import os
import time
import random
import requests

UA_APP = "SLCC/15.5.1 (IOS,appname=sunloginControlClient)"

REFRESH_URL = "https://api-std.sunlogin.oray.com/authorize/refreshing"
TOKENLOGIN_URL = "<SENSITIVE>"
TOKEN_LOGIN_WEB = "<SENSITIVE>"

SIGN_URL = "https://store-api.oray.com/points/sign"
# 注意：income 不要写死 0，运行时用 pointid 拼
INCOME_URL_TMPL = "https://store-api.oray.com/point/{pointid}/income"
BALANCE_URL = "https://store-api.oray.com/point/balance"
INCOMES_URL = "https://store-api.oray.com/point/incomes"

# ====== 以后不看 HAR，只从环境变量/配置拿 ======
OLD_ACCESS_TOKEN ="<JWT_TOKEN>"
REFRESH_TOKEN = "<SENSITIVE>"
POINT_KEY = os.getenv("SL_POINT_KEY", "")

SL_EX_CLIENT_ID="<SENSITIVE>"
SL_X_APPID="kNUC97u86Zr7mt9xeZVl"
#export SL_ACCESS_TOKEN="<SENSITIVE>"
#export SL_REFRESH_TOKEN="<SENSITIVE>"
SL_USERID="<SENSITIVE>"



def base_store_headers():
    return {
        "User-Agent": UA_APP,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Origin": "https://sunlight.oray.com",
        "Referer": "https://sunlight.oray.com/",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    }


def refresh_tokens(sess: requests.Session, old_access: str, refresh_token: str):
    """
    不依赖 HAR 的做法：允许配置 client id / appid。
    如果你没配 EX_CLIENT_ID / X_APPID，这里大概率会失败，我们会在 main 里捕获并降级。
    """
    headers = {
        "Authorization": f"Bearer {old_access}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": UA_APP,
    }
    if EX_CLIENT_ID:
        headers["EX-ClientId"] = EX_CLIENT_ID
    if X_APPID:
        headers["X-AppID"] = X_APPID
        headers["ns"] = "user"
        headers["Country-Region"] = "zh_CN"

    body = {"refresh_token": refresh_token, "access_token": old_access}
    r = sess.post(REFRESH_URL, headers=headers, json=body, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"[refreshing] HTTP {r.status_code}: {r.text}")
    j = r.json()
    return j["access_token"], j["refresh_token"]


def tokenlogin(sess: requests.Session, access_token: str):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": UA_APP,
    }
    r = sess.get(TOKENLOGIN_URL, headers=headers, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"[tokenlogin] HTTP {r.status_code}: {r.text}")
    j = r.json()
    return j["access_token"], j.get("refresh_token")


def web_token_login(sess: requests.Session, token: str):
    """拿 oray.com cookie（有些账号/环境 store-api 可能会用到）"""
    params = {"app_id": "sunlogin", "token": token, "url": "https://sunlight.oray.com/?tab=sunlogin"}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    sess.get(TOKEN_LOGIN_WEB, headers=headers, params=params, allow_redirects=True, timeout=20)


class AuthStrategy:
    """
    store-api 的“鉴权方式候选集”：
    1) 只用基础头（有些接口本来就不需要鉴权）
    2) 叠加 cookie（web_token_login 后 session 里会有）
    3) 加 bearer token（某些环境需要）
    4) cookie + bearer 一起上
    """
    def __init__(self, name: str, bearer: str | None = None):
        self.name = name
        self.bearer = bearer

    def headers(self):
        h = base_store_headers()
        if self.bearer:
            h["Authorization"] = f"Bearer {self.bearer}"
        return h


def request_with_strategies(sess: requests.Session, method: str, url: str, strategies: list[AuthStrategy], **kwargs):
    last = None
    for st in strategies:
        try:
            r = sess.request(method, url, headers=st.headers(), timeout=20, **kwargs)
            # 200/201/204 视为成功；你也可以按接口实际返回调整
            if r.status_code in (200, 201, 204):
                return r, st
            last = (r, st)
        except Exception as e:
            last = (e, st)
    # 全失败：把最后一次结果抛出去便于定位
    if isinstance(last[0], Exception):
        raise RuntimeError(f"[{method} {url}] all strategies failed, last={last[1].name}: {last[0]}")
    r, st = last
    raise RuntimeError(f"[{method} {url}] all strategies failed, last={st.name}: HTTP {r.status_code} {r.text}")


def get_pointid_from_sign(resp_text: str):
    """
    /points/sign 返回 JSON，里面通常有 pointid。
    解析失败就返回 None，让后续走 fallback（比如 income 不跑，只查余额/明细）。
    """
    try:
        j = requests.models.complexjson.loads(resp_text)
        pid = j.get("pointid")
        if isinstance(pid, int):
            return pid
    except Exception:
        pass
    return None


def run_once(sess: requests.Session, strategies: list[AuthStrategy]):
    # 1) sign
    r1, st1 = request_with_strategies(sess, "GET", SIGN_URL, strategies)
    print(f"GET /points/sign: {r1.status_code} via={st1.name} {(r1.text or '')[:220]}")
    pointid = get_pointid_from_sign(r1.text)

    # 2) income（用 pointid 拼；pointid 解析不到就跳过）
    if pointid is not None and POINT_KEY:
        income_url = INCOME_URL_TMPL.format(pointid=pointid)
        r2, st2 = request_with_strategies(
            sess, "POST", income_url, strategies, data={"point_key": POINT_KEY}
        )
        print(f"POST /point/{pointid}/income: {r2.status_code} via={st2.name} {(r2.text or '')[:260]}")
    else:
        print(f"[SKIP] income: pointid={pointid}, point_key={'set' if POINT_KEY else 'empty'}")

    # 3) 验证：余额/收入明细（这两步能帮你确认“是否实际到账”，不依赖 income 是否成功）
    r3, st3 = request_with_strategies(sess, "GET", BALANCE_URL, strategies)
    print(f"GET /point/balance: {r3.status_code} via={st3.name} {(r3.text or '')[:220]}")
    r4, st4 = request_with_strategies(sess, "GET", INCOMES_URL, strategies)
    print(f"GET /point/incomes: {r4.status_code} via={st4.name} {(r4.text or '')[:220]}")


def main():
    sess = requests.Session()

    bearer_candidates = [None]  # 先无 bearer
    # 尝试走 token 链路：成功则加入 bearer 候选 + 获取 cookie
    try:
        if OLD_ACCESS_TOKEN and REFRESH_TOKEN:
            new_access, _ = refresh_tokens(sess, OLD_ACCESS_TOKEN, REFRESH_TOKEN)
            web_access, _ = tokenlogin(sess, new_access)
            web_token_login(sess, web_access)
            bearer_candidates.append(web_access)
            print("<SENSITIVE>")
        else:
            print("[INFO] token env not set; skip token chain")
    except Exception as e:
        print("[WARN] token chain failed; will still try store-api with other strategies:", e)

    # 构造策略：无 bearer / bearer（如有）
    strategies = [AuthStrategy("base(no bearer)", None)]
    for b in bearer_candidates:
        if b:
            strategies.append(AuthStrategy("bearer", b))
    # cookie 是在 session 里自然携带的（web_token_login 成功时）；不需要单独策略名区分
    # 但为了“可视化”，我们再加一个“cookie+bearer”并不改变 headers，只是表示你期望 cookie 存在
    for b in bearer_candidates:
        if b:
            strategies.append(AuthStrategy("cookie+bearer", b))

    # 重试策略：遇到“已签到/已领取”应当停；这里先给你一个简单版本（失败就指数退避）
    for i in range(1, 6):
        print(f"\n=== Attempt {i}/5 ===")
        try:
            run_once(sess, strategies)
            break
        except Exception as e:
            print("[ERR]", e)
            time.sleep(min(8, 0.8 * (2 ** (i - 1))) + random.uniform(0, 0.6))


if __name__ == "__main__":
    main()