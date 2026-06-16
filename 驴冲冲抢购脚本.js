/*
 * 驴充充全自动抢购脚本 [卡点增强版 v4 | 失败原因可见 + 以目标服务器时间校准（多采样取中位数更稳）]
 * 运行前需安装依赖: npm install axios
 *
 * 主要改动：
 * 1) 校准优先使用 appapi.lvcchong.com 响应头 Date（最贴近判定服务器时间），再回退腾讯/苏宁
 * 2) 失败分支不再“吞掉”，会打印 code/message（方便定位：未开始/风控/频繁/参数错误等）
 * 3) advanceTime 默认改为 0（避免提前 100~200ms 被判定“活动未开始”）
 * 4) 倒计时等待更细粒度，最后几十毫秒忙等，减少 setTimeout 过头
 */

const axios = require('axios');
const https = require('https');

// ================= 👤 账号配置 (务必修改) =================
const CONFIG = {
  // 👇👇👇【这里必须改】填入你的真实手机号 👇👇👇
  phone: "<PHONE>",

  userId: "72902801", // 你的 UserId

  // ⚡ 并发数（过高可能触发风控/频繁）
  concurrency: 15,

  // 🚀 提前量 (毫秒)
  // 建议先用 0 或 -30（宁可稍晚一点点，也不要提前被判“未开始”）
  advanceTime: 350,

  // 🕒 开启时间校准
  fixTime: true,

  // 打印更详细的请求/错误信息（建议先开 true 跑 1~2 次定位问题）
  debug: true,

  // ⏱️ 多采样校准参数（目标服务器校准时使用）
  // 启动时建议 5 次采样；开抢前复校建议 7 次采样（脚本里已自动区分）
  // 如你网络抖动很大，可把 pick 调小一点（如2）或 samples 调大一点（如9）
  // calibPick: 3 表示选 RTT 最小的 3 次，再取 offset 中位数
  calibPick: 3,
  calibGapMs: 60,

  // 🧨 抢券出手策略（对抗 -2000 网络繁忙/限流）
  // waves: 分几波发（避免一次 15 并发全被限流）
  waves: [5, 5, 5],        // 三波，每波 5 个请求（总 15）
  waveGapMs: 45,           // 波与波之间间隔（ms）
  retryWindowMs: 650,      // 若返回 -2000/网络繁忙，在这个窗口内快速重试
  retryBackoffMs: [35, 55, 85, 130, 200], // 重试退避序列（ms）


  // 登录失败重试：最大次数（设为 0 表示无限重试）
  loginMaxRetries: 0,
  // 登录失败后基础等待（ms），会做指数退避 + 抖动
  loginRetryBaseDelay: 600,
};
// ========================================================

let TARGET = { id: "", price: "", targetDate: null, name: "" };
let TIME_OFFSET = 0; // 时间偏差（毫秒，整数）
let hasRecalibrated = false;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// axios keep-alive
const agent = new https.Agent({
  keepAlive: true,
  keepAliveMsecs: 1000,
  maxSockets: Infinity,
});

const request = axios.create({
  timeout: 8000,
  httpsAgent: agent,
  headers: {
    "User-Agent":
      "Mozilla/5.0 (Linux; Android 15; 23049RAD8C Build/AQ3A.241006.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/142.0.7444.173 Mobile Safari/537.36 XWEB/1420125 MMWEBSDK/20251006 MMWEBID/2234 MicroMessenger/8.0.66.2980(0x28004252) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 miniProgram/wx0132aa93a8b214ae",
    "Content-Type": "application/x-www-form-urlencoded",
    Origin: "https://h5.lvcchong.com",
    Referer: "https://h5.lvcchong.com/",
    Connection: "keep-alive",
  },
});

// 获取“校准后”的当前时间戳
function getNow() {
  // 始终返回整数毫秒，避免 time=... 出现小数导致“参数错误”
  return Math.round(Date.now() + TIME_OFFSET);
}

function nowStr() {
  const d = new Date(getNow());
  return (
    d.toLocaleString("zh-CN", { hour12: false }) +
    `.${String(d.getMilliseconds()).padStart(3, "0")}`
  );
}

function logDebug(...args) {
  if (CONFIG.debug) console.log(...args);
}

// ================= 时间校准：优先用目标服务器 Date =================

