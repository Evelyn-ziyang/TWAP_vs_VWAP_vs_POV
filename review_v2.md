# TWAP / Forecast VWAP / POV — Review v2

> 更新日期：2026-08-25  
> 汇报结构：Full-day fixed-Q case study + 60-minute Dynamic-Q comparison  
> 数据口径：当前可复现结果使用仓库内 AAPL 5-minute fixture；volume 为 provider-defined tick volume  
> 结论边界：research prototype，不是生产交易系统，也不构成投资建议

## 1. Executive takeaway

Review v2 将“算法如何运行”和“算法如何公平比较”拆成两层：

| Layer | 时间范围 | Parent order | 样本 | 用途 |
|---|---|---|---:|---|
| Full-day case study | 2026-07-31，09:30–16:00 ET | 固定 BUY 5,000 | 1 session | 展示三种执行节奏和单笔订单结果 |
| Dynamic-Q comparison | 2026-07-27 至 07-31 的 rolling 60-minute windows | $Q_w=\lfloor3\%\sum_{t\in w}V_t\rfloor$ | 115 windows | 控制相对订单难度后比较分布、胜率和 regime |

两层结果不能混在同一统计排名中。Full-day 是 case study；跨窗口结论只来自 Dynamic-Q experiment。

## 2. Full-day fixed-Q case study

### 2.1 Setup

```text
Ticker:       AAPL
Session:      2026-07-31
Window:       09:30–16:00 America/New_York
Bars:         78 × 5 minutes
Side / Q:     BUY 5,000
POV rate:     10%
Hard cap:     20% of provider volume per bar
VWAP profile: prior five sessions only
```

![Full-day fixed-Q execution case study](figures/readme/00_full_day_case_study.svg)

这张图用于解释执行路径：TWAP 近似线性完成；Forecast VWAP 根据历史 profile 调整每 bar target；POV 随 realized market volume 加速，并在约午间前完成。价格路径显著低于 arrival price，因此 BUY 的 arrival shortfall 大幅为负，不能解释为算法创造 alpha。

### 2.2 Outcome table

| Algorithm | Completion | Average price | VWAP slippage | Modelled cost |
|---|---:|---:|---:|---:|
| TWAP | 100.0% | $302.5568 | −17.66 bps | $507.22 |
| Forecast VWAP | 100.0% | $302.7594 | −10.97 bps | $480.55 |
| POV | 100.0% | $303.0752 | −0.55 bps | $570.44 |

单日中，POV 最贴近 market VWAP，Forecast VWAP 的 modeled cost 最低，TWAP 的 BUY 成交均价最低；这些是不同 benchmark 下的不同维度，不能据一个 session 宣布总体赢家。可审计明细见 [`full_day_summary.csv`](figures/readme/full_day_summary.csv)。

## 3. Dynamic-Q comparison

### 3.1 Window construction and information timing

- 每个窗口包含 12 根 5-minute bars，即 60 分钟；
- 每隔 3 根 bar 启动一个窗口，即 15 分钟步长；
- 每日从 09:30–10:30 到 15:00–16:00，共 23 个窗口；
- 5 个测试 session 共 115 个窗口；
- 相邻窗口共享 9/12 根 bar，即 75% overlap；
- 测试日只使用之前 session 估计 Forecast VWAP profile；训练集从 1 日 expanding 到 5 日；
- 每个窗口使用 realized volume 做 ex-post 难度标准化：

$$
Q_w=\left\lfloor0.03\sum_{t\in w}V_t\right\rfloor.
$$

当前 $Q_w$ 范围为 170–1,217，中位数为 397。它不是实盘开始前可知的订单量；生产研究应使用 forecast window volume、ADV 或客户给定的 Q。

### 3.2 Distribution and win rate

![Delta IS distributions](figures/readme/02_delta_is_distribution.svg)

