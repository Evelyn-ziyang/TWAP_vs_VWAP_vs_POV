# TWAP / Forecast VWAP / POV：执行节奏与成本比较

本项目比较三种常见母订单拆分算法：**TWAP** 按时间均匀执行，**Forecast VWAP** 按交易前预测的日内成交量曲线执行，**POV** 则随已观察到的市场成交量动态执行。研究问题不是寻找一个永远最优的算法，而是说明：在相同订单与约束下，三种方法的执行路径、完成时点、成本分布和 regime 敏感性有何不同。

## 1. Data

| 项目 | 本项目设置 |
|---|---|
| 标的与频率 | AAPL，5-minute OHLCV |
| 交易时段 | 2026-07-24 至 2026-07-31，共 6 个完整正常交易日 |
| 日内范围 | 09:30–16:00 ET，78 bars/day，共 468 bars |
| Full-day 测试 | 前 5 日估计 VWAP profile；最后 1 日（2026-07-31）测试 |
| Dynamic-Q 测试 | 2026-07-31；固定使用此前 5 个交易日估计 profile |
<!--| 数据文件 | [`Data_example/example.pkl`](Data_example/example.pkl)，可由 [`AAPL_5m_source.csv`](Data_example/AAPL_5m_source.csv) 离线重建 |-->

选择 5 分钟 bar，是为了在日内成交量形状和 bar-level 噪声之间折中。需要强调：当前公开 fixture 的 `volume` 是数据商定义的 **tick volume**，不是 consolidated share volume。因此这些结果适合比较算法逻辑，但 POV participation 和 impact 数值不应被解释成生产级股票成交量估计。

## 2. 三种算法

设母订单总量为 $Q$，执行窗口有 $N$ 个 bar，$V_i$ 是第 $i$ 个 bar 的市场成交量，$R_i$ 是进入该 bar 时的剩余订单量，$L$ 是 lot size。

### TWAP：时间驱动

TWAP 给每个时间桶相同权重：

$$
q_i^{\mathrm{TWAP}} \approx \frac{Q}{N}.
$$

整数余量由 largest-remainder 方法分配，因此最终计划量严格等于 \(Q\)。它的优点是透明、稳定、交易前完全已知；缺点是忽略日内流动性变化，低量时段的实际参与率可能升高。

### Forecast VWAP：预测成交量曲线驱动

先把每个训练日同一时段的成交量转换成日内占比：

$$
s_{d,i}=\frac{V_{d,i}}{\sum_j V_{d,j}},\qquad
\hat p_i=\frac{\operatorname{median}_d(s_{d,i})}
{\sum_k\operatorname{median}_d(s_{d,k})},
\qquad
q_i^{\mathrm{VWAP}}\approx Q\hat p_i.
$$

本项目使用的是 **Forecast-Profile VWAP**，测试日真实成交量不会进入 profile；它不是提前知道未来成交量的 realized-volume oracle。该方法能把订单向预测的高流动性时段移动，但结果依赖 profile 预测质量。

### POV：实时成交量驱动

POV 以参与率 $\rho$ 跟随已观察市场成交量。为避免使用同一根 5-minute bar 的完整成交量，代码默认使用一根 bar 的滞后：

$$
q_i^{\mathrm{POV}}
=\min\!\left(R_i,\left\lfloor\frac{\rho V_{i-1}}{L}\right\rfloor L\right),
\qquad q_1^{\mathrm{POV}}=0.
$$

本项目设 $\rho=10\%$。POV 是反馈策略：市场放量后加速，缩量后减速，因此完成时点不是交易前固定的；若窗口总量不足，它可能无法完成。回测中的 20% hard cap 是区间结束后核验 fill feasibility 的约束，不是 bar-open 时提前知道的 scheduling signal。

| 算法 | 主要驱动 | 交易前能否确定完整 schedule | 最主要的优势 | 最主要的风险 |
|---|---|---|---|---|
| TWAP | 时间 | 是 | 简单、可预测、对 volume forecast 不敏感 | 忽略流动性形状 |
| Forecast VWAP | 历史/预测 volume profile | 是 | 计划量与预期流动性匹配 | profile forecast error |
| POV | 实时 observed volume | 否 | 自动适应当日实际放量/缩量 | 完成时点和成本更依赖市场路径 |

## 3. 实验设计

项目用两层实验回答不同问题。

### Full-day fixed-Q：展示一笔真实形态的订单如何执行

- AAPL，2026-07-31，09:30–16:00 ET；
- BUY 5,000 shares；
- 三种算法面对同一个固定母订单；
- 用于观察每 bar 节奏、累计完成路径和单日成本。

### Dynamic-Q：在相同订单难度下比较分布

