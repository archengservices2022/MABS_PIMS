#!/usr/bin/env python3
"""
Migration for Arch PIMS: Update project numbers from 001-099 to 101-199 sequences.
This uses the arch Firebase database (invoice-7fe93-default-rtdb.firebaseio.com).

Usage:
    python migrate_arch_projects.py
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def migrate_arch_projects():
    """Migrate arch project numbers from 001 to 101 format."""
    try:
        # Set Firebase project to 'arch' before importing
        os.environ["FIREBASE_PROJECT"] = "arch"

        from web_app.app import fb_get, fb_update

        print("🏢 Migrating ARCH PIMS project numbers...")
        print(f"Database: invoice-7fe93-default-rtdb.firebaseio.com")
        print()

        projects = fb_get("/projects") or {}

        if not projects:
            print("No projects found in Arch database.")
            return True

        migrated = []
        skipped = []

        pattern = r"^(ARCH|MABS)-(\d{6})(\d{3})(.*)$"

        for project_id, project_data in projects.items():
            if not isinstance(project_data, dict):
                skipped.append((project_id, "Invalid data structure"))
                continue

            old_number = project_data.get("project_number", "")
            if not old_number:
                skipped.append((project_id, "No project_number field"))
                continue

            match = re.match(pattern, str(old_number))
            if not match:
                skipped.append((project_id, f"Doesn't match pattern: {old_number}"))
                continue

            prefix, date, sequence, suffix = match.groups()
            sequence_int = int(sequence)

            if sequence_int > 99:
                skipped.append((project_id, f"Already updated: {old_number}"))
                continue

            new_sequence = sequence_int + 100
            new_number = f"{prefix}-{date}{new_sequence:03d}{suffix}"

            print(f"  {old_number} → {new_number}")

            fb_update(f"/projects/{project_id}", {"project_number": new_number})
            migrated.append({
                "project_id": project_id,
                "old_number": old_number,
                "new_number": new_number
            })

        print("\n" + "="*60)
        print(f"Arch PIMS Migration complete!")
        print(f"  ✓ Updated: {len(migrated)} projects")
        print(f"  ⊘ Skipped: {len(skipped)} projects")
        print("="*60)

        return True

    except Exception as e:
        print(f"Error during Arch migration: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = migrate_arch_projects()
    sys.exit(0 if success else 1)
