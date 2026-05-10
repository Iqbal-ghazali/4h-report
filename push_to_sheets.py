#!/usr/bin/env python3
"""
push_to_sheets.py
=================
Baca nodes_<timestamp>.json + instances_<timestamp>.json terbaru
dari subdirektori 'data/' relatif terhadap lokasi script,
lalu tulis ke Google Sheets sebagai SHEET BARU.

Path selalu dihitung dari lokasi file script ini (__file__),
sehingga script bisa dijalankan dari direktori mana pun.

Nama sheet baru otomatis pakai timestamp, contoh: "Infra 2025-05-11 14:30"

Layout sheet:
  Baris 1  : "Controller & Compute Nodes"  (bold, CENTER, merge A:I)
  Baris 2  : Header kolom  (bold, hijau muda A:I, CENTER)
  Baris 3+ : Data nodes
  (2 baris kosong)
  Baris X  : "OpenStack VM Instances"  (bold, CENTER, merge A:I)
  Baris X+1: Header kolom  (bold, hijau muda A:I, CENTER)
  Baris X+2+: Data instances
  (1 baris kosong)
  Baris Y  : Last updated: <timestamp>

Usage:
  python3 push_to_sheets.py
  python3 push_to_sheets.py --data-dir /custom/data/path
  python3 push_to_sheets.py --nodes data/nodes_20250511_143000.json \\
                            --instances data/instances_20250511_143000.json
  python3 push_to_sheets.py --sheet-id YOUR_SPREADSHEET_ID
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ─── KONFIGURASI ──────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1Pamx_pVk6j9KmU61l7c21LYC_3hvy_coC4dHoCt6Qxk"

# Semua path dihitung relatif terhadap lokasi script ini,
# bukan dari CWD — agar script bisa dijalankan dari mana pun.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SA_FILE          = os.path.join(SCRIPT_DIR, "service_account.json")
DEFAULT_DATA_DIR = os.path.join(SCRIPT_DIR, "data")

# Warna header: hijau muda
HEADER_COLOR = {"red": 0.60, "green": 0.85, "blue": 0.60}
HEADER_TEXT  = {"red": 0.1,  "green": 0.1,  "blue": 0.1}

# Baris info section
INFO_TEXT_COLOR = {"red": 0.2, "green": 0.2, "blue": 0.2}

# Kolom yang ditampilkan
COLUMNS = [
    ("NO",             "no"),
    ("HOSTNAME",       "hostname"),
    ("IP",             "ip"),
    ("OS VERSION",     "os_version"),
    ("KERNEL VERSION", "kernel_version"),
    ("UPTIME",         "uptime"),
    ("vCPU",           "vcpu"),
    ("RAM (Total)",    "ram_total"),
    ("DISK (Total)",   "disk_total"),
]

INFO_NODES     = "Controller & Compute Nodes"
INFO_INSTANCES = "OpenStack VM Instances"

# ─── LOAD JSON ────────────────────────────────────────────────────────────────

def find_latest_json(data_dir: str, prefix: str) -> str:
    """
    Cari file JSON terbaru di data_dir dengan prefix tertentu.
    Sort by nama file (ascending) → elemen terakhir = paling baru.
    Raise FileNotFoundError kalau tidak ada file yang match.
    """
    pattern = os.path.join(data_dir, f"{prefix}_*.json")
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"Tidak ada file '{prefix}_*.json' di {data_dir}.\n"
            f"  Jalankan collect_infra.py terlebih dahulu.")
    return matches[-1]


def load_json(path: str, label: str) -> dict:
    """Load dan validasi satu file JSON."""
    if not os.path.isfile(path):
        print(f"[ERROR] File {label} tidak ditemukan: {path}", file=sys.stderr)
        print("  Jalankan collect_infra.py terlebih dahulu.", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    required = {"collected_at", "data"}
    if not required.issubset(data.keys()):
        print(f"[ERROR] Format {label} tidak valid. "
              f"Keys yang dibutuhkan: {required}", file=sys.stderr)
        sys.exit(1)

    return data

# ─── DATA PREPARATION ─────────────────────────────────────────────────────────

def build_rows(data_list: list) -> list:
    """Ubah list dict JSON jadi list of rows (header + data)."""
    header = [col[0] for col in COLUMNS]
    rows   = [header]
    for item in data_list:
        row = []
        for _, key in COLUMNS:
            val = item.get(key, "N/A")
            if val is None:
                val = "N/A"
            row.append(val)
        rows.append(row)
    return rows

# ─── GOOGLE SHEETS SERVICE ────────────────────────────────────────────────────

def build_sheets_service(sa_file: str):
    if not os.path.isfile(sa_file):
        print(f"[ERROR] Service account file tidak ditemukan: {sa_file}",
              file=sys.stderr)
        sys.exit(1)
    creds = service_account.Credentials.from_service_account_file(
        sa_file,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)

# ─── SHEET MANAGEMENT ─────────────────────────────────────────────────────────

def list_existing_sheets(svc, spreadsheet_id: str) -> list:
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return [s["properties"] for s in meta.get("sheets", [])]


def create_new_sheet(svc, spreadsheet_id: str, sheet_title: str):
    """
    Buat tab/sheet baru. Return (sheetId, final_title).
    Auto-suffix jika nama sudah ada.
    """
    existing        = list_existing_sheets(svc, spreadsheet_id)
    existing_titles = {s["title"] for s in existing}

    final_title = sheet_title
    counter     = 2
    while final_title in existing_titles:
        final_title = f"{sheet_title} ({counter})"
        counter    += 1

    resp = svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [{
                "addSheet": {
                    "properties": {
                        "title": final_title,
                        "index": 0,  # selalu paling kiri
                    }
                }
            }]
        }
    ).execute()

    new_sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
    print(f"  Sheet baru dibuat: '{final_title}' (sheetId={new_sheet_id})")
    return new_sheet_id, final_title

# ─── WRITE DATA ───────────────────────────────────────────────────────────────

def write_values(svc, spreadsheet_id: str, sheet_name: str,
                 nodes_rows: list, instances_rows: list,
                 collected_at: str) -> dict:
    """
    Tulis semua nilai ke sheet sekaligus via batchUpdate.
    Return dict posisi baris untuk keperluan formatting.
    """
    sn = sheet_name

    nodes_info_row   = 1
    nodes_header_row = 2
    nodes_data_end   = nodes_header_row + len(nodes_rows) - 1

    gap             = 2
    inst_info_row   = nodes_data_end + gap + 1
    inst_header_row = inst_info_row + 1
    inst_data_end   = inst_header_row + len(instances_rows) - 1

    last_updated_row = inst_data_end + 2

    svc.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {"range": f"'{sn}'!A{nodes_info_row}",   "values": [[INFO_NODES]]},
                {"range": f"'{sn}'!A{nodes_header_row}", "values": nodes_rows},
                {"range": f"'{sn}'!A{inst_info_row}",    "values": [[INFO_INSTANCES]]},
                {"range": f"'{sn}'!A{inst_header_row}",  "values": instances_rows},
                {"range": f"'{sn}'!A{last_updated_row}", "values": [[f"Last updated: {collected_at}"]]},
            ],
        }
    ).execute()

    print(f"  Nodes    : baris {nodes_header_row}–{nodes_data_end} "
          f"({len(nodes_rows) - 1} node)")
    print(f"  Instances: baris {inst_header_row}–{inst_data_end} "
          f"({len(instances_rows) - 1} instance)")

    return {
        "nodes_info_row":   nodes_info_row,
        "nodes_header_row": nodes_header_row,
        "nodes_data_end":   nodes_data_end,
        "inst_info_row":    inst_info_row,
        "inst_header_row":  inst_header_row,
        "inst_data_end":    inst_data_end,
    }

# ─── FORMATTING ───────────────────────────────────────────────────────────────

def apply_formatting(svc, spreadsheet_id: str, sheet_id: int,
                     pos: dict, num_cols: int = 9):
    """
    Formatting:
      - Baris INFO   : bold, CENTER, merge A:I, no background
      - Baris HEADER : bold, hijau muda HANYA kolom A:I, CENTER
      - Freeze 2 baris atas
      - Auto-resize kolom A:I
    """
    requests_batch = []

    # ── Baris INFO: merge A:I + bold + CENTER ──
    for info_row in [pos["nodes_info_row"], pos["inst_info_row"]]:
        r0 = info_row - 1  # 0-indexed

        requests_batch.append({
            "mergeCells": {
                "range": {
                    "sheetId":          sheet_id,
                    "startRowIndex":    r0,
                    "endRowIndex":      r0 + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex":   num_cols,
                },
                "mergeType": "MERGE_ALL",
            }
        })

        requests_batch.append({
            "repeatCell": {
                "range": {
                    "sheetId":          sheet_id,
                    "startRowIndex":    r0,
                    "endRowIndex":      r0 + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex":   num_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "bold":            True,
                            "fontSize":        11,
                            "foregroundColor": INFO_TEXT_COLOR,
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment":   "MIDDLE",
                    }
                },
                "fields": ("userEnteredFormat("
                           "textFormat,horizontalAlignment,verticalAlignment)"),
            }
        })

    # ── Baris HEADER: bold, hijau muda HANYA kolom A:I, CENTER ──
    for header_row in [pos["nodes_header_row"], pos["inst_header_row"]]:
        r0 = header_row - 1

        requests_batch.append({
            "repeatCell": {
                "range": {
                    "sheetId":          sheet_id,
                    "startRowIndex":    r0,
                    "endRowIndex":      r0 + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex":   num_cols,   # ← hanya sampai kolom I
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "bold":            True,
                            "foregroundColor": HEADER_TEXT,
                        },
                        "backgroundColor":     HEADER_COLOR,
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": ("userEnteredFormat("
                           "textFormat,backgroundColor,horizontalAlignment)"),
            }
        })

    # ── Freeze 2 baris atas ──
    requests_batch.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId":        sheet_id,
                "gridProperties": {"frozenRowCount": 2},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # ── Auto-resize kolom A:I ──
    requests_batch.append({
        "autoResizeDimensions": {
            "dimensions": {
                "sheetId":    sheet_id,
                "dimension":  "COLUMNS",
                "startIndex": 0,
                "endIndex":   num_cols,
            }
        }
    })

    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests_batch},
    ).execute()
    print("  Formatting berhasil diterapkan.")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Push infra JSON ke Google Sheets (sheet baru tiap run)")
    parser.add_argument(
        "--data-dir", "-d",
        default=DEFAULT_DATA_DIR,
        help="Direktori tempat mencari nodes_*.json & instances_*.json "
             "(default: <lokasi script>/data/)",
    )
    parser.add_argument(
        "--nodes", "-n",
        default=None,
        help="Path nodes_*.json spesifik (opsional, override auto-detect)",
    )
    parser.add_argument(
        "--instances", "-i",
        default=None,
        help="Path instances_*.json spesifik (opsional, override auto-detect)",
    )
    parser.add_argument(
        "--sheet-id", "-s",
        default=SPREADSHEET_ID,
        dest="sheet_id",
        help="Spreadsheet ID target",
    )
    parser.add_argument(
        "--sa-file",
        default=SA_FILE,
        help="Path service account JSON",
    )
    args = parser.parse_args()

    if not args.sheet_id:
        print("[ERROR] SPREADSHEET_ID belum diisi.", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("  Infra JSON  →  Google Sheets (sheet baru)")
    print("=" * 60)

    # ── 1. Load JSON ──
    print(f"\n[1/4] Membaca data JSON …")
    try:
        nodes_path = args.nodes or find_latest_json(args.data_dir, "nodes")
        inst_path  = args.instances or find_latest_json(args.data_dir, "instances")
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    nodes_data = load_json(nodes_path, "nodes")
    inst_data  = load_json(inst_path,  "instances")

    collected_at = nodes_data.get("collected_at", "unknown")
    print(f"  Nodes     : {nodes_data.get('count', '?')} entries  [{nodes_path}]")
    print(f"  Instances : {inst_data.get('count', '?')} entries  [{inst_path}]")
    print(f"  Data dari : {collected_at}")

    if not nodes_data["data"] and not inst_data["data"]:
        print("[WARN] Kedua file kosong, tidak ada yang ditulis.", file=sys.stderr)
        sys.exit(0)

    try:
        dt          = datetime.fromisoformat(collected_at)
        sheet_title = dt.strftime("Infra %Y-%m-%d %H:%M")
    except ValueError:
        sheet_title = f"Infra {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    nodes_rows = build_rows(nodes_data["data"])
    inst_rows  = build_rows(inst_data["data"])

    # ── 2. Connect ──
    print(f"\n[2/4] Menghubungkan ke Google Sheets …")
    try:
        svc = build_sheets_service(args.sa_file)
        print(f"  Spreadsheet ID : {args.sheet_id}")
    except Exception as e:
        print(f"[ERROR] Gagal build service: {e}", file=sys.stderr)
        sys.exit(1)

    # ── 3. Buat sheet baru ──
    print(f"\n[3/4] Membuat sheet baru: '{sheet_title}' …")
    try:
        new_sheet_id, final_title = create_new_sheet(
            svc, args.sheet_id, sheet_title)
    except HttpError as e:
        print(f"[ERROR] Google Sheets API error: {e}", file=sys.stderr)
        sys.exit(1)

    # ── 4. Tulis data + format ──
    print(f"\n[4/4] Menulis data dan formatting …")
    try:
        pos = write_values(
            svc, args.sheet_id, final_title,
            nodes_rows, inst_rows, collected_at,
        )
        apply_formatting(
            svc, args.sheet_id, new_sheet_id, pos,
            num_cols=len(COLUMNS),
        )
    except HttpError as e:
        print(f"[ERROR] Gagal menulis ke Sheets: {e}", file=sys.stderr)
        sys.exit(1)

    sheet_url = (
        f"https://docs.google.com/spreadsheets/d/{args.sheet_id}"
        f"#gid={new_sheet_id}"
    )
    print(f"\n{'=' * 60}")
    print(f"  ✅ Selesai! Sheet baru: '{final_title}'")
    print(f"  → {sheet_url}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()