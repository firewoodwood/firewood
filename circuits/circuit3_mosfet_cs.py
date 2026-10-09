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

手算（详见正文推导）：题目给了 λ = 0.02 /V，所以要用含沟道长度调制的精确式
    V_G  = 5 × 40/(60+40) = 2 V
    V_GS = V_G                      （源极接地）
    V_OV = V_GS − V_th = 1 V
    I_D  = ½·K·V_OV²·(1 + λ·V_DS)   （饱和区，与 V_DS = VDD − I_D·Rd 联立解）
    V_DS = VDD − I_D·Rd
    饱和判据：V_DS > V_GS − V_th
    gm   = K·V_OV·(1 + λ·V_DS)
    gds  = ∂I_D/∂V_DS = λ·½K·V_OV² = λ·I_D/(1 + λ·V_DS)
    ro   = 1/gds = (1 + λ·V_DS)/(λ·I_D)
    Av   = −gm·(Rd ∥ ro)

  注意 ro：**不能**用教材上那个 ro = 1/(λ·I_D)。它漏掉了上面 gds 里的
  (1 + λ·V_DS) 因子（等价于把 λ 算两次），本题会让 ro 偏小 8.27%。

    （教材常见的 I_D = ½·K·V_OV²、gm = K·V_OV 是忽略 λ 的一阶近似，
      脚本里也一并算出来做对照。）

本脚本做：
    1) 直流工作点仿真，与手算的 V_GS / I_D / V_DS 对比，并判断是否饱和
    2) 瞬态仿真：输入 10 mV/1 kHz 正弦，看输出波形（反相放大），实测增益
    3) 交流扫描：幅频/相频，验证中频增益与手算一致

注意：直流通路与小信号等效模型的**电路图**按要求由手绘提供，
本脚本不再生成（曾经用 matplotlib 画过一版，约 210 行，已删除）。

