from __future__ import annotations

from techbench.models import Finding, MachineSnapshot, Severity


def diagnose(snapshot: MachineSnapshot) -> list[Finding]:
    """Run rule-based diagnosis against a machine snapshot.

    Rules are data-driven so local, remote, and simulated machines share
    the same engine. Findings are ordered critical → warning → info.
    """
    findings: list[Finding] = []
    findings.extend(_storage(snapshot))
    findings.extend(_memory(snapshot))
    findings.extend(_thermal(snapshot))
    findings.extend(_network(snapshot))
    findings.extend(_process_anomalies(snapshot))
    findings.extend(_os_hygiene(snapshot))
    findings.extend(_power(snapshot))
    findings.extend(_events(snapshot))

    rank = {Severity.critical: 0, Severity.warning: 1, Severity.info: 2, Severity.ok: 3}
    findings.sort(key=lambda f: (rank[f.severity], -f.confidence, f.title))
    return findings


def overall_severity(findings: list[Finding]) -> Severity:
    active = [f for f in findings if not f.remediated]
    if any(f.severity == Severity.critical for f in active):
        return Severity.critical
    if any(f.severity == Severity.warning for f in active):
        return Severity.warning
    if any(f.severity == Severity.info for f in active):
        return Severity.info
    return Severity.ok


def health_score(findings: list[Finding]) -> int:
    score = 100
    for f in findings:
        if f.remediated:
            continue
        if f.severity == Severity.critical:
            score -= 28
        elif f.severity == Severity.warning:
            score -= 12
        elif f.severity == Severity.info:
            score -= 4
    return max(0, min(100, score))


def _metric(components: list, component_id: str, key: str, default=None):
    for c in components:
        if c.id == component_id:
            return c.metrics.get(key, default)
    return default


def _storage(snapshot: MachineSnapshot) -> list[Finding]:
    out: list[Finding] = []
    for drive in snapshot.smart:
        if drive.pending > 0 or drive.reallocated >= 10 or drive.health.lower() in {
            "failing",
            "predicted failure",
            "pre-fail",
        }:
            out.append(
                Finding(
                    id=f"smart-fail-{drive.device}",
                    severity=Severity.critical,
                    component="storage",
                    title="Drive predictive failure (SMART)",
                    summary=(
                        f"{drive.model} on {drive.device} is reporting SMART pre-fail "
                        f"data. Data loss is likely if the drive is not replaced."
                    ),
                    evidence=[
                        f"Health: {drive.health}",
                        f"Reallocated sectors: {drive.reallocated}",
                        f"Pending sectors: {drive.pending}",
                        f"Power-on hours: {drive.power_on_hours}",
                        f"Avg latency: {drive.latency_ms:.1f} ms",
                    ],
                    recommendations=[
                        "Back up the volume immediately to another disk or network share.",
                        "Replace the failing drive; do not run chkdsk / repair in place as the only fix.",
                        "Clone to a new drive if the machine must stay online.",
                    ],
                    confidence=0.95,
                    playbook_id="backup-and-replace-disk",
                )
            )
        elif drive.reallocated > 0 or drive.latency_ms >= 25:
            out.append(
                Finding(
                    id=f"smart-warn-{drive.device}",
                    severity=Severity.warning,
                    component="storage",
                    title="Storage degradation",
                    summary=f"{drive.model} shows early wear or elevated latency.",
                    evidence=[
                        f"Reallocated sectors: {drive.reallocated}",
                        f"Latency: {drive.latency_ms:.1f} ms",
                        f"Health: {drive.health}",
                    ],
                    recommendations=[
                        "Confirm backups are current.",
                        "Monitor SMART weekly; replace if pending sectors appear.",
                    ],
                    confidence=0.78,
                    playbook_id="monitor-disk",
                )
            )
        if drive.temperature_c is not None and drive.temperature_c >= 70:
            out.append(
                Finding(
                    id=f"smart-hot-{drive.device}",
                    severity=Severity.warning,
                    component="storage",
                    title="Drive running hot",
                    summary=f"{drive.model} is {drive.temperature_c:.0f}°C. Heat accelerates NAND/HDD wear.",
                    evidence=[f"Temperature: {drive.temperature_c:.0f}°C", f"Device: {drive.device}"],
                    recommendations=[
                        "Improve chassis airflow around the drive bay.",
                        "Confirm the drive is not thermally throttling the volume.",
                    ],
                    confidence=0.74,
                    playbook_id="cool-down",
                )
            )

    for vol in snapshot.volumes:
        if vol.used_pct >= 95:
            out.append(
                Finding(
                    id=f"disk-full-{vol.mount}",
                    severity=Severity.critical,
                    component="storage",
                    title=f"Volume {vol.mount} is critically full",
                    summary=f"{vol.mount} is {vol.used_pct:.0f}% used. Updates, paging, and logging can fail.",
                    evidence=[
                        f"Filesystem: {vol.fs}",
                        f"Capacity: {vol.total_gb:.0f} GB",
                        f"Used: {vol.used_pct:.1f}%",
                    ],
                    recommendations=[
                        "Clear temp, recycle bin, and old Windows Update caches.",
                        "Move large media off the system volume.",
                        "Extend the volume or replace with a larger drive.",
                    ],
                    confidence=0.99,
                    playbook_id="free-disk-space",
                )
            )
        elif vol.used_pct >= 90:
            out.append(
                Finding(
                    id=f"disk-high-{vol.mount}",
                    severity=Severity.warning,
                    component="storage",
                    title=f"Volume {vol.mount} is running low",
                    summary=f"{vol.mount} is {vol.used_pct:.0f}% used.",
                    evidence=[f"Used: {vol.used_pct:.1f}% of {vol.total_gb:.0f} GB"],
                    recommendations=["Remove unused installers and old restore points."],
                    confidence=0.9,
                    playbook_id="free-disk-space",
                )
            )
    return out


