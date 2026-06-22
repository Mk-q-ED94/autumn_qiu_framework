"""Guard: docs/http-sse-contract.md stays in sync with the real route table.

A hand-written API reference rots the moment an endpoint is added or removed
without touching it. This test pins the doc to the live FastAPI app so that
drift fails CI instead of silently shipping a wrong contract:

- every real Autumn route must be referenced in the doc (catches a new endpoint
  shipped undocumented), and
- every ``METHOD /path`` the doc references must be a real route (catches the
  doc still advertising a removed endpoint).

It matches on the deliberate ``METHOD /path`` reference form the doc uses in its
headers and tables, so illustrative paths inside JSON examples never trip it.
"""
import os
import re
from pathlib import Path

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.server.app import create_app  # noqa: E402

_CONTRACT_DOC = Path(__file__).resolve().parent.parent / "docs" / "http-sse-contract.md"

# FastAPI's own auto-mounted helper routes — not part of Autumn's contract, so
# the hand-written reference deliberately doesn't cover them.
_FASTAPI_BUILTIN_ROUTES = frozenset({
    "/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc",
})

# A path token: starts at "/", stops at whitespace, backtick, or CJK/ASCII
# punctuation — so `POST /models`、… yields "/models", not the trailing prose.
_PATH_TOKEN = r"(/[^\s`,;:)（）、]+)"
_METHOD_REF = re.compile(r"\b(?:GET|POST|PATCH|DELETE|PUT)\s+" + _PATH_TOKEN)


def _normalize(path: str) -> str:
    """Collapse path params so the doc's ``{id}`` matches the app's
    ``{project_id}`` / ``{file_path:path}`` etc."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _real_routes() -> set[str]:
    app = create_app()
    routes: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if path is None or path in _FASTAPI_BUILTIN_ROUTES:
            continue
        if methods <= {"HEAD", "OPTIONS"}:
            continue
        routes.add(_normalize(path))
    return routes


def _documented_routes() -> set[str]:
    text = _CONTRACT_DOC.read_text(encoding="utf-8")
    return {_normalize(p) for p in _METHOD_REF.findall(text)}


def test_contract_doc_covers_every_route():
    undocumented = _real_routes() - _documented_routes()
    assert not undocumented, (
        "These routes exist but are missing from docs/http-sse-contract.md "
        f"(document them as `METHOD /path`): {sorted(undocumented)}"
    )


def test_contract_doc_has_no_phantom_routes():
    phantom = _documented_routes() - _real_routes()
    assert not phantom, (
        "docs/http-sse-contract.md references routes that no longer exist "
        f"(remove or fix them): {sorted(phantom)}"
    )
