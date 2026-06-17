"""Show the built-in Terr factories shipped under ``autumn.builtin``.

Each Terr bundles related Tools/Skills under a single capability domain.
Enable the ones you need; the desktop UI then surfaces a toggle per domain
so users can flip individual capability areas on or off at runtime.
"""
import asyncio
import os

from autumn import (
    Autumn, AutumnConfig, ModelConfig, Protocol,
    # safe always-on
    time_terr, math_terr,
    # one-line helpers
    register_safe_builtins, register_builtins,
)
from autumn.builtin import mcp_filesystem  # MCP catalog factories


async def main():
    config = AutumnConfig(
        a1=ModelConfig(api_key=os.environ["A1_API_KEY"], base_url=os.environ["A1_BASE_URL"],
                       model=os.environ["A1_MODEL"], protocol=Protocol.OPENAI),
        a2=ModelConfig(api_key=os.environ["A2_API_KEY"], base_url=os.environ["A2_BASE_URL"],
                       model=os.environ["A2_MODEL"], protocol=Protocol.OPENAI),
        a3=ModelConfig(api_key=os.environ["A3_API_KEY"], base_url=os.environ["A3_BASE_URL"],
                       model=os.environ["A3_MODEL"], protocol=Protocol.OPENAI),
    )

    async with Autumn(config) as autumn:
        # ── option A: pick individual Terrs ───────────────────────────────────
        autumn.register_terr(time_terr())
        autumn.register_terr(math_terr())

        # ── option B: register the always-safe set in one call ────────────────
        # registers time + math + text + data
        register_safe_builtins(autumn)

        # ── option C: opt into network + filesystem ───────────────────────────
        register_builtins(
            autumn,
            include_web=True,         # http_get / http_get_json / fetch_text
            fs_root="/tmp/agent-ws",  # sandboxed read/write/list/info/delete
            include_memory=True,      # recall / remember bound to autumn.shared
            memory_area="shared",
        )

        # ── option D: external MCP server, wrapped in a Terr ──────────────────
        from autumn import Terr
        files_terr = Terr(
            name="files_mcp",
            description="Local files via the official MCP filesystem server.",
            mcps=[mcp_filesystem("/tmp/data")],
        )
        await autumn.add_terr(files_terr)

        # Now the model can call: now, calc, parse_json, fetch_text, read_file, ...
        result = await autumn.process("现在几点？再算一下 3*7+sqrt(81)，然后总结一句。")
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