def _memory(snapshot: MachineSnapshot) -> list[Finding]:
    out: list[Finding] = []
    mem_pct = _metric(snapshot.components, "memory", "used_pct")
    if mem_pct is None and snapshot.telemetry:
        mem_pct = snapshot.telemetry.mem_pct
    if mem_pct is None:
        return out

    hogs = sorted(snapshot.processes, key=lambda p: p.mem_pct, reverse=True)
    top = hogs[0] if hogs else None
    swap_pct = _metric(snapshot.components, "memory", "swap_pct", 0) or 0

    if mem_pct >= 92 and top and top.mem_pct >= 25:
        out.append(
            Finding(
                id="memory-leak",
                severity=Severity.critical,
                component="memory",
                title="Severe memory pressure / likely leak",
                summary=(
                    f"RAM is {mem_pct:.0f}% used and {top.name} (PID {top.pid}) "
                    f"alone holds {top.mem_pct:.0f}%."
                ),
                evidence=[
                    f"Committed memory: {mem_pct:.1f}%",
                    f"Top consumer: {top.name} @ {top.mem_pct:.1f}% ({top.path or 'path unknown'})",
                    f"Swap / pagefile: {swap_pct:.0f}%",
                ],
                recommendations=[
                    f"Restart {top.name} and watch the working set.",
                    "If it climbs again, update or replace the application.",
                    "Add RAM if the workload is legitimate and consistently this high.",
                ],
                confidence=0.88,
                playbook_id="relieve-memory-pressure",
            )
        )
    elif mem_pct >= 88:
        out.append(
            Finding(
                id="memory-high",
                severity=Severity.warning,
                component="memory",
                title="High memory utilization",
                summary=f"RAM is {mem_pct:.0f}% used; the machine may start paging.",
                evidence=[
                    f"Used: {mem_pct:.1f}%",
                    f"Swap: {swap_pct:.0f}%",
                ]
                + (
                    [f"Top process: {top.name} {top.mem_pct:.0f}%"]
                    if top
                    else []
                ),
                recommendations=[
                    "Close unused browsers and background apps.",
                    "Review startup programs.",
                ],
                confidence=0.84,
                playbook_id="relieve-memory-pressure",
            )
        )

    if swap_pct >= 80 and mem_pct >= 80:
        out.append(
            Finding(
                id="swap-thrash",
                severity=Severity.warning,
                component="memory",
                title="Paging / swap thrash",
                summary="The system is heavily using swap while RAM is already tight — UI and disk will feel frozen.",
                evidence=[f"Swap {swap_pct:.0f}%", f"RAM {mem_pct:.0f}%"],
                recommendations=[
                    "End the heaviest processes, then add RAM if this is normal load.",
                ],
                confidence=0.8,
                playbook_id="relieve-memory-pressure",
            )
        )
    return out


