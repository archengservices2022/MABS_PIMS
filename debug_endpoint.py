#!/usr/bin/env python
import os
os.environ['FIREBASE_PROJECT'] = 'arch'

from web_app.app import app, fb_get, _safe_float

with app.app_context():
    all_proj_comm = fb_get("/project_commissions") or {}

    print("Testing commission data extraction:\n")

    commissions = []
    for comm_id, comm_data in list(all_proj_comm.items() if isinstance(all_proj_comm, dict) else [])[:3]:
        if not isinstance(comm_data, dict):
            continue

        commission_entry = {
            "commission_doc_id": comm_id,
            "project_id": comm_data.get("project_id", ""),
            "project_number": comm_data.get("project_number", "—"),
            "client_name": comm_data.get("company_name", ""),
            "salesperson": comm_data.get("salesperson", ""),
            "contract_value": _safe_float(comm_data.get("contract_value", 0)),
            "commission_amount": _safe_float(comm_data.get("commission_amount", 0)),
            "rate_display": comm_data.get("rate_display", "—"),
            "total_deducted": _safe_float(comm_data.get("total_deducted", 0)),
            "remaining_due": _safe_float(comm_data.get("remaining_due", 0)),
            "status": comm_data.get("status", "Pending"),
        }
        commissions.append(commission_entry)
        print(f"Commission {len(commissions)}:")
        for key, val in commission_entry.items():
            print(f"  {key}: {val}")
        print()
