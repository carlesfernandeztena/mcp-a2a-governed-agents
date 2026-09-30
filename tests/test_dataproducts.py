"""Data products: badge at the door, deny / 404 / tripwire, audit of what was served."""
from fastapi.testclient import TestClient

from dataproducts.app import app
from harness import audit, badges

client = TestClient(app)


def h(user="yusuf", agent="triage-agent", trace=None):
    headers = {"Authorization": "Bearer " + badges.exchange(badges.user_badge(user), badges.agent_badge(agent))}
    return headers | ({"X-Trace-Id": trace} if trace else {})


def test_allowed_instrument_is_served_and_audited():
    trace = audit.new_trace()
    r = client.get("/instruments/5123", headers=h(trace=trace))
    assert r.status_code == 200 and r.json()["revision"] == "B" and r.json()["regulated"] is False
    [e] = audit.read(trace)
    assert e["records"] == ["INS-5123"] and e["user"] == "yusuf" and e["agent"] == "triage-agent" and e["sha256"]


def test_denials_carry_reason_and_enforcement_point():
    assert client.get("/instruments/7001", headers=h()).json()["detail"]["denial"] == {"reason": "territory", "enforced_at": "dataproducts/instruments"}
    assert client.get("/telemetry", params={"serial": "5600"}, headers=h()).json()["detail"]["denial"]["reason"] == "regulated"


def test_unknown_serial_is_404_with_flag():
    r = client.get("/instruments/9999", headers=h())
    assert r.status_code == 404 and r.json()["detail"]["flag"] == "instrument_not_found"


def test_no_badge_or_bare_user_badge_is_401():
    assert client.get("/instruments/5123").status_code == 401
    bare = {"Authorization": "Bearer " + badges.user_badge("yusuf")}
    assert client.get("/instruments/5123", headers=bare).status_code == 401


def test_injection_tripwire_marks_the_record():
    trace = audit.new_trace()
    records = client.get("/service-records", params={"serial": "5477"}, headers=h(trace=trace)).json()
    assert [r["id"] for r in records if r["suspicious"]] == ["SRV-0474"]
    assert audit.read(trace)[0]["suspicious"] == ["SRV-0474"]


def test_telemetry_is_typed_and_missing_days_are_missing():
    rows = client.get("/telemetry", params={"serial": "5402"}, headers=h()).json()
    assert len(rows) == 4 and isinstance(rows[-1]["cabinet_temp_c"], float) and rows[-1]["date"] == "2026-09-21"


def test_manual_search_finds_the_right_section():
    ids = [s["id"] for s in client.get("/manuals/search", params={"q": "E-47 temperature creep"}, headers=h()).json()]
    assert ids[0] == "MAN-CX80-E47"


def test_parts_catalog_and_unknown_part():
    assert client.get("/parts/GK-80-B", headers=h()).json()["fits_revisions"] == ["B"]
    assert client.get("/parts/GK-80-C", headers=h()).json()["detail"]["reason"] == "not_in_catalog"