运行： python circuit3_mosfet_cs.py
输出： 控制台对比表 + PNG（瞬态波形 c3_transient.png、Bode 图 c3_bode.png）
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
K = 0.8e-3           # A/V²   (0.8 mA/V²)，即 I_D = ½·K·(V_GS − V_th)² 中的系数
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
    """按题目要求手算静态工作点与增益。

    题目给了 λ = 0.02 /V，所以**必须把它算进去**：level-1 模型在饱和区的电流是
        I_D = ½·K·V_ov²·(1 + λ·V_DS)

    把 V_DS = VDD − I_D·Rd 代进去，含 I_D 的项可以合并，得到的是一个**一次方程**
    （不是二次 —— 一开始我按二次去解，取错了根，算出的 I_D 差了 17%）：

        I_D·(1 + ½K·V_ov²·λ·Rd) = ½K·V_ov²·(1 + λ·VDD)

        =>  I_D = ½K·V_ov²·(1 + λ·VDD) / (1 + ½K·V_ov²·λ·Rd)

    代入本题参数：0.4mA×1.1 / (1 + 0.4mA×0.02×2k) = 0.433071 mA，
    V_DS = 5 − 0.433071mA×2k = 4.133858 V，与仿真完全一致。

    说明：常见的教材写法 I_D = ½K·V_ov² 是**忽略 λ 的一阶近似**，本题因为给了
    具体的 λ，用精确式才能和仿真对上。下面把两种都算出来，方便对照。
    """
    vg = VDD * RG2 / (RG1 + RG2)          # 分压
    vgs = vg                              # 源极接地
    vov = vgs - VTH                       # 过驱动电压

    # --- 精确解：含 (1 + λ·V_DS) ---
    #   I_D = ½K·V_ov²·(1 + λ·VDD) / (1 + ½K·V_ov²·λ·Rd)
    base = 0.5 * K * vov ** 2
    id_exact = base * (1 + LAMBDA * VDD) / (1 + base * LAMBDA * RD)
    vds_exact = VDD - id_exact * RD
    # 注意：定出 V_DS 之后，gm 也要跟着带上 (1 + λ·V_DS)
    #   gm = ∂I_D/∂V_GS = K·V_ov·(1 + λ·V_DS)
    gm_exact = K * vov * (1 + LAMBDA * vds_exact)
    # 小信号输出电阻：对 V_DS 求导得到 gds，注意**不能**直接用 1/(λ·I_D)。
    #   I_D = ½K·V_ov²·(1 + λ·V_DS)
    #   gds = ∂I_D/∂V_DS = ½K·V_ov²·λ = λ·I_D / (1 + λ·V_DS)
    # 用 1/(λ·I_D) 等于把 λ 算了两次，会漏掉 (1 + λ·V_DS) 这个因子
    # （本题是 1.0827，即 ro 偏小 8.27%、Av 偏小 0.13%）。
    base_for_gds = 0.5 * K * vov ** 2          # 不含 λ 的那部分
    gds_exact = LAMBDA * base_for_gds
    ro_exact = 1.0 / gds_exact
    rd_par_ro_exact = 1.0 / (1.0 / RD + 1.0 / ro_exact)
    av_exact = -gm_exact * rd_par_ro_exact

    # --- 一阶近似：忽略 λ（教材常见写法），用来对照 ---
    id_approx = 0.5 * K * vov ** 2
    vds_approx = VDD - id_approx * RD
    gm_approx = K * vov
    # 一阶近似下同样要对 V_DS 求导拿 gds，而不是套 1/(λ·I_D)
    ro_approx = 1.0 / (LAMBDA * 0.5 * K * vov ** 2)
    rd_par_ro_approx = 1.0 / (1.0 / RD + 1.0 / ro_approx)
    av_approx = -gm_approx * rd_par_ro_approx

    sat_ok = vds_exact > vov              # 饱和判据 V_DS > V_GS − V_th
    av_no_ro = -gm_exact * RD             # 再忽略 ro 的近似

    return dict(vg=vg, vgs=vgs, vov=vov, sat_ok=sat_ok,
                # 精确解（与仿真对比用这一组）
                id=id_exact, vds=vds_exact, gm=gm_exact, ro=ro_exact,
                rd_par_ro=rd_par_ro_exact, av=av_exact, av_no_ro=av_no_ro,
                # 一阶近似（忽略 λ）
                id_approx=id_approx, vds_approx=vds_approx, gm_approx=gm_approx,
                ro_approx=ro_approx, rd_par_ro_approx=rd_par_ro_approx,
                av_approx=av_approx)


