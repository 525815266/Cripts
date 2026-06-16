// @LastEditTime: "2026-02-26 12:00" by：yaohuo24245
/*
联通权益超市脚本 (动态惊喜福利版 + 兜底机制 + 超市任务抽奖)
更新点：
  1. 新增动态获取“福享权益天天领”商品详情、productCode。
  2. 新增兑换前置的 unlock/surpriseInterest 解锁动作。
  3. 新增动态获取失败时的自定义ID兜底开关 (ENABLE_FALLBACK_PRODUCT)。
  4. 完美保留了原版的所有底层登录、加解密及防风控 UA。
*/

const $ = new Env("联通权益超市自动抢兑");
const crypto = require("crypto");

// ==================== 核心配置区 ====================
const ENABLE_PANIC_BUY = true;       // 是否开启抢购兑换福利模式
const ENABLE_FALLBACK_PRODUCT = true; // 是否开启兜底机制（动态获取失败时，是否使用下面的自定义兜底配置）
const ENABLE_DAILY_TASK = true;      // 是否开启日常做任务及抽奖模式
const MANUAL_TEST_MODE = true;    // 是否开启测试模式

const FIXED_CONFIG = {
  pushplus_token: "填自己的token", 
  target_phone: "填自己的手机号",   //可填可不填 
  account: "填自己的QQ号",   //可填可不填因为没有QQ音乐了
  // 兜底商品配置 (当动态获取异常时使用)
  panic_config: {
    activityId: 11,
    productId: 371, 
    productCode: "1000011204",
    accountType: "4" 
  },
  daily_config: { activityId: 12 },
  stop_keywords: [
    "今天已参与活动", "请明天再来", "今日次数已用尽", "已参与", "次数上限",
    "认证失败", "商品已售罄", "活动已结束", "来晚了"
  ]
};

const IS_TEST = MANUAL_TEST_MODE || ((process.env.TEST_MODE || "").toString() === "1");
let globalMarketPoolChecked = false;
let globalMarketHasPrizes = false;

// ==================== 核心类 ====================
class UnicomAuthService {
  constructor(token_online, index = 0) {
    this.token_online = token_online;
    this.index = index + 1;
    this.mobile = "";
    this.market_token = "";
    this.market_task_yGdtco4r = "";

    this.appVersion = "android@11.0000";
    this.deviceCode = this.generateDeviceID(this.token_online); 
    this.userAgent_base = `Dalvik/2.1.0 (Linux; U; Android 9; ALN-AL10 Build/PQ3A.190705.11211540);unicom{version:${this.appVersion}}`;
    this.userAgent_market = "Mozilla/5.0 (Linux; Android 9; ONEPLUS A5000 Build/PKQ1.180716.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/138.0.7204.179 Mobile Safari/537.36; unicom{version:android@11.0000,desmobile:0};devicetype{deviceBrand:OnePlus,deviceModel:ONEPLUS A5000}";

    const { CookieJar } = require("tough-cookie");
    this.cookieJar = new CookieJar(undefined, { rejectPublicSuffixes: true, looseMode: true });
    this.got = require("got").extend({
      cookieJar: this.cookieJar,
      timeout: 30000,
      followRedirect: false,
      retry: { limit: 1 },
      headers: { "Connection": "keep-alive" }
    });
  }

  log(msg) { console.log(`账号[${this.index}] ${msg}`); }
  maskMobile(m) { return m ? m.replace(/(\d{3})\d{4}(\d{4})/, '$1****$2') : m; }
  
  generateDeviceID(key) {
    const hash = crypto.createHash('md5').update(key).digest('hex');
    return `${hash.substr(0,8)}-${hash.substr(8,4)}-${hash.substr(12,4)}-${hash.substr(16,4)}-${hash.substr(20,12)}`;
  }

  randomString(len) {
    const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-";
    let r = '';
    for (let i = 0; i < len; i++) r += chars.charAt(Math.floor(Math.random() * chars.length));
    return r;
  }

  encryptPhone(phone) {
    const pubKeyStr = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD7tGWDKF928i3HUQjJiNGeVfaYsMpqVUAT5UIZPntgHsJ7pgQgkv7Hdth9jCIZGPzjUIdyrgR9dSe7GUmbAma7bpSsJDdiPgTkz87J3ypN7RWSg74xSsQ2VZUAf9yG1mYyu9brdF/ujgeb+MTNNoWwJ22MaEFKw2+Wx/IP9x+J1QIDAQAB";
    const publicKey = `-----BEGIN PUBLIC KEY-----\n${pubKeyStr}\n-----END PUBLIC KEY-----`;
    try {
      const buffer = Buffer.from(phone.toString(), 'utf-8');
      const encrypted = crypto.publicEncrypt({
        key: publicKey,
        padding: crypto.constants.RSA_PKCS1_PADDING, 
      }, buffer);
      return encrypted.toString('base64');
    } catch (e) { return ""; }
  }

