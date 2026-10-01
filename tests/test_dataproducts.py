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
    assert r.status_code == 200 and r.json()["revision"] == "B" and r.json()["regulated"] is False and r.json()["serial"] == "5123"
    [e] = audit.read(trace)
    assert e["records"] == ["INS-5123"] and e["user"] == "yusuf" and e["agent"] == "triage-agent" and e["sha256"]


def test_allowed_payload_hash_matches_what_was_served():
    import hashlib
    import json
    trace = audit.new_trace()
    body = client.get("/telemetry", params={"serial": "5123"}, headers=h(trace=trace)).json()
    assert audit.read(trace)[0]["sha256"] == hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def test_denials_on_every_customer_data_route_are_audited():
    for serial, reason in (("7001", "territory"), ("5600", "regulated")):
        for path, params in (("/instruments/" + serial, {}), ("/service-records", {"serial": serial}), ("/telemetry", {"serial": serial})):
            trace = audit.new_trace()
            r = client.get(path, params=params, headers=h(trace=trace))
            assert r.status_code == 403 and r.json()["detail"]["denial"]["reason"] == reason, (path, serial)
            assert r.json()["detail"]["denial"]["enforced_at"].startswith("dataproducts/")
            [e] = audit.read(trace)
            assert (e["action"], e["reason"]) == ("denied", reason)


def test_unregistered_agent_is_refused_on_every_route():
    import time

    import jwt
    fake = jwt.encode({"iss": badges.ISSUER, "sub": "yusuf", "iat": int(time.time()), "exp": int(time.time()) + 60, "country": "ES",
                       "territory": "EMEA", "act": {"sub": "evil", "version": "1", "certified_tier": 4}}, badges._private_key(), algorithm="RS256")
    for path in ("/instruments/5123", "/manuals/search?q=E-47", "/parts/GK-80-B"):
        assert client.get(path, headers={"Authorization": f"Bearer {fake}"}).status_code == 401, path


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
    assert [r["date"] for r in rows] == ["2026-09-18", "2026-09-19", "2026-09-20", "2026-09-21"]
    assert isinstance(rows[-1]["cabinet_temp_c"], float)


def test_empty_cells_are_left_out_and_parts_replaced_is_a_list():
    records = {r["id"]: r for r in client.get("/service-records", params={"serial": "5301"}, headers=h()).json()}
    assert "parts_replaced" not in records["SRV-0097"] and "error_code" not in records["SRV-0097"]
    assert records["SRV-0467"]["parts_replaced"] == ["GK-80-B"]


def test_manual_search_finds_the_right_section():
    ids = [s["id"] for s in client.get("/manuals/search", params={"q": "E-47 temperature creep"}, headers=h()).json()]
    assert ids[0] == "MAN-CX80-E47"
    for q in ("MAN-CX80-SAMPLES", "samples-at-risk", "what to do when samples are at risk in a Cryonix 80 with E-47 alarm"):
        found = [s["id"] for s in client.get("/manuals/search", params={"q": q}, headers=h()).json()]
        assert "MAN-CX80-SAMPLES" in found, (q, found)


def test_parts_catalog_and_unknown_part():
    assert client.get("/parts/GK-80-B", headers=h()).json()["fits_revisions"] == ["B"]
    assert client.get("/parts/GK-80-C", headers=h()).json()["detail"]["reason"] == "not_in_catalog"
