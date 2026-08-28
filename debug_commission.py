#!/usr/bin/env python
import os
import json
os.environ['FIREBASE_PROJECT'] = 'arch'

from web_app.app import app, fb_get

with app.app_context():
    all_proj_comm = fb_get("/project_commissions") or {}
    all_projects = fb_get("/job_forms") or {}

    print("=== SAMPLE COMMISSION RECORD ===")
    if isinstance(all_proj_comm, dict):
        for comm_id, comm_data in list(all_proj_comm.items())[:1]:
            print(f"\nCommission Doc ID: {comm_id}")
            print(f"Fields:")
            if isinstance(comm_data, dict):
                for key, value in comm_data.items():
                    print(f"  {key}: {value}")

    print("\n=== SAMPLE PROJECT RECORD ===")
    if isinstance(all_projects, dict):
        for proj_id, proj_data in list(all_projects.items())[:1]:
            print(f"\nProject ID: {proj_id}")
            print(f"Fields (sample):")
            if isinstance(proj_data, dict):
                keys = ['number', 'project_number', 'client', 'sales', 'sales_person', 'contract_value']
                for key in keys:
                    if key in proj_data:
                        print(f"  {key}: {proj_data[key]}")
