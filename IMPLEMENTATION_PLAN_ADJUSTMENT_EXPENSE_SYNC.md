# Implementation Plan: Advance Adjustment to Expense Sync

## Overview
This feature creates a bidirectional sync between advance adjustments and finance expenses. When an adjustment is created/updated/deleted, the corresponding expense is also created/updated/deleted.

## Files to Modify
1. `web_app/app.py` - Add sync functions and modify endpoints
2. `web_app/templates/advance_detail.html` - Make expense fields read-only where needed
3. Database adjustments - Add linking fields

## Key Functions to Create

### 1. _sync_adjustment_to_expense()
- Triggered: When adjustment is saved/updated
- Logic:
  - Extract adjustment data
  - Determine if commission deduction (needs project tracking)
  - Get project numbers from commission deductions
  - Create/update expense record in balance_sheet_expenses
  - Link expense_id to adjustment record
  - Handle categories by type

### 2. _delete_linked_expense()
- Triggered: When adjustment is deleted
- Logic:
  - Find expense by linked_adjustment_id
  - Delete the expense record

### 3. _restore_linked_expense()
- Triggered: When adjustment is restored
- Logic:
  - Find expense by linked_adjustment_id
  - Mark expense as restored

## Integration Points

### In add_advance_adjustment():
- After successful adjustment save (around line 12600)
- Call: `_sync_adjustment_to_expense(adjustment_id, adjustment, advance_data, employee_name)`

### In update_advance_adjustment():
- After successful adjustment update
- Call: `_sync_adjustment_to_expense(adjustment_id, adjustment, advance_data, employee_name)`

### In delete_advance_adjustment():
- After successful adjustment delete
- Call: `_delete_linked_expense(adjustment_id)`

## Data Structure Changes

### Adjustment Record (employee_advances/{id}/adjustments/{adj_id})
Add field:
```
"linked_expense_id": "expense_uuid"
```

### Expense Record (balance_sheet_expenses/{id})
Add fields:
```
"linked_adjustment_id": "adjustment_uuid",
"adjustment_type": "Commission Deduction|Loan Deduction|...",
"from_advance_id": "advance_uuid",
"is_adjustment": true,
"read_only_amount": true
```

## Implementation Status
⏳ Ready for coding
