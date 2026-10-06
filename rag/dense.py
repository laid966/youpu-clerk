"""语义这条腿：**本地 ONNX 向量检索**。

## 为什么是本地模型，不是调 API

项目的原则是「**CI 不需要密钥**」——CI 里跑不了的东西，等于没人验证。
调 embedding API 会让这一级永远进不了 CI，而且结果不可复现。
所以选本地 ONNX：装一次、下一次模型，之后**完全离线、零成本、确定**。

## 为什么是这个模型

`BAAI/bge-small-zh-v1.5`（中文小模型），取 `Xenova` 仓库的 **int8 量化 ONNX**：

| | |
|---|---|
| 体积 | 约 24MB（int8；fp32 约 95MB） |
| 依赖 | `onnxruntime` + `numpy` + `tokenizers` |
| 需要 GPU 吗 | 不需要 |

## 它和关键词那条腿的关系：**两条腿都要，用 RRF 融合**

- **关键词（BM25）**：精确、可解释、零成本。用户写 `ALT` 就一定能匹配到 `ALT`。
- **语义（向量）**：解决**词汇不匹配**——"吃药" vs "干预"、"转氨酶" vs "丙氨酸氨基转移酶"。
  但它会给出"意思相近但事实不同"的结果（例："尿酸与饮食" vs "孕妇能不能吃海鲜"）。

**两条腿的错法不一样，所以合起来比任何一条都稳。**
融合用 `rrf_fuse`——**按名次，不是把分数相加**（BM25 分数无界，余弦在 [0,1]，相加等于让一路随机主宰）。

## 模型不在时的行为

`available()` 返回 False，链路**降级为只有关键词那一腿**，并且
`backend.name` 会变成 `disabled`——**评测报告里会写明"语义腿未启用"**，
不会静默当成"没有这一条腿"。
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, runtime_checkable

__all__ = [
    "DenseBackend",
    "NullBackend",
    "OnnxBgeBackend",
    "MODEL_FILES",
    "MODEL_REPO",
    "MODEL_DIR",
    "build_dense_backend",
    "cosine_ranking",
    "download_model",
]

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "data" / "models" / "bge-small-zh-v1.5"

#: `Xenova` 仓库提供现成的 ONNX + fast tokenizer（transformers.js 生态）。
#: 取 int8 量化版：24MB，精度损失在中文短文本检索上可以忽略，但体积小 4 倍。
MODEL_REPO = "Xenova/bge-small-zh-v1.5"
MODEL_FILES: Mapping[str, str] = {
    "model_int8.onnx": "onnx/model_int8.onnx",
    "tokenizer.json": "tokenizer.json",
}

#: BGE 中文 v1.5 官方建议的检索指令前缀。**只加在查询侧**，文档侧不加。
#: 加错了会掉分——所以它是常量而不是随手写在函数里。
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


@runtime_checkable
class DenseBackend(Protocol):
    name: str

    def available(self) -> bool: ...
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@dataclass
class NullBackend:
    """模型不在时的占位。**名字里带 disabled，报告里一眼能看出语义腿没启用。**"""

    reason: str = "模型未下载"

    @property
    def name(self) -> str:
        return f"disabled（{self.reason}）"

    def available(self) -> bool:
        return False

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        raise RuntimeError(f"语义后端不可用：{self.reason}")


class OnnxBgeBackend:
    """本地 BGE 小模型的 ONNX 推理。**分批、确定、无需 GPU。**"""

    def __init__(self, model_dir: str | Path = MODEL_DIR, max_length: int = 256) -> None:
        self.model_dir = Path(model_dir)
        self.max_length = max_length
        self.name = "bge-small-zh-v1.5(int8/onnx)"
        self._session = None
        self._tokenizer = None

    # ---- 可用性 ----

    @property
    def missing_files(self) -> tuple[str, ...]:
        return tuple(name for name in MODEL_FILES if not (self.model_dir / name).is_file())

    def available(self) -> bool:
        if self.missing_files:
            return False
        try:
            import numpy  # noqa: F401
            import onnxruntime  # noqa: F401
            import tokenizers  # noqa: F401
        except ImportError:
            return False
        return True

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        missing = self.missing_files
        if missing:
            raise RuntimeError(
                f"模型文件缺失：{missing}（目录 {self.model_dir}）。\n"
                "  先跑：python -m rag fetch-model"
            )

        import onnxruntime
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=self.max_length)
        self._tokenizer.enable_padding()

        options = onnxruntime.SessionOptions()
        # 单线程：语料只有十几条，多线程反而更慢，而且会让结果在不同机器上不好复现
        options.intra_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(
            str(self.model_dir / "model_int8.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    # ---- 推理 ----

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        import numpy as np

        assert self._tokenizer is not None and self._session is not None

        encodings = self._tokenizer.encode_batch(list(texts))
        input_ids = np.array([item.ids for item in encodings], dtype=np.int64)
        attention = np.array([item.attention_mask for item in encodings], dtype=np.int64)

        feeds = {"input_ids": input_ids, "attention_mask": attention}
        # BERT 系模型常有 token_type_ids；Xenova 的导出不一定有，按实际输入名喂
        input_names = {item.name for item in self._session.get_inputs()}
        if "token_type_ids" in input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)

        outputs = self._session.run(None, feeds)
        hidden = outputs[0]  # (batch, seq, hidden)

        # mean pooling：只对真实 token 求平均（要乘 attention mask，否则 padding 会污染向量）
        mask = attention[:, :, None].astype(np.float32)
        summed = (hidden * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        pooled = summed / counts

        # L2 归一化：之后用点积就等于余弦相似度
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = pooled / np.clip(norms, 1e-9, None)
        return normalized.tolist()


def cosine_ranking(
    query_vector: Sequence[float], doc_vectors: Sequence[Sequence[float]], doc_ids: Sequence[str]
) -> list[tuple[str, float]]:
    """按余弦相似度排序。**向量已归一化时点积即余弦。**

    分数相同时按 doc_id 稳定排序，保证可复现。
    """
    scores: list[tuple[str, float]] = []
    for doc_id, vector in zip(doc_ids, doc_vectors):
        dot = sum(a * b for a, b in zip(query_vector, vector))
        scores.append((doc_id, dot))
    return sorted(scores, key=lambda item: (-item[1], item[0]))


def download_model(target: str | Path = MODEL_DIR, timeout: int = 120) -> tuple[str, ...]:
    """从 HuggingFace 下载模型文件。**一次性的、显式的动作**（不是自动的）。

    为什么不做成"用时自动下载"：那会让"这个项目能不能跑"依赖于网络，
    而且评测结果会因为模型版本悄悄变化而不可复现。
    """
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []

    for local_name, remote_path in MODEL_FILES.items():
        destination = target / local_name
        if destination.is_file():
            continue
        url = f"https://huggingface.co/{MODEL_REPO}/resolve/main/{remote_path}"
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            payload = response.read()
        destination.write_bytes(payload)
        downloaded.append(local_name)

    return tuple(downloaded)


def build_dense_backend(model_dir: str | Path = MODEL_DIR) -> DenseBackend:
    """按需组装：模型在就用 ONNX，不在就返回明确标出原因的 NullBackend。"""
    backend = OnnxBgeBackend(model_dir)
    if backend.available():
        return backend
    missing = backend.missing_files
    reason = f"缺文件 {list(missing)}" if missing else "依赖未安装（numpy/onnxruntime/tokenizers）"
    return NullBackend(reason=reason)