async function calibrateByTargetServerOnce() {
  // 用目标域名响应头 Date 校准（单次采样）
  const url = "https://appapi.lvcchong.com/";
  const start = Date.now();
  const res = await axios.get(url, {
    timeout: 2000,
    httpsAgent: agent,
    validateStatus: () => true,
    headers: {
      "User-Agent": "Mozilla/5.0",
      Connection: "keep-alive",
    },
  });
  const end = Date.now();

  const dateHeader = res.headers && (res.headers.date || res.headers.Date);
  if (!dateHeader) throw new Error("目标服务器无 Date 响应头");

  const serverTime = new Date(dateHeader).getTime();
  if (!Number.isFinite(serverTime)) throw new Error("无法解析目标服务器 Date");

  const rtt = end - start;
  const latency = rtt / 2;
  const trueServerTime = serverTime + latency;
  const offset = trueServerTime - end;

  return { offset, rtt };
}

function medianInt(arr) {
  const a = [...arr].sort((x, y) => x - y);
  const mid = Math.floor(a.length / 2);
  if (a.length % 2) return Math.round(a[mid]);
  return Math.round((a[mid - 1] + a[mid]) / 2);
}

async function calibrateByTargetServer(label, samples = 5, pick = 3, gapMs = 60) {
  // 多次采样：挑 RTT 最小的 pick 次，用 offset 的“中位数”作为最终 TIME_OFFSET（更稳）
  const results = [];
  for (let i = 0; i < samples; i++) {
    try {
      const r = await calibrateByTargetServerOnce();
      results.push(r);
    } catch (e) {
      // 忽略单次失败
    }
    await sleep(gapMs);
  }
  if (results.length === 0) throw new Error("目标服务器多采样全部失败");

  results.sort((a, b) => a.rtt - b.rtt);
  const chosen = results.slice(0, Math.min(pick, results.length));

  const finalOffset = medianInt(chosen.map((x) => x.offset));
  TIME_OFFSET = Math.round(finalOffset);

  const best = chosen[0];
  const worst = chosen[chosen.length - 1];
  const sign = TIME_OFFSET > 0 ? "+" : "";
  console.log(
    `🆗 ${label}完成! [目标服务器多采样] 偏差修正: ${sign}${Math.floor(TIME_OFFSET)}ms ` +
      `(采样${results.length}次, 取RTT最小${chosen.length}次, RTT范围${best.rtt}~${worst.rtt}ms)`
  );
  console.log(`🕒 当前精准时间: ${nowStr()}`);
  return true;
}

async function calibrateByTencent(label) {
  // 腾讯源 vv.video.qq.com
  const HEADERS_TIME = {
    "User-Agent":
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    Referer: "http://www.qq.com",
  };

  const start = Date.now();
  const res = await axios.get(`http://vv.video.qq.com/checktime?otype=json&t=${start}`, {
    timeout: 2000,
    headers: HEADERS_TIME,
    validateStatus: () => true,
  });
  const end = Date.now();

  const raw = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
  const match = raw.match(/"t":(\d+)/);
  if (!match || !match[1]) throw new Error("腾讯源未返回 t 字段");

  const serverTime = parseInt(match[1], 10) * 1000;
  const latency = (end - start) / 2;
  const trueServerTime = serverTime + latency;

  TIME_OFFSET = trueServerTime - end;
  const sign = TIME_OFFSET > 0 ? "+" : "";
  console.log(`🆗 ${label}完成! [腾讯源] 偏差修正: ${sign}${Math.floor(TIME_OFFSET)}ms`);
  console.log(`🕒 当前精准时间: ${nowStr()}`);
  return true;
}

async function calibrateBySuning(label) {
  // 备用：苏宁
  const HEADERS_TIME = {
    "User-Agent":
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    Referer: "http://www.suning.com",
  };

  const start = Date.now();
  const res = await axios.get(`http://quan.suning.com/getSysTime.do`, {
    timeout: 2000,
    headers: HEADERS_TIME,
    validateStatus: () => true,
  });
  const end = Date.now();
  if (!res.data || !res.data.sysTime2) throw new Error("苏宁源未返回 sysTime2");

  const serverTime = new Date(res.data.sysTime2).getTime();
  if (!Number.isFinite(serverTime)) throw new Error("无法解析苏宁 sysTime2");

  // 仍做 RTT/2 修正
  const latency = (end - start) / 2;
  const trueServerTime = serverTime + latency;

  TIME_OFFSET = trueServerTime - end;
  const sign = TIME_OFFSET > 0 ? "+" : "";
  console.log(`🆗 ${label}完成! [苏宁] 偏差修正: ${sign}${Math.floor(TIME_OFFSET)}ms`);
  console.log(`🕒 当前精准时间: ${nowStr()}`);
  return true;
}

