"""
华尔街趋势突破  v3
════════════════════════════════════════════════════════
在 v2 基础上的进一步优化：

【缺陷1】MA20 斜率只检查「ma20.iloc[-1] > ma20.iloc[-3]」，
  2根K线斜率在盘整期噪声很大，假阳性高。
  → 改为：MA20 近5日斜率为正（5日变化量），同时 MA20 自身须在近20日均值上方。

【缺陷2】量比以「前5日均量」为分母，5日太短，容易被前几日的异常放量拉高基准，
  导致今日正常放量被误判为「不及标准」。
  → 改为：今日量 > 过去20日均量 × VOL_RATIO（20日基准更稳定），
  同时今日量 > 昨日量（量在递增，不是孤量）。

【缺陷3】CHANGE_LOW = 0.03（3%）涨幅下限过低，
  MA20 已经向上+量比达标时 3% 涨幅依然可能是日内随机波动。
  → 提高到 0.04，并增加「今日 K 线实体 > 60%」过滤（大实体阳线，非上影线假突破）。

【缺陷4】未验证突破位的「历史阻力确认」——
  真正的有效突破往往在突破前有过多次测试（价格曾经在该价位附近反弹失败）。
  → 增加：今日收盘须突破过去50日内曾被测试过至少2次的阻力位
  （近似实现：close 突破过去 50 日内最高收盘价 × 0.995，即接近历史高点）。

【缺陷5】v2 中 df.get("volume", df.get("vol")) 在 df 不含这两列时返回 None，
  但未处理 volume 为全零序列的边界情况。
  → 增加零值保护和类型安全检查。
"""

import numpy as np

MA_PERIOD    = 20
MA_LONG      = 50     # 用于阻力位验证
VOL_PERIOD   = 20     # 量比基准改为20日
VOL_RATIO    = 1.5
CHANGE_LOW   = 0.04
CHANGE_HIGH  = 0.095
MIN_BODY_PCT = 0.60   # 今日 K 线实体占高低差的比例（需有 high/low）

def get_name():
    return "华尔街趋势突破"

def run(df) -> bool:
    if len(df) < MA_LONG + VOL_PERIOD + 5:
        return False

    close = df["close"].astype(float)

    # ── 量能数据 ──────────────────────────────────────────────────────
    volume = None
    for col in ("volume", "vol"):
        if col in df.columns:
            vol_candidate = df[col].astype(float)
            if float(vol_candidate.iloc[-1]) > 0:
                volume = vol_candidate
            break
    if volume is None:
        return False

    # ── 涨幅计算 ──────────────────────────────────────────────────────
    prev_c = float(close.iloc[-2])
    curr_c = float(close.iloc[-1])
    if prev_c == 0:
        return False
    change = (curr_c - prev_c) / prev_c
    if not (CHANGE_LOW < change < CHANGE_HIGH):
        return False

    # ── K 线实体过滤（大实体阳线，非长上影线假突破）───────────────────
    if "high" in df.columns and "low" in df.columns:
        h = float(df["high"].astype(float).iloc[-1])
        l = float(df["low"].astype(float).iloc[-1])
        o = float(df["open"].astype(float).iloc[-1]) if "open" in df.columns else prev_c
        candle_range = h - l
        body = abs(curr_c - o)
        if candle_range > 0 and body / candle_range < MIN_BODY_PCT:
            return False  # 实体占比不足，可能是长影线假突破

    # ── MA20 趋势 ─────────────────────────────────────────────────────
    ma20 = close.rolling(MA_PERIOD).mean()
    ma20_curr = float(ma20.iloc[-1])
    if curr_c <= ma20_curr:
        return False

    # MA20 近5日斜率（百分比）
    ma20_5d_ago = float(ma20.iloc[-6])
    if ma20_5d_ago == 0 or ma20_curr <= ma20_5d_ago:
        return False

    # MA20 自身须高于其近20日均值（MA20 在上行通道中，而非顶部反转）
    ma20_of_ma20 = float(ma20.iloc[-21:-1].mean())
    if ma20_curr <= ma20_of_ma20:
        return False

    # ── 量比确认（20日基准）──────────────────────────────────────────
    vol_avg_20 = float(volume.iloc[-(VOL_PERIOD + 1):-1].mean())
    if vol_avg_20 == 0:
        return False
    if float(volume.iloc[-1]) < vol_avg_20 * VOL_RATIO:
        return False

    # 今日量 > 昨日量（量在递增）
    if float(volume.iloc[-1]) <= float(volume.iloc[-2]):
        return False

    # ── 【新增】阻力位突破确认 ────────────────────────────────────────
    # 今日收盘须突破过去 MA_LONG 日内的高位收盘区（取前50日最高收盘的 99.5%）
    hist_high_50 = float(close.iloc[-(MA_LONG + 1):-1].max())
    if curr_c < hist_high_50 * 0.995:
        return False  # 未触及历史压力位，不构成有效突破

    return True


if __name__ == "__main__":
    import pandas as pd

    np.random.seed(42)
    n = 90
    # 构造：整体上涨趋势，最后一日放量突破前高
    close_arr = np.linspace(9, 11.5, n) + np.random.randn(n) * 0.08
    high_arr  = close_arr + np.random.uniform(0.05, 0.15, n)
    low_arr   = close_arr - np.random.uniform(0.05, 0.15, n)
    open_arr  = close_arr - np.random.uniform(-0.05, 0.05, n)

    # 最后一日：大实体阳线突破
    close_arr[-1] = close_arr[-2] * 1.055
    open_arr[-1]  = close_arr[-2] * 1.01
    high_arr[-1]  = close_arr[-1] * 1.005
    low_arr[-1]   = open_arr[-1] * 0.998

    vol_arr = np.random.uniform(1e7, 2e7, n)
    vol_arr[-1] = float(vol_arr[-6:-1].mean()) * 2.0

    df = pd.DataFrame({"open": open_arr, "high": high_arr,
                        "low": low_arr, "close": close_arr, "volume": vol_arr})
    print(f"华尔街趋势突破 信号: {run(df)}")