# ----------------------------------------------------------------------------
# 电路搭建
# ----------------------------------------------------------------------------
def build_common():
    """搭出电路里与激励无关的部分（供电、偏置、RD、MOS、寄生电容）。

    激励源不放在这里：瞬态要 SIN、AC 要 AC 1，两者不同；
    而且同名源重复添加会抛 NameError: Element name Vin is already defined。
    """
    c = Circuit('NMOS Common-Source Amplifier')

    # VDD 供电轨（PySpice 没有内置 vdd 节点，自己用电压源建一个）
    c.V('dd', 4, c.gnd, VDD @ u_V)

    # 输入耦合电容 Cb1：题目说"视为足够大"，取 100 µF
    #   （1 kHz 时容抗 = 1/(2π×1k×100µ) ≈ 1.59 Ω，远小于 Rg1∥Rg2 = 24 kΩ，可视为交流短路）
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
    #   λ 的参数名必须写完整单词 lambda。**写 lambd 不会报错，但会被静默忽略**，
    #   仿真里的管子实际 λ=0 —— 这一点实测确认过：固定 Vgs=2V/Vds=4.2V，
    #   写 lambd=0.02 与完全不写 λ 得到的 I_D 都是 0.400000 mA；写 lambda=0.02
    #   才得到 0.433600 mA = 0.4×(1+0.02×4.2)。
    #   lambda 是 Python 关键字，不能直接当关键字参数，但可以用 dict 展开绕过：
    #   c.model(..., **{'lambda': LAMBDA})
    #   注意：cgs / cgd **不是**合法的 ngspice 模型参数，会报
    #   "no such parameter on this device"（实测逐个参数试出来的）。
    #   所以这两只电容改成在电路里接成实体元件，见下。
    c.model('NMOS_enh', 'NMOS', level=1, vto=VTH, kp=K, **{'lambda': LAMBDA})
    # 漏极、栅极、源极、衬底（衬底与源极一起接地）
    # 不传 l/w：KP 已经把 W/L 折算进去了，再传实例参数会被 ngspice 拒绝。
    c.MOSFET('1', 3, 2, c.gnd, c.gnd, model='NMOS_enh')

    # MOS 的极间寄生电容：Cgs（栅-源）、Cgd（栅-漏）。
    # 没有它们的话，AC 扫描会是一条平坦的直线、看不到任何高频滚降。
    #
    # 关于高频滚降的来源（这里改过一次说法）：**不是** Cgd 的米勒效应。
    # 本电路的栅极由理想电压源经 100 µF 直接驱动，源阻抗≈0，米勒效应需要
    # 一个非零的源阻抗才会显现。实测依据：去掉 Cgd 后 100 MHz 内完全没有滚降；
    # 去掉 Cgs 后 −3 dB 点完全不变（仍是 36.03 MHz）；把源端串上 100 kΩ
    # （这才真的构成米勒）−3 dB 立刻掉到 0.26 MHz。
    # 所以这里的滚降是**输出极点** 1/(2π(Rd∥ro)·Cgd) ≈ 20.2 MHz 与
    # **前馈零点** gm/(2π·Cgd) ≈ 34.5 MHz 共同作用的结果，合起来约 36.2 MHz。
    c.C('gs', 2, c.gnd, CGS @ u_F)
    c.C('gd', 2, 3, CGD @ u_F)

    # 这里原先并过一只"代表 ro"的电阻（值取手算的 1/(λ·I_D)），
    # 依据是当时以为"ngspice 的 level-1 在 AC 里把 gds 当成 0"。
    # 那个判断是错的：真正的原因是模型参数名写成了 lambd、被静默忽略，
    # 于是 λ=0、gds=0。参数名改对之后模型自带 ro，这只电阻等于**重复计入**，
    # 实测会把手算本该吻合的增益从 1.7050 拉到 1.6743，所以删掉。
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


def run_transient():
    """瞬态：输入 10 mV / 1 kHz 正弦，看输出反相放大并实测增益。"""
    c = build_common()
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


