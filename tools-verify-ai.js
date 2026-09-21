/**
 * AI 逻辑无头验证脚本（本地验证用，不参与提交）
 *
 * 做法：把 index.html 里的 <script> 抽出来，在 node:vm 里用最小 DOM/Canvas 桩
 * 跑起来，再用可复现的伪随机数驱动几百局「AI 自动玩」，统计：
 *   - 有多少局能在 stepLimit 步内连吃 15 个食物且不死
 *   - 失败原因分布、平均/最坏步数
 *
 * 用法： node tools-verify-ai.js [局数] [每局步数上限]
 *   例： node tools-verify-ai.js 400 8000
 *
 * 页面里所有文件级声明都是 let/const，不会挂到 globalThis，
 * 因此脚本末尾追加了一小段导出代码，把观测点显式挂上去。
 */
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const HTML = path.join(__dirname, 'index.html');
// 胜利条件：蛇身铺满全部格子。格子数从页面里取，避免两处各写一份。
let GRID_CELLS = 0;

const html = fs.readFileSync(HTML, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (scripts.length !== 1) {
    console.error('预期恰好 1 个 script 标签，实际 ' + scripts.length + ' 个');
    process.exit(1);
}
const code = scripts[0];

const exportCode = `
globalThis.__game = {
    startAI: () => startAI(),
    moveSnake: () => moveSnake(),
    gridCells: () => GRID_SIZE * GRID_SIZE,
    // 检查食物是否满足"有解"约束：从蛇头沿回路向前 1 ~ (L+1) 格内
    checkFoodSolvable: () => {
        const total = GRID_SIZE * GRID_SIZE;
        const head = snake[0];
        const headIdx = cycleIndex.get(head.x + ',' + head.y);
        const foodIdx = cycleIndex.get(food.x + ',' + food.y);
        const ahead = ((foodIdx - headIdx) % total + total) % total;
        return { ahead: ahead, maxAhead: Math.min(snake.length + 1, total - snake.length),
                 food: { x: food.x, y: food.y }, snakeLen: snake.length };
    },
    getState: () => ({
        gameOver, winFlag, score, aiMode, aiResult, snake: snake.length,
        foodEatenCount,
        status: statusTip.innerText,
        historyCount: roundHistory.length
    })
};
`;

function makeElement() {
    return {
        innerText: '', innerHTML: '', textContent: '', className: '', style: {},
        children: [],
        appendChild(c) { this.children.push(c); return c; },
        removeChild() {},
        setAttribute() {},
        removeAttribute() {},
        getAttribute() { return null; },
        addEventListener() {}
    };
}

const elements = new Map();
const documentStub = {
    documentElement: makeElement(),
    getElementById(id) {
        if (!elements.has(id)) elements.set(id, makeElement());
        return elements.get(id);
    },
    createElement() { return makeElement(); },
    addEventListener() {},
    querySelector() { return makeElement(); }
};

const ctxStub = new Proxy({}, {
    get(t, prop) { return prop in t ? t[prop] : () => {}; },
    set(t, prop, v) { t[prop] = v; return true; }
});

const canvasStub = makeElement();
canvasStub.width = 400;
canvasStub.height = 400;
canvasStub.getContext = () => ctxStub;
elements.set('gameCanvas', canvasStub);

const storage = new Map();
const localStorageStub = {
    getItem: k => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
};

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

const sandbox = {};
sandbox.globalThis = sandbox;
sandbox.window = sandbox;
sandbox.document = documentStub;
sandbox.localStorage = localStorageStub;
sandbox.CanvasRenderingContext2D = function () {};
sandbox.Date = Date;
sandbox.console = console;
// contextify 只把内容绑定到 context 内部，不额外挂到 sandbox 对象上，
// 所以 Math 要显式注入，才能在外面替换 random 来控制食物生成
sandbox.Math = Object.create(Math);
sandbox.Math.random = mulberry32(1);

// 页面用 setTimeout 自调度驱动游戏循环；测试直接调 moveSnake，因此定时器
// 只需提供空实现。真实演示时长由下面的 makeTickCounter 按同一套调速规则复算。
sandbox.setTimeout = () => 0;
sandbox.setInterval = () => 0;
sandbox.clearInterval = () => {};
sandbox.clearTimeout = () => {};
sandbox.requestAnimationFrame = () => 0;

vm.createContext(sandbox);
vm.runInContext(code + exportCode, sandbox, { filename: 'snake-page.js' });

const game = sandbox.__game;
GRID_CELLS = game.gridCells();

// ---- 复刻页面的节奏，用来算"真实墙钟要跑多久" ----
// 页面现在**不做**自动提速：每 tick 固定走 1 步，AI 模式间隔 AI_TICK_MS。
// 测速规则若改了，这两个常量需要同步（index.html 里是 AI_TICK_INTERVAL）。
const AI_TICK_MS = 60;
let wallTicks = 0;        // 累计帧数（= 总步数）
let ticksThisTrial = 0;   // 本局帧数

const TRIALS = Number(process.argv[2] || 100);
const STEP_LIMIT = Number(process.argv[3] || 200000);

let wins = 0;
const failReasons = new Map();
const stepsList = [];
// 「食物有解」约束的违例记录：食物必须落在蛇头沿回路向前 1 ~ (L+1) 格内
const solvableViolations = [];
let solvableChecks = 0;

for (let seed = 1; seed <= TRIALS; seed++) {
    sandbox.Math.random = mulberry32(seed * 2654435761);
    game.startAI();

    // 每局重置"本局帧数"；现在每帧固定 1 步，帧数就等于步数
    ticksThisTrial = 0;

    let steps = 0;
    while (!game.getState().gameOver && steps < STEP_LIMIT) {
        // 每 50 步抽查一次当前食物是否仍然满足"有解"约束
        if (steps % 50 === 0) {
            const fs = game.checkFoodSolvable();
            solvableChecks++;
            if (!(fs.ahead >= 1 && fs.ahead <= fs.maxAhead)) {
                if (solvableViolations.length < 5) {
                    solvableViolations.push('seed=' + seed + ' step=' + steps +
                        ' ahead=' + fs.ahead + ' maxAhead=' + fs.maxAhead + ' snakeLen=' + fs.snakeLen);
                } else {
                    solvableViolations.push('…');
                }
            }
        }
        game.moveSnake();
        ticksThisTrial++;
        steps++;
    }
    wallTicks += ticksThisTrial;
    const st = game.getState();
    // 终局：蛇身铺满全部格子（吃掉 cells-3 个食物后蛇长达到 cells）。
    // 注意这不是"胜利条件"，只是这局物理上走到头了；游戏本身可以无限开新局。
    if (st.gameOver && st.winFlag && st.snake >= GRID_CELLS && st.aiResult === 'full') {
        wins++;
        stepsList.push(steps);
    } else {
        const reason = steps >= STEP_LIMIT
            ? '超出步数上限(' + STEP_LIMIT + ')'
            : st.status.replace(/^[^ ]+ /, '');
        failReasons.set(reason, (failReasons.get(reason) || 0) + 1);
    }
}

const rate = (wins / TRIALS * 100).toFixed(1);
console.log('========================================');
console.log('  AI 无头验证结果');
console.log('========================================');
console.log('  终局条件      : 蛇身铺满全部 ' + GRID_CELLS + ' 格（游戏本身可无限开新局）');
console.log('  总局数        : ' + TRIALS);
console.log('  步数上限/局   : ' + STEP_LIMIT);
console.log('  铺满全盘      : ' + wins + '  (' + rate + '%)');
console.log('  未铺满        : ' + (TRIALS - wins));
if (failReasons.size) {
    console.log('  失败原因分布  :');
    for (const [r, n] of [...failReasons.entries()].sort((a, b) => b[1] - a[1])) {
        console.log('      - ' + r + ' × ' + n);
    }
}
if (stepsList.length) {
    const sum = stepsList.reduce((a, b) => a + b, 0);
    console.log('  平均步数/局   : ' + (sum / stepsList.length).toFixed(1) +
                '  (min ' + Math.min(...stepsList) + ', max ' + Math.max(...stepsList) + ')');
}
console.log('----------------------------------------');
console.log('  「食物有解」约束检查');
console.log('  抽查次数      : ' + solvableChecks + ' 次（每 50 步一次）');
if (solvableViolations.length) {
    console.log('  违例          : ' + solvableViolations.length);
    for (const v of solvableViolations) console.log('      - ' + v);
} else {
    console.log('  违例          : 0  ✓ 食物始终落在蛇头向前可达范围内');
}
console.log('----------------------------------------');
console.log('  演示时长（每 tick 1 步，匀速）');
console.log('  AI 帧间隔     : ' + AI_TICK_MS + 'ms');
console.log('  平均步数/局   : ' + Math.round(wallTicks / TRIALS) + ' 步');
console.log('  单局墙钟时长  : ' + (wallTicks * AI_TICK_MS / 1000 / TRIALS).toFixed(1) + ' 秒');
console.log('========================================');

process.exit((wins === TRIALS && solvableViolations.length === 0) ? 0 : 2);
