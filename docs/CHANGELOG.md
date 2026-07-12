# 变更日志

本文件按可验收里程碑记录已经合并的产品与工程能力。项目尚未建立统一的产品
发布版本或 Git tag；规格、包和引擎各自的版本号不作为本日志的里程碑版本，运行
记录仍以 Git SHA 作为 `code_version`。每条能力都引用仓库内可直接定位的 pytest
测试函数或 Playwright 测试标题。

## 维护纪律

1. 每个合并到 main 的功能或修复变更范围必须更新“未发布”，或直接加入当天的
   里程碑；纯文档、测试整理和工程杂务可不单列。
2. 每条能力使用 `路径::测试函数或测试标题` 引用至少一个验收测试；不接受只写
   测试文件、人工截图或“已验证”。
3. 发布里程碑时只移动“未发布”条目并补日期，不改写历史验收名。
4. 后端 CI 按一次 PR/push 的聚合变更范围检查：只要受管的运行或构建路径发生
   变化，本文件必须新增一个带验收引用的能力条目；不要求 PR 内每个原子提交
   分别改日志。

## 未发布

- **前端图表配色纪律**：五个含 ECharts 的页面（回测、组合驾驶舱、日更、情景、
  利差台）的图表颜色统一取自 `meta.ts` 的 SOLID 常量与随主题取值的
  `chartTheme()`，暗色主题不再被写死的亮色网格线（旧 `#dde4db`）刺穿；利差台
  策略记分牌 Sharpe 柱改为红涨绿跌方向，与本页收益列及全站一致。前端只改渲染
  配色，不触碰任何后端业务数字。
  验收：`frontend/e2e/chart-palette.spec.ts::图表页颜色只走 SOLID / chartTheme，无写死 hex 与亮色网格`、
  `frontend/e2e/chart-palette.spec.ts::图表在暗色主题下正常渲染（网格随主题重构未破坏图表）`。

- **LLM 客户端瘦身基建**：固定三类 provider 共用一套惰性
  OpenAI-compatible transport；默认路径零可选 SDK，安全运行身份进入有效配置
  指纹。内容寻址 trace 以私有权限原子落盘，同调用 first-write-wins 并可重放；
  本阶段不接真实新闻或决策权重链。
  验收：`tests/backend/test_llm_foundation.py::test_registry_is_frozen_and_contains_exactly_three_provider_types`、
  `tests/backend/test_llm_foundation.py::test_effective_config_fingerprint_preserves_default_and_tracks_llm_identity`、
  `tests/backend/test_llm_foundation.py::test_sdk_factory_receives_fixed_endpoint_timeout_and_native_max_retries`、
  `tests/backend/test_llm_foundation.py::test_runtime_mock_call_persists_then_replays_without_factory_or_sdk`、
  `tests/backend/test_llm_foundation.py::test_runtime_replay_rejects_schema_valid_cache_with_bogus_citation`、
  `tests/backend/test_llm_foundation.py::test_public_api_cannot_enable_llm_or_spend_server_credentials`、
  `tests/backend/test_llm_foundation.py::test_replay_serializes_same_call_and_concurrent_distinct_calls_survive`。

## 2026-07-12 · 交付队列 1–7

- **五档立场刻度**：由确定性代码统一生成七桶立场，周报、权重层和结果命中统计
  共用同一枚举；旧决策记录仍可加载。
  验收：`tests/backend/test_stance.py::test_four_stance_thresholds_and_both_sides`、
  `tests/backend/test_stance.py::test_old_decision_record_defaults_and_consumers_share_central_stances`、
  `frontend/e2e/stance.spec.ts::L3 逐桶展示后端五档立场并支持中英移动端`。

- **确定性决策纪要**：从已落库决策生成五段式 Markdown，完整保留三层权重、
  观点参数、归因、护栏与血缘，并通过只读 API 导出。
  验收：`tests/backend/test_report.py::test_report_is_byte_deterministic_and_covers_five_sections_and_three_layers`、
  `tests/backend/test_report.py::test_report_api_returns_canonical_markdown_and_missing_id_is_404`。

- **可追溯命令行**：提供 run、backtest、trace、report 四个直调确定性引擎的命令，
  trace 可从归因下钻到观点、信号和输入哈希。
  验收：`tests/backend/test_cli.py::test_entrypoint_and_help_register_exact_four_commands`、
  `tests/backend/test_cli.py::test_trace_reads_record_and_keeps_all_views_signals_hashes_and_full_method_names`。

- **Docker 一键复现**：Node 构建前端、Python 非 root 运行，同一服务托管 API 与
  SPA；只读根文件系统下仅持久化命名运行卷，并保留 Git 修订血缘。
  验收：`tests/backend/test_docker.py::test_dockerfile_multistage_paths_non_root_and_health_contract`、
  `tests/backend/test_docker.py::test_compose_build_run_non_root_health_and_volume_persistence`。

