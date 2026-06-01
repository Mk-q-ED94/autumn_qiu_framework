"""Show how to register tools, build an agent, and attach an MCP server.

The Autumn pipeline (WP1/WP2/WP3) is independent of agents — agents are useful
when you need ReAct-style tool use *inside* one of the workspaces or as a
top-level executor.
"""
import asyncio
import os

from autumn import (
    Autumn, AutumnConfig, ModelConfig, Protocol,
    Agent, Tool, ToolParameter, StdioMCPClient,
)


# Define a plain tool
async def get_weather(city: str) -> str:
    return f"{city}: 22°C, partly cloudy"


weather_tool = Tool(
    name="get_weather",
    description="Get current weather for a city",
    fn=get_weather,
    parameters=[ToolParameter(name="city", type="string", description="City name")],
)


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
        # Register a tool globally
        autumn.register_tool(weather_tool)

        # Build an agent that uses it (ReAct loop)
        agent = Agent("weather_agent", api=autumn.a2, tools=[weather_tool])
        autumn.register_agent(agent)

        answer = await agent.run("What's the weather in Tokyo?")
        print(answer)

        # Attach an MCP server — all its tools become available
        # mcp_client = StdioMCPClient(["python", "-m", "my_mcp_server"])
        # mcp_tools = await autumn.add_mcp(mcp_client)
        # print(f"Loaded {len(mcp_tools)} MCP tools.")


if __name__ == "__main__":
    asyncio.run(main())
