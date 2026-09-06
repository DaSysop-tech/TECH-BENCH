from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Callable

from techbench.models import (
    ComponentHealth,
    EventInfo,
    Inventory,
    MachineSnapshot,
    ProcessInfo,
    Severity,
    SmartInfo,
    TelemetrySample,
    VolumeInfo,
)


@dataclass(frozen=True)
class SimProfile:
    id: str
    alias: str
    location: str
    owner: str
    inventory: Inventory
    builder: Callable[[float], MachineSnapshot]


def _noise(base: float, amp: float, t: float, seed: float) -> float:
    wobble = math.sin(t / 3.5 + seed) * amp + math.sin(t / 1.7 + seed * 1.7) * (amp * 0.35)
    return max(0.0, base + wobble + random.Random(int(t) ^ int(seed * 100)).uniform(-amp * 0.15, amp * 0.15))


def _base_windows_procs() -> list[ProcessInfo]:
    return [
        ProcessInfo(pid=4, name="System", cpu_pct=0.4, mem_pct=0.2, user="NT AUTHORITY\\SYSTEM", signed=True, path=""),
        ProcessInfo(pid=880, name="csrss.exe", cpu_pct=0.2, mem_pct=0.4, user="NT AUTHORITY\\SYSTEM", signed=True, path="C:\\Windows\\System32\\csrss.exe"),
        ProcessInfo(pid=1012, name="winlogon.exe", cpu_pct=0.1, mem_pct=0.3, user="NT AUTHORITY\\SYSTEM", signed=True, path="C:\\Windows\\System32\\winlogon.exe"),
        ProcessInfo(pid=1230, name="explorer.exe", cpu_pct=1.5, mem_pct=4.2, user="USER", signed=True, path="C:\\Windows\\explorer.exe"),
        ProcessInfo(pid=2044, name="MsMpEng.exe", cpu_pct=2.0, mem_pct=3.1, user="SYSTEM", signed=True, path="C:\\Program Files\\Windows Defender\\MsMpEng.exe"),
        ProcessInfo(pid=3110, name="SearchHost.exe", cpu_pct=0.8, mem_pct=2.4, user="USER", signed=True, path="C:\\Windows\\SystemApps\\SearchHost.exe"),
    ]


