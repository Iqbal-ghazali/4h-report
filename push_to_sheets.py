#!/usr/bin/env python3

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

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1Pamx_pVk6j9KmU61l7c21LYC_3hvy_coC4dHoCt6Qxk"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SA_FILE          = os.path.join(SCRIPT_DIR, "service_account.json")
DEFAULT_DATA_DIR = os.path.join(SCRIPT_DIR, "data")

MAIN_SHEET_NAME = "Infra Main"

HEADER_COLOR = {
    "red": 0.60,
    "green": 0.85,
    "blue": 0.60
}

HEADER_TEXT = {
    "red": 0.1,
    "green": 0.1,
    "blue": 0.1
}

INFO_TEXT_COLOR = {
    "red": 0.2,
    "green": 0.2,
    "blue": 0.2
}

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

# ─────────────────────────────────────────────────────────────
# JSON
# ─────────────────────────────────────────────────────────────

def find_latest_json(data_dir: str, prefix: str) -> str:
    pattern = os.path.join(data_dir, f"{prefix}_*.json")
    matches = sorted(glob.glob(pattern))

    if not matches:
        raise FileNotFoundError(
            f"Tidak ada file '{prefix}_*.json' di {data_dir}"
        )

    return matches[-1]


def load_json(path: str, label: str) -> dict:
    if not os.path.isfile(path):
        print(f"[ERROR] File {label} tidak ditemukan: {path}",
              file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    required = {"collected_at", "data"}

    if not required.issubset(data.keys()):
        print(f"[ERROR] Format {label} tidak valid",
              file=sys.stderr)
        sys.exit(1)

    return data


def build_rows(data_list: list) -> list:
    header = [col[0] for col in COLUMNS]
    rows = [header]

    for item in data_list:
        row = []

        for _, key in COLUMNS:
            val = item.get(key, "N/A")

            if val is None:
                val = "N/A"

            row.append(val)

        rows.append(row)

    return rows

# ─────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ─────────────────────────────────────────────────────────────

def build_sheets_service(sa_file: str):
    if not os.path.isfile(sa_file):
        print(f"[ERROR] Service account tidak ditemukan: {sa_file}",
              file=sys.stderr)
        sys.exit(1)

    creds = service_account.Credentials.from_service_account_file(
        sa_file,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

    return build("sheets", "v4", credentials=creds)


def list_existing_sheets(svc, spreadsheet_id: str) -> list:
    meta = svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id
    ).execute()

    return [s["properties"] for s in meta.get("sheets", [])]


def get_sheet_by_name(
    svc,
    spreadsheet_id: str,
    sheet_name: str
):
    sheets = list_existing_sheets(
        svc,
        spreadsheet_id
    )

    for s in sheets:
        if s["title"] == sheet_name:
            return s

    return None

# ─────────────────────────────────────────────────────────────
# SHEET MANAGEMENT
# ─────────────────────────────────────────────────────────────

def create_main_sheet_if_not_exists(
    svc,
    spreadsheet_id: str,
    sheet_name: str
):
    existing = get_sheet_by_name(
        svc,
        spreadsheet_id,
        sheet_name
    )

    if existing:
        return existing["sheetId"]

    resp = svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [{
                "addSheet": {
                    "properties": {
                        "title": sheet_name,
                        "index": 0,
                    }
                }
            }]
        }
    ).execute()

    sheet_id = (
        resp["replies"][0]
        ["addSheet"]
        ["properties"]
        ["sheetId"]
    )

    print(f"  Sheet utama dibuat: '{sheet_name}'")

    return sheet_id


def duplicate_sheet_backup(
    svc,
    spreadsheet_id: str,
    source_sheet_id: int
):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    backup_name = f"Infra Backup {ts}"

    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [{
                "duplicateSheet": {
                    "sourceSheetId": source_sheet_id,
                    "newSheetName": backup_name,
                }
            }]
        }
    ).execute()

    print(f"  Backup dibuat: '{backup_name}'")


def reset_sheet(
    svc,
    spreadsheet_id: str,
    sheet_id: int,
    sheet_name: str
):
    requests = [
        {
            "unmergeCells": {
                "range": {
                    "sheetId": sheet_id
                }
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": sheet_id
                },
                "fields": "*"
            }
        }
    ]

    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()

    svc.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'"
    ).execute()

    print("  Sheet berhasil di-reset")

