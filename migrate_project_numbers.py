#!/usr/bin/env python3
"""
One-time migration script to update project numbers from 001-099 to 101-199 sequences.
This updates all existing projects that follow the MABS-YYYYMM### format.

Usage:
    python migrate_project_numbers.py
"""

import re
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def migrate_project_numbers():
    """Migrate existing project numbers from 001 to 101 format."""
    try:
        # Import Firebase utilities from app
        from web_app.app import fb_get, fb_update

        print("Loading all projects from Firebase...")
        projects = fb_get("/projects") or {}

        if not projects:
            print("No projects found.")
            return

        migrated = []
        skipped = []

        # Pattern to match MABS-YYYYMM### format
        pattern = r"^(MABS)-(\d{6})(\d{3})(.*)$"

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

            # Only migrate sequences 001-099 (values 1-99)
            if sequence_int > 99:
                skipped.append((project_id, f"Already updated or out of range: {old_number}"))
                continue

            # Add 100 to sequence
            new_sequence = sequence_int + 100
            new_number = f"{prefix}-{date}{new_sequence:03d}{suffix}"

            print(f"  {old_number} → {new_number}")

            # Update project in Firebase
            fb_update(f"/projects/{project_id}", {"project_number": new_number})
            migrated.append({
                "project_id": project_id,
                "old_number": old_number,
                "new_number": new_number
            })

        print("\n" + "="*60)
        print(f"Migration complete!")
        print(f"  ✓ Updated: {len(migrated)} projects")
        print(f"  ⊘ Skipped: {len(skipped)} projects")
        print("="*60)

        if migrated:
            print("\nMigrated projects:")
            for item in migrated:
                print(f"  {item['old_number']} → {item['new_number']}")

        if skipped:
            print("\nSkipped projects:")
            for project_id, reason in skipped[:10]:  # Show first 10
                print(f"  {project_id}: {reason}")
            if len(skipped) > 10:
                print(f"  ... and {len(skipped) - 10} more")

        return True

    except Exception as e:
        print(f"Error during migration: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = migrate_project_numbers()
    sys.exit(0 if success else 1)
