```python id="v4r8mx"
#!/usr/bin/env python3

import os
from datetime import datetime

from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

# =========================================================
# CONFIG
# =========================================================

SPREADSHEET_ID = "1Pamx_pVk6j9KmU61l7c21LYC_3hvy_coC4dHoCt6Qxk"

# Sheet: infra main
SHEET_GID = "1335848489"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SERVICE_ACCOUNT_FILE = os.path.join(
    SCRIPT_DIR,
    "service_account.json"
)

OUTPUT_DIR = os.path.join(
    SCRIPT_DIR,
    "pdf"
)

# =========================================================
# GOOGLE AUTH
# =========================================================

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
)

authed_session = AuthorizedSession(creds)

# =========================================================
# CREATE OUTPUT DIRECTORY
# =========================================================

os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================================================
# OUTPUT FILE
# =========================================================

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

output_file = os.path.join(
    OUTPUT_DIR,
    f"infra_report_{timestamp}.pdf"
)

# =========================================================
# EXPORT URL
# =========================================================

export_url = (
    f"https://docs.google.com/spreadsheets/d/"
    f"{SPREADSHEET_ID}/export"
    f"?format=pdf"
    f"&gid={SHEET_GID}"
    f"&size=A4"
    f"&portrait=false"
    f"&scale=4"
    f"&fitw=true"
    f"&sheetnames=false"
    f"&printtitle=false"
    f"&pagenumbers=false"
    f"&gridlines=false"
    f"&fzr=true"
    f"&horizontal_alignment=CENTER"
    f"&vertical_alignment=MIDDLE"
    f"&top_margin=0.10"
    f"&bottom_margin=0.10"
    f"&left_margin=0.10"
    f"&right_margin=0.10"
)

# =========================================================
# EXPORT PDF
# =========================================================

print("=" * 60)
print("EXPORTING PDF...")
print("=" * 60)

response = authed_session.get(export_url)

if response.status_code != 200:
    print(f"[ERROR] Export gagal: {response.status_code}")
    print(response.text)
    raise SystemExit(1)

with open(output_file, "wb") as f:
    f.write(response.content)

print("=" * 60)
print("PDF BERHASIL DIBUAT")
print(output_file)
print("=" * 60)
```
