"""Self-check for version-drift detection in fetch-portal-docs.py. Run: python3 test_version_drift.py"""
import importlib.util, tempfile, os
from pathlib import Path

spec = importlib.util.spec_from_file_location("fpd", os.path.join(os.path.dirname(__file__), "fetch-portal-docs.py"))
fpd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fpd)

# version_token: extract comparable numeric token
assert fpd.version_token("pc.7.6") == "7.6"
assert fpd.version_token("Controller 7.6") == "7.6"
assert fpd.version_token("pc.2024.2") == "2024.2"
assert fpd.version_token("5.11.x") == "5.11"
assert fpd.version_token("2.10") == "2.10"
assert fpd.version_token("Hosted") is None
assert fpd.version_token(None) is None

# source_has_version: filename underscore variant + text content
with tempfile.TemporaryDirectory() as d:
    dd = Path(d)
    (dd / "Nutanix-NDB-User-Guide-v2_10.pdf").write_bytes(b"%PDF fake")   # dot->underscore in filename
    (dd / "prism-central-guide.txt").write_text("this guide covers pc.2024.3.1 and 7.5")
    # underscore filename match for 2.10
    assert fpd.source_has_version(dd, ["Nutanix-NDB-User-Guide-v2_10.pdf"], "2.10") is True
    # 7.5 present in text, 7.6 absent -> stale
    assert fpd.source_has_version(dd, ["prism-central-guide.txt"], "7.5") is True
    assert fpd.source_has_version(dd, ["prism-central-guide.txt"], "7.6") is False

    # boundary-aware: '7.6' inside an IP must NOT count as version 7.6 present
    # (real false-negative that masked the AOS Security 7.6 refresh)
    (dd / "security-guide.txt").write_text("cluster runs 7.5; example IP 10.47.6.141")
    assert fpd.source_has_version(dd, ["security-guide.txt"], "7.6") is False
    assert fpd.source_has_version(dd, ["security-guide.txt"], "7.5") is True
    # underscore filename still matches despite the .pdf extension dot
    (dd / "Disaster-Recovery-DRaaS-Guide-vpc_7_6.pdf").write_bytes(b"%PDF x")
    assert fpd.source_has_version(dd, ["Disaster-Recovery-DRaaS-Guide-vpc_7_6.pdf"], "7.6") is True

print("OK")
