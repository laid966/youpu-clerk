"""审计图的节点。

六个节点，各管一件事：

| 节点 | 职责 | 花钱吗 |
|---|---|---|
| `plan` | 按策略决定"查哪些指标" | 否 |
| `inspect_deterministic` | 跑六个确定性检查器 | 否 |
| `inspect_semantic` | 对计划内的指标跑语义检查 | **是** |
| `reflect` | 自我反驳：模型结论必须能在原文里找到依据 | 否 |
| `decide` | 合并、去重、按策略决定谁升级人工 | 否 |
| `human_review` | 标记需要人工接住（真正的 HITL 中断在后续做） | 否 |
| `finalize` | 产出可读的审计结果 | 否 |

**只有一步花钱**，这是刻意的：能用程序判的全在前一步做完了。

`reflect` 值得单独说：它不是"再问一次模型"，而是**一条可编程验证的要求**——
模型说某句越界，就必须把它引用的原句交出来；交不出来、或那句子虚乌有，
这条结论就被丢掉。这比"再让模型确认一次"便宜、确定，而且真的能挡住编造。
"""

from __future__ import annotations

from typing import Any, Sequence

from agent.guardrails import apply_guardrails
from agent.judge import Judge
from agent.policy import KNOWN_CATEGORIES, AuditPolicy
from agent.prompts import current_prompt
from agent.semantic_check import check_text
from audit.artifact import Artifact
from audit.detect import Finding, detect
from audit.pipeline import Metric, severity_rank

__all__ = ["AuditNodes"]


