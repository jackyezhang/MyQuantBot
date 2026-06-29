"""
scorer.py  —  动态评分引擎 v2
==============================
变化：
  - WEIGHT / COEF_FN 全部从 strategy_registry 读取，scorer 自身不再硬编码
  - 新增 generic_coef（通用系数）和各策略专属系数函数，供注册表引用
  - 对外接口不变：dynamic_base_score() / score_detail()

评分结构（满分 ~100）
─────────────────────
策略层（上限 75）= Σ weight_i × coef_i(kline)
K线质量层（上限 25）= Q1量比 + Q2动量 + Q3均线 + Q4共振

注意：scorer.py 不直接 import strategy_registry，
      避免循环引用。WEIGHT / COEF_FN 由外部注入（见底部）。
"""

# ── 强度系数边界 ────────────────────────────────────────────────────────
COEF_MIN = 0.60
COEF_MAX = 1.40

# 由 strategy_registry 在模块末尾注入，scorer 内部通过这两个变量工作
_WEIGHT:  dict = {}
_COEF_FN: dict = {}


def _inject(weight: dict, coef_fn: dict):
    """由 strategy_registry.py 调用，注入配置（避免循环 import）"""
    global _WEIGHT, _COEF_FN
    _WEIGHT  = weight
    _COEF_FN = coef_fn


def _clamp(v: float, lo: float = COEF_MIN, hi: float = COEF_MAX) -> float:
    return max(lo, min(hi, v))


# ════════════════════════════════════════════════════════════════════════
#  通用系数函数（新策略未精调时的兜底）
# ════════════════════════════════════════════════════════════════════════

def generic_coef(kline: dict) -> float:
    """
    通用强度系数：量比 + 今日涨幅，适合大多数趋势类策略。
    精调时替换为专属函数。
    """
    score = 1.0
    vr  = kline.get("vol_ratio") or 0
    chg = kline.get("chg1") or 0
    score += 0.05 * min(vr, 4)     # 量比每 +1x 加 0.05，上限 4x
    score += 0.03 * min(chg, 5)    # 涨幅每 +1% 加 0.03，上限 5%
    if chg <= 0:
        score -= 0.20
    return _clamp(score)


# ════════════════════════════════════════════════════════════════════════
#  各策略专属系数函数（公开命名，供注册表 import）
# ════════════════════════════════════════════════════════════════════════

def coef_alpha_break(kline: dict) -> float:
    """华尔街趋势突破：量比 + 涨幅位置 + MA 排列"""
    score = 1.0
    vr = kline.get("vol_ratio") or 0
    if   vr >= 5.0: score += 0.25
    elif vr >= 3.0: score += 0.15
    elif vr >= 1.5: score += 0.05
    else:           score -= 0.15

    chg = kline.get("chg1") or 0
    if   5.0 <= chg <= 7.5:                    score += 0.15
    elif 3.5 <= chg < 5.0 or 7.5 < chg <= 9.0: score += 0.05
    elif chg < 3.0 or chg > 9.5:               score -= 0.20

    ma5 = kline.get("ma5") or 0
    ma20 = kline.get("ma20") or 0
    if ma5 > 0 and ma20 > 0:
        gap = (ma5 - ma20) / ma20 * 100
        if   gap >= 3: score += 0.10
        elif gap >= 1: score += 0.05
        elif gap < 0:  score -= 0.15

    return _clamp(score)


def coef_donchian(kline: dict) -> float:
    """唐奇安通道突破：5日涨幅延续性 + 放量确认"""
    score = 1.0
    chg5 = kline.get("chg5") or 0
    if   chg5 >= 15: score += 0.25
    elif chg5 >= 8:  score += 0.15
    elif chg5 >= 3:  score += 0.05
    elif chg5 < 0:   score -= 0.20

    vr = kline.get("vol_ratio") or 0
    if   vr >= 3.0: score += 0.15
    elif vr >= 1.5: score += 0.05
    else:           score -= 0.10

    return _clamp(score)