| Compared with TWAP | Mean ΔIS | Median ΔIS | Win rate | Completion |
|---|---:|---:|---:|---:|
| Forecast VWAP | +0.02 bps | −0.08 bps | 57.4% | 100.0% |
| POV | +0.84 bps | −0.26 bps | 51.3% | 100.0% |

`ΔIS < 0` 代表被比较算法优于 TWAP。Forecast VWAP 和 POV 都出现“median/win rate 看起来较好，但 mean ΔIS 为正”的现象：多数小幅改善被少数较大的正向尾部损失抵消。因此汇报时必须同时给 mean、median、win rate 和完整分布。

### 3.3 Volume × volatility regime

![Dynamic-Q regime heatmap](figures/readme/03_regime_heatmap.svg)

| Algorithm | Volume regime | Volatility regime | Windows | Mean ΔIS | Win rate |
|---|---|---|---:|---:|---:|
| Forecast VWAP | Low | Low | 37 | −0.25 bps | 62.2% |
| Forecast VWAP | Low | High | 20 | +0.47 bps | 25.0% |
| Forecast VWAP | High | Low | 20 | −0.21 bps | 65.0% |
| Forecast VWAP | High | High | 38 | +0.17 bps | 65.8% |
| POV | Low | Low | 37 | −2.56 bps | 64.9% |
| POV | Low | High | 20 | +0.55 bps | 40.0% |
| POV | High | Low | 20 | +3.91 bps | 40.0% |
| POV | High | High | 38 | +2.68 bps | 50.0% |

Dynamic Q 消除了之前低量窗口中 fixed Q 过大、TWAP/VWAP 都被 hard cap 压成相同 fill path 的问题。左上格因此从严格的 0 变为 Forecast VWAP `−0.25 bps`、POV `−2.56 bps`。

高量高波动格中 Forecast VWAP 的 win rate 为 65.8%，但 mean ΔIS 为 +0.17 bps，仍说明尾部损失不可忽略。regime 表只应视为描述性分组：窗口有重叠，每格样本也较少。

### 3.4 IS distribution and completion

![IS distribution by algorithm](figures/readme/04_is_distribution_by_algorithm.svg)

![Dynamic-Q completion rate](figures/readme/05_completion_rate.svg)

三种算法在全部 115 个 normalized windows 中均实现 100% completion，因此本轮 ΔIS 差异不是由 unequal fill ratio 驱动。完整表见：

- [`dynamic_q_summary.csv`](figures/readme/dynamic_q_summary.csv)
- [`dynamic_q_regime_summary.csv`](figures/readme/dynamic_q_regime_summary.csv)
- [`rolling_window_results.csv`](figures/readme/rolling_window_results.csv)

## 4. Relationship to the reference GitHub project

