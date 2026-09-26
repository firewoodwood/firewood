"""
电路① RC 低通滤波电路
================================================================================

电路：  Vi ──[ R ]──┬── Vo
                    │
                   ===  C
                    │
                   GND

元件取值（题目允许自定）：R = 1 kΩ，C = 100 nF
  τ  = R·C = 1e3 × 100e-9 = 1e-4 s = 100 µs
  fc = 1 / (2π·R·C) = 1 / (2π×1e-4) ≈ 1591.55 Hz

本脚本做三件事，并把结果与手算值一一对照：
  1) 方波输入的瞬态响应：看输出的指数充放电，测实际时间常数 τ
  2) 幅频特性（Bode 图）：找 -3 dB 点，验证 fc 的手算值
  3) 相频特性：低频 0°、fc 处 -45°、高频趋于 -90°

运行： python circuit1_rc_lowpass.py
输出： 控制台表格 + PNG 波形图（transient / bode）
"""

import os

import plot_setup                       # 中文字体 / Agg 后端 / 统一风格
import matplotlib.pyplot as plt
import numpy as np

import PySpice.Logging.Logging as Logging
Logging.setup_logging(logging_level='ERROR')

from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import u_F, u_Hz, u_Ohm, u_s, u_V

# ----------------------------------------------------------------------------
# 元件参数与手算理论值
# ----------------------------------------------------------------------------
R = 1_000.0        # Ω
C = 100e-9         # F

tau_theory = R * C                        # 时间常数 (s)
fc_theory = 1.0 / (2.0 * np.pi * R * C)   # 截止频率 (Hz)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')


def build_circuit():
    """搭出 RC 低通电路（只含 R、C，激励源由各分析自行添加）。

    注意：激励源不放在这里。否则 transient 里再加一个同名 Vin 会撞名
    （PySpice 会抛 NameError: Element name Vin is already defined），
    而且瞬态要方波、AC 要 AC 1，两者的源本来就不一样。
    """
    c = Circuit('RC Low-Pass Filter')
    c.R('1', 1, 2, R @ u_Ohm)
    c.C('1', 2, c.gnd, C @ u_F)
    return c


# ----------------------------------------------------------------------------
# 1) 瞬态：方波输入
# ----------------------------------------------------------------------------
def run_transient():
    """用方波看指数充放电，并从波形里反推时间常数 τ。

    方波频率取 200 Hz（周期 5 ms = 50τ），这样每个半周期都能充到稳态，
    波形上能清楚看到指数形状而不是被频率掩盖。
    """
    period = 1.0 / 200.0
    # 上升/下降时间取周期的 0.1%，近似理想方波又不太吃步长
    rise = period * 1e-3

    c = build_circuit()
    # PULSE(V1 V2 TD TR TF PW PER)：td=0，上升/下降时间 rise，脉宽与间隔各占半周期
    c.V('in', 1, c.gnd,
        'PULSE 0 5 0 %f %f %f %f' % (rise, rise, period / 2.0, period))

    sim = c.simulator(temperature=25, nominal_temperature=25)
    # 步长取 τ/200，保证指数曲线足够光滑
    analysis = sim.transient(step_time=tau_theory / 200, end_time=5 * period)

    t = np.array(analysis.time)
    vin = np.array(analysis['1'])
    vout = np.array(analysis['2'])

    # 从第一个完整充电段反推 τ：取 0~63.2% 的稳态值所需时间
    v_final = 5.0
    target = 0.632 * v_final
    # 找第一次上升沿之后 vout 穿越 63.2% 的时刻
    t_rise_start = None
    for i in range(1, len(t)):
        if vin[i] > 2.5 and vin[i - 1] <= 2.5:
            t_rise_start = t[i]
            break
    tau_meas = None
    if t_rise_start is not None:
        for i in range(1, len(t)):
            if t[i] > t_rise_start and vout[i] >= target and vout[i - 1] < target:
                tau_meas = t[i] - t_rise_start
                break
    # 同时用 10%~90% 上升时间校验：t_r = 2.197τ  →  τ = t_r / 2.197
    tau_from_tr = None
    if t_rise_start is not None:
        t10 = t90 = None
        for i in range(1, len(t)):
            if t[i] < t_rise_start:
                continue
            if t10 is None and vout[i] >= 0.10 * v_final:
                t10 = t[i]
            if t90 is None and vout[i] >= 0.90 * v_final:
                t90 = t[i]
                break
        if t10 is not None and t90 is not None:
            tau_from_tr = (t90 - t10) / 2.197

    return dict(t=t, vin=vin, vout=vout, tau_meas=tau_meas, tau_from_tr=tau_from_tr)


