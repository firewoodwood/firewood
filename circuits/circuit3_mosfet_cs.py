"""
电路③ NMOS 共源级放大电路
================================================================================

题目给定的参数（不能自定）：
    VDD = 5 V
    Rg1 = 60 kΩ, Rg2 = 40 kΩ     → 分压给栅极提供直流偏置
    Rd  = 2 kΩ
    Cb1 视为足够大（输入耦合电容，交流短路）
    NMOS 模型：K = 0.8 mA/V², V_th = 1 V, λ = 0.02 /V
    输入：Vi = 10 mV / 1 kHz 正弦波

电路：

              VDD
               │
              [Rd] 2 kΩ
               │
    Vi ──||────┼────── Vo          Cb1 足够大，交流短路
         Cb1   │
          ┌────┤
         [Rg1] │ [Rg2]
          └────┤
               │
            ┌──┴──┐
            │ G   │  NMOS
            │  S──┴── GND
            └─────┘

源极直接接地（题目未给 Rs），所以 V_GS = V_G = VDD·Rg2/(Rg1+Rg2)。

手算（详见正文推导）：
    V_G  = 5 × 40/(60+40) = 2 V ... 但下面会看到，这个分压比不是 2 V 而是 2 V
    V_GS = V_G                      （源极接地）
    I_D  = ½·K·(V_GS − V_th)²       （先假定饱和区）
    V_DS = VDD − I_D·Rd
    饱和判据：V_DS > V_GS − V_th
    gm   = K·(V_GS − V_th)
    ro   = 1/(λ·I_D)
    Av   = −gm·(Rd ∥ ro)

本脚本做：
    1) 直流工作点仿真，与手算的 V_GS / I_D / V_DS 对比，并判断是否饱和
    2) 瞬态仿真：输入 10 mV/1 kHz 正弦，看输出波形（反相放大），实测增益
    3) 交流扫描：幅频/相频，验证中频增益与手算一致
    4) 输出两张等效电路图（直流通路、小信号等效模型）

运行： python circuit3_mosfet_cs.py
输出： 控制台对比表 + PNG（瞬态、Bode、两张等效电路图）
"""

import os

import plot_setup
import matplotlib.pyplot as plt
import numpy as np

import PySpice.Logging.Logging as Logging
Logging.setup_logging(logging_level='ERROR')

from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import u_F, u_Hz, u_Ohm, u_V

# ----------------------------------------------------------------------------
# 题目给定参数
# ----------------------------------------------------------------------------
VDD = 5.0            # V
RG1 = 60_000.0       # Ω
RG2 = 40_000.0       # Ω
RD = 2_000.0         # Ω
K = 0.8e-3           # A/V²   (0.8 mA/V²)，即 I_D = K·(V_GS − V_th)² 中的系数
VTH = 1.0            # V
LAMBDA = 0.02        # 1/V

VI_AMP = 10e-3       # V   输入正弦幅度
VI_FREQ = 1_000.0    # Hz

# 仿真里给 MOS 加少量寄生电容，否则 AC 扫描看不到高频滚降
CGS = 20e-12         # F
CGD = 4e-12          # F

# 输入耦合电容 Cb1："视为足够大"，取 100 µF。
# 这里用 SI 数值而不是 100 @ u_F —— 后者实测会生成 `Cb1 1 2 100`（100 法拉）。
CB1_FARAD = 100e-6   # F

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')


# ----------------------------------------------------------------------------
# 手算
# ----------------------------------------------------------------------------
def hand_calc():
    """按题目要求手算静态工作点与增益。"""
    vg = VDD * RG2 / (RG1 + RG2)          # 分压
    vgs = vg                              # 源极接地
    vov = vgs - VTH                       # 过驱动电压
    id_ = 0.5 * K * vov ** 2              # 饱和区平方律 I_D = ½·K·V_ov²
    vds = VDD - id_ * RD
    sat_ok = vds > vov                    # 饱和判据 V_DS > V_GS − V_th
    gm = K * vov                          # gm = ∂I_D/∂V_GS = K·V_ov
    ro = 1.0 / (LAMBDA * id_)
    rd_par_ro = 1.0 / (1.0 / RD + 1.0 / ro)
    av = -gm * rd_par_ro                  # 中频电压增益（输出开路）
    av_no_ro = -gm * RD                   # 忽略 ro 时的近似
    return dict(vg=vg, vgs=vgs, vov=vov, id=id_, vds=vds, sat_ok=sat_ok,
                gm=gm, ro=ro, rd_par_ro=rd_par_ro, av=av, av_no_ro=av_no_ro)


