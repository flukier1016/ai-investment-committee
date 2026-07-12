# 旧静态页数据迁移说明

旧版单文件静态页 `AI投委会_静态页面html.html`（约 1.5MB，11 个 Tab）的全部业务数据
位于其第 255 行的单个内联 JSON（约 414KB，13 个顶层键）。本项目用
`scripts/extract_legacy_fixtures.py` 抽取其中口径兼容的数据块，写入
`data/demo/legacy/`，并做以下迁移处理。

## 一、资产口径映射（28 → 27）

旧版 28 资产含**两条现金腿**（`cash_cny` 人民币现金 / `cash_usd` 美元现金），
新版按交接文档合并为单一 `cash`。权重类字典迁移时两腿相加。

旧资产 id → 新资产 id：

| 旧 id | 新 id | 说明 |
|---|---|---|
| spx | spy | 标普500 |
| ndx | qqq | 纳斯达克100 |
| sx5e | fez | 欧洲斯托克50 |
| nky | ewj | 日本股票 |
| kospi | ewy | 韩国股票 |
| hsi | hsi_2800 | 恒生指数 |
| dividend | dividend_510880 | 上证红利 |
| tbond_fut | cgb10y_fut | 10Y国债期货 |
| credit_aaa | aaa_cp_3y | AAA中短票 |
| ust_fut | us10y_zn | 美10Y期货 |
| copper_sh | copper | 沪铜 |
| cash_cny + cash_usd | cash | 双现金腿合并 |

资讯库（`knowledge`）的资产标签使用第三套 id（oil/dxy/usdcnh/ust10/cgb…），
在抽取脚本中单独建映射表处理。

## 二、已迁移为 fixture 的数据（data/demo/legacy/）

| 文件 | 来源 | 用途 | 处理 |
|---|---|---|---|
| market_snapshot.json | `market_snapshot` | 参考 | 28→27 并腿 |
| methodology_cards.json | `methodology` | 方法论出处卡 | 只保留四方法；yale/mvo_bl 存档标注 |
| news_library.json | `knowledge` 195条 | 资讯 Demo 素材 | 资产标签映射 + `publish_ts` 日末代理 |
| spread_desk_report.json | `debate.desk_report` | 利差台参考 | legs 并腿 |
| risk_officer_report.json | `debate.risk_report` | 宏观事件日历（驾驶舱/利差台展示） | 原样 |
| live_daily_history.json | `live` | 日更参考 | 删除六引擎 top_engine 字段 |
| personality_quiz.json | `profile` | 投资性格问卷（配置页可选 Demo） | 明确标注只映射风险参数 |
| ops_metrics.json | `ops_metrics` | 工程效能参考 | 原样 |

所有 fixture 带 `"source": "legacy_static_page"` 标记与 as-of 时间。旧资讯只有
`published` 日期，没有真实发布时刻；抽取器保留原字段，并确定性补
`publish_ts = YYYY-MM-DDT23:59:59Z`。这是防同日回测前视的保守日末可见代理，
不冒充真实发布时间，策略写在 `news_library.json._meta.publish_ts_policy`。

## 三、不迁移 / 必须重算的旧口径

- **六引擎辩论全记录**（`debate` 的 openings/rebuttals/verdict/engine_scores）——
  新架构无六引擎投票，废弃。
- **`profile.engine_priors`**（六引擎信任权重）——废弃；投资性格只映射风险参数。
- **v3 回测净值 12 条序列**（`backtest`）——committee/eng_equal/追最强等基准
  均为六引擎口径，全部由新引擎从 Demo 价格面板重算（`backend/app/domain/backtest.py`）。
- **`report_md` 周报**——第二章整章引用六引擎辩论；新版由本周 DecisionRecord
  结构化生成（`backend/app/services/weekly.py`）。
- **`scenarios[].verdict_weights` / `top_engine`**——重算；新版情景回放调用
  真实引擎在该 as-of 重算完整决策链。
- **旧 v4 块中 `tsmom.layer="strategic"`**——错误层级；新版 TSMOM 固定为
  tactical（战术偏离），Risk Parity 是唯一战略底仓。

## 四、运行数据与旧数据的边界

新项目**不在运行时读取任何旧 HTML 或 legacy fixture 参与计算**。计算链路的
唯一输入是 `data/demo/` 下的确定性合成数据（`market_prices.csv` / `macro.csv` /
`erp_inputs.csv`，由 `scripts/generate_demo_data.py` 固定种子生成，含
point-in-time 发布日）。legacy fixture 只用于展示性内容（事件日历、问卷、
方法论文案、资讯库），页面中均标注来源。`domain/news.py` 的
`news_asof_filter()` 只建立未来真实新闻接入前的可见性红线，本阶段不把 legacy
资讯接入 MarketSlice、输入指纹、信号或权重链。