# ----------------------------------------------------------------------------
# 2) & 3) 交流扫描：幅频与相频
# ----------------------------------------------------------------------------
def run_ac():
    """AC 扫描，得到幅频/相频，并找 -3 dB 点。"""
    c = build_circuit()
    c.V('in', 1, c.gnd, 'DC 0 AC 1')

    sim = c.simulator(temperature=25, nominal_temperature=25)
    # 10 Hz ~ 100 kHz，每十倍频程 200 点
    analysis = sim.ac(start_frequency=10 @ u_Hz, stop_frequency=100 @ u_Hz * 1000,
                      number_of_points=200, variation='dec')

    freq = np.array(analysis.frequency)
    vout = np.array(analysis['2'])
    gain = np.abs(vout)
    gain_db = 20.0 * np.log10(gain)
    phase_deg = np.angle(vout, deg=True)

    # 找 -3 dB 交点（在 0 dB 附近的低频增益是 1，即 0 dB）
    fc_meas = None
    for i in range(1, len(gain_db)):
        if gain_db[i - 1] >= -3.0 and gain_db[i] < -3.0:
            # 线性插值提高精度
            x0, x1 = np.log10(freq[i - 1]), np.log10(freq[i])
            y0, y1 = gain_db[i - 1], gain_db[i]
            x = x0 + (y0 - (-3.0)) * (x1 - x0) / (y1 - y0)
            fc_meas = 10 ** x
            break

    phase_at_fc = None
    if fc_meas is not None:
        phase_at_fc = float(np.interp(np.log10(fc_meas), np.log10(freq), phase_deg))

    return dict(freq=freq, gain_db=gain_db, phase_deg=phase_deg,
                fc_meas=fc_meas, phase_at_fc=phase_at_fc)


