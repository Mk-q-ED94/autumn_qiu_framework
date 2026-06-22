# 4D Recall Benchmark

> Roadmap P3 #9. Harness: `script/bench_recall.py` · Smoke test: `tests/test_bench_recall.py`

Measures recall latency across Autumn's five memory configurations as the store
grows, to answer one concrete worry: **how badly does vector recall degrade on a
large zone?** `SQLiteVectorStore.search` is a brute-force linear scan — it loads
every stored blob, cosine-scores it, and heaps the top-k — so per-query cost is
O(N · dim). This doc records the method and a representative run; re-run the
harness for fresh numbers on your hardware.

## What each configuration measures

| kind | storage | recall path |
|------|---------|-------------|
| `dict` | `DictBackend` (in-memory) | KV miss + full-history decode + tag filter |
| `markdown` | `MarkdownBackend` (files) | same history-scan path, over markdown on disk |
| `vector` | Dict + vector layer | semantic brute-force kNN — **the one under watch** |
| `lexical` | Dict + lexical layer | BM25/FTS5 keyword search (index-backed) |
| `hybrid` | Dict + vector + lexical | RRF fusion of vector + lexical |

Embeddings come from a deterministic offline mock (hash-seeded unit vectors), so
the numbers reflect storage + math cost, not embedding quality or network time —
which is exactly what latency depends on.

## Running

```bash
python script/bench_recall.py                                  # 100/500/1000 × dim 1536
python script/bench_recall.py --sizes 500,2000,5000 --queries 30
python script/bench_recall.py --backends vector,hybrid --dim 1536
```

## Representative run

`dim=1536` (production default), 15 queries/cell, FTS5 available, single core.
Absolute milliseconds are machine-specific; the **scaling shape** is the point.

| backend | size | build ms | recall mean | p50 | p95 | avg hits |
|---------|-----:|---------:|------------:|----:|----:|---------:|
| dict | 500 | 868 | 2.4 | 2.4 | 2.5 | 5.0 |
| dict | 2000 | 15758 | 10.9 | 10.0 | 16.5 | 5.0 |
| vector | 500 | 3685 | 58.7 | 57.5 | 73.5 | 5.0 |
| vector | 2000 | 28371 | **247.0** | 242.9 | 301.2 | 5.0 |
| lexical | 500 | 3181 | 0.8 | 0.7 | 1.0 | 5.0 |
| lexical | 2000 | 27306 | **1.8** | 1.8 | 2.2 | 5.0 |
| hybrid | 500 | 6229 | 63.0 | 60.7 | 71.3 | 5.0 |
| hybrid | 2000 | 39558 | 243.3 | 236.4 | 311.1 | 5.0 |

## Takeaways

1. **Vector recall scales linearly and is the bottleneck.** 4× the store (500 →
   2000) gives ~4.2× the latency (59 → 247 ms mean), confirming the O(N) scan. At
   2000 entries a single recall already costs ~0.25 s — and it keeps climbing.
2. **Lexical is effectively flat** (~1.8 ms at 2000) because FTS5 is index-backed.
   For large zones where keyword overlap is acceptable, lexical is orders of
   magnitude cheaper.
3. **Hybrid inherits vector's cost** — the RRF fusion is cheap, but it still runs
   the full vector scan, so it tracks `vector`, not `lexical`.
4. **`dict`/`markdown` history-scan recall is cheap-ish but also linear** (decode +
   tag filter); `markdown` pays a large constant for file I/O on both build and read.

**Implication for 1.0.** The vector layer is fine for the per-zone history sizes
Autumn runs today (tens of entries), but it does **not** scale to large recall
stores. Before promoting big-store semantic recall past 🟡 experimental, the scan
needs an ANN index (e.g. HNSW/IVF) or a store-size cap — tracked as a follow-up,
not a 0.x blocker. Until then, prefer `lexical`/`hybrid` with a bounded vector
zone, and keep `decay`/eviction trimming the history that feeds the index.
