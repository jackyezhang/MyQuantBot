"""
布林带超卖反弹  v3
════════════════════════════════════════════════════════
策略来源：John Bollinger「布林带」超卖反弹
优化点（v2 → v3）：

【缺陷1】v2 只检查「昨日 < 下轨，今日 >= 下轨」单次穿越，
  在持续下跌中，每次短暂反弹都会触发信号（N形持续下跌逐级打出新低）。
  → 增加「反弹幅度确认」：今日收盘须高于昨日收盘 >= X%，
  且今日是阳线（收盘 > 开盘或前收），确认是真实反弹而非小幅收复。

【缺陷2】MA60 趋势过滤只要「ma60.iloc[-1] > ma60.iloc[-5]」，
  5日斜率太短，中期下跌中的周线级别反弹完全可以通过此过滤。
  → 改为双重均线过滤：MA60 方向（20日斜率）+ MA60 本身须 > MA120
  （确认长期趋势向上，不是在熊市中逆势接刀）。

【缺陷3】布林带下轨触碰后应检查「跌破下轨的深度」——
  轻微触碰（昨收仅低于下轨 0.1%）与深度超卖（低于下轨 2%+）的反弹意义完全不同。
  → 增加：昨日收盘须低于下轨至少 0.5%（有实质超卖），过滤边缘噪声触碰。

【缺陷4】成交量门槛 VOL_MULT=1.2 没有区分「反弹日量」与「跌破日量」——
  Wyckoff 认为「止跌反弹的量应小于此前恐慌抛售的量」（弹性反弹），
  若反弹量 > 抛售量，可能是主力对倒或套牢盘解套抛压。
  → 增加：今日量 < 最近5日最大量 × 0.9（反弹量不能创近期新高）。

【缺陷5】布林带宽度（Bandwidth）未被利用——
  真正的超卖反弹通常发生在布林带收窄后的扩张初期，
  若带宽本身很小，下轨突破可能只是正常波动。
  → 增加：布林带宽度（(upper-lower)/middle）> 最近20日均值，
  确认当前波动率高于正常水平（真实超卖，非低波动率假突破）。
"""

import numpy as np

BOLL_PERIOD     = 20
BOLL_STD        = 2.0
VOL_MULT        = 1.2
OVERSOLD_DEPTH  = 0.005   # 昨日须低于下轨至少 0.5%
MIN_BOUNCE_PCT  = 0.005   # 今日反弹涨幅下限（0.5%）
MA_SHORT        = 60
MA_LONG         = 120

def get_name():
    return "布林带超卖反弹"

def run(df) -> bool:
    need = BOLL_PERIOD + MA_LONG + 25
    if len(df) < need:
        return False

    close = df["close"].astype(float)

    ma20   = close.rolling(BOLL_PERIOD).mean()
    std20  = close.rolling(BOLL_PERIOD).std(ddof=1)
    upper  = ma20 + BOLL_STD * std20
    lower  = ma20 - BOLL_STD * std20

    curr_c  = float(close.iloc[-1])
    prev_c  = float(close.iloc[-2])
    lower_prev = float(lower.iloc[-2])
    lower_curr = float(lower.iloc[-1])
    upper_curr = float(upper.iloc[-1])
    mid_curr   = float(ma20.iloc[-1])

    if mid_curr == 0 or lower_curr == 0:
        return False

    # 1. 昨日须有实质超卖深度（低于下轨至少 OVERSOLD_DEPTH）
    if prev_c >= lower_prev * (1 - OVERSOLD_DEPTH):
        return False

    # 2. 反弹形态：今日收盘回到下轨上方
    if curr_c < lower_curr:
        return False

    # 3. 反弹幅度确认（今日真实阳线，有实质弹力）
    if prev_c == 0:
        return False
    bounce_pct = (curr_c - prev_c) / prev_c
    if bounce_pct < MIN_BOUNCE_PCT:
        return False

    # 4. 成交量确认：反弹需要量能，但不超过近期恐慌量
    if "volume" in df.columns:
        vol = df["volume"].astype(float)
        vol_avg5  = float(vol.iloc[-6:-1].mean())
        vol_curr  = float(vol.iloc[-1])
        vol_max5  = float(vol.iloc[-6:-1].max())   # 近5日最大量（恐慌日）

        if vol_avg5 > 0 and vol_curr < vol_avg5 * VOL_MULT:
            return False  # 量能不足

        # 反弹量不应超过恐慌量（避免对倒或套牢解套）
        if vol_curr > vol_max5 * 0.9:
            return False

    # 5. 【优化】长期趋势双重过滤：MA60 > MA120 且 MA60 近20日斜率向上
    ma60  = close.rolling(MA_SHORT).mean()
    ma120 = close.rolling(MA_LONG).mean()
    ma60_curr  = float(ma60.iloc[-1])
    ma120_curr = float(ma120.iloc[-1])
    ma60_20d   = float(ma60.iloc[-21])

    if ma60_curr != ma60_curr or ma120_curr != ma120_curr:  # NaN
        return False
    if ma60_curr < ma120_curr:
        return False   # 长期趋势向下，不做逆势
    if ma60_curr <= ma60_20d:
        return False   # MA60 近20日斜率向下

    # 6. 【新增】布林带宽度须高于正常水平（真实超卖，非低波动率误触）
    bandwidth_curr = (upper_curr - lower_curr) / mid_curr
    bw_series = ((upper - lower) / ma20).dropna()
    if len(bw_series) < 21:
        return False
    bw_avg20 = float(bw_series.iloc[-21:-1].mean())
    if bandwidth_curr <= bw_avg20:
        return False  # 当前带宽未扩张，超卖可信度低

    return True


if __name__ == "__main__":
    import pandas as pd

    np.random.seed(42)
    n = 220
    crash_bar = 175

    # 长期上涨趋势（保证 MA60 > MA120）
    close_arr = np.linspace(8.0, 18.0, n) + np.random.randn(n) * 0.25
    vol_arr   = np.ones(n) * 2.2e7

    # 恐慌日：跌破布林下轨 1.8%
    s = pd.Series(close_arr)
    lower_s = s.rolling(BOLL_PERIOD).mean() - BOLL_STD * s.rolling(BOLL_PERIOD).std(ddof=1)
    close_arr[crash_bar]     = float(lower_s.iloc[crash_bar - 1]) * 0.982
    vol_arr[crash_bar]       = 6e7   # 恐慌抛售大量

    # 反弹日（信号日）：收盘回到下轨上方，量能充足但不超过恐慌量
    s2      = pd.Series(close_arr)
    lower2  = s2.rolling(BOLL_PERIOD).mean() - BOLL_STD * s2.rolling(BOLL_PERIOD).std(ddof=1)
    close_arr[crash_bar + 1] = max(float(lower2.iloc[crash_bar + 1]) * 1.012,
                                   close_arr[crash_bar - 1] * 0.995)
    vol_arr[crash_bar + 1]   = 4.0e7  # 反弹量 > 均量×1.2 且 < 恐慌量×0.9

    df = pd.DataFrame({"close": close_arr[:crash_bar + 2],
                       "volume": vol_arr[:crash_bar + 2]})
    print(f"布林带超卖反弹 信号: {run(df)}")    # 预期 True
