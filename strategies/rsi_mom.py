"""
RSI 动量稳健  v3
════════════════════════════════════════════════════════
策略来源：Welles Wilder「RSI 相对强弱指数」
优化点（v2 → v3）：

【缺陷1】RSI 区间 52-68 筛选「健康多头」，但未验证 RSI 的动量方向——
  RSI=65 可能是从 70 下行（动量衰减）或从 55 上行（动量上升），
  性质完全不同，前者是卖出信号，后者才是买入信号。
  → 增加：RSI 当前值 > RSI 3日前的值（RSI 本身在上升），确认动量加速。

【缺陷2】MA20 斜率用「ma20.iloc[-1] > ma20.iloc[-3]」（2根K线），
  跟 alpha_break.py 同样问题——窗口太短，假阳性高。
  → 改为 MA20 近5日斜率（百分比），并加最低斜率下限。

【缺陷3】RSI 动量策略核心要避开「超买回落」区间，
  但 RSI < 68 只排除了顶部，未检验「是否刚从超买区回落」。
  → 增加：过去5日内 RSI 最高值不超过 75（从高位回落的动量策略风险极大）。

【缺陷4】RSI 动量策略需要结合「价格突破确认」——
  RSI 在健康区间不代表价格结构良好，可能是震荡中的随机 RSI。
  → 增加：今日收盘 > 过去10日均价（价格在短期均线上方，结构向好）。

【缺陷5】avg_loss.replace(0, float("nan")) 在 avg_loss=0 时会得到 NaN，
  这会导致 RSI=100（完全强势），在这种边界情况下应该如何处理？
  → 明确处理：若 avg_loss == 0，RSI = 100，直接检查是否在有效区间。
  同时增加 NaN 级联保护。
"""

import numpy as np

RSI_PERIOD      = 14
RSI_LOW         = 52
RSI_HIGH        = 68
RSI_MAX_RECENT  = 75    # 过去5日 RSI 最高值不超过此值（未从高位回落）
MA_PERIOD       = 20
MIN_MA_SLOPE    = 0.001 # MA20 百分比斜率下限（每5日最低涨幅）
MA10_PERIOD     = 10    # 短期均价参考

def get_name():
    return "RSI动量稳健"

def run(df) -> bool:
    if len(df) < RSI_PERIOD + MA_PERIOD + MA10_PERIOD + 10:
        return False

    close = df["close"].astype(float)

    # ── 标准 Wilder RSI ──────────────────────────────────────────────
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()

    # 边界处理：avg_loss == 0 → RSI = 100
    avg_loss_safe = avg_loss.replace(0, np.nan)
    rs  = avg_gain / avg_loss_safe
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(100)  # avg_loss=0 时 RSI=100

    rsi_curr = float(rsi.iloc[-1])
    rsi_3d   = float(rsi.iloc[-4])   # 3日前

    # NaN 保护
    if rsi_curr != rsi_curr or rsi_3d != rsi_3d:
        return False

    # 1. RSI 在健康多头区间
    if not (RSI_LOW < rsi_curr < RSI_HIGH):
        return False

    # 2. 【新增】RSI 自身在上升（动量方向确认）
    if rsi_curr <= rsi_3d:
        return False

    # 3. 【新增】过去5日 RSI 未曾超买（排除从高位回落的衰减动量）
    rsi_max5 = float(rsi.iloc[-6:-1].max())
    if rsi_max5 >= RSI_MAX_RECENT:
        return False

    # 4. 趋势过滤：MA20 向上倾斜（百分比斜率 + 下限）
    ma20      = close.rolling(MA_PERIOD).mean()
    ma20_curr = float(ma20.iloc[-1])
    ma20_5d   = float(ma20.iloc[-6])
    if ma20_curr != ma20_curr or ma20_5d != ma20_5d:
        return False
    if ma20_5d == 0:
        return False
    ma20_slope = (ma20_curr - ma20_5d) / ma20_5d
    if ma20_slope < MIN_MA_SLOPE:
        return False

    # 5. 【新增】价格须在10日均价上方（短期价格结构向好）
    ma10_curr = float(close.rolling(MA10_PERIOD).mean().iloc[-1])
    if ma10_curr != ma10_curr:
        return False
    if float(close.iloc[-1]) <= ma10_curr:
        return False

    return True


if __name__ == "__main__":
    import pandas as pd

    np.random.seed(17)
    n = 80
    # 构造：持续温和上涨，RSI 保持在健康动量区间，未曾超买
    # 线性增长 + 小幅随机扰动，保证 RSI 在 55-65 之间稳步上行
    close_arr = 10 + np.linspace(0, 3, n) + np.random.randn(n) * 0.10
    df = pd.DataFrame({"close": close_arr})
    print(f"RSI动量稳健 信号: {run(df)}")
