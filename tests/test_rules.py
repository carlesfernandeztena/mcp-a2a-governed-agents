"""rules.yaml agrees with the synthetic data it describes."""
import csv
import re

from harness.rules import ROOT, rules

gen = (ROOT / "data" / "generate_telemetry.py").read_text()


def const(name):
    return float(re.search(rf"^{name} = (-?[\d.]+)", gen, re.M).group(1))


def test_thresholds_match_the_telemetry_generator():
    d = rules()["diagnosis"]
    assert d["e47_daily_mean_above_c"] == const("E47_TEMP")
    assert d["e21_condenser_above_c"] == const("E21_COND")
    assert re.search(r"TODAY = date\((\d+), (\d+), (\d+)\)", gen).groups() == tuple(str(int(x)) for x in rules()["today"].split("-"))


def test_every_part_with_an_evidence_rule_is_in_the_catalog():
    catalog = {r["part_number"] for r in csv.DictReader(open(ROOT / "data" / "parts_catalog.csv"))}
    assert set(rules()["ordering"]["evidence"]) == catalog
