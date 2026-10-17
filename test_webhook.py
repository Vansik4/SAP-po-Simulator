"""Sends a test PO confirmation to the local webhook.

Usage:  python test_webhook.py [po_number] [status]
        status: Created | Confirmed | Pending
"""
import sys

import requests

URL = "http://localhost:8000/api/webhook"

payload = {
    "po_number": sys.argv[1] if len(sys.argv) > 1 else "4500012345",
    "vendor_email": "sales@supplier-demo.com",
    "client_email": "purchasing@customer-demo.com",
    "order_details": {
        "items": [
            {"item": 10, "material": "MAT-1001", "description": "Hex Bolt M8x40 Zinc", "quantity": 200, "unit": "EA", "net_price": 0.42, "net_value": 84.0},
            {"item": 20, "material": "MAT-4410", "description": "Ball Bearing 6204-2RS", "quantity": 50, "unit": "EA", "net_price": 3.9, "net_value": 195.0},
        ],
        "currency": "USD",
        "total": 279.0,
        "delivery_date": "2026-11-15",
    },
    "status": sys.argv[2] if len(sys.argv) > 2 else "Confirmed",
}

r = requests.post(URL, json=payload, timeout=10)
print(r.status_code, r.json())