def frontdesk(t: float) -> MachineSnapshot:
    """Failing NVMe + nearly full system volume. Classic 'PC is freezing' ticket."""
    latency = _noise(48, 10, t, 1.2)
    used = _noise(96.4, 0.4, t, 2.1)
    cpu = _noise(22, 8, t, 0.4)
    mem = _noise(61, 4, t, 0.9)
    inv = Inventory(
        hostname="FRONTDESK-PC",
        os="Windows 11 Pro 23H2",
        cpu="Intel Core i5-10400",
        ram_gb=8,
        gpu="Intel UHD Graphics 630",
        motherboard="Dell OptiPlex 3080",
        disks=["Kingston NV2 256GB NVMe"],
        uptime_hours=312,
        ip="10.20.8.41",
    )
    return MachineSnapshot(
        inventory=inv,
        components=[
            ComponentHealth(id="cpu", label="CPU", status=Severity.ok, metrics={"usage_pct": cpu, "temp_c": 58, "clock_mhz": 2900, "base_mhz": 2900, "cores": 6}),
            ComponentHealth(id="memory", label="Memory", status=Severity.ok, metrics={"used_pct": mem, "total_gb": 8, "swap_pct": 22}),
            ComponentHealth(id="storage", label="Storage", status=Severity.critical, metrics={"used_pct": used, "latency_ms": latency}),
            ComponentHealth(id="gpu", label="GPU", status=Severity.ok, metrics={"temp_c": 47, "model": inv.gpu}),
            ComponentHealth(id="network", label="Network", status=Severity.ok, metrics={"ip": inv.ip}),
            ComponentHealth(id="psu", label="Power", status=Severity.ok, metrics={"load_pct": 34, "rails": {"12v": 12.05, "5v": 5.02}}),
            ComponentHealth(id="thermal", label="Thermal", status=Severity.ok, metrics={"fan_rpm": 1240}),
            ComponentHealth(id="os", label="OS", status=Severity.warning, metrics={"uptime_hours": 312}),
        ],
        processes=_base_windows_procs()
        + [
            ProcessInfo(pid=4402, name="Teams.exe", cpu_pct=6, mem_pct=11, user="frontdesk", signed=True, path="C:\\Program Files\\Teams\\Teams.exe"),
            ProcessInfo(pid=5510, name="chrome.exe", cpu_pct=8, mem_pct=18, user="frontdesk", signed=True, path="C:\\Program Files\\Google\\Chrome\\chrome.exe"),
        ],
        volumes=[
            VolumeInfo(mount="C:", fs="NTFS", total_gb=238, used_pct=used, model="Kingston NV2 256GB"),
        ],
        network={"ip": inv.ip, "dns_ok": True, "packet_loss_pct": 0.2, "gateway_ms": 2, "dns": "10.20.0.10"},
        events=[
            EventInfo(ts="2026-09-05 18:11:02", source="disk", level="error", message="The driver detected a controller error on \\Device\\Harddisk0\\DR0."),
            EventInfo(ts="2026-09-05 18:11:04", source="ntfs", level="error", message="Delayed Write Failed on volume C:"),
            EventInfo(ts="2026-09-04 09:02:11", source="Kernel-Power", level="error", message="The system has rebooted without cleanly shutting down first."),
        ],
        smart=[
            SmartInfo(
                device="nvme0n1",
                model="Kingston NV2 256GB",
                health="Predicted Failure",
                temperature_c=71,
                reallocated=38,
                pending=14,
                power_on_hours=14880,
                latency_ms=latency,
            )
        ],
        telemetry=TelemetrySample(ts=t, cpu_pct=cpu, mem_pct=mem, disk_pct=used, net_kbps=_noise(180, 40, t, 3), cpu_temp_c=58, gpu_temp_c=47, fan_rpm=1240),
        defender_enabled=True,
        startup_count=21,
    )


def gaming_rig(t: float) -> MachineSnapshot:
    """Thermal throttle + GPU hotspot. 'FPS tanks after 20 minutes'."""
    cpu_temp = _noise(97, 2.2, t, 4.4)
    gpu_temp = _noise(93, 2.0, t, 5.1)
    fan = int(_noise(420, 80, t, 1.8))  # anemic fan
    clock = 3100 if cpu_temp < 90 else _noise(2400, 180, t, 2)
    cpu = _noise(88, 6, t, 0.7)
    mem = _noise(72, 3, t, 1.1)
    inv = Inventory(
        hostname="GAMING-RIG-X",
        os="Windows 11 Home 24H2",
        cpu="AMD Ryzen 7 5800X",
        ram_gb=32,
        gpu="NVIDIA GeForce RTX 3070",
        motherboard="MSI B550 Tomahawk",
        disks=["Samsung 980 1TB NVMe"],
        uptime_hours=18,
        ip="192.168.4.88",
    )
    return MachineSnapshot(
        inventory=inv,
        components=[
            ComponentHealth(
                id="cpu",
                label="CPU",
                status=Severity.critical,
                metrics={"usage_pct": cpu, "temp_c": cpu_temp, "clock_mhz": clock, "base_mhz": 3800, "throttling": True, "cores": 8},
            ),
            ComponentHealth(id="memory", label="Memory", status=Severity.ok, metrics={"used_pct": mem, "total_gb": 32, "swap_pct": 4}),
            ComponentHealth(id="storage", label="Storage", status=Severity.ok, metrics={"used_pct": 54}),
            ComponentHealth(id="gpu", label="GPU", status=Severity.critical, metrics={"temp_c": gpu_temp, "model": inv.gpu, "hotspot_c": gpu_temp + 8}),
            ComponentHealth(id="network", label="Network", status=Severity.ok, metrics={"ip": inv.ip}),
            ComponentHealth(id="psu", label="Power", status=Severity.warning, metrics={"load_pct": 94, "rails": {"12v": 11.72, "5v": 5.01}}),
            ComponentHealth(id="thermal", label="Thermal", status=Severity.critical, metrics={"fan_rpm": fan, "cpu_temp_c": cpu_temp}),
            ComponentHealth(id="os", label="OS", status=Severity.ok, metrics={}),
        ],
        processes=_base_windows_procs()
        + [
            ProcessInfo(pid=9001, name="cyberpunk2077.exe", cpu_pct=62, mem_pct=28, user="kai", signed=True, path="D:\\Games\\cyberpunk2077.exe"),
            ProcessInfo(pid=9008, name="Discord.exe", cpu_pct=3, mem_pct=6, user="kai", signed=True, path="C:\\Users\\kai\\AppData\\Local\\Discord\\Discord.exe"),
            ProcessInfo(pid=9100, name="NVIDIA Overlay", cpu_pct=2, mem_pct=1.5, user="kai", signed=True, path="C:\\Program Files\\NVIDIA Corporation\\NVIDIA Overlay.exe"),
        ],
        volumes=[VolumeInfo(mount="C:", fs="NTFS", total_gb=931, used_pct=54, model="Samsung 980 1TB")],
        network={"ip": inv.ip, "dns_ok": True, "packet_loss_pct": 0, "gateway_ms": 3, "dns": "1.1.1.1"},
        events=[
            EventInfo(ts="2026-09-06 01:14:22", source="nvlddmkm", level="error", message="NVIDIA driver nvlddmkm timeout (TDR)."),
            EventInfo(ts="2026-09-06 01:14:23", source="WHEA-Logger", level="error", message="A corrected hardware error has occurred. Thermal margin exceeded."),
        ],
        smart=[
            SmartInfo(device="nvme0n1", model="Samsung 980 1TB", health="passed", temperature_c=49, reallocated=0, pending=0, power_on_hours=4200, latency_ms=0.8)
        ],
        telemetry=TelemetrySample(ts=t, cpu_pct=cpu, mem_pct=mem, disk_pct=54, net_kbps=_noise(900, 200, t, 8), cpu_temp_c=cpu_temp, gpu_temp_c=gpu_temp, fan_rpm=fan),
        defender_enabled=True,
        startup_count=9,
    )


