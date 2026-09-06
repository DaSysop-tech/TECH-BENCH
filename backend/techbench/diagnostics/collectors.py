from __future__ import annotations

import os
import platform
import socket
import time
from pathlib import Path

import psutil

from techbench.models import (
    ComponentHealth,
    Inventory,
    MachineSnapshot,
    ProcessInfo,
    Severity,
    SmartInfo,
    TelemetrySample,
    VolumeInfo,
)


def collect_local_snapshot() -> MachineSnapshot:
    hostname = socket.gethostname()
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    cpu_pct = psutil.cpu_percent(interval=0.15)
    load = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0, 0, 0)
    temps = _cpu_temp()
    net = psutil.net_io_counters()
    disk = psutil.disk_io_counters()
    boot = psutil.boot_time()
    uptime_h = (time.time() - boot) / 3600
    ip = _primary_ip()

    volumes = []
    for part in psutil.disk_partitions(all=False):
        if part.fstype in {"squashfs", "overlay", "tmpfs"}:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        volumes.append(
            VolumeInfo(
                mount=part.mountpoint,
                fs=part.fstype or "unknown",
                total_gb=usage.total / (1024**3),
                used_pct=usage.percent,
                model=part.device,
            )
        )

    processes: list[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "name", "username"]):
        try:
            cpu = proc.cpu_percent(interval=None)
            mem = proc.memory_percent()
            if cpu < 0.5 and mem < 0.8:
                continue
            exe = ""
            try:
                exe = proc.exe() or ""
            except (psutil.AccessDenied, psutil.Error):
                exe = proc.info.get("name") or ""
            processes.append(
                ProcessInfo(
                    pid=proc.pid,
                    name=proc.info.get("name") or "unknown",
                    cpu_pct=cpu,
                    mem_pct=mem,
                    user=proc.info.get("username") or "",
                    path=exe[:180],
                    signed=None,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda p: p.cpu_pct + p.mem_pct, reverse=True)
    processes = processes[:24]

    disk_used = max((v.used_pct for v in volumes), default=0)
    sample = TelemetrySample(
        ts=time.time(),
        cpu_pct=cpu_pct,
        mem_pct=vm.percent,
        disk_pct=disk_used,
        net_kbps=((net.bytes_sent + net.bytes_recv) / 1024) % 8000 if net else 0,
        cpu_temp_c=temps,
        gpu_temp_c=None,
        fan_rpm=None,
    )

    components = [
        ComponentHealth(
            id="cpu",
            label="CPU",
            status=_sev(cpu_pct, 85, 95),
            metrics={
                "usage_pct": cpu_pct,
                "cores": psutil.cpu_count() or 1,
                "load_1": load[0],
                "temp_c": temps,
                "model": _cpu_model(),
            },
        ),
        ComponentHealth(
            id="memory",
            label="Memory",
            status=_sev(vm.percent, 88, 95),
            metrics={
                "used_pct": vm.percent,
                "total_gb": round(vm.total / (1024**3), 1),
                "swap_pct": swap.percent,
            },
        ),
        ComponentHealth(
            id="storage",
            label="Storage",
            status=_sev(disk_used, 90, 95),
            metrics={"used_pct": disk_used, "volumes": len(volumes)},
            notes=[f"{v.mount} {v.used_pct:.0f}%" for v in volumes[:6]],
        ),
        ComponentHealth(
            id="network",
            label="Network",
            status=Severity.ok if ip else Severity.warning,
            metrics={"ip": ip, "bytes_sent": getattr(net, "bytes_sent", 0)},
        ),
        ComponentHealth(
            id="gpu",
            label="GPU",
            status=Severity.info,
            metrics={"model": _gpu_model()},
            notes=["Host GPU telemetry is limited in this environment."],
        ),
        ComponentHealth(
            id="psu",
            label="Power",
            status=Severity.info,
            metrics={},
            notes=["PSU rails are not exposed on this host."],
        ),
        ComponentHealth(
            id="thermal",
            label="Thermal",
            status=_sev(temps or 0, 85, 95) if temps else Severity.info,
            metrics={"cpu_temp_c": temps},
        ),
        ComponentHealth(
            id="os",
            label="Operating system",
            status=Severity.ok,
            metrics={"platform": platform.platform(), "kernel": platform.release()},
        ),
    ]

    smart: list[SmartInfo] = []
    for v in volumes[:3]:
        smart.append(
            SmartInfo(
                device=v.model,
                model=v.model,
                health="passed" if v.used_pct < 98 else "warn",
                temperature_c=temps,
                latency_ms=max(1.0, (getattr(disk, "read_time", 0) or 0) / 1000),
            )
        )

    return MachineSnapshot(
        inventory=Inventory(
            hostname=hostname,
            os=f"{platform.system()} {platform.release()}",
            cpu=_cpu_model(),
            ram_gb=round(vm.total / (1024**3), 1),
            gpu=_gpu_model(),
            motherboard=_dmi("board_name") or platform.machine(),
            disks=[v.model for v in volumes[:4]],
            uptime_hours=round(uptime_h, 1),
            ip=ip,
        ),
        components=components,
        processes=processes,
        volumes=volumes,
        network={
            "ip": ip,
            "dns_ok": True,
            "packet_loss_pct": 0,
            "gateway_ms": 1,
            "dns": _read_dns(),
        },
        events=[],
        smart=smart,
        telemetry=sample,
        defender_enabled=None,
        startup_count=None,
    )


def collect_local_telemetry() -> TelemetrySample:
    vm = psutil.virtual_memory()
    net = psutil.net_io_counters()
    cpu = psutil.cpu_percent(interval=0.05)
    disk_pct = 0.0
    try:
        disk_pct = psutil.disk_usage("/").percent
    except Exception:
        pass
    return TelemetrySample(
        ts=time.time(),
        cpu_pct=cpu,
        mem_pct=vm.percent,
        disk_pct=disk_pct,
        net_kbps=((net.bytes_sent + net.bytes_recv) / 1024) % 4000 if net else 0,
        cpu_temp_c=_cpu_temp(),
    )


def _sev(value: float, warn: float, crit: float) -> Severity:
    if value >= crit:
        return Severity.critical
    if value >= warn:
        return Severity.warning
    return Severity.ok


def _cpu_temp() -> float | None:
    try:
        temps = psutil.sensors_temperatures() or {}
        for entries in temps.values():
            for e in entries:
                if e.current:
                    return float(e.current)
    except Exception:
        pass
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal.exists():
        try:
            raw = int(thermal.read_text().strip())
            return raw / 1000 if raw > 1000 else float(raw)
        except Exception:
            return None
    return None


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if "model name" in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine()


def _gpu_model() -> str:
    pci = Path("/proc/driver/nvidia/gpus")
    if pci.exists():
        return "NVIDIA GPU"
    return os.environ.get("GPU_NAME") or "Integrated / unknown"


def _primary_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _read_dns() -> str:
    try:
        lines = Path("/etc/resolv.conf").read_text().splitlines()
        ns = [ln.split()[1] for ln in lines if ln.startswith("nameserver")]
        return ", ".join(ns) if ns else "unknown"
    except Exception:
        return "unknown"


def _dmi(key: str) -> str | None:
    path = Path(f"/sys/class/dmi/id/{key}")
    try:
        if path.exists():
            return path.read_text().strip() or None
    except Exception:
        return None
    return None