# ─────────────────────────────────────────────────────────────
# WRITE VALUES
# ─────────────────────────────────────────────────────────────

def write_values(
    svc,
    spreadsheet_id: str,
    sheet_name: str,
    nodes_rows: list,
    instances_rows: list,
    collected_at: str,
):
    sn = sheet_name

    nodes_info_row   = 1
    nodes_header_row = 2
    nodes_data_end   = nodes_header_row + len(nodes_rows) - 1

    gap = 2

    inst_info_row   = nodes_data_end + gap + 1
    inst_header_row = inst_info_row + 1
    inst_data_end   = inst_header_row + len(instances_rows) - 1

    last_updated_row = inst_data_end + 2

    svc.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {
                    "range": f"'{sn}'!A{nodes_info_row}",
                    "values": [[INFO_NODES]]
                },
                {
                    "range": f"'{sn}'!A{nodes_header_row}",
                    "values": nodes_rows
                },
                {
                    "range": f"'{sn}'!A{inst_info_row}",
                    "values": [[INFO_INSTANCES]]
                },
                {
                    "range": f"'{sn}'!A{inst_header_row}",
                    "values": instances_rows
                },
                {
                    "range": f"'{sn}'!A{last_updated_row}",
                    "values": [[f"Last updated: {collected_at}"]]
                },
            ],
        }
    ).execute()

    return {
        "nodes_info_row":   nodes_info_row,
        "nodes_header_row": nodes_header_row,
        "nodes_data_end":   nodes_data_end,
        "inst_info_row":    inst_info_row,
        "inst_header_row":  inst_header_row,
        "inst_data_end":    inst_data_end,
    }

# ─────────────────────────────────────────────────────────────
# FORMATTING
# ─────────────────────────────────────────────────────────────

