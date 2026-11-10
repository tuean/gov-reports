"""嵌入模型封装。

关键点：
1. BGE 中文系列在**检索**任务上要求给 query 加指令前缀，文档侧不加。漏掉会让召回明显变差。
2. huggingface.co 在本机直连超时，默认走 hf-mirror.com 镜像。
3. 向量一律 L2 归一化，配合 cosine 距离。
"""

from __future__ import annotations

import os

# 必须在 import transformers / sentence_transformers 之前设置
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np  # noqa: E402

# 模型登记表：dim 用于写入前自检，query_prefix 见上
MODELS: dict[str, dict] = {
    "bge-small-zh-v1.5": {
        "repo": "BAAI/bge-small-zh-v1.5",
        "dim": 512,
        "query_prefix": "为这个句子生成表示以用于检索相关文章：",
        "size": "~95 MB",
    },
    "bge-base-zh-v1.5": {
        "repo": "BAAI/bge-base-zh-v1.5",
        "dim": 768,
        "query_prefix": "为这个句子生成表示以用于检索相关文章：",
        "size": "~400 MB",
    },
    "bge-large-zh-v1.5": {
        "repo": "BAAI/bge-large-zh-v1.5",
        "dim": 1024,
        "query_prefix": "为这个句子生成表示以用于检索相关文章：",
        "size": "~1.3 GB",
    },
    "bge-m3": {
        "repo": "BAAI/bge-m3",
        "dim": 1024,
        "query_prefix": "",  # m3 不需要指令前缀
        "size": "~2.2 GB",
    },
}

DEFAULT_MODEL = "bge-small-zh-v1.5"


def resolve(name: str) -> dict:
    if name not in MODELS:
        raise SystemExit(f"未知模型 {name!r}，可选: {', '.join(MODELS)}")
    return MODELS[name]


class Embedder:
    """懒加载的句向量模型，首次调用时才载入权重。"""

    def __init__(self, name: str = DEFAULT_MODEL, device: str | None = None):
        self.name = name
        self.spec = resolve(name)
        self.dim = self.spec["dim"]
        self.query_prefix = self.spec["query_prefix"]
        self._model = None
        self.device = device

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            kw = {"device": self.device} if self.device else {}
            self._model = SentenceTransformer(self.spec["repo"], **kw)
        return self._model

    def _encode(self, texts: list[str], batch_size: int) -> np.ndarray:
        embs = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,  # 归一化 -> 内积即余弦
            show_progress_bar=len(texts) > 256,
            convert_to_numpy=True,
        )
        return np.asarray(embs, dtype=np.float32)

    def embed_documents(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """文档侧：不加指令前缀。"""
        return self._encode(texts, batch_size)

    def embed_query(self, query: str) -> np.ndarray:
        """查询侧：加指令前缀（若该模型需要），返回 (dim,) 的已归一化向量。"""
        return self._encode([self.query_prefix + query], 1)[0]
