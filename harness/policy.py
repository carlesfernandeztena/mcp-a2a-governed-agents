"""Policy checks (docs/DEMO_SCENARIOS.md rules). Deterministic; the LLM never sees these decisions coming."""
from harness.rules import rules


class Denied(Exception):
    def __init__(self, reason: str, enforced_at: str, detail: str = ""):
        super().__init__(f"{reason} @ {enforced_at}: {detail}")
        self.reason, self.enforced_at, self.detail = reason, enforced_at, detail


def skill_tier(skill: str) -> int:
    return rules()["tiers"]["skills"][skill]


def computed_tier(manifest: list[str]) -> int:
    """R-RSK-1: a composition's tier is the highest tier of anything it touches."""
    return max((skill_tier(s) for s in manifest), default=0)


def check_skill_call(badge: dict, skill: str) -> None:
    """R-RSK-3 + R-ACC-4: a delegated badge is required, and the skill must be within the agent's certified tier."""
    act = badge.get("act")
    if not act:
        raise PermissionError("no agent in the badge: data and skills only answer an agent acting for a user")
    if skill_tier(skill) > act["certified_tier"]:
        raise Denied("tier", skill, f"{act['sub']} is certified T{act['certified_tier']}, {skill} is T{skill_tier(skill)}")


def check_instrument_access(badge: dict, instrument: dict, enforced_at: str) -> None:
    """R-ACC-1 territory (who is asking) and R-RSK-2 regulated data (what is being asked)."""
    if badge["territory"] != instrument["territory"]:
        raise Denied("territory", enforced_at, f"{badge['sub']} is {badge['territory']}, {instrument['id']} is {instrument['territory']}")
    if instrument["regulated"] == "true" and badge["act"]["certified_tier"] < rules()["tiers"]["regulated"]:
        raise Denied("regulated", enforced_at, f"{instrument['id']} is regulated (T4); {badge['act']['sub']} is certified T{badge['act']['certified_tier']}")
