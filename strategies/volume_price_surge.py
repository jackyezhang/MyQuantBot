"""
量价齐升启动  v2
════════════════════════════════════════════════════════
策略来源：William O'Neil「CANSLIM」量价理论 + 威廉姆斯筹码分析
优化点（v1 → v2）：

【缺陷1】「收盘价创20日新高」用 close.iloc[-(LOOKBACK+1):-1]，
  这实际上取的是前21根到前1根，包含今日之前20根的最高收盘——
  但 LOOKBACK=20 时，若总行数恰好等于 MIN_BARS，可能包含 NaN 值。
  → 改用 rolling(LOOKBACK).max().iloc[-2]（截止昨日），语义更清晰安全。

【缺陷2】「连续3日量价齐增」从今日往前数，包含了今日，
  但今日数据可能是实时行情（未收盘），应从昨日往前确认 CONSEC_DAYS 日，
  今日单独作为信号触发日判断。
  → 将连续量价验证改为：过去 CONSEC_DAYS 日（不含今日），
  同时今日须满足：涨幅 > 0 且量 > 前一日量。

【缺陷3】O'Neil CANSLIM 核心是「突破前整理期成交量极度萎缩」（Dry-up），
  原策略完全没有检验整理期缩量，缺少买点质量区分。
  → 增加：突破前5日成交量（不含今日）须低于20日均量（整理缩量确认）。

【缺陷4】仅看价格新高，未验证「筹码换手充分」——
  O'Neil 强调启动前必须经历足够的洗盘/换手，
  原策略用线性上涨数据构造会误判为已换手。
  → 增加：20日内须有至少2个交易日跌幅 > 1%（有过小幅回调，筹码结构更健康）。

【缺陷5】MAX_CHANGE = 0.095 允许接近涨停的追板，风险极高。
  → 收窄至 0.08，给止损留出空间。
"""

import numpy as np

LOOKBACK       = 20
CONSEC_DAYS    = 3
MAX_CHANGE     = 0.08    # 收窄上限
DRY_UP_RATIO   = 0.85    # 突破前5日均量须 < 20日均量 × 比例（整理缩量）
MIN_PULLBACKS  = 2       # 20日内至少须有几次小幅回调（> 1%跌幅）

MIN_BARS = LOOKBACK + CONSEC_DAYS + 5

def get_name():
    return "量价齐升启动"

def run(df) -> bool:
    if len(df) < MIN_BARS:
        return False

    close  = df["close"].astype(float)
    volume = None
    for col in ("volume", "vol"):
        if col in df.columns:
            volume = df[col].astype(float)
            break
    if volume is None:
        return False

    curr_c = float(close.iloc[-1])
    prev_c = float(close.iloc[-2])
    if prev_c == 0:
        return False
    today_chg = (curr_c - prev_c) / prev_c

    # 0. 今日涨幅在合理区间
    if not (0 < today_chg < MAX_CHANGE):
        return False

    # 1. 今日收盘价创 LOOKBACK 日新高（截止昨日）
    hist_high = float(close.rolling(LOOKBACK).max().iloc[-2])
    if curr_c <= hist_high:
        return False

    # 2. 今日成交量创 LOOKBACK 日新高（截止昨日）
    hist_vol_high = float(volume.rolling(LOOKBACK).max().iloc[-2])
    if float(volume.iloc[-1]) <= hist_vol_high:
        return False

    # 3. 今日量价同步放大
    if float(volume.iloc[-1]) <= float(volume.iloc[-2]):
        return False

    # 4. 过去 CONSEC_DAYS 日（不含今日）连续量价同步递增
    for i in range(2, CONSEC_DAYS + 2):
        c_today = float(close.iloc[-i])
        c_yest  = float(close.iloc[-i - 1])
        v_today = float(volume.iloc[-i])
        v_yest  = float(volume.iloc[-i - 1])
        if c_today <= c_yest or v_today <= v_yest:
            return False

    # 5. 【新增】突破前5日整理缩量（Dry-up 确认）
    pre_vol_5   = float(volume.iloc[-6:-1].mean())   # 突破前5日均量
    base_vol_20 = float(volume.iloc[-21:-1].mean())  # 20日基准均量
    if base_vol_20 == 0:
        return False
    if pre_vol_5 > base_vol_20 * DRY_UP_RATIO:
        return False  # 整理期未缩量，启动质量差

    # 6. 【新增】近20日内有足够次数的小幅回调（筹码换手健康）
    lookback_close = close.iloc[-21:-1]
    daily_chg = lookback_close.pct_change().dropna()
    pullback_days = int((daily_chg < -0.01).sum())
    if pullback_days < MIN_PULLBACKS:
        return False

    return True


if __name__ == "__main__":
    import pandas as pd, numpy as np

    np.random.seed(42)
    # 基础段：高量能（5e7-7e7），含2次有效回调
    n_base = 25
    closes = list(np.linspace(8, 9.0, n_base))
    volumes = list(np.random.uniform(5e7, 7e7, n_base))
    closes.append(closes[-1] * 0.981); volumes.append(5e7)           # 回调1
    for i in range(3): closes.append(closes[-1]*1.005); volumes.append(5.5e7)
    closes.append(closes[-1] * 0.979); volumes.append(5.2e7)          # 回调2
    for i in range(2): closes.append(closes[-1]*1.006); volumes.append(5.3e7)
    # 突破前5日：价涨量增但绝对量低于基础段（整理缩量确认）
    for i in range(5):
        closes.append(closes[-1] * (1 + 0.008 + i*0.001))
        volumes.append(1.5e7 + i * 0.3e7)
    # 信号日：突破20日新高+成交量新高
    closes.append(closes[-1] * 1.049)
    volumes.append(9e7)
    df = pd.DataFrame({"close": closes, "volume": volumes})
    print(f"量价齐升启动 信号: {run(df)}")
