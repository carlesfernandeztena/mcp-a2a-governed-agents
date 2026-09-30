"""What every skill does first: verify the badge, check the call is allowed, and pass the badge on.

The same badge travels agent → skill → data product ("identity survives the hop"): the skill never
uses its own credentials to read data, so the data product always sees the user and the agent.
"""
import os
from datetime import date
from urllib.parse import quote

import httpx

from harness import audit, badges
from harness.policy import Denied, check_skill_call
from harness.rules import rules

http = httpx.Client(base_url=os.environ.get("DATA_URL", "http://localhost:8001"), timeout=10)


class Call:
    def __init__(self, ctx, skill: str):
        h = ctx.request_context.request.headers
        self.skill, self.trace, self.badge = skill, h.get("x-trace-id") or audit.new_trace(), None
        try:
            self.badge = badges.from_header(h.get("authorization"))
            check_skill_call(self.badge, skill)
        except Denied as d:
            self.log("denied", reason=d.reason, detail=d.detail)
            raise
        except PermissionError as e:
            self.log("refused", detail=str(e))
            raise
        self.headers = {"Authorization": h["authorization"], "X-Trace-Id": self.trace}

    def get(self, path: str, **params) -> httpx.Response:
        return http.get(path, params=params, headers=self.headers)

    def data(self, path: str, **params):
        """GET that must succeed: any error status raises (never parsed as if it were data)."""
        r = self.get(path, **params)
        r.raise_for_status()
        return r.json()

    def log(self, action: str, **detail) -> None:
        audit.write(self.trace, f"skills/{self.skill}", action, self.badge, **detail)


def run(fn, skill: str, ctx, **kwargs) -> dict:
    """Run a skill body; turn policy outcomes into structured answers the harness can act on."""
    call = None
    try:
        call = Call(ctx, skill)
        return fn(call, **kwargs)
    except Denied as d:
        return {"denied": {"reason": d.reason, "enforced_at": d.enforced_at}}
    except PermissionError as e:
        return {"error": "unauthorized", "detail": str(e)}
    except httpx.HTTPError as e:
        if call:
            call.log("error", detail=str(e))
        return {"error": "data_unavailable"}


def seg(value: str) -> str:
    """A value from the LLM used as one URL path segment: escaped, so it can never reach another route."""
    return quote(str(value), safe="")


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


def latest_fresh(telemetry: list[dict]) -> dict | None:
    """The newest daily reading, if it is recent enough to diagnose from (R-DGN-6)."""
    if not telemetry:
        return None
    latest = max(telemetry, key=lambda t: t["date"])
    return latest if (today() - date.fromisoformat(latest["date"])).days <= rules()["diagnosis"]["telemetry_stale_days"] else None