def apply_formatting(
    svc,
    spreadsheet_id: str,
    sheet_id: int,
    pos: dict,
    num_cols: int = 9
):
    requests_batch = []

    # INFO ROWS

    for info_row in [
        pos["nodes_info_row"],
        pos["inst_info_row"]
    ]:
        r0 = info_row - 1

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
                            "bold": True,
                            "fontSize": 11,
                            "foregroundColor": INFO_TEXT_COLOR,
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": (
                    "userEnteredFormat("
                    "textFormat,"
                    "horizontalAlignment,"
                    "verticalAlignment)"
                ),
            }
        })

    # HEADER ROWS

    for header_row in [
        pos["nodes_header_row"],
        pos["inst_header_row"]
    ]:
        r0 = header_row - 1

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
                            "bold": True,
                            "foregroundColor": HEADER_TEXT,
                        },
                        "backgroundColor": HEADER_COLOR,
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": (
                    "userEnteredFormat("
                    "textFormat,"
                    "backgroundColor,"
                    "horizontalAlignment)"
                ),
            }
        })

    # LEFT ALIGN COLUMN A

    left_align_ranges = [
        {
            "start": pos["nodes_header_row"] + 1,
            "end":   pos["nodes_data_end"] + 1,
        },
        {
            "start": pos["inst_header_row"] + 1,
            "end":   pos["inst_data_end"] + 1,
        }
    ]

    for r in left_align_ranges:
        requests_batch.append({
            "repeatCell": {
                "range": {
                    "sheetId":          sheet_id,
                    "startRowIndex":    r["start"] - 1,
                    "endRowIndex":      r["end"] - 1,
                    "startColumnIndex": 0,
                    "endColumnIndex":   1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "LEFT"
                    }
                },
                "fields": (
                    "userEnteredFormat.horizontalAlignment"
                ),
            }
        })

    # FREEZE TOP ROWS

    requests_batch.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {
                    "frozenRowCount": 2
                },
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # AUTO RESIZE

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

    # FIX WIDTH COLUMN A

    requests_batch.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId":    sheet_id,
                "dimension":  "COLUMNS",
                "startIndex": 0,
                "endIndex":   1,
            },
            "properties": {
                "pixelSize": 45
            },
            "fields": "pixelSize",
        }
    })

    # =========================================================
    # CLEAR ALL BORDERS
    # =========================================================

    requests_batch.append({
        "updateBorders": {
            "range": {
                "sheetId": sheet_id
            },
            "top": {"style": "NONE"},
            "bottom": {"style": "NONE"},
            "left": {"style": "NONE"},
            "right": {"style": "NONE"},
            "innerHorizontal": {"style": "NONE"},
            "innerVertical": {"style": "NONE"},
        }
    })

    # =========================================================
    # TABLE 1 BORDERS
    # =========================================================

    requests_batch.append({
        "updateBorders": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": pos["nodes_header_row"] - 1,
                "endRowIndex": pos["nodes_data_end"],
                "startColumnIndex": 0,
                "endColumnIndex": num_cols,
            },
            "top": {
                "style": "SOLID"
            },
            "bottom": {
                "style": "SOLID"
            },
            "left": {
                "style": "SOLID"
            },
            "right": {
                "style": "SOLID"
            },
            "innerHorizontal": {
                "style": "SOLID"
            },
            "innerVertical": {
                "style": "SOLID"
            }
        }
    })

    # =========================================================
    # TABLE 2 BORDERS
    # =========================================================

    requests_batch.append({
        "updateBorders": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": pos["inst_header_row"] - 1,
                "endRowIndex": pos["inst_data_end"],
                "startColumnIndex": 0,
                "endColumnIndex": num_cols,
            },
            "top": {
                "style": "SOLID"
            },
            "bottom": {
                "style": "SOLID"
            },
            "left": {
                "style": "SOLID"
            },
            "right": {
                "style": "SOLID"
            },
            "innerHorizontal": {
                "style": "SOLID"
            },
            "innerVertical": {
                "style": "SOLID"
            }
        }
    })

    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests_batch},
    ).execute()

    print("  Formatting berhasil diterapkan")

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Push infra JSON ke Google Sheets"
    )

    parser.add_argument(
        "--data-dir",
        "-d",
        default=DEFAULT_DATA_DIR,
    )

    parser.add_argument(
        "--nodes",
        "-n",
        default=None,
    )

    parser.add_argument(
        "--instances",
        "-i",
        default=None,
    )

    parser.add_argument(
        "--sheet-id",
        "-s",
        default=SPREADSHEET_ID,
        dest="sheet_id",
    )

    parser.add_argument(
        "--sa-file",
        default=SA_FILE,
    )

    args = parser.parse_args()

    print("=" * 60)
    print("  Infra JSON → Google Sheets")
    print("=" * 60)

    print("\n[1/5] Membaca JSON ...")

    try:
        nodes_path = (
            args.nodes or
            find_latest_json(args.data_dir, "nodes")
        )

        inst_path = (
            args.instances or
            find_latest_json(args.data_dir, "instances")
        )

    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    nodes_data = load_json(nodes_path, "nodes")
    inst_data  = load_json(inst_path, "instances")

    collected_at = nodes_data.get("collected_at", "unknown")

    nodes_rows = build_rows(nodes_data["data"])
    inst_rows  = build_rows(inst_data["data"])

    print("\n[2/5] Connect Google Sheets ...")

    try:
        svc = build_sheets_service(args.sa_file)

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    print("\n[3/5] Validasi sheet utama ...")

    main_sheet_id = create_main_sheet_if_not_exists(
        svc,
        args.sheet_id,
        MAIN_SHEET_NAME
    )

    print("\n[4/5] Backup + reset sheet ...")

    try:
        duplicate_sheet_backup(
            svc,
            args.sheet_id,
            main_sheet_id
        )

        reset_sheet(
            svc,
            args.sheet_id,
            main_sheet_id,
            MAIN_SHEET_NAME
        )

    except HttpError as e:
        print(f"[ERROR] Gagal backup/reset: {e}",
              file=sys.stderr)
        sys.exit(1)

    print("\n[5/5] Menulis data ...")

    try:
        pos = write_values(
            svc,
            args.sheet_id,
            MAIN_SHEET_NAME,
            nodes_rows,
            inst_rows,
            collected_at,
        )

        apply_formatting(
            svc,
            args.sheet_id,
            main_sheet_id,
            pos,
            num_cols=len(COLUMNS),
        )

    except HttpError as e:
        print(f"[ERROR] Gagal write data: {e}",
              file=sys.stderr)
        sys.exit(1)

    print("\n============================================================")
    print("  ✅ Selesai")
    print(f"  Main Sheet : {MAIN_SHEET_NAME}")
    print("============================================================\n")


if __name__ == "__main__":
    main()