def _thermal(snapshot: MachineSnapshot) -> list[Finding]:
    out: list[Finding] = []
    cpu_temp = _metric(snapshot.components, "cpu", "temp_c")
    gpu_temp = _metric(snapshot.components, "gpu", "temp_c")
    fan_rpm = _metric(snapshot.components, "thermal", "fan_rpm")
    throttle = _metric(snapshot.components, "cpu", "throttling")
    clocks = _metric(snapshot.components, "cpu", "clock_mhz")
    base = _metric(snapshot.components, "cpu", "base_mhz")

    if snapshot.telemetry:
        cpu_temp = cpu_temp if cpu_temp is not None else snapshot.telemetry.cpu_temp_c
        gpu_temp = gpu_temp if gpu_temp is not None else snapshot.telemetry.gpu_temp_c
        fan_rpm = fan_rpm if fan_rpm is not None else snapshot.telemetry.fan_rpm

    if cpu_temp is not None and cpu_temp >= 95:
        out.append(
            Finding(
                id="cpu-thermal-critical",
                severity=Severity.critical,
                component="thermal",
                title="CPU thermal shutdown risk",
                summary=f"CPU package is {cpu_temp:.0f}°C. Sustained temps this high throttle clocks and can trip thermal protection.",
                evidence=[
                    f"CPU temp: {cpu_temp:.1f}°C",
                    f"Fan RPM: {fan_rpm if fan_rpm is not None else 'n/a'}",
                    f"Throttling flag: {throttle}",
                    f"Clock: {clocks} MHz / base {base} MHz" if clocks else "Clock: n/a",
                ],
                recommendations=[
                    "Shut down if the chassis is too hot to touch.",
                    "Clear dust from heatsink and fans; reseat the cooler.",
                    "Replace dried thermal paste; verify fan headers in firmware.",
                ],
                confidence=0.93,
                playbook_id="cool-down",
            )
        )
    elif cpu_temp is not None and cpu_temp >= 85:
        out.append(
            Finding(
                id="cpu-thermal-high",
                severity=Severity.warning,
                component="thermal",
                title="CPU running hot",
                summary=f"CPU is {cpu_temp:.0f}°C. Expect boost clocks to drop.",
                evidence=[
                    f"CPU temp: {cpu_temp:.1f}°C",
                    f"Fan RPM: {fan_rpm if fan_rpm is not None else 'n/a'}",
                ],
                recommendations=[
                    "Improve airflow; check that intake filters are not clogged.",
                ],
                confidence=0.85,
                playbook_id="cool-down",
            )
        )

    if throttle or (
        clocks
        and base
        and cpu_temp
        and cpu_temp >= 80
        and clocks < base * 0.85
    ):
        if not any(f.id == "cpu-thermal-critical" for f in out):
            out.append(
                Finding(
                    id="cpu-throttle",
                    severity=Severity.warning,
                    component="cpu",
                    title="Thermal throttling detected",
                    summary="The CPU is cutting clocks under heat. Performance will feel inconsistent.",
                    evidence=[
                        f"Throttling: {throttle}",
                        f"Clock {clocks} vs base {base}",
                        f"Temp {cpu_temp}°C" if cpu_temp is not None else "Temp n/a",
                    ],
                    recommendations=[
                        "Resolve cooling before chasing software slowness.",
                    ],
                    confidence=0.86,
                    playbook_id="cool-down",
                )
            )

    if gpu_temp is not None and gpu_temp >= 90:
        out.append(
            Finding(
                id="gpu-thermal",
                severity=Severity.warning if gpu_temp < 95 else Severity.critical,
                component="gpu",
                title="GPU hotspot",
                summary=f"GPU is {gpu_temp:.0f}°C.",
                evidence=[f"GPU temp: {gpu_temp:.1f}°C"],
                recommendations=[
                    "Re-seat the GPU power cables and clean the card fans.",
                    "Undervolt or cap FPS if this is a small-form-factor build.",
                ],
                confidence=0.82,
                playbook_id="cool-down",
            )
        )

    if fan_rpm is not None and fan_rpm == 0 and cpu_temp is not None and cpu_temp >= 70:
        out.append(
            Finding(
                id="fan-dead",
                severity=Severity.critical,
                component="thermal",
                title="Case / CPU fan not spinning",
                summary="Fan RPM is 0 while the package is already warm. Cooling has failed.",
                evidence=[f"Fan RPM: {fan_rpm}", f"CPU temp: {cpu_temp:.1f}°C"],
                recommendations=[
                    "Power down. Check fan connectors and replace the fan.",
                ],
                confidence=0.9,
                playbook_id="cool-down",
            )
        )
    return out


