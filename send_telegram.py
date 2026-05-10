#!/usr/bin/env python3

import os
import glob
import requests
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = "-"
CHAT_ID = "-"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "pdf")

# =========================================================
# FIND LATEST PDF
# =========================================================

pdf_files = sorted(
    glob.glob(os.path.join(PDF_DIR, "*.pdf"))
)

if not pdf_files:
    raise Exception("Tidak ada file PDF")

latest_pdf = pdf_files[-1]

pdf_name = os.path.basename(latest_pdf)

# =========================================================
# GET FILE TIMESTAMP
# =========================================================

file_time = os.path.getmtime(latest_pdf)

generated_time = datetime.fromtimestamp(
    file_time
).strftime("%Y-%m-%d %H:%M:%S")

# =========================================================
# TELEGRAM API
# =========================================================

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"

caption = f"""
📄 Daily Infra Report

🕒 Generated Time:
{generated_time}

🔁 Automation:
Every 4 Hours

📎 Attached File:
{pdf_name}
"""

print("=" * 60)
print(f"Sending PDF : {latest_pdf}")
print("=" * 60)

with open(latest_pdf, "rb") as f:
    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "caption": caption,
        },
        files={
            "document": f
        }
    )

print(response.text)

if response.status_code == 200:
    print("\n✅ PDF berhasil dikirim ke Telegram")
else:
    print("\n❌ Gagal kirim Telegram")