- 23 个相互重叠的 60-minute windows；每个窗口 12 bars，每 15 分钟滚动一次；另输出 6 个不重叠窗口作为稳健性对照；
- 所有窗口只测试 2026-07-31，并固定使用此前 5 个完整 session 训练 profile，避免把 1–5 日不同历史长度的策略混在一起；
- 每个窗口设 $Q_w=\lfloor3\%\times\sum_iV_{w,i}\rfloor$，本样本 $Q$ 范围为 170–734，中位数 315；
- BUY 订单，POV rate 10%，统一 hard cap 20%；
- 以 arrival implementation shortfall 比较，BUY 的定义为

$$
IS=10^4\frac{P_{\mathrm{fill}}-P_{\mathrm{arrival}}}{P_{\mathrm{arrival}}},
$$

数值越低越好。图表使用的净 IS 包含显式费用；CSV 另列不含费用的 gross price shortfall。Dynamic-Q 使用完整窗口成交量决定 $Q_w$，是 **ex-post research normalization**，用于控制相对订单难度，不是可直接部署的实盘 sizing 规则。它不会证明生产可实施性，也不支持显著性推断。

## 4. Figures：三种算法的区别

### Figure 1 — Full-day fixed-Q case study

![Full-day fixed-Q case study](figures/readme/00_full_day_case_study.svg)

这张图最直接地展示了节奏差异：

- **TWAP** 的每 bar 目标接近常数，累计成交量接近直线；
- **Forecast VWAP** 按历史 profile 调整速度，预测高量时多做、低量时少做，因此累计路径相对 TWAP 弯曲；
- **POV** 使用一根 bar 滞后的 observed volume，开盘放量后加速，并明显早于另外两种方法完成，完成后 schedule 归零。

| Algorithm | Completion | Avg fill | VWAP slippage | Modelled cost |
|---|---:|---:|---:|---:|
| TWAP | 100.0% | 302.5568 | -17.66 bps | $507.22 |
| Forecast VWAP | 100.0% | 302.7594 | -10.97 bps | $480.55 |
| POV | 100.0% | 302.4696 | -20.52 bps | $583.87 |

当天价格从 arrival 后明显下跌，所以 arrival IS 主要反映单日价格路径，不应解释为算法 alpha。改成因果化、滞后一根 bar 的 POV 后，本日 POV 的成交均价和 VWAP slippage 最低，而 Forecast VWAP 的模型化 spread + impact + fee 最低；“贴近 benchmark”和“模型成本最低”仍不是同一个目标。

### Figure 2 — Single-window execution demo

![Single-window execution demo](figures/readme/01_single_window_demo.svg)

这个 60 分钟窗口的动态订单量为 $Q=734$。三种算法都完成订单，但路径明显不同：TWAP 把执行平均分到窗口末，Forecast VWAP 做温和的 profile 倾斜，POV 在观察到窗口开头放量后快速完成。它说明 POV 的核心差异不是静态权重，而是滞后的 volume feedback 和可变完成时点。

### Figure 3 — Relative implementation shortfall distributions

![Delta IS distributions](figures/readme/02_delta_is_distribution.svg)

图中 $\Delta IS=IS_{\mathrm{algo}}-IS_{\mathrm{TWAP}}$，小于 0 表示相对 TWAP 更好。

| Compared with TWAP | Mean ΔIS | Median ΔIS | Win rate | Completion |
|---|---:|---:|---:|---:|
| Forecast VWAP | +1.14 bps | +0.54 bps | 26.1% | 100.0% |
| POV | -2.52 bps | -3.41 bps | 52.2% | 100.0% |

Forecast VWAP 的分布仍集中在 0 附近，说明在这些短窗口里，它与 TWAP 的成交时点通常相近；本日多数窗口并未优于 TWAP。POV 的分布更宽、尾部更明显，反映其成本更依赖窗口内放量顺序和价格路径。这里只是同一测试日的 23 个描述性窗口，不能把胜率解释成独立样本统计。

### Figure 4 — Volume × volatility regimes

![Volume and volatility regime heatmap](figures/readme/03_regime_heatmap.svg)

按 window volume 和 realized volatility 的样本中位数将窗口划分为四个 regime：

- **Forecast VWAP** 在 low-volume/low-vol 中 mean ΔIS 为 +0.42 bps，在 high-volume/high-vol 中为 +2.11 bps；两个非对角格各只有 1 个窗口，不能作 regime 推断；
- **POV** 在 low-volume/low-vol 中 mean ΔIS 为 -9.60 bps，但在 high-volume/low-vol 与 high-volume/high-vol 中分别为 +8.22 和 +4.77 bps，显示其对成交量出现顺序与价格路径更敏感；
- 所有格子的 completion 都是 100%，因此这里的差异不是由某个算法少成交造成的。

这张图只能提示算法优劣可能具有条件性：Forecast VWAP 的差异较小但受预测误差影响；POV 的路径敏感性更强。由于仅一个测试日、窗口重叠且部分格只有 1 个观测，热力图不构成可外推的 regime 证据。

### Figure 5 — IS distribution by algorithm