def accounting(t: float) -> MachineSnapshot:
    """Chrome leak + swap thrash. 'Excel takes forever'."""
    mem = _noise(94, 1.5, t, 6)
    swap = _noise(86, 3, t, 6.2)
    cpu = _noise(48, 10, t, 2)
    inv = Inventory(
        hostname="NB-ACCOUNTING-04",
        os="Windows 10 Pro 22H2",
        cpu="Intel Core i5-8250U",
        ram_gb=8,
        gpu="Intel UHD 620",
        motherboard="Lenovo ThinkPad T480",
        disks=["WDC SATA SSD 256GB"],
        uptime_hours=186,
        ip="10.20.12.19",
    )
    chrome_mem = min(62.0, mem - 32)
    return MachineSnapshot(
        inventory=inv,
        components=[
            ComponentHealth(id="cpu", label="CPU", status=Severity.warning, metrics={"usage_pct": cpu, "temp_c": 74, "clock_mhz": 1600, "base_mhz": 1600}),
            ComponentHealth(id="memory", label="Memory", status=Severity.critical, metrics={"used_pct": mem, "total_gb": 8, "swap_pct": swap}),
            ComponentHealth(id="storage", label="Storage", status=Severity.warning, metrics={"used_pct": 91}),
            ComponentHealth(id="gpu", label="GPU", status=Severity.ok, metrics={"temp_c": 62}),
            ComponentHealth(id="network", label="Network", status=Severity.ok, metrics={"ip": inv.ip}),
            ComponentHealth(id="psu", label="Power", status=Severity.ok, metrics={"load_pct": 40, "rails": {"12v": 12.1, "5v": 5.04}}),
            ComponentHealth(id="thermal", label="Thermal", status=Severity.ok, metrics={"fan_rpm": 2800}),
            ComponentHealth(id="os", label="OS", status=Severity.info, metrics={}),
        ],
        processes=_base_windows_procs()
        + [
            ProcessInfo(pid=6120, name="chrome.exe", cpu_pct=22, mem_pct=chrome_mem, user="finance", signed=True, path="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"),
            ProcessInfo(pid=6122, name="chrome.exe", cpu_pct=8, mem_pct=9, user="finance", signed=True, path="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"),
            ProcessInfo(pid=7001, name="EXCEL.EXE", cpu_pct=11, mem_pct=14, user="finance", signed=True, path="C:\\Program Files\\Microsoft Office\\EXCEL.EXE"),
            ProcessInfo(pid=7088, name="Outlook.exe", cpu_pct=4, mem_pct=8, user="finance", signed=True, path="C:\\Program Files\\Microsoft Office\\Outlook.exe"),
        ],
        volumes=[VolumeInfo(mount="C:", fs="NTFS", total_gb=238, used_pct=91, model="WDC SATA SSD 256GB")],
        network={"ip": inv.ip, "dns_ok": True, "packet_loss_pct": 0, "gateway_ms": 4, "dns": "10.20.0.10"},
        events=[
            EventInfo(ts="2026-09-06 08:41:00", source="Resource-Exhaustion-Detector", level="warning", message="Windows successfully diagnosed a low virtual memory condition."),
        ],
        smart=[
            SmartInfo(device="sda", model="WDC SATA SSD 256GB", health="passed", temperature_c=41, reallocated=2, pending=0, power_on_hours=20110, latency_ms=6)
        ],
        telemetry=TelemetrySample(ts=t, cpu_pct=cpu, mem_pct=mem, disk_pct=91, net_kbps=_noise(120, 30, t, 1), cpu_temp_c=74, gpu_temp_c=62, fan_rpm=2800),
        defender_enabled=True,
        startup_count=16,
    )


