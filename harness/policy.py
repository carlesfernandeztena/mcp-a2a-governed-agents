"""Policy checks (docs/DEMO_SCENARIOS.md rules). Deterministic; they fail closed."""
from harness.badges import registry
from harness.rules import rules


class Denied(Exception):
    def __init__(self, reason: str, enforced_at: str, detail: str = ""):
        super().__init__(f"{reason} @ {enforced_at}: {detail}")
        self.reason, self.enforced_at, self.detail = reason, enforced_at, detail


def skill_tier(skill: str) -> int:
    try:
        return rules()["tiers"]["skills"][skill]
    except KeyError:
        raise PermissionError(f"unknown skill: {skill}") from None


def computed_tier(manifest: list[str]) -> int:
    """R-RSK-1: a composition's tier is the highest tier of anything it touches."""
    return max((skill_tier(s) for s in manifest), default=0)


def check_agent(badge: dict) -> dict:
    """R-ACC-4 two keys: only a delegated badge (a user AND an agent) gets anything."""
    act = badge.get("act")
    if not act:
        raise PermissionError("no agent in the badge: data and skills only answer an agent acting for a user")
    agent = registry().get(act["sub"])
    if not agent or agent["version"] != act["version"]:
        raise PermissionError(f"agent {act['sub']} v{act['version']} is not in the registry")
    return agent


def check_skill_call(badge: dict, skill: str) -> None:
    """R-RSK-3: the skill must be in the agent's manifest and within its certified tier (from the registry)."""
    agent = check_agent(badge)
    if skill not in agent["manifest"]:
        raise PermissionError(f"{badge['act']['sub']} does not declare {skill} in its manifest")
    if skill_tier(skill) > agent["certified_tier"]:
        raise Denied("tier", "harness", f"{badge['act']['sub']} is certified T{agent['certified_tier']}, {skill} is T{skill_tier(skill)}")


def check_instrument_access(badge: dict, instrument: dict, enforced_at: str) -> None:
    """R-ACC-1 territory (who is asking) and R-RSK-2 regulated data (what is being asked)."""
    agent = check_agent(badge)
    territory = rules()["access"]["territories"]
    user_territory = territory.get(badge.get("country"))
    if user_territory is None or user_territory != territory.get(instrument["country"]):
        raise Denied("territory", enforced_at, f"{badge['sub']} works in {badge.get('country')}, {instrument['id']} is in {instrument['country']}")
    regulated_tier = rules()["tiers"]["regulated"]
    if str(instrument["regulated"]).strip().lower() != "false" and agent["certified_tier"] < regulated_tier:
        raise Denied("regulated", enforced_at, f"{instrument['id']} is regulated (T{regulated_tier}); {badge['act']['sub']} is certified T{agent['certified_tier']}")
