# Commission Calculation Fix - Summary

## Problem Identified

The P&L section in Project Detail was showing incorrect commission amounts (e.g., $50 instead of $500).

### Root Causes

1. **Field Name Mismatch (Bug #1)**
   - `project_detail.py` was looking for `commission_earned` field (doesn't exist)
   - `project_commissions` stores `commission_amount` field
   - Result: Fallback logic always returned 0
   - **Fix:** Changed fallback to use `commission_amount` (3 locations)

2. **Commission Type Detection (Bug #2)**
   - `_upsert_project_commission` only recognized exact matches: `"percent"` or `"fixed"`
   - Commission Detail form sends: `"Custom Percentage (%)"` or `"Fixed Amount ($)"`
   - When types didn't match, calculation fell back to salesperson's default rate (5% instead of 50%)
   - Result: $1000 × 5% = $50 instead of $1000 × 50% = $500
   - **Fix:** Updated type detection to check for `"%"` or `"$"` in type string, similar to project_detail logic

3. **Stored Commission Amounts**
   - Existing projects with custom override rates had their `commission_amount` already stored as $50
   - These amounts won't be recalculated until `_upsert_project_commission` is called again
   - **Fix:** Run migration script to recalculate all commissions

## Changes Made

### In `web_app/app.py`:

#### Change 1: Field name fallback (3 locations)
```python
# Before:
comm_earned = _safe_float(_comm_entry.get("commission_earned", 0))

# After:
comm_earned = _safe_float(_comm_entry.get("commission_amount", 0))
```
- Line 3929 (project_detail)
- Line 11415 (financial_byproject_export)
- Line 13925 (financial)

#### Change 2: Commission type detection in _upsert_project_commission (lines 23208-23232)
```python
# Before:
if override_type == "percent" and override_value > 0:
    commission_amount = contract_value * override_value / 100
elif override_type == "fixed" and override_value > 0:
    commission_amount = override_value

# After:
if ("percent" in override_type or "%" in override_type) and override_value > 0:
    pct_val = override_value if override_value > 1 else (override_value * 100)
    commission_amount = contract_value * pct_val / 100
    override_type = "percent"  # Normalize
elif ("fixed" in override_type or "$" in override_type) and override_value > 0:
    commission_amount = override_value
    override_type = "fixed"  # Normalize
```

#### Change 3: Added logging for debugging (lines 3916-3930)
Added debug logs to track commission calculation values during project detail view.

### Migration Script: `fix_commission_calculations.py`

Recalculates commission amounts for all projects with custom override rates.

## How to Apply the Fix

### Step 1: Verify Code Changes
The code changes in `app.py` are already in place. Restart Flask for changes to take effect.

### Step 2: Recalculate Commission Amounts
Run the migration script to fix existing commission amounts:

```bash
python fix_commission_calculations.py
```

This will:
- Scan all projects with custom commission overrides
- Recalculate their commission amounts using the corrected logic
- Show summary of fixed/skipped/errored projects

### Step 3: Verify Results
1. Reload the Project Detail page
2. Check that EXPENSES now shows $500 (not $50) for 50% commission
3. Verify P&L calculations reflect the corrected amounts

## What Changed for Users

### Before Fix
- Commission P&L showed: $50
- Commission Details showed: Custom 50.0% → $500
- Inconsistency caused confusion and incorrect financial reports

### After Fix
- Commission P&L shows: $500 ✓
- Commission Details shows: Custom 50.0% → $500 ✓
- Consistent across all views

## Note on Commission Forms

The system now properly handles commission type values from both sources:
- **Project Detail form:** Sends `"percent"`, `"fixed"`, `"default"`
- **Commission Detail form:** Sends `"Custom Percentage (%)"`, `"Fixed Amount ($)"`, etc.

Both formats are now correctly recognized and normalized for consistent calculation.