# ----------------------------------------------------------------------------
# 主流程：算、画、打印对比表
# ----------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print('=' * 74)
    print(' 电路① RC 低通滤波电路    R = %.0f Ω, C = %.0f nF' % (R, C * 1e9))
    print('=' * 74)
    print(' ' + plot_setup.font_report())

    tr = run_transient()
    ac = run_ac()

    # ---------- 对比表 ----------
    print('\n[1] 时间常数 τ')
    print('    手算  τ = R·C = %.0f Ω × %.0e F = %.4e s = %.1f µs'
          % (R, C, tau_theory, tau_theory * 1e6))
    if tr['tau_meas'] is not None:
        print('    仿真  τ（从 0→63.2%% 实测）= %.4e s = %.1f µs'
              % (tr['tau_meas'], tr['tau_meas'] * 1e6))
    if tr['tau_from_tr'] is not None:
        print('    仿真  τ（由 10%%~90%% 上升时间反推）= %.4e s = %.1f µs'
              % (tr['tau_from_tr'], tr['tau_from_tr'] * 1e6))

    print('\n[2] 截止频率 fc（-3 dB）')
    print('    手算  fc = 1/(2πRC) = %.2f Hz' % fc_theory)
    if ac['fc_meas'] is not None:
        err = (ac['fc_meas'] - fc_theory) / fc_theory * 100.0
        print('    仿真  fc（Bode 图 -3 dB 交点）= %.2f Hz   (偏差 %.3f%%)'
              % (ac['fc_meas'], err))

    print('\n[3] 相移')
    if ac['fc_meas'] is not None:
        print('    理论  fc 处相移 = -45°')
        print('    仿真  fc 处相移 = %.2f°' % ac['phase_at_fc'])
    idx_low = 0
    idx_high = len(ac['freq']) - 1
    print('    理论  低频 → 0°，高频 → -90°')
    print('    仿真  %.0f Hz 处 %.2f°，%.0f Hz 处 %.2f°'
          % (ac['freq'][idx_low], ac['phase_deg'][idx_low],
             ac['freq'][idx_high], ac['phase_deg'][idx_high]))

    # ---------- 画图 ----------
    fig, axes = plt.subplots(2, 1, figsize=(9, 7.5))
    ax = axes[0]
    ax.plot(tr['t'] * 1e3, tr['vin'], '--', color='#888', linewidth=1.2, label='输入 Vi（方波）')
    ax.plot(tr['t'] * 1e3, tr['vout'], color='#e74c3c', linewidth=1.8, label='输出 Vo（指数充放电）')
    ax.axhline(0.632 * 5, color='#3498db', linewidth=0.8, linestyle=':')
    ax.text(0.02, 0.70, '63.2% 稳态值', transform=ax.transAxes,
            color='#3498db', fontsize=9)
    ax.set_xlabel('时间 (ms)')
    ax.set_ylabel('电压 (V)')
    ax.set_title('RC 低通滤波：方波输入的瞬态响应')
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)

    ax = axes[1]
    ax.semilogx(ac['freq'], ac['gain_db'], color='#2ecc71', linewidth=1.8, label='幅频 (dB)')
    ax.axhline(-3, color='#e74c3c', linewidth=0.9, linestyle='--')
    ax.axvline(fc_theory, color='#e74c3c', linewidth=0.9, linestyle='--')
    ax.plot([fc_theory], [-3], 'o', color='#e74c3c', markersize=6)
    ax.annotate('fc = %.1f Hz @ -3 dB' % fc_theory,
                xy=(fc_theory, -3), xytext=(fc_theory * 3.2, -12),
                fontsize=9, color='#c0392b',
                arrowprops=dict(arrowstyle='->', color='#c0392b', linewidth=0.9))
    ax.set_xlabel('频率 (Hz)')
    ax.set_ylabel('增益 (dB)')
    ax.set_ylim(-50, 5)
    ax.set_title('幅频特性（Bode 图）')
    ax.grid(alpha=0.3, which='both')
    ax.legend(fontsize=9)

    # 相频单独放到同一张图的第二个 y 轴太挤，这里改画两栏
    plt.tight_layout()
    p1 = os.path.join(OUT_DIR, 'c1_rc_transient_bode.png')
    plt.savefig(p1, dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.semilogx(ac['freq'], ac['phase_deg'], color='#8e44ad', linewidth=1.8)
    ax.axvline(fc_theory, color='#e74c3c', linewidth=0.9, linestyle='--')
    ax.axhline(-45, color='#e74c3c', linewidth=0.9, linestyle='--')
    ax.plot([fc_theory], [ac['phase_at_fc']], 'o', color='#e74c3c', markersize=6)
    ax.annotate('fc 处 -45°（实测 %.1f°）' % ac['phase_at_fc'],
                xy=(fc_theory, ac['phase_at_fc']), xytext=(fc_theory * 4, -30),
                fontsize=9, color='#c0392b',
                arrowprops=dict(arrowstyle='->', color='#c0392b', linewidth=0.9))
    ax.set_xlabel('频率 (Hz)')
    ax.set_ylabel('相位 (°)')
    ax.set_title('相频特性')
    ax.set_ylim(-95, 5)
    ax.grid(alpha=0.3, which='both')
    plt.tight_layout()
    p2 = os.path.join(OUT_DIR, 'c1_rc_phase.png')
    plt.savefig(p2, dpi=130)
    plt.close(fig)

    print('\n仿真出图已保存：')
    print('  ' + p1)
    print('  ' + p2)
    print('=' * 74)


if __name__ == '__main__':
    main()
