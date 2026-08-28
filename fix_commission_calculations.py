#!/usr/bin/env python3
"""
Recalculate commission amounts for all projects to fix the override type mismatch bug.
This script re-runs _upsert_project_commission for all projects to ensure commissions
are calculated correctly based on custom override rates.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from web_app.app import fb_get, fb_update, _upsert_project_commission, log

def recalculate_all_commissions():
    """Recalculate commission for all projects."""
    projects = fb_get("/projects") or {}

    if not isinstance(projects, dict):
        print("No projects found or invalid format")
        return

    fixed_count = 0
    skipped_count = 0
    error_count = 0

    for project_id, project_data in projects.items():
        if not isinstance(project_data, dict):
            skipped_count += 1
            continue

        proj_num = project_data.get("project_number", "unknown")

        # Check if project has commission override
        override_type = project_data.get("commission_override_type", "").strip()
        override_val = float(project_data.get("commission_override_value", 0) or 0)

        if not override_type or not override_val or override_type.lower() == "default":
            skipped_count += 1
            continue

        try:
            print(f"Recalculating: {proj_num}")
            print(f"  Override Type: {override_type}")
            print(f"  Override Value: {override_val}")

            # Re-run the commission calculation
            _upsert_project_commission(project_id, project_data)

            # Get the updated commission data
            updated_comm = fb_get(f"/project_commissions/{project_id}") or {}
            new_amount = float(updated_comm.get("commission_amount", 0) or 0)

            print(f"  New Commission Amount: ${new_amount:,.2f}")
            print(f"  Status: ✓ Fixed")
            fixed_count += 1

        except Exception as e:
            print(f"  Status: ✗ Error - {str(e)}")
            error_count += 1

    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Fixed:   {fixed_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Errors:  {error_count}")
    print(f"{'='*60}")

if __name__ == "__main__":
    print("Starting commission recalculation...")
    print("This will update commission amounts for all projects with custom overrides.\n")

    response = input("Continue? (yes/no): ").strip().lower()
    if response != "yes":
        print("Cancelled.")
        sys.exit(0)

    recalculate_all_commissions()
    print("\nDone!")
