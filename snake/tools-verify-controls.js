/**
 * 暂停 / 结束本局 行为验证（本地验证用，不参与提交）
 *
 * 用法： node tools-verify-controls.js
 *
 * 验证点：
 *   1) 暂停后 moveSnake 不再推进（蛇长/得分/食物计数都不变）
 *   2) 恢复时先走 3 秒倒计时：倒计时期间 paused 仍为 true、暂停键与转向都不响应，
 *      倒计时走完才真正恢复推进
 *   3) 暂停可以反复切换，且不影响状态
 *   4) 结束本局等价于蛇死亡：走 endGame('fail')，记战绩、结算最高分、
 *      并清除暂停状态，之后还能再开新局
 *   5) 工具栏按钮的显隐按状态分（不是一套规则）：
 *        开局提示 -> 只给「AI自动玩」；手动/AI 游玩中 -> 给暂停与「结束本局」；
 *        本局结束 -> 给「AI自动玩」与「重新开始」；
 *        胜利界面 -> 工具栏只留「重新开始」（横幅里是「继续玩 / 返回」）
 *        （「AI自动玩」在手动游玩、AI 游玩、胜利界面三种情况下都要收起）
 *   8) 空格键按状态分四种含义：开局提示=开始、游玩中=暂停/继续、
 *      本局结束=重新开始、胜利界面=继续玩
 *   6) 玩到一半点「重新开始」会把这一局记进战绩（分数与局数都算），
 *      而停在开局提示上点它什么都不记
 *   7) 手动结束 / 玩到一半重开在战绩里标为"玩家叫停"（图标 🔄 而非撞死的 💀）
 */
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const code = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1])[0];

const exportCode = `
globalThis.__g = {
    startAI: () => startAI(),
    moveSnake: () => moveSnake(),
    togglePause: () => togglePause(),
    finishRound: () => finishRound(),
    resetGame: () => resetGame(),
    showRoundPrompt: () => showRoundPrompt(),
    startNewRoundWithPrompt: () => startNewRoundWithPrompt(),
    beginRound: () => beginRound(),
    clickRestartBtn: () => restartBtn.click(),
    // 按钮**点击**本身也要测：历史上有过"监听器指向已删元素、bootstrap 被打断"
    // 的问题，而以前只测了按钮调用的函数（finishRound / togglePause / startAI）。
    clickEndBtn: () => endBtn.click(),
    clickPauseBtn: () => pauseBtn.click(),
    clickAiBtn: () => aiBtn.click(),
    // 模拟按空格：派发真实键盘事件，走页面上的 document 监听器
    pressSpace: () => document.dispatchEvent(
        new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true })),
    // 等价于 checkWinScore() 命中 15 分那条分支：直接亮出胜利界面
    forceWinBanner: () => { winShown = true; showWinBanner(); },
    // 清空战绩，便于逐局构造
    clearHistory: () => { roundHistory = []; roundCount = 0; renderHistory(); },
    // 直接记一局（绕开游戏流程，让断言可确定地核对某一种组合）
    recordRound: (scoreVal, outcome, wasAI, userEnded) => {
        score = scoreVal;
        recordRound(outcome, '测试', wasAI, userEnded);
    },
    // 读取战绩列表里每一行渲染出来的文字（DOM 桩会把它拼在 textContent 上）
    historyTexts: () => {
        const out = [];
        for (const li of historyList.children) {
            const parts = [];
            for (const sp of li.children) parts.push(sp.textContent);
            out.push(parts.join(' '));
        }
        return out;
    },
    setScore: (n) => { score = n; updateScoreDisplay(); },
    // 倒计时：观测是否激活、剩余多少 ms，以及把时间"快进"到结束（便于无头测试）
    countdown: () => ({ active: countdownActive(), endsAt: countdownEndsAt,
                        ms: countdownEndsAt ? (countdownEndsAt - Date.now()) : 0 }),
    fastForwardCountdown: () => {
        if (countdownEndsAt) countdownEndsAt = Date.now() - 1;   // 让它立即到点
        updateCountdown();                                       // 动画循环每帧会调它
    },
    state: () => ({
        gameOver, winFlag, paused, score, aiMode, aiResult, endReason, winScreenVisible,
        snakeLen: snake.length, foodEatenCount,
        countdownActive: countdownActive(),
        status: statusTip.innerText,
        pauseLabel: pauseBtn.innerText,
        pauseHighlighted: pauseBtn.classList.contains('is-paused'),
        // 暂停键是否隐藏：刚点进来（开局提示）与结束后都应为 true
        pauseHidden: pauseBtn.classList.contains('is-hidden'),
        // 「重新开始」「结束本局」与暂停键同一套显隐规则
        restartHidden: restartBtn.classList.contains('is-hidden'),
        endHidden: endBtn.classList.contains('is-hidden'),
        aiHidden: aiBtn.classList.contains('is-hidden'),
        // 战绩里的最后一条：供"记录分数 / 玩家叫停"这类断言用
        lastResult: roundHistory.length ? roundHistory[roundHistory.length - 1] : null,
        roundCount: roundCount,
        roundPending: roundPending,
        roundInProgress: roundInProgress,
        history: roundHistory.map(h => ({ score: h.score, mode: h.mode, result: h.result,
                                          won: h.won, endedByUser: h.endedByUser }))
    })
};
`;

