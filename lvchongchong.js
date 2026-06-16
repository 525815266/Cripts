
/**
 * 驴充充自动任务脚本
 * 功能 自动签到 + 看视频赚积分
 * 
 * 环境变量配置：
 * LCC_ACCOUNTS - 账号信息，格式 手机号#用户ID#备注名
 * 多个账号用换行分隔，例如 
 * <PHONE>#123456#账号1
 * <PHONE>#789012#账号2
 * 
 * 使用方法：
 * 1. 设置环境变量 LCC_ACCOUNTS
 * 2. 运行脚本 node 驴充充.js
 * 3. 脚本会自动执行签到和看视频任务
 * 4. 执行完成后发送通知汇总
 */

const request = require("request");
const crypto = require("crypto");
const { log } = console;
const { sendNotify } = require('./sendNotify');

// 环境变量与配置
const ACCOUNTS_ENV = process.env.LCC_ACCOUNTS || "<SENSITIVE>";
let accounts = [];

// 全局状态
let userToken = "", currentPhone = "", currentUserId = "";
let userScore = 0, isSigned = false;
let tokenFailAccounts = [], allAccountSummary = [];

// RSA公钥 (Base64编码)
const RSA_PUBLIC_KEY_B64 = 'QkFRQURJUVhLVHhVMGFyV0U5eTRZTkRxQkhPRWdaMnptY1JqUjNTUW1mSE5OWWdkQ3hLZzNpZGNxakJkUXdOZUtPb1Fsam5BREk1VHRFdFpkTTlSYlZ6cnlLTDNqNld1OEZreDEyYmlDKyt5emtrL2R6TTd3QzJvQzdFOERzenJ1cDM5VFFlZjEyaDhpZmVDcVYvMlZhMTArQUhFcFJiK25VeVd4TzNiTU5uY0dVdjJTQ1FnQktRaUJDREFORzRBQVVRQUJFUUQzYklTR3FTQ0cwQU1mR0lN';

// 生成nonce
function generateNonce(timestamp) {
    try {
        // 1. Base64解码公钥
        const decodedKey = Buffer.from(RSA_PUBLIC_KEY_B64, 'base64').toString();
        
        // 2. 字符串反转
        const reversedKey = decodedKey.split('').reverse().join('');
        
        // 3. 尝试不同的PEM格式
        const formats = [
            `-----BEGIN PUBLIC KEY-----\n${reversedKey}\n-----END PUBLIC KEY-----`,
            reversedKey, // 直接使用反转后的字符串
            `-----BEGIN RSA PUBLIC KEY-----\n${reversedKey}\n-----END RSA PUBLIC KEY-----`
        ];
        
        for (let i = 0; i < formats.length; i++) {
            try {
                const encrypted = crypto.publicEncrypt({
                    key: formats[i],
                    padding: crypto.constants.RSA_PKCS1_PADDING
                }, Buffer.from(String(timestamp)));
                
                const result = encodeURIComponent(encrypted.toString('base64'));
                return result;
            } catch (formatError) {
                // 静默处理格式错误，继续尝试下一个格式
            }
        }
        
        throw new Error("所有格式都失败了");
    } catch (error) {
        log(`生成nonce失败: ${error.message}`);
        return null;
    }
}

// 刷新Token
async function refreshToken() {
    log("Token过期，正在刷新...");
    try {
        const tokenResult = await getTokenByPhoneAndUserId(currentPhone, currentUserId);
        userToken = tokenResult.userToken;
        log("Token刷新成功");
        return true;
    } catch (error) {
        log(`Token刷新失败: ${error.message}`);
        return false;
    }
}

// 解析账号信息
function parseAccounts() {
    if (!ACCOUNTS_ENV) {
        log("⚠️ 未设置LCC_ACCOUNTS环境变量");
        return [];
    }
    
    return ACCOUNTS_ENV.split('\n')
        .map((accStr, index) => {
            const trimmed = accStr.trim();
            if (!trimmed) return null;
            
            const parts = trimmed.split('#').map(p => p.trim());
            return parts.length >= 2 ? {
                phone: parts[0],
                userId: parts[1],
                mark: parts[2] || `账号${index + 1}`
            } : null;
        })
        .filter(acc => acc !== null);
}

// 主函数
async function main() {
    try {
        accounts = parseAccounts();
        if (accounts.length === 0) {
            log("没有有效的账号信息，脚本退出");
            return;
        }
        
        log(`共找到 ${accounts.length} 个账号\n`);
        
        for (let i = 0; i < accounts.length; i++) {
            if (i > 0) {
                log("休息10s，防止黑IP");
                await wait(10000);
            }
            await processAccount(accounts[i], i + 1);
        }
        
        sendAllAccountsSummary();
    } catch (error) {
        log(`脚本主流程出错: ${error.message}`);
        sendNotify("驴充充脚本执行失败", `错误信息: ${error.message}`);
    }
}

