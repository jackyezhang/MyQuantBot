"""
唐奇安通道突破  v3
════════════════════════════════════════════════════════
策略来源：Richard Donchian 通道突破系统
优化点（v2 → v3）：

【缺陷1】v2 通道高点用 series.iloc[-(CHANNEL_PERIOD+1):-1].max()，
  直接切片对 Series 是安全的，但如果 df 含有 NaN（行情缺失日），
  max() 会跳过 NaN，导致实际参考的有效天数不足 CHANNEL_PERIOD。
  → 对通道数据先 dropna()，然后取最后 CHANNEL_PERIOD 根有效数据的最高点。

【缺陷2】唐奇安通道的真正力量来自「通道高点持续时间」——
  若20日高点是3个月前创下的单日高点，突破的意义与上周创的高点完全不同。
  → 增加：近5日内通道高点应出现过至少2次（价格多次测试过该阻力位），
  说明压力位有充分「确认」，突破更有意义。

【缺陷3】VOL_MULT=1.3 以20日均量为基准，未区分「近期量能趋势」，
  若近20日本身就是放量期（如连续拉升），此均量基准偏高，导致放量标准虚高。
  → 改为：以近20日量的中位数（median）为基准，中位数对异常值更鲁棒。

【缺陷4】突破后若当日有「长上影线」（最高价显著高于收盘），
  说明突破遭遇抛压，可信度下降。
  → 增加（当有 high/low 时）：上影线长度 < K 线实体的 50%，过滤假突破尝试。

【缺陷5】唐奇安原版有两个通道：20日突破入场、10日跌破出场。
  入场时应验证「过去10日没有发生过突破后立即回落」的情况
  （即近期不存在失败突破，避免连续虚假信号）。
  → 增加：过去10日内不存在「当日突破20日高点但次日大幅回落(>1.5%)」的失败先例。
"""

import numpy as np

CHANNEL_PERIOD  = 20
TEST_DAYS       = 5     # 通道高点被测试次数的回望窗口
MIN_TESTS       = 2     # 最少测试次数
VOL_MULT        = 1.3
FAILED_BK_DAYS  = 10    # 检查失败突破的回望天数
FAILED_BK_DROP  = 0.015 # 失败突破定义：突破后次日跌幅 > 1.5%

def get_name():
    return "唐奇安通道突破"

def run(df) -> bool:
    if len(df) < CHANNEL_PERIOD + FAILED_BK_DAYS + 5:
        return False

    close  = df["close"].astype(float)
    curr_c = float(close.iloc[-1])

    # ── 通道高点（用 high 优先，dropna 处理缺失）──────────────────────
    if "high" in df.columns:
        series = df["high"].astype(float)
    else:
        series = close

    valid_series = series.dropna()
    if len(valid_series) < CHANNEL_PERIOD + 1:
        return False
    channel_data = valid_series.iloc[-(CHANNEL_PERIOD + 1):-1]
    channel_high = float(channel_data.max())

    # 1. 今日收盘突破通道高点
    if curr_c <= channel_high:
        return False

    # 2. 【新增】通道高点须被多次测试（有充分阻力确认）
    #    近 TEST_DAYS 日内，价格有 MIN_TESTS 次触及/接近通道高点（98%以上）
    recent_highs = series.iloc[-(TEST_DAYS + 1):-1]
    touch_count = int((recent_highs >= channel_high * 0.98).sum())
    if touch_count < MIN_TESTS:
        return False

    # 3. 成交量确认（以中位数为基准，更鲁棒）
    if "volume" in df.columns:
        vol = df["volume"].astype(float)
        vol_median = float(vol.iloc[-(CHANNEL_PERIOD + 1):-1].median())
        if vol_median > 0 and float(vol.iloc[-1]) < vol_median * VOL_MULT:
            return False

    # 4. 【新增】K 线质量：上影线不能过长（当有 high/open 数据时）
    if "high" in df.columns and "open" in df.columns:
        h = float(df["high"].astype(float).iloc[-1])
        o = float(df["open"].astype(float).iloc[-1])
        body = abs(curr_c - o)
        upper_shadow = h - max(curr_c, o)
        if body > 0 and upper_shadow > body * 0.5:
            return False  # 上影线过长，突破遭遇抛压

    # 5. 【新增】排除「近期失败突破」——过去 FAILED_BK_DAYS 日内不存在
    #    「当日突破通道但次日大幅回落」的先例
    hist_close = close.values
    hist_channel = series.values
    for i in range(-(FAILED_BK_DAYS + 1), -1):
        day_c   = float(hist_close[i])
        day_h   = float(hist_channel[i])
        # 该日的通道高点（需要更早的数据，简化用该日前20日高点）
        window_start = max(0, len(hist_close) + i - CHANNEL_PERIOD)
        window_end   = len(hist_close) + i
        if window_end <= window_start:
            continue
        past_ch = float(np.max(hist_channel[window_start:window_end]))
        # 若该日曾突破历史高点，但次日大幅回落
        next_c = float(hist_close[i + 1]) if i + 1 < 0 else float(hist_close[-1])
        if day_c > past_ch and day_c > 0:
            next_drop = (next_c - day_c) / day_c
            if next_drop < -FAILED_BK_DROP:
                return False   # 近期有失败突破记录，当前突破可信度降低

    return True


if __name__ == "__main__":
    import pandas as pd

    np.random.seed(42)
    n = 60
    high_arr  = np.linspace(10, 12.5, n) + np.random.rand(n) * 0.2
    low_arr   = high_arr - np.random.uniform(0.15, 0.35, n)
    close_arr = (high_arr + low_arr) / 2
    open_arr  = close_arr - np.random.uniform(-0.05, 0.05, n)

    # 最近5日内，价格多次接近历史高点（多次测试阻力位）
    hist_max = float(high_arr[:-5].max())
    for i in range(-5, -1):
        high_arr[i]  = hist_max * np.random.uniform(0.985, 0.998)
        close_arr[i] = high_arr[i] - 0.1

    # 突破日：大实体阳线+放量
    high_arr[-1]  = hist_max + 0.4
    close_arr[-1] = high_arr[-1] - 0.05
    open_arr[-1]  = close_arr[-1] - 0.25   # 小上影线

    vol_arr = np.random.uniform(1e7, 3e7, n)
    vol_arr[-1] = float(np.median(vol_arr[-21:-1])) * 2.0

    df = pd.DataFrame({"open": open_arr, "high": high_arr,
                        "low": low_arr, "close": close_arr, "volume": vol_arr})
    print(f"唐奇安通道突破 信号: {run(df)}")
