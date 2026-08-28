# Commission Date Sync - Quick Testing Guide

## 🎯 What Should Happen Now

### When you edit a commission expense date in Finance tab:
1. ✅ The date should update in the Expenses list
2. ✅ Go to Commission Details → the paid date should also update
3. ✅ Go to Payroll Salaries → the date should match

### When you edit a commission salary date in Payroll tab:
1. ✅ The date should update in the Salaries list  
2. ✅ Go to Commission Details → the paid date should also update
3. ✅ Go to Finance Expenses → the date should match

### When you TRY to edit commission amounts:
1. ✅ Get error: "Cannot edit amount: This is a commission payment..."
2. ✅ You can ONLY edit the date, not the amount

---

## 🧪 Test Procedure

### Step 1: Create a Commission Payment
**Location:** Payroll → Commission Details

**Action:**
- Pick a salesperson
- Click "Mark as Paid" on a project
- OR Click "Add Commission Payment" and enter amount + date
- Note the current date being used

**Example:**
- Salesperson: John Smith
- Project: MABS-202608001
- Amount: $1,000.00
- Date: 2026-08-28

---

### Step 2: Find the Commission in Expenses
**Location:** Financial → Expenses

**Look for:**
- Expense name like: "Commission - John Smith (MABS-202608001)"
- Amount: $1,000.00
- Date: 2026-08-28

---

### Step 3: Edit the Date in Expenses
**Action:**
- Click the expense to open it
- Click "Edit Expense" button
- Find the Date field
- Change date to something different (e.g., 2026-08-29)
- Click "Update Expense"
- You should see: "success" message

**Expected Result:**
- ✅ Expense date changes to 2026-08-29
- ✅ NO error message

---

### Step 4: Verify Sync in Commission Details
**Location:** Payroll → Commission Details

**Check:**
- Find the same commission project
- Look at the "PAID AMOUNT" row
- Should show the NEW date: 2026-08-29 ✅

**If NOT synced:**
- Refresh the page (F5 or Ctrl+R)
- Check again

---

### Step 5: Test Amount Edit Protection
**Location:** Financial → Expenses

**Action:**
- Open the same commission expense
- Click "Edit Expense"
- Try to change the Amount field
- Click "Update Expense"

**Expected Result:**
- ✅ Get error message: "Cannot edit amount: This is a commission payment..."
- ✅ Update should FAIL
- ✅ Amount should NOT change

---

### Step 6: Test Salary Date Sync
**Location:** Payroll → Salaries

**Find:**
- Look for salary record matching the commission
- Name: "Commission" or employee name

**Action:**
- Click to edit
- Change the date (e.g., 2026-08-30)
- Click "Update Salary"

**Expected Result:**
- ✅ Salary date changes to 2026-08-30
- ✅ Back in Commission Details, paid date should also be 2026-08-30 ✅

---

## 🔍 Troubleshooting

### Dates Not Syncing?

**Check these:**

1. **Is the expense tagged as a commission?**
   - Expense name should include "Commission"
   - Category should be "Payroll"

2. **Are you refreshing the page?**
   - Changes might not show until page refresh
   - Press F5 or Ctrl+R

3. **Check the Flask logs:**
   ```bash
   tail -f /tmp/flask.log | grep -i "commission"
   ```
   
   Should see:
   ```
   Commission sync check: old_date='2026-08-28', new_date='2026-08-29'
   Syncing date to single commission: ...
   ```

4. **Is commission_id set?**
   - In Firebase Console, check `/balance_sheet_expenses/{expense_id}`
   - Should have field: `"commission_id": "..."`
   - Should have field: `"is_commission": true`

---

## 📋 Test Results Checklist

Use this to verify everything works:

- [ ] Can mark commission as paid in Commission Details
- [ ] Commission expense appears in Finance tab
- [ ] Can edit expense date without error
- [ ] After edit, commission details date updates
- [ ] Attempt to edit expense amount gives error
- [ ] Can edit salary date
- [ ] After salary edit, commission date updates
- [ ] Multi-project payments work (multiple commissions paid together)
- [ ] Date format is consistent (YYYY-MM-DD)
- [ ] All three tabs show same dates (Commission, Expenses, Salaries)

---

## 🐛 If Something Breaks

**Report these details:**

1. **What exactly happened?**
   - Did you change a date in Expense or Salary?
   - Did you try to change an amount?

2. **What date format did you use?**
   - YYYY-MM-DD (2026-08-28)
   - MM/DD/YYYY (08/28/2026)
   - Other?

3. **Show the error message** (if any)
   - Copy the exact text

4. **Check the logs:**
   ```bash
   tail -50 /tmp/flask.log
   ```
   - Look for any ERROR or WARNING lines
   - Look for commission sync messages

5. **Firebase data:**
   - In Firebase Console, check if commission record updated
   - Path: `/project_commissions/{commission_id}`
   - Field: `paid_at` should show new date

---

## ✅ Success Signs

When everything is working:

1. **Editing expense date:**
   - Form submits successfully
   - Page shows updated date
   - Commission Details shows matching date

2. **Editing salary date:**
   - Form submits successfully  
   - Page shows updated date
   - Commission Details shows matching date

3. **Trying to edit amount:**
   - See error message
   - Edit is blocked
   - Amount doesn't change

4. **Logs show:**
   - "Commission sync check" message
   - "Syncing date to" message
   - No ERROR messages

---

## 📞 Questions?

Check these files for detailed info:

1. `COMMISSION_PAYMENT_CHANGES.md` - Technical overview
2. `COMMISSION_IMPLEMENTATION_REPORT.md` - Detailed implementation
3. `COMMISSION_SYNC_DEBUG.md` - Debugging guide
4. `COMMISSION_SYNC_VERIFICATION.md` - Complete verification checklist
