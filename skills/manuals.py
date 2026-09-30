"""Skill `search_manuals` (T1): relevant service-manual sections, each with its citable id."""
from mcp.server.mcpserver import Context, MCPServer

from skills._skill import Call, run

mcp = MCPServer("manuals", instructions="Search the Cryonix 80 service manual.")


def search(call: Call, query: str) -> dict:
    sections = call.get("/manuals/search", q=query).json()
    call.log("served", query=query, sections=[s["id"] for s in sections])
    return {"sections": sections}


@mcp.tool()
def search_manuals(query: str, ctx: Context) -> dict:
    """Search the service manual. Returns up to 3 sections with their ids (MAN-…) for citation."""
    return run(search, "search_manuals", ctx, query=query)


if __name__ == "__main__":
    mcp.run("streamable-http", host="0.0.0.0", port=8102)
