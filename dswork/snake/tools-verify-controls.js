/**
 * 暂停 / 结束本局 行为验证（本地验证用，不参与提交）
 *
 * 用法： node tools-verify-controls.js
 *
 * 验证点：
 *   1) 暂停后 moveSnake 不再推进（蛇长/得分/食物计数都不变）
 *   2) 恢复后能继续推进
 *   3) 暂停可以反复切换，且不影响状态
 *   4) 结束本局等价于蛇死亡：走 endGame('fail')，记战绩、结算最高分、
 *      并清除暂停状态，之后还能再开新局
 */
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const code = [...fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8')
    .matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1])[0];

const exportCode = `
globalThis.__g = {
    startAI: () => startAI(),
    moveSnake: () => moveSnake(),
    togglePause: () => togglePause(),
    finishRound: () => finishRound(),
    resetGame: () => resetGame(),
    state: () => ({
        gameOver, winFlag, paused, score, aiMode, aiResult, endReason,
        snakeLen: snake.length, foodEatenCount,
        status: statusTip.innerText,
        pauseLabel: pauseBtn.innerText,
        pauseHighlighted: pauseBtn.classList.contains('is-paused'),
        history: roundHistory.map(h => ({ score: h.score, mode: h.mode, result: h.result, won: h.won }))
    })
};
`;

function makeElement() {
    const classes = new Set();
    return {
        innerText: '', innerHTML: '', textContent: '', className: '', style: {}, children: [],
        classList: {
            add(c) { classes.add(c); },
            remove(c) { classes.delete(c); },
            contains(c) { return classes.has(c); }
        },
        appendChild(c) { this.children.push(c); return c; },
        removeChild() {}, setAttribute() {}, removeAttribute() {},
        getAttribute() { return null; }, addEventListener() {}
    };
}

const els = new Map();
const documentStub = {
    documentElement: makeElement(),
    getElementById(id) { if (!els.has(id)) els.set(id, makeElement()); return els.get(id); },
    createElement() { return makeElement(); },
    addEventListener() {}, querySelector() { return makeElement(); }
};

const noop = () => {};
const ctxStub = {
    save: noop, restore: noop, beginPath: noop, closePath: noop, moveTo: noop, lineTo: noop,
    arc: noop, fill: noop, stroke: noop, fillRect: noop, strokeRect: noop, clearRect: noop,
    quadraticCurveTo: noop, fillText: noop, measureText: () => ({ width: 0 }),
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

console.log('=== 1. 暂停后不再推进 ===');
sandbox.Math.random = mulberry32(20260917);
g.startAI();
for (let i = 0; i < 200; i++) g.moveSnake();
const before = g.state();
check('AI 已开始推进', before.snakeLen > 3, '蛇长 ' + before.snakeLen + '，吃到 ' + before.foodEatenCount);

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

console.log('\n=== 2. 恢复后能继续推进 ===');
g.togglePause();
const resumed = g.state();
check('paused 变为 false', resumed.paused === false);
check('按钮文案变回「暂停」', resumed.pauseLabel.indexOf('暂停') >= 0, resumed.pauseLabel);
check('按钮取消高亮', resumed.pauseHighlighted === false);

const beforeResume = g.state().foodEatenCount;
for (let i = 0; i < 2000; i++) g.moveSnake();
const afterResume = g.state();
check('恢复后继续吃到食物', afterResume.foodEatenCount > beforeResume,
    beforeResume + ' → ' + afterResume.foodEatenCount);

console.log('\n=== 3. 反复切换暂停不影响状态 ===');
const beforeToggle = g.state();
for (let i = 0; i < 20; i++) {
    g.togglePause();          // 暂停
    g.moveSnake();            // 应无效
    g.togglePause();          // 恢复
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

console.log('\n========================================');
console.log('  通过 ' + pass + ' 项，失败 ' + fail + ' 项');
console.log('========================================');
process.exit(fail === 0 ? 0 : 2);
