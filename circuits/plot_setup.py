"""
出图统一配置（被三个电路脚本共用）
================================================================================

要解决三件事：

1) **中文字体**：matplotlib 自带的 DejaVu Sans 没有 CJK 字形，中文标题会变成
   一串 "Glyph xxxxx missing from font(s)" 警告，图上则是方框。这里按优先级
   在 Windows 常见中文字体里挑一个可用的。
2) **无界面后端**：这台机器没有图形界面，必须用 Agg，否则 plt.show() 会挂住。
3) **负号**：换字体后默认的 Unicode 负号（U+2212）可能缺失，要关掉。

三个电路脚本都 `import plot_setup`，保证出图风格一致。
"""

import warnings

import matplotlib
matplotlib.use('Agg')          # 必须在 pyplot 之前设置
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 常见中文字体，按优先级尝试
_CJK_CANDIDATES = [
    'Microsoft YaHei', 'Microsoft YaHei UI',   # Win10/11 默认中文界面字体
    'SimHei',                                   # 黑体
    'SimSun',                                   # 宋体
    'Noto Sans CJK SC', 'Source Han Sans SC',   # 跨平台备选
    'PingFang SC', 'Heiti SC',                  # macOS
]


def _pick_cjk_font():
    """返回系统里第一个可用的中文字体名；都没有则返回 None。"""
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CJK_CANDIDATES:
        if name in available:
            return name
    return None


CJK_FONT = _pick_cjk_font()

if CJK_FONT:
    plt.rcParams['font.sans-serif'] = [CJK_FONT, 'DejaVu Sans']
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['axes.unicode_minus'] = False   # 用 ASCII 负号，避免字形缺失
else:
    # 没有中文字体时，把这类警告压掉，免得刷屏；图上的中文会是方框
    warnings.filterwarnings('ignore', message='Glyph .* missing from font')

# 统一风格
plt.rcParams.update({
    'figure.facecolor': 'white',
    'axes.grid': True,
    'grid.alpha': 0.3,
    'axes.titlesize': 12,
    'axes.labelsize': 10,
    'legend.fontsize': 9,
})


def font_report():
    """给脚本打印一行字体选择结果，方便确认中文能不能正常显示。"""
    if CJK_FONT:
        return '中文字体: %s' % CJK_FONT
    return '中文字体: 未找到中文字体，图中中文可能显示为方框'