  hasStopKeyword(msg) {
    return msg && FIXED_CONFIG.stop_keywords.some(k => msg.includes(k));
  }

  async request(opt) {
    try {
      const r = await this.got(opt);
      let body = r.body;
      try { body = JSON.parse(body); } catch (e) {}
      return { statusCode: r.statusCode, headers: r.headers, result: body };
    } catch (e) {
      return { statusCode: -1, result: null, error: e.message };
    }
  }

  getMarketHeaders() {
    return {
      "Host": "backward.bol.wo.cn",
      "Connection": "keep-alive",
      "Pragma": "no-cache",
      "Cache-Control": "no-cache",
      "sec-ch-ua-platform": '"Android"',
      "User-Agent": this.userAgent_market,
      "Authorization": `Bearer ${this.market_token}`,
      "Content-type": "application/json",
      "Origin": "https://contact.bol.wo.cn",
      "X-Requested-With": "com.sinovatech.unicom.ui",
      "Referer": "https://contact.bol.wo.cn/",
      "Accept": "application/json, text/plain, */*"
    };
  }

  async onLine() {
    this.log(`正在登录 (DeviceID: ${this.deviceCode.substr(0,6)}...)...`);
    try {
        const { result } = await this.request({
          method: "post",
          url: "https://m.client.10010.com/mobileService/onLine.htm",
          headers: { "User-Agent": this.userAgent_base },
          form: {
            isFirstInstall: '1',
            netWay: 'Wifi',
            version: this.appVersion,
            deviceId: this.deviceCode,
            token_online: this.token_online,
            provinceChanel: 'general',
            deviceModel: 'ALN-AL10',
            step: 'dingshi',
            androidId: "291a7deb1d716b5a",
            reqtime: Date.now()
          }
        });

        if (result?.code == 0 || result?.code == 200) {
          this.mobile = result.desmobile || "";
          this.log(`基础登录成功 ${this.maskMobile(this.mobile)}`);
          return true;
        }
        this.log(`基础登录失败: ${result?.msg || result?.code}`);
        return false;
    } catch (e) {
        this.log(`登录异常: ${e.message}`);
        return false;
    }
  }

  async marketUnicomLogin() {
    const { headers } = await this.request({
      method: "get",
      url: "https://m.client.10010.com/mobileService/openPlatform/openPlatLineNew.htm",
      headers: { "User-Agent": this.userAgent_base },
      searchParams: { to_url: "https://contact.bol.wo.cn/" }
    });
    let ticket = null;
    if (headers?.location) {
      const u = new URL(headers.location);
      ticket = u.searchParams.get("ticket");
    }
    if (!ticket) {
      this.log("权益超市: 获取Ticket失败");
      return false;
    }
    this.market_task_yGdtco4r = this.randomString(800);
    const headers_login = this.getMarketHeaders();
    delete headers_login["Authorization"];
    headers_login["Content-type"] = "application/x-www-form-urlencoded";
    const { result } = await this.request({
      method: "post",
      url: `https://backward.bol.wo.cn/prod-api/auth/marketUnicomLogin?yGdtco4r=${this.market_task_yGdtco4r}`,
      headers: headers_login,
      form: { ticket }
    });
    if (result?.code == 200) {
      this.market_token = result.data.token;
      this.log("权益超市: 登录成功");
      return true;
    }
    this.log(`权益超市: 登录失败: ${result?.msg}`);
    return false;
  }

  // ==================== 【动态抢购与解锁】 ====================
  
