#!/usr/bin/env python3

import os
import json
import copy
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

# =========================================================
# CONFIG
# =========================================================

SPREADSHEET_ID = "1Pamx_pVk6j9KmU61l7c21LYC_3hvy_coC4dHoCt6Qxk"
MAIN_SHEET_NAME = "infra main"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(SCRIPT_DIR, "data")

SERVICE_ACCOUNT_FILE = os.path.join(
    SCRIPT_DIR,
    "service_account.json"
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets"
]

# =========================================================
# GOOGLE AUTH
# =========================================================

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
)

service = build(
    "sheets",
    "v4",
    credentials=creds
)

# =========================================================
# LOAD JSON
# =========================================================

controller_file = os.path.join(
    DATA_DIR,
    "controllers.json"
)

vm_file = os.path.join(
    DATA_DIR,
    "vms.json"
)

with open(controller_file, "r") as f:
    controllers = json.load(f)

with open(vm_file, "r") as f:
    vms = json.load(f)

# =========================================================
# GET SPREADSHEET
# =========================================================

spreadsheet = service.spreadsheets().get(
    spreadsheetId=SPREADSHEET_ID
).execute()

sheets = spreadsheet.get("sheets", [])

main_sheet = None

for sheet in sheets:
    if sheet["properties"]["title"] == MAIN_SHEET_NAME:
        main_sheet = sheet
        break

if not main_sheet:
    raise Exception(f"Sheet '{MAIN_SHEET_NAME}' tidak ditemukan")

sheet_id = main_sheet["properties"]["sheetId"]

# =========================================================
# DUPLICATE CURRENT SHEET
# =========================================================

timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

backup_sheet_name = f"backup {timestamp}"

duplicate_request = {
    "requests": [
        {
            "duplicateSheet": {
                "sourceSheetId": sheet_id,
                "newSheetName": backup_sheet_name
            }
        }
    ]
}

service.spreadsheets().batchUpdate(
    spreadsheetId=SPREADSHEET_ID,
    body=duplicate_request
).execute()

print("=" * 60)
print(f"Backup sheet created: {backup_sheet_name}")
print("=" * 60)

# =========================================================
# CLEAR MAIN SHEET
# =========================================================

service.spreadsheets().values().clear(
    spreadsheetId=SPREADSHEET_ID,
    range=f"{MAIN_SHEET_NAME}!A:Z"
).execute()

# =========================================================
# BUILD DATA
# =========================================================

values = []

# =========================================================
# TITLE
# =========================================================

values.append([
    "INFRASTRUCTURE REPORT"
])

values.append([
    f"Last Updated: {timestamp}"
])

values.append([])

# =========================================================
# SECTION 1
# =========================================================

values.append([
    "Controller & Compute Nodes"
])

values.append([
    "NO",
    "HOSTNAME",
    "IP",
    "OS VERSION",
    "KERNEL VERSION",
    "UPTIME",
    "vCPU",
    "RAM (Total)",
    "DISK (Total)"
])

for idx, item in enumerate(controllers, start=1):
    values.append([
        idx,
        item.get("hostname", ""),
        item.get("ip", ""),
        item.get("os_version", ""),
        item.get("kernel_version", ""),
        item.get("uptime", ""),
        item.get("vcpu", ""),
        item.get("ram_total", ""),
        item.get("disk_total", ""),
    ])

values.append([])
values.append([])

# =========================================================
# SECTION 2
# =========================================================

values.append([
    "OpenStack VM Instances"
])

values.append([
    "NO",
    "HOSTNAME",
    "IP",
    "OS VERSION",
    "KERNEL VERSION",
    "UPTIME",
    "vCPU",
    "RAM (Total)",
    "DISK (Total)"
])

for idx, item in enumerate(vms, start=1):
    values.append([
        idx,
        item.get("hostname", ""),
        item.get("ip", ""),
        item.get("os_version", ""),
        item.get("kernel_version", ""),
        item.get("uptime", ""),
        item.get("vcpu", ""),
        item.get("ram_total", ""),
        item.get("disk_total", ""),
    ])

