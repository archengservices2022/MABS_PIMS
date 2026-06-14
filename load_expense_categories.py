#!/usr/bin/env python3
"""
Load expense types, categories, and expense names from desktop software into Firebase
"""
import sys
sys.path.insert(0, 'web_app')

from app import fb_ref

# Expense types
expense_types = [
    "O & M (Operations & Maintenance)",
    "Capital Expenses",
    "Other Expenses"
]

# Categories organized by expense type
categories_by_type = {
    "O & M (Operations & Maintenance)": [
        "Facilities & Utilities",
        "Office & Admin Overhead",
        "Engineering Software & IT",
        "Salaries, Labor & Related Costs",
        "Professional Services",
        "Insurance & Compliance",
        "Travel, Site Visits & Vehicles",
        "Marketing & Business Development",
        "Training, Licensure & Development",
        "Safety & Field Supplies",
        "Miscellaneous O & M"
    ],
    "Capital Expenses": [
        "Computer & Office Equipment",
        "Field & Inspection Equipment",
        "Furniture & Fixtures",
        "Vehicles",
        "Software (Capitalized)",
        "Leasehold Improvements",
        "Accumulated Depreciation"
    ],
    "Other Expenses": [
        "Other",
        "Salary/Bonuses",
        "Tax Expenses/Tax Deductions",
        "Medical/Benefits",
        "Meals & Entertainment",
        "Donations",
        "Bank Charges",
        "Contingency Funds",
        "Unexpected Costs"
    ]
}

