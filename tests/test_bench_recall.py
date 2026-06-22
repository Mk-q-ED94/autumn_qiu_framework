"""Smoke test for the recall benchmark harness (script/bench_recall.py).

The benchmark itself is a dev tool, deliberately kept out of the timed suite.
This test runs it at trivial scale so the harness can't silently rot — it checks
that every backend produces a well-formed result row and that the table renders,
not any particular latency number (those are machine-dependent).
"""
import importlib.util
from pathlib import Path

import pytest

_BENCH_PATH = Path(__file__).resolve().parent.parent / "script" / "bench_recall.py"


def _load_bench():
    spec = importlib.util.spec_from_file_location("bench_recall", _BENCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load_bench()


async def test_run_benchmark_covers_every_backend():
    rows = await bench.run_benchmark(
        sizes=[8], queries=3, dim=16, backends=list(bench.BACKENDS), seed=7,
    )
    # one row per (backend, size); single size → one row per backend
    assert {r["backend"] for r in rows} == set(bench.BACKENDS)
    for r in rows:
        assert r["size"] == 8
        assert r["build_ms"] >= 0.0
        # every latency stat is a real, ordered number
        assert r["p50_ms"] <= r["p95_ms"] <= r["max_ms"]
        assert r["mean_ms"] >= 0.0
        assert r["avg_hits"] >= 0.0


async def test_run_benchmark_subset_and_multiple_sizes():
    rows = await bench.run_benchmark(
        sizes=[4, 8], queries=2, dim=16, backends=["dict", "vector"], seed=1,
    )
    assert len(rows) == 4  # 2 backends × 2 sizes
    assert {r["backend"] for r in rows} == {"dict", "vector"}
    assert {r["size"] for r in rows} == {4, 8}


async def test_dict_and_vector_return_hits():
    # dict recalls via the tag-filtered history path; vector via brute-force kNN.
    # Both should surface up to k results on a populated store.
    rows = await bench.run_benchmark(
        sizes=[10], queries=4, dim=16, backends=["dict", "vector"], k=5, seed=3,
    )
    by_backend = {r["backend"]: r for r in rows}
    assert by_backend["dict"]["avg_hits"] > 0
    assert by_backend["vector"]["avg_hits"] > 0


def test_format_markdown_renders_table():
    rows = [{
        "backend": "vector", "size": 100, "build_ms": 12.3, "mean_ms": 1.5,
        "p50_ms": 1.4, "p95_ms": 2.0, "max_ms": 2.1, "avg_hits": 5.0,
    }]
    out = bench.format_markdown(rows, dim=1536, queries=20)
    assert "| backend |" in out
    assert "| vector | 100 |" in out
    assert "dim=1536" in out


def test_main_rejects_unknown_backend():
    with pytest.raises(SystemExit):
        bench.main(["--backends", "nope", "--sizes", "4"])
