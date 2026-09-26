"""
电路② 验证戴维南定理
================================================================================

被测的含源二端网络（端口 a = 节点 2，端口 b = 地）：

                 ┌──[ R1 = 4 kΩ ]──┐
                 │                 │
                V1 = 12 V          ├──── a (节点 2)
                 │                 │
                GND                │
                                   │
                 ┌──[ R2 = 2 kΩ ]──┘
                 │
                V2 = 6 V
                 │
                GND

两个源各自经一个电阻汇到端口节点 2，所以节点 2 的 KCL 是
    (V2n − V1)/R1 + (V2n − V2)/R2 = 0

元件取值（题目允许自定）：
    V1 = 12 V, R1 = 4 kΩ
    V2 = 6 V,  R2 = 2 kΩ

验证思路（题目要求 V_oc、I_sc 两次仿真 + 等效替换后接负载的验证表）：
    1) 开路：把端口空着，仿真得 V_oc
    2) 短路：端口对地短接，仿真得 I_sc
    3) 戴维南等效电阻：R_th = V_oc / I_sc
       （另外用"独立源置零法"再算一次：两个电压源短路，端口注入 1 A 测电压）
    4) 搭出戴维南等效电路（V_th 串 R_th），接上负载 R_L
    5) 把"原网络接负载"与"等效电路接负载"的电压/电流列表对比
    6) 顺带验证最大功率传输：扫描 R_L，功率峰值应出现在 R_L = R_th

运行： python circuit2_thevenin.py
输出： 控制台对比表 + PNG（原网络/等效电路对照、最大功率传输曲线、V-I 外特性）
"""

import os

import plot_setup
import matplotlib.pyplot as plt
import numpy as np

import PySpice.Logging.Logging as Logging
Logging.setup_logging(logging_level='ERROR')

from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import u_A, u_kOhm, u_Ohm, u_V

# ----------------------------------------------------------------------------
# 元件参数与手算理论值
# ----------------------------------------------------------------------------
V1 = 12.0          # V
R1 = 4_000.0       # Ω
V2 = 6.0           # V
R2 = 2_000.0       # Ω

R_L = 3_000.0      # Ω  验证用的负载

# 手算 V_oc：节点 2 的 KCL
#   (V2n - V1)/R1 + (V2n - V2)/R2 = 0
#   → V2n·(1/R1 + 1/R2) = V1/R1 + V2/R2
G_sum = 1.0 / R1 + 1.0 / R2
I_sum = V1 / R1 + V2 / R2
Voc_theory = I_sum / G_sum                    # = 8.0 V

# 手算 R_th：两个独立电压源置零（短路）后，从端口看进去是 R1 ∥ R2
Rth_theory = 1.0 / G_sum                      # = 1333.33 Ω

# 手算 I_sc：端口短路，节点 2 电位被强制为 0
Isc_theory = V1 / R1 + V2 / R2                # = 6.0 mA（两个源各自灌入的电流之和）

# 手算"接 R_L 后"的端口电压与电流
#   原网络：节点 2 的 KCL  (V/R1 - V1/R1) + (V/R2 - V2/R2) + V/R_L = 0
#   等效后应该完全一样
Vload_theory = (V1 / R1 + V2 / R2) / (G_sum + 1.0 / R_L)
Iload_theory = Vload_theory / R_L

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')


# ----------------------------------------------------------------------------
# 电路搭建
# ----------------------------------------------------------------------------
def build_original(load=None, short_port=False):
    """原含源二端网络。

    load      : 端口上接的负载电阻（Ω），None 表示开路
    short_port: True 时把端口对地短路（用于测 I_sc）
    """
    c = Circuit('Original two-terminal network')
    # 节点 1 与节点 2 之间：V1 串 R1
    c.V('1', 1, c.gnd, V1 @ u_V)
    c.R('1', 1, 2, R1 @ u_Ohm)
    # 节点 3 与节点 2 之间：V2 串 R2
    c.V('2', 3, c.gnd, V2 @ u_V)
    c.R('2', 2, 3, R2 @ u_Ohm)

    if short_port:
        c.R('sc', 2, c.gnd, 1e-6 @ u_Ohm)     # 近似理想短路线
    elif load is not None:
        c.R('L', 2, c.gnd, load @ u_Ohm)
    return c


def build_thevenin(load=None):
    """戴维南等效电路：V_th 串 R_th，端口开在节点 2。"""
    c = Circuit('Thevenin equivalent')
    c.V('th', 1, c.gnd, Voc_theory @ u_V)
    c.R('th', 1, 2, Rth_theory @ u_Ohm)
    if load is not None:
        c.R('L', 2, c.gnd, load @ u_Ohm)
    return c