/**
 * 键盘事件桩。vm 沙箱里没有 DOM，而 pressSpace 要派发一个真实的
 * keydown 事件（页面的监听器挂在 document 上），所以这里给个最小实现：
 * 只带处理器会读到的字段，preventDefault 是个空函数。
 */
class KeyboardEventStub {
    constructor(type, init) {
        this.type = type;
        this.key = (init && init.key) || '';
        this.code = (init && init.code) || '';
        this.repeat = !!(init && init.repeat);
        this.bubbles = !!(init && init.bubbles);
        this.defaultPrevented = false;
    }
    preventDefault() { this.defaultPrevented = true; }
}

function makeElement() {
    const classes = new Set();
    const handlers = {};
    const children = [];
    return {
        innerText: '', textContent: '', className: '', style: {}, children: children,
        // innerHTML 要做成访问器：renderHistory() 每轮开头都会
        // historyList.innerHTML = ''，普通属性不会清掉 children，
        // 历史就会越积越多（实测积到 46 条）。
        get innerHTML() { return ''; },
        set innerHTML(v) { if (v === '') children.length = 0; },
        classList: {
            add(c) { classes.add(c); },
            remove(c) { classes.delete(c); },
            contains(c) { return classes.has(c); },
            // toggle 是真实 DOM 的 API：暂停键的显隐用了
            // classList.toggle('is-hidden', !show)，这个桩是白名单式的，
            // 少了它会抛 "pauseBtn.classList.toggle is not a function"。
            toggle(c, force) {
                const on = (force === undefined) ? !classes.has(c) : !!force;
                if (on) classes.add(c); else classes.delete(c);
                return on;
            }
        },
        appendChild(c) { this.children.push(c); return c; },
        removeChild() {}, setAttribute() {}, removeAttribute() {},
        getAttribute() { return null; },
        // 记下注册的事件处理函数，click() 时按顺序调用。
        // 真实 DOM 的按钮点击就是这样触发监听器的；没有它就没法在无头环境里
        // 验证"点「重新开始」会把这一局记进战绩"。
        addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
        click() { (handlers.click || []).forEach(fn => fn({ preventDefault() {} })); }
    };
}

const els = new Map();
const documentStub = {
    documentElement: makeElement(),
    getElementById(id) { if (!els.has(id)) els.set(id, makeElement()); return els.get(id); },
    createElement() { return makeElement(); },
    querySelector() { return makeElement(); },
    // 页面把 keydown 监听器挂在 document 上，pressSpace 要能派发过去。
    // 和 makeElement 里的做法一样：注册时存起来，dispatchEvent 时按类型调用。
    addEventListener(type, fn) { (docHandlers[type] = docHandlers[type] || []).push(fn); },
    dispatchEvent(e) {
        (docHandlers[e.type] || []).forEach(fn => fn(e));
        return true;
    }
};
const docHandlers = {};

