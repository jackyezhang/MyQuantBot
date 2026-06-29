"""
MyQuantBot main.py  —  插件化架构版
=====================================
新增策略只需：
  1. 新建 strategies/<name>.py（实现 get_name / run）
  2. 在 strategy_registry.py 追加一条注册记录
  main.py 本身零修改。
"""

import os, time, importlib.util, requests, json, logging
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from datetime import date

from google import genai
from google.genai import types
from google.genai.errors import APIError

# ── 插件化配置：所有策略元数据从注册表读取 ──────────────────────────────
from strategy_registry import (
    TARGET_STRATEGIES,
    REQUIRED_STRATEGIES,
    WEIGHT,           # 中文名→权重，仅用于兼容旧日志，评分已由 scorer 处理
)
from scorer import dynamic_base_score, score_detail

# ================== 日志 ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ================== 配置 ==================
PROXY              = ""
BASE_URL           = "http://你的服务器地址:8080"
WECHAT_WEBHOOK_URL = "你的腾讯机器人地址"
GEMINI_API_KEY     = "你的key"
STRATEGY_DIR       = "./strategies"

MAX_WORKERS     = 20
REQUEST_TIMEOUT = (2, 5)
SCAN_INTERVAL   = 1800
PRE_TOP_N       = 20
FINAL_TOP_N     = 5
AI_SLEEP        = 5.5

# ================== 初始化 ==================
if PROXY:
    os.environ["http_proxy"]  = PROXY
    os.environ["https_proxy"] = PROXY

client = genai.Client(api_key=GEMINI_API_KEY)

# ================== 加载策略（从注册表自动派生）==================
def load_strategies() -> list:
    strategies = []
    for name in TARGET_STRATEGIES:
        path = os.path.join(STRATEGY_DIR, f"{name}.py")
        if not os.path.exists(path):
            log.warning(f"策略文件未找到，已跳过: {path}")
            continue
        spec = importlib.util.spec_from_file_location(name, path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        strategies.append(mod)
        log.info(f"已加载策略: {mod.get_name()} ({name}.py)")
    return strategies

# ================== 单股扫描 ==================
def scan_stock(stock: dict, strategies: list) -> dict | None:
    code = stock["code"]
    name = stock.get("name", "未知")
    try:
        res  = requests.get(f"{BASE_URL}/api/kline?code={code}", timeout=REQUEST_TIMEOUT)
        body = res.json()
        if not isinstance(body, dict):
            return None
        data = (body.get("data") or {}).get("List", [])
        if not data:
            return None

        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]

        signals = []
        for s in strategies:
            try:
                if s.run(df):
                    signals.append(s.get_name())
            except Exception as e:
                log.debug(f"策略 {s.get_name()} 在 {code} 异常: {e}")

        if not signals:
            return None

        # ── K线摘要（用于动态评分和 AI 提示词）──────────────────────────
        try:
            close  = df["close"].astype(float)
            volume = df["volume"].astype(float) if "volume" in df.columns else None
            PRICE_DIVISOR = 1000.0 if close.iloc[-1] > 5000 else 1.0
            chg1  = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100
            chg5  = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100
            price = close.iloc[-1] / PRICE_DIVISOR
            ma5   = close.rolling(5).mean().iloc[-1] / PRICE_DIVISOR
            ma20  = close.rolling(20).mean().iloc[-1] / PRICE_DIVISOR
            vol_ratio = None
            if volume is not None:
                vol_avg5  = volume.iloc[-6:-1].mean()
                vol_ratio = volume.iloc[-1] / vol_avg5 if vol_avg5 > 0 else None
            kline_summary = {
                "price":     round(price, 2),
                "chg1":      round(chg1, 2),
                "chg5":      round(chg5, 2),
                "ma5":       round(ma5, 2),
                "ma20":      round(ma20, 2),
                "vol_ratio": round(vol_ratio, 2) if vol_ratio else None,
            }
        except Exception as e:
            log.debug(f"K线摘要计算异常 [{code}]: {e}")
            kline_summary = {}

        return {"code": code, "name": name, "signals": signals, "kline": kline_summary}

    except requests.RequestException as e:
        log.debug(f"K线请求失败 [{code}]: {e}")
        return None