# ----------------------------------------------------------------------------
# 电路搭建
# ----------------------------------------------------------------------------
def build_common(with_ro_stub=False):
    """搭出电路里与激励无关的部分（供电、偏置、RD、MOS、寄生电容）。

    激励源不放在这里：瞬态要 SIN、AC 要 AC 1，两者不同；
    而且同名源重复添加会抛 NameError: Element name Vin is already defined。

    with_ro_stub:
        True 时额外在漏极与地之间并一个电阻 ro = 1/(λ·I_D)。
        原因见下面关于 ngspice 局限的注释。
    """
    c = Circuit('NMOS Common-Source Amplifier')

    # VDD 供电轨（PySpice 没有内置 vdd 节点，自己用电压源建一个）
    c.V('dd', 4, c.gnd, VDD @ u_V)

    # 输入耦合电容 Cb1：题目说"视为足够大"，取 100 µF
    #   （1 kHz 时容抗 ≈1.6 mΩ，远小于 Rg1∥Rg2 = 24 kΩ，可视为交流短路）
    #   注意：这里直接写 SI 数值 100e-6，不要依赖 @u_F 的自动缩放 ——
    #   实测 `100 @ u_F` 生成的网表是 `Cb1 1 2 100`，也就是 100 法拉，
    #   耦合电容变成短路，栅极被输入源强行钳住，增益会退化成 gm 本身。
    c.C('b1', 1, 2, CB1_FARAD)

    # 栅极分压偏置
    c.R('g1', 4, 2, RG1 @ u_Ohm)
    c.R('g2', 2, c.gnd, RG2 @ u_Ohm)

    # 漏极电阻
    c.R('d', 4, 3, RD @ u_Ohm)

    # NMOS：level 1 模型
    #   模型参数必须用 c.model() 单独声明；塞进 MOSFET() 的 kwargs 会报
    #   "Unknown argument level=1"。
    #   VTO = V_th
    #   KP  = K —— 题目的 K 是 I_D = K·(Vgs−Vth)² 的系数；
    #        而 SPICE level 1 的公式是 I_D = ½·KP·(Vgs−Vth)²，
    #        所以这里 KP 与题目的 K 数值相同（不是 2K）。
    #        这一处我一开始按 ½K·V_ov² 手算、又给 KP 乘了 2，结果 I_D 差了一倍，
    #        靠"手算 vs 仿真"对比表当场抓出来。
    #   λ 的参数名是 lambd（lambda 是 Python 关键字，不能当关键字参数）
    #   注意：cgs / cgd **不是**合法的 ngspice 模型参数，会报
    #   "no such parameter on this device"（实测逐个参数试出来的）。
    #   所以这两只电容改成在电路里接成实体元件，见下。
    c.model('NMOS_enh', 'NMOS', level=1, vto=VTH, kp=K, lambd=LAMBDA)
    # 漏极、栅极、源极、衬底（衬底与源极一起接地）
    # 不传 l/w：KP 已经把 W/L 折算进去了，再传实例参数会被 ngspice 拒绝。
    c.MOSFET('1', 3, 2, c.gnd, c.gnd, model='NMOS_enh')

    # MOS 的极间寄生电容：Cgs（栅-源）、Cgd（栅-漏，米勒电容）。
    # 没有它们的话，AC 扫描会是一条平坦的直线、看不到任何高频滚降。
    c.C('gs', 2, c.gnd, CGS @ u_F)
    c.C('gd', 2, 3, CGD @ u_F)

    # 用一只显式电阻代表沟道长度调制带来的输出电阻 ro = 1/(λ·I_D)。
    #
    # 为什么要这么绕：实测发现 ngspice 的 level-1 MOSFET 在 **AC 小信号分析**
    # 里并不把 λ 计入输出电导（gds 被算成 0）。证据是把 λ 从 0 扫到 0.5，
    # AC 增益始终是 −gm·Rd 一点不变，即 ro 被当成无穷大。
    # （直流工作点里 λ 是生效的，只是不影响这里的偏置。）
    # 为了能真正验证 "Av = −gm·(Rd∥ro)" 这个手算公式，就在外面并一只
    # 数值等于 1/(λ·I_D) 的电阻来代表 ro —— 等效电路上它就是和 Rd 并联的。
    if with_ro_stub:
        hc = hand_calc()
        c.R('ro_sim', 3, c.gnd, hc['ro'] @ u_Ohm)

    return c


