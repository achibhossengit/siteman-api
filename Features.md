# SiteMan — Feature List
Construction site labour and cost management for companies. Each company is an isolated tenant. The platform owner manages companies and their subscriptions.

---

## Platform Administration
1. System user login (separate from company users)
2. View and search all companies
3. Activate or deactivate a company
4. Monitor subscription status of all companies
5. Assign permissions to system managers

## Authentication & Account Access
1. User login with phone number and password
2. User registration that creates a new company automatically
3. Forgot password and password reset
4. Logout
5. Change password

## Subscription & Billing
1. View subscription status and validity
2. Online payment with gateway
3. Restrict access when subscription has expired
4. Renewal reminders

## Company Setup & Users
1. Create users under the company
2. Assign roles to users (Admin, Main Manager, Site Manager)
3. Assign users to one or more sites
4. Assign permissions to users
5. Activate or deactivate a user
6. View and search company users

## Site Management
1. Create and edit sites
2. Activate or deactivate a site
3. Assign managers to a site
4. View company sites (managers see only their sites)
5. Site detail page with balance and recent activity

## Labour Management
1. Create and edit labourers
2. Assign a labourer to a site
3. Move a labourer between sites (one site at a time)
4. Mark a labourer inactive
5. Update labour salary for a date range
6. View and search labourers by site or status

## Daily Attendance
1. Record daily attendance for a labourer
2. Record present days and extra amounts
3. View attendance history by labourer, site, or date

## Labour Payments
1. Issue a payment to a labourer at any time
2. Labour may return overpaid money
3. Track labour balance

## Work Sessions
1. After few days of working labour can go on vacation, so need to track this period when he start work, and when leave at this session


## Site Cash
1. Record cash deposits and money received
2. Record cash transfers and returns
3. Company owner may withdrawal from site
4. View site cash ledger `like a passbook`
5. Track site cash balance

## Inter-Site Cash Transfer
1. Request a cash transfer between two sites
2. Approve or reject a transfer request with a note
3. Automatically update both sites' balances on approval
4. View transfer history and status

## Site Costs & Bills
1. Record site construction costs
2. Record other costs (kept separate)
3. Record site bills and revenue
4. Track costs by site and by floor
5. View cost and bill ledger
6. Categories them based on site/floors

## Record Edits & Audit Log
1. Authorized users edit or delete records directly (no approval step)
2. System auto-logs every update/delete (who, when, before/after, note)
3. View the audit trail per record, site, user, or date
4. Admin can view and remove audit entries (never edit them)
5. Records dated within a closed work session are locked from edits

## Reports & Dashboard
1. Labour balance report
2. Site expense report
3. Site balance report
4. Site labour cost report
5. Summary for desire daterange
6. Company dashboard with site overview and alerts
7. Site and labour account statements

## Audit & Security
1. Record history of changes on financial records
2. Track who made each change and when
3. View audit trail
4. Keep each company's data fully isolated

---

## Core Workflow
1. A person registers and a new company is created automatically; that person becomes the company Admin.
2. The Admin creates users with different roles.
3. The Admin manages the company subscription.
4. Labourers, sites, and other records are created under the company.
5. Labourers are assigned to sites.
6. Daily attendance is recorded per labourer per site.
7. Daily earnings and expenses (cash, cost, bill) are recorded.
8. Labour payments can be issued at any time except is labour inactive.
9. A labourer may move between sites, one site at a time.
10. Labourers may become inactive.
11. The system generates site and labour account statements.

---

## Roles
- **System Admin** — manages all companies and subscriptions.
- **System Manager** — monitors subscriptions and payments (assigned permissions).
- **Company Admin** — full control of one company: users, sites, labour, subscription.
- **Company Manager** — manages assigned sites and reviews the audit trail for them.
- **Site Manager** — records attendance, cash, and cost for permitted sites; edits are logged.