- **风控三视角点评**：激进、保守、中性三组点评完全由波动预算利用率、距上限
  余量和换手代理确定性生成；前端直接展示后端值并使用共同中性色。
  验收：`tests/backend/test_risk_perspectives.py::test_record_derivation_is_deterministic_exact_and_non_mutating`、
  `frontend/e2e/risk-perspectives.spec.ts::三人格固定展示后端值并支持中英移动端`、
  `frontend/e2e/risk-perspectives.spec.ts::三人格亮暗主题只使用共同中性色且不套涨跌类`。

- **新闻 point-in-time 前置契约**：按调用方 as-of 过滤未来新闻；回测对无时间新闻
  fail-closed，live 保留无时间新闻。旧展示资讯补保守日末代理时间，但尚未接入
  MarketSlice、输入指纹、信号或真实新闻源。
  验收：`tests/backend/test_news_asof.py::test_future_articles_are_filtered_and_boundary_is_visible`、
  `tests/backend/test_news_asof.py::test_backtest_drops_every_missing_publish_ts_without_published_fallback`、
  `tests/backend/test_news_asof.py::test_live_keeps_missing_in_place_but_still_filters_known_future`。

- **CHANGELOG 纪律**：按日期和交付里程碑回填历史能力；能力条目只能引用仓库内
  可解析的验收测试，后续受管运行或构建路径的变更范围必须新增能力条目。
  验收：`tests/backend/test_changelog.py::test_every_changelog_entry_has_resolvable_acceptance_test`、
  `tests/backend/test_changelog.py::test_product_change_range_adds_changelog_capability`。

## 2026-07-11 · 确定性运营闭环

- **决策结果账本与委员会复核**：决策经历 pending 到 resolved 的幂等生命周期，
  委员会论据保留可回链引用，前端展示正反检验与结果账本。
  验收：`tests/backend/test_outcomes_committee.py::test_pending_then_resolve_lifecycle`、
  `tests/backend/test_outcomes_committee.py::test_committee_review_refs_are_traceable`、
  `frontend/e2e/app.spec.ts::委员会正反检验与结果账本`。

- **结构化模型降级契约**：模型缺失、异常、幻觉引用或自由文本象限一律降级或
  拒绝，战术输入缺失时只允许显式 abstain 与确定性先验回退。
  验收：`tests/backend/test_llm_contract.py::test_client_exception_degrades_to_abstain_never_freetext`、
  `tests/backend/test_llm_contract.py::test_hallucinated_citation_rejected`、
  `tests/backend/test_degraded_inputs.py::test_all_tactical_missing_falls_back_to_prior`。

- **数据与约束失效保护**：未来数据不得进入切片，不可行约束响亮失败，新增字段
  的决策记录仍可 JSON 往返加载。
  验收：`tests/backend/test_data_guards.py::test_slice_never_contains_future_data`、
  `tests/backend/test_robustness.py::test_infeasible_constraints_fail_loud_not_invalid_weights`、
  `tests/backend/test_robustness.py::test_decision_record_json_roundtrip_with_new_fields`。

## 2026-07-11 · 原子持久化修复

- **决策记录并发写入**：每次保存使用唯一临时文件和原子替换，并发读取不再看到
  半写 JSON。
  验收：`tests/backend/test_robustness.py::test_store_save_concurrent_no_partial_reads`。

- **结果账本并发写入**：结果账本使用每次写入唯一的临时文件，消除并发写入者
  抢占固定临时路径的竞态。
  验收：`tests/backend/test_outcomes_committee.py::test_outcomes_concurrent_writes`。

## 2026-07-11 · 五方法三层可运行基线

- **确定性三层配置引擎**：Risk Parity 战略底仓与 Time Series Momentum、
  Merrill Lynch Investment Clock、Equity Risk Premium 战术观点经
  Black-Litterman Model 融合，资产、桶、类别和预算中性归因严格闭合；同一输入
  得到同一决策。
  验收：`tests/backend/test_acceptance.py::test_asset_weights_sum_to_one`、
  `tests/backend/test_acceptance.py::test_attribution_closure_after_guardrails`、
  `tests/backend/test_acceptance.py::test_determinism`。

- **市场数据时点纪律**：合成市场、宏观与风险溢价数据按 as-of 切片，发布日前的
  宏观数据不会进入历史决策。
  验收：`tests/backend/test_acceptance.py::test_point_in_time_no_future_leak`、
  `tests/backend/test_data_guards.py::test_slice_never_contains_future_data`。

- **九模块与三层溯源前端**：首页展示信号、观点和权重的完整链路，支持观点矩阵、
  血缘回链、27 项明细资产、中英双语和移动端，并只显示五个英文全称方法名。
  验收：`frontend/e2e/app.spec.ts::三层同屏 + 顶部最终结果在前`、
  `frontend/e2e/app.spec.ts::可见区域不出现方法简称`、
  `frontend/e2e/app.spec.ts::技术工作台：P 矩阵 27 列 + 行跳计算`。
