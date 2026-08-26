# TWAP / Forecast VWAP / POV — Review v2（整改后）

> 本文是当前代码与图表的结果摘要。对外部 AI 审查逐项判断及整改证据见 [`review_assessment.md`](review_assessment.md)。

## 1. 研究口径

| 层次 | 设置 | 用途 |
|---|---|---|
| Full-day fixed-Q | AAPL，2026-07-31，BUY 5,000，09:30–16:00 ET | 展示一笔固定母订单的节奏与完成路径 |
| Dynamic-Q 主比较 | 最后 1 日的 23 个重叠 60-minute windows；固定此前 5 日 profile；Q = 3% × realized window volume | 在相同相对订单难度和相同完成率下作描述性比较 |
| 非重叠稳健性 | 最后 1 日的 6 个 60-minute windows | 暴露重叠窗口依赖性，不用于显著性推断 |
| 完成率敏感性 | Q = 3%、5%、10%、15% × window volume | 检验大订单下 hard cap 与 POV participation 的完成风险 |

数据仍只有 AAPL 六个交易日，volume 是 provider-defined tick volume 而非 consolidated shares。因此全部数值是算法行为演示，不是生产 TCA 证据。

## 2. 整改后的算法口径

- **TWAP**：总量按时间桶等分，largest remainder 保证整数总量守恒。
- **Forecast VWAP**：对恰好 5 个训练日的同一 slot 日内 volume share 取中位数；测试日 volume 不进入预测 profile；训练日缺任何目标 slot 会直接报错。
- **POV**：默认使用一根 bar 滞后的 observed volume，避免用同 bar 完整 volume 决定本 bar target：

$$
q_i^{POV}=\min\left(R_i,\left\lfloor\rho V_{i-1}\right\rfloor\right),
\qquad q_1^{POV}=0,\quad \rho=10\%.
$$

成交参考价在数据提供 `bar_vwap` 时优先使用，否则回退 HLC/3。结果同时输出不含费用的 gross price shortfall 和含显式费用的 net shortfall；逐 bar spread/fee 可以由输入覆盖默认值。

## 3. 图表结论

### Figure 1：Full-day fixed-Q

![Full-day fixed-Q](figures/readme/00_full_day_case_study.svg)

| Algorithm | Completion | Avg fill | Net VWAP slippage | Modelled cost |
|---|---:|---:|---:|---:|
| TWAP | 100.0% | 302.5568 | -17.65 bps | $507.22 |
| Forecast VWAP | 100.0% | 302.7594 | -10.96 bps | $480.55 |
| POV | 100.0% | 302.4696 | -20.52 bps | $583.87 |

TWAP 路径最平滑；Forecast VWAP 根据历史 profile 前后倾斜；滞后 POV 在观察到放量后加速并较早完成。当天价格从 arrival 后大幅下跌，所以 arrival IS 主要是 timing/path，不是算法 alpha。单日只能解释“如何执行”，不能用于长期排名。

### Figure 2：Single-window 路径

![Single window](figures/readme/01_single_window_demo.svg)

在 Q = 734 的窗口中，TWAP 近似线性，Forecast VWAP 温和倾斜，POV 首 bar 不交易、随后对已观察放量作反馈并快速完成。该图直接显示修复 look-ahead 后三种 information set 的差异。

### Figure 3：相对 TWAP 的 ΔIS

![Delta IS](figures/readme/02_delta_is_distribution.svg)

| Algorithm | Mean ΔIS | Median ΔIS | Win rate | Completion |
|---|---:|---:|---:|---:|
| Forecast VWAP | +1.14 bps | +0.54 bps | 26.1% | 100.0% |
| POV | -2.52 bps | -3.41 bps | 52.2% | 100.0% |

Forecast VWAP 与 TWAP 仍很接近；POV 分布更宽、路径敏感性更强。23 个窗口均来自同一天且 75% overlap，以上只是描述，不是统计显著性。

### Figure 4：Volume × volatility regime

![Regime](figures/readme/03_regime_heatmap.svg)

Forecast VWAP 在 low-volume/low-vol 与 high-volume/high-vol 的 mean ΔIS 分别为 +0.42 与 +2.11 bps。POV 在 low-volume/low-vol 为 -9.60 bps，在 high-volume/low-vol 与 high-volume/high-vol 为 +8.22 与 +4.77 bps。两个非对角格各只有一个观测，因此热力图只提示条件性，不构成 regime 实证结论。

### Figure 5：IS 箱线图

![IS distribution](figures/readme/04_is_distribution_by_algorithm.svg)

TWAP 与 Forecast VWAP 箱体高度重叠；POV 的中心和尾部不同。三组 mean IS 为 -29.46、-28.32、-31.98 bps，明显受同一测试日开盘窗口的市场移动影响，不能视为算法 alpha。

### Figure 6：完成率敏感性

![Completion sensitivity](figures/readme/05_completion_rate.svg)

| Q / window volume | TWAP | Forecast VWAP | POV |
|---:|---:|---:|---:|
| 3% | 100.0% | 100.0% | 100.0% |
| 5% | 100.0% | 100.0% | 100.0% |
| 10% | 100.0% | 100.0% | 91.3% |
| 15% | 99.5% | 99.6% | 60.9% |

这项结果直接反驳“carry 必然让 POV 100% 完成”的判断：carry 只滚动已经调度但受 cap 限制的 target，不会替 POV 强制调度全部母订单。订单增大后，POV 的 completion risk 清楚出现。

## 4. 非重叠窗口对照

6 个非重叠窗口中，Forecast VWAP 相对 TWAP 的 mean ΔIS 为 -0.20 bps、胜率 50.0%；POV 为 -10.97 bps、胜率 83.3%。样本只有 6 个，不能用来宣称优势；其作用是提醒读者 23 个重叠窗口并非 23 个独立试验。

## 5. 最终结论与边界

三种算法承担不同风险：TWAP 是时间与流动性错配风险，Forecast VWAP 是 profile forecast error，POV 是反馈滞后、路径与完成风险。当前证据能可靠展示 pacing 机制，不能可靠给出长期成本排序。

仍未解决、也不应凭空参数化的问题包括永久冲击、订单簿/queue、adverse selection、maker-taker、跨标的与 SELL 样本。下一步应固定多标的长历史 consolidated trades/quotes snapshot，做 walk-forward、非重叠日级聚合和可校准的冲击模型。
