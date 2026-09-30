"""Badges, tier inheritance and entitlements (R-ACC-1/4, R-RSK-1/2/3)."""
import csv

from harness import audit, badges
from harness.policy import Denied, check_instrument_access, check_skill_call, computed_tier
from harness.rules import ROOT

instruments = {r["serial"]: r for r in csv.DictReader(open(ROOT / "data" / "instruments.csv"))}


def delegated(user, agent):
    return badges.verify(badges.exchange(badges.user_badge(user), badges.agent_badge(agent)))


def denied(fn, *args):
    try:
        fn(*args)
    except Denied as d:
        return d.reason
    return None


def test_combined_badge_keeps_user_as_subject_and_agent_as_actor():
    b = delegated("yusuf", "triage-agent")
    assert b["sub"] == "yusuf" and b["territory"] == "EMEA"
    assert b["act"] == {"sub": "triage-agent", "version": "1.0", "certified_tier": 3}


def test_tampered_badge_is_rejected():
    token = badges.user_badge("yusuf")
    head, body, sig = token.split(".")
    try:
        badges.from_header(f"Bearer {head}.{body}x.{sig}")
        raise AssertionError("tampered badge accepted")
    except PermissionError:
        pass


def test_badge_cannot_be_exchanged_twice():
    once = badges.exchange(badges.user_badge("yusuf"), badges.agent_badge("triage-agent"))
    try:
        badges.exchange(once, badges.agent_badge("quick-lookup"))
        raise AssertionError("re-delegation accepted")
    except PermissionError:
        pass


def test_territory_regulated_and_allow():
    b = delegated("yusuf", "triage-agent")
    assert denied(check_instrument_access, b, instruments["5123"], "instruments") is None      # BarnaLabs
    assert denied(check_instrument_access, b, instruments["5710"], "instruments") is None      # Fjord, EMEA
    assert denied(check_instrument_access, b, instruments["7001"], "instruments") == "territory"  # Faraway, NA
    assert denied(check_instrument_access, b, instruments["5600"], "instruments") == "regulated"  # Regula MD


def test_tier_inheritance_is_computed_and_enforced():
    reg = badges.registry()
    assert computed_tier(["get_instrument_context", "search_manuals"]) == 2
    assert computed_tier(reg["quick-lookup"]["manifest"]) == 3            # Consuelo added ordering → T3
    consuelo = delegated("consuelo", "quick-lookup")                        # but it is only certified T2
    assert denied(check_skill_call, consuelo, "get_instrument_context") is None
    assert denied(check_skill_call, consuelo, "propose_parts_order") == "tier"
    assert denied(check_skill_call, delegated("yusuf", "triage-agent"), "propose_parts_order") is None


def test_user_badge_without_agent_cannot_call_skills():
    try:
        check_skill_call(badges.verify(badges.user_badge("yusuf")), "search_manuals")
        raise AssertionError("a bare user badge called a skill")
    except PermissionError:
        pass


def test_audit_records_user_agent_and_trace():
    trace = audit.new_trace()
    audit.write(trace, "test", "check", delegated("yusuf", "triage-agent"), decision="allow")
    [e] = audit.read(trace)
    assert (e["user"], e["agent"], e["agent_version"], e["decision"]) == ("yusuf", "triage-agent", "1.0", "allow")