def _network(snapshot: MachineSnapshot) -> list[Finding]:
    out: list[Finding] = []
    net = snapshot.network or {}
    ip = net.get("ip") or snapshot.inventory.ip
    packet_loss = net.get("packet_loss_pct", 0) or 0
    dns_ok = net.get("dns_ok", True)
    gateway_ms = net.get("gateway_ms")
    ssid = net.get("ssid")
    signal = net.get("wifi_signal_pct")
    apipa = isinstance(ip, str) and ip.startswith("169.254")

    if apipa:
        out.append(
            Finding(
                id="net-apipa",
                severity=Severity.critical,
                component="network",
                title="No DHCP lease (APIPA address)",
                summary=f"Adapter has link-local address {ip}. The PC cannot reach the LAN or internet.",
                evidence=[f"IP: {ip}", f"Gateway RTT: {gateway_ms}"],
                recommendations=[
                    "Renew DHCP (ipconfig /renew or dhclient).",
                    "Check the cable, switch port, and DHCP server.",
                    "If Wi-Fi, forget the SSID and reconnect.",
                ],
                confidence=0.97,
                playbook_id="fix-network",
            )
        )

    if packet_loss >= 8:
        out.append(
            Finding(
                id="net-loss",
                severity=Severity.critical if packet_loss >= 20 else Severity.warning,
                component="network",
                title="High packet loss",
                summary=f"Path is dropping {packet_loss:.0f}% of probes. Sessions will stall and VoIP will chop.",
                evidence=[
                    f"Loss: {packet_loss:.1f}%",
                    f"Gateway: {gateway_ms} ms" if gateway_ms is not None else "Gateway: n/a",
                    f"SSID: {ssid}" if ssid else "Link: wired or unknown",
                ],
                recommendations=[
                    "Swap the patch cable / try a wired backup.",
                    "Move closer to the AP if this is Wi-Fi.",
                    "Check for duplex mismatch on the switch port.",
                ],
                confidence=0.87,
                playbook_id="fix-network",
            )
        )

    if dns_ok is False:
        out.append(
            Finding(
                id="net-dns",
                severity=Severity.warning if not apipa else Severity.critical,
                component="network",
                title="DNS resolution failing",
                summary="Name lookup is failing. Browsing will look like 'no internet' even if ping to an IP works.",
                evidence=[
                    f"dns_ok={dns_ok}",
                    f"Configured DNS: {net.get('dns', 'unknown')}",
                ],
                recommendations=[
                    "Set a known-good resolver (e.g. the site DNS or 1.1.1.1) as a test.",
                    "Flush the client cache after DHCP is healthy.",
                ],
                confidence=0.9,
                playbook_id="fix-network",
            )
        )

    if signal is not None and signal < 35 and not apipa:
        out.append(
            Finding(
                id="wifi-weak",
                severity=Severity.warning,
                component="network",
                title="Weak Wi-Fi signal",
                summary=f"Signal is {signal:.0f}%. Roaming and retries explain the slowness.",
                evidence=[f"SSID: {ssid}", f"Signal: {signal:.0f}%"],
                recommendations=[
                    "Move the workstation or add an AP.",
                    "Prefer 5 GHz if the client supports it.",
                ],
                confidence=0.8,
                playbook_id="fix-network",
            )
        )

    errors = net.get("errors") or net.get("nic_errors") or 0
    try:
        errors = float(errors)
    except (TypeError, ValueError):
        errors = 0
    if errors >= 50:
        out.append(
            Finding(
                id="nic-errors",
                severity=Severity.warning,
                component="network",
                title="NIC error counter climbing",
                summary=f"The adapter has logged {errors:.0f} errors. Cabling or duplex mismatch is likely.",
                evidence=[f"errors={errors:.0f}", f"IP: {ip}"],
                recommendations=[
                    "Swap the patch cable and switch port.",
                    "Force auto-negotiate; avoid a 100/full mismatch.",
                ],
                confidence=0.76,
                playbook_id="fix-network",
            )
        )
    return out


