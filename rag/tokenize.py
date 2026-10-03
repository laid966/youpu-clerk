"""中文/英文混合分词。

**为什么这件事重要**：BM25 是按"词"算分的，而中文没有空格。
分错了，后面的检索就全错——召回不回来的东西，再好的重排也救不了。

策略：
- 中文走 jieba 分词
- 英文缩写与数字必须**保持完整**：`ALT`、`GGT`、`U/L`、`3.4`、`13.9`
  这些是检索里最有价值的精确信号，一旦被切碎就废了
- 统一小写，丢掉标点与纯停用词

## 已知局限（写进文档，别藏着）

jieba 的默认词典对医学术语不一定合意，比如"丙氨酸氨基转移酶"可能被切成
"丙氨酸 / 氨基 / 转移酶"。这里**不额外造医学词典**，因为：
1. 用户查询里出现全称的概率远低于出现 `ALT` 或"转氨酶"的概率；
2. 加自定义词典会让分词结果依赖一个容易过时的词表，反而更难维护。

如果 A4 的评测显示全称查询召回不足，再回头加词典——**先用数字说话**。
"""

from __future__ import annotations

import logging
import re

import jieba

# jieba 首次使用会构建词典缓存并往 stderr 打印一堆进度，CLI 输出会被淹没。
# 它只是初始化信息，不是错误，静音掉。
jieba.setLogLevel(logging.WARNING)

__all__ = ["tokenize", "tokens_for_index"]

# 纯 ASCII 的字段、数字、缩写：整块保留。
# 斜杠也算在 run 里，否则 `U/L`、`mmol/L` 这类单位会被切成孤零零一个字母——
# 而单位恰恰是最有辨识度的 token 之一。
_ASCII_RUN = re.compile(r"[A-Za-z][A-Za-z0-9/]*|\d+(?:\.\d+)?")

# 这些词在检索里没有区分度，去掉可以少些噪音。
#
# ⚠️ 这里踩过一次真实的坑：最初只收了"什么/怎么/如何"，结果
# `ALT 偏高怎么办` 排第一的是"什么是危急值，看到危急值应该**怎么办**"那条指南——
# **疑问词污染**：问句里的"怎么办"是个稀有词，IDF 很高，把无关文档顶了上来。
# 实测 31 条用例里有 6 条因此排错，Recall@1 被压到 74.2%。
# 所以疑问词、口语填充词必须成组地收进来，而不是碰上一个补一个。
_STOPWORDS = frozenset(
    {
        # 结构助词与代词
        "的", "了", "是", "在", "和", "与", "或", "及", "有", "为", "对", "把", "被",
        "我", "你", "他", "它", "这", "那", "这个", "那个", "这些", "那些",
        # 疑问词与口语填充词
        "什么", "怎么", "怎样", "如何", "怎么办", "咋办", "要不要", "是不是", "会不会",
        "有没有", "哪些", "哪个", "多少", "多久", "多", "请问", "一下", "意思", "要紧",
        "有关", "关系", "一般", "可能", "需要", "应该", "可以", "注意", "情况", "时候",
        "吗", "呢", "吧", "啊", "的话",
    }
)


def tokenize(text: str) -> list[str]:
    """切成检索用的词序列。"""
    if not text:
        return []

    tokens: list[str] = []

    # 先按"非中英数字"切开，保证 ASCII 片段不被 jieba 拆散。
    # ⚠️ 这里**不能加捕获组**：`re.split(r"(...)")` 会把分隔符本身也放进结果，
    # 于是"，""？"会被当成一个片段再送进 jieba，切成"标点 token"污染索引。
    # 实测就是这么漏进去的——测试里那条断言才把它抓出来。
    for segment in re.split(r"[^\u4e00-\u9fffA-Za-z0-9./]+", text):
        if not segment:
            continue
        if _ASCII_RUN.search(segment) and not re.search(r"[\u4e00-\u9fff]", segment):
            tokens.extend(match.group(0).lower() for match in _ASCII_RUN.finditer(segment))
            continue
        tokens.extend(word.strip().lower() for word in jieba.cut(segment) if word.strip())

    return [
        token
        for token in tokens
        # 兜底：只保留含有中文或字母数字的 token，纯标点一律丢掉
        if token
        and token not in _STOPWORDS
        and not token.isspace()
        and re.search(r"[\u4e00-\u9fffA-Za-z0-9]", token)
    ]


def tokens_for_index(text: str) -> list[str]:
    """建索引时用的词序列（目前与查询侧一致，保留这个入口是为了将来能不对称处理）。"""
    return tokenize(text)