const noop = () => {};
const ctxStub = {
    save: noop, restore: noop, beginPath: noop, closePath: noop, moveTo: noop, lineTo: noop,
    arc: noop, fill: noop, stroke: noop, fillRect: noop, strokeRect: noop, clearRect: noop,
    quadraticCurveTo: noop, fillText: noop, measureText: () => ({ width: 0 }),
    // 2D 变换：倒计时的数字会做一次轻微缩放，用到 translate / scale / save / restore。
    // 这个桩是白名单式的（只列了用到的 API），少了它们整段绘制会抛
    // "ctx.translate is not a function" 把脚本打断。
    translate: noop, scale: noop, rotate: noop, setTransform: noop, transform: noop,
    fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '', textBaseline: '',
    shadowColor: '', shadowBlur: 0, globalAlpha: 1
};
const cv = makeElement();
cv.width = 400; cv.height = 400; cv.getContext = () => ctxStub;
els.set('gameCanvas', cv);

function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
        a = (a + 0x6D2B79F5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

const storage = new Map();
const sandbox = {};
sandbox.globalThis = sandbox;
sandbox.window = sandbox;
sandbox.document = documentStub;
sandbox.localStorage = {
    getItem: k => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
};
sandbox.KeyboardEvent = KeyboardEventStub;   // pressSpace 要派发 keydown
sandbox.CanvasRenderingContext2D = function () {};
sandbox.Date = Date;
sandbox.console = console;
sandbox.Math = Object.create(Math);
sandbox.Math.random = mulberry32(1);
sandbox.setTimeout = () => 0;
sandbox.setInterval = () => 0;
sandbox.clearInterval = () => {};
sandbox.clearTimeout = () => {};
sandbox.requestAnimationFrame = () => 0;

vm.createContext(sandbox);
vm.runInContext(code + exportCode, sandbox, { filename: 'snake-page.js' });
const g = sandbox.__g;

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ✓ ' + label + (detail ? '  —— ' + detail : '')); }
    else { fail++; console.log('  ✗ ' + label + (detail ? '  —— ' + detail : '')); }
}

/**
 * 从 index.html 源码里解析胜利横幅内按钮的 id（按出现顺序）。
 *
 * 用"容器配对"的方式定位横幅范围：从 id="winBanner" 那行开始，数 <div 与
 * </div> 直到配平。早先按行扫到第一个 </div></div> 就停，结果把后面的工具栏
 * 按钮也吃了进来（横幅现在就嵌在工具栏里面），断言假失败。
 */
function bannerButtonIds() {
    const lines = html.split('\n');
    const start = lines.findIndex(l => l.includes('id="winBanner"'));
    if (start < 0) return [];
    const ids = [];
    let depth = 0;
    for (let i = start; i < lines.length; i++) {
        const opens = (lines[i].match(/<div/g) || []).length;
        const closes = (lines[i].match(/<\/div>/g) || []).length;
        depth += opens - closes;
        const m = lines[i].match(/<button[^>]*id="([^"]+)"/);
        if (m) ids.push(m[1]);
        if (i > start && depth <= 0) break;
    }
    return ids;
}

console.log('=== 0. 暂停键的显示时机 ===');
// resetGame() 只重置不启动循环；showRoundPrompt() 会停在开局提示上（roundPending=true）。
// 这个状态下没有"可暂停的一局"，暂停键应当隐藏。
g.resetGame();
g.showRoundPrompt();
check('开局提示期间暂停键隐藏', g.state().pauseHidden === true,
    'pauseHidden=' + g.state().pauseHidden);

console.log('=== 1. 暂停后不再推进 ===');
sandbox.Math.random = mulberry32(20260917);
g.startAI();
for (let i = 0; i < 200; i++) g.moveSnake();
const before = g.state();
check('AI 已开始推进', before.snakeLen > 3, '蛇长 ' + before.snakeLen + '，吃到 ' + before.foodEatenCount);
check('开局后暂停键显示', before.pauseHidden === false, 'pauseHidden=' + before.pauseHidden);