// 处理单个账号
async function processAccount(account, accountNum) {
    let { phone, userId, mark } = account;
    let taskSummary = [];
    let isFirstTaskListCall = true;
    isSigned = false;
    userScore = 0;
    
    try {
        log(`${'='.repeat(50)}`);
        log(`🚀 开始【第 ${accountNum} 个账号：${mark}】`);
        
        if (!phone || !userId) {
            log(`❌ 账号信息不完整，跳过`);
            allAccountSummary.push({ mark, status: "信息不完整", totalScore: 0, earnedScore: 0, tasks: [] });
            return;
        }
        currentPhone = phone;
        currentUserId = userId;
        
        // 获取Token和用户信息
        const tokenResult = await getTokenByPhoneAndUserId(phone, userId);
        userToken = tokenResult.userToken;
        
        if (!await getUserInfoAndSignStatus()) {
            tokenFailAccounts.push(mark);
            log(`❌ 获取用户信息失败`);
            allAccountSummary.push({ mark, status: "获取用户信息失败", totalScore: 0, earnedScore: 0, tasks: [] });
            return;
        }
        log(`💰 当前积分: ${userScore}`);
        const accountStartScore = userScore; // 记录账号开始时的积分
        
        // 处理签到
        if (!isSigned) {
            await handleSignIn(taskSummary);
            await wait(2000);
        } else {
            log("✅ 今日已签到");
        }
        
        // 获取任务列表
        const allTasks = await getCompleteTaskList(isFirstTaskListCall);
        if (!allTasks?.length) {
            log("❌ 获取任务列表失败");
            allAccountSummary.push({ mark, status: "获取任务列表失败", totalScore: 0, earnedScore: 0, tasks: [] });
            return;
        }
        isFirstTaskListCall = false;
        
        // 检查并执行看视频任务
        const videoTask = allTasks.find(task => task.type === 7); // 看视频赚积分
        if (videoTask && videoTask.finishTimes < videoTask.times) {
            const needExecute = videoTask.times - videoTask.finishTimes;
            log(`\n📺 开始执行看视频任务 (${videoTask.finishTimes}/${videoTask.times})`);
            await executeVideoTask(needExecute);
        } 
        
        // 脚本功能已完成：签到 + 看视频
        
        // 获取最终积分
        await getUserInfoAndSignStatus(); // 刷新最新积分
        const earnedScore = Math.max(0, userScore - accountStartScore);
        log(`✨ 本次获得积分: ${earnedScore}，总积分: ${userScore}`);
        log(`${'='.repeat(50)}`);
        
        allAccountSummary.push({
            mark, status: "完成", totalScore: userScore, earnedScore,
            tasks: [...taskSummary]
        });
    } catch (error) {
        log(`账号处理出错: ${error.message}`);
        allAccountSummary.push({
            mark, status: "处理出错", totalScore: userScore, earnedScore: 0,
            tasks: [...taskSummary]
        });
    }
}

// 执行看视频任务
async function executeVideoTask(times) {
    for (let i = 0; i < times; i++) {
        log(`📺 看视频 ${i+1}/${times}`);
        await executeVideoOnce();
        
        // 除了最后一次，每次看完视频后随机等待25-30秒
        if (i < times - 1) {
            const randomDelay = Math.floor(Math.random() * 6) + 25; // 25-30秒
            log(`   休息${randomDelay}秒后观看下一个视频...`);
            await wait(randomDelay * 1000);
        }
    }
    log(`📺 看视频任务完成 ✅`);
}

// 执行一次看视频操作
async function executeVideoOnce() {
    return new Promise(async (resolve) => {
        try {
            // 发送看视频请求
            const result = await sendVideoRequest();
            
            if (result && result.code === 402) {
                log("🔄 刷新Token...");
                if (!await refreshToken()) {
                    return resolve();
                }
                // Token刷新后重新请求
                const retryResult = await sendVideoRequest();
                if (retryResult && retryResult.code === 200) {
                    if (retryResult.data && retryResult.data.userScore) {
                        const prevScore = userScore;
                        userScore = retryResult.data.userScore;
                        const earned = userScore - prevScore;
                        log(`   +${earned}积分 (总计: ${userScore})`);
                    }
                } else {
                    const errorMsg = retryResult?.message || retryResult?.msg || `错误码: ${retryResult?.code}`;
                    log(`   ❌ ${errorMsg}`);
                }
            } else if (result && result.code === 200) {
                if (result.data && result.data.userScore) {
                    const prevScore = userScore;
                    userScore = result.data.userScore;
                    const earned = userScore - prevScore;
                    log(`   +${earned}积分 (总计: ${userScore})`);
                }
            } else {
                const errorMsg = result?.message || result?.msg || `错误码: ${result?.code}`;
                log(`   ❌ ${errorMsg}`);
            }
            
        } catch (error) {
            log(`看视频异常: ${error.message}`);
        }
        resolve();
    });
}

