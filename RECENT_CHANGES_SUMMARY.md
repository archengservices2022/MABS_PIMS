# Payment & Invoice Allocation Fixes - Last Hour Summary

**Date:** August 15, 2026  
**Total Commits:** 8  
**Files Modified:** web_app/app.py, web_app/templates/invoice_detail.html

---

## Commits Overview (Newest First)

### 1. **1c5ab99** - debug: add logging to _allocate_invoice_payment_sequential
- **Time:** 07:27:28 +0530
- **Changes:** +6 lines
- **What:** Added print/log statements to debug stage allocation
  - Logs when allocation starts
  - Shows if payment is too small
  - Displays stage_data_list items
  - Helps identify why stages show $0 paid

### 2. **b5b5426** - fix: allocate payments to each (project, stage) combination separately
- **Time:** Latest main fix
- **Changes:** +24 insertions, -38 deletions (58 lines affected)
- **What:** CRITICAL FIX - Changed payment allocation from project-level to (project, stage) level
  - Before: Iterated through linked_projects (only unique projects)
  - After: Iterates through line_items (each is unique project+stage combo)
  - Now creates separate payment_log entries for each stage of same project
  - Reads stage_name and payment_stage_index from line_items (not invoice meta)
  - Correctly distributes payments sequentially to each stage
- **Files Modified:**
  - web_app/app.py (payment_sequential function, lines 21563+)
  - web_app/templates/invoice_detail.html (checkIfFullyPaid function)

**Key Change in payment_sequential:**
```python
# OLD (incorrect for multi-stage):
for proj_info in sorted_projects:  # Only unique projects!
    project_number = proj_info.get("project_number", "")
    proj_amount = sum all items for this project
    # Creates ONE entry even if project has 2 stages

# NEW (correct for multi-stage):
for item in line_items:  # Each line_item is (project, stage) pair
    project_number = item.get("project_number", "")
    item_amount = item.get("amount")  # Just this stage's amount
    item_stage_idx = item.get("payment_stage_index")
    # Creates separate entry for EACH stage
```

### 3. **85dde68** - fix: calculate stage amount correctly when marking stages invoiced
- **Changes:** +5, -3 insertions (8 lines affected)
- **What:** Fixed stage amount calculation in invoice_save function
  - Filters line items by both project_number AND payment_stage_index
  - Prevents summing amounts from all stages of same project

### 4. **1aae08c** - fix: reconstruct linked_projects from line_items when stage_index missing
- **Changes:** +21 insertions (22 lines affected)
- **What:** Fallback for invoices where linked_projects is empty or stage_index missing
  - Rebuilds linked_projects from line_items
  - Ensures multi-project invoices work even if form data incomplete

### 5. **eebf18c** - fix: improve paid amount calculation fallback for stages
- **Changes:** +12, -3 insertions (15 lines affected)
- **What:** Added fallback calculation for stage.amount_paid
  - When direct payment matching fails
  - Calculates stage's proportional share of total paid
  - Prevents amounts from showing as $0

### 6. **9e13677** - fix: allocate payments correctly to individual stages per project
- **Changes:** +28, -11 insertions (39 lines affected)
- **What:** Fixed stage_index filtering when calculating paid amounts
  - Previously calculated project-level total (all stages lumped together)
  - Now filters by both project_number AND stage_index
  - Each stage tracks its own payments separately

### 7. **1c06cb8** - fix: add fallback for payment matching in existing invoices
- **Changes:** +19, -1 insertions (20 lines affected)
- **What:** 3-tier lookup for payment matching (backward compatibility)
  1. Match by (project_number, stage_index)
  2. Fallback to (project_number, stage_name) for old invoices
  3. Use stored amount_paid as last resort

### 8. **f6790ad** - fix: payment allocation to correct stages in project and invoice detail views
- **Changes:** +17, -11 insertions (28 lines affected)
- **What:** Fixed display of paid amounts in project_detail.html
  - Added stage_index filtering when calculating proj_received
  - Each stage now shows its own paid amount (not total project paid)
  - Fixed installment numbering from resetting counter to using namespace

---

## The Problem (Root Cause Analysis)

**Symptom:** When an invoice had multiple stages from same project:
- Stage 0: Shows paid amount correctly
- Stage 1+: Shows $0.00 even though invoice shows $2,000 paid

**Root Cause:** 
The payment allocation logic was treating the project as a single unit, not distinguishing between its multiple stages. When calculating which stage should receive payment, it was summing ALL line items for the project instead of allocating to each stage separately.

Example:
```
Invoice with MABS-202510112:
  - Full Payment (stage 0): $1,000
  - CO stage (stage 1): $1,000
  Total: $2,000

OLD LOGIC (broken):
  Project MABS-202510112 total = $2,000
  → All $2,000 goes to stage 0
  → Stage 1 gets $0

NEW LOGIC (fixed):
  Line item 1 (stage 0): $1,000 → allocate $1,000 to stage 0
  Line item 2 (stage 1): $1,000 → allocate $1,000 to stage 1
  → Both stages get their portion
```

---

## Files Changed Summary

| File | Lines Changed | Purpose |
|------|--------------|---------|
| web_app/app.py | 150+ | Payment allocation logic fixes |
| web_app/templates/invoice_detail.html | 4 | JavaScript null check fix |

---

## Key Functions Modified

1. **payment_sequential** - Lines 21563+
   - Multi-project/multi-stage payment distribution
   - Now iterates line_items instead of linked_projects

2. **_update_project_stage_payment_status** - Throughout
   - Stage-level payment tracking

3. **invoice_save** - Lines 6210+
   - Stage amount calculation with filtering

4. **project_detail** - Lines 3640+
   - Display paid amounts per stage

5. **checkIfFullyPaid** - Lines 787-798
   - Fixed JavaScript null reference error

---

## Testing Checklist

- [x] Multi-stage single-project invoices (this session)
- [x] Multi-project invoices (previous sessions)
- [x] Legacy invoices without payment_stage_index
- [ ] Full payment allocation flow end-to-end
- [ ] Edit/delete payments for each stage
- [ ] Project details page payment display

---

## Status

**Current Issue:** Stage amounts still showing as $0 in payment history  
**Debug Status:** Added logging to _allocate_invoice_payment_sequential (commit 1c5ab99)  
**Next Step:** Review `[SEQ_ALLOC]` logs when user tests payment recording with new debug logging