g.togglePause();
const pausedState = g.state();
check('paused 变为 true', pausedState.paused === true);
check('按钮文案变为「继续」', pausedState.pauseLabel.indexOf('继续') >= 0, pausedState.pauseLabel);
check('按钮进入高亮态', pausedState.pauseHighlighted === true);
check('状态栏提示已暂停', pausedState.status.indexOf('暂停') >= 0, pausedState.status);

// 暂停期间调用 moveSnake 应当完全不动
for (let i = 0; i < 500; i++) g.moveSnake();
const during = g.state();
check('暂停期间 500 次 moveSnake 无任何推进',
    during.snakeLen === pausedState.snakeLen &&
    during.score === pausedState.score &&
    during.foodEatenCount === pausedState.foodEatenCount,
    '蛇长 ' + pausedState.snakeLen + ' → ' + during.snakeLen +
    '，得分 ' + pausedState.score + ' → ' + during.score);

console.log('\n=== 2. 恢复时先走 3 秒倒计时，走完才继续推进 ===');
g.togglePause();                       // 从暂停点"继续"
const cd = g.state();
check('进入倒计时', cd.countdownActive === true);
check('倒计时期间 paused 仍为 true', cd.paused === true);
check('倒计时期间按钮仍是「继续」', cd.pauseLabel.indexOf('继续') >= 0, cd.pauseLabel);
const cdInfo = g.countdown();
check('倒计时时长约 3 秒', cdInfo.ms > 2500 && cdInfo.ms <= 3000, cdInfo.ms + ' ms');

// 倒计时期间：暂停键不响应（不能把它取消掉）
g.togglePause();
const cdAfterSpace = g.state();
check('倒计时期间按暂停键无反应',
    cdAfterSpace.countdownActive === true && cdAfterSpace.paused === true);

// 倒计时期间：moveSnake 不应推进（paused 仍是 true，双保险）
const cdBefore = g.state().foodEatenCount;
for (let i = 0; i < 300; i++) g.moveSnake();
check('倒计时期间 300 次 moveSnake 无推进', g.state().foodEatenCount === cdBefore,
    '食物计数 ' + cdBefore + ' → ' + g.state().foodEatenCount);

// 快进到倒计时结束
g.fastForwardCountdown();
const resumed = g.state();
check('倒计时结束后 countdownActive 为 false', resumed.countdownActive === false);
check('倒计时结束后 paused 变为 false', resumed.paused === false);
check('倒计时结束后按钮文案变回「暂停」', resumed.pauseLabel.indexOf('暂停') >= 0, resumed.pauseLabel);
check('倒计时结束后按钮取消高亮', resumed.pauseHighlighted === false);

const beforeResume = g.state().foodEatenCount;
for (let i = 0; i < 2000; i++) g.moveSnake();
const afterResume = g.state();
check('倒计时结束后能继续吃到食物', afterResume.foodEatenCount > beforeResume,
    beforeResume + ' → ' + afterResume.foodEatenCount);

console.log('\n=== 3. 反复切换暂停不影响状态 ===');
const beforeToggle = g.state();
for (let i = 0; i < 20; i++) {
    g.togglePause();          // 暂停
    g.moveSnake();            // 应无效
    g.togglePause();          // 恢复 -> 进入倒计时
    g.fastForwardCountdown(); // 让倒计时走完，才是真正恢复
    g.moveSnake();            // 应有效
}
const afterToggle = g.state();
check('切换 20 轮后 paused 为 false', afterToggle.paused === false);
check('切换过程中游戏未结束', afterToggle.gameOver === false);
check('切换过程中游戏有推进', afterToggle.foodEatenCount >= beforeToggle.foodEatenCount);