# Expense names organized by category
expense_names_by_category = {
    "Other": [],
    "Facilities & Utilities": [
        "Office rent or co-working space fees",
        "Utilities (electricity, water, gas)",
        "Internet service",
        "Trash & cleaning services",
        "Property taxes (for office, if applicable)",
        "Office repairs & maintenance (HVAC, lights, minor repairs)"
    ],
    "Office & Admin Overhead": [
        "Office supplies (paper, pens, notebooks, printer ink)",
        "Printer/plotter maintenance & paper",
        "Postage & shipping (documents, contracts, samples)",
        "Bank fees & merchant processing fees",
        "Software: Microsoft 365 / Google Workspace",
        "Software: PDF tools (Bluebeam, Adobe, etc.)",
        "Software: Password manager",
        "Software: Others",
        "Cloud storage (Dropbox, Google Drive, OneDrive)"
    ],
    "Engineering Software & IT": [
        "Engineering software: SAP2000 / ETABS / STAAD / RAM / RISA",
        "Engineering software: Others",
        "CAD/BIM tools: AutoCAD, Civil 3D, Revit",
        "License/maintenance fees for all software",
        "IT support services",
        "Computer maintenance & small repairs",
        "Antivirus, backup services, security tools"
    ],
    "Salaries, Labor & Related Costs": [
        "Owner draw/salary",
        "Employee salaries & wages",
        "Overtime or temporary staff",
        "Payroll taxes paid by the company",
        "Employee benefits: Health insurance",
        "Employee benefits: Retirement plan contributions",
        "Employee benefits: Paid time off costs",
        "Payments to subcontract engineers, drafters"
    ],
    "Professional Services": [
        "Accounting & bookkeeping fees",
        "Tax preparation and consulting",
        "Legal services (contracts, company setup)",
        "Business consulting or coaching services",
        "Registered agent fees (if applicable)"
    ],
    "Insurance & Compliance": [
        "Professional liability / Errors & Omissions (E&O) insurance",
        "General liability insurance",
        "Business owner's policy (BOP)",
        "Workers' comp insurance",
        "Commercial auto insurance",
        "License renewals (PE license, SE license)",
        "Business license renewals",
        "Memberships"
    ],
    "Travel, Site Visits & Vehicles": [
        "Mileage (personal vehicle for business)",
        "Fuel costs (company vehicles)",
        "Parking fees & tolls",
        "Vehicle maintenance",
        "Airfare, hotels for out-of-town site visits",
        "Rental cars or rideshare for business trips",
        "Meals while traveling for business"
    ],
    "Marketing & Business Development": [
        "Website hosting and domain expenses",
        "Website maintenance & updates",
        "Graphic design (logo, templates, brochures)",
        "Online ads (Google, LinkedIn, Facebook)",
        "Printing of business cards, brochures, banners",
        "Sponsorships of events",
        "Client entertainment (dinners, coffee meetings)"
    ],
    "Training, Licensure & Development": [
        "Continuing education (PDH hours, webinars)",
        "Training courses (technical or business)",
        "Books, codes, and standards",
        "Exam fees for additional licenses"
    ],
    "Safety & Field Supplies": [
        "PPE: hard hats, safety vests, glasses, gloves, boots",
        "Field tools for inspections",
        "Calibration of field instruments",
        "First-aid kits and safety equipment"
    ],
    "Miscellaneous O & M": [
        "Subscriptions: LinkedIn Premium",
        "Subscriptions: Industry journals",
        "Project management tools",
        "Document management tools or e-signature services"
    ],
    "Computer & Office Equipment": [
        "Laptops",
        "Desktops",
        "Monitors",
        "Printers/Scanners",
        "Servers",
        "Networking Equipment"
    ],
    "Field & Inspection Equipment": [
        "Survey Equipment",
        "Testing Equipment",
        "Measurement Tools",
        "Safety Equipment",
        "Inspection Devices"
    ],
    "Furniture & Fixtures": [
        "Office Desks",
        "Chairs",
        "Filing Cabinets",
        "Shelving Units",
        "Conference Room Furniture"
    ],
    "Vehicles": [
        "Company Cars",
        "Trucks",
        "Vans",
        "Heavy Equipment",
        "Vehicle Accessories"
    ],
    "Software (Capitalized)": [
        "Engineering Software License",
        "ERP System",
        "CRM System",
        "Database Software",
        "Custom Software Development"
    ],
    "Leasehold Improvements": [
        "Office Renovations",
        "Electrical Work",
        "Plumbing Improvements",
        "HVAC Installation",
        "Security Systems"
    ],
    "Accumulated Depreciation": [
        "Depreciation Expense - Computers",
        "Depreciation Expense - Office Equipment",
        "Depreciation Expense - Vehicles",
        "Accumulated Depreciation"
    ],
    "Salary/Bonuses": [
        "Employee Salary",
        "Manager Salary",
        "Executive Salary",
        "Performance Bonus",
        "Year-end Bonus",
        "Commission Payments",
        "Incentive Payments"
    ],
    "Tax Expenses/Tax Deductions": [
        "Federal Income Tax",
        "Tax Deduction",
        "Payroll Tax",
        "Sales Tax",
        "Property Tax",
        "Business Tax"
    ],
    "Medical/Benefits": [
        "Health Insurance Premiums",
        "Dental Insurance",
        "Vision Insurance",
        "Retirement Contributions",
        "Life Insurance",
        "Disability Insurance",
        "Wellness Programs"
    ],
    "Meals & Entertainment": [
        "Client Meals",
        "Business Lunches",
        "Team Dinners",
        "Conference Meals",
        "Entertainment Expenses",
        "Team Building Events"
    ],
    "Donations": [
        "Charitable Donations",
        "Community Sponsorships",
        "Educational Donations",
        "Non-profit Contributions",
        "Event Sponsorships"
    ],
    "Bank Charges": [
        "Monthly Account Fees",
        "Transaction Fees",
        "Wire Transfer Fees",
        "Credit Card Processing Fees",
        "Check Printing Fees",
        "Overdraft Fees"
    ],
    "Contingency Funds": [
        "Emergency Funds",
        "Reserve Funds",
        "Project Contingency",
        "Operational Reserve",
        "Risk Management Fund"
    ],
    "Unexpected Costs": [
        "Emergency Repairs",
        "Unplanned Maintenance",
        "Price Increases",
        "Regulatory Changes",
        "Market Fluctuations"
    ]
}

print("Loading expense categories into Firebase...")

# Load expense types
print("  - Loading expense types...")
fb_ref("/custom_categories/expense_type").set(expense_types)

# Load categories by type
print("  - Loading categories...")
for exp_type, categories in categories_by_type.items():
    fb_ref(f"/custom_categories/Categories/{exp_type}").set(categories)

# Load expense names by category
print("  - Loading expense names...")
for category, names in expense_names_by_category.items():
    fb_ref(f"/custom_categories/expense_names/{category}").set(names)

print("\n[SUCCESS] All expense categories loaded successfully!")
print(f"\nSummary:")
print(f"  Expense Types: {len(expense_types)}")
print(f"  Categories: {sum(len(cats) for cats in categories_by_type.values())}")
print(f"  Expense Names: {sum(len(names) for names in expense_names_by_category.values())}")