def sales_laptop(t: float) -> MachineSnapshot:
    """Flaky Wi-Fi, DNS fails, high loss. 'VPN keeps dropping'."""
    loss = _noise(18, 6, t, 9)
    signal = _noise(22, 8, t, 9.5)
    cpu = _noise(18, 5, t, 0.3)
    mem = _noise(58, 4, t, 0.4)
    inv = Inventory(
        hostname="SALES-LAPTOP-12",
        os="Windows 11 Pro 23H2",
        cpu="Intel Core i7-1165G7",
        ram_gb=16,
        gpu="Intel Iris Xe",
        motherboard="HP EliteBook 840 G8",
        disks=["Kioxia 512GB NVMe"],
        uptime_hours=54,
        ip="169.254.21.6",
    )
    return MachineSnapshot(
        inventory=inv,
        components=[
            ComponentHealth(id="cpu", label="CPU", status=Severity.ok, metrics={"usage_pct": cpu, "temp_c": 61}),
            ComponentHealth(id="memory", label="Memory", status=Severity.ok, metrics={"used_pct": mem, "total_gb": 16, "swap_pct": 8}),
            ComponentHealth(id="storage", label="Storage", status=Severity.ok, metrics={"used_pct": 62}),
            ComponentHealth(id="gpu", label="GPU", status=Severity.ok, metrics={"temp_c": 55}),
            ComponentHealth(id="network", label="Network", status=Severity.critical, metrics={"ip": inv.ip, "ssid": "HQ-Guest", "wifi_signal_pct": signal}),
            ComponentHealth(id="psu", label="Power", status=Severity.ok, metrics={"load_pct": 22, "rails": {"12v": 12.0, "5v": 5.0}}),
            ComponentHealth(id="thermal", label="Thermal", status=Severity.ok, metrics={"fan_rpm": 1600}),
            ComponentHealth(id="os", label="OS", status=Severity.ok, metrics={}),
        ],
        processes=_base_windows_procs()
        + [
            ProcessInfo(pid=3200, name="Cisco AnyConnect", cpu_pct=1.2, mem_pct=2, user="morgan", signed=True, path="C:\\Program Files\\Cisco\\Cisco AnyConnect Secure Mobility Client\\vpnui.exe"),
            ProcessInfo(pid=3340, name="outlook.exe", cpu_pct=3, mem_pct=9, user="morgan", signed=True, path="C:\\Program Files\\Microsoft Office\\outlook.exe"),
        ],
        volumes=[VolumeInfo(mount="C:", fs="NTFS", total_gb=477, used_pct=62, model="Kioxia 512GB NVMe")],
        network={
            "ip": inv.ip,
            "dns_ok": False,
            "packet_loss_pct": loss,
            "gateway_ms": 900,
            "dns": "192.168.0.1",
            "ssid": "HQ-Guest",
            "wifi_signal_pct": signal,
        },
        events=[
            EventInfo(ts="2026-09-06 07:55:12", source="Netwtw10", level="error", message="Intel Wi-Fi adapter reset (status C00000A3)."),
            EventInfo(ts="2026-09-06 07:56:01", source="Dhcp-Client", level="error", message="Your computer was not able to renew its address from the network."),
        ],
        smart=[
            SmartInfo(device="nvme0n1", model="Kioxia 512GB", health="passed", temperature_c=39, reallocated=0, pending=0, power_on_hours=2100, latency_ms=0.4)
        ],
        telemetry=TelemetrySample(ts=t, cpu_pct=cpu, mem_pct=mem, disk_pct=62, net_kbps=_noise(12, 8, t, 2), cpu_temp_c=61, gpu_temp_c=55, fan_rpm=1600),
        defender_enabled=True,
        startup_count=11,
    )


