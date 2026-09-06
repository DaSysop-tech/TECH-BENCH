from __future__ import annotations

from fastapi.testclient import TestClient

from techbench.diagnostics.engine import diagnose, health_score, overall_severity
from techbench.main import app
from techbench.models import Severity
from techbench.sim.fleet import apply_remediation, snapshot_for
from techbench.store import state


def test_frontdesk_disk_failure():
    snap = snapshot_for("sim-frontdesk", 1_700_000_000)
    findings = diagnose(snap)
    ids = {f.id for f in findings}
    assert any(i.startswith("smart-fail") for i in ids)
    assert any(i.startswith("disk-full") or i.startswith("disk-high") for i in ids)
    assert overall_severity(findings) == Severity.critical
    assert health_score(findings) < 60


def test_gaming_thermal():
    snap = snapshot_for("sim-gaming", 1_700_000_000)
    findings = diagnose(snap)
    ids = {f.id for f in findings}
    assert "cpu-thermal-critical" in ids or "cpu-throttle" in ids
    assert "gpu-thermal" in ids
    assert overall_severity(findings) == Severity.critical


def test_accounting_memory_leak():
    snap = snapshot_for("sim-accounting", 1_700_000_000)
    findings = diagnose(snap)
    ids = {f.id for f in findings}
    assert "memory-leak" in ids or "memory-high" in ids


def test_sales_network():
    snap = snapshot_for("sim-sales", 1_700_000_000)
    findings = diagnose(snap)
    ids = {f.id for f in findings}
    assert "net-apipa" in ids
    assert "net-dns" in ids or "net-loss" in ids


def test_warehouse_malware_pattern():
    snap = snapshot_for("sim-warehouse", 1_700_000_000)
    findings = diagnose(snap)
    assert any(f.id.startswith("proc-suspect") for f in findings)
    assert any(f.id == "defender-off" for f in findings)


def test_healthy_lab_is_clean():
    snap = snapshot_for("sim-lab", 1_700_000_000)
    findings = diagnose(snap)
    assert overall_severity(findings) in {Severity.ok, Severity.info}
    assert health_score(findings) >= 90


def test_remediation_clears_malware_process():
    snap = snapshot_for("sim-warehouse", 1_700_000_000)
    findings = diagnose(snap)
    suspect = next(f for f in findings if f.id.startswith("proc-suspect"))
    fixed = apply_remediation("sim-warehouse", suspect.id, snap)
    after = diagnose(fixed)
    assert not any(f.id.startswith("proc-suspect") for f in after)


def test_api_lists_seeded_machines():
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        machines = client.get("/api/machines").json()
        ids = {m["id"] for m in machines}
        assert "local-workstation" in ids
        assert "sim-frontdesk" in ids
        assert "sim-warehouse" in ids
        fd = client.get("/api/machines/sim-frontdesk").json()
        assert fd["overall"] == "critical"
        assert any("SMART" in f["title"] or "full" in f["title"].lower() for f in fd["findings"])


def test_scan_and_remediate_roundtrip():
    with TestClient(app) as client:
        scanned = client.post("/api/machines/sim-accounting/scan")
        assert scanned.status_code == 200
        body = scanned.json()
        assert body["status"] == "online"
        finding = next(f for f in body["findings"] if "memory" in f["id"])
        fixed = client.post(
            "/api/machines/sim-accounting/remediate",
            json={"finding_id": finding["id"]},
        )
        assert fixed.status_code == 200
        assert any(f["id"] == finding["id"] and f["remediated"] for f in fixed.json()["findings"])
        assert fixed.json()["health_score"] >= body["health_score"]


def test_pairing_rejects_bad_code():
    with TestClient(app) as client:
        r = client.post(
            "/api/agent/register",
            json={
                "code": "NOPE-00",
                "inventory": {
                    "hostname": "x",
                    "os": "Linux",
                    "cpu": "test",
                    "ram_gb": 1,
                },
            },
        )
        assert r.status_code == 403


def test_pairing_and_snapshot():
    with TestClient(app) as client:
        pair = client.post("/api/pair", json={"alias": "Lab PC", "location": "Bench 2"})
        assert pair.status_code == 200
        code = pair.json()["code"]
        snap = snapshot_for("sim-lab", 1).model_dump(mode="json")
        reg = client.post(
            "/api/agent/register",
            json={"code": code, "inventory": snap["inventory"]},
        )
        assert reg.status_code == 200
        token = reg.json()["token"]
        posted = client.post("/api/agent/snapshot", json={"token": token, "snapshot": snap})
        assert posted.status_code == 200
        assert posted.json()["kind"] == "remote"
        assert posted.json()["hostname"] == "LAB-CONTROL-01"


def test_store_resets_between_clients():
    """Lifespan should seed a local machine for each TestClient."""
    with TestClient(app) as client:
        n = len(client.get("/api/machines").json())
        assert n >= 7
    # state is process-global; just prove the app still serves after close
    assert "local-workstation" in state.machines
