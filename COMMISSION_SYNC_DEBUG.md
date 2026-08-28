# Commission Date Sync - Debugging Guide

## Issue
When editing date in Finance Expense tab, the paid_at date in Commission Details tab is not updating.

## Root Cause Analysis

The commission sync code is in place in the `expense_edit` endpoint. Let me trace through the logic:

### 1. Expense Edit Flow

**Endpoint:** `POST /financial/expense/<exp_id>/edit`  
**Location:** app.py line 15709+

**Step-by-step:**

1. **Line 15716:** Read existing expense record
   ```python
   existing = fb_get(f"/balance_sheet_expenses/{exp_id}") or {}
   ```
   - Gets OLD expense data including date, commission_id, is_commission flag

2. **Line 15730-15743:** Build data dict with NEW values
   ```python
   data = {
       ...
       "date": request.form.get("date", datetime.now(COMPANY_TZ).strftime("%Y-%m-%d")),
       ...
   }
   ```
   - Gets new date from form submission

3. **Line 15812:** Save expense record
   ```python
   fb_update(f"/balance_sheet_expenses/{exp_id}", data)
   ```
   - Updates expense in Firebase

4. **Line 15922-15969:** Commission sync logic
   ```python
   is_commission_payment = existing.get("is_commission") or commission_id or ...
   if is_commission_payment:
       old_date = existing.get("date", "").strip()
       new_date = data.get("date", "").strip()
       
       if old_date != new_date and new_date:
           commission_update = {
               "paid_at": new_date,
               "last_payment_date": new_date,
               ...
           }
           fb_update(f"/project_commissions/{commission_id}", commission_update)
   ```

### 2. What Could Go Wrong

- ✅ `commission_id` field IS being set when expense is created (line 10415, 10416)
- ✅ `is_commission` flag IS being set (added in line 10421, 10110)
- ⚠️ Date format comparison - dates must match exactly (including timezone)
- ⚠️ Expense record might not be tagged properly when edited

## Fix Applied

1. **Added `is_commission: True` flag** to all commission expense records
   - `/api/commission/mark-paid` endpoint (line 10421)
   - `/api/commission/pay` endpoint (line 10110)

2. **Added detailed logging** to track sync execution
   - Line 15945: Logs date comparison
   - Line 15958: Logs single commission sync
   - Line 15964: Logs multi-commission sync

3. **Improved date handling** in sync logic
   - Added `.strip()` to remove whitespace
   - Added check for empty date strings

## Verification Steps

### Manual Testing (In Browser)

1. **Open Commission Details for a salesperson**
   - Note: Don't use already-synced records; need a fresh commission payment

2. **Create or find a commission payment**
   - Use "Mark as Paid" or "Add Commission Payment"
   - Note the payment date

3. **Go to Financial > Expenses**
   - Find the commission expense record
   - Note: Should have expense_name like "Commission - Salesperson Name (MABS-...)"

4. **Edit the expense**
   - Change the date to something different
   - Click "Update Expense"
   - Should save successfully

5. **Verify sync**
   - Go back to Commission Details
   - Check if the "paid_at" date updated to match the new expense date

### Checking Logs

```bash
# Check Flask logs for commission sync messages
tail -f /tmp/flask.log | grep -i "commission sync"
```

Expected output when editing commission expense:
```
Commission sync check: old_date='2026-08-28', new_date='2026-08-29', commission_id=...
Syncing date to single commission: <commission_id>
```

## What's Being Updated

When a commission expense date is edited:

**Old Behavior:**
- ❌ Date updated in Expenses tab only
- ❌ Commission Details paid_at NOT updated

**New Behavior:**
- ✅ Date updated in Expenses tab  
- ✅ Commission Details paid_at UPDATED
- ✅ Salary record date UPDATED (line 15920)
- ✅ All related commissions synced (for multi-project payments)

## Data Sync Verification

### Single Commission Payment

```
Finance Expense Tab:
  date: 2026-08-28
  commission_id: abc123
  ↓
  Sync to:
  Commission Details:
    paid_at: 2026-08-28 ✅
```

### Multi-Project Commission Payment

```
Finance Expense Tab:
  date: 2026-08-28
  is_commission: true
  commission_payment_details: [
    { commission_id: abc123, ... },
    { commission_id: def456, ... }
  ]
  ↓
  Sync to:
  Commission Details (abc123):
    paid_at: 2026-08-28 ✅
  Commission Details (def456):
    paid_at: 2026-08-28 ✅
```

## Code Changes Summary

| Location | Change | Purpose |
|----------|--------|---------|
| Line 10421 | Add `is_commission: True` to mark-paid expense | Enable proper detection |
| Line 10110 | Add `is_commission: True` to pay endpoint expense | Enable proper detection |
| Line 15945 | Add logging for sync check | Debug date comparison |
| Line 15958-15969 | Add logging for sync execution | Track which commissions updated |

## Next Steps If Still Not Working

1. **Check if expense has commission_id:**
   ```
   In Firebase Console:
   /balance_sheet_expenses/{exp_id}
   Should have field: "commission_id": "..."
   ```

2. **Check if commission record exists:**
   ```
   In Firebase Console:
   /project_commissions/{commission_id}
   Should exist and be updatable
   ```

3. **Check for errors in Firebase operations:**
   - Look for permission issues
   - Check if Firebase update is failing silently

4. **Enable more detailed logging:**
   - Add logging before and after `fb_update` calls
   - Check if the UPDATE is actually reaching Firebase