# ================== 投票制过滤 ==================
def filter_by_level(hits: list, total_strategies_count: int) -> tuple[list, int]:
    """
    分级过滤逻辑（修复版）
    ─────────────────────────────────────────────────────────────────
    原问题：
      要求「必选策略命中 ≥ 4」，但优化后的9个策略中，
      部分策略存在信号互斥（如「布林带超卖反弹」要求刚经历下跌，
      「量价齐升启动」要求连续上涨突破新高），同只股票几乎不会
      同时触发 4 个必选，导致 486 只初筛全部被过滤掉。

    新逻辑：
      ┌─────────────────────────────────────────────────────┐
      │ 硬性门槛：总命中策略数 ≥ level（从 L9 自适应降至 L3）│
      │ 软性锚点：命中的必选策略数 ≥ 1（保证信号质量下限）  │
      └─────────────────────────────────────────────────────┘
      REQUIRED_STRATEGIES 从「必须全部命中」改为「至少命中其中1个」，
      作为质量锚而非多重必要条件，严格度由总命中数 level 控制。
    """
    MIN_LEVEL = 3   # 绝对下限：至少 3 个策略同时命中

    # 诊断日志：打印命中分布，方便日常调参
    dist: dict[int, int] = {}
    for x in hits:
        n = len(x["signals"])
        dist[n] = dist.get(n, 0) + 1
    log.info(f"命中分布（命中策略数→股票数）: { {k: dist[k] for k in sorted(dist)} }")

    for level in range(total_strategies_count, MIN_LEVEL - 1, -1):
        filtered = [
            x for x in hits
            if len(x["signals"]) >= level                           # 总命中数达标
            and len(set(x["signals"]) & REQUIRED_STRATEGIES) >= 1  # 至少1个必选命中
        ]
        if filtered:
            log.info(f"过滤结果：L{level}，入选 {len(filtered)} 只")
            return filtered, level

    return [], 0