// 🔥 时间校准入口：目标服务器 -> 腾讯 -> 苏宁
async function calibrateTime(isRecheck = false) {
  if (!CONFIG.fixTime) return false;

  const label = isRecheck ? "⚡ 抢前终极校准" : "✅ 启动初次校准";
  console.log(`[系统] 正在进行 ${label}...`);

  try {
    return await calibrateByTargetServer(label, isRecheck ? 7 : 5, CONFIG.calibPick || 3, CONFIG.calibGapMs || 60);
  } catch (e) {
    logDebug(`⚠️ 目标服务器校准失败: ${e.message}`);
  }

  try {
    return await calibrateByTencent(label);
  } catch (e) {
    logDebug(`⚠️ 腾讯源校准失败: ${e.message}`);
  }

  try {
    return await calibrateBySuning(label);
  } catch (e) {
    console.log(`❌ 校准失败（全部源不可用），保持本机时间。原因: ${e.message}`);
    return false;
  }
}

// ================= 业务接口 =================

// 1) 登录
async function loginOnce() {
  console.log(`[${nowStr()}] 🔄 正在登录...`);
  try {
    const paramsObj = {
      phone: CONFIG.phone,
      userId: CONFIG.userId,
      time: String(getNow()),
      ownerId: "0",
    };
    const params = new URLSearchParams(paramsObj).toString();

    const res = await request.post(
      "https://appapi.lvcchong.com/appBaseApi/h5/accessEntrance",
      params
    );

    if (res.data && res.data.code === 200 && res.data.data && res.data.data.userToken) {
      request.defaults.headers.common["token"] = res.data.data.userToken;
      console.log(`[${nowStr()}] ✅ 登录成功`);
      return { ok: true, data: res.data };
    }

    const payload = res.data || {};
    console.log(`❌ 登录失败: ${JSON.stringify(payload)}`);

    // 额外打印关键入参，便于排查“参数错误”
    if (CONFIG.debug) {
      console.log(`   ↳ 登录入参: ${JSON.stringify(paramsObj)}`);
    }

    return { ok: false, data: payload };
  } catch (e) {
    console.log(`❌ 登录异常: ${e.message}`);
    return { ok: false, data: { code: "EXCEPTION", message: e.message } };
  }
}

async function login() {
  // 0 表示无限重试（除非手动 Ctrl+C）
  const max = Number(CONFIG.loginMaxRetries || 0);
  let attempt = 0;

  while (true) {
    attempt += 1;
    const r = await loginOnce();
    if (r.ok) return true;

    const code = r.data && r.data.code;
    const msg = (r.data && (r.data.message || r.data.msg)) || "";

    // 如果是“参数错误/时间问题/签名问题”的泛化提示，先重新校准一次再重试
    if (CONFIG.fixTime && (msg.includes("参数错误") || code === -1)) {
      console.log(`   ↳ 检测到“参数错误”类返回，尝试重新校准时间后再登录...`);
      await calibrateTime(true);
    }

    // 是否达到最大次数
    if (max > 0 && attempt >= max) {
      console.log(`❌ 登录重试已达上限（${max} 次），脚本退出。`);
      return false;
    }

    // 指数退避 + 抖动，避免频繁触发风控/限流
    const base = Number(CONFIG.loginRetryBaseDelay || 600);
    const backoff = Math.min(base * Math.pow(1.6, attempt - 1), 12000); // 上限 12s
    const jitter = Math.floor(Math.random() * 400); // 0~399ms
    const waitMs = Math.floor(backoff + jitter);

    console.log(`   ↳ ${waitMs}ms 后第 ${attempt + 1} 次重试登录...`);
    await sleep(waitMs);
  }
}


async function getProductDetail(productId) {
  try {
    const params = new URLSearchParams({
      productId: productId,
      userId: CONFIG.userId,
    }).toString();
    const res = await request.post(
      "https://appapi.lvcchong.com/appBaseApi/scoreUser/getProductById",
      params
    );
    if (res.data && res.data.code === 200 && res.data.data) return res.data.data;
  } catch (e) {
    logDebug(`getProductDetail 异常: ${e.message}`);
  }
  return null;
}