def warehouse(t: float) -> MachineSnapshot:
    """Unsigned lure-named process + defender off. Isolate immediately."""
    cpu = _noise(41, 10, t, 11)
    mem = _noise(55, 4, t, 11.2)
    net = _noise(2400, 400, t, 12)
    inv = Inventory(
        hostname="WAREHOUSE-WS",
        os="Windows 10 Pro 21H2",
        cpu="Intel Core i3-8100",
        ram_gb=8,
        gpu="Intel UHD 630",
        motherboard="HP ProDesk 400 G5",
        disks=["Seagate Barracuda 1TB HDD"],
        uptime_hours=640,
        ip="10.44.2.77",
    )
    return MachineSnapshot(
        inventory=inv,
        components=[
            ComponentHealth(id="cpu", label="CPU", status=Severity.warning, metrics={"usage_pct": cpu, "temp_c": 68}),
            ComponentHealth(id="memory", label="Memory", status=Severity.ok, metrics={"used_pct": mem, "total_gb": 8, "swap_pct": 12}),
            ComponentHealth(id="storage", label="Storage", status=Severity.ok, metrics={"used_pct": 48}),
            ComponentHealth(id="gpu", label="GPU", status=Severity.ok, metrics={"temp_c": 50}),
            ComponentHealth(id="network", label="Network", status=Severity.warning, metrics={"ip": inv.ip, "outbound_kbps": net}),
            ComponentHealth(id="psu", label="Power", status=Severity.ok, metrics={"load_pct": 30, "rails": {"12v": 12.04, "5v": 4.99}}),
            ComponentHealth(id="thermal", label="Thermal", status=Severity.ok, metrics={"fan_rpm": 900}),
            ComponentHealth(id="os", label="OS", status=Severity.critical, metrics={"defender_enabled": False}),
        ],
        processes=_base_windows_procs()
        + [
            ProcessInfo(
                pid=8844,
                name="svch0st.exe",
                cpu_pct=27,
                mem_pct=9,
                user="SYSTEM",
                signed=False,
                path="C:\\Users\\Public\\update-svc\\svch0st.exe",
                net_kbps=net,
            ),
            ProcessInfo(pid=1188, name="spoolsv.exe", cpu_pct=0.4, mem_pct=0.8, user="SYSTEM", signed=True, path="C:\\Windows\\System32\\spoolsv.exe"),
        ],
        volumes=[VolumeInfo(mount="C:", fs="NTFS", total_gb=931, used_pct=48, model="Seagate Barracuda 1TB")],
        network={"ip": inv.ip, "dns_ok": True, "packet_loss_pct": 0, "gateway_ms": 1, "dns": "10.44.0.2", "outbound_kbps": net},
        events=[
            EventInfo(ts="2026-09-06 03:12:44", source="Microsoft-Windows-Windows Defender", level="error", message="Real-time protection has been disabled."),
            EventInfo(ts="2026-09-06 03:13:01", source="Service Control Manager", level="error", message="The Windows Defender Antivirus Service terminated unexpectedly."),
        ],
        smart=[
            SmartInfo(device="sda", model="Seagate Barracuda 1TB", health="passed", temperature_c=36, reallocated=0, pending=0, power_on_hours=22000, latency_ms=8)
        ],
        telemetry=TelemetrySample(ts=t, cpu_pct=cpu, mem_pct=mem, disk_pct=48, net_kbps=net, cpu_temp_c=68, gpu_temp_c=50, fan_rpm=900),
        defender_enabled=False,
        startup_count=14,
    )


