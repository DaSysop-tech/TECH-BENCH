"""Markdown service-tag reports for a bay."""

from __future__ import annotations

from datetime import datetime, timezone

from techbench.models import Finding, Machine, Severity

_SEV_ORDER = {Severity.critical: 0, Severity.warning: 1, Severity.info: 2, Severity.ok: 3}


_UNSAFE = str.maketrans({"[": "(", "]": ")", "`": "'", "*": " ", "#": " ", "<": " ", ">": " "})


def _plain(value: object) -> str:
    text = " ".join(str(value).translate(_UNSAFE).split())
    return text[:400]


def _bullet(items: list[str]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [f"- {_plain(item)}" for item in items]


def render_markdown_report(machine: Machine) -> str:
    """Technician-facing markdown. Values are flattened so agent text cannot inject structure."""
    snap = machine.snapshot
    inv = snap.inventory if snap else None
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    open_findings = [f for f in machine.findings if not f.remediated]
    closed = [f for f in machine.findings if f.remediated]
    open_findings.sort(key=lambda f: (_SEV_ORDER[f.severity], f.title))

    lines = [
        f"# TECH-BENCH report — {_plain(machine.alias)}",
        "",
        f"- Generated: {generated}",
        f"- Bay id: `{_plain(machine.id)}`",
        f"- Hostname: `{_plain(machine.hostname)}`",
        f"- Kind: {_plain(machine.kind.value)}",
        f"- Status: {_plain(machine.status.value)}",
        f"- Location: {_plain(machine.location) or 'unspecified'}",
        f"- Owner: {_plain(machine.owner) or '—'}",
        f"- Overall: **{_plain(machine.overall.value)}**",
        f"- Health score: **{machine.health_score}**",
        f"- Open findings: {len(open_findings)} "
        f"(critical {machine.open_critical}, warning {machine.open_warning}, info {machine.open_info})",
        f"- Remediated: {len(closed)}",
        "",
        "## Inventory",
        "",
    ]
    if inv:
        lines.extend(
            [
                f"- OS: {_plain(inv.os)}",
                f"- CPU: {_plain(inv.cpu)}",
                f"- RAM: {inv.ram_gb} GB",
                f"- GPU: {_plain(inv.gpu)}",
                f"- Board: {_plain(inv.motherboard)}",
                f"- Disks: {_plain(', '.join(inv.disks) or '—')}",
                f"- IP: `{_plain(inv.ip) or '—'}`",
                f"- Uptime: {inv.uptime_hours:.1f} h",
                f"- Agent: {_plain(inv.agent_version) or '—'}",
            ]
        )
    else:
        lines.append("- No snapshot on this bay yet.")

    if snap:
        lines.extend(["", "## SMART", ""])
        if snap.smart:
            for disk in snap.smart:
                lines.append(
                    f"- `{_plain(disk.device)}` {_plain(disk.model)} — "
                    f"health {_plain(disk.health)}, realloc {disk.reallocated}, "
                    f"pending {disk.pending}, latency {disk.latency_ms:.1f} ms"
                )
        else:
            lines.append("- No SMART records.")

        tel = snap.telemetry
        lines.extend(["", "## Thermals (last sample)", ""])
        if tel:
            lines.extend(
                [
                    f"- CPU: {tel.cpu_pct:.1f}% / {tel.cpu_temp_c if tel.cpu_temp_c is not None else 'n/a'} °C",
                    f"- Memory: {tel.mem_pct:.1f}%",
                    f"- Disk: {tel.disk_pct:.1f}%",
                    f"- GPU temp: {tel.gpu_temp_c if tel.gpu_temp_c is not None else 'n/a'} °C",
                    f"- Fan: {tel.fan_rpm if tel.fan_rpm is not None else 'n/a'} RPM",
                ]
            )
        else:
            lines.append("- No telemetry sample.")

        lines.extend(["", "## Network", ""])
        if snap.network:
            for key, value in snap.network.items():
                lines.append(f"- {_plain(key)}: {_plain(value)}")
        else:
            lines.append("- No network snapshot.")

    lines.extend(["", "## Open findings", ""])
    if not open_findings:
        lines.append("The bay is clean. No open findings.")
    else:
        for finding in open_findings:
            lines.extend(_finding_block(finding))

    if closed:
        lines.extend(["", "## Remediated", ""])
        for finding in closed:
            lines.append(f"- ~~{_plain(finding.title)}~~ (`{_plain(finding.id)}`)")

    if machine.last_delta:
        d = machine.last_delta
        lines.extend(
            [
                "",
                "## Last scan",
                "",
                f"- Score {d.score_before} → {d.score_after}",
                f"- Appeared: {len(d.appeared)}",
                f"- Cleared: {len(d.cleared)}",
                f"- Still open: {d.still_open}",
            ]
        )

    if machine.notes:
        lines.extend(["", "## Technician notes", ""])
        for note in machine.notes[-12:]:
            lines.append(f"- {_plain(note.body)}")

    lines.extend(
        [
            "",
            "---",
            "",
            "Playbooks on this bench mutate **simulated** snapshots only. "
            "They do not run commands on local or remote PCs.",
            "",
        ]
    )
    return "\n".join(lines)


def _finding_block(finding: Finding) -> list[str]:
    return [
        f"### {_plain(finding.severity.value).upper()} — {_plain(finding.title)}",
        "",
        f"- Id: `{_plain(finding.id)}`",
        f"- Component: `{_plain(finding.component)}`",
        f"- Confidence: {finding.confidence:.0%}",
        "",
        _plain(finding.summary),
        "",
        "**Evidence**",
        *_bullet(finding.evidence),
        "",
        "**Recommendations**",
        *_bullet(finding.recommendations),
        "",
    ]