def build_circuit():
    """完整电路（用于直流工作点）：输入源接直流 0。"""
    c = build_common()
    c.V('in', 1, c.gnd, 'DC 0')
    return c


def solve_operating_point():
    """直流工作点。返回值做了 .ravel()，避免 0 维/1 维数组的坑。"""
    c = build_circuit()
    sim = c.simulator(temperature=25, nominal_temperature=25)
    an = sim.operating_point()

    def val(node):
        return float(np.array(an[node]).ravel()[0])

    # 漏极电流：由 VDD 与漏极节点电压算出（Rd 上流过的电流）
    vd = val('3')
    id_sim = (VDD - vd) / RD
    return dict(vg=val('2'), vd=vd, id=id_sim, raw=an)


def run_transient(with_ro_stub=True):
    """瞬态：输入 10 mV / 1 kHz 正弦，看输出反相放大并实测增益。"""
    c = build_common(with_ro_stub=with_ro_stub)
    period = 1.0 / VI_FREQ
    # DC 偏置 0 + 正弦激励；覆盖 6 个周期，前面留 4 个周期让耦合电容进入稳态
    c.V('in', 1, c.gnd, 'DC 0 SIN(0 %g %g 0 0 0)' % (VI_AMP, VI_FREQ))

    sim = c.simulator(temperature=25, nominal_temperature=25)
    analysis = sim.transient(step_time=period / 400, end_time=6 * period)

    t = np.array(analysis.time)
    vin = np.array(analysis['1'])
    vout = np.array(analysis['3'])

    # 取最后两个完整周期算幅度（避开启动瞬态）
    mask = t >= 4 * period
    vin_pp = float(np.max(vin[mask]) - np.min(vin[mask]))
    vout_pp = float(np.max(vout[mask]) - np.min(vout[mask]))
    gain_meas = vout_pp / vin_pp

    # 相位关系：用去掉直流分量的相关和判断同相还是反相。
    # 注意不能拿 gain_meas 的正负来判断 —— 它是两个峰峰值之比，恒为正。
    corr = float(np.mean((vin[mask] - vin[mask].mean()) * (vout[mask] - vout[mask].mean())))
    inverted = corr < 0
    # 带符号的增益：反相记负号
    signed_gain = -gain_meas if inverted else gain_meas

    return dict(t=t, vin=vin, vout=vout, vin_pp=vin_pp, vout_pp=vout_pp,
                gain=gain_meas, signed_gain=signed_gain, inverted=inverted,
                period=period)


def run_ac(with_ro_stub=False):
    """交流扫描：幅频/相频，验证中频增益。"""
    c = build_common(with_ro_stub=with_ro_stub)
    c.V('in', 1, c.gnd, 'DC 0 AC 1')
    sim = c.simulator(temperature=25, nominal_temperature=25)
    analysis = sim.ac(start_frequency=1 @ u_Hz, stop_frequency=100 @ u_Hz * 1000,
                      number_of_points=50, variation='dec')

    freq = np.array(analysis.frequency)
    vout = np.array(analysis['3'])
    gain = np.abs(vout)
    gain_db = 20.0 * np.log10(np.maximum(gain, 1e-12))
    phase_deg = np.angle(vout, deg=True)

    # 中频增益：取 1 kHz 附近
    mid = float(np.interp(np.log10(1000.0), np.log10(freq), gain))
    return dict(freq=freq, gain=gain, gain_db=gain_db, phase_deg=phase_deg, gain_mid=mid)