def lab_healthy(t: float) -> MachineSnapshot:
    cpu = _noise(8, 3, t, 0.2)
    mem = _noise(34, 3, t, 0.5)
    inv = Inventory(
        hostname="LAB-CONTROL-01",
        os="Windows 11 Pro 24H2",
        cpu="Intel Core i7-13700",
        ram_gb=32,
        gpu="Intel UHD 770",
        motherboard="Lenovo ThinkCentre M90q",
        disks=["Samsung 990 Pro 1TB"],
        uptime_hours=40,
        ip="10.20.1.10",
    )
    return MachineSnapshot(
        inventory=inv,
        components=[
            ComponentHealth(id="cpu", label="CPU", status=Severity.ok, metrics={"usage_pct": cpu, "temp_c": 48, "clock_mhz": 3500, "base_mhz": 2100}),
            ComponentHealth(id="memory", label="Memory", status=Severity.ok, metrics={"used_pct": mem, "total_gb": 32, "swap_pct": 1}),
            ComponentHealth(id="storage", label="Storage", status=Severity.ok, metrics={"used_pct": 41}),
            ComponentHealth(id="gpu", label="GPU", status=Severity.ok, metrics={"temp_c": 44}),
            ComponentHealth(id="network", label="Network", status=Severity.ok, metrics={"ip": inv.ip}),
            ComponentHealth(id="psu", label="Power", status=Severity.ok, metrics={"load_pct": 18, "rails": {"12v": 12.08, "5v": 5.03}}),
            ComponentHealth(id="thermal", label="Thermal", status=Severity.ok, metrics={"fan_rpm": 1100}),
            ComponentHealth(id="os", label="OS", status=Severity.ok, metrics={}),
        ],
        processes=_base_windows_procs()
        + [
            ProcessInfo(pid=5001, name="Code.exe", cpu_pct=2, mem_pct=6, user="lab", signed=True, path="C:\\Users\\lab\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"),
        ],
        volumes=[VolumeInfo(mount="C:", fs="NTFS", total_gb=931, used_pct=41, model="Samsung 990 Pro 1TB")],
        network={"ip": inv.ip, "dns_ok": True, "packet_loss_pct": 0, "gateway_ms": 1, "dns": "10.20.0.10"},
        events=[],
        smart=[
            SmartInfo(device="nvme0n1", model="Samsung 990 Pro 1TB", health="passed", temperature_c=37, reallocated=0, pending=0, power_on_hours=900, latency_ms=0.2)
        ],
        telemetry=TelemetrySample(ts=t, cpu_pct=cpu, mem_pct=mem, disk_pct=41, net_kbps=_noise(40, 10, t, 1), cpu_temp_c=48, gpu_temp_c=44, fan_rpm=1100),
        defender_enabled=True,
        startup_count=6,
    )


