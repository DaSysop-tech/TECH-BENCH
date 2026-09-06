from __future__ import annotations

from techbench.diagnostics.engine import diagnose, health_score, overall_severity
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


def test_api_lists_seeded_machines(client):
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


def test_scan_and_remediate_roundtrip(client):
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


def test_pairing_rejects_bad_code(client):
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


def test_pairing_and_snapshot(client):
    pair = client.post("/api/pair", json={"alias": "Lab PC", "location": "Bench 2"})
    assert pair.status_code == 200
    code = pair.json()["code"]
    cmd = pair.json()["agent_command"]
    assert code in cmd
    assert "BENCH_HOST" not in cmd
    assert "techbench_agent.py" in cmd
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


def test_store_resets_between_clients(client):
    n = len(client.get("/api/machines").json())
    assert n >= 7
    assert "local-workstation" in state.machines


def test_machine_list_omits_snapshot_and_counts_findings(client):
    machines = client.get("/api/machines").json()
    assert machines
    for m in machines:
        assert "snapshot" not in m
        assert "open_critical" in m
        assert "open_warning" in m
        assert "open_info" in m
    frontdesk = next(m for m in machines if m["id"] == "sim-frontdesk")
    assert frontdesk["open_critical"] >= 1
    warehouse = next(m for m in machines if m["id"] == "sim-warehouse")
    assert warehouse["open_critical"] + warehouse["open_warning"] + warehouse["open_info"] >= 1
    lab = next(m for m in machines if m["id"] == "sim-lab")
    assert lab["open_critical"] == 0


def test_markdown_report_flattens_agent_text():
    from techbench.models import Finding, Inventory, Machine, MachineKind, MachineSnapshot, Severity
    from techbench.report import render_markdown_report

    snap = MachineSnapshot(
        inventory=Inventory(hostname="x", os="Linux", cpu="t", ram_gb=8),
    )
    m = Machine(
        id="remote-x",
        hostname="x",
        alias="Box",
        os="Linux",
        kind=MachineKind.remote,
        snapshot=snap,
        findings=[
            Finding(
                id="t",
                severity=Severity.warning,
                component="os",
                title="](http://evil)",
                summary="line1\nline2 `code`",
                evidence=["a\nb"],
                recommendations=["do\nstuff"],
            )
        ],
        open_warning=1,
    )
    body = render_markdown_report(m)
    assert "](http://evil)" not in body
    assert "line1 line2 'code'" in body
    r = client.get("/api/machines/sim-frontdesk/report")
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert "techbench-sim-frontdesk.md" in r.headers.get("content-disposition", "")
    body = r.text
    assert "TECH-BENCH report" in body
    assert "sim-frontdesk" in body
    assert "Open findings" in body
    missing = client.get("/api/machines/does-not-exist/report")
    assert missing.status_code == 404
