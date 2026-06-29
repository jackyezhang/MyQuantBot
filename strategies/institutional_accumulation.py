"""
主力吸筹形态  v2
════════════════════════════════════════════════════════
策略来源：Richard Wyckoff「威科夫市场周期」+ 缩量横盘理论
优化点（v1 → v2）：

【缺陷1】箱体振幅用 (max-min)/min 计算，min 是最低收盘价而非箱体下沿锚点，
  在吸筹期价格漂移时会误判振幅。
  → 改为 (max-min)/((max+min)/2) 中值归一化，更稳健。

【缺陷2】VOL_SHRINK 比较「前5日均量 vs 后5日均量」，
  若吸筹期首日恰好放量（如主力试盘），会导致比值失真。
  → 改为拟合吸筹期成交量的线性回归斜率为负（量在持续萎缩），更鲁棒。

【缺陷3】突破日「量比」以「吸筹期均量」为基准，吸筹期本身是低量阶段，
  导致阈值虚低，弱放量也能通过。
  → 基准改为吸筹期前 N 日的「正常量」（吸筹前的市场均量），更真实。

【缺陷4】未检查吸筹期箱体前是否有下跌——Wyckoff 要求吸筹出现在「下跌末端」，
  若横盘出现在高位则是「派发」而非「吸筹」，性质完全相反。
  → 增加：吸筹期前 15 日内有明显下跌（跌幅 > 阈值），确认底部吸筹背景。

【缺陷5】突破日涨幅上限 9.5% 允许次日追板，实际上主力拉升首日 3-6% 最健康。
  → 上限收窄至 0.075，减少追板风险。
"""

import numpy as np

ACCUM_DAYS      = 10      # 吸筹期观察天数
PRE_ACCUM_DAYS  = 15      # 吸筹期前用于估算「正常量」的天数
DECLINE_WINDOW  = 20      # 检查前置下跌的回望窗口
MIN_DECLINE     = 0.08    # 吸筹前需有 8% 以上跌幅（确认底部背景）
MAX_RANGE       = 0.06    # 吸筹期箱体振幅上限（中值归一化）
BREAK_VOL       = 2.0     # 突破日量比（相对正常量）
BREAK_LOW       = 0.02    # 突破日涨幅下限
BREAK_HIGH      = 0.075   # 突破日涨幅上限（收窄，降低追板风险）

MIN_BARS = ACCUM_DAYS + PRE_ACCUM_DAYS + DECLINE_WINDOW + 5

def get_name():
    return "主力吸筹突破"

def _linear_slope(arr):
    """返回 arr 的线性回归斜率（正=量在增加，负=量在萎缩）"""
    n = len(arr)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    x -= x.mean()
    y = np.array(arr, dtype=float)
    y -= y.mean()
    denom = (x * x).sum()
    return float((x * y).sum() / denom) if denom != 0 else 0.0

def run(df) -> bool:
    if len(df) < MIN_BARS:
        return False

    close = df["close"].astype(float)
    volume = None
    for col in ("volume", "vol"):
        if col in df.columns:
            volume = df[col].astype(float)
            break
    if volume is None:
        return False

    # ── 今日数据 ──────────────────────────────────────────────────────
    curr_c = close.iloc[-1]
    prev_c = close.iloc[-2]
    if prev_c == 0:
        return False
    today_chg = (curr_c - prev_c) / prev_c

    # ── Phase 2：突破日过滤 ───────────────────────────────────────────
    if not (BREAK_LOW < today_chg < BREAK_HIGH):
        return False

    # ── 吸筹期数据（不含今日）────────────────────────────────────────
    accum_close = close.iloc[-(ACCUM_DAYS + 1):-1]
    accum_vol   = volume.iloc[-(ACCUM_DAYS + 1):-1]

    accum_max = float(accum_close.max())
    accum_min = float(accum_close.min())
    accum_mid = (accum_max + accum_min) / 2
    if accum_mid == 0:
        return False

    # 1. 箱体振幅（中值归一化）< MAX_RANGE
    box_range = (accum_max - accum_min) / accum_mid
    if box_range > MAX_RANGE:
        return False

    # 2. 今日收盘突破箱体上沿
    if curr_c <= accum_max:
        return False

    # 3. 吸筹期量能持续萎缩（线性回归斜率为负）
    slope = _linear_slope(accum_vol.values)
    if slope >= 0:
        return False  # 量未萎缩

    # 4. 突破日量比（以吸筹期前 PRE_ACCUM_DAYS 日正常量为基准）
    normal_vol_start = -(ACCUM_DAYS + 1 + PRE_ACCUM_DAYS)
    normal_vol_end   = -(ACCUM_DAYS + 1)
    normal_vol = volume.iloc[normal_vol_start:normal_vol_end].mean()
    if normal_vol == 0:
        return False
    if volume.iloc[-1] / normal_vol < BREAK_VOL:
        return False

    # 5. 【新增】前置下跌确认：吸筹期开始前 DECLINE_WINDOW 日内有明显下跌
    pre_start = -(ACCUM_DAYS + 1 + DECLINE_WINDOW)
    pre_end   = -(ACCUM_DAYS + 1)
    pre_close = close.iloc[pre_start:pre_end]
    pre_high  = float(pre_close.max())
    pre_end_val = float(pre_close.iloc[-1])
    if pre_high == 0:
        return False
    prior_decline = (pre_high - pre_end_val) / pre_high
    if prior_decline < MIN_DECLINE:
        return False  # 横盘前没有明显下跌，可能是高位派发，非底部吸筹

    return True


if __name__ == "__main__":
    import pandas as pd

    rng = np.random.RandomState(7)
    # 前期铺垫（不影响检测窗口）
    early = list(11.0 + rng.randn(20) * 0.10)
    early_vol = list(rng.uniform(4e7, 5e7, 20))
    # 下跌段（20日内跌幅约19%）
    decline = list(np.linspace(13.0, 10.5, 20) + rng.randn(20) * 0.04)
    decline_vol = list(rng.uniform(3e7, 5e7, 20))
    # 吸筹期（10日窄幅横盘，量持续萎缩）
    anchor = decline[-1]
    accum_close, accum_vol = [], []
    for i in range(10):
        accum_close.append(round(anchor + rng.uniform(-0.12, 0.12), 2))
        accum_vol.append(2.2e7 - i * 1.3e6)
    # 突破日：涨5.5%，成交量约正常量2.5倍
    break_c = round(accum_close[-1] * 1.055, 2)
    normal_vol_mean = np.mean(early_vol + decline_vol)
    break_v = normal_vol_mean * 2.5
    all_c = early + decline + accum_close + [break_c]
    all_v = early_vol + decline_vol + accum_vol + [break_v]
    df = pd.DataFrame({"close": all_c, "volume": all_v})
    print(f"主力吸筹突破 信号: {run(df)}")    # 预期 True
