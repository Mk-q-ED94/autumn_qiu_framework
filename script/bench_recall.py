#!/usr/bin/env python3
"""Benchmark 4D recall latency across the five memory configurations.

Roadmap P3 #9. The motivating worry is **vector recall under a large store**:
``SQLiteVectorStore.search`` is a brute-force linear scan (load every blob,
cosine-score it, heap the top-k), so its cost grows O(N · dim) per query. This
harness makes that growth visible and gives the other four backends as baselines.

The five configurations (the "backends" the roadmap names), each measured on the
recall path it actually uses:

| kind     | storage              | recall path measured                       |
|----------|----------------------|--------------------------------------------|
| dict     | DictBackend (memory) | KV miss + full-history decode + tag filter |
| markdown | MarkdownBackend      | same history-scan path, over markdown files|
| vector   | Dict + vector layer  | semantic brute-force kNN (the hot one)     |
| lexical  | Dict + lexical layer | BM25/FTS5 keyword search                    |
| hybrid   | Dict + vector+lexical| RRF fusion of the two                       |

Everything runs offline: embeddings come from a deterministic hash-based mock,
so the numbers reflect storage + math cost (which is what latency is about),
not embedding quality or a network round-trip.

Usage::

    python script/bench_recall.py                       # defaults
    python script/bench_recall.py --sizes 100,1000,5000 --queries 30
    python script/bench_recall.py --backends vector,hybrid --dim 1536

It is intentionally **not** part of the pytest suite (it is slow and timing-based);
``tests/test_bench_recall.py`` runs a tiny smoke pass so the harness can't rot.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

# Allow ``python script/bench_recall.py`` from a source checkout without install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autumn.core.memory.backends import (  # noqa: E402
    DictBackend,
    MarkdownBackend,
    SQLiteLexicalStore,
    SQLiteVectorStore,
)
from autumn.core.memory.base import MemoryArea, MemoryEntry  # noqa: E402

BACKENDS = ("dict", "markdown", "vector", "lexical", "hybrid")
_TAG = "turn"  # every entry carries this so the history-scan path has work to do

# A small vocabulary so stored entries and queries share tokens (lets the lexical
# layer actually match), while content stays long enough to be non-trivial.
_VOCAB = (
    "deploy database migration rollback cache index query latency throughput "
    "memory vector recall embedding cosine schema config server client stream "
    "token prompt model agent task mission workspace terr plugin reconnect"
).split()


class _MockEmbedding:
    """Deterministic, offline embedding. Hash-seeded unit vectors — not semantic,
    but the per-query cosine cost is identical to a real one, which is the point."""

    def __init__(self, dim: int = 1536):
        self._dim = dim

    async def embed(self, text: str) -> list[float]:
        rng = random.Random(abs(hash(text)) % (2**31))
        vec = [rng.uniform(-1.0, 1.0) for _ in range(self._dim)]
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


def _sentence(rng: random.Random, words: int = 12) -> str:
    return " ".join(rng.choice(_VOCAB) for _ in range(words))


async def _make_area(
    kind: str, size: int, workdir: Path, dim: int, seed: int,
) -> tuple[MemoryArea, list, str | None]:
    """Build and populate a MemoryArea for ``kind``. Returns the area, a list of
    async close-callables for SQLite layers, and the query-time tags (or None)."""
    rng = random.Random(seed)
    closers: list = []

    if kind == "markdown":
        backend = MarkdownBackend(workdir / "md")
    else:
        backend = DictBackend()

    # history_limit = size so nothing is evicted — we want to scan the full store.
    area = MemoryArea(kind, backend, history_limit=size)
    query_tags: str | None = None

    if kind in ("vector", "hybrid"):
        store = SQLiteVectorStore(str(workdir / "vec.db"))
        area.enable_vector(_MockEmbedding(dim), store, auto_index=True)
        closers.append(store.close)
    if kind in ("lexical", "hybrid"):
        store = SQLiteLexicalStore(str(workdir / "lex.db"))
        area.enable_lexical(store, auto_index=True)
        closers.append(store.close)
    if kind in ("dict", "markdown"):
        # No semantic layer — the scaling recall path is the tag-filtered history
        # scan, so query with the shared tag to exercise a full decode+filter.
        query_tags = _TAG

    for i in range(size):
        await area.append_history(
            MemoryEntry(
                id=f"e{i}",
                content=f"entry {i}: {_sentence(rng)}",
                timestamp=time.time(),
                tags=[_TAG],
            )
        )
    await area.flush_index()
    return area, closers, query_tags


async def _bench_one(
    kind: str, size: int, queries: int, dim: int, k: int, seed: int,
) -> dict:
    """Time build + ``queries`` recalls for one (kind, size). Returns a row dict."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        t0 = time.perf_counter()
        area, closers, tags = await _make_area(kind, size, workdir, dim, seed)
        build_ms = (time.perf_counter() - t0) * 1000.0

        rng = random.Random(seed + 1)
        latencies: list[float] = []
        hits = 0
        try:
            for _ in range(queries):
                q = _sentence(rng, words=4)
                t = time.perf_counter()
                results = await area.recall(
                    q, k=k, tags=[tags] if tags else None,
                )
                latencies.append((time.perf_counter() - t) * 1000.0)
                hits += len(results)
        finally:
            for close in closers:
                try:
                    await close()
                except Exception:
                    pass

    latencies.sort()
    return {
        "backend": kind,
        "size": size,
        "build_ms": build_ms,
        "mean_ms": statistics.mean(latencies),
        "p50_ms": latencies[len(latencies) // 2],
        "p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        "max_ms": latencies[-1],
        "avg_hits": hits / queries,
    }


async def run_benchmark(
    sizes: list[int],
    queries: int = 20,
    dim: int = 1536,
    backends: list[str] = list(BACKENDS),
    k: int = 5,
    seed: int = 1234,
) -> list[dict]:
    """Run the full grid (backends × sizes) and return one row dict per cell."""
    rows: list[dict] = []
    for kind in backends:
        for size in sizes:
            rows.append(await _bench_one(kind, size, queries, dim, k, seed))
    return rows


def format_markdown(rows: list[dict], dim: int, queries: int) -> str:
    header = (
        f"# 4D recall benchmark  (dim={dim}, queries/cell={queries})\n\n"
        "| backend | size | build ms | recall mean | p50 | p95 | max | avg hits |\n"
        "|---------|-----:|---------:|------------:|----:|----:|----:|---------:|\n"
    )
    lines = [
        "| {backend} | {size} | {build_ms:.1f} | {mean_ms:.3f} | {p50_ms:.3f} "
        "| {p95_ms:.3f} | {max_ms:.3f} | {avg_hits:.1f} |".format(**r)
        for r in rows
    ]
    return header + "\n".join(lines) + "\n"


def _has_fts5() -> bool:
    import sqlite3
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        con.close()
        return True
    except sqlite3.OperationalError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark 4D recall latency.")
    parser.add_argument("--sizes", default="100,500,1000",
                        help="comma-separated store sizes (default 100,500,1000)")
    parser.add_argument("--queries", type=int, default=20,
                        help="recall calls timed per cell (default 20)")
    parser.add_argument("--dim", type=int, default=1536,
                        help="embedding dimension (default 1536, matches prod)")
    parser.add_argument("--backends", default=",".join(BACKENDS),
                        help=f"comma-separated subset of {','.join(BACKENDS)}")
    parser.add_argument("--k", type=int, default=5, help="top-k per recall (default 5)")
    parser.add_argument("--seed", type=int, default=1234)
    args = parser.parse_args(argv)

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    unknown = [b for b in backends if b not in BACKENDS]
    if unknown:
        parser.error(f"unknown backend(s): {unknown}; choose from {list(BACKENDS)}")

    if ("lexical" in backends or "hybrid" in backends) and not _has_fts5():
        print("note: this SQLite build lacks FTS5 — lexical/hybrid will return "
              "0 hits (latency still measured).\n", file=sys.stderr)

    rows = asyncio.run(run_benchmark(
        sizes, queries=args.queries, dim=args.dim, backends=backends, k=args.k,
        seed=args.seed,
    ))
    print(format_markdown(rows, args.dim, args.queries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
