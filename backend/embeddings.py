"""Embeddings — deterministic mock now; real backends hook in later (Phase 7).

Mock vectors are stable per text (hash-seeded) so the vector code path is
exercised offline. They carry no semantic signal: structured fact_key lookup
remains the source of truth; vectors are paraphrase-catchers only.
"""
import hashlib
import os
import random

DIM = 768


def _mock_embed(text: str) -> list[float]:
    seed = int(hashlib.sha256(f"teamgen-embed:{text}".encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(DIM)]


def embed(texts: list[str]) -> list[list[float]] | None:
    mode = os.environ.get("EMBEDDING_MODE", "bge-small")
    if mode == "off":
        return None
    # Real backends (bge-small / text-embedding-3-small) land pre-Phase-7;
    # until then the mock keeps every path deterministic and offline.
    return [_mock_embed(t) for t in texts]


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
