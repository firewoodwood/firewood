/**
 * 独立验证：只核对任务书的阶段二硬指标 ——
 * AI 自动控制蛇，连续吃完 15 个食物不死（不撞墙、不撞自己），全程无需人工操作。
 *
 * 说明：仓库里的 tools-verify-ai.js 口径更严（要铺满全盘 400 格），
 * 本脚本专门对应任务书原文那一条，两者互补。
 *
 * 判定：
 *   · 吃到 15 分且从未 gameOver  -> 达标
 *   · 无论何时 gameOver（不区分死因）-> 不达标
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HTML = path.join(__dirname, 'index.html');
const html = fs.readFileSync(HTML, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (scripts.length !== 1) {
    console.error('预期恰好 1 个 script 标签，实际 ' + scripts.length + ' 个');
    process.exit(1);
}

const exportCode = `
globalThis.__game = {
    // 每局先 initGame() 拿一局干净的：它会重置 score / snake / aiMode / gameOver
    // 等全部状态（注意 startAI() 自带 if (aiMode) return 守卫，重复调用不会重置，
    //  所以绝不能靠连续调用 startAI() 来开新局）。
    newRound: () => { initGame(); aiMode = true; aiResult = null; },
    moveSnake: () => moveSnake(),
    gridCells: () => GRID_SIZE * GRID_SIZE,
    winScore: () => WIN_SCORE,
    disableRender: () => { drawCanvas = function () {}; updateEffects = function () {}; },
    getState: () => ({
        gameOver, winFlag, score, aiMode, aiResult, snake: snake.length,
        foodEatenCount, stepCount,
        head: { x: snake[0].x, y: snake[0].y }
    })
};
`;

function makeElement() {
    const classes = new Set();
    const el = {
        innerText: '', innerHTML: '', textContent: '', className: '', style: {},
        children: [], width: 0, height: 0,
        classList: {
            add(c) { classes.add(c); }, remove(c) { classes.delete(c); },
            contains(c) { return classes.has(c); },
            toggle(c) { if (classes.has(c)) { classes.delete(c); return false; } classes.add(c); return true; }
        },
        appendChild(c) { this.children.push(c); return c; },
        removeChild() {}, setAttribute() {}, removeAttribute() {},
        getAttribute() { return null; }, addEventListener() {},
        getContext() {
            return new Proxy({}, {
                get(_, k) {
                    if (k === 'canvas') return { width: 400, height: 400 };
                    return () => ({});
                }
            });
        }
    };
    return el;
}

const elements = new Map();
const documentStub = {
    documentElement: makeElement(),
    getElementById(id) { if (!elements.has(id)) elements.set(id, makeElement()); return elements.get(id); },
    createElement() { return makeElement(); },
    querySelector() { return makeElement(); },
    addEventListener() {}
};

const sandbox = {
    document: documentStub,
    window: { addEventListener() {}, matchMedia: () => ({ matches: false }) },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    requestAnimationFrame() { return 0; },
    cancelAnimationFrame() {},
    setTimeout() { return 0; },
    clearTimeout() {},
    setInterval() { return 0; },
    clearInterval() {},
    console,
    Math, Date, JSON
};
sandbox.globalThis = sandbox;

const ctx = vm.createContext(sandbox);
// 伪随机数：可复现（与仓库脚本同一思路）
let seed = 20260101;
function rand() {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
}
sandbox.Math = Object.create(Math);
sandbox.Math.random = rand;

vm.runInContext(scripts[0] + exportCode, ctx, { filename: 'snake/index.html:script' });

const G = sandbox.__game;
G.disableRender();

const TRIALS = Number(process.argv[2] || 20);
const STEP_LIMIT = Number(process.argv[3] || 4000);
const NEED = G.winScore();

console.log('=== 阶段二硬指标验证：AI 连吃 ' + NEED + ' 个食物不死 ===');
console.log('  局数        : ' + TRIALS);
console.log('  每局步数上限: ' + STEP_LIMIT);
console.log('  棋盘        : ' + G.gridCells() + ' 格');
console.log('');

let pass = 0, died = 0, timeout = 0, worstSteps = 0, sumSteps = 0;
const deathInfo = [];

for (let t = 0; t < TRIALS; t++) {
    G.newRound();
    let steps = 0, dead = false;
    while (steps < STEP_LIMIT) {
        const st = G.getState();
        if (st.gameOver) { dead = true; deathInfo.push(st); break; }
        if (st.score >= NEED) break;
        G.moveSnake();
        steps++;
    }
    const st = G.getState();
    if (dead) {
        died++;
    } else if (st.score >= NEED && !st.gameOver) {
        pass++;
        sumSteps += steps;
        if (steps > worstSteps) worstSteps = steps;
    } else {
        timeout++;
    }
}

console.log('  结果：');
console.log('    达标（连吃 ' + NEED + ' 个不死）: ' + pass + ' / ' + TRIALS);
console.log('    中途死亡                      : ' + died);
console.log('    超步数上限未达标              : ' + timeout);
if (pass > 0) {
    console.log('    达标局平均步数                : ' + (sumSteps / pass).toFixed(1));
    console.log('    达标局最坏步数                : ' + worstSteps);
}
if (died > 0) {
    console.log('    死亡局样例                    : ' + JSON.stringify(deathInfo[0]));
}
console.log('');
console.log(pass === TRIALS
    ? '  ✓ 「AI 连续吃完 ' + NEED + ' 个食物不死」在 ' + TRIALS + ' 局中全部达成'
    : '  ★ 有 ' + (TRIALS - pass) + ' 局未达标，需排查');
process.exit(pass === TRIALS ? 0 : 2);
