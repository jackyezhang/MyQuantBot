"""
均线彩虹多头排列  v2
════════════════════════════════════════════════════════
策略来源：Stan Weinstein「Stage Analysis」阶段分析法
优化点（v1 → v2）：

【缺陷1】斜率用「当前值 - N日前值」的绝对量，不同价格区间的股票斜率不可比。
  → 改为 (ema_now - ema_n_days_ago) / ema_n_days_ago，用百分比斜率标准化。

【缺陷2】条件4「EMA5斜率 > EMA20斜率」是趋势加速的必要条件，
  但缺少「斜率需达到最低动能阈值」，导致极缓慢上涨也能通过。
  → 增加 EMA5 斜率绝对下限（年化涨幅折算），过滤龟速慢牛。

【缺陷3】PERIODS = [5,10,20,60]，相邻均线差距在高价股上很小，
  EMA5 vs EMA10 经常仅差几分钱，稍有震荡就排列破坏。
  → 增加「相邻均线间距 > 最低间距阈值」过滤，要求彩虹有实质分层。

【缺陷4】Weinstein Stage 2 还要求 MA30（原版30周均线）本身创近期新高，
  本版缺少「均线自身处于历史高位」的确认。
  → 增加 EMA60 当前值 > EMA60 回望期内均值（确认是均线上行，非顶部）。

【缺陷5】策略未考虑市场整体环境——熊市中个股均线彩虹形态失败率极高。
  → 增加可选的「价格在250日均线上方」过滤（Weinstein 核心要求之一）。
"""

import numpy as np

PERIODS        = [5, 10, 20, 60]
USE_MA250      = True     # 开启250日均线市场环境过滤
SLOPE_LOOKBACK = 5        # 斜率回望天数
MIN_SLOPE5_PCT = 0.0015   # EMA5 最低斜率（每根K线均价涨幅下限）
MIN_SPACING    = 0.002    # 相邻均线最低间距（占均线值的比例）

MIN_BARS = 250 + SLOPE_LOOKBACK + 3 if USE_MA250 else max(PERIODS) + SLOPE_LOOKBACK + 3

def get_name():
    return "均线彩虹多头"

def run(df) -> bool:
    if len(df) < MIN_BARS:
        return False

    close = df["close"].astype(float)
    curr  = float(close.iloc[-1])

    # ── 计算各均线 ────────────────────────────────────────────────────
    emas   = {}
    slopes = {}
    for p in PERIODS:
        em = close.ewm(span=p, adjust=False).mean()
        ema_now  = float(em.iloc[-1])
        ema_prev = float(em.iloc[-(SLOPE_LOOKBACK + 1)])
        if ema_now != ema_now or ema_prev != ema_prev:  # NaN
            return False
        emas[p]   = ema_now
        # 百分比斜率（消除价格量纲）
        slopes[p] = (ema_now - ema_prev) / ema_prev if ema_prev != 0 else 0.0

    # 1. 价格站在所有均线上方
    if any(curr <= emas[p] for p in PERIODS):
        return False

    # 2. 均线彩虹排列：EMA5 > EMA10 > EMA20 > EMA60
    vals = [emas[p] for p in PERIODS]
    for i in range(len(vals) - 1):
        if vals[i] <= vals[i + 1]:
            return False

    # 3. 相邻均线间距足够（有实质分层，非紧贴状态）
    for i in range(len(PERIODS) - 1):
        spacing = (emas[PERIODS[i]] - emas[PERIODS[i+1]]) / emas[PERIODS[i+1]]
        if spacing < MIN_SPACING:
            return False

    # 4. 所有均线向上倾斜
    if any(slopes[p] <= 0 for p in PERIODS):
        return False

    # 5. EMA5 斜率超过最低动能阈值（过滤无效缓涨）
    if slopes[5] < MIN_SLOPE5_PCT:
        return False

    # 6. 短期斜率 > 中期斜率（趋势加速）—— 百分比斜率比较更公平
    if slopes[5] <= slopes[20]:
        return False

    # 7. 【新增】EMA60 当前值 > EMA60 近20日均值（均线本身在爬升，非顶部）
    em60 = close.ewm(span=60, adjust=False).mean()
    em60_recent_avg = float(em60.iloc[-21:-1].mean())
    if emas[60] <= em60_recent_avg:
        return False

    # 8. 【新增】250日均线：价格在长期均线上方（Weinstein Stage 2 核心要求）
    if USE_MA250:
        ma250 = float(close.rolling(250).mean().iloc[-1])
        if ma250 != ma250:  # NaN
            return False
        if curr <= ma250:
            return False

    return True


if __name__ == "__main__":
    import pandas as pd, numpy as np
    np.random.seed(9)
    n = 350
    # 需要足够长度让 EMA60 和 MA250 均线充分预热
    t = np.arange(n)
    close_arr = 8 + 0.038 * t + np.random.randn(n) * 0.04
    df = pd.DataFrame({"close": close_arr})
    print(f"均线彩虹多头 信号: {run(df)}")