FLEET: list[SimProfile] = [
    SimProfile(
        id="sim-frontdesk",
        alias="Front desk kiosk",
        location="Lobby",
        owner="Facilities",
        inventory=frontdesk(0).inventory,
        builder=frontdesk,
    ),
    SimProfile(
        id="sim-gaming",
        alias="Gaming rig (ticket #4412)",
        location="Remote / home office",
        owner="Kai R.",
        inventory=gaming_rig(0).inventory,
        builder=gaming_rig,
    ),
    SimProfile(
        id="sim-accounting",
        alias="Accounting notebook",
        location="Finance bay",
        owner="Priya S.",
        inventory=accounting(0).inventory,
        builder=accounting,
    ),
    SimProfile(
        id="sim-sales",
        alias="Sales laptop",
        location="On the road",
        owner="Morgan L.",
        inventory=sales_laptop(0).inventory,
        builder=sales_laptop,
    ),
    SimProfile(
        id="sim-warehouse",
        alias="Warehouse workstation",
        location="Building C / dock",
        owner="Ops",
        inventory=warehouse(0).inventory,
        builder=warehouse,
    ),
    SimProfile(
        id="sim-lab",
        alias="Lab control (healthy)",
        location="IT lab",
        owner="Helpdesk",
        inventory=lab_healthy(0).inventory,
        builder=lab_healthy,
    ),
]


def snapshot_for(profile_id: str, t: float | None = None) -> MachineSnapshot:
    t = t if t is not None else time.time()
    for p in FLEET:
        if p.id == profile_id:
            return p.builder(t)
    raise KeyError(profile_id)


def apply_remediation(profile_id: str, finding_id: str, snapshot: MachineSnapshot) -> MachineSnapshot:
    """Mutate a snapshot as if the technician applied a known-good playbook."""
    snap = snapshot.model_copy(deep=True)
    fid = finding_id.lower()

    if "smart" in fid or "disk-full" in fid or "disk-high" in fid:
        for vol in snap.volumes:
            vol.used_pct = min(vol.used_pct, 64)
        for s in snap.smart:
            if "smart" in fid:
                s.health = "replaced / pending clone"
                s.pending = 0
                s.reallocated = 0
                s.latency_ms = 0.6
        for c in snap.components:
            if c.id == "storage":
                c.status = Severity.ok
                c.metrics["used_pct"] = min(float(c.metrics.get("used_pct", 64)), 64)

    if "memory" in fid or "swap" in fid:
        for c in snap.components:
            if c.id == "memory":
                c.metrics["used_pct"] = 48
                c.metrics["swap_pct"] = 6
                c.status = Severity.ok
        for p in snap.processes:
            if p.name.lower().startswith("chrome"):
                p.mem_pct = min(p.mem_pct, 8)
        if snap.telemetry:
            snap.telemetry.mem_pct = 48

    if "thermal" in fid or "throttle" in fid or "gpu-thermal" in fid or "fan" in fid:
        for c in snap.components:
            if c.id in {"cpu", "gpu", "thermal"}:
                c.status = Severity.ok
                if "temp_c" in c.metrics:
                    c.metrics["temp_c"] = min(float(c.metrics["temp_c"]), 62)
                if "throttling" in c.metrics:
                    c.metrics["throttling"] = False
                if "fan_rpm" in c.metrics:
                    c.metrics["fan_rpm"] = max(int(c.metrics.get("fan_rpm") or 0), 1600)
        if snap.telemetry:
            snap.telemetry.cpu_temp_c = 62
            snap.telemetry.gpu_temp_c = 58
            snap.telemetry.fan_rpm = 1800

    if "net-" in fid or "wifi" in fid:
        snap.inventory.ip = "10.20.30.77"
        snap.network.update(
            {"ip": "10.20.30.77", "dns_ok": True, "packet_loss_pct": 0.1, "gateway_ms": 3, "wifi_signal_pct": 78}
        )
        for c in snap.components:
            if c.id == "network":
                c.status = Severity.ok
                c.metrics["ip"] = "10.20.30.77"

    if "proc-suspect" in fid or "defender" in fid:
        snap.processes = [p for p in snap.processes if "svch0st" not in p.name.lower()]
        snap.defender_enabled = True
        for c in snap.components:
            if c.id == "os":
                c.status = Severity.ok
        if snap.telemetry:
            snap.telemetry.net_kbps = min(snap.telemetry.net_kbps, 80)

    if "psu" in fid:
        for c in snap.components:
            if c.id == "psu":
                c.status = Severity.ok
                c.metrics["load_pct"] = 40
                c.metrics["rails"] = {"12v": 12.05, "5v": 5.02}

    if "startup" in fid:
        snap.startup_count = 6

    return snap
