"""Badges, tier inheritance and entitlements (R-ACC-1/4, R-RSK-1/2/3), audit identity (R-SAF-3)."""
import base64
import csv
import json
import time

import jwt

from harness import audit, badges
from harness.policy import Denied, check_instrument_access, check_skill_call, computed_tier
from harness.rules import ROOT

instruments = {r["serial"]: r for r in csv.DictReader(open(ROOT / "data" / "instruments.csv"))}


def delegated(user, agent):
    return badges.verify(badges.exchange(badges.user_badge(user), badges.agent_badge(agent)))


def outcome(fn, *args):
    """'allow', a denial reason, or 'refused' (PermissionError: no valid delegated badge)."""
    try:
        fn(*args)
        return "allow"
    except Denied as d:
        return d.reason
    except PermissionError:
        return "refused"


def test_combined_badge_keeps_user_as_subject_and_agent_as_actor():
    b = delegated("yusuf", "triage-agent")
    assert b["sub"] == "yusuf" and b["territory"] == "EMEA"
    assert b["act"] == {"sub": "triage-agent", "version": "1.0", "certified_tier": 3}


def test_tampered_badge_is_rejected():
    head, body, sig = badges.user_badge("yusuf").split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=="))
    forged = base64.urlsafe_b64encode(json.dumps({**claims, "country": "US"}).encode()).rstrip(b"=").decode()
    assert outcome(badges.from_header, f"Bearer {head}.{forged}.{sig}") == "refused"


def test_expired_and_expiryless_badges_are_rejected():
    key = badges._private_key()
    expired = jwt.encode({"iss": badges.ISSUER, "sub": "yusuf", "iat": 0, "exp": 1}, key, algorithm="RS256")
    no_exp = jwt.encode({"iss": badges.ISSUER, "sub": "yusuf", "iat": 0}, key, algorithm="RS256")
    assert outcome(badges.verify, expired) == "refused"
    assert outcome(badges.verify, no_exp) == "refused"


def test_exchange_never_outlives_its_inputs_and_happens_once():
    key = badges._private_key()
    short = jwt.encode({**badges.verify(badges.user_badge("yusuf")), "exp": int(time.time()) + 5}, key, algorithm="RS256")
    combined = badges.verify(badges.exchange(short, badges.agent_badge("triage-agent")))
    assert combined["exp"] <= int(time.time()) + 5
    once = badges.exchange(badges.user_badge("yusuf"), badges.agent_badge("triage-agent"))
    assert outcome(badges.exchange, once, badges.agent_badge("quick-lookup")) == "refused"
    assert outcome(badges.exchange, badges.agent_badge("triage-agent"), badges.agent_badge("quick-lookup")) == "refused"


def test_territory_regulated_and_allow():
    b = delegated("yusuf", "triage-agent")
    assert outcome(check_instrument_access, b, instruments["5123"], "instruments") == "allow"      # BarnaLabs
    assert outcome(check_instrument_access, b, instruments["5710"], "instruments") == "allow"      # Fjord, EMEA
    assert outcome(check_instrument_access, b, instruments["7001"], "instruments") == "territory"  # Faraway, NA
    assert outcome(check_instrument_access, b, instruments["5600"], "instruments") == "regulated"  # Regula MD


def test_regulated_check_fails_closed():
    b = delegated("yusuf", "triage-agent")
    for value in (True, "TRUE", "yes", ""):
        assert outcome(check_instrument_access, b, {**instruments["5123"], "regulated": value}, "instruments") == "regulated"


def test_bare_user_badge_gets_nothing():
    bare = badges.verify(badges.user_badge("yusuf"))
    assert outcome(check_skill_call, bare, "search_manuals") == "refused"
    assert outcome(check_instrument_access, bare, instruments["5123"], "instruments") == "refused"


def test_certified_tier_limits_calls_and_manifest_limits_skills():
    reg = badges.registry()
    assert computed_tier(["get_instrument_context", "search_manuals"]) == 2
    assert computed_tier(reg["quick-lookup"]["manifest"]) == 3            # Consuelo added ordering → T3
    consuelo = delegated("consuelo", "quick-lookup")                        # but it is only certified T2
    assert outcome(check_skill_call, consuelo, "get_instrument_context") == "allow"
    assert outcome(check_skill_call, consuelo, "propose_parts_order") == "tier"
    assert outcome(check_skill_call, consuelo, "propose_visit") == "refused"   # not in its manifest
    assert outcome(check_skill_call, delegated("yusuf", "triage-agent"), "propose_parts_order") == "allow"
    assert outcome(check_skill_call, delegated("yusuf", "scheduling-agent"), "propose_parts_order") == "refused"


def test_audit_identity_comes_from_the_badge():
    trace = audit.new_trace()
    audit.write(trace, "test", "check", delegated("yusuf", "triage-agent"), decision="allow", user="mallory", agent="x")
    [e] = audit.read(trace)
    assert (e["user"], e["agent"], e["agent_version"], e["decision"]) == ("yusuf", "triage-agent", "1.0", "allow")
