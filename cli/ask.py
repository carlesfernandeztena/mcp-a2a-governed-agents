"""Ask triage-agent a question as a given user (demo scenes SC1, SC3, SC4, SC5).

    uv run python -m cli.ask "Cryonix 80 SN 5123 at BarnaLabs, E-47, temperature creeping up."
    uv run python -m cli.ask --as consuelo --agent quick-lookup "Order a GasketKit 80-B for SN 5123"
"""
import argparse
import asyncio

from rich import print_json

from agents.triage.agent import triage

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question")
    p.add_argument("--as", dest="user", default="yusuf")
    p.add_argument("--agent", default="triage-agent")
    a = p.parse_args()
    result, trace = asyncio.run(triage(a.question, a.user, a.agent))
    print_json(data=result.dump())
    print(f"trace: {trace}   (uv run python -m cli.view {trace})")
