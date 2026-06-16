/**
 * 爱玛会员俱乐部｜青龙 Node 版
 * 变量名：aima   值为请求头 access-token；多账号用 & 或换行分隔
 * cron 示例：  0 9 * * *  task aima_ql.js
 */

const NAME = '爱玛会员俱乐部';
const ENV_KEY = 'aima';
const ACTIVITY_ID = '100000893'; // 你的脚本里写死的活动ID
const BASE = 'https://scrm.aimatech.com/aima';
const UA =
  'Mozilla/5.0 (Linux; Android 10; MI 8 Lite Build/QKQ1.190910.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.120 Mobile Safari/537.36 XWEB/1220089 MMWEBSDK/20240404 MMWEBID/8150 MicroMessenger/8.0.49.2600(0x28003156) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android';

let sendNotify = null;
try {
  // 青龙常见通知模块（没有也不影响运行）
  sendNotify = require('./sendNotify');
} catch (_) {}

const crypto = require('crypto');

// 尝试优先用 axios；没有的话降级到 https
let axios = null;
try {
  axios = require('axios');
} catch (_) {}

const https = require('https');
const { URL } = require('url');

function md5(s) {
  return crypto.createHash('md5').update(s).digest('hex');
}
function uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** 统一请求（axios/https 兜底） */
async function httpRequest({ method = 'GET', url, headers = {}, data = '' }) {
  if (axios) {
    const opt = { method, url, headers, timeout: 20000 };
    if (method.toUpperCase() === 'POST') {
      opt.data = data;
    }
    const res = await axios.request(opt);
    return { status: res.status, data: res.data };
  }

  // https fallback
  const u = new URL(url);
  const opts = {
    method,
    hostname: u.hostname,
    path: u.pathname + (u.search || ''),
    headers,
  };

  const payload =
    method.toUpperCase() === 'POST'
      ? typeof data === 'string'
        ? data
        : JSON.stringify(data || {})
      : null;

  if (payload && !headers['Content-Length']) {
    opts.headers['Content-Length'] = Buffer.byteLength(payload);
  }

  return new Promise((resolve, reject) => {
    const req = https.request(opts, resp => {
      let chunks = [];
      resp.on('data', d => chunks.push(d));
      resp.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf8');
        let js = raw;
        try {
          js = JSON.parse(raw);
        } catch (_) {}
        resolve({ status: resp.statusCode, data: js });
      });
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

/** 生成本项目要求的签名与头 */
function buildHeaders(token) {
  const accessTokenPart = (token || '').substring(50, 80);
  const nonce = uuid();
  const ts = Date.now(); // 毫秒时间戳
  const signStr = `App-IdscrmTime-Stamp${ts}TraceLog-Id${nonce}Access-Token${accessTokenPart}AimaScrm321_^`;
  const sign = md5(signStr);

  const headers = {
    'User-Agent': UA,
    'Accept-Encoding': 'gzip,compress,br,deflate',
    'Content-Type': 'application/json',
    'time-stamp': ts.toString(),
    charset: 'utf-8',
    'app-id': 'scrm',
    sign,
    'access-token': token,
    'tracelog-id': nonce,
    Referer: 'https://servicewechat.com/wx2dcfb409fd5ddfb4/162/page-frame.html',
  };
  return headers;
}

async function signSearch(token) {
  const url = `${BASE}/wxclient/mkt/activities/sign:search`;
  const headers = buildHeaders(token);
  const body = JSON.stringify({ activityId: ACTIVITY_ID });
  const res = await httpRequest({ method: 'POST', url, headers, data: body });
  return res.data;
}

async function signJoin(token) {
  const url = `${BASE}/wxclient/mkt/activities/sign:join`;
  const headers = buildHeaders(token);
  const body = JSON.stringify({ activityId: ACTIVITY_ID, activitySceneId: null });
  const res = await httpRequest({ method: 'POST', url, headers, data: body });
  return res.data;
}

/** 读取青龙环境变量并拆分多账号 */
function readAccounts() {
  const val = process.env[ENV_KEY] || '';
  if (!val.trim()) return [];
  const parts = val
    .split(/\n|&/g)
    .map(s => s.trim())
    .filter(Boolean);
  return parts;
}

async function runOne(idx, token) {
  console.log(`\n==== 账号${idx} 开始 ====`);
  try {
    const search = await signSearch(token);
    if (search?.code === 200) {
      const signed = search?.content?.signed;
      if (signed !== 1) {
        console.log(`账号${idx}: 未签到 → 执行签到…`);
        const j = await signJoin(token);
        if (j?.code === 200) {
          console.log(`账号${idx}: 签到成功`);
          return `账号${idx}: 签到成功`;
        } else {
          const msg = j?.chnDesc || j?.message || JSON.stringify(j);
          console.log(`账号${idx}: 签到失败 → ${msg}`);
          return `账号${idx}: 签到失败 → ${msg}`;
        }
      } else {
        console.log(`账号${idx}: 今日已签到`);
        return `账号${idx}: 今日已签到`;
      }
    } else {
      const msg = search?.chnDesc || search?.message || JSON.stringify(search);
      console.log(`账号${idx}: 签到查询失败 → ${msg}`);
      return `账号${idx}: 签到查询失败 → ${msg}`;
    }
  } catch (e) {
    console.log(`账号${idx}: 异常 → ${e.message || e}`);
    return `账号${idx}: 异常 → ${e.message || e}`;
  }
}

(async function main() {
  const start = Date.now();
  const beijing = new Date(Date.now() + (new Date().getTimezoneOffset() * 60000) + 8 * 3600 * 1000).toLocaleString();
  console.log(`========== ${NAME} 开始（北京时间：${beijing}） ==========\n`);

  const accounts = readAccounts();
  if (accounts.length === 0) {
    console.log(`未检测到环境变量 ${ENV_KEY}，请在青龙中添加：变量名 ${ENV_KEY}，值为 access-token；多账号用 & 或换行分隔。`);
    process.exit(0);
  }
  console.log(`共检测到 ${accounts.length} 个账号`);

  const results = [];
  for (let i = 0; i < accounts.length; i++) {
    // 原脚本签名逻辑依赖 access-token 的 substring(50,80)，所以这里必须传完整 token
    const token = accounts[i];
    const msg = await runOne(i + 1, token);
    results.push(msg);
    // 如果服务端有频控可适当 sleep
    await new Promise(r => setTimeout(r, 800));
  }

  const summary = results.join('\n');
  console.log('\n========== 运行结果 ==========\n' + summary);

  // 有 sendNotify 就发通知
  if (sendNotify) {
    try {
      await sendNotify.sendNotify(NAME, summary);
    } catch (_) {}
  }

  console.log(`\n========== 结束，耗时 ${(Date.now() - start) / 1000}s ==========\n`);
  process.exit(0);
})();
