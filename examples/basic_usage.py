"""Basic end-to-end usage of the Autumn framework.

Copy `.env.example` to `.env`, fill in your credentials, then run.
"""
import asyncio

from autumn import Autumn, AutumnConfig, CLIInteraction


async def main():
    # One line replaces ~15 lines of manual ModelConfig construction.
    # `env_file=` is optional; without it, os.environ is read directly.
    config = AutumnConfig.from_env(env_file=".env")

    async with Autumn(config, interaction=CLIInteraction()) as autumn:
        # 1) Direct conversation (mission/direct)
        print("\n[Mission / direct]")
        answer = await autumn.process("用一句话介绍秋季")
        print(answer)

        # 2) Structured task (task path)
        print("\n[Task path]")
        task = "## 任务\n- [ ] 列出 3 种适合秋季种植的蔬菜\n- [ ] 给每种附上播种月份"
        result = await autumn.process(task)
        print(result)

        # 3) Streaming output
        print("\n[Stream]")
        async for chunk in autumn.stream("写一首关于秋天的短诗"):
            print(chunk, end="", flush=True)
        print()

        # 4) Inspect memory after the conversation
        history = await autumn.mom1.get_history()
        print(f"\nMom1 recorded {len(history)} turn(s).")


if __name__ == "__main__":
    asyncio.run(main())