class AuditNodes:
    def __init__(
        self,
        policy: AuditPolicy,
        judge: Judge,
        metrics: Sequence[Metric],
        prompt: str | None = None,
    ) -> None:
        self.policy = policy
        self.judge = judge
        self.metrics = tuple(metrics)
        self.prompt = prompt or current_prompt()

    # ------------------------------------------------------------------ #
    # plan
    # ------------------------------------------------------------------ #

    def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        artifact = Artifact.from_dict(state["artifact"])
        scope = self.policy.inspect_scope

        if scope == "all":
            codes = [item.code for item in artifact.items]
        elif scope == "with_citations_only":
            codes = [item.code for item in artifact.items if item.citations]
        elif scope == "abnormal_only":
            codes = [
                item.code
                for item in artifact.items
                if severity_rank(item.severity) > 0
            ]
        else:
            raise ValueError(f"未知的 inspect_scope：{scope}")

        codes = sorted(codes)
        return {
            "planned_codes": codes,
            "semantic": [],
            "deterministic": [],
            "rejected": [],
            "accepted": [],
            "escalated": False,
            "escalation_reasons": [],
            "model_calls": 0,
            "notes": [f"策略：{self.policy.describe()}", f"计划检查 {len(codes)} 个指标"],
        }

    # ------------------------------------------------------------------ #
    # inspect（确定性）
    # ------------------------------------------------------------------ #

    def inspect_deterministic(self, state: dict[str, Any]) -> dict[str, Any]:
        artifact = Artifact.from_dict(state["artifact"])
        findings = detect(
            artifact,
            state["report_values"],
            state["sex"],
            state["age"],
            self.metrics,
        )
        return {
            "deterministic": [self._finding_to_dict(f, detector=f.detector) for f in findings]
        }

    # ------------------------------------------------------------------ #
    # inspect（语义）
    # ------------------------------------------------------------------ #

    def inspect_semantic(self, state: dict[str, Any]) -> dict[str, Any]:
        artifact = Artifact.from_dict(state["artifact"])
        limit = self.policy.max_model_calls_per_artifact

        found: list[dict[str, Any]] = []
        calls = 0
        truncated = False

        for code in state.get("planned_codes", []):
            if calls >= limit:
                truncated = True
                break
            item = artifact.item(code)
            outcome = check_text(item.explanation, code, self.prompt, self.judge)

            # 命中护栏时没有调用模型；其余情况（含解析失败）都算一次调用
            called = not (outcome.finding is not None and outcome.finding.decided_by == "guardrail")
            if called:
                calls += 1

            if outcome.finding is not None:
                found.append(
                    self._finding_to_dict(
                        outcome.finding,
                        detector="semantic_check",
                        text=item.explanation,
                    )
                )

        notes = list(state.get("notes", []))
        notes.append(f"语义检查：调用模型 {calls} 次")
        if truncated:
            notes.append(
                f"⚠️ 达到单份调用上限 {limit}，本轮未查完全部计划指标"
                "（这是为了控成本，会让召回下降——要不要放宽由策略决定）"
            )

        return {"semantic": found, "model_calls": calls, "notes": notes}

    # ------------------------------------------------------------------ #
    # reflect
    # ------------------------------------------------------------------ #

    def reflect(self, state: dict[str, Any]) -> dict[str, Any]:
        artifact = Artifact.from_dict(state["artifact"])
        kept: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for finding in state.get("semantic", []):
            if not self.policy.accept_model_findings and finding["decided_by"] == "model":
                rejected.append({**finding, "reject_reason": "策略设置为不接受模型结论"})
                continue

            if self.policy.require_verifiable_evidence and finding["decided_by"] == "model":
                text = artifact.item(finding["target"]).explanation
                evidence = str(finding.get("evidence", "")).strip()
                if not evidence or evidence not in text:
                    rejected.append(
                        {**finding, "reject_reason": "结论引用的原句无法在文本中定位（疑似编造）"}
                    )
                    continue

            kept.append(finding)

        return {"semantic": kept, "rejected": rejected}

    # ------------------------------------------------------------------ #
    # decide
    # ------------------------------------------------------------------ #

    def decide(self, state: dict[str, Any]) -> dict[str, Any]:
        artifact = Artifact.from_dict(state["artifact"])

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for finding in state.get("deterministic", []):
            merged[(finding["detector"], finding["target"])] = finding
        for finding in state.get("semantic", []):
            merged.setdefault((finding["detector"], finding["target"]), finding)

        accepted = list(merged.values())
        accepted.sort(key=lambda item: (item["target"], item["detector"]))

        reasons: list[str] = []
        if self.policy.escalate_on_critical_severity:
            critical = [
                item.code for item in artifact.items if item.severity == "critical"
            ]
            if critical:
                reasons.append(f"存在危急值判定：{', '.join(sorted(critical))}")

        for finding in accepted:
            category = finding.get("category")
            if category and category in self.policy.escalate_categories:
                reasons.append(
                    f"{finding['target']} 命中升级类目 {category}（{finding['detector']}）"
                )
            elif (
                category
                and category not in KNOWN_CATEGORIES
                and self.policy.escalate_unknown_category
            ):
                reasons.append(
                    f"{finding['target']} 出现未知类目 {category}，按 fail-safe 升级人工"
                )

        return {
            "accepted": accepted,
            "escalated": bool(reasons),
            "escalation_reasons": reasons,
        }

    # ------------------------------------------------------------------ #
    # human_review / finalize
    # ------------------------------------------------------------------ #

    def human_review(self, state: dict[str, Any]) -> dict[str, Any]:
        notes = list(state.get("notes", []))
        notes.append("已标记为需人工复核（生产环境这里会中断等人处理，见 A5 后续）")
        return {"escalated": True, "notes": notes}

    def finalize(self, state: dict[str, Any]) -> dict[str, Any]:
        accepted = state.get("accepted", [])
        audit = {
            "report_id": state["artifact"]["report_id"],
            "escalated": bool(state.get("escalated")),
            "escalation_reasons": list(state.get("escalation_reasons", [])),
            "findings": accepted,
            "counts": {
                "deterministic": len(state.get("deterministic", [])),
                "semantic": len(state.get("semantic", [])),
                "accepted": len(accepted),
                "rejected": len(state.get("rejected", [])),
            },
            "model_calls": int(state.get("model_calls", 0)),
            "policy": self.policy.describe(),
            "notes": list(state.get("notes", [])),
        }
        return {"audit": audit}

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #

    @staticmethod
    def _finding_to_dict(finding: Any, detector: str, text: str = "") -> dict[str, Any]:
        if isinstance(finding, Finding):
            return {
                "detector": detector,
                "target": finding.target,
                "location": finding.location,
                "category": None,
                "evidence": finding.observed,
                "message": finding.message,
                "decided_by": "deterministic",
            }

        # 护栏命中时**必须归到确定性层**（detector 用 safety_terms），不能记成 semantic_check。
        #
        # 真实 bug 回归：原先一律记成 semantic_check，于是同一条关键词型越界
        # 被确定性检查器和语义检查的护栏各报一次——**报两遍**，
        # 而其中一遍对不上标准答案，直接被算成误报。
        # 护栏的本质就是词表匹配，它属于确定性层；`decided_by` 里保留了它的来源可追溯。
        resolved_detector = "safety_terms" if finding.decided_by == "guardrail" else detector

        return {
            "detector": resolved_detector,
            "target": finding.target,
            "location": "items[].explanation",
            "category": finding.category,
            "evidence": finding.evidence,
            "message": f"语义检查判定越界（{finding.category}）",
            "decided_by": finding.decided_by,
        }


def guardrail_summary(text: str) -> list[dict[str, Any]]:
    """给 CLI 用的小工具：只看护栏命中情况，不调模型。"""
    return [hit.to_dict() for hit in apply_guardrails(text)]
