"""三层知识库。

| 层 | 内容 | 进检索索引吗 |
|---|---|---|
| **L1 参考区间** | 每个指标的分性别参考区间（精确数值） | **不进** |

进检索索引的还有两层，它们只在下面这张表里：

| 层 | 内容 | 进检索索引吗 |
|---|---|---|
| **L2 指标解释库** | 通俗解释、常见相关因素、该怎么做 | ✅ |
| **L3 指南要点库** | 复查、空腹准备、危急值处理等通用要点 | ✅ |

## 为什么参考区间不进向量/检索索引

它是**精确数值**。语义检索会给你一个"差不多"的区间，而临床判读要的是"就是这一条"。
所以本项目的核心分工是：

> **数值判断走确定性（L1 + 规则引擎），语义解释走检索（L2 + L3）。**

把 L1 塞进向量库是一个很常见、但会让系统变得不可靠的做法：
检索一旦漏掉或错配区间，后面的分级就全错，而且错得无法察觉。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import yaml

__all__ = [
    "Chunk",
    "KnowledgeBase",
    "LAYER_EXPLANATION",
    "LAYER_GUIDELINE",
    "LAYER_REFERENCE",
    "load_knowledge",
]

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "rag" / "knowledge"

LAYER_REFERENCE = "reference"
LAYER_EXPLANATION = "explanation"
LAYER_GUIDELINE = "guideline"
RETRIEVABLE_LAYERS = (LAYER_EXPLANATION, LAYER_GUIDELINE)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    layer: str
    metric_code: str | None
    title: str
    text: str
    keywords: str = ""

    def index_text(self) -> str:
        """送进索引的文本。

        三个刻意的设计，每一个都是被真实失败逼出来的：

        1. **标题重复两次**。BM25 没有字段权重，重复标题是最简单的"加权"办法：
           让指标名比正文里的偶然提及更有分量。不这么做，问"血红蛋白是什么意思"
           会被那条讲贫血的指南抢走——因为指南更短，长度归一化帮了它。
        2. **关键词字段**。同一件事有多种说法：ALT 卡片里写"升高"，
           空腹血糖卡片里写"偏高"。用户问"ALT 偏高怎么办"时，"偏高"这个稀有词
           会把空腹血糖那张无辜的卡顶上来（实测 4 条用例因此排错）。
           把方向词补齐到每张卡上，它就失去区分度，判定重新交给指标名。
        3. **指标名与缩写都进正文**。用户可能只写 `ALT`，也可能只写全称。
        """
        return "\n".join(part for part in (self.title, self.title, self.keywords, self.text) if part)


@dataclass(frozen=True)
class KnowledgeBase:
    reference_table: Mapping[str, Mapping[str, tuple[float, float]]]
    chunks: tuple[Chunk, ...]

    def by_id(self, chunk_id: str) -> Chunk | None:
        for chunk in self.chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        return None

    def layers(self, *layers: str) -> tuple[Chunk, ...]:
        wanted = set(layers) if layers else set(RETRIEVABLE_LAYERS)
        return tuple(chunk for chunk in self.chunks if chunk.layer in wanted)

    def documents(self) -> dict[str, str]:
        """chunk_id -> 索引文本。"""
        return {chunk.chunk_id: chunk.index_text() for chunk in self.chunks}

    def citation_ids(self) -> frozenset[str]:
        """可以被引用的标识集合（chunk id 与标题都算，便于模型自然引用）。"""
        ids: set[str] = set()
        for chunk in self.chunks:
            ids.add(chunk.chunk_id)
            ids.add(chunk.title)
        return frozenset(ids)


def _load_yaml(path: Path) -> list[dict]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw.get("notes"):
        raise ValueError(f"{path} 里没有 notes")
    return list(raw["notes"])


def load_knowledge(metrics: Sequence | None = None) -> KnowledgeBase:
    """加载三层知识库。

    L1 参考区间从指标清单（`domain/med-metrics.yaml`）读，保持与判定域同源；
    L2/L3 从 `rag/knowledge/*.yaml` 读。
    """
    if metrics is None:
        from audit.pipeline import load_metrics  # 延迟导入，避免包之间互相牵扯

        metrics = load_metrics()

    reference_table: dict[str, dict[str, tuple[float, float]]] = {
        metric.code: dict(metric.reference) for metric in metrics
    }

    metric_titles = {metric.code: f"{metric.name}（{metric.abbr}，{metric.unit}）" for metric in metrics}
    chunks: list[Chunk] = []

    # 方向词与通用词：每张指标卡都补齐，让它们失去区分度。
    # 不这么做，"偏高"就会变成只有少数卡片才有的稀有词，检索会被它带偏。
    metric_keywords = "偏高 升高 高 偏低 降低 低 正常 参考区间 复查 门诊 解读 指标"

    for note in _load_yaml(KNOWLEDGE_DIR / "metric_notes.yaml"):
        code = str(note["code"])
        if code not in metric_titles:
            raise ValueError(f"metric_notes.yaml 里的指标 {code} 不在指标清单中")
        body = "\n".join(
            part
            for part in (
                str(note.get("plain", "")).strip(),
                f"常见相关因素：{note['factors']}" if note.get("factors") else "",
                f"建议：{note['action']}" if note.get("action") else "",
            )
            if part
        )
        chunks.append(
            Chunk(
                chunk_id=f"kb://metric/{code}",
                layer=LAYER_EXPLANATION,
                metric_code=code,
                title=metric_titles[code],
                text=body,
                keywords=metric_keywords,
            )
        )

    for note in _load_yaml(KNOWLEDGE_DIR / "guideline_notes.yaml"):
        note_id = str(note["id"])
        chunks.append(
            Chunk(
                chunk_id=f"kb://guideline/{note_id}",
                layer=LAYER_GUIDELINE,
                metric_code=None,
                title=str(note["title"]),
                text=str(note["text"]).strip(),
            )
        )

    ids = [chunk.chunk_id for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("知识库 chunk_id 有重复")

    return KnowledgeBase(reference_table=reference_table, chunks=tuple(chunks))
