"""
MACD 零轴共振金叉  v2
════════════════════════════════════════════════════════
策略来源：Jesse Livermore 趋势跟踪 + Gerald Appel MACD 理论
优化点（v1 → v2）：

【缺陷1】条件3「bar_prev <= 0 且 bar_curr > 0」是金叉首日确认，
  但这个条件与条件1（金叉）在数学上几乎等价（DIF穿越DEA即bar变号），
  实际上没有增加额外过滤信息，属于冗余条件。
  → 替换为真正有价值的过滤：「DIF 当前斜率 > 0 且加速上行」，
  即 dif_curr > dif_prev > dif_prev_prev（DIF 连续2日改善），
  确认动能不是单日脉冲而是持续恢复。

【缺陷2】零轴上方金叉信号在震荡市中（DIF 在零轴附近反复穿越）噪声极大。
  → 增加：DIF 必须在零轴上方至少保持连续 N 日（避免刚刚穿越零轴的弱势金叉）。
  DIF 连续5日 > 0，确认是真正的多头区域，而非勉强翻正。

【缺陷3】DEA 当前值虽然 > 0，但若 DEA 斜率为负（DEA 还在下行），
  说明中期趋势仍在恶化，此时金叉只是技术反弹而非趋势翻转。
  → 增加：DEA 斜率必须 > 0（DEA 本身在上行，中期趋势向好）。

【缺陷4】策略未考虑回调幅度——最强的零轴金叉应发生在「小幅回调后」，
  即金叉前的回调中 DIF 最低值不应低于 -DEA_DAMP（跌破零轴太深说明趋势已破坏）。
  → 增加：金叉前回调期间（DEA开始下行到金叉日），DIF 最低值 > 合理下限。
"""

import numpy as np

EMA_FAST    = 12
EMA_SLOW    = 26
EMA_SIGNAL  = 9
DIF_ABOVE0_MIN_DAYS = 5   # DIF 需连续在零轴上方的天数
MIN_BARS    = EMA_SLOW + EMA_SIGNAL + DIF_ABOVE0_MIN_DAYS + 10

def get_name():
    return "MACD零轴金叉"

def run(df) -> bool:
    if len(df) < MIN_BARS:
        return False

    close = df["close"].astype(float)

    # ── 标准 MACD 计算 ───────────────────────────────────────────────
    ema_fast  = close.ewm(span=EMA_FAST,   adjust=False).mean()
    ema_slow  = close.ewm(span=EMA_SLOW,   adjust=False).mean()
    dif       = ema_fast - ema_slow
    dea       = dif.ewm(span=EMA_SIGNAL,   adjust=False).mean()

    dif_vals = dif.values
    dea_vals = dea.values

    # NaN 检查
    for v in [dif_vals[-1], dif_vals[-2], dif_vals[-3],
              dea_vals[-1], dea_vals[-2]]:
        if v != v:
            return False

    dif_curr  = float(dif_vals[-1])
    dif_prev  = float(dif_vals[-2])
    dif_prev2 = float(dif_vals[-3])
    dea_curr  = float(dea_vals[-1])
    dea_prev  = float(dea_vals[-2])

    # 1. 金叉：昨 DIF < DEA，今 DIF > DEA
    if not (dif_prev < float(dea_vals[-2]) and dif_curr > dea_curr):
        return False

    # 2. 零轴上方共振（DIF 和 DEA 均在0轴上方）
    if dif_curr <= 0 or dea_curr <= 0:
        return False

    # 3. 【优化】DIF 连续2日改善（确认动能持续恢复，非单日脉冲）
    #    dif_prev2 → dif_prev → dif_curr 应递增（或至少后两者递增且 prev > prev2）
    if not (dif_curr > dif_prev and dif_prev > dif_prev2):
        return False

    # 4. 【新增】DIF 连续 DIF_ABOVE0_MIN_DAYS 日在零轴上方（剔除弱势翻正）
    lookback_dif = dif_vals[-(DIF_ABOVE0_MIN_DAYS + 1):-1]  # 不含今日
    if any(v <= 0 for v in lookback_dif):
        return False

    # 5. 【新增】DEA 斜率向上（中期趋势在改善，不是继续恶化中的反弹）
    if dea_curr <= dea_prev:
        return False

    # 6. 【新增】金叉前回调期间 DIF 未大幅跌破——
    #    取前20日内 DIF 的最低值，要求不低于 -(dea_curr * 0.3)
    #    （允许小幅回调，但不能深度下探，否则趋势已破坏）
    dif_recent_min = float(np.min(dif_vals[-21:-1]))
    if dif_recent_min < -(abs(dea_curr) * 0.3):
        return False

    return True


if __name__ == "__main__":
    import pandas as pd

    n = 180
    close = np.zeros(n)
    for i in range(100):      close[i] = 10 + i * 0.08
    for i in range(100, 115): close[i] = close[99] - (i-99) * 0.04   # 浅幅回调
    for i in range(115, 130): close[i] = close[114] + (i-114) * 0.02  # 横盘
    for i in range(130, n):   close[i] = close[129] + (i-129) * 0.25  # 加速拉升
    # 信号在第131根K线触发（DIF连续3日改善 + 金叉 + 均在零轴上方）
    df = pd.DataFrame({"close": close[:131]})
    print(f"MACD零轴金叉 信号: {run(df)}")    # 预期 True
