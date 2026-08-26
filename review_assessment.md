# 对外部交易审查报告的复核与整改

复核对象：`report.md` 中 12 项交易/研究问题及 5 项工程问题。结论分为“正确”“部分正确”和“判断不成立”。正确项已在代码、测试、图表或披露中整改；无法凭当前数据可靠校准的模型项没有用任意参数伪装成已解决。

## 交易与研究问题

| Issue | 判断 | 原因与已执行修改 |
|---|---|---|
| 1. POV 使用同 bar 完整 volume | **正确** | 原实现若被解释为 bar-open 决策，确有 look-ahead。`pov()` 现默认使用一根 bar 滞后的 volume，首 bar target 为 0；`lag_bars=0` 仅保留为明确标注的非因果诊断。测试和所有图表均已重跑。20% hard cap 仍是区间结束后核验实际 fill feasibility 的约束，不是 scheduler 的未来输入。 |
| 2. 没有永久/累积冲击 | **正确，属于模型边界** | 当前平方根 impact 只是 bar 内临时冲击，不能识别永久冲击、信息泄露或后续价格反馈。仅凭 6 日 tick-volume OHLCV 无法校准可靠的 propagator/Almgren–Chriss 参数，因此未随意添加“永久冲击常数”。README 与研报明确把成本数值降级为教学模型结果。 |
| 3. 固定 spread 与 fee | **正确，但报告中的具体倍数不是普适事实** | 时变点差与 maker/taker 会改变成本；“AAPL 开盘一定为午间 2–5 倍”不能由本数据验证。数据 record 现可选带 `half_spread_bps`、`fee_per_share`，模拟器优先使用逐 bar 参数，默认常数仅作 fallback。 |
| 4. HLC/3 忽略 bar 内路径 | **正确** | 有真实 `bar_vwap` 时现优先使用；缺失时才回退 HLC/3。5-minute OHLCV 仍无法恢复先涨后跌、queue 或 adverse selection，文档继续披露该限制。 |
| 5. Dynamic-Q 使用 realized volume | **部分正确** | 它确实是 ex-post、不可直接部署的 sizing rule，这一点保留并强化披露。但“high-volume 订单绝对更大所以污染公平比较”并不自动成立：Q 与 window volume 同比例缩放，正是在控制相对 participation 难度。它适合研究归一化，不适合生产下单或因果推断；生产应改用客户 Q、ADV 或 forecast volume。 |
| 6. 75% overlap 与小样本 | **正确** | 主样本改为固定 5 个训练日、仅最后一日 23 个测试窗口；另生成 6 个非重叠窗口汇总。所有 win rate/regime 只按描述性结果表述，不作显著性推断。当前数据仍太短，不能声称问题已被根治。 |
| 7. carry 人为保证 POV 完成 | **判断不成立，但暴露完成风险的建议正确** | `carry` 只滚动“已经由 scheduler 产生、但因 hard cap 未成交”的 target；它不会把尚未被 POV participation rule 调度的母订单塞入后续 bar，也不会收盘强制补单。原 3% Q 在 10% POV rate 下能完成，主要因为订单小于可调度量，不是 carry 保证。已新增 3%/5%/10%/15% 完成率敏感性：POV 在 10% Q 时平均完成 91.3%，15% 时仅 60.9%，完成风险现已被量化。 |
| 8. 单日价格路径被当作 alpha | **对风险的提醒正确，对当前文档的指控过时** | README 原本已经明确说明单日下跌主导 BUY arrival IS，Figure 1 的结果表也没有展示 Arrival bp。现进一步只把单日案例作为路径说明，并同时报告 market-VWAP slippage、modelled cost；不能用它排名长期算法。 |
| 9. VWAP profile 历史异质、缺失 slot、结构过简 | **大部分正确** | Dynamic-Q 现在固定使用恰好 5 个此前 session，不再混用 1–5 日 expanding history；任何训练 session 缺 target slot 会报错，不再静默填 0。当前记录只到 15:55、代表连续交易的最后 5 分钟区间，没有单独 auction print，因此“把 auction bar 当连续 bar”不适用于这份 fixture。weekday/event/reforecast 仍是后续工作。 |
| 10. 3% 小单未呈现 TWAP 流动性风险 | **正确** | 新增订单比例敏感性图和 CSV。15% 时 TWAP/VWAP 开始出现轻微未完成，POV 明显未完成；主 ΔIS 比较仍只使用 3%，以避免 unequal completion 污染成本比较。 |
| 11. 只测 BUY/AAPL/6 日 | **正确** | 本地没有可信的多标的长历史 consolidated 数据，不能制造样本。已保留五标的约 60 日抓取脚本，并强化“当前只作 AAPL 教学演示”的边界。正式实证仍需固定原始 snapshot，并加入 SELL 与不同流动性标的。 |
| 12. IS 含费、fee benchmark、arrival/open | **部分正确** | Implementation Shortfall 实务中可报告含显式成本的 net IS，因此“费用必须永远单列”不是唯一标准。问题在于口径必须透明且分母一致。结果现同时给出不含费用的 `*_price_*_bps` 与含费用的净指标；VWAP fee bps 改用 market-VWAP notional。Arrival=open 是订单在首 bar open 到达时的明确 benchmark；HLC/3 是 fill proxy 的局限，不是自动构成 benchmark gaming。 |

## 工程问题

| 项目 | 判断与处理 |
|---|---|
| 字体路径与 import 失败 | **正确，已修复。** 依次尝试 Pillow/系统 DejaVu/Arial，并有 `load_default()` fallback；缺字体不再阻断 pytest collection。 |
| 任意 pickle 反序列化 | **正确，已修复信任边界。** 默认只允许仓库内 fixture；外部 pickle 必须显式 `--allow-unsafe-pickle`，推荐 JSON。 |
| 缺失 slot 静默补 0 | **正确，已修复。** 训练 session 缺任一目标 slot 时立即报错。 |
| 测试硬编码 fixture 常数 | **不属于缺陷本身。** 日期、78 bars 和窗口数是 checked-in fixture 的回归契约；fixture 改变时测试应显式更新，而非放松到无法发现数据漂移。已新增因果 POV、profile 完整性、pickle 信任、gross/net 指标、非重叠窗口与完成率敏感性测试。 |
| 绘图重复、`sys.path`、下载重试 | **维护性建议正确。** 本轮加入 Yahoo 指数退避重试；绘图去重与包结构重构不影响金融结论，留作后续独立重构，避免在研究整改中引入大范围无关变更。 |

## 整改后的可靠边界

- 可靠：三种算法的 pacing 逻辑、因果化 POV 的路径差异、Forecast VWAP 的严格历史/测试隔离、整数与完成率语义。
- 描述性：23 个重叠窗口和 6 个非重叠窗口上的 ΔIS、胜率与 regime 图。
- 不可靠外推：绝对成本、长期算法排名、显著性、consolidated-share participation、永久冲击和生产选型。

所有整改结果由 `12 passed` 的测试覆盖，图表与 CSV 已从修改后的实现重新生成。