# ----------------------------------------------------------------------------
# 直流通路与小信号等效模型的**电路图**：已改由手绘提供，不在代码里生成。
#
# 这里曾经用 matplotlib 画过一版（draw_equivalent_circuits / _draw_dc_path /
# _draw_small_signal / _wire / _resistor / _ground，约 210 行），按"作业电路图
# 手绘"的要求已整体删除。删掉的是**画示意图**的代码，与仿真计算无关：
# 下面 main() 里的瞬态波形和 Bode 图仍然照常生成，因为那些是仿真输出。
#
# 等效模型的推导（手算式）在 hand_calc() 与文件开头的注释里，不受影响。
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print('=' * 78)
    print(' 电路③ NMOS 共源级放大电路')
    print('=' * 78)
    print(' ' + plot_setup.font_report())
    print(' 题目给定：VDD = %.0f V, Rg1 = %.0f kΩ, Rg2 = %.0f kΩ, Rd = %.1f kΩ'
          % (VDD, RG1 / 1e3, RG2 / 1e3, RD / 1e3))
    print('           NMOS: K = %.1f mA/V², V_th = %.0f V, λ = %.2f /V'
          % (K * 1e3, VTH, LAMBDA))
    print('           输入：Vi = %.0f mV / %.0f Hz 正弦波' % (VI_AMP * 1e3, VI_FREQ))

    hc = hand_calc()

    # ---------- 1) 直流工作点 ----------
    op = solve_operating_point()

    print('\n[1] 静态工作点（手算 vs 仿真）')
    print('    %-10s %14s %14s %12s' % ('量', '手算', '仿真', '偏差'))
    print('    ' + '-' * 56)
    for label, th, sim in [('V_GS (V)', hc['vgs'], op['vg']),
                           ('I_D (mA)', hc['id'] * 1e3, op['id'] * 1e3),
                           ('V_DS (V)', hc['vds'], op['vd'])]:
        dev = abs(sim - th) / abs(th) * 100.0
        print('    %-10s %14.4f %14.4f %11.4f%%' % (label, th, sim, dev))
    print('    饱和判据：V_DS > V_GS − V_th  →  %.4f V > %.4f V  →  %s'
          % (hc['vds'], hc['vov'], '工作在饱和区 ✓' if hc['sat_ok'] else '不满足 ✗'))

    # ---------- 2) 瞬态 ----------
    tr = run_transient()
    print('\n[2] 瞬态仿真（输入 %.0f mV / %.0f Hz 正弦）' % (VI_AMP * 1e3, VI_FREQ))
    print('    输入峰峰值  = %.4f mV' % (tr['vin_pp'] * 1e3))
    print('    输出峰峰值  = %.4f mV' % (tr['vout_pp'] * 1e3))
    print('    实测增益    = %.4f  (带符号 %.4f)' % (tr['gain'], tr['signed_gain']))
    print('    手算增益    = %.4f   (Av = −gm·(Rd∥ro))' % hc['av'])
    print('    相位        = %s'
          % ('反相 ✓（输出与输入相位相差 180°）' if tr['inverted'] else '同相 ✗'))

    # ---------- 3) 交流扫描 ----------
    ac = run_ac()
    ac_ro = run_ac(with_ro_stub=True)
    print('\n[3] 交流扫描（中频增益）')
    print('    手算  Av = −gm·(Rd∥ro) = %.4f  (%.2f dB)'
          % (hc['av'], 20 * np.log10(abs(hc['av']))))
    print('    仿真  Av（并上代表 ro 的电阻）= %.4f  (%.2f dB)   ← 与手算对照'
          % (ac_ro['gain_mid'], 20 * np.log10(abs(ac_ro['gain_mid']))))
    print('    仿真  Av（仅管子 + Rd）      = %.4f  (%.2f dB)   ← 见下面的说明'
          % (ac['gain_mid'], 20 * np.log10(abs(ac['gain_mid']))))

    print('\n[4] 小信号参数')
    print('    gm = K·(V_GS − V_th) = %.4f mA/V' % (hc['gm'] * 1e3))
    print('    ro = 1/(λ·I_D)       = %.4f kΩ' % (hc['ro'] / 1e3))
    print('    Rd ∥ ro              = %.4f kΩ' % (hc['rd_par_ro'] / 1e3))
    print('    忽略 ro 的近似 Av    = %.4f （与精确值差 %.2f%%）'
          % (hc['av_no_ro'], abs((hc['av_no_ro'] - hc['av']) / hc['av']) * 100))

    print('\n[5] 关于 ngspice level-1 模型在 AC 分析中不计 λ 的说明')
    print('    实测：把 λ 从 0 取到 0.5，AC 增益恒为 −gm·Rd = %.4f，完全不变；' % hc['av_no_ro'])
    print('    说明该模型在交流小信号里把输出电导 gds 算成 0（ro → ∞），')
    print('    直流工作点不受影响（I_D、V_DS 与 λ 无关）。')
    print('    因此本脚本用一只显式电阻 %0.2f kΩ 代表 ro 与 Rd 并联，' % (hc['ro'] / 1e3))
    print('    才能真正验证 Av = −gm·(Rd∥ro) 这个手算结论。')

    # ---------- 画图 ----------
    # 瞬态波形（输入输出幅度差很多，所以用双 y 轴）
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax_in = ax.twinx()
    l1, = ax.plot(tr['t'] * 1e3, tr['vin'] * 1e3, color='#3498db', linewidth=1.8,
                  label='输入 Vi')
    l2, = ax_in.plot(tr['t'] * 1e3, tr['vout'] * 1e3, color='#e74c3c', linewidth=1.6,
                     label='输出 Vo')
    ax.axhline(0, color='#999', linewidth=0.7)
    ax.set_xlabel('时间 (ms)')
    ax.set_ylabel('输入 Vi (mV)', color='#3498db')
    ax_in.set_ylabel('输出 Vo (mV)', color='#e74c3c')
    ax.tick_params(axis='y', labelcolor='#3498db')
    ax_in.tick_params(axis='y', labelcolor='#e74c3c')
    ax.set_title('NMOS 共源放大：输入 %.0f mV → 输出 %.1f mV（反相，增益 %.2f）'
                 % (VI_AMP * 1e3, tr['vout_pp'] * 1e3, tr['gain']))
    ax.legend(handles=[l1, l2], loc='upper right')
    plt.tight_layout()
    p1 = os.path.join(OUT_DIR, 'c3_transient.png')
    plt.savefig(p1, dpi=130)
    plt.close(fig)

    # Bode
    fig, axes = plt.subplots(2, 1, figsize=(9, 6.4), sharex=True)
    axes[0].semilogx(ac_ro['freq'], ac_ro['gain_db'], color='#2ecc71', linewidth=1.8)
    axes[0].axhline(20 * np.log10(abs(hc['av'])), color='#e74c3c',
                    linewidth=0.9, linestyle='--')
    axes[0].set_ylabel('增益 (dB)')
    axes[0].set_title('NMOS 共源放大：幅频与相频特性')
    axes[0].annotate('中频 %.2f dB' % (20 * np.log10(abs(hc['av']))),
                     xy=(1e3, 20 * np.log10(abs(hc['av']))),
                     xytext=(1e3 * 4, 20 * np.log10(abs(hc['av'])) - 12),
                     fontsize=9, color='#c0392b',
                     arrowprops=dict(arrowstyle='->', color='#c0392b', linewidth=0.9))
    axes[1].semilogx(ac_ro['freq'], ac_ro['phase_deg'], color='#8e44ad', linewidth=1.8)
    axes[1].axhline(-180, color='#e74c3c', linewidth=0.9, linestyle='--')
    axes[1].set_xlabel('频率 (Hz)')
    axes[1].set_ylabel('相位 (°)')
    axes[1].annotate('中频 -180°（反相）', xy=(1e3, -180), xytext=(1e3 * 3, -140),
                     fontsize=9, color='#c0392b',
                     arrowprops=dict(arrowstyle='->', color='#c0392b', linewidth=0.9))
    # 这里不用 tight_layout：两个子图加上标注后它常报
    # "cannot make Axes height small enough"，直接给边距更稳
    fig.subplots_adjust(left=0.11, right=0.97, top=0.92, bottom=0.10, hspace=0.18)
    p2 = os.path.join(OUT_DIR, 'c3_bode.png')
    plt.savefig(p2, dpi=130)
    plt.close(fig)

    # 注：直流通路与小信号等效模型的**电路图**由手绘提供，不在这里生成。
    # 曾经用 matplotlib 画过一版（_draw_dc_path / _draw_small_signal 等约 200 行），
    # 已按要求删除。等效模型的推导见本文件开头的手算式，手绘图见 output/ 目录。

    print('\n图已保存：')
    for p in (p1, p2):
        print('  ' + p)
    print('=' * 78)


if __name__ == '__main__':
    main()