console.log('\n=== 4. 结束本局等价于蛇死亡 ===');
const beforeEnd = g.state();
const historyBefore = beforeEnd.history.length;
g.togglePause();             // 先暂停，验证结束时能清除暂停
check('结束前处于暂停', g.state().paused === true);

g.finishRound();
const ended = g.state();
check('gameOver 为 true', ended.gameOver === true);
check('winFlag 为 false（死亡，不是填满）', ended.winFlag === false);
check('aiResult 为 fail', ended.aiResult === 'fail');
check('暂停状态被清除', ended.paused === false);
check('结束后暂停键隐藏', ended.pauseHidden === true,
    '（那一局已经结束，按「继续」也没有可继续的东西）');
check('按钮已复位为「暂停」', ended.pauseLabel.indexOf('暂停') >= 0);
check('记录了结束原因', !!ended.endReason, ended.endReason);
check('状态栏显示死亡', ended.status.indexOf('💀') >= 0, ended.status);
check('战绩新增一条', ended.history.length === historyBefore + 1,
    historyBefore + ' → ' + ended.history.length);
const last = ended.history[ended.history.length - 1];
check('战绩标注为 AI / fail', last.mode === 'AI' && last.result === 'fail' && last.won === false,
    JSON.stringify(last));

console.log('\n=== 5. 结束后可再开新局 ===');
g.resetGame();
const fresh = g.state();
check('gameOver 复位', fresh.gameOver === false);
check('得分归零', fresh.score === 0);
check('蛇长回到 3', fresh.snakeLen === 3);
check('最高分为上一局得分', fresh.score === 0 && Number(els.get('highScoreDisplay').innerText) === last.score,
    '最高分 ' + els.get('highScoreDisplay').innerText + '，上局得分 ' + last.score);
check('战绩仍保留', fresh.history.length === ended.history.length);

console.log('\n=== 6. 重新开始 / 结束本局 的显隐与记录 ===');
// 停在开局提示上：三个按钮都该隐藏，点重开也不该记录
g.startNewRoundWithPrompt();
const atPrompt = g.state();
check('开局提示期间「重新开始」隐藏', atPrompt.restartHidden === true);
check('开局提示期间「结束本局」隐藏', atPrompt.endHidden === true);
const roundsAtPrompt = atPrompt.roundCount;
const historyAtPrompt = atPrompt.history.length;
g.clickRestartBtn();                       // 提示期间按钮藏着，点它不应产生记录
const afterPromptClick = g.state();
check('提示期间点重开不记录战绩', afterPromptClick.history.length === historyAtPrompt,
    historyAtPrompt + ' → ' + afterPromptClick.history.length);
check('提示期间点重开不计局数', afterPromptClick.roundCount === roundsAtPrompt,
    roundsAtPrompt + ' → ' + afterPromptClick.roundCount);

// 开局后：三个按钮都该显示
g.beginRound();
const inRound = g.state();
check('游玩中「重新开始」隐藏', inRound.restartHidden === true,
    '（那一局还在跑，不该摆一个重新开始）');
check('游玩中「结束本局」显示', inRound.endHidden === false);
check('游玩中「AI自动玩」隐藏', inRound.aiHidden === true,
    '（手动玩时点它会把当前这局顶掉，属于危险操作）');

// 玩到一半"重开"：应记录这一局（分数 + 局数），并标为玩家叫停。
// 注意：游玩中工具栏的「重新开始」现在是隐藏的，玩家正常操作走的是
// 「结束本局」；这里直接调 clickRestartBtn() 是为了保证那条代码路径
// （哪怕将来按钮又放出来）仍然会正确记录，属于防御性断言。
g.setScore(7);
const roundsBeforeRestart = g.state().roundCount;
g.clickRestartBtn();
const afterRestart = g.state();
check('玩到一半重开计局数', afterRestart.roundCount === roundsBeforeRestart + 1,
    roundsBeforeRestart + ' → ' + afterRestart.roundCount);
check('玩到一半重开记录了分数',
    !!afterRestart.lastResult && afterRestart.lastResult.score === 7,
    JSON.stringify(afterRestart.lastResult));
