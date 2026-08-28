# Advance Adjustment to Expense Sync Feature

## Overview
When an advance adjustment is saved/updated, it should automatically create or update a corresponding expense record in the Finance Expenses system for accounting tracking.

## Requirements

### 1. Commission Deduction Type
When adjustment type is "Commission Deduction":

**Expense Record Fields:**
- `expense_type`: "Other"
- `category`: "Commission Deduction"
- `expense_name`: "Adjusted - {Employee Name}"
- `vendor`: "Advance Adjustments"
- `amount`: {Adjustment Amount} (READ-ONLY)
- `date`: {Adjustment Date} (EDITABLE, syncs both ways)
- `project_numbers`: All projects from commission deduction list
- `submitted_by`: Employee name who made adjustment
- `from_advance_id`: Link to source advance record
- `linked_advance_id`: Reference to advance adjustment record

**Display Rules:**
- Detail page: Show all project numbers
- Table view: Show first 3, then "X projects" if more
- Example: "MABS-202512110, MABS-202512108, MABS-202512107, 2 projects"

### 2. Other Adjustment Types
All other adjustment types (Loan Deduction, Tax Deduction, etc.):

**Expense Record Fields:**
- `expense_type`: "Other"
- `category`: {Adjustment Type} (varies by type)
- `expense_name`: "Adjusted - {Employee Name}"
- `vendor`: "Advance Adjustments"
- `amount`: {Adjustment Amount} (READ-ONLY)
- `date`: {Adjustment Date} (EDITABLE)
- `project_numbers`: EMPTY (no project tracking)

### 3. Sync Logic

**On Adjustment Save:**
1. Check if expense already exists (by linked_advance_id)
2. If not, create new expense
3. If exists, update amount, category, date, project_numbers

**On Adjustment Delete:**
1. Delete linked expense record

**On Date Edit (in Adjustment):**
1. Update expense date
2. Update adjustment history record with new date
3. Reflect change immediately in both places

**Amount/Details are Read-Only:**
- User cannot edit amount in expense detail
- User cannot edit category in expense detail
- Only date can be changed in expense

### 4. Implementation Steps

**Step 1:** Add helper function to sync adjustment to expense
**Step 2:** Call sync function in add_advance_adjustment() 
**Step 3:** Call sync function in update_advance_adjustment()
**Step 4:** Call sync function in delete_advance_adjustment()
**Step 5:** Update expense table to handle project number display
**Step 6:** Make expense detail page read-only for amount/details
**Step 7:** Handle date edit sync in both directions

## Database Structure

**balance_sheet_expenses table additions:**
```
{
  "id": "uuid",
  "expense_type": "Other",
  "category": "Commission Deduction|Loan Deduction|Tax Deduction",
  "expense_name": "Adjusted - {Employee}",
  "vendor": "Advance Adjustments",
  "amount": 100.00,
  "date": "2026-08-28",
  "project_numbers": ["MABS-202512110", "MABS-202512108"],
  "submitted_by": "Admin",
  "linked_advance_id": "advance_adj_id",
  "from_advance_id": "advance_id",
  "is_adjustment": true,
  "created_at": "2026-08-28T...",
  "updated_at": "2026-08-28T..."
}
```

## Status
⏳ Ready for implementation
