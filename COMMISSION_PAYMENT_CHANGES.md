# Commission Payment Protection & Sync Implementation

## Overview
Updated the system to prevent users from editing commission payment amounts in Salaries and Expenses tabs, while allowing date edits that sync back to Commission Details.

## Changes Made

### 1. Expense Edit Endpoint (`/financial/expense/<exp_id>/edit`) - Line 15922+
**Protection Added:**
- Detects commission payments (via `commission_id`, `is_commission` flag, or category/type)
- Prevents editing of commission payment amounts
- Returns error: "Cannot edit amount: This is a commission payment from the commission details tab..."

**Date Sync Added:**
- When date is edited on commission expense, syncs the date back to commission record(s)
- Handles both single commission payments (via `commission_id`)
- Handles multi-project payments (via `commission_payment_details` array)
- Updates `paid_at` and `last_payment_date` in commission records

### 2. Salary Update Endpoint (`/api/payroll/salaries/<sal_id>` PUT) - Line 11586+
**Protection Added:**
- Checks for commission protection using `is_commission` flag or `commission_id`
- Prevents editing of commission payment amounts
- Returns same error message as expense endpoint

**Date Sync Added:**
- When date is edited on commission salary, syncs back to commission record(s)
- Handles both single commission payments and multi-project payments
- Validates salary_type == "Commission" before syncing

### 3. Commission Payment Endpoint (`/api/commission/pay`) - Line 10065+
**Enhancement:**
- Added `is_commission: True` flag to salary records
- Added `commission_payment_details` array to salary records (for multi-project tracking)
- These flags enable proper identification and protection in both edit endpoints

## Behavior

### Mark as Paid (Single Commission)
✅ Creates salary record with `commission_id` field
✅ Creates expense record with `commission_id` field
✅ Amount cannot be edited in Salaries or Expenses
✅ Date can be edited → syncs to Commission Details

### Add Commission Payment (Multiple Commissions)
✅ Creates salary record with `is_commission=true` and `commission_payment_details` array
✅ Creates expense record with `commission_payment_details` array
✅ Amount cannot be edited in Salaries or Expenses
✅ Date can be edited → syncs to all commissions in the payment

## File Modified
- `c:\Users\HP\MABS_PIMS\web_app\app.py`

## Error Messages
Users attempting to edit commission payment amounts will see:
```
"Cannot edit amount: This is a commission payment from the commission details tab. 
You can only edit the date. To modify the payment amount, use commission payment options."
```

## Data Flow

```
Commission Details Tab:
├── Mark as Paid (Single)
│   └── Creates Salary + Expense with commission_id
│       └── User can only edit date (syncs back to commission)
│
└── Add Commission Payment (Multiple)
    └── Creates Salary + Expense with is_commission flag + commission_payment_details
        └── User can only edit date (syncs back to all commissions in payment)
```

## Testing Checklist
- [ ] Mark single project as paid → verify amounts locked, date editable
- [ ] Add commission payment for multiple projects → verify amounts locked, date editable
- [ ] Edit commission salary date → verify commission details date updates
- [ ] Edit commission expense date → verify commission details date updates
- [ ] Attempt to edit commission amount in salary → verify error message
- [ ] Attempt to edit commission amount in expense → verify error message