def _process_anomalies(snapshot: MachineSnapshot) -> list[Finding]:
    out: list[Finding] = []
    suspicious = []
    for p in snapshot.processes:
        name = p.name.lower()
        looks_like_lure = any(
            token in name
            for token in ("svch0st", "scvhost", "expl0rer", "winlogonx", "update-svc")
        )
        unsigned_net = p.signed is False and p.net_kbps >= 200
        odd_path = bool(p.path) and any(
            s in p.path.lower()
            for s in ("\\temp\\", "/tmp/", "appdata\\local\\temp", "public\\")
        )
        if looks_like_lure or unsigned_net or (odd_path and p.net_kbps >= 80):
            suspicious.append(p)

    if suspicious:
        p = suspicious[0]
        out.append(
            Finding(
                id=f"proc-suspect-{p.pid}",
                severity=Severity.critical,
                component="os",
                title="Suspicious process / possible malware",
                summary=(
                    f"{p.name} (PID {p.pid}) matches lure-name, unsigned+noisy, "
                    f"or temp-path beaconing patterns."
                ),
                evidence=[
                    f"Name: {p.name}",
                    f"Path: {p.path or 'unknown'}",
                    f"Signed: {p.signed}",
                    f"Network: {p.net_kbps:.0f} kbps",
                    f"CPU {p.cpu_pct:.0f}% / MEM {p.mem_pct:.0f}%",
                ],
                recommendations=[
                    "Isolate the NIC (disable adapter) until reviewed.",
                    "Do not enter credentials on this machine.",
                    "Capture the binary hash and submit to the site AV / SOC.",
                    "Reimage if persistence is confirmed.",
                ],
                confidence=0.83,
                playbook_id="isolate-malware",
            )
        )

    cpu_hogs = [p for p in snapshot.processes if p.cpu_pct >= 85]
    if cpu_hogs and not suspicious:
        p = cpu_hogs[0]
        out.append(
            Finding(
                id=f"cpu-hog-{p.pid}",
                severity=Severity.warning,
                component="cpu",
                title="Process saturating the CPU",
                summary=f"{p.name} is using {p.cpu_pct:.0f}% CPU.",
                evidence=[f"PID {p.pid}", f"{p.path}"],
                recommendations=[
                    "Check whether the workload is expected (encode, compile, scan).",
                    "Restart the process if it is stuck.",
                ],
                confidence=0.75,
                playbook_id="inspect-process",
            )
        )
    return out


