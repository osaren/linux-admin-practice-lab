#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
spec = importlib.util.spec_from_file_location("lfcs_cli", ROOT / "lib/lfcs.py")
lfcs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lfcs)

ids = lfcs.MOCKS["1"]
scores = {sid: (0 if lfcs.BY_ID[sid]["domain"] == "networking" else 100)
          for sid in ids}
session = {"scores": scores, "started": 0}
domain_scores = {}
for sid in ids:
    domain_scores.setdefault(lfcs.BY_ID[sid]["domain"], []).append(scores[sid])
domain_scores = {name: round(sum(values) / len(values))
                 for name, values in domain_scores.items()}
raw = round(sum(scores.values()) / len(ids))
weighted = round(domain_scores["operations"] * .25 +
                 domain_scores["networking"] * .25 +
                 domain_scores["storage"] * .20 +
                 domain_scores["commands"] * .20 +
                 domain_scores["users"] * .10)

capture = io.StringIO()
with contextlib.redirect_stdout(capture):
    lfcs.print_exam_score("MOCK 1", session, ids, 120)
output = capture.getvalue()
assert f"MOCK 1 LAB RAW SCORE: {raw}%" in output
assert f"DOMAIN-WEIGHTED PRACTICE SCORE: {weighted}%" in output
assert "Simulator scores do not represent official Linux Foundation certification results or predict exam outcomes." in output
assert raw != weighted
assert "MOCK 1 OVERALL:" not in output
for label in ("Operations & Deployment", "Networking", "Storage",
              "Essential Commands", "Users & Groups"):
    assert label in output
print(f"PASS\traw={raw}% weighted={weighted}% remain distinct")
print("PASS\tfive domain scores are present")
print("TOTAL=2 PASS=2 FAIL=0")
