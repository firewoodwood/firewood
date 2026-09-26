"""
一键跑完三个电路（题目要求三个都要做、都要交）
================================================================================

用法：
    python run_all.py

依次执行：
    电路① RC 低通滤波        →  τ、fc、相移的「手算 vs 仿真」对比
    电路② 验证戴维南定理      →  V_oc / I_sc / R_th + 接负载后的等效性对比
    电路③ NMOS 共源放大       →  静态工作点、增益的「手算 vs 仿真」对比

每个脚本都会把自己的 PNG 图写进 output/ 目录。
"""

import runpy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = [
    ('电路① RC 低通滤波电路', 'circuit1_rc_lowpass.py'),
    ('电路② 验证戴维南定理', 'circuit2_thevenin.py'),
    ('电路③ NMOS 共源级放大电路', 'circuit3_mosfet_cs.py'),
]


def main():
    # 让脚本能 import 同目录下的 plot_setup
    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    ok = []
    for title, filename in SCRIPTS:
        path = os.path.join(HERE, filename)
        print('\n' + '#' * 78)
        print('# ' + title)
        print('#' * 78)
        try:
            # run_path 会在独立命名空间里执行脚本，等价于直接 python 该文件
            runpy.run_path(path, run_name='__main__')
            ok.append((title, True))
        except Exception as exc:                       # noqa: BLE001
            print('!! 执行失败: %s' % exc)
            ok.append((title, False))

    print('\n' + '=' * 78)
    print(' 汇总')
    print('=' * 78)
    for title, passed in ok:
        print('  %s  %s' % ('✓' if passed else '✗', title))
    print('=' * 78)
    return 0 if all(p for _, p in ok) else 1


if __name__ == '__main__':
    sys.exit(main())
