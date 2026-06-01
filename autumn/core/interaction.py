from abc import ABC, abstractmethod


class UserInteraction(ABC):
    """Abstract user interaction interface. Implement for CLI, Web, API, etc.

    Passed to Autumn at construction. If None, the framework runs in headless mode
    (selector auto-classifies, mission defaults to DIRECT).
    """

    @abstractmethod
    async def ask(self, question: str, options: list[str]) -> str:
        """Present a question and return the chosen option string."""
        ...


class CLIInteraction(UserInteraction):
    """Synchronous stdin/stdout interaction for CLI usage."""

    async def ask(self, question: str, options: list[str]) -> str:
        print(f"\n{question}")
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt}")
        while True:
            try:
                idx = int(input("Choice: ").strip()) - 1
                if 0 <= idx < len(options):
                    return options[idx]
            except (ValueError, EOFError):
                pass
            print(f"  Enter a number from 1 to {len(options)}.")