Reference：[`alicelmre2705/twap-vs-vwap-2026`](https://github.com/alicelmre2705/twap-vs-vwap-2026)

### 4.1 Aligned design choices

- 5-minute US equity regular-hours bars；
- 12-bar / 60-minute comparison windows；
- parent order normalized to 3% of window volume；
- TWAP baseline and historical-profile Forecast VWAP；
- ΔIS distribution、win rate、volume × volatility regime 和 IS boxplot。

### 4.2 Intentional differences

| Dimension | This project | Reference |
|---|---|---|
| Third strategy | Online-style POV | Realized-volume VWAP oracle |
| Per-bar cap | 20% | 5% |
| Unfilled target | Carry forward | No reallocation |
| Fill reference | HLC3 + spread + square-root impact + fees | Bar close; no explicit impact model |
| Forecast profile | Prior-session normalized shares的中位数 | Historical average intraday profile |
| Quantity | Integer, lot-aligned | Continuous formulas in README |
| Checked-in evidence | AAPL, 6 sessions | Reported five-ticker, ~60-day experiment |

POV 不是 reference 的 oracle。POV 只根据当前逐步实现的 market volume 调整；oracle 需要知道完整未来窗口 volume，只能作为事后上界。

### 4.3 Data reproducibility boundary

Reference README 描述的是通过 yfinance 下载的约 60 个交易日，而不是一个固定、带哈希的 OHLCV snapshot；因此“完全相同数据”会随运行日期变化，无法仅凭 README 唯一确定。本仓库提供 [`fetch_reference_universe.py`](Data_example/fetch_reference_universe.py)，按相同 universe `{AAPL, MSFT, AMZN, NVDA, SPY}`、5-minute frequency 和最多 60 个完整 session 建立 schema-v1 pickle：

```bash
python Data_example/fetch_reference_universe.py
```

当前 checked-in Review v2 图使用可离线审计的 AAPL fixture，没有把合成 ticker 或 reference 的 oracle 伪装成 POV。若要作严格 five-ticker replication，应固定下载日期、保存原始 OHLCV snapshot，并在该 snapshot 上重跑所有三种算法。

## 5. Recommended presentation flow

1. **Problem and algorithms**：TWAP、Forecast VWAP、POV 的 pacing signal；
2. **Two-layer methodology**：说明 fixed-Q case study 与 Dynamic-Q normalized comparison 不混用；
3. **Full-day case study**：用一张图解释 schedule、completion 和 price path；
4. **Dynamic-Q distribution**：mean、median、win rate 与尾部；
5. **Regime heatmap**：说明优势不是跨 regime 稳定存在；
6. **Completion and limitations**：100% completion、75% overlap、单 ticker、tick-volume 和 ex-post Q；
7. **Conclusion**：当前证据支持“行为和 regime dependence”，不支持生产级算法排名。

## 6. Review v2 deliverables

| Artifact | Purpose |
|---|---|
| [`00_full_day_case_study.svg`](figures/readme/00_full_day_case_study.svg) / [`PNG`](figures/readme/00_full_day_case_study.png) | Full-day fixed-Q 主图 |
| [`01_single_window_demo.svg`](figures/readme/01_single_window_demo.svg) / [`PNG`](figures/readme/01_single_window_demo.png) | Dynamic-Q 单窗口示例 |
| [`02_delta_is_distribution.svg`](figures/readme/02_delta_is_distribution.svg) / [`PNG`](figures/readme/02_delta_is_distribution.png) | ΔIS distribution 和 win rate |
| [`03_regime_heatmap.svg`](figures/readme/03_regime_heatmap.svg) / [`PNG`](figures/readme/03_regime_heatmap.png) | Volume × volatility regime |
| [`04_is_distribution_by_algorithm.svg`](figures/readme/04_is_distribution_by_algorithm.svg) / [`PNG`](figures/readme/04_is_distribution_by_algorithm.png) | IS boxplot |
| [`05_completion_rate.svg`](figures/readme/05_completion_rate.svg) / [`PNG`](figures/readme/05_completion_rate.png) | Completion rate |
| [`generate_readme_figures.py`](figures/generate_readme_figures.py) | 重建全部图表和 CSV |
| [`fetch_reference_universe.py`](Data_example/fetch_reference_universe.py) | 重建 reference-aligned five-ticker 数据入口 |

## 7. Limitations

1. 当前统计结果只有 AAPL 和 6 个 session；
2. 115 个窗口有 75% overlap，不是独立样本；
3. Dynamic Q 使用 realized window volume，属于 ex-post normalization；
4. provider volume 是 tick volume，不是 consolidated share volume；
5. rolling Forecast VWAP 的历史长度从 1 日扩展到 5 日，并不固定；
6. regime 使用样本内 median split，格子边界会随样本变化；
7. spread、impact 和 fee 参数没有用真实 fills 校准；
8. bar-level replay 无法模拟 intra-bar path、queue position、venue 和 adverse selection；
9. 单日 full-day 结果和 Dynamic-Q 结果回答不同问题，不能合并排名；
10. reference 的 rolling yfinance 数据不是固定 snapshot，跨运行日期的精确数值不可直接复现。
