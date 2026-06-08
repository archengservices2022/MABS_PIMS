# Update Process

## Priority

1. Keep `data/settings.json` private. It contains local company settings and user password hashes.
2. Keep Firebase service account keys outside the project, for example `C:\Users\skota\.mabs\servicekey.json`.
3. Build the app executable with the correct `.spec` file.
4. Generate SHA-256 checksum files for every executable uploaded to a release.
5. Upload the app executable, updater executable, and matching checksum files to GitHub Releases.
6. Test the in-app updater from an installed copy before sharing the release.

## Development Checklist - May 1

These app logic items should be completed before preparing a release. The order below is the recommended implementation order because later items depend on earlier data fields being consistent.

### Project Payment Model

1. Define one payment model for each project with separate fields for payment category, payment status, down payment percentage, down payment amount, due amount, paid amount, received date, and completion status.
2. Keep payment category and payment status independent. When payment status changes, the payment category should not be overwritten.
3. Incorporate advance, regular, due payment, and final completion into the same project record so duplicate project records are not created.
4. Add net 30 handling in the Add Project dialog due payment flow.
5. In the Add Project dialog, automatically calculate due payment from the down payment percentage and total amount.

### Project Timeline Logic

1. Add close start date and end date timeline fields in Add Project.
2. Count only weekdays for project timelines, excluding Saturday and Sunday.
3. Automatically calculate project dates after the start date is entered, and keep the timeline values in one row.

### Project Dashboard

1. Update the project dashboard to show payment status, due amount, paid amount, and received date.
2. Show only projects from the last 30 days on the project dashboard by default.
3. Sort out plant initials, for example USA state initials like AZ, ID, and FL.

### Invoice Logic

1. Restore invoice add, remove, and edit actions to the previous invoice tab instead of doing them only in Invoice History.
2. Link invoice payment status with received date.
3. Prevent duplicate project invoices. If Load to Invoice is clicked twice for the same project, show a warning such as `MABS202604112 has already been created`.

### Balance Sheet Logic

1. When an invoice status changes to partial payment, paid, or down payment, update each project's paid amount and received date in the balance sheet.
2. Do not show unpaid revenue in the balance sheet.

### Payment Assets

1. Fix the Zelle QR code display/use.

## For Users

1. Open the app.
2. Click the update button in the top-right corner.
3. If an update is available, click **Install Now**.
4. Wait for the download and checksum verification to finish.
5. The app will close and restart after the updater replaces the old executable.

## For Developers

### Before Release

1. Update the current version in `data/settings.json` under `github.current_version`.
2. Confirm `github.repo` points to the release repository.
3. Run the auth tests:

   ```powershell
   python -m unittest tests.test_auth_utils
   ```

4. Build the executable:

   ```powershell
   pyinstaller PIMS.spec
   ```

5. Build or provide the updater executable expected by `update_checker.py`.

### Release Assets

The latest GitHub release must include all of these files:

- `invoice.exe`
- `invoice.exe.sha256`
- `invoice_updater.exe`
- `invoice_updater.exe.sha256`

Generate checksum files with:

```powershell
Get-FileHash .\invoice.exe -Algorithm SHA256 | ForEach-Object { $_.Hash.ToLower() + "  invoice.exe" } | Set-Content .\invoice.exe.sha256
Get-FileHash .\invoice_updater.exe -Algorithm SHA256 | ForEach-Object { $_.Hash.ToLower() + "  invoice_updater.exe" } | Set-Content .\invoice_updater.exe.sha256
```

### Publish

1. Commit the code changes.
2. Create a version tag, for example:

   ```powershell
   git tag v1.3
   git push origin v1.3
   ```

3. Create or edit the GitHub release for that tag.
4. Upload the required release assets.
5. Test update installation from the previous version.

## Notes

- The updater verifies SHA-256 checksums before replacing executables.
- Passwords are stored as salted PBKDF2 hashes. Old SHA-256 password hashes are still accepted and upgraded after a successful login.
- Local data, logs, invoices, and secrets should stay out of version control.