def run_ac():
    """交流扫描：幅频/相频，验证中频增益。"""
    c = build_common()
    c.V('in', 1, c.gnd, 'DC 0 AC 1')
    sim = c.simulator(temperature=25, nominal_temperature=25)
    # 频段取 10 Hz ~ 100 MHz：低频端能看到输入耦合电容带来的高通效应
    # （Cb1=100µF 配 Rg1∥Rg2=24kΩ，拐点约 0.066 Hz，所以 10 Hz 已经接近平坦），
    # 高频端能看到 Cgd 的米勒效应造成的滚降。
    # 原先只扫到 100 kHz，结果整条曲线在图上几乎是平的、看不出任何趋势。
    analysis = sim.ac(start_frequency=10 @ u_Hz, stop_frequency=100 @ u_Hz * 1e6,
                      number_of_points=20, variation='dec')

    freq = np.array(analysis.frequency)
    vout = np.array(analysis['3'])
    gain = np.abs(vout)
    gain_db = 20.0 * np.log10(np.maximum(gain, 1e-12))
    # 相位要"展开"：反相放大器的相位落在 −180° 附近，而 np.angle 的值域是
    # (−180°, 180°]，相位穿过 −180° 时会从 −179.9° 跳到 +179.9°，画出来就是
    # 一条竖线 —— 看着像相位突变，其实只是绕圈。展开后才是连续的物理曲线：
    # 低频约 −179.6°（实测 10 Hz）→ 中频 −180° → 高频继续朝 −180° 以下走。
    phase_deg = np.degrees(np.unwrap(np.angle(vout)))

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
    print('\n[3] 交流扫描（中频增益）')
    print('    手算  Av = −gm·(Rd∥ro) = %.4f  (%.2f dB)'
          % (hc['av'], 20 * np.log10(abs(hc['av']))))
    print('    仿真  Av（管子 + Rd）  = %.4f  (%.2f dB)'
          % (ac['gain_mid'], 20 * np.log10(abs(ac['gain_mid']))))
    dev_av = abs(abs(ac['gain_mid']) - abs(hc['av'])) / abs(hc['av']) * 100
    print('    偏差 = %.4f%%   ← ro 由模型自己提供（λ 已生效），无需外接电阻'
          % dev_av)

    print('\n[4] 小信号参数')
    print('    gm = K·(V_GS − V_th) = %.4f mA/V' % (hc['gm'] * 1e3))
    print('    gds = λ·½K·V_ov²     = %.4f µS   （对 V_DS 求导，与 V_DS 无关）'
          % (LAMBDA * 0.5 * K * hc['vov'] ** 2 * 1e6))
    print('    ro  = 1/gds          = %.4f kΩ' % (hc['ro'] / 1e3))
    print('    Rd ∥ ro              = %.4f kΩ' % (hc['rd_par_ro'] / 1e3))
    print('    忽略 ro 的近似 Av    = %.4f （与精确值差 %.2f%%）'
          % (hc['av_no_ro'], abs((hc['av_no_ro'] - hc['av']) / hc['av']) * 100))

    print('\n[5] 关于 λ 与 ro')
    print('    level-1 模型饱和区电流是 I_D = ½·K·V_ov²·(1 + λ·V_DS)，λ 直接进直流工作点；')
    print('    AC 小信号里它照常提供 gds。注意 gds = ∂I_D/∂V_DS = λ·½K·V_ov²，')
    print('    **不是** λ·I_D —— 后者把 λ 算了两次，会漏掉 (1 + λ·V_DS) 因子，')
    print('    本题偏小 8.27%%。正确值 ro = %.2f kΩ（不是 115.45 kΩ）。' % (hc['ro'] / 1e3))
    print('    所以 ro 不需要外接电阻来代表 —— 早先版本这么做，是因为模型参数名')
    print('    写成了 lambd，被 ngspice 静默忽略（不报错），实际 λ=0、gds=0。')
    print('    这一点是拿探针实测出来的：固定 Vgs=2V/Vds=4.2V，写 lambd=0.02 与')
    print('    完全不写 λ，I_D 都是 0.400000 mA；写 lambda=0.02 才得到 0.433600 mA。')

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
    axes[0].semilogx(ac['freq'], ac['gain_db'], color='#2ecc71', linewidth=1.8)
    axes[0].axhline(20 * np.log10(abs(hc['av'])), color='#e74c3c',
                    linewidth=0.9, linestyle='--')
    axes[0].set_ylabel('增益 (dB)')
    axes[0].set_title('NMOS 共源放大：幅频与相频特性')
    axes[0].annotate('中频 %.2f dB' % (20 * np.log10(abs(hc['av']))),
                     xy=(1e3, 20 * np.log10(abs(hc['av']))),
                     xytext=(3e3, 20 * np.log10(abs(hc['av'])) - 3.0),
                     fontsize=9, color='#c0392b',
                     arrowprops=dict(arrowstyle='->', color='#c0392b', linewidth=0.9))
    axes[1].semilogx(ac['freq'], ac['phase_deg'], color='#8e44ad', linewidth=1.8)
    axes[1].axhline(-180, color='#e74c3c', linewidth=0.9, linestyle='--')
    axes[1].set_xlabel('频率 (Hz)')
    axes[1].set_ylabel('相位 (°)')
    # 标注放在相位子图【内部】偏右上。原来写的是 y = −140（在 −180 线之上），
    # 而这条图的纵轴上限就是 −175 左右，文字会跑到轴外、箭头拖出一条长线。
    axes[1].annotate('中频 −180°（反相）', xy=(1e3, -180), xytext=(3e4, -198),
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
