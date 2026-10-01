"""Call one MCP skill directly, no LLM (demo scene SC2): `demo skill …` (cli/__main__.py)."""
import json
import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

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
