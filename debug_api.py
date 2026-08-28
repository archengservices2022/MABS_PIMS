#!/usr/bin/env python
import os
import json
os.environ['FIREBASE_PROJECT'] = 'arch'

from web_app.app import app

with app.app_context():
    with app.test_client() as client:
        # Mock session
        with client.session_transaction() as sess:
            sess['user_uid'] = 'test-user'
            sess['user_role'] = 'admin'
            sess['logged_in'] = True

        # Test the API
        response = client.get('/api/payroll/commissions')

        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.get_json()
            comms = data.get('commissions', [])
            print(f"\nTotal commissions: {len(comms)}")

            if comms:
                print("\n=== FIRST 2 COMMISSION RECORDS ===")
                for comm in comms[:2]:
                    print(f"\nCommission:")
                    for key, value in comm.items():
                        print(f"  {key}: {value}")
        else:
            print(f"Error: {response.data}")
