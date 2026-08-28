# Cascade Delete Testing & Debugging Guide

## ✅ Cascade Delete Features Implemented

### What Should Happen:

1. **Delete from Payroll Salaries:**
   - ✅ Salary record deleted
   - ✅ Linked expense record deleted from Finance
   - ✅ Commission paid_amount reverted to 0
   - ✅ Commission status changed to "Pending"
   - ✅ Commission paid_at cleared

2. **Delete from Finance Expenses:**
   - ✅ Expense record deleted
   - ✅ Linked salary record deleted from Payroll
   - ✅ Commission paid_amount reduced by payment amount
   - ✅ Commission status updated based on remaining balance
   - ✅ Commission paid_at cleared if fully reverted

3. **Multi-Project Commission Payment:**
   - ✅ All commissions in payment reverted to unpaid
   - ✅ Each commission's paid_amount reset independently
   - ✅ Status recalculated for each commission

---

## 🧪 Step-by-Step Testing

### Test 1: Delete Commission Payment from Payroll

**Step 1:** Create a commission payment
```
Payroll → Commission Details → "Mark as Paid" or "Add Commission Payment"
Note: Which commissions you marked paid
```

**Step 2:** Delete from Payroll Salaries
```
Payroll → Salaries (or go to Payroll tab, find the commission salary)
Find: Commission payment salary record
Delete: Click delete button
Result: Salary deleted, expense auto-deleted
```

**Step 3:** Verify Commission Details Updated
```
Payroll → Commission Details
Find: The commission you paid
Check: paid_amount should be back to 0 or showing "Pending" status
```

**Step 4:** Check Logs
```bash
tail -100 /tmp/flask.log | grep -i "deleting commission\|reverted\|====="
```

Should show something like:
```
===== DELETING COMMISSION PAYMENT SALARY <id> =====
Commission details type: <list>, content: [{'commission_id': 'xxx', ...}]
Processing 1 commission details
Commission ID: xxx
Reverting commission xxx
✓ Reverted commission xxx
===== REVERTED 1 COMMISSIONS =====
```

---

### Test 2: Delete Commission Payment from Expenses

**Step 1:** Create a commission payment
```
Payroll → Commission Details → "Mark as Paid"
Note which commission
```

**Step 2:** Go to Expenses and Delete
```
Financial → Expenses
Find: "Commission - ..." expense
Delete: Click delete
Result: Expense deleted, salary auto-deleted
```

**Step 3:** Verify Commission Details
```
Payroll → Commission Details
Find: The commission you deleted
Check: Should show 0 paid, status = Pending
```

**Step 4:** Check Logs
```bash
tail -100 /tmp/flask.log | grep -i "deleting commission\|reverted"
```

Should show:
```
===== DELETING COMMISSION PAYMENT EXPENSE <id> =====
Commission payment details: [...]
Processing 1 commissions from details
Commission xxx: reverting payment
✓ Reverted commission xxx
```

---

### Test 3: Multi-Project Commission Payment Delete

**Step 1:** Create multi-project payment
```
Payroll → Commission Details → "Add Commission Payment"
Enter: $500 amount (covers multiple projects)
Select: 2-3 pending commissions
Click: "Add Payment"
```

**Step 2:** Delete from Payroll
```
Payroll → Salaries
Find: Commission salary with "Commission - [Salesperson]"
Delete: Click delete
```

**Step 3:** Verify All Commissions Reverted
```
Payroll → Commission Details
Check: All commissions that were in the payment should show:
  - paid_amount: 0
  - status: Pending
  - paid_at: empty
```

**Step 4:** Check Logs
```bash
tail -100 /tmp/flask.log | grep -i "processing.*commission"
```

Should show:
```
===== DELETING COMMISSION PAYMENT SALARY <id> =====
Commission details type: <list>, content: [
  {'commission_id': 'comm1', ...},
  {'commission_id': 'comm2', ...},
  {'commission_id': 'comm3', ...}
]
Processing 3 commission details
  Commission comm1: reverting payment of $200.00
  ✓ Reverted commission comm1
  Commission comm2: reverting payment of $200.00
  ✓ Reverted commission comm2
  Commission comm3: reverting payment of $100.00
  ✓ Reverted commission comm3
===== REVERTED 3 COMMISSIONS =====
```

---

## 🔍 Debugging If It's Not Working

### Issue: Commissions not reverting to Pending

**Check 1: Are commission_payment_details being stored?**
```bash
# Look for these in logs when CREATING payment:
tail -50 /tmp/flask.log | grep -i "commission.*detail\|Add Commission Payment"

# Should show commission_payment_details being set
```

