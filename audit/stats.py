"""统计置信：一个分数**能证明什么**。

## 为什么需要这个模块

「24 条全对，召回 100%」听起来很漂亮，但它证明不了多少事。
**样本是有限的，所以只能给出一个区间，不能给出一个点。**

数学上很清楚：如果真实召回是 90%，你测 24 条也可能碰巧全对。
所以「24/24 全对」的正确读法是：

    真实召回 ≥ 88.3%（95% 置信）

也就是说：**它连"召回达到 90%"都证明不了。**

## 公式

用 Clopper–Pearson 精确区间（不是正态近似——小样本下正态近似会给出
超出 [0,1] 的荒谬结果）。

- **k 次成功 / n 次试验的下界**：找到 p 使得 P(X ≥ k | p) = 1 − 置信度
- **0 次失败时的简便形式**：下界 = α^(1/n)，其中 α = 1 − 置信度
  （n=24、95% 置信 → 0.05^(1/24) = 88.3%）
- **0 次误报 / n 条干净样本的上界**：1 − α^(1/n)
  （n=20、95% 置信 → 13.9%）

## 要用多少样本

想在"零失败"的前提下声称真实率不低于 target，需要：

    n ≥ ln(α) / ln(target)

| 想证明 | 零失败时需要 |
|---|---|
| ≥ 90% | 29 |
| ≥ 95% | 59 |
| ≥ 98% | 149 |
| ≥ 99% | 299 |

这张表是回答"样本够不够"的唯一依据。**先说要声称什么，再说要多少样本。**
"""

from __future__ import annotations

from math import ceil, comb, log

__all__ = [
    "binomial_cdf",
    "lower_bound",
    "proof_lines",
    "required_zero_failure_sample",
    "upper_bound",
]


def binomial_cdf(successes: int, trials: int, p: float) -> float:
    """P(X ≤ successes)，X ~ B(trials, p)。"""
    if successes < 0:
        return 0.0
    if successes >= trials:
        return 1.0
    return sum(
        comb(trials, index) * (p**index) * ((1 - p) ** (trials - index))
        for index in range(successes + 1)
    )


def lower_bound(successes: int, trials: int, confidence: float = 0.95) -> float:
    """真实率的**单侧下界**：有 confidence 的把握，真实率不低于这个值。"""
    if trials <= 0 or successes <= 0:
        return 0.0
    if successes >= trials:
        return (1 - confidence) ** (1 / trials)

    alpha = 1 - confidence
    low, high = 0.0, successes / trials
    for _ in range(200):
        middle = (low + high) / 2
        # P(X ≥ successes | p) 随 p 递增；下界 p_L 满足 tail(p_L) = alpha，
        # 所以 tail(middle) > alpha 说明 middle 偏高 → 收上界。
        if 1 - binomial_cdf(successes - 1, trials, middle) > alpha:
            high = middle
        else:
            low = middle
    return (low + high) / 2


def upper_bound(successes: int, trials: int, confidence: float = 0.95) -> float:
    """真实率的**单侧上界**：有 confidence 的把握，真实率不超过这个值。

    用来读「零误报」：0/20 的意思是真实误报率**最高** 13.9%。
    """
    if trials <= 0:
        return 1.0
    if successes <= 0:
        return 1 - (1 - confidence) ** (1 / trials)
    if successes >= trials:
        return 1.0

    alpha = 1 - confidence
    low, high = successes / trials, 1.0
    for _ in range(200):
        middle = (low + high) / 2
        # P(X ≤ successes | middle) 随 middle 递减
        if binomial_cdf(successes, trials, middle) > alpha:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def required_zero_failure_sample(target: float, confidence: float = 0.95) -> int:
    """零失败的前提下，要声称真实率 ≥ target，至少需要多少样本。"""
    if not 0 < target < 1:
        raise ValueError("target 必须在 (0, 1) 之间")
    alpha = 1 - confidence
    return ceil(log(alpha) / log(target))


def proof_lines(
    positives: int,
    caught: int,
    negatives: int,
    false_positives: int,
    confidence: float = 0.95,
) -> list[str]:
    """生成「这份成绩能证明什么」的 Markdown 段落。

    语义评测和留出集共用，保证两个报告的口径一致。
    """
    percent = int(confidence * 100)
    lines = [
        f"## 这份成绩能证明什么（{percent}% 置信）",
        "",
        "> **样本是有限的，所以它只能给出一个区间，不能给出一个点。**",
        "> 下面这两行比上面的百分比更重要——**它们才是你真正能声称的东西。**",
        "",
    ]

    if positives:
        low = lower_bound(caught, positives, confidence)
        lines.append(
            f"- 召回 **{caught}/{positives} = {caught / positives:.1%}** "
            f"→ 真实召回 **≥ {low:.1%}**"
        )
        for target in (0.90, 0.95, 0.99):
            need = required_zero_failure_sample(target, confidence)
            if low >= target:
                lines.append(f"  - ✅ 已经能声称 ≥{target:.0%}（需要 {need} 条，现有 {positives} 条）")
            else:
                lines.append(
                    f"  - ❌ **还不能**声称 ≥{target:.0%}：需要 {positives} → {need} 条正例"
                )
    else:
        lines.append("- 正例 0 条，什么都证明不了")

    if negatives:
        high = upper_bound(false_positives, negatives, confidence)
        lines.append(
            f"- 误报 **{false_positives}/{negatives} = {false_positives / negatives:.1%}** "
            f"→ 真实误报 **≤ {high:.1%}**"
        )
        for target in (0.05, 0.01):
            need = required_zero_failure_sample(1 - target, confidence)
            if high <= target:
                lines.append(f"  - ✅ 已经能声称 ≤{target:.0%}（需要 {need} 条，现有 {negatives} 条）")
            else:
                lines.append(
                    f"  - ❌ **还不能**声称 ≤{target:.0%}：需要 {negatives} → {need} 条负例"
                )
    else:
        lines.append("- 负例 0 条，什么都证明不了")

    lines += [
        "",
        "**怎么用这张单子**：先决定要声称什么（比如「召回 ≥95%、误报 ≤5%」），",
        "再看需要多少条样本，然后照这个数去扩样本集——**而不是先攒样本再看能声称什么。**",
        "",
    ]
    return lines