def op_point(circuit):
    """跑直流工作点，返回各节点电压的字典。"""
    sim = circuit.simulator(temperature=25, nominal_temperature=25)
    an = sim.operating_point()
    return {name: float(np.array(an[name]).ravel()[0]) for name in an.nodes}


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print('=' * 74)
    print(' 电路② 验证戴维南定理')
    print('=' * 74)
    print(' ' + plot_setup.font_report())
    print(' 元件：V1 = %.0f V, R1 = %.1f kΩ, V2 = %.0f V, R2 = %.1f kΩ'
          % (V1, R1 / 1e3, V2, R2 / 1e3))
    print(' 端口 a = 节点 2，端口 b = 地')

    # ---------- 1) 开路仿真 ----------
    voc_sim = op_point(build_original())['2']

    # ---------- 2) 短路仿真 ----------
    # 端口电压 ~0，电流 = 流经短路线的电流
    csc = build_original(short_port=True)
    an = csc.simulator(temperature=25, nominal_temperature=25).operating_point()
    v_port_sc = float(np.array(an['2']).ravel()[0])
    # 短路电流：由 KCL，I_sc = (V1 - V_port)/R1 + (V2 - V_port)/R2
    isc_sim = (V1 - v_port_sc) / R1 + (V2 - v_port_sc) / R2

    # ---------- 3) R_th 两种算法 ----------
    rth_from_ratio = voc_sim / isc_sim
    # 独立源置零法：把 V1、V2 换成 0V 源（等效短路），再测端口看进去的电阻
    c_zero = Circuit('R_th by zeroing sources')
    c_zero.V('1', 1, c_zero.gnd, 0 @ u_V)
    c_zero.R('1', 1, 2, R1 @ u_Ohm)
    c_zero.V('2', 3, c_zero.gnd, 0 @ u_V)
    c_zero.R('2', 2, 3, R2 @ u_Ohm)
    # 在端口注入 1 A 测电压，则 R = V / 1A
    c_zero.I('test', c_zero.gnd, 2, 1 @ u_A)
    an_zero = c_zero.simulator(temperature=25, nominal_temperature=25).operating_point()
    rth_zeroing = float(np.array(an_zero['2']).ravel()[0])

    # ---------- 4) 原网络 vs 等效电路，接同一负载 ----------
    rows = []
    for name, rl in [('开路 (R_L = ∞)', None),
                     ('R_L = 10 kΩ', 10_000.0),
                     ('R_L = 3 kΩ', 3_000.0),
                     ('R_L = 1 kΩ', 1_000.0),
                     ('R_L = 500 Ω', 500.0)]:
        v_orig = op_point(build_original(load=rl))['2']
        v_thev = op_point(build_thevenin(load=rl))['2']
        i_orig = 0.0 if rl is None else v_orig / rl
        i_thev = 0.0 if rl is None else v_thev / rl
        rows.append((name, v_orig, v_thev, i_orig, i_thev))

    # ---------- 5) 最大功率传输：扫 R_L ----------
    load_sweep = np.logspace(np.log10(100), np.log10(20_000), 60)
    p_orig = []
    p_thev = []
    for rl in load_sweep:
        v1_ = op_point(build_original(load=float(rl)))['2']
        v2_ = op_point(build_thevenin(load=float(rl)))['2']
        p_orig.append(v1_ ** 2 / rl)
        p_thev.append(v2_ ** 2 / rl)
    p_orig = np.array(p_orig)
    p_thev = np.array(p_thev)
    idx_max = int(np.argmax(p_thev))
    rl_at_pmax = float(load_sweep[idx_max])
    pmax_sim = float(p_thev[idx_max])
    pmax_theory = Voc_theory ** 2 / (4.0 * Rth_theory)

    # ---------- 打印对比表 ----------
    print('\n[1] 开路电压 V_oc')
    print('    手算  V_oc = (V1/R1 + V2/R2) / (1/R1 + 1/R2) = %.4f V' % Voc_theory)
    print('    仿真  V_oc = %.4f V' % voc_sim)

    print('\n[2] 短路电流 I_sc')
    print('    手算  I_sc = V1/R1 + V2/R2 = %.4f mA' % (Isc_theory * 1e3))
    print('    仿真  I_sc = %.4f mA   （短路后端口电压 %.3e V）'
          % (isc_sim * 1e3, v_port_sc))

    print('\n[3] 戴维南等效电阻 R_th')
    print('    手算  R_th = R1 ∥ R2 = %.4f Ω' % Rth_theory)
    print('    仿真一  R_th = V_oc / I_sc = %.4f Ω' % rth_from_ratio)
    print('    仿真二  R_th = 独立源置零后端口注入 1 A 测得 = %.4f Ω' % rth_zeroing)

    print('\n[4] 接负载后的对比表（原网络 vs 戴维南等效电路）')
    print('    %-16s %12s %12s %12s %12s %10s' %
          ('负载', 'V_orig (V)', 'V_thev (V)', 'I_orig (mA)', 'I_thev (mA)', '偏差'))
    print('    ' + '-' * 82)
    for name, vo, vt, io, it in rows:
        dev = abs(vt - vo) / max(abs(vo), 1e-12) * 100.0
        print('    %-16s %12.4f %12.4f %12.4f %12.4f %9.2e%%'
              % (name, vo, vt, io * 1e3, it * 1e3, dev))
    print('    （手算 R_L = 3 kΩ 时 V = %.4f V, I = %.4f mA）'
          % (Vload_theory, Iload_theory * 1e3))

    print('\n[5] 最大功率传输')
    print('    理论  峰值出现在 R_L = R_th = %.1f Ω，P_max = V_oc²/(4R_th) = %.4f mW'
          % (Rth_theory, pmax_theory * 1e3))
    print('    仿真  峰值出现在 R_L = %.1f Ω，P_max = %.4f mW'
          % (rl_at_pmax, pmax_sim * 1e3))

    # ---------- 画图 ----------
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))

    ax = axes[0]
    labels = [r[0].replace(' (R_L = ∞)', '\n(开路)') for r in rows]
    x = np.arange(len(rows))
    w = 0.36
    ax.bar(x - w / 2, [r[1] for r in rows], w, label='原网络', color='#3498db')
    ax.bar(x + w / 2, [r[2] for r in rows], w, label='戴维南等效', color='#e67e22')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel('端口电压 (V)')
    ax.set_title('原网络 vs 戴维南等效：接不同负载时的端口电压')
    ax.legend()

    ax = axes[1]
    ax.semilogx(load_sweep, p_thev * 1e3, color='#e67e22', linewidth=2, label='戴维南等效')
    ax.semilogx(load_sweep, p_orig * 1e3, '--', color='#3498db', linewidth=1.4, label='原网络')
    ax.axvline(Rth_theory, color='#e74c3c', linewidth=0.9, linestyle=':')
    ax.plot([rl_at_pmax], [pmax_sim * 1e3], 'o', color='#e74c3c', markersize=6)
    ax.annotate('R_L = R_th = %.0f Ω\nP_max = %.2f mW' % (rl_at_pmax, pmax_sim * 1e3),
                xy=(rl_at_pmax, pmax_sim * 1e3),
                xytext=(rl_at_pmax * 0.12, pmax_sim * 1e3 * 0.72),
                fontsize=9, color='#c0392b',
                arrowprops=dict(arrowstyle='->', color='#c0392b', linewidth=0.9))
    ax.set_xlabel('负载电阻 R_L (Ω)')
    ax.set_ylabel('负载功率 (mW)')
    ax.set_title('最大功率传输：峰值在 R_L = R_th')
    ax.legend()

    plt.tight_layout()
    p = os.path.join(OUT_DIR, 'c2_thevenin.png')
    plt.savefig(p, dpi=130)
    plt.close(fig)

    # 端口特性曲线：V-I 外特性是一条直线，斜率 -R_th
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    i_axis = np.linspace(0, isc_sim, 50)
    v_line = Voc_theory - Rth_theory * i_axis
    ax.plot(i_axis * 1e3, v_line, color='#8e44ad', linewidth=2,
            label='V = V_oc − R_th·I')
    ax.plot([0], [Voc_theory], 'o', color='#e74c3c', markersize=7)
    ax.annotate('开路点 (0, %.2f V)' % Voc_theory, xy=(0, Voc_theory),
                xytext=(isc_sim * 1e3 * 0.12, Voc_theory * 0.82),
                fontsize=9, color='#c0392b',
                arrowprops=dict(arrowstyle='->', color='#c0392b', linewidth=0.9))
    ax.plot([isc_sim * 1e3], [0], 'o', color='#e74c3c', markersize=7)
    ax.annotate('短路点 (%.2f mA, 0)' % (isc_sim * 1e3), xy=(isc_sim * 1e3, 0),
                xytext=(isc_sim * 1e3 * 0.35, Voc_theory * 0.22),
                fontsize=9, color='#c0392b',
                arrowprops=dict(arrowstyle='->', color='#c0392b', linewidth=0.9))
    # 把负载测试点也标上
    for name, vo, vt, io, it in rows:
        if io > 0:
            ax.plot([io * 1e3], [vo], 's', color='#2ecc71', markersize=5)
    ax.plot([], [], 's', color='#2ecc71', markersize=5, label='各负载工作点')
    ax.set_xlabel('端口电流 I (mA)')
    ax.set_ylabel('端口电压 V (V)')
    ax.set_title('含源二端网络的外特性（斜率 = −R_th）')
    ax.legend()
    plt.tight_layout()
    p2 = os.path.join(OUT_DIR, 'c2_thevenin_vi.png')
    plt.savefig(p2, dpi=130)
    plt.close(fig)

    print('\n图已保存：')
    print('  ' + p)
    print('  ' + p2)
    print('=' * 74)


if __name__ == '__main__':
    main()