check('玩到一半重开标为玩家叫停',
    !!afterRestart.lastResult && afterRestart.lastResult.endedByUser === true);
check('重开后回到开局提示', afterRestart.roundPending === true);

// 结束后：三个按钮都该隐藏，且手动结束标为玩家叫停
g.beginRound();
g.setScore(3);
g.finishRound();
const afterEnd = g.state();
check('结束后「重新开始」显示', afterEnd.restartHidden === false,
    '（这时才该出现重新开始）');
check('结束后「结束本局」隐藏', afterEnd.endHidden === true,
    '（已经结束了，没什么可结束的）');
check('结束后「AI自动玩」显示', afterEnd.aiHidden === false);
check('结束后暂停键隐藏', afterEnd.pauseHidden === true,
    '（那一局已经结束，按"继续"也没有可继续的东西）');
// 空格键在结束态的含义是「重新开始」
g.pressSpace();
const afterSpace = g.state();
check('结束后按空格 -> 回到开局提示', afterSpace.roundPending === true,
    'roundPending=' + afterSpace.roundPending);
check('结束后按空格 -> gameOver 复位', afterSpace.gameOver === false);
check('结束后按空格 -> 分数归零', afterSpace.score === 0, 'score=' + afterSpace.score);

check('手动结束标为玩家叫停（图标 🔄）',
    !!afterEnd.lastResult && afterEnd.lastResult.endedByUser === true &&
    afterEnd.lastResult.result === 'fail',
    JSON.stringify(afterEnd.lastResult));

console.log('\n=== 7. 「AI自动玩」的显隐与胜利界面的「返回」 ===');
// AI 游玩中：AI 按钮该隐藏（已经在跑了，它没有任何作用）
g.startNewRoundWithPrompt();
check('开局提示期间「AI自动玩」显示', g.state().aiHidden === false,
    '（这时它是唯一的开局入口）');
g.clickAiBtn();
const aiRunning = g.state();
check('AI 游玩中「AI自动玩」隐藏', aiRunning.aiHidden === true);
check('AI 游玩中暂停键显示', aiRunning.pauseHidden === false);
check('AI 游玩中「结束本局」显示', aiRunning.endHidden === false);

// 结束这一局，准备验证胜利界面
g.finishRound();
g.startNewRoundWithPrompt();
g.beginRound();
g.setScore(15);
g.forceWinBanner();                       // 直接亮出胜利界面（等价于 checkWinScore 命中）
const winState = g.state();
check('胜利界面「AI自动玩」隐藏', winState.aiHidden === true);
check('胜利界面「结束本局」隐藏', winState.endHidden === true);
check('胜利界面「重新开始」显示', winState.restartHidden === false,
    '（工具栏里它是唯一的操作，玩家不必先"返回"再重开）');
check('胜利界面暂停键隐藏', winState.pauseHidden === true,
    '（横幅里已有「继续玩」，功能重复）');
check('胜利界面已亮出', winState.winScreenVisible === true);

// 胜利界面按空格 = 继续玩（进倒计时）
g.pressSpace();
const fromWin = g.state();
check('胜利界面按空格 -> 关闭胜利界面', fromWin.winScreenVisible === false);
check('胜利界面按空格 -> 进入恢复倒计时', fromWin.countdownActive === true);

// 横幅结构：现在是「继续玩 / 返回」两个按钮，重新开始搬到了工具栏。
// 从 index.html 源码里解析横幅那段的按钮顺序 —— 不用 DOM 桩，因为桩的
// querySelectorAll 返回空数组，断言会假失败。
const bannerIds = bannerButtonIds();
check('胜利横幅只剩一个按钮', bannerIds.length === 1, bannerIds.join(' / '));
check('横幅里就是「继续玩」', bannerIds[0] === 'continueBtn', bannerIds[0]);
check('横幅里已无「重新开始」', bannerIds.indexOf('restartFromWinBtn') < 0);
check('横幅里已无「返回」', bannerIds.indexOf('backFromWinBtn') < 0);