// 2) 深度扫描：锁定最近一场“充电券”
async function analyzeTargets() {
  console.log(`[${nowStr()}] 🔍 扫描活动目录...`);
  try {
    const params = new URLSearchParams({
      pageNum: "1",
      pageSize: "30",
      categoryIds: "59;53;54;55;56;57;58;52;51;60",
      productChannel: "1",
    }).toString();

    const res = await request.post(
      "https://appapi.lvcchong.com/appBaseApi/scoreUser/getMenuProduct",
      params
    );

    if (!res.data || res.data.code !== 200 || !res.data.data) {
      console.log(`❌ 扫描失败: ${JSON.stringify(res.data)}`);
      return false;
    }

    const candidates = res.data.data.filter((p) => p.productName && p.productName.includes("充电券"));
    if (candidates.length === 0) {
      console.log("❌ 未找到充电券活动");
      return false;
    }

    const validTargets = [];
    const now = getNow();

    for (const item of candidates) {
      const detail = await getProductDetail(item.id);
      if (detail && detail.hourTime) {
        const [h, m, s] = detail.hourTime.split(":").map(Number);
        const tDate = new Date(now);
        tDate.setHours(h, m, s, 0);
        if (now > tDate.getTime()) tDate.setDate(tDate.getDate() + 1);

        validTargets.push({
          id: item.id,
          price: item.price,
          name: item.productName,
          targetDate: tDate,
        });
        console.log(`   👉 [${item.productName}] 开抢:${detail.hourTime}`);
      }
    }

    if (validTargets.length === 0) return false;

    validTargets.sort((a, b) => a.targetDate - b.targetDate);
    TARGET = validTargets[0];

    console.log(`\n🎯 锁定目标: 【${TARGET.name}】`);
    console.log(`⏰ 开抢时间: ${TARGET.targetDate.toLocaleString()}`);

    const waitMs = TARGET.targetDate.getTime() - getNow();
    console.log(`⏳ 剩余等待: ${(waitMs / 1000 / 60).toFixed(2)} 分钟`);
    return true;
  } catch (e) {
    console.log(`❌ 扫描异常: ${e.message}`);
    return false;
  }
}

// 3) 抢购：不再吞失败原因
function generateAttackPromise(index) {
  const data = new URLSearchParams({
    id: TARGET.id,
    price: TARGET.price,
    purchaseNumber: "1",
    orderSource: "3",
    channelName: "微信小程序",
    isExchangeLimit: "0",
  }).toString();

  const t0 = Date.now();
  return request
    .post(
      "https://appapi.lvcchong.com/appBaseApi/scoreUser/score/createScoreOrder",
      data
    )
    .then((res) => {
      const t1 = Date.now();
      const r = res.data || {};
      const code = r.code;
      const msg = r.message || r.msg || "";

      if (code === 200 || (typeof msg === "string" && msg.includes("成功"))) {
        console.log(`🎉🎉🎉 [线程${index}] 抢购成功！(耗时${t1 - t0}ms)`);
        return { ok: true, code, msg };
      }

      // 常见失败关键词仍保留“醒目提示”
      const printable = msg || JSON.stringify(r);
      if (printable.includes("积分")) console.log(`😭 [线程${index}] 积分不足：${printable}`);
      else if (printable.includes("库存")) console.log(`❌ [线程${index}] 无库存：${printable}`);
      else if (printable.includes("未开始") || printable.includes("未到") || printable.includes("开始")) {
        console.log(`⏳ [线程${index}] 活动未开始/未到时间：code=${code} msg=${printable}`);
      } else if (printable.includes("频繁") || printable.includes("稍后") || printable.includes("再试")) {
        console.log(`🛑 [线程${index}] 触发频繁/限流：code=${code} msg=${printable}`);
      } else if (printable.includes("验证码") || printable.includes("人机") || printable.includes("风控")) {
        console.log(`🧩 [线程${index}] 可能需要验证码/风控：code=${code} msg=${printable}`);
      } else {
        console.log(`⚠️ [线程${index}] 失败：code=${code} msg=${printable}`);
      }

      return { ok: false, code, msg: printable };
    })
    .catch((e) => {
      const errMsg =
        (e.response && JSON.stringify(e.response.data)) ||
        e.message ||
        "unknown error";
      console.log(`🌩️ [线程${index}] 请求异常: ${errMsg}`);
      return { ok: false, code: "NETWORK_ERR", msg: errMsg };
    });
}

// ================= 主程序 =================

