#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import requests

# ─── KONFIGURASI ──────────────────────────────────────────────────────────────

PROM_NODES     = "http://10.18.251.13:9090"   # controller + compute
PROM_INSTANCES = "http://10.18.224.200:9090"  # VM instances

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_DIR = os.path.join(SCRIPT_DIR, "data")

REQUEST_TIMEOUT = 10  # detik per request ke Prometheus

# ─── PROMETHEUS HELPERS ───────────────────────────────────────────────────────

def prom_query(base_url: str, promql: str) -> list:
    """
    Jalankan satu PromQL query, return list of result dicts.
    Return [] kalau gagal (connection error, timeout, dsb).
    """
    try:
        resp = requests.get(
            f"{base_url}/api/v1/query",
            params={"query": promql},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            return data["data"]["result"]
        print(f"  [WARN] Prometheus returned status={data.get('status')} "
              f"| query: {promql[:60]}…", file=sys.stderr)
    except requests.exceptions.ConnectionError:
        print(f"  [WARN] Tidak bisa connect ke {base_url}", file=sys.stderr)
    except requests.exceptions.Timeout:
        print(f"  [WARN] Timeout saat query ke {base_url} | {promql[:60]}…",
              file=sys.stderr)
    except Exception as exc:
        print(f"  [WARN] {base_url} | {promql[:60]}… → {exc}", file=sys.stderr)
    return []


def prom_scalar(base_url: str, promql: str, ip: str) -> str:
    """
    Ambil satu nilai skalar untuk IP tertentu.
    Return "N/A" kalau tidak ditemukan.
    """
    for result in prom_query(base_url, promql):
        if ip in result["metric"].get("instance", ""):
            return result["value"][1]
    return "N/A"


def is_prometheus_up(base_url: str) -> bool:
    """Cek apakah Prometheus bisa diakses."""
    try:
        resp = requests.get(f"{base_url}/-/healthy", timeout=REQUEST_TIMEOUT)
        return resp.status_code == 200
    except Exception:
        return False

# ─── FORMAT HELPERS ───────────────────────────────────────────────────────────

def fmt_uptime(seconds_str: str) -> str:
    """Convert detik float ke format '5d 3h 12m'."""
    if seconds_str == "N/A":
        return "N/A"
    try:
        td = timedelta(seconds=float(seconds_str))
        total_hours, rem = divmod(td.seconds, 3600)
        minutes, _       = divmod(rem, 60)
        return f"{td.days}d {total_hours}h {minutes}m"
    except (ValueError, TypeError):
        return seconds_str


def fmt_gb(bytes_str: str) -> str:
    """Convert bytes ke format '128.0 GB'."""
    if bytes_str == "N/A":
        return "N/A"
    try:
        return f"{float(bytes_str) / 1024 ** 3:.1f} GB"
    except (ValueError, TypeError):
        return bytes_str


def fmt_vcpu(count_str: str) -> str:
    """Bulatkan vCPU ke integer string."""
    if count_str == "N/A":
        return "N/A"
    try:
        return str(int(float(count_str)))
    except (ValueError, TypeError):
        return count_str

# ─── DATA COLLECTION ──────────────────────────────────────────────────────────

def get_all_instances(base_url: str) -> list:
    """
    Ambil list semua instance yang terdaftar di Prometheus
    berdasarkan metrik node_uname_info.
    """
    results = prom_query(base_url, "node_uname_info")
    seen, out = set(), []
    for r in results:
        inst = r["metric"].get("instance", "")
        if inst and inst not in seen:
            seen.add(inst)
            out.append(inst)
    return sorted(out)


def get_node_info(base_url: str, instance: str) -> dict:
    """
    Kumpulkan semua data untuk satu instance/node dari Prometheus.
    """
    ip = instance.split(":")[0]
    info = {
        "hostname":       ip,
        "os_version":     "N/A",
        "kernel_version": "N/A",
        "uptime":         "N/A",
        "vcpu":           "N/A",
        "ram_total":      "N/A",
        "disk_total":     "N/A",
        "error":          None,
    }

    try:
        # Hostname + kernel dari node_uname_info
        uname_results = prom_query(
            base_url, f'node_uname_info{{instance=~".*{ip}.*"}}')
        for r in uname_results:
            m = r["metric"]
            info["hostname"]       = m.get("nodename", info["hostname"])
            info["kernel_version"] = m.get("release",  info["kernel_version"])
            info["os_version"]     = m.get("version",  info["os_version"])

        # Pretty OS name dari node_os_info (node_exporter >= 1.6)
        os_results = prom_query(
            base_url, f'node_os_info{{instance=~".*{ip}.*"}}')
        for r in os_results:
            pretty = r["metric"].get("pretty_name", "")
            if pretty:
                info["os_version"] = pretty
                break

        # Uptime
        boot_raw = prom_scalar(
            base_url,
            f'(time() - node_boot_time_seconds{{instance=~".*{ip}.*"}})',
            ip,
        )
        info["uptime"] = fmt_uptime(boot_raw)

        # vCPU
        vcpu_raw = prom_scalar(
            base_url,
            f'count without(cpu,mode)'
            f'(node_cpu_seconds_total{{instance=~".*{ip}.*",mode="idle"}})',
            ip,
        )
        info["vcpu"] = fmt_vcpu(vcpu_raw)

        # RAM total
        ram_raw = prom_scalar(
            base_url,
            f'node_memory_MemTotal_bytes{{instance=~".*{ip}.*"}}',
            ip,
        )
        info["ram_total"] = fmt_gb(ram_raw)

        # Disk total (partisi fisik, kecualikan virtual fs)
        disk_raw = "N/A"
        disk_results = prom_query(
            base_url,
            f'sum by (instance)(node_filesystem_size_bytes{{'
            f'instance=~".*{ip}.*",'
            f'fstype!~"tmpfs|overlay|squashfs|devtmpfs|ramfs"}})',
        )
        for r in disk_results:
            if ip in r["metric"].get("instance", ""):
                disk_raw = r["value"][1]
                break

        # Fallback: root partition saja
        if disk_raw == "N/A":
            fallback = prom_query(
                base_url,
                f'node_filesystem_size_bytes{{'
                f'instance=~".*{ip}.*",'
                f'mountpoint="/",fstype!="tmpfs"}}',
            )
            for r in fallback:
                if ip in r["metric"].get("instance", ""):
                    disk_raw = r["value"][1]
                    break

        info["disk_total"] = fmt_gb(disk_raw)

    except Exception as exc:
        info["error"] = str(exc)
        print(f"  [ERROR] Gagal collect data untuk {instance}: {exc}",
              file=sys.stderr)

    return info


def collect_section(base_url: str, label: str) -> dict:
    """
    Kumpulkan data semua node/instance dari satu Prometheus.
    """
    print(f"\n[{label}] Prometheus: {base_url}")

    section = {
        "source":       base_url,
        "label":        label,
        "reachable":    False,
        "collected_at": datetime.now().isoformat(timespec="seconds"),
        "data":         [],
    }

    if not is_prometheus_up(base_url):
        print(f"  [WARN] Prometheus di {base_url} tidak bisa diakses. "
              f"Section ini akan kosong.", file=sys.stderr)
        return section

    section["reachable"] = True
    instances = get_all_instances(base_url)
    print(f"  Ditemukan {len(instances)} instance")

    if not instances:
        print(f"  [WARN] Tidak ada instance yang ditemukan di {base_url}",
              file=sys.stderr)
        return section

    rows = []
    for idx, inst in enumerate(instances, 1):
        print(f"  [{idx:2}/{len(instances)}] Collecting {inst} …")
        info = get_node_info(base_url, inst)
        ip   = inst.split(":")[0]
        row  = {
            "no":             idx,
            "hostname":       info["hostname"],
            "ip":             ip,
            "os_version":     info["os_version"],
            "kernel_version": info["kernel_version"],
            "uptime":         info["uptime"],
            "vcpu":           info["vcpu"],
            "ram_total":      info["ram_total"],
            "disk_total":     info["disk_total"],
        }
        if info.get("error"):
            row["_error"] = info["error"]
        rows.append(row)

    section["data"] = rows
    return section

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Collect OpenStack infra data dari Prometheus → JSON")
    parser.add_argument(
        "--output-dir", "-o",
        default=DEFAULT_DATA_DIR,
        help=f"Direktori output JSON (default: <lokasi script>/data/)",
    )
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)

    # Buat direktori output kalau belum ada (tidak looping, hanya sekali cek)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
        print(f"  [INFO] Direktori dibuat: {output_dir}")

    print("=" * 60)
    print("  OpenStack Infra Collector  →  JSON")
    print("=" * 60)

    collected_at = datetime.now().isoformat(timespec="seconds")

    nodes_section     = collect_section(PROM_NODES,     "Controllers & Computes")
    instances_section = collect_section(PROM_INSTANCES, "VM Instances")

    nodes_output = {
        "collected_at": collected_at,
        "source":       nodes_section["source"],
        "label":        nodes_section["label"],
        "reachable":    nodes_section["reachable"],
        "count":        len(nodes_section["data"]),
        "data":         nodes_section["data"],
    }

    instances_output = {
        "collected_at": collected_at,
        "source":       instances_section["source"],
        "label":        instances_section["label"],
        "reachable":    instances_section["reachable"],
        "count":        len(instances_section["data"]),
        "data":         instances_section["data"],
    }

    ts_str         = datetime.now().strftime("%Y%m%d_%H%M%S")
    nodes_path     = os.path.join(output_dir, f"nodes_{ts_str}.json")
    instances_path = os.path.join(output_dir, f"instances_{ts_str}.json")

    with open(nodes_path, "w", encoding="utf-8") as f:
        json.dump(nodes_output, f, indent=2, ensure_ascii=False)

    with open(instances_path, "w", encoding="utf-8") as f:
        json.dump(instances_output, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"  Output:")
    print(f"    Nodes     → {nodes_path} ({nodes_output['count']} entries)")
    print(f"    Instances → {instances_path} ({instances_output['count']} entries)")
    print(f"  Timestamp   : {collected_at}")
    print(f"{'=' * 60}\n")

    if not nodes_section["reachable"] or not instances_section["reachable"]:
        sys.exit(1)


if __name__ == "__main__":
    main()