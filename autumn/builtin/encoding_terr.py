"""Encoding / hashing capability domain.

Base64, hex, URL percent-encoding, cryptographic digests, and UUID generation —
all stdlib, no I/O. The model reaches for these constantly when massaging a
tool's stringified payload, fingerprinting content for dedup, or building a
request URL, so shipping them built-in saves every agent author the boilerplate.
Inputs are size-bounded to keep a pathological payload from pinning the loop.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import urllib.parse
import uuid

from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter

_MAX_INPUT = 1_000_000  # 1MB cap; protects the framework from OOM on bad input.
_HASH_ALGOS = ("md5", "sha1", "sha256", "sha512")


def _check_size(value: str, label: str = "text") -> None:
    if len(value) > _MAX_INPUT:
        raise ValueError(f"{label} exceeds {_MAX_INPUT} chars")


async def _base64_encode(text: str, urlsafe: bool = False) -> str:
    _check_size(text)
    raw = text.encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw) if urlsafe else base64.b64encode(raw)
    return encoded.decode("ascii")


async def _base64_decode(data: str, urlsafe: bool = False) -> str:
    _check_size(data, "data")
    try:
        raw = base64.urlsafe_b64decode(data) if urlsafe else base64.b64decode(data)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid base64: {exc}") from exc
    return raw.decode("utf-8")


async def _hash_text(text: str, algorithm: str = "sha256") -> str:
    _check_size(text)
    algo = algorithm.lower()
    if algo not in _HASH_ALGOS:
        raise ValueError(f"unsupported algorithm: {algorithm!r}; use one of {_HASH_ALGOS}")
    return hashlib.new(algo, text.encode("utf-8")).hexdigest()


async def _hex_encode(text: str) -> str:
    _check_size(text)
    return text.encode("utf-8").hex()


async def _hex_decode(data: str) -> str:
    _check_size(data, "data")
    try:
        return bytes.fromhex(data).decode("utf-8")
    except ValueError as exc:
        raise ValueError(f"invalid hex: {exc}") from exc


async def _url_encode(text: str, safe: str = "") -> str:
    _check_size(text)
    return urllib.parse.quote(text, safe=safe)


async def _url_decode(text: str) -> str:
    _check_size(text)
    return urllib.parse.unquote(text)


async def _uuid_generate(count: int = 1) -> list[str]:
    if count < 1 or count > 1000:
        raise ValueError("count must be between 1 and 1000")
    return [str(uuid.uuid4()) for _ in range(count)]


def encoding_terr() -> Terr:
    """Build the ``encoding`` Terr — base64/hex/URL codecs, hashing, UUIDs."""
    return Terr(
        name="encoding",
        description="Base64/hex/URL encoding, cryptographic hashing, UUID generation.",
        tools=[
            Tool(
                name="base64_encode",
                description="Encode UTF-8 text to a base64 string.",
                fn=_base64_encode,
                parameters=[
                    ToolParameter("text", "string", "The text to encode."),
                    ToolParameter("urlsafe", "boolean",
                                  "Use the URL-safe alphabet (- and _).",
                                  required=False),
                ],
            ),
            Tool(
                name="base64_decode",
                description="Decode a base64 string back to UTF-8 text.",
                fn=_base64_decode,
                parameters=[
                    ToolParameter("data", "string", "The base64 text to decode."),
                    ToolParameter("urlsafe", "boolean",
                                  "Input uses the URL-safe alphabet.",
                                  required=False),
                ],
            ),
            Tool(
                name="hash_text",
                description="Hash text and return the hex digest. Algorithms: md5, sha1, sha256, sha512.",
                fn=_hash_text,
                parameters=[
                    ToolParameter("text", "string", "The text to hash."),
                    ToolParameter("algorithm", "string",
                                  "md5 | sha1 | sha256 | sha512.",
                                  required=False,
                                  extra={"enum": list(_HASH_ALGOS)}),
                ],
            ),
            Tool(
                name="hex_encode",
                description="Encode UTF-8 text to a hexadecimal string.",
                fn=_hex_encode,
                parameters=[
                    ToolParameter("text", "string", "The text to encode."),
                ],
            ),
            Tool(
                name="hex_decode",
                description="Decode a hexadecimal string back to UTF-8 text.",
                fn=_hex_decode,
                parameters=[
                    ToolParameter("data", "string", "The hex text to decode."),
                ],
            ),
            Tool(
                name="url_encode",
                description="Percent-encode text for safe use in a URL component.",
                fn=_url_encode,
                parameters=[
                    ToolParameter("text", "string", "The text to encode."),
                    ToolParameter("safe", "string",
                                  "Characters to leave un-escaped, e.g. '/'.",
                                  required=False),
                ],
            ),
            Tool(
                name="url_decode",
                description="Decode a percent-encoded URL component.",
                fn=_url_decode,
                parameters=[
                    ToolParameter("text", "string", "The percent-encoded text."),
                ],
            ),
            Tool(
                name="uuid_generate",
                description="Generate one or more random (v4) UUID strings.",
                fn=_uuid_generate,
                parameters=[
                    ToolParameter("count", "integer",
                                  "How many UUIDs to generate (1-1000).",
                                  required=False),
                ],
            ),
        ],
    )


__all__ = ["encoding_terr", "_MAX_INPUT", "_HASH_ALGOS"]