# ================== AI 审计 ==================
def ai_audit_single(stock: dict, idx: int, total: int) -> tuple[dict, str]:
    code    = stock["code"]
    name    = stock.get("name", "未知")
    signals = "、".join(stock["signals"])
    log.info(f"AI审计 [{idx}/{total}] {name}({code})")

    kline     = stock.get("kline", {})
    kline_str = ""
    if kline:
        vol_line  = f"量比：{kline['vol_ratio']}x" if kline.get("vol_ratio") else ""
        kline_str = f"""
技术数据：
  当前价：{kline.get('price')}
  今日涨幅：{kline.get('chg1')}%
  5日涨幅：{kline.get('chg5')}%
  MA5：{kline.get('ma5')}  MA20：{kline.get('ma20')}
  {vol_line}"""

    today  = date.today().strftime("%Y年%m月%d日")
    prompt = f"""你是专业A股量化基金经理，今天是{today}。
请先激活 Google Search 搜索工具进行以下调研，再结合技术数据综合评分：

【搜索任务】
1. 搜索"{name} {code} 最新消息 {today[:7]}"，了解近期公司公告、业绩、重大事件。
2. 搜索该股票所属行业的最新政策、热点动态。
3. 搜索"A股 {today[:7]} 市场情绪 主力资金"，了解当前总体市场环境。

【股票基本信息】
股票：{name}（{code}）
命中策略：{signals}{kline_str}

【评分维度（各20分，共100分） score】
1. 技术面：均线多头排列、突破幅度、量价配合
2. 资金面：量比大小、近期成交变化、主力动向
3. 基本面：近期公告、业绩预期、有无利空
4. 行业景气度：所在行业政策、板块热度、资金轮动方向
5. 市场时机：当前大盘环境、风险偏好、短线爆发条件

【输出要求】
必须只返回一个合法的 JSON 字典，不要包含 markdown 标记（如 ```json），不要有任何前言或后记。
键名必须为 score 和 reason：
{{"score": 85, "reason": "核心技术信号描述。新闻/行业动态：XXX。风险提示：XXX。"}}"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.2
                )
            )
            text = resp.text.strip()
            if "```" in text:
                parts = text.split("```")
                text  = parts[1] if len(parts) >= 3 else parts[-1]
                text  = text.replace("json", "", 1).strip()
            result = json.loads(text)
            result["score"] = int(result.get("score", 0))
            if "reason" not in result:
                result["reason"] = "AI未返回具体原因"
            return result, "SUCCESS"

        except APIError as e:
            err_msg = str(e)
            if e.code == 503 or "503" in err_msg:
                if attempt < max_retries - 1:
                    wait = 5 if attempt == 0 else 12
                    log.warning(f"[503] 高负载 [{code}]，等待 {wait}s 后重试...")
                    time.sleep(wait)
                    continue
                else:
                    log.error(f"[503] 达到最大重试次数，跳过 [{code}]")
                    return {"score": 0, "reason": "AI服务器临时不可用"}, "FAIL_SKIP"
            if e.code == 429 or "429" in err_msg:
                if attempt < max_retries - 1:
                    log.warning(f"[429] 限流 [{code}]，等待 30s...")
                    time.sleep(30)
                    continue
                else:
                    log.error(f"[429] 配额耗尽")
                    return {"score": 0, "reason": "AI配额今日已耗尽"}, "429_QUOTA"
            log.warning(f"API异常 [{code}] (Code: {e.code}): {err_msg}")
            break
        except Exception as e:
            log.warning(f"AI审计异常或JSON解析失败 [{code}]: {e}")
            break

    return {"score": 0, "reason": "AI分析失败"}, "FAIL_SKIP"


# ================== 推送 ==================
def push(content: str):
    if not WECHAT_WEBHOOK_URL or "你的机器人KEY" in WECHAT_WEBHOOK_URL:
        log.warning("未配置有效的企业微信 Webhook 地址，跳过推送")
        return
    try:
        res = requests.post(
            WECHAT_WEBHOOK_URL,
            json={"msgtype": "markdown", "markdown": {"content": content}},
            headers={"Content-Type": "application/json"},
            proxies={"http": None, "https": None},
            timeout=10
        )
        res_json = res.json()
        if res_json.get("errcode") == 0:
            log.info("企业微信消息推送成功")
        else:
            log.error(f"企业微信推送返回错误: {res_json}")
    except Exception as e:
        log.error(f"企业微信推送失败: {e}")


# ================== 主流程 ==================
def main():
    strategies = load_strategies()
    if not strategies:
        log.error("没有可用策略，退出")
        return

    log.info(f"已注册策略：{[s.get_name() for s in strategies]}")
    log.info(f"必选策略（参与投票）：{REQUIRED_STRATEGIES}")

    # 1. 获取股票池
    try:
        stock_list = requests.get(f"{BASE_URL}/api/codes", timeout=10).json()["data"]["codes"]
        log.info(f"股票池：{len(stock_list)} 只")
    except Exception as e:
        log.error(f"获取股票池失败: {e}")
        return

    # 2. 并发扫描 K 线
    hits: list[dict] = []
    lock = Lock()
    with tqdm(total=len(stock_list), desc="🚀 扫描中", unit="只") as pbar:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(scan_stock, s, strategies): s for s in stock_list}
            for fut in as_completed(futures):
                result = fut.result()
                if result:
                    with lock:
                        hits.append(result)
                pbar.update(1)

    log.info(f"初筛命中：{len(hits)} 只")
    if not hits:
        push("📭 量化报告\n本轮无命中")
        return

    # 3. 投票制过滤
    filtered, level = filter_by_level(hits, len(strategies))
    if not filtered:
        push("📭 量化报告\n本轮无有效信号")
        return
    log.info(f"策略等级 L{level}，入选：{len(filtered)} 只")

    # 4. 动态基础评分预排序
    for s in filtered:
        s["base_score"] = dynamic_base_score(s["signals"], s.get("kline", {}))
    candidates = sorted(filtered, key=lambda x: x["base_score"], reverse=True)[:PRE_TOP_N]

    # 5. AI 审计
    total      = len(candidates)
    ai_enabled = True
    log.info(f"开始 AI 审计：{total} 只，间隔 {AI_SLEEP}s")

    for i, stock in enumerate(candidates, 1):
        if ai_enabled:
            audit, status = ai_audit_single(stock, i, total)
            if status == "429_QUOTA":
                log.warning("配额耗尽，切换纯基础分模式")
                ai_enabled = False
        else:
            audit = {"score": 0, "reason": "AI配额今日已耗尽"}

        stock["ai_score"]    = audit["score"]
        stock["reason"]      = audit["reason"]
        stock["final_score"] = stock["base_score"] + stock["ai_score"]

        if ai_enabled and i < total:
            time.sleep(AI_SLEEP)

    # 6. 最终排序
    has_any_ai = any(s["ai_score"] > 0 for s in candidates[:FINAL_TOP_N])
    mode = "AI辅助" if has_any_ai else "纯策略"
    top  = sorted(candidates, key=lambda x: x["final_score"], reverse=True)[:FINAL_TOP_N]

    # 7. 控制台输出
    print(f"\n{'='*40}")
    print(f"  🏆 TOP{FINAL_TOP_N}  |  L{level}  |  {mode}")
    print(f"{'='*40}\n")
    for i, s in enumerate(top, 1):
        print(f"第{i}名 【{s['name']}】({s['code']})")
        print(f"  信号: {', '.join(s['signals'])}")
        print(score_detail(s["signals"], s.get("kline", {})))
        if s["ai_score"] > 0:
            print(f"  评分: {s['final_score']}（基础{s['base_score']} + AI{s['ai_score']}）")
            print(f"  AI:   {s['reason']}\n")
        else:
            print(f"  基础分: {s['base_score']} (AI审计跳过或失败)\n")

    # 8. 推送企业微信
    for i, s in enumerate(top, 1):
        signals_fmt = " | ".join([f"<font color=\"info\">{sig}</font>" for sig in s["signals"]])
        if s["ai_score"] > 0:
            score_line = (
                f"**综合评分：** <font color=\"warning\">{s['final_score']}</font> "
                f"（基础 {s['base_score']} + AI {s['ai_score']}）\n\n"
                f"**AI 审计判断：**\n>{s['reason']}"
            )
        else:
            score_line = f"**基础评分：** <font color=\"comment\">{s['base_score']}</font>\n*(AI审计未完成)*"

        push(f"""### 🏆 量化选股 TOP {i} ({mode})

**【{s['name']}】** (`{s['code']}`)
**策略信号：** {signals_fmt}
---------------------------------
{score_line}""")
        time.sleep(1.5)

    log.info(f"推送完成（TOP{len(top)}，{mode}）")


# ================== 定时循环 ==================
if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            log.error(f"主循环异常: {e}")
        log.info(f"等待 {SCAN_INTERVAL // 60} 分钟后下一轮...")
        time.sleep(SCAN_INTERVAL)