// 发送看视频请求
async function sendVideoRequest() {
    return new Promise((resolve) => {
        try {
            const timestamp = Date.now();
            const nonce = generateNonce(timestamp);
            
            // 构建URL
            let url = `https://appapi.lvcchong.com/appBaseApi/scoreUser/task/receiveTaskScore?timestamp=${timestamp}`;
            if (nonce) {
                url += `&nonce=${nonce}`;
            }
            
            const options = {
                method: "POST",
                url: url,
                headers: { 
                    "token": userToken, 
                    "content-type": "application/x-www-form-urlencoded",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x6309080f)XWEB/14185",
                    "Origin": "https://h5.lvcchong.com",
                    "Referer": "https://h5.lvcchong.com/"
                },
                form: { 
                    content: "HZC7B9RVy5411UnJohSPT%2F%2BNueFczy1TKuL9hPFjpu1DF9ArV3oIK%2FLaDdi2eMB17wyo8jYMvGfindyVjSXUBBKtcVo7t1Q9%2FFi1CLRSgPnQ3ryc1rvWiSPuDvef01MsNyRYGPPpSP5FPDQczW0m3sFhEWWotJyuc85QryjO6cU%3D"
                }
            };
            
            request(options, (error, response, body) => {
                try {
                    if (error || !body) {
                        resolve(null);
                        return;
                    }
                    
                    const result = JSON.parse(body);
                    resolve(result);
                } catch (e) {
                    resolve(null);
                }
            });
        } catch (error) {
            resolve(null);
        }
    });
}