![Implementation shortfall distribution by algorithm](figures/readme/04_is_distribution_by_algorithm.svg)

TWAP 与 Forecast VWAP 的箱体高度重叠，再次说明 Forecast VWAP 在当前单日样本中没有可识别的 unconditional 优势。POV 的中心和离散程度有所不同，来自其更快、更依赖已观察成交量的完成路径。三组 mean IS 分别为 -29.46、-28.32 和 -31.98 bps；均值被开盘窗口的巨大市场移动明显影响，不能单独视为算法 alpha。

### Figure 6 — Completion sensitivity

![Completion rate](figures/readme/05_completion_rate.svg)

在 3% 和 5% order fraction 下三种算法均完成；Q 提高到 10% 时，滞后 POV 的平均 completion 降至 91.3%，到 15% 时降至 60.9%。TWAP 与 Forecast VWAP 在 15% 时平均 completion 仍约为 99.5% 和 99.6%。因此 3% 主比较控制了 fill ratio，而敏感性图明确展示了 POV 的参与率约束和完成风险；carry 并没有把尚未被 POV 调度的母订单强制补齐。

## 5. 总结

| 维度 | TWAP | Forecast VWAP | POV |
|---|---|---|---|
| 执行节奏 | 最平滑、最可预测 | 预先向预测高量时段倾斜 | 对实际放量快速响应 |
| 完成时点 | 通常接近窗口末 | 通常接近窗口末 | 可很早完成，也可能因低量而延迟 |
| 当前样本相对表现 | 稳定 baseline | 与 TWAP 非常接近，部分 regime 小幅改善 | 分布更宽、regime 敏感性更强 |
| 主要模型风险 | 忽略 volume curve | volume-profile forecast error | realized-volume 路径、延迟与未完成风险 |
| 更适合回答的问题 | “按时间均匀做完” | “按预期市场节奏执行” | “保持实时市场参与率” |

结论不是某一种算法全面胜出，而是三者承担不同风险：TWAP 承担流动性错配风险，Forecast VWAP 承担预测风险，POV 承担路径和完成时点风险。实际选择应由客户 benchmark、订单占 ADV、完成约束、流动性预测可信度和 urgency 决定。

## 6. Limitations

1. 当前只有 AAPL、6 个交易日；主比较只有最后一日的 23 个窗口且存在 75% overlap，不是独立统计样本，也不支持显著性推断。另提供 6 个非重叠窗口汇总，但样本仍远不足。
2. Volume 是 provider-defined tick volume，不是 consolidated shares；POV 和 3% Dynamic-Q 只能视为方法演示。
3. Forecast VWAP 固定使用前 5 日中位数 profile，没有事件、weekday 或实时 reforecast；当前连续交易时段样本不含独立 auction print。
4. 成交模型在有 `bar_vwap` 时优先使用它，否则回退 HLC/3；默认 half-spread、平方根临时 impact 和 fee 仍是简化假设。代码支持每 bar spread/fee，但未模拟永久冲击、order book、queue、venue 与 adverse selection。
5. Dynamic-Q 的 realized window volume 是 ex-post normalization。生产环境应改用预先给定母订单、ADV 或 forecast window volume。

<!--## 7. Reproduce

项目主体只依赖 Python 3.10+ 标准库；生成图需要 Pillow，测试需要 pytest。

```bash
# 运行固定全日回测
python algo_exec.py --data Data_example/example.pkl

# 逐张生成 README 图（PNG + SVG）和汇总 CSV
python figures/generate_readme_figures.py

# 运行测试
python -m pytest -q
```-->

<!--关键输出：

- [`review_assessment.md`](review_assessment.md)：对外部审查逐项判断、反驳理由与整改记录；
- [`review_v2.md`](review_v2.md)：更完整的 Review v2 汇报稿；
- [`review_v2_report.tex`](review_v2_report.tex)：A4 研报版 LaTeX 源文件；
- [`output/pdf/twap_vwap_pov_review_v2_report.pdf`](output/pdf/twap_vwap_pov_review_v2_report.pdf)：可直接用于汇报的研报 PDF；
- [`figures/readme/full_day_summary.csv`](figures/readme/full_day_summary.csv)：Full-day 结果；
- [`figures/readme/dynamic_q_summary.csv`](figures/readme/dynamic_q_summary.csv)：Dynamic-Q 总体结果；
- [`figures/readme/dynamic_q_nonoverlap_summary.csv`](figures/readme/dynamic_q_nonoverlap_summary.csv)：6 个非重叠窗口稳健性对照；
- [`figures/readme/dynamic_q_regime_summary.csv`](figures/readme/dynamic_q_regime_summary.csv)：regime 结果；
- [`figures/readme/completion_sensitivity.csv`](figures/readme/completion_sensitivity.csv)：3%–15% 订单比例下的完成率；
- [`figures/readme/rolling_window_results.csv`](figures/readme/rolling_window_results.csv)：23 个主比较窗口的底层明细。-->