def _os_hygiene(snapshot: MachineSnapshot) -> list[Finding]:
    out: list[Finding] = []
    if snapshot.defender_enabled is False:
        out.append(
            Finding(
                id="defender-off",
                severity=Severity.warning,
                component="os",
                title="Endpoint protection is disabled",
                summary="Windows Defender / real-time protection is reported off. Combined with odd processes this is high risk.",
                evidence=["defender_enabled=false"],
                recommendations=[
                    "Re-enable real-time protection from an admin account.",
                    "Check for policies or malware that disabled it.",
                ],
                confidence=0.9,
                playbook_id="isolate-malware",
            )
        )
    if snapshot.startup_count is not None and snapshot.startup_count >= 18:
        out.append(
            Finding(
                id="startup-bloat",
                severity=Severity.info,
                component="os",
                title="Startup program bloat",
                summary=f"{snapshot.startup_count} items launch at logon, which drags boot time.",
                evidence=[f"startup_count={snapshot.startup_count}"],
                recommendations=["Disable unused vendors in Task Manager → Startup."],
                confidence=0.7,
                playbook_id="trim-startup",
            )
        )
    uptime = snapshot.inventory.uptime_hours
    if uptime >= 24 * 21:
        out.append(
            Finding(
                id="uptime-stale",
                severity=Severity.info,
                component="os",
                title="Machine has not been rebooted in weeks",
                summary=f"Uptime is {uptime:.0f} hours. Pending updates and leaked handles are likely.",
                evidence=[f"uptime_hours={uptime:.1f}"],
                recommendations=["Schedule a reboot after saving work."],
                confidence=0.65,
            )
        )

    crashish = [
        e
        for e in snapshot.events
        if e.level.lower() in {"critical", "error"}
        and any(k in e.message.lower() for k in ("bugcheck", "kernel-power", "whea", "unexpected shutdown"))
    ]
    if uptime < 2 and len(crashish) >= 2:
        out.append(
            Finding(
                id="reboot-loop",
                severity=Severity.critical,
                component="os",
                title="Reboot loop / unexpected shutdowns",
                summary=(
                    f"Uptime is only {uptime:.1f} h and the log shows {len(crashish)} "
                    "kernel-power / WHEA / bugcheck events. This box is crashing, not just slow."
                ),
                evidence=[f"{e.ts} [{e.source}] {e.message}" for e in crashish[:4]],
                recommendations=[
                    "Do not chase software until PSU rails, RAM, and SMART are clean.",
                    "Memtest and a known-good PSU swap are the next hardware moves.",
                    "Capture the bugcheck code before the next crash wipes it.",
                ],
                confidence=0.9,
                playbook_id="stabilize-reboot-loop",
            )
        )
    return out


def _power(snapshot: MachineSnapshot) -> list[Finding]:
    out: list[Finding] = []
    rails = _metric(snapshot.components, "psu", "rails") or {}
    watt_pct = _metric(snapshot.components, "psu", "load_pct")
    unstable = False
    if isinstance(rails, dict):
        v12 = rails.get("12v")
        v5 = rails.get("5v")
        if v12 is not None and (v12 < 11.4 or v12 > 12.6):
            unstable = True
        if v5 is not None and (v5 < 4.75 or v5 > 5.25):
            unstable = True
    if unstable:
        out.append(
            Finding(
                id="psu-rails",
                severity=Severity.critical,
                component="psu",
                title="PSU rail voltage out of spec",
                summary="ATX rails are outside ATX spec. Random reboots and USB drops are expected.",
                evidence=[f"Rails: {rails}"],
                recommendations=[
                    "Replace the PSU; do not keep stressing a failing supply.",
                    "Check for overloaded daisy-chained GPU adapters.",
                ],
                confidence=0.8,
                playbook_id="replace-psu",
            )
        )
    if watt_pct is not None and watt_pct >= 92:
        out.append(
            Finding(
                id="psu-overload",
                severity=Severity.warning,
                component="psu",
                title="Power supply near capacity",
                summary=f"PSU load is {watt_pct:.0f}%. Transient GPU spikes may brown out the box.",
                evidence=[f"load_pct={watt_pct}"],
                recommendations=["Fit a higher-wattage 80 PLUS unit, or reduce GPU power target."],
                confidence=0.72,
                playbook_id="replace-psu",
            )
        )
    return out


def _events(snapshot: MachineSnapshot) -> list[Finding]:
    out: list[Finding] = []
    critical_events = [
        e
        for e in snapshot.events
        if e.level.lower() in {"critical", "error"}
        and any(
            k in e.message.lower()
            for k in ("whea", "bugcheck", "disk", "nvlddmkm", "kernel-power", "storsvc")
        )
    ]
    if len(critical_events) >= 2:
        sample = critical_events[0]
        out.append(
            Finding(
                id="event-crash",
                severity=Severity.warning,
                component="os",
                title="Recurring kernel / storage errors in the log",
                summary=f"{len(critical_events)} recent error events point at crashes, WHEA, or disk faults.",
                evidence=[f"{e.ts} [{e.source}] {e.message}" for e in critical_events[:4]],
                recommendations=[
                    "Correlate with SMART and PSU findings before reinstalling Windows.",
                    f"Start with: {sample.message[:120]}",
                ],
                confidence=0.77,
            )
        )
    return out
