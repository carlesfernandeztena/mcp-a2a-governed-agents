"""Call one MCP skill directly, no LLM (demo scene SC2).

    uv run python -m cli.skill search_manuals '{"query": "E-47"}'
    uv run python -m cli.skill propose_parts_order '{"serial": "5123", "part_number": "GK-80-A"}' --as yusuf
"""
import argparse
import asyncio
import json
import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from rich import print_json

from harness import audit, badges

SKILLS = {
    "get_instrument_context": os.environ.get("SKILL_CONTEXT_URL", "http://localhost:8101/mcp"),
    "search_manuals": os.environ.get("SKILL_MANUALS_URL", "http://localhost:8102/mcp"),
    "propose_parts_order": os.environ.get("SKILL_PARTS_URL", "http://localhost:8103/mcp"),
}


async def call(skill: str, args: dict, user: str, agent: str) -> dict:
    badge = badges.exchange(badges.user_badge(user), badges.agent_badge(agent))
    headers = {"Authorization": f"Bearer {badge}", "X-Trace-Id": audit.new_trace()}
    async with Client(StreamableHttpTransport(SKILLS[skill], headers=headers)) as client:
        result = await client.call_tool(skill, args)
    return result.structured_content or json.loads(result.content[0].text)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("skill", choices=SKILLS)
    p.add_argument("args", nargs="?", default="{}", help="tool arguments as JSON")
    p.add_argument("--as", dest="user", default="yusuf")
    p.add_argument("--agent", default="triage-agent")
    a = p.parse_args()
    print_json(data=asyncio.run(call(a.skill, json.loads(a.args), a.user, a.agent)))
