# MyQuantBot — A股量化选股机器人
[![Python Version](https://img.shields.io/badge/Python-3.9+-blue?svg=true&logo=python&logoColor=white)](https://github.com)
[![Gemini AI](https://img.shields.io/badge/AI-Gemini%201.5%20Flash-orange?svg=true&logo=google-gemini&logoColor=white)](https://github.com)
[![License](https://img.shields.io/badge/License-MIT-green?svg=true)](https://github.com)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?svg=true)](https://github.com)
> 9大投资大师策略 × Gemini AI 审计 × 企业微信实时推送

每 30 分钟全市场扫描 5500+ 只 A 股，策略多重共振筛选后交由 Gemini 联网审计，最终推送 TOP5 标的到企业微信。

---

## 功能概览

- **全市场扫描**：并发拉取 5500+ 只 K 线，20 线程约 2 分钟完成一轮
- **9大量化策略**：涵盖趋势突破、动量、吸筹、均线、量价等多个维度，每个策略独立优化至投资大师原版标准
- **自适应分级过滤**：从 L9（9策略全中）自动降级到 L3，找到当日最高质量信号层
- **动态评分引擎**：策略权重 × K 线强度系数 + K 线质量分，满分 ~100
- **Gemini AI 联网审计**：对候选股票实时搜索最新公告、行业动态、市场情绪，综合打分
- **企业微信推送**：每轮输出 TOP5，含评分明细和 AI 研判

---

## 项目结构

```
MyQuantBot/
├── main.py                    # 主循环：扫描 → 过滤 → AI审计 → 推送
├── strategy_registry.py       # 策略注册表（唯一配置入口）
├── scorer.py                  # 动态评分引擎
│
├── strategies/                # 策略插件目录
│   ├── alpha_break.py         # 华尔街趋势突破（MA20+量比+大实体）
│   ├── donchian.py            # 唐奇安通道突破（20日高点+中位数量比）
│   ├── rsi_mom.py             # RSI动量稳健（Wilder RSI+MA20斜率）
│   ├── bollinger.py           # 布林带超卖反弹（带宽扩张+双均线）
│   ├── macd_golden.py         # MACD零轴金叉（DIF连续改善+DEA向上）
│   ├── volume_price_surge.py  # 量价齐升启动（O'Neil Dry-up突破）
│   ├── turtle_atr_breakout.py # 海龟ATR突破（Dennis原版+波动率扩张）
│   ├── ema_ribbon.py          # 均线彩虹多头（Weinstein Stage 2）
│   └── institutional_accumulation.py  # 主力吸筹突破（Wyckoff底部形态）
│
└── tracking/                  # 持仓追踪（Serenity 版）
    ├── score_tracker.py       # 每日证伪止损检测
    └── forward_picks.csv      # 活跃持仓池
```

---

## 快速开始

**环境要求**：Python 3.11+，本地行情 API（`/api/kline`、`/api/codes`）

```bash
# 1. 安装依赖
pip install pandas requests tqdm google-genai

# 2. 配置（直接编辑 main.py 顶部）
BASE_URL           = "http://你的行情服务地址:端口"
WECHAT_WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key"
GEMINI_API_KEY     = "你的Gemini API Key"

# 3. 启动
py main.py
```

---

## 评分体系

每只候选股票的最终分 = **基础分**（动态，上限 75）+ **AI 分**（0~100）

### 基础分组成

```
基础分 = Σ( 策略权重 × 强度系数 )  +  K线质量分
          ↑上限75                      ↑上限25
```

**策略权重**（注册表配置，可调）：

| 策略 | 权重 | 类型 |
|------|------|------|
| 华尔街趋势突破 | 30 | 必选锚点 |
| 量价齐升启动 | 28 | 必选锚点 |
| 主力吸筹突破 | 26 | 必选锚点 |
| 唐奇安通道突破 | 25 | 必选锚点 |
| 海龟ATR突破 | 24 | 辅助验证 |
| MACD零轴金叉 | 22 | 辅助验证 |
| RSI动量稳健 | 20 | 必选锚点 |
| 均线彩虹多头 | 20 | 辅助验证 |
| 布林带超卖反弹 | 15 | 必选锚点 |

**强度系数**（0.60~1.40）：每个策略有专属系数函数，根据量比、涨幅、均线排列实时调整权重。

**K 线质量分**（0~25）：

- Q1 量比质量（0~8）：量比越大得分越高，≥8x 满分
- Q2 价格动量（0~7）：今日涨幅 + 5日涨幅综合评估
- Q3 均线排列（0~5）：`价格 > MA5 > MA20` 且 MA5/MA20 间距越大加分越高
- Q4 多策略共振（0~5）：同时命中 ≥4 个策略额外加 5 分

### 自适应分级过滤

```
命中策略数  ≥ L9 → L8 → L7 → ... → L3（自动找有结果的最高级别）
同时要求：至少命中 1 个"必选锚点"策略
```

每轮日志会打印命中分布，例如：
```
命中分布（命中策略数→股票数）: {1: 312, 2: 134, 3: 28, 4: 9, 5: 2}
过滤结果：L4，入选 9 只
```

---

## 添加新策略

只需两步，`main.py` 和 `scorer.py` 零修改：

**Step 1** — 新建 `strategies/my_strategy.py`：

```python
def get_name() -> str:
    return "我的策略名"   # 必须与注册表 name 字段完全一致

def run(df) -> bool:
    """
    df: pandas DataFrame，列名小写，至少包含 close
    返回 True 表示该股票触发信号
    """
    close = df["close"].astype(float)
    # ... 策略逻辑 ...
    return True
```

**Step 2** — 在 `strategy_registry.py` 追加一条：

```python
{
    "file":     "my_strategy",       # strategies/ 下的文件名（不含.py）
    "name":     "我的策略名",         # 与 get_name() 完全一致
    "weight":   20,                  # 基础权重，建议 15~30
    "required": False,               # True=必选锚点，False=辅助验证
    "coef_fn":  generic_coef,        # 强度系数函数，可先用通用版
},
```

---

## 推送示例

```
🏆 量化选股 TOP 1 (AI辅助)

【光力科技】(300480)
策略信号：RSI动量稳健 | 华尔街趋势突破 | 唐奇安通道突破
─────────────────────────────────
综合评分：165（基础 75 + AI 90）

AI 审计判断：
技术面强势，均线多头排列，股价突破且量价配合良好。
资金面活跃，半导体设备国产替代逻辑强劲。基本面稳健，
产能满产并积极扩建，业绩预期向好。行业景气度高，
政策大力支持，国产替代逻辑强劲。
```

---

## 主要参数

在 `main.py` 顶部直接修改：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `SCAN_INTERVAL` | 1800 | 扫描间隔（秒） |
| `MAX_WORKERS` | 20 | 并发线程数 |
| `PRE_TOP_N` | 20 | 送入 AI 审计的候选数 |
| `FINAL_TOP_N` | 5 | 最终推送数 |
| `AI_SLEEP` | 5.5 | AI 调用间隔（秒，防限流） |

---

## 策略设计理念

每个策略均参照原版投资大师方法论，在 v2/v3 版本中修复了常见的工程缺陷：

| 策略 | 理论来源 | 核心优化 |
|------|----------|----------|
| 华尔街趋势突破 | 趋势跟踪 | K线实体过滤、20日量中位数基准、阻力位确认 |
| 唐奇安通道突破 | Richard Donchian | 多次阻力测试确认、失败突破记录排除 |
| RSI动量稳健 | Welles Wilder | Wilder 标准平滑、RSI 方向确认、防高位回落 |
| 布林带超卖反弹 | John Bollinger | 超卖深度门槛、MA60>MA120 双均线过滤、带宽扩张 |
| MACD零轴金叉 | Gerald Appel | DIF 连续改善、防弱势翻正、DEA 方向确认 |
| 量价齐升启动 | William O'Neil | Dry-up 缩量确认、筹码换手验证、20日量新高 |
| 海龟ATR突破 | Richard Dennis | ATR 短长期比较、防疲惫突破（N连涨过滤） |
| 均线彩虹多头 | Stan Weinstein | MA250 环境过滤、百分比斜率、相邻均线间距 |
| 主力吸筹突破 | Richard Wyckoff | 前置下跌确认、线性回归量萎缩、正常量基准 |

---

## 注意事项

- 本项目仅供**量化研究和学习**使用，不构成任何投资建议
- 策略信号为历史规律的统计总结，不保证未来表现
- A股具有涨跌停板制度，策略参数中已针对此特性做专项适配
- 建议配合止损规则使用，切勿满仓追涨