// 获取Token
async function getTokenByPhoneAndUserId(phone, userId) {
    return new Promise((resolve, reject) => {
        const options = {
            method: "POST",
            url: "https://appapi.lvcchong.com/appBaseApi/h5/accessEntrance",
            headers: {
                "User-Agent": "Mozilla/5.0 (Linux; Android 15; 22061218C Build/AQ3A.241006.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 XWEB/1160117 MMWEBSDK/20250503 MMWEBID/6435 MicroMessenger/8.0.61.2861(0x28003D41) WeChat/arm64 Weixin GPVersion/1 NetType/WIFI Language/zh_CN ABI/arm64 miniProgram/wx0132aa93a8b214ae",
                "Origin": "https://h5.lvcchong.com",
                "Referer": "https://h5.lvcchong.com/",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            form: { phone, userId, time: Date.now(), ownerId: "0" }
        };

        request(options, (error, response, body) => {
            if (error) return reject(`获取Token失败: ${error.message}`);
            
            try {
                const result = JSON.parse(body);
                if (result.code === 200 && result.success && result.data?.userToken) {
                    resolve({ userToken: result.data.userToken, refreshToken: result.data.refreshToken });
                } else {
                    reject(`获取Token失败: ${result.message || "未知错误"}，错误码: ${result.code}`);
                }
            } catch (parseError) {
                reject(`解析Token响应失败: ${parseError.message}`);
            }
        });
    });
}

// 获取用户信息和签到状态
async function getUserInfoAndSignStatus() {
    return new Promise(resolve => {
        const options = {
            method: "POST",
            url: "https://appapi.lvcchong.com/appBaseApi/scoreUser/score/getMyScorePageInfo",
            headers: { "token": userToken, "Content-Type": "application/x-www-form-urlencoded" },
            form: { "page": 1, "limit": 10, "sourceType": 3 }
        };
        
        request(options, (error, response, body) => {
            try {
                if (error || !body) return resolve(false);
                
                const result = JSON.parse(body);
                if (result.code === 200 && result.data) {
                    userScore = result.data.userScore || 0;
                    
                    const signConfig = result.data.signConfigList || [];
                    const todaySign = signConfig.find(item => item.isToday === 1);
                    isSigned = todaySign ? todaySign.isSigned === 1 : result.data.signFlag === 1;
                    
                    return resolve(true);
                }
            } catch (e) {}
            resolve(false);
        });
    });
}

// 获取任务列表
async function getCompleteTaskList(isFirstCall = false) {
    return new Promise(resolve => {
        const options = {
            method: "POST",
            url: "https://appapi.lvcchong.com/appBaseApi/scoreUser/task/getTaskList",
            headers: { 
                "token": userToken, 
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0 (Linux; Android 15; 22061218C Build/AQ3A.241006.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 XWEB/1160117 MMWEBSDK/20250503 MMWEBID/6435 MicroMessenger/8.0.61.2861(0x28003D41) WeChat/arm64 Weixin GPVersion/1 NetType/WIFI Language/zh_CN ABI/arm64 miniProgram/wx0132aa93a8b214ae"
            },
            form: { "sourceType": 3, "version": 1 }
        };
        
        request(options, (error, response, body) => {
            try {
                if (error || !body) return resolve(null);
                
                const result = JSON.parse(body);
                if (result.code === 200 && result.success && Array.isArray(result.data)) {
                    // 只在第一次获取任务列表时显示看视频状态
                    if (isFirstCall) {
                        const videoTask = result.data.find(task => task.type === 7);
                        if (videoTask) {
                            const status = videoTask.status === 2 ? "✅" : (videoTask.finishTimes >= videoTask.times ? "🎁" : "⏳");
                            log(`📺 看视频: ${videoTask.finishTimes}/${videoTask.times} ${status}`);
                        }
                    }
                    
                    return resolve(result.data);
                }
            } catch (e) {}
            resolve(null);
        });
    });
}

// 处理签到
async function handleSignIn(taskSummary) {
    log("执行签到...");
    return new Promise(resolve => {
        const options = {
            method: "POST",
            url: "https://appapi.lvcchong.com/appBaseApi/scoreUser/sign/userSign",
            headers: { 
                "token": userToken, 
                "content-type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x6309080f)XWEB/14185",
                "Origin": "https://h5.lvcchong.com",
                "Referer": "https://h5.lvcchong.com/"
            },
            form: { sourceType: "3" }
        };
        
        request(options, (error, response, body) => {
            try {
                if (error || !body) {
                    log("签到失败: 网络错误");
                    taskSummary.push({ name: "签到", status: "失败", score: 0 });
                    return resolve();
                }
                
                const result = JSON.parse(body);
                if (result.code == 200 && result.success) {
                    isSigned = true;
                    
                    // 从signConfigList中找到今天的签到配置获取积分
                    let todayScore = 0;
                    if (result.data?.signConfigList) {
                        const todayConfig = result.data.signConfigList.find(item => item.isToday === 1);
                        todayScore = todayConfig ? todayConfig.score : result.data?.score || 0;
                    } else {
                        todayScore = result.data?.score || 0;
                    }
                    
                    // 更新总积分
                    if (result.data?.totalScore) {
                        userScore = result.data.totalScore;
                    }
                    
                    log(`签到成功，获得 ${todayScore} 积分`);
                    taskSummary.push({ name: "签到", status: "成功", score: todayScore });
                } else {
                    const reason = result.message || result.msg || `错误码: ${result.code}`;
                    log(`签到失败: ${reason}`);
                    taskSummary.push({ name: "签到", status: "失败", score: 0, reason });
                }
            } catch (e) {
                log(`签到处理出错: ${e.message}`);
                taskSummary.push({ name: "签到", status: "错误", score: 0 });
            }
            resolve();
        });
    });
}

// 接收任务积分函数已移除
// 根据抓包分析，该函数需要复杂的content加密参数，已被移除

// 发送汇总通知
function sendAllAccountsSummary() {
    const totalAccounts = accounts.length;
    const successAccounts = allAccountSummary.filter(item => item.status === "完成").length;
    const totalEarned = allAccountSummary.reduce((sum, item) => sum + item.earnedScore, 0);
    
    // 获取当前时间（北京时间）
    const now = new Date();
    const beijingTime = new Date(now.getTime() + 8 * 3600 * 1000);
    const timeStr = beijingTime.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
    
    // 统计各种状态的账号数量
    const failedAccounts = allAccountSummary.filter(item => item.status !== "完成").length;
    
    // 简洁的推送内容
    let content = `⚡ **驴充充任务概览**\n`;
    content += `总计: ${totalAccounts} | 成功: ${successAccounts} | 失败: ${failedAccounts}\n`;
    content += `💰 获得积分: ${totalEarned}\n`;
    content += `--------------------------------\n`;
    
    // 只显示主要账号信息
    allAccountSummary.forEach(item => {
        if (item.status === "完成") {
            content += `✅ ${item.mark}: +${item.earnedScore} (总${item.totalScore})\n`;
        } else {
            content += `❌ ${item.mark}: ${item.status}\n`;
        }
    });
    
    sendNotify("驴充充", content.trim());
}

// 等待函数
function wait(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// 启动脚本
main();
