#!/usr/bin/env python
import os
os.environ['FIREBASE_PROJECT'] = 'arch'

from web_app.app import app, fb_get

with app.app_context():
    # Test directly without HTTP request
    all_proj_comm = fb_get("/project_commissions") or {}

    print(f'Commissions in database: {len(all_proj_comm) if isinstance(all_proj_comm, dict) else 0}')

    if isinstance(all_proj_comm, dict):
        for proj_id, comm_data in list(all_proj_comm.items())[:5]:
            if isinstance(comm_data, dict):
                status = comm_data.get("status", "?")
                earned = comm_data.get("commission_amount", 0)
                salesperson = comm_data.get("salesperson", "Unknown")
                print(f'  - {salesperson}: {proj_id} - {status} - ${earned}')
    else:
        print('Commissions is not a dict')
