"""One-off repair: restore a missing Down Payment stage on a project.

A project whose plan is "X% down + single balance" must have two stages. If an edit collapsed it
into one full-amount stage that took over the Down Payment's invoice link, this splits it back:

    Down Payment (X%)  - keeps the invoice link / status / paid amount
    Final Payment      - Pending Invoice, the remaining balance

Usage (from the repo root, with the same environment the app runs with - e.g. FIREBASE_PROJECT=mabs):
    python web_app/repair_project_stages.py MABS-202610137          # dry run, prints what it would do
    python web_app/repair_project_stages.py MABS-202610137 --apply  # writes the fix
"""
import sys
from datetime import datetime, timezone

import app as pims  # noqa: E402  (sits next to app.py, so it is importable as-is)


def main(project_number: str, apply: bool) -> int:
    projects = pims.fb_get("/projects") or {}
    matches = [(pid, p) for pid, p in projects.items()
               if isinstance(p, dict) and p.get("project_number") == project_number]
    if len(matches) != 1:
        print(f"Expected exactly one project {project_number}, found {len(matches)}")
        return 1
    pid, proj = matches[0]
    stages = proj.get("payment_stages") or []
    cv = pims._safe_float(proj.get("contract_value", 0))
    pct = pims._safe_float(proj.get("down_payment_percent", 0))
    print(f"Project {project_number} ({pid}): contract={cv}, down%={pct}, "
          f"installments={proj.get('installment_count')}")
    for i, s in enumerate(stages):
        print(f"  stage {i}: {s}")

    base = [s for s in stages if isinstance(s, dict) and not pims._is_co_stage(s)]
    if len(base) != 1 or pct <= 0 or pct >= 100:
        print("Not the collapsed-plan shape (need exactly one base stage and 0 < down% < 100). Nothing to do.")
        return 1
    stage = base[0]
    if "down payment" in str(stage.get("name", "")).lower():
        print("Stage is already a Down Payment. Nothing to do.")
        return 1

    down_amt = round(cv * pct / 100.0, 2)
    balance = round(cv - down_amt, 2)

    inv_id = stage.get("invoice_id", "")
    inv = (pims.fb_get(f"/invoices/{inv_id}") or {}) if inv_id else {}
    inv_total = pims._safe_float((inv.get("meta") or {}).get("total", 0))
    print(f"Linked invoice {stage.get('invoice_number') or inv_id or '(none)'}: total={inv_total}")
    if inv_id and abs(inv_total - down_amt) > 0.01:
        print(f"Invoice total {inv_total} does not match the down payment {down_amt}; "
              "not guessing - fix this one by hand.")
        return 1

    down = dict(stage, name=f"Down Payment ({pct:.0f}%)", amount=down_amt)
    final = {"name": "Final Payment", "amount": balance, "status": "Pending Invoice", "invoice_id": ""}
    new_stages = [down, final] + [s for s in stages if s is not stage and pims._is_co_stage(s)]
    print("Would write:")
    for i, s in enumerate(new_stages):
        print(f"  stage {i}: {s}")
    if not apply:
        print("Dry run - re-run with --apply to write.")
        return 0
    pims.fb_update(f"/projects/{pid}", {"payment_stages": new_stages,
                                        "updated_at": datetime.now(timezone.utc).isoformat()})
    print("Written.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], "--apply" in sys.argv))