# =========================================================
# WRITE VALUES
# =========================================================

service.spreadsheets().values().update(
    spreadsheetId=SPREADSHEET_ID,
    range=f"{MAIN_SHEET_NAME}!A1",
    valueInputOption="RAW",
    body={
        "values": values
    }
).execute()

# =========================================================
# FORMAT REQUESTS
# =========================================================

requests = []

# =========================================================
# MERGE TITLE
# =========================================================

requests.append({
    "mergeCells": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 9
        },
        "mergeType": "MERGE_ALL"
    }
})

# =========================================================
# FORMAT TITLE
# =========================================================

requests.append({
    "repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 0,
            "endRowIndex": 1
        },
        "cell": {
            "userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "textFormat": {
                    "fontSize": 18,
                    "bold": True
                }
            }
        },
        "fields": "userEnteredFormat(horizontalAlignment,textFormat)"
    }
})

# =========================================================
# LEFT ALIGN
# A3:A9
# A14:A38
# =========================================================

requests.append({
    "repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 2,
            "endRowIndex": 9,
            "startColumnIndex": 0,
            "endColumnIndex": 1
        },
        "cell": {
            "userEnteredFormat": {
                "horizontalAlignment": "LEFT"
            }
        },
        "fields": "userEnteredFormat.horizontalAlignment"
    }
})

requests.append({
    "repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 13,
            "endRowIndex": 38,
            "startColumnIndex": 0,
            "endColumnIndex": 1
        },
        "cell": {
            "userEnteredFormat": {
                "horizontalAlignment": "LEFT"
            }
        },
        "fields": "userEnteredFormat.horizontalAlignment"
    }
})

# =========================================================
# COLUMN WIDTH
# =========================================================

column_widths = {
    0: 60,
    1: 260,
    2: 150,
    3: 220,
    4: 220,
    5: 120,
    6: 80,
    7: 120,
    8: 120,
}

for col, width in column_widths.items():
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": col,
                "endIndex": col + 1
            },
            "properties": {
                "pixelSize": width
            },
            "fields": "pixelSize"
        }
    })

# =========================================================
# HEADER STYLE
# =========================================================

header_rows = [4, 13]

for row in header_rows:
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row,
                "endRowIndex": row + 1,
                "startColumnIndex": 0,
                "endColumnIndex": 9
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {
                        "red": 0.2,
                        "green": 0.2,
                        "blue": 0.2
                    },
                    "horizontalAlignment": "CENTER",
                    "textFormat": {
                        "foregroundColor": {
                            "red": 1,
                            "green": 1,
                            "blue": 1
                        },
                        "bold": True
                    }
                }
            },
            "fields": "*"
        }
    })

# =========================================================
# SECTION TITLE STYLE
# =========================================================

section_rows = [3, 12]

for row in section_rows:
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row,
                "endRowIndex": row + 1,
                "startColumnIndex": 0,
                "endColumnIndex": 9
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {
                        "red": 0.85,
                        "green": 0.85,
                        "blue": 0.85
                    },
                    "textFormat": {
                        "bold": True,
                        "fontSize": 12
                    }
                }
            },
            "fields": "*"
        }
    })

# =========================================================
# CLEAR ALL BORDERS
# =========================================================

requests.append({
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
# A4:I11
# =========================================================

requests.append({
    "updateBorders": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 4,
            "endRowIndex": 11,
            "startColumnIndex": 0,
            "endColumnIndex": 9
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
# A14:I40
# =========================================================

requests.append({
    "updateBorders": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 14,
            "endRowIndex": 40,
            "startColumnIndex": 0,
            "endColumnIndex": 9
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
# APPLY FORMATTING
# =========================================================

service.spreadsheets().batchUpdate(
    spreadsheetId=SPREADSHEET_ID,
    body={
        "requests": requests
    }
).execute()

print("=" * 60)
print("Spreadsheet updated successfully")
print("=" * 60)