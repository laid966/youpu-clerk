# 变异测试报告（A6）

> 故意把流水线改坏，看**测试套件抓不抓得住**。
> 抓住叫「杀死」，没抓住叫「存活」——**存活的变异体就是测试盲区**。

## 变异得分

**100.0%**（杀死 17 / 必须杀死 17）

另有 1 个变异体属于**允许存活**的可调旋钮（成本/范围类参数，见下表标注），不计入得分。

**预期杀手命中率：100.0%**（17 / 18）

> 第二栏比第一栏更值钱：变异体被杀死了、但**不是预期那条测试杀的**，
> 说明我以为在守它的测试其实没守，是别的测试顺带守住的。
> 一旦那条别的测试被改动，这个不变量就没人守了。

无效变异体 0 个（目标代码片段不唯一，不计入分母）

## 逐个变异体

| 编号 | 改成什么 | 结果 | 预期杀手命中 | 实际失败的测试 | 它守住的不变量 |
|---|---|---|---|---|---|
| M01 | 去掉数值一致性检查的相对容差（0.01 → 0） | ✅ 杀死 | ✅ | `tests/test_agent_graph.py::test_run_batch_catches_paraphrases_with_fake_judge`, `tests/test_agent_graph.py::test_hard_negative_phrases_are_not_flagged_by_fake_judge` 等 5 条 | 正常显示取整不该被误报成数值抄错 |
| M02 | 忽略域声明的默认结论 | ✅ 杀死 | ✅ | `tests/test_app.py::test_cases_list_does_not_leak_ground_truth`, `tests/test_app.py::test_artifact_endpoint_returns_items` 等 11 条 | 分级域里「没有规则命中」等于全部正常，不是规则缺口 |
| M03 | 关掉全部转人工判断（escalated 恒为 False） | ✅ 杀死 | ✅ | `tests/test_adjudicate.py::test_amount_threshold_triggers_escalation`, `tests/test_adjudicate.py::test_promotional_ticket_is_not_refundable` 等 12 条 | 该转人工的必须转人工 |
| M04 | 忽略规则优先级（按 id 排序） | ✅ 杀死 | ✅ | `tests/test_adjudicate.py::test_14_day_rule_beats_generic_tier`, `tests/test_adjudicate.py::test_business_cabin_overrides_generic_tier` 等 11 条 | 高优先级规则必须压过低优先级规则 |
| M05 | 去掉金额四舍五入到分 | ✅ 杀死 | ✅ | `tests/test_adjudicate.py::test_rounding_is_half_up_to_cent`, `tests/test_adjudicate.py::test_no_float_artifacts` 等 5 条 | 金额必须四舍五入到分 |
| M06 | 把干净样本比例改成 0（消灭误报率的分母） | ✅ 杀死 | ✅ | `tests/test_agent.py::test_semantic_cases_are_targeted`, `tests/test_agent.py::test_negatives_are_hardened` 等 14 条 | 没有干净样本就测不出误报率 |
| M07 | 让护栏一条都匹配不上（词表失效） | ✅ 杀死 | ✅ | `tests/test_agent.py::test_guardrails_catch_obvious_violations`, `tests/test_agent.py::test_guardrail_short_circuits_the_model` | 露骨的越界写法必须被词表挡住 |
| M08 | 关掉「模型结论必须交得出原文依据」的校验 | ✅ 杀死 | ✅ | `tests/test_agent_graph.py::test_reflect_rejects_finding_without_verifiable_evidence` | 模型编造的结论必须被挡住 |
| M09 | 去掉标题重复（检索的字段加权失效） | ✅ 杀死 | ✅ | `tests/test_rag.py::test_metric_chunk_carries_keywords_and_repeats_title` | 标题重复是对指标名的加权，去掉会改变排序 |
| M10 | 让改写型越界里混进禁用词（基准就失去意义了） | ✅ 杀死 | ✅ | `tests/test_inject.py::test_paraphrased_safety_violations_avoid_the_banned_word_list`, `tests/test_inject.py::test_every_recorded_defect_actually_exists` | 改写型越界必须真的绕开词表，否则不能证明语义检查的必要性 |
| M11 | 缺省策略关掉「危急值必须升级人工」 | ✅ 杀死 | ✅ | `tests/test_invariants.py::test_shipped_policy_keeps_safety_invariants` | 出厂默认就该是安全的：危急值默认必须人工 |
| M12 | 缺省策略把检查范围从「只查异常」改成「全查」（成本涨 10 倍） | ❌ **存活** | ⚠️ 否 | — | 这是一个**成本旋钮**，刻意留给使用者调（见 docs/10-你的任务.md 的 T5）。用测试钉死具体取值会阻止正常调整——只要求有测试保证取值合法。 |
| M13 | 缺省策略关掉「模型结论必须交得出原文依据」 | ✅ 杀死 | ✅ | `tests/test_agent_graph.py::test_reflect_rejects_finding_without_verifiable_evidence`, `tests/test_invariants.py::test_shipped_policy_keeps_safety_invariants` | 反幻觉校验默认必须开着 |
| M14 | 关掉 BM25 的文档长度归一化（b=0.75 → 0） | ✅ 杀死 | ✅ | `tests/test_invariants.py::test_bm25_parameters_are_pinned` | 长度归一化影响排序质量，改坏应当被检索指标发现 |
| M15 | 把 BM25 的词频饱和参数调到几乎无饱和（k1=1.5 → 50） | ✅ 杀死 | ✅ | `tests/test_invariants.py::test_bm25_parameters_are_pinned`, `tests/test_rag.py::test_baseline_does_not_regress` | k1 控制词频饱和，极端取值会让长文档被过度奖励 |
| M16 | 放宽评测的匹配规则：只看指标名，不看检查器 | ✅ 杀死 | ✅ | `tests/test_invariants.py::test_evaluation_matching_requires_same_detector` | 匹配必须同时看检查器与指标，否则乱报的检查器也能蹭到召回率 |
| M17 | 让数值一致性检查对任何偏差都放行（容差 1% → 100%） | ✅ 杀死 | ✅ | `tests/test_detect.py::test_value_mismatch_is_caught` | 数值抄错必须被抓到 |
| M18 | 忽略单份模型调用上限（成本护栏失效） | ✅ 杀死 | ✅ | `tests/test_agent_graph.py::test_model_call_cap_is_enforced_and_noted` | 成本上限必须真的生效 |

## 测试盲区（存活 = 改坏了测试也没反应）

- **M12**：缺省策略把检查范围从「只查异常」改成「全查」（成本涨 10 倍）
  - 目标文件：`agent/policy.py`
  - 本该由这条测试抓住：`(不要求被杀死)`
  - 它守住的不变量：这是一个**成本旋钮**，刻意留给使用者调（见 docs/10-你的任务.md 的 T5）。用测试钉死具体取值会阻止正常调整——只要求有测试保证取值合法。

## 这个数字的边界（必须一起读）

这里只覆盖**单元测试能杀死的变异体**（改代码、改数据）。
提示词层面的弱化单元测试杀不掉——单元测试用的是假模型，
提示词改了它看不出来。那类变异要靠**语义评测的指标门槛**来杀，属于后续工作。

所以：**不要把变异得分当成「测试覆盖率」来读**，它衡量的是「这些测试是否真的在守东西」。