console.log('\n=== 8. 战绩里的奖杯（手动 >= 15 分）===');
// 逐局构造，避免"让蛇跑死"那种间接路径导致行号算错
g.clearHistory();
const TROPHY_CASES = [
    // [分数, 结束方式, 是否 AI, 是否玩家叫停, 期望有奖杯]
    [15, 'fail', false, true, true],     // 手动 15 分自己叫停
    [16, 'fail', false, false, true],    // 手动 16 分撞死
    [99, 'full', false, false, true],    // 手动 99 分铺满
    [14, 'fail', false, false, false],   // 手动 14 分（差一分）
    [0, 'fail', false, false, false],    // 手动 0 分
    [400, 'full', true, false, false],   // AI 铺满全盘
    [15, 'fail', true, true, false],     // AI 15 分被叫停
    [30, 'fail', true, false, false]     // AI 30 分撞死
];
for (const c of TROPHY_CASES) g.recordRound(c[0], c[1], c[2], c[3]);
const texts = g.historyTexts().reverse();   // 列表倒序展示，翻回正序
check('战绩条数正确', texts.length === TROPHY_CASES.length,
    texts.length + ' / ' + TROPHY_CASES.length);
TROPHY_CASES.forEach((c, i) => {
    const got = texts[i] || '(缺)';
    const hasTrophy = got.indexOf('🏆') >= 0;
    const label = (c[2] ? 'AI' : '手动') + ' ' + c[0] + ' 分';
    check(label + (c[4] ? ' 应有奖杯' : ' 不应有奖杯') + ' -> ' + got,
        hasTrophy === c[4]);
});
// 奖杯不能顶掉原来的结束方式图标
const firstText = texts[0] || '';
check('奖杯不顶掉结束方式图标（手动15分叫停 = 🔄🏆）',
    firstText.indexOf('🔄') >= 0 && firstText.indexOf('🏆') >= 0, firstText);
check('未达标的局没有奖杯（手动14分）',
    (texts[3] || '').indexOf('🏆') < 0, texts[3]);
check('AI 的局即使 400 分也没有奖杯',
    (texts[5] || '').indexOf('🏆') < 0, texts[5]);

console.log('\n=== 9. 工具栏按钮的点击接线 ===');
// 这一节测的是"按钮点下去有没有反应"，不是按钮调用的函数对不对 ——
// 函数在别处已经测过；这里防的是"监听器没绑上 / 绑到了已删元素"。
g.startNewRoundWithPrompt();
g.beginRound();
const beforeEndClick = g.state();
check('点击前处于游玩中', beforeEndClick.gameOver === false && beforeEndClick.roundInProgress === true);
g.clickEndBtn();
const afterEndClick = g.state();
check('点「结束本局」-> gameOver', afterEndClick.gameOver === true,
    'gameOver=' + afterEndClick.gameOver);
check('点「结束本局」-> 记了战绩', afterEndClick.history.length === beforeEndClick.history.length + 1,
    beforeEndClick.history.length + ' -> ' + afterEndClick.history.length);
check('点「结束本局」-> 标为玩家叫停',
    !!afterEndClick.lastResult && afterEndClick.lastResult.endedByUser === true);

g.startNewRoundWithPrompt();
g.beginRound();
const beforePauseClick = g.state();
g.clickPauseBtn();
const afterPauseClick = g.state();
check('点「暂停」-> paused 翻转', afterPauseClick.paused === !beforePauseClick.paused,
    beforePauseClick.paused + ' -> ' + afterPauseClick.paused);
check('点「暂停」-> 按钮文案变「继续」', afterPauseClick.pauseLabel.indexOf('继续') >= 0,
    afterPauseClick.pauseLabel);
g.clickPauseBtn();                        // 恢复 -> 进倒计时
g.fastForwardCountdown();
check('再点一次 -> 恢复推进', g.state().paused === false);

console.log('\n========================================');
console.log('  通过 ' + pass + ' 项，失败 ' + fail + ' 项');
console.log('========================================');
process.exit(fail === 0 ? 0 : 2);
