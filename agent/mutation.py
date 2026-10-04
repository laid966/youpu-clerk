"""变异测试运行器：在**临时副本**里改坏代码，跑测试，算变异得分。

## 为什么必须在副本里做

变异测试要真的改文件。如果在工作区里改，一旦中途崩了（或被杀掉），
你的仓库就停在一个"被改坏"的状态里——而且很难看出哪里被改了。

所以：**把项目复制到临时目录，在副本里改，跑完删掉。**
工作区全程只读，出任何问题都不影响你。

## 判定规则

- 测试失败（非 0 退出码）→ **杀死**：这个不变量被守住了
- 测试通过 → **存活**：测试盲区，报告里会重点列出来
- 目标代码片段出现次数 ≠ 1 → **无效**：变异体本身写得不精确，不计入分母
  （这条很关键：一个"改不动"的变异体会被误算成存活，把得分拉低）
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from agent.mutants import MUTANTS, Mutant

__all__ = ["MutationBaselineError", "MutationReport", "MutationResult", "run_mutation"]


class MutationBaselineError(RuntimeError):
    """沙箱里未变异时测试就不通过——此时任何变异得分都是伪造的。"""

ROOT = Path(__file__).resolve().parents[1]
FAILED_LINE = re.compile(r"^FAILED (\S+)", re.MULTILINE)

_SKIP_DIRS = {
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    "data",
    "reports",
    "exports",
    "node_modules",
}
_SKIP_FILES = {"judged-reports.jsonl", "injected-artifacts.jsonl"}

# **变异运行必须排除的"元测试"。**
#
# 这些测试校验的是"变异体定义本身是否精确"（目标片段在源文件里恰好出现一次）。
# 一旦某个变异体被应用，源文件里的片段就变了——于是这条测试
# **对每一个变异体都会失败**，让所有变异体都显示为"被杀死"。
#
# 真实事故：第一次拿到 18/18 的 100% 就是这么来的，
# 跟"产品测试有没有守住"毫无关系。这类元测试属于**测试基础设施**，
# 不该参与变异计分——就像裁判不能同时当运动员。
_META_TESTS = ("tests/test_invariants.py::test_mutant_targets_are_precise",)


def _pytest_command() -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
    ]
    for node_id in _META_TESTS:
        command += ["--deselect", node_id]
    return command


def _ignore(_dir: str, names: list[str]) -> set[str]:
    skipped: set[str] = set()
    for name in names:
        if name in _SKIP_DIRS or name in _SKIP_FILES:
            skipped.add(name)
        elif name.endswith((".pyc", ".db", ".log")):
            skipped.add(name)
        elif name.startswith("dataset-"):
            skipped.add(name)
    return skipped


@dataclass(frozen=True)
class MutationResult:
    mutant: Mutant
    status: str  # killed | survived | invalid
    killer: str | None
    detail: str
    failed_tests: tuple[str, ...] = ()

    @property
    def killed(self) -> bool:
        return self.status == "killed"

    @property
    def expected_caught(self) -> bool:
        """**预期的那条测试**是否真的失败了。

        这一栏比"有没有被杀"更值钱：变异体被杀死了、但不是预期那条测试杀的，
        说明我以为在守它的测试其实没守——是别的测试顺带守住的。
        那种情况下，一旦别的测试被改动，这个不变量就没人守了。
        """
        if not self.killed:
            return False
        expected = self.mutant.expected_killer
        return any(
            name == expected or name.startswith(expected + "[") for name in self.failed_tests
        )


@dataclass(frozen=True)
class MutationReport:
    results: tuple[MutationResult, ...]

    @property
    def valid(self) -> tuple[MutationResult, ...]:
        return tuple(item for item in self.results if item.status != "invalid")

    @property
    def killed(self) -> tuple[MutationResult, ...]:
        return tuple(item for item in self.valid if item.killed)

    @property
    def must_kill(self) -> tuple[MutationResult, ...]:
        return tuple(item for item in self.valid if item.mutant.must_kill)

    @property
    def allowed_survivors(self) -> tuple[MutationResult, ...]:
        """允许存活的变异体（刻意留给人的可调旋钮）。"""
        return tuple(item for item in self.valid if not item.mutant.must_kill)

    @property
    def real_gaps(self) -> tuple[MutationResult, ...]:
        """**真正的测试盲区**：必须被杀死、却活下来的。"""
        return tuple(item for item in self.valid if item.mutant.must_kill and not item.killed)

    @property
    def survived(self) -> tuple[MutationResult, ...]:
        return tuple(item for item in self.valid if item.status == "survived")

    @property
    def score(self) -> float:
        """变异得分**只统计必须被杀死的那批**。

        把"允许存活"的旋钮算进分母会低估测试质量；
        把它们当成"必须杀死"又会在你正常调参时误报。
        """
        must = self.must_kill
        return len([item for item in must if item.killed]) / len(must) if must else 0.0

    @property
    def expected_caught(self) -> tuple[MutationResult, ...]:
        return tuple(item for item in self.valid if item.expected_caught)

    @property
    def expected_catch_rate(self) -> float:
        """预期杀手命中率：我的测试设计意图与实际是否一致（只算必须杀死的）。"""
        must = self.must_kill
        return len([item for item in must if item.expected_caught]) / len(must) if must else 0.0

    @property
    def incidentally_killed(self) -> tuple[MutationResult, ...]:
        """被杀死了，但不是预期那条测试杀的。"""
        return tuple(item for item in self.killed if not item.expected_caught)

    def to_markdown(self) -> str:
        lines = [
            "# 变异测试报告（A6）",
            "",
            "> 故意把流水线改坏，看**测试套件抓不抓得住**。",
            "> 抓住叫「杀死」，没抓住叫「存活」——**存活的变异体就是测试盲区**。",
            "",
            "## 变异得分",
            "",
            f"**{self.score:.1%}**（杀死 {len([i for i in self.must_kill if i.killed])} / 必须杀死 {len(self.must_kill)}）",
            "",
            f"另有 {len(self.allowed_survivors)} 个变异体属于**允许存活**的可调旋钮"
            "（成本/范围类参数，见下表标注），不计入得分。",
            "",
            f"**预期杀手命中率：{self.expected_catch_rate:.1%}**"
            f"（{len(self.expected_caught)} / {len(self.valid)}）",
            "",
            "> 第二栏比第一栏更值钱：变异体被杀死了、但**不是预期那条测试杀的**，",
            "> 说明我以为在守它的测试其实没守，是别的测试顺带守住的。",
            "> 一旦那条别的测试被改动，这个不变量就没人守了。",
            "",
            f"无效变异体 {len(self.results) - len(self.valid)} 个（目标代码片段不唯一，不计入分母）",
            "",
            "## 逐个变异体",
            "",
            "| 编号 | 改成什么 | 结果 | 预期杀手命中 | 实际失败的测试 | 它守住的不变量 |",
            "|---|---|---|---|---|---|",
        ]
        for item in self.results:
            if item.status == "killed":
                result = "✅ 杀死"
            elif item.status == "survived":
                result = "❌ **存活**"
            else:
                result = "⚠️ 无效"
            if item.status == "invalid":
                hit = "—"
            else:
                hit = "✅" if item.expected_caught else "⚠️ 否"
            failed = ", ".join(f"`{name}`" for name in item.failed_tests[:2]) or "—"
            if len(item.failed_tests) > 2:
                failed += f" 等 {len(item.failed_tests)} 条"
            lines.append(
                f"| {item.mutant.mutant_id} | {item.mutant.description} | {result} "
                f"| {hit} | {failed} | {item.mutant.invariant} |"
            )
        lines.append("")

        if self.incidentally_killed:
            lines += [
                "## 被「顺带」杀死（预期测试没守住）",
                "",
                "这些变异体确实被抓住了，但**不是我以为的那条测试**抓的：",
                "",
            ]
            for item in self.incidentally_killed:
                lines.append(
                    f"- **{item.mutant.mutant_id}**：预期 `{item.mutant.expected_killer}`，"
                    f"实际失败的是 {', '.join('`' + n + '`' for n in item.failed_tests[:3])}"
                )
            lines.append("")

        if self.survived:
            lines += ["## 测试盲区（存活 = 改坏了测试也没反应）", ""]
            for item in self.survived:
                lines.append(f"- **{item.mutant.mutant_id}**：{item.mutant.description}")
                lines.append(f"  - 目标文件：`{item.mutant.target}`")
                lines.append(f"  - 本该由这条测试抓住：`{item.mutant.expected_killer}`")
                lines.append(f"  - 它守住的不变量：{item.mutant.invariant}")
            lines.append("")
        else:
            lines += ["## 测试盲区", "", "- 无（全部变异体都被杀死）", ""]

        lines += [
            "## 这个数字的边界（必须一起读）",
            "",
            "这里只覆盖**单元测试能杀死的变异体**（改代码、改数据）。",
            "提示词层面的弱化单元测试杀不掉——单元测试用的是假模型，",
            "提示词改了它看不出来。那类变异要靠**语义评测的指标门槛**来杀，属于后续工作。",
            "",
            "所以：**不要把变异得分当成「测试覆盖率」来读**，它衡量的是「这些测试是否真的在守东西」。",
            "",
        ]
        return "\n".join(lines)


def run_mutation(
    mutants: Sequence[Mutant] = MUTANTS,
    timeout_seconds: int = 300,
    verbose: bool = False,
) -> MutationReport:
    results: list[MutationResult] = []

    with tempfile.TemporaryDirectory(prefix="mutants-") as temp_dir:
        sandbox = Path(temp_dir) / "project"
        shutil.copytree(ROOT, sandbox, ignore=_ignore)

        # ---- 基线自检（这一步不能省）----
        #
        # 真实事故：有一轮跑出"18/18 全部杀死、得分 100%"，看起来很漂亮，
        # 但每个变异体的失败列表里都出现同一条测试——连碰不到它的变异体也是。
        # 原因是复制到沙箱时带上了一条本来就写错的测试，
        # **套件本来就红，跟变异毫无关系**，于是每个变异体都被误判为"杀死"。
        #
        # 结论：**基线不通过时，变异得分是伪造的。** 宁可整轮作废，也不给假数字。
        baseline = subprocess.run(
            _pytest_command(),
            cwd=sandbox,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if baseline.returncode != 0:
            baseline_output = (baseline.stdout or "") + (baseline.stderr or "")
            failed = tuple(dict.fromkeys(FAILED_LINE.findall(baseline_output)))
            detail = "、".join(failed[:5]) or "(未能解析出失败用例，可能是收集阶段就失败)"
            raise MutationBaselineError(
                "沙箱基线不通过，变异测试结果无意义（整轮作废）。\n"
                f"失败的测试：{detail}\n"
                "常见原因：复制到沙箱时漏了某个文件、测试依赖工作区的残留状态、"
                "或者新增的测试本身在干净环境下就会失败。"
            )

        for mutant in mutants:
            target = sandbox / mutant.target
            if not target.is_file():
                results.append(
                    MutationResult(mutant, "invalid", None, f"目标文件不存在：{mutant.target}")
                )
                continue

            original = target.read_text(encoding="utf-8")
            occurrences = original.count(mutant.old_snippet)
            if occurrences != 1:
                results.append(
                    MutationResult(
                        mutant,
                        "invalid",
                        None,
                        f"目标片段在文件里出现 {occurrences} 次（必须恰好 1 次）",
                    )
                )
                continue

            target.write_text(
                original.replace(mutant.old_snippet, mutant.new_snippet), encoding="utf-8"
            )
            try:
                # 刻意**不加 -x**：跑完整个套件，收集全部失败测试。
                # 加 -x 只会看到第一个失败，无法回答"我预期的那条测试到底失败了没有"。
                completed = subprocess.run(
                    _pytest_command(),
                    cwd=sandbox,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                output = (completed.stdout or "") + (completed.stderr or "")
                failed_tests = tuple(dict.fromkeys(FAILED_LINE.findall(output)))

                if completed.returncode != 0:
                    killer = failed_tests[0] if failed_tests else "(收集/导入阶段就失败)"
                    results.append(
                        MutationResult(
                            mutant, "killed", killer, "测试失败", failed_tests=failed_tests
                        )
                    )
                else:
                    results.append(MutationResult(mutant, "survived", None, "测试全部通过"))
            except subprocess.TimeoutExpired:
                results.append(MutationResult(mutant, "survived", None, "测试超时"))
            finally:
                target.write_text(original, encoding="utf-8")

            if verbose:
                last = results[-1]
                flag = "预期杀手命中" if last.expected_caught else "预期杀手未命中"
                print(
                    f"  {mutant.mutant_id} {last.status:<9} "
                    f"{flag if last.status != 'invalid' else last.detail}"
                )

    return MutationReport(results=tuple(results))
