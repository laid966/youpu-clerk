"""★ 这是你的文件 ★ 审计策略：成本 / 召回 / 人工工作量三者的取舍。

这个文件决定审计器的"性格"：**愿意花多少钱、允许漏多少、让人看多少。**
三个数字互相拉扯，没有免费的午餐：

| 你调大这个 | 召回 | 成本 | 人工工作量 |
|---|---|---|---|
| `inspect_scope` 从"只查异常项"改成"全查" | ↑ | ↑ | 不变 |
| `max_model_calls_per_artifact` | ↑ | ↑ | 不变 |
| `accept_model_findings` 设 False | ↓ | 不变 | ↓ |
| `escalate_*` 加更多类目 | 不变 | 不变 | ↑（但漏得少） |

**你的任务**：把它调到你认为对的位置，并**说明理由**。
理由要能回答：在医疗场景里，一次漏报和一次误报，哪个代价更大？为什么？

## 一份有用的参考思路

审计器有两种错：
- **漏报**（该报的没报）→ 用户看到一份有问题的解读却不知道 → 后果可能很严重
- **误报**（不该报的报了）→ 人工要去核一遍 → 浪费人力，多了就没人用

这两者不对称。**如果你认为漏报代价远大于误报，就该把 `inspect_scope` 调宽、
把 `escalate_categories` 加全**——然后接受成本和人工负担上升。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AUDIT_POLICY", "AuditPolicy", "INSPECT_SCOPES"]

#: 语义检查的范围。改这个会直接改变成本与召回。
INSPECT_SCOPES = (
    "abnormal_only",  # 只查异常指标（默认：便宜，但可能漏掉正常项里的越界表述）
    "all",  # 每一个指标都查（最贵，召回最高）
    "with_citations_only",  # 只查有依据的指标（折中）
)

#: **所有可能出现的越界类别**。有**两个来源**，改任何一个都要回到这里对账：
#:
#: 1. 提示词（`agent/prompts.py` 的 JSON 模板里声明的 `category` 枚举）
#: 2. 护栏（`agent/guardrails.py` 每条 `GuardrailRule` 的 `category`）
#:
#: ⚠️ 漏登记的后果**不是报错**，而是这一类结论会走"未知类别 fail-safe"——
#: 结果往往是**对的**（确实该升级人工），但**理由是错的**：
#: 一旦有人把 `escalate_unknown_category` 关掉、或者改了类别名的拼写，
#: 保护就会无声消失。**跨文件的约定必须有测试守着**，
#: 靠注释提醒是没用的——这条规矩是被真实事故逼出来的
#: （见 `tests/test_invariants.py` 的一致性测试）。
KNOWN_CATEGORIES = (
    "diagnosis",
    "treatment",
    "dosage",
    "guidance",
    "prognosis",
    "plan",  # 提示词 v2 引入：具体执行方案（劝阻就医、量化处方、复查安排）
    "conclusion",  # 护栏引入：结论性表达（替医生定性）
)


@dataclass(frozen=True)
class AuditPolicy:
    # ---- 查多少 ----
    inspect_scope: str = "all"
    max_model_calls_per_artifact: int = 12

    # ---- 信多少 ----
    accept_model_findings: bool = True
    require_verifiable_evidence: bool = True
    """模型的结论必须能在原文里找到它引用的那句话，否则丢弃。

    这一条是**可编程验证**的（evidence 是否真出现在文本里），
    所以它不是"信任模型"，而是"要求模型自证"。强烈建议保持打开。
    """

    # ---- 让人看多少 ----
    escalate_categories: tuple[str, ...] = ("diagnosis", "treatment", "plan", "conclusion")
    """**这一类越界一律交给人。** 只列"漏一条代价很大"的那些。

    - `plan`（具体执行方案）：含"劝阻就医""量化处方"——**替医生做决定，漏一条最危险**
    - `conclusion`（结论性表达）：护栏抓到的替医生定性

    ⚠️ **登记进 `KNOWN_CATEGORIES` 之后必须同时出现在这里。**
    只登记、不升级，会让这一类结论**从"fail-safe 兜底升级"变成"静默放行"**——
    保护消失，而且没有任何报错。这个坑验证过，见 `docs/10-你的任务.md` 的 T8。
    """
    escalate_on_critical_severity: bool = True
    escalate_unknown_category: bool = True
    """出现没见过的类别时默认升级给人。

    fail-safe 原则：**不认识的东西不要自己决定。** 你的提示词一旦引入新类别，
    要么补进 KNOWN_CATEGORIES，要么接受它全部升级人工。
    """

    def describe(self) -> str:
        return (
            f"范围={self.inspect_scope} "
            f"| 单份模型调用上限={self.max_model_calls_per_artifact} "
            f"| 接受模型结论={self.accept_model_findings} "
            f"| 证据必须可验证={self.require_verifiable_evidence} "
            f"| 升级类目={','.join(self.escalate_categories) or '无'} "
            f"| 危急必升级={self.escalate_on_critical_severity}"
        )


#: 当前生效的策略。★改这里★，改完跑：
#:     .\.venv\Scripts\python.exe -m agent audit --limit 40
#: 对比不同策略下的召回、误报、模型调用数与人工升级数。
AUDIT_POLICY = AuditPolicy()