async function start() {
  console.log(`\n🚀 启动脚本 [卡点增强版 v4]...`);
  console.log(`⚙️ 并发=${CONFIG.concurrency} 提前量=${CONFIG.advanceTime}ms 校准=${CONFIG.fixTime} debug=${CONFIG.debug}`);

  // 第一次校准（启动）
  await calibrateTime(false);

  if (!(await login())) return;
  if (!(await analyzeTargets())) return;

  console.log(`[${nowStr()}] 🔥 预热连接完毕，挂机中...`);
  try {
    const warmUpParams = new URLSearchParams({ userId: CONFIG.userId }).toString();
    await request.post(
      "https://appapi.lvcchong.com/appBaseApi/scoreUser/checkUserScoreBalance",
      warmUpParams
    );
  } catch (e) {
    logDebug(`预热失败(可忽略): ${e.message}`);
  }

  while (true) {
    const diff = TARGET.targetDate.getTime() - getNow();

    // 在剩余 40s ~ 30s 做“终极复校”，避免最后冲刺期波动
    if (CONFIG.fixTime && !hasRecalibrated && diff <= 40000 && diff > 30000) {
      console.log(`\n⏰ 此时距离开抢约 ${(diff / 1000).toFixed(1)}s，开始终极复校...`);
      await calibrateTime(true);
      hasRecalibrated = true;
      console.log(`[${nowStr()}] 🔥 状态更新完毕，最后 30秒 倒计时！`);
      continue;
    }

    if (diff <= CONFIG.advanceTime) {
      console.log(`\n⚡ [${nowStr()}] 时间到 (剩余${diff}ms)，全军出击！`);
      // 分波出手 + 限流快速重试
      const attackStart = Date.now();

      async function attackWithRetry(workerId) {
        // 在 retryWindowMs 内，如果遇到 -2000/网络繁忙 就重试几次
        const deadline = attackStart + (CONFIG.retryWindowMs || 650);
        let attempt = 0;

        while (true) {
          const r = await generateAttackPromise(workerId);
          if (r && r.ok) return r;

          const msg = (r && r.msg) || "";
          const isBusy = msg.includes("-2000") || msg.includes("网络繁忙") || msg.includes("稍后重试");
          const isSoldOut = msg.includes("售罄") || msg.includes("已售罄") || msg.includes("库存");

          // 已售罄就别再浪费窗口了
          if (isSoldOut) return r;

          if (!isBusy) return r;

          const now = Date.now();
          if (now >= deadline) return r;

          const backoffs = CONFIG.retryBackoffMs || [35, 55, 85, 130, 200];
          const wait = backoffs[Math.min(attempt, backoffs.length - 1)] + Math.floor(Math.random() * 20);
          attempt++;
          await sleep(wait);
        }
      }

      const results = [];
      const waves = Array.isArray(CONFIG.waves) && CONFIG.waves.length ? CONFIG.waves : [CONFIG.concurrency];
      let workerId = 1;

      for (let w = 0; w < waves.length; w++) {
        const count = waves[w];
        const batch = [];
        for (let i = 0; i < count && workerId <= CONFIG.concurrency; i++) {
          batch.push(attackWithRetry(workerId));
          workerId++;
        }
        // 并行执行该波
        results.push(...(await Promise.all(batch)));

        // 若已有成功，就不继续后续波（节省风控风险）
        const okCountNow = results.filter((x) => x && x.ok).length;
        if (okCountNow > 0) break;

        if (w < waves.length - 1) await sleep(CONFIG.waveGapMs || 45);
      }

      const okCount = results.filter((x) => x && x.ok).length;

      console.log(`🏁 [${nowStr()}] 抢购结束：成功 ${okCount}/${results.length}`);
      break;
    }

    // 更细粒度等待，最后几十毫秒忙等，避免 setTimeout 过头
    if (diff > 5000) {
      await sleep(1000);
      process.stdout.write(`等待中... ${Math.floor(diff / 1000)}s   \r`);
    } else if (diff > 800) {
      await sleep(100);
      process.stdout.write(`等待中... ${(diff / 1000).toFixed(2)}s   \r`);
    } else if (diff > 120) {
      await sleep(10);
      process.stdout.write(`⚡ 锁定中... ${(diff / 1000).toFixed(3)}s   \r`);
    } else if (diff > 30) {
      await sleep(2);
      process.stdout.write(`⚡ 锁定中... ${(diff / 1000).toFixed(3)}s   \r`);
    } else {
      // 最后 30ms 忙等到触发点
      while (TARGET.targetDate.getTime() - getNow() > CONFIG.advanceTime) {}
    }
  }
}

start();
