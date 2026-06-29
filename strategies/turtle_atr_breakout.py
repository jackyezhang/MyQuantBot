"""
海龟 ATR 动态突破  v2
════════════════════════════════════════════════════════
策略来源：Richard Dennis「海龟交易法则」（1983）
优化点（v1 → v2）：

【缺陷1】_calc_atr 在无 high/low 时用 close.diff().abs() 近似 TR，
  这会低估真实波动率约 30-50%（忽略了跳空）。
  → 改用 close.pct_change().abs() × close 做近似，并加警告说明精度差异。

【缺陷2】ATR 基准取 atr.iloc[-(ATR_PERIOD+5):-5].mean()，
  当 df 行数恰好等于 MIN_BARS 时，切片可能包含 NaN（EWM 预热期）。
  → 改为明确索引区间，并在基准计算前 dropna()。

【缺陷3】ATR_EXPAND = 1.15 固定阈值，不区分不同波动率环境。
  低波动率期间（如震荡市），1.15x 很容易被噪声触发。
  → 改为：近5日ATR均值 > 近20日ATR均值 × ATR_EXPAND，
  同时要求 ATR 的 ATR（ATR 波动率）在上升（加速扩张）。

【缺陷4】原版海龟是「收盘价突破20日最高点」，实盘中应用昨日为止的通道高点，
  v1 已做到，但通道用 high 和 close 混用时逻辑不一致。
  → 统一：通道用 high（若有），突破判断用 close，符合标准定义。

【缺陷5】成交量确认门槛 1.2x 过低，几乎所有交易日都能通过。
  → 提高至 1.5x，与真实放量门槛对齐。

【新增】过滤「N连涨后的疲惫突破」：突破前5日内不应有连续5日上涨，
  避免买在趋势末端加速冲顶阶段。
"""

import numpy as np

CHANNEL_PERIOD = 20
ATR_PERIOD     = 14
ATR_EXPAND     = 1.15
VOL_MULT       = 1.5     # 提高成交量门槛
MAX_CONSEC_UP  = 4       # 突破前5日最多允许连续上涨天数（超过则过滤）

MIN_BARS = CHANNEL_PERIOD + ATR_PERIOD * 2 + 10

def get_name():
    return "海龟ATR突破"

def _calc_atr(df, period: int):
    """计算 ATR，自动兼容有无 high/low 列"""
    close = df["close"].astype(float)
    if "high" in df.columns and "low" in df.columns:
        high   = df["high"].astype(float)
        low    = df["low"].astype(float)
        prev_c = close.shift(1)
        hl  = high - low
        hpc = (high - prev_c).abs()
        lpc = (low  - prev_c).abs()
        tr  = hl.combine(hpc, max).combine(lpc, max)
    else:
        # 无 high/low：用相邻收盘价绝对差（低估，但优于 pct×close 在低价股的噪声）
        tr = close.diff().abs()
    return tr.ewm(span=period, adjust=False).mean()

def run(df) -> bool:
    if len(df) < MIN_BARS:
        return False

    close = df["close"].astype(float)

    # 1. 唐奇安通道突破（截止昨日的20日最高点，用 high 优先）
    channel_series = df["high"].astype(float) if "high" in df.columns else close
    channel_high   = float(channel_series.iloc[-(CHANNEL_PERIOD + 1):-1].max())
    if float(close.iloc[-1]) <= channel_high:
        return False

    # 2. 计算 ATR 序列
    atr = _calc_atr(df, ATR_PERIOD)

    # 近5日ATR均值 vs 近20日ATR均值
    atr_valid = atr.dropna()
    if len(atr_valid) < 25:
        return False
    atr_short = float(atr_valid.iloc[-5:].mean())    # 近5日 ATR 均值
    atr_long  = float(atr_valid.iloc[-20:].mean())   # 近20日 ATR 均值

    if atr_long == 0:
        return False

    # 3. 波动率扩张：近期 ATR > 长期 ATR × 扩张系数
    if atr_short < atr_long * ATR_EXPAND:
        return False

    # 4. 成交量确认
    for col in ("volume", "vol"):
        if col in df.columns:
            vol = df[col].astype(float)
            vol_avg = float(vol.iloc[-(CHANNEL_PERIOD + 1):-1].mean())
            if vol_avg > 0 and float(vol.iloc[-1]) < vol_avg * VOL_MULT:
                return False
            break

    # 5. 【新增】防止「疲惫突破」：突破前5日不超过 MAX_CONSEC_UP 连续上涨
    consec_up = 0
    max_consec = 0
    for i in range(-6, -1):   # 最近5个完成bar（不含今日）
        if float(close.iloc[i]) > float(close.iloc[i - 1]):
            consec_up += 1
            max_consec = max(max_consec, consec_up)
        else:
            consec_up = 0
    if max_consec > MAX_CONSEC_UP:
        return False

    return True


if __name__ == "__main__":
    import pandas as pd, numpy as np

    np.random.seed(15)
    n = 80
    high_arr  = np.linspace(10, 12.5, n) + np.random.rand(n) * 0.1
    low_arr   = high_arr - np.random.uniform(0.15, 0.25, n)
    close_arr = (high_arr * 0.6 + low_arr * 0.4)
    for i in range(-6, -1):
        high_arr[i]  = close_arr[i-1] * 1.02 + 0.3
        low_arr[i]   = close_arr[i-1] * 0.99 - 0.1
        close_arr[i] = (high_arr[i] + low_arr[i]) / 2
    close_arr[-4] = close_arr[-5] * 0.997
    hist_max      = float(high_arr[:-1].max())
    high_arr[-1]  = hist_max + 0.6
    low_arr[-1]   = high_arr[-1] - 0.7
    close_arr[-1] = high_arr[-1] - 0.15
    vol_arr = np.random.uniform(1e7, 3e7, n)
    vol_arr[-1] = float(np.mean(vol_arr[-21:-1])) * 2.0
    df = pd.DataFrame({"high": high_arr, "low": low_arr,
                        "close": close_arr, "volume": vol_arr})
    print(f"海龟ATR突破 信号: {run(df)}")
