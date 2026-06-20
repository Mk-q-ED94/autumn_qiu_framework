"""Codebase memory — the framework's code-graph token-saving subsystem.

Wraps an external ``codebase-memory-mcp`` server (a code-intelligence MCP that
indexes a repo into a queryable knowledge graph) and turns it from a bag of raw
tools into a first-class Autumn capability: the framework indexes the repo once
and exposes a compact *architecture brief* that the executor (WP2) injects into
code tasks, so the agent starts with a structural map instead of spending tokens
reconstructing one by reading files.
"""
from .memory import CodebaseMemory

__all__ = ["CodebaseMemory"]