  async getDynamicProduct() {
    const d = new Date(new Date().getTime() + 8 * 3600 * 1000);
    const dateStr = `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; // 格式如 2026-2-26

    const { result } = await this.request({
      method: "post",
      url: `https://backward.bol.wo.cn/prod-api/promotion/activity/roll/getActivitiesDetail?yGdtco4r=${this.market_task_yGdtco4r}`,
      headers: this.getMarketHeaders(),
      body: JSON.stringify({
        majorId: 3,
        subCodeList: ["YOUCHOICEONE"],
        currentTime: dateStr,
        withUserStatus: 1
      })
    });

    if (result?.code == 200 && result?.data?.length > 0) {
      const activity = result.data.find(a => a.activityCode === "YOUCHOICEONE");
      if (activity && activity.detailList && activity.detailList.length > 0) {
        // 找一个库存大于0的，如果没有则默认拿第一个
        const product = activity.detailList.find(p => p.leftQuantity > 0) || activity.detailList[0];
        return {
          activityId: activity.activityId,      // 例: 11
          activityCode: activity.activityCode,  // 例: YOUCHOICEONE
          productId: product.id,                // 例: 371
          productCode: product.productCode,     // 例: 1000011204
          productName: product.productName      // 例: 哔哩哔哩大会员周卡
        };
      }
    }
    return null;
  }

  async unlockProduct(productId, activityCode) {
    const { result } = await this.request({
      method: "post",
      url: `https://backward.bol.wo.cn/prod-api/promotion/activity/roll/unlock/surpriseInterest?yGdtco4r=${this.market_task_yGdtco4r}`,
      headers: this.getMarketHeaders(),
      body: JSON.stringify({
        timeVerRan: Date.now(),
        mobile: this.mobile || FIXED_CONFIG.account, 
        id: productId,
        activityId: activityCode // 固定传 YOUCHOICEONE
      })
    });
    
    if (result?.code == 200 && result?.data === true) {
      this.log(`🔓 权益解锁成功！`);
      return true;
    } else {
      this.log(`⚠️ 解锁失败: ${result?.msg || JSON.stringify(result)}`);
      return false;
    }
  }

  async receiveSurpriseRights() {
    if (!this.market_token) return false;
    
    let targetConfig = null;
    let productName = "未知商品";

    this.log("正在动态获取惊喜福利池商品...");
    const dynamicProduct = await this.getDynamicProduct();

    if (dynamicProduct) {
      productName = dynamicProduct.productName;
      this.log(`🎁 成功获取动态权益: 【${productName}】`);
      
      // 执行前置解锁
      await this.unlockProduct(dynamicProduct.productId, dynamicProduct.activityCode);
      await sleep(1000);

      targetConfig = {
        activityId: dynamicProduct.activityId,
        productId: dynamicProduct.productId,
        productCode: dynamicProduct.productCode,
        accountType: "4"
      };
    } else {
      this.log("⚠️ 动态获取权益失败或接口异常");
      if (ENABLE_FALLBACK_PRODUCT) {
        this.log("🔄 已开启兜底配置，将使用内置参数进行抢购...");
        targetConfig = FIXED_CONFIG.panic_config;
        productName = "兜底配置商品";
      } else {
        this.log("❌ 未开启兜底功能，结束本次抢购");
        return false;
      }
    }

    const targetPhone = FIXED_CONFIG.target_phone;
    let encryptedTarget = (targetPhone && targetPhone.length === 11) ? this.encryptPhone(targetPhone) : "";
    
    const d = new Date(new Date().getTime() + 8 * 3600 * 1000);
    const dateStr = `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; 

    const body = {
      channelId: null,
      activityId: targetConfig.activityId,
      productId: targetConfig.productId,
      productCode: targetConfig.productCode,
      currentTime: dateStr,
      accountType: targetConfig.accountType || "4",
      account: FIXED_CONFIG.account, 
      ...(encryptedTarget ? { targetAccount: encryptedTarget } : {})
    };

    // 发起兑换请求，重试2次
    for (let i = 0; i <= 2; i++) {
      if (i > 0) await sleep(500);
      const { result } = await this.request({
        method: "post",
        url: `https://backward.bol.wo.cn/prod-api/promotion/activity/roll/receiveRights?yGdtco4r=${this.market_task_yGdtco4r}`,
        headers: this.getMarketHeaders(),
        body: JSON.stringify(body)
      });

      if (result?.code == 200) {
        this.log(`🎉 抢购成功！获得: 【${productName}】`);
        return true;
      } else {
        this.log(`抢购请求${i+1}失败[${result?.code}]: ${result?.msg || ""}`);
        if (this.hasStopKeyword(result?.msg)) return true; // 遇到上限等关键字停止重试
      }
    }
    return false;
  }

  // ==================== 【超市权益日常任务/抽奖】 ====================
  async getTasks() {
    const { result } = await this.request({
      method: "get",
      url: `https://backward.bol.wo.cn/prod-api/promotion/activityTask/getAllActivityTasks?activityId=${FIXED_CONFIG.daily_config.activityId}`,
      headers: this.getMarketHeaders()
    });
    return result?.data?.activityTaskUserDetailVOList || [];
  }

  async runTask(task) {
    const { name, param1: param, triggerTime, triggeredTime } = task;
    if (triggeredTime >= triggerTime || name.includes("购买")) return;
    let api = name.includes("分享") ? "checkShare" : "checkView";
    await sleep(1500);
    const { result } = await this.request({
      method: "post",
      url: `https://backward.bol.wo.cn/prod-api/promotion/activityTaskShare/${api}?checkKey=${param}`,
      headers: this.getMarketHeaders(),
      body: "{}"
    });
    if (result?.code == 200) this.log(`✅ 任务完成: ${name}`);
  }

  async checkRafflePool() {
    if (globalMarketPoolChecked && !globalMarketHasPrizes) return;
    this.log("权益超市: 正在查询奖品池...");
    const { result } = await this.request({
      method: "post",
      url: `https://backward.bol.wo.cn/prod-api/promotion/home/raffleActivity/prizeList?id=${FIXED_CONFIG.daily_config.activityId}&timeVerRan=${Date.now()}`,
      headers: this.getMarketHeaders(),
      body: "{}"
    });
    if (result?.code == 200 && Array.isArray(result.data)) {
      const keywords = ['月卡', 'VIP', '周卡', '绿钻'];
      globalMarketHasPrizes = result.data.some(p => keywords.some(k => p.name.includes(k)) && parseInt(p.dailyPrizeLimit) > 0);
      if (globalMarketHasPrizes) this.log("🌊 监测到奖池包含大奖！");
    }
    globalMarketPoolChecked = true;
  }

  async runRaffleLogic() {
    this.log("权益超市: 正在查询抽奖次数...");
    const { result } = await this.request({
      method: "post",
      url: `https://backward.bol.wo.cn/prod-api/promotion/home/raffleActivity/getUserRaffleCountExt?id=${FIXED_CONFIG.daily_config.activityId}&timeVerRan=${Date.now()}`,
      headers: this.getMarketHeaders(),
      body: "{}"
    });

    let count = 0;
    if (result?.code == 200) {
      if (typeof result.data === 'object' && result.data !== null) {
        count = parseInt(result.data.raffleCount) || 0;
      } else {
        count = parseInt(result.data) || 0;
      }
    }

    this.log(`🎫 剩余抽奖次数: ${count}`);
    for (let i = 0; i < count; i++) {
      await sleep(3000);
      const success = await this.doDraw();
      if (!success) break;
    }
  }

  async doDraw() {
    const { result } = await this.request({
      method: "post",
      url: `https://backward.bol.wo.cn/prod-api/promotion/home/raffleActivity/userRaffle?id=${FIXED_CONFIG.daily_config.activityId}&channel=unicomTab&timeVerRan=${Date.now()}`,
      headers: this.getMarketHeaders(),
      body: "{}"
    });

    if (result?.code == 200) {
      const prize = result.data?.prizesName || "谢谢参与";
      this.log(`🎁 抽奖结果: ${prize}`);
      return true;
    } else if (result?.code == 500 && result?.msg?.includes("验证")) {
      this.log("权益超市: 触发验证，尝试处理...");
      const verify = await this.request({
        method: "post",
        url: `https://backward.bol.wo.cn/prod-api/promotion/home/raffleActivity/validateCaptcha?id=${FIXED_CONFIG.daily_config.activityId}`,
        headers: this.getMarketHeaders(),
        body: "{}"
      });
      if (verify.result?.code == 200) return await this.doDraw();
    }
    this.log(`❌ 抽奖失败: ${result?.msg}`);
    return false;
  }

  async start() {
    if (!this.market_token) return;

    if (ENABLE_PANIC_BUY) {
      this.log("🚀 进入【抢购兑换模式】...");
      if (!IS_TEST) {
        const startTime = new Date(new Date().setHours(9, 59, 59, 0));
        while (new Date() < startTime) await sleep(500);
      }
      await this.receiveSurpriseRights();
    }

    if (ENABLE_DAILY_TASK) {
      this.log("🍵 进入【日常任务/抽奖模式】...");
      try {
        const tasks = await this.getTasks();
        for (const t of tasks) await this.runTask(t);
        await this.checkRafflePool();
        await this.runRaffleLogic();
      } catch (e) { this.log(`日常出错: ${e.message}`); }
    }
  }
}

// ===================== 主流程 =====================
async function main() {
  console.log(`=============== 启动 ===============`);
  const tokens = getAccounts("chinaUnicomCookie");
  if (tokens.length === 0) { console.log("❌ 请设置环境变量 chinaUnicomCookie"); return; }
  const validServices = [];
  for (let i = 0; i < tokens.length; i++) {
    const auth = new UnicomAuthService(tokens[i], i);
    if (await auth.onLine()) {
      await sleep(1000);
      if (await auth.marketUnicomLogin()) validServices.push(auth);
    }
    await sleep(2000);
  }
  if (validServices.length > 0) {
    console.log(`\n✅ ${validServices.length} 个账号就绪\n`);
    await Promise.all(validServices.map(a => a.start()));
  }
  console.log("\n=============== 结束 ===============");
}

function getAccounts(name) {
  const val = process.env[name] || "";
  if (!val) return [];
  for (const d of ["\n", "&", "@"]) if (val.includes(d)) return val.split(d).map(s => s.trim()).filter(Boolean);
  return [val.trim()];
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function Env(n) { return { name: n, log: console.log }; }
if (require.main === module) main().catch(console.error);
