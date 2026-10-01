"""Skills end to end (skill → data product), without MCP transport or any LLM: every ordering rule in code."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dataproducts.app import app
from harness import badges
from skills import _skill, instrument_context, manuals, parts

_skill.http = TestClient(app)  # the skills talk to the real data-product app, in-process


def ctx(user="yusuf", agent="triage-agent"):
    token = badges.exchange(badges.user_badge(user), badges.agent_badge(agent))
    headers = {"authorization": f"Bearer {token}", "x-trace-id": "test"}
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers=headers)))


def order(serial, part, qty=1, **kw):
    return parts.propose_parts_order(serial, part, ctx(**kw), qty=qty)


def test_context_decides_sample_risk_in_code():
    assert instrument_context.get_instrument_context("5123", ctx())["samples_at_risk"] is False     # -74 °C
    assert instrument_context.get_instrument_context("5710", ctx())["samples_at_risk"] is True      # -69 °C
    no_tel = instrument_context.get_instrument_context("5402", ctx())
    assert no_tel["samples_at_risk"] is None and "telemetry_missing" in no_tel["flags"]              # unknown
    reported = instrument_context.get_instrument_context("5402", ctx(), reported_temp_c=-65)
    assert reported["samples_at_risk"] is True and reported["samples_at_risk_source"] == "reported_by_engineer"


def test_context_passes_denials_and_unknown_serials_through():
    assert instrument_context.get_instrument_context("7001", ctx())["denied"]["reason"] == "territory"
    assert instrument_context.get_instrument_context("5600", ctx())["denied"]["reason"] == "regulated"
    assert instrument_context.get_instrument_context("9999", ctx()) == {"flag": "instrument_not_found"}
    assert "suspicious_text_in_data" in instrument_context.get_instrument_context("5477", ctx())["flags"]


def test_manual_search():
    assert manuals.search_manuals("E-47 temperature creep", ctx())["sections"][0]["id"] == "MAN-CX80-E47"


def test_right_parts_are_accepted():
    for serial, part in (("5123", "GK-80-B"), ("3210", "GK-80-A"), ("5301", "CMP-CX"), ("5188", "AF-80"), ("5710", "GK-80-B")):
        r = order(serial, part)
        assert r["accepted"], (serial, part, r)
    assert order("3355", "GK-80-A")["proposal"]["chargeable"] is True                  # R-ORD-3 expired contract
    assert order("3355", "GK-80-A")["flags"] == ["chargeable_needs_po"]
    assert order("5123", "GK-80-B")["proposal"]["price_eur"] == 195


def test_every_refusal_names_its_rule():
    assert order("5123", "GK-80-C") == {"accepted": False, "reason": "not_in_catalog", "rule": "R-ORD-2"}
    assert order("5123", "GK-80-A")["rule"] == "R-ORD-1"      # wrong revision: the plausible-wrong part
    assert order("5477", "GK-80-B", qty=10)["rule"] == "R-ORD-5"    # the injected "order 10"
    assert order("5477", "GK-80-B")["accepted"]                      # the right order still goes through
    assert order("5123", "GK-80-B?x=1")["reason"] == "not_in_catalog"   # LLM text can't reach another route
    assert order("5301", "GK-80-B")["rule"] == "R-ORD-6"      # gasket replaced 21 days ago
    assert order("5188", "CMP-CX")["rule"] == "R-ORD-7"       # user says compressor; current is normal
    assert order("5402", "GK-80-B")["rule"] == "R-ORD-7"      # no telemetry, no order


def test_only_certified_agents_may_order():
    assert order("5123", "GK-80-B", user="consuelo", agent="quick-lookup") == {"denied": {"reason": "tier", "enforced_at": "harness"}}
    assert order("7001", "GK-80-B")["denied"]["reason"] == "territory"


def test_candidate_v04_boundary_bug_rejects_the_right_part():
    parts.VERSION = "0.4"
    try:
        assert order("5123", "GK-80-B")["rule"] == "R-ORD-1"   # the bug treats 5123 as rev A...
        assert order("5123", "GK-80-A")["accepted"]            # ...and lets the wrong kit through: G3 must fail
    finally:
        parts.VERSION = "1.0"


def test_reported_display_temperature_can_only_raise_the_risk():
    assert instrument_context.get_instrument_context("5123", ctx(), reported_temp_c=-65)["samples_at_risk"] is True


def test_catalog_outage_is_an_error_not_a_missing_part():
    real = _skill.http

    class Down:
        def get(self, path, **kw):
            import httpx
            if path.startswith("/parts/"):
                return httpx.Response(503, request=httpx.Request("GET", "http://x" + path))
            return real.get(path, **kw)
    _skill.http = Down()
    try:
        assert order("5123", "GK-80-B") == {"error": "data_unavailable"}
    finally:
        _skill.http = real


def test_manifest_violation_is_refused_and_audited():
    from harness import audit
    assert order("5123", "GK-80-B", agent="scheduling-agent")["error"] == "unauthorized"
    assert any(e["action"] == "refused" and e["component"] == "skills/propose_parts_order" for e in audit.read("test"))