**Check 2: Does the salary have commission_id or commission_payment_details?**
```
In Firebase Console:
/balance_sheet_salary/{salary_id}

Should have:
- "salary_type": "Commission"
- "is_commission": true
- "commission_id": "..." OR
- "commission_payment_details": [...]
```

**Check 3: Are commissions in Firebase?**
```
In Firebase Console:
/project_commissions/{commission_id}

Should have:
- "paid_amount": > 0 (before deletion)
- "paid_at": "2026-08-28" (before deletion)
- "status": "Paid (Fully Covered)" or has amount paid
```

**Check 4: Run the delete and check logs in detail**
```bash
# Right before deleting, clear the log:
> /tmp/flask.log

# Delete the commission payment

# Check logs:
tail -50 /tmp/flask.log

# Look for:
✓ "===== DELETING COMMISSION PAYMENT"
✓ "Processing X commission details"
✓ "Reverting commission"
✓ "===== REVERTED X COMMISSIONS ====="
```

### If "Processing 0 commission details":

**Problem:** commission_payment_details not stored or empty

**Solutions:**
1. Verify commission_payment_details is being set when creating payment (see logs from creation)
2. Check Firebase to see actual structure
3. Check if it's being stored as array or JSON string

### If "Commission <id> not found":

**Problem:** Commission ID doesn't exist or is invalid

**Solutions:**
1. Verify commission_id format in commission_payment_details
2. Check if commission record exists in /project_commissions/{id}
3. Verify commission_id was captured correctly when payment created

---

## 📋 Log Analysis Checklist

When testing deletion, look for:

- [ ] `===== DELETING COMMISSION PAYMENT` message
- [ ] Commission details list shows correctly
- [ ] `Processing X commission details` shows correct count
- [ ] Each commission gets "Reverting" message
- [ ] Each commission gets "✓ Reverted" success message
- [ ] `===== REVERTED X COMMISSIONS =====` message
- [ ] No error or warning messages

---

## 💡 What Gets Reverted

When commission payment is deleted:

| Field | Before Delete | After Delete |
|-------|---------------|--------------|
| `paid_amount` | e.g., 200.00 | 0 |
| `paid_at` | 2026-08-28 | null/"" |
| `last_payment_date` | 2026-08-28 | null |
| `status` | "Paid (Fully Covered)" or with amount | "Pending" |
| `updated_at` | old timestamp | new timestamp |
| `updated_by` | old user | deleting user |

---

## 🔄 Commission Details Display

After deletion, Commission Details should show:

**For single commission that was paid:**
```
PAID AMOUNT: $0.00
REMAINING DUE: $[commission_amount]
STATUS: Pending (yellow badge)
No date shown (paid_at is empty)
```

**For partial payment scenario:**
If commission was for $500 and paid $200, after deletion:
```
PAID AMOUNT: $0.00 (back from $200)
REMAINING DUE: $500.00 (back to full amount)
STATUS: Pending
```

---

## 📞 If Still Not Working

Please provide:

1. **Commission ID:** From Commission Details page
2. **Salary ID:** From Payroll Salaries page
3. **Expense ID:** From Finance Expenses page
4. **Full log output:**
   ```bash
   tail -200 /tmp/flask.log > /tmp/commission_delete_log.txt
   # Share the log file content
   ```
5. **Firebase Console:**
   - Screenshot of `/project_commissions/{commission_id}` before/after delete
   - Screenshot of salary record showing commission_payment_details

This will help identify exactly where the revert is failing.

---

## 📝 Expected Flow

```
Mark as Paid in Commission Details
  ↓
Creates Salary Record (salary_type: Commission, is_commission: true)
  ↓
Creates Expense Record (is_commission: true, category: Payroll)
  ↓
Updates Commission Record (paid_amount: X, status: Paid)

--- Delete from Payroll Salaries ---
  ↓
Reads Salary Record (gets commission_payment_details)
  ↓
For each commission in details:
    - Gets current commission record
    - Reverts: paid_amount = 0, status = Pending, paid_at = null
  ↓
Deletes Expense Record (auto cascade)
  ↓
Commission Details page shows Pending status ✓
```

---

## ✅ Verification Commands

Quick check after deletion:

```bash
# Show recent deletion logs
tail -50 /tmp/flask.log | grep -A 20 "DELETING COMMISSION"

# Count successful reverts
tail -100 /tmp/flask.log | grep "✓ Reverted" | wc -l

# Check for any errors
tail -100 /tmp/flask.log | grep "✗\|Error\|Exception" | grep -i commission
```

All set! Test and let me know if commissions aren't reverting properly. 🚀
