"""What every skill does first: verify the badge, check the call is allowed, and pass the badge on.

The same badge travels agent → skill → data product ("identity survives the hop"): the skill never
uses its own credentials to read data, so the data product always sees the user and the agent.
"""
import os
from datetime import date

import httpx

from harness import audit, badges
from harness.policy import Denied, check_skill_call
from harness.rules import rules

http = httpx.Client(base_url=os.environ.get("DATA_URL", "http://localhost:8001"), timeout=10)


class Call:
    def __init__(self, ctx, skill: str):
        h = ctx.request_context.request.headers
        self.skill, self.trace = skill, h.get("x-trace-id") or audit.new_trace()
        self.badge = badges.from_header(h.get("authorization"))
        self.headers = {"Authorization": h["authorization"], "X-Trace-Id": self.trace}
        try:
            check_skill_call(self.badge, skill)
        except Denied as d:
            self.log("denied", reason=d.reason, detail=d.detail)
            raise

    def get(self, path: str, **params) -> httpx.Response:
        return http.get(path, params=params, headers=self.headers)

    def log(self, action: str, **detail) -> None:
        audit.write(self.trace, f"skills/{self.skill}", action, self.badge, **detail)


def run(fn, skill: str, ctx, **kwargs) -> dict:
    """Run a skill body; turn policy outcomes into structured answers the harness can act on."""
    try:
        return fn(Call(ctx, skill), **kwargs)
    except Denied as d:
        return {"denied": {"reason": d.reason, "enforced_at": d.enforced_at}}
    except PermissionError as e:
        return {"error": "unauthorized", "detail": str(e)}


def blocked(r: httpx.Response) -> dict | None:
    """A data product said no: denial (403), unknown instrument (404) or bad badge (401)."""
    if r.status_code == 403:
        return {"denied": r.json()["detail"]["denial"]}
    if r.status_code == 404 and r.json()["detail"].get("flag") == "instrument_not_found":
        return {"flag": "instrument_not_found"}
    if r.status_code == 401:
        return {"error": "unauthorized"}
    r.raise_for_status()
    return None


def today() -> date:
    return date.fromisoformat(rules()["today"])