def coef_rsi_mom(kline: dict) -> float:
    """RSI动量稳健：偏好温和涨幅，过热反而降分"""
    score = 1.0
    chg = kline.get("chg1") or 0
    if   1.5 <= chg <= 4.5: score += 0.20
    elif 0   <  chg <  1.5: score += 0.05
    elif chg > 7:            score -= 0.15
    elif chg <= 0:           score -= 0.25

    ma5  = kline.get("ma5")  or 0
    ma20 = kline.get("ma20") or 0
    if ma5 > 0 and ma20 > 0 and ma5 > ma20:
        score += 0.10

    return _clamp(score)


def coef_bollinger(kline: dict) -> float:
    """布林带超卖反弹：反弹力度 + 量能确认"""
    score = 1.0
    chg = kline.get("chg1") or 0
    if   chg >= 5: score += 0.25
    elif chg >= 2: score += 0.10
    elif chg <= 0: score -= 0.25

    vr = kline.get("vol_ratio") or 0
    if   vr >= 2.0: score += 0.15
    elif vr >= 1.2: score += 0.05
    else:           score -= 0.10

    return _clamp(score)


# ════════════════════════════════════════════════════════════════════════
#  K线综合质量分（0~25）
# ════════════════════════════════════════════════════════════════════════

def _kline_quality_score(kline: dict, signals: list) -> float:
    q = 0.0

    # Q1 量比质量（0~8）
    vr = kline.get("vol_ratio") or 0
    if   vr >= 8:   q += 8
    elif vr >= 5:   q += 6
    elif vr >= 3:   q += 4
    elif vr >= 1.5: q += 2
    elif vr >= 1.0: q += 1

    # Q2 价格动量（0~7）
    chg1 = kline.get("chg1") or 0
    chg5 = kline.get("chg5") or 0
    if   5 <= chg1 <= 9: q += 3
    elif 2 <= chg1 <  5: q += 1.5
    elif chg1 > 9:       q += 1      # 过热
    if   chg5 >= 15: q += 4
    elif chg5 >= 8:  q += 2.5
    elif chg5 >= 3:  q += 1
    elif chg5 <  0:  q -= 1

    # Q3 均线排列（0~5）
    ma5   = kline.get("ma5")   or 0
    ma20  = kline.get("ma20")  or 0
    price = kline.get("price") or 0
    if ma5 > 0 and ma20 > 0 and price > 0:
        if price > ma5 > ma20:
            q += 3
            gap = (ma5 - ma20) / ma20 * 100
            if   gap >= 3: q += 2
            elif gap >= 1: q += 1
        elif price > ma5:
            q += 1

    # Q4 多策略共振奖励（0~5）
    n = len(signals)
    if   n >= 4: q += 5
    elif n >= 3: q += 3
    elif n >= 2: q += 1

    return min(q, 25.0)


# ════════════════════════════════════════════════════════════════════════
#  对外接口
# ════════════════════════════════════════════════════════════════════════

def dynamic_base_score(signals: list, kline: dict) -> int:
    """计算动态基础分（0~100）"""
    strategy_score = 0.0
    for sig in signals:
        base_w  = _WEIGHT.get(sig, 0)
        coef_fn = _COEF_FN.get(sig, generic_coef)
        strategy_score += base_w * (coef_fn(kline) if kline else 1.0)

    quality_score  = _kline_quality_score(kline, signals) if kline else 0.0
    strategy_score = min(strategy_score, 75.0)
    return int(round(strategy_score + quality_score))


def score_detail(signals: list, kline: dict) -> str:
    """返回评分明细字符串，用于控制台调试输出"""
    lines = ["── 评分明细 ──"]
    strategy_total = 0.0
    for sig in signals:
        base_w  = _WEIGHT.get(sig, 0)
        coef_fn = _COEF_FN.get(sig, generic_coef)
        coef    = coef_fn(kline) if kline else 1.0
        pts     = base_w * coef
        strategy_total += pts
        lines.append(f"  {sig}: {base_w} × {coef:.2f} = {pts:.1f}分")
    strategy_total = min(strategy_total, 75.0)
    q = _kline_quality_score(kline, signals) if kline else 0.0
    lines.append(f"  K线质量加分: {q:.1f}分")
    lines.append(f"  合计: {int(round(strategy_total + q))}分")
    return "\n".join(lines)
