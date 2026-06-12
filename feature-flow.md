# SiteMan — Feature and user Flow

> Source: `dfd-process-list.md` (Level 2). Each Level 2 process = one feature, with its flow and implementation detail.
> Cross-cutting rules apply everywhere:
> - **Tenant isolation** — every query is filtered by the requesting user's `company_id`.
> - **Audit** — every financial/locked write (P7, P8, P10, P11, P12, P13, P15) also writes an audit record (who, when, before/after).
> - **Locking** — records dated on or before the labour's last work-session end date are locked; they can only change through an update request (P15).

---

## P1 — Manage Authentication

### P1.1 — Login
- User gives phone number and password.
- System validates BD phone number (normalize to `+8801XXXXXXXXX`, reject invalid operator codes).
- System verifies password against the user account; account must be active and company must be active.
- System sends an OTP to this phone number via SMS (6-digit, short expiry, limited attempts).
- User submits the OTP to complete login.
- On success system issues JWT access + refresh tokens (token carries `user_id`, `company_id`, role).
- Resend OTP: allowed after a cooldown, limited number of resends per hour.

### P1.2 — Register
- Visitor provides name, phone_number, email, company detail, and password.
- System validates BD phone_number and checks it is not already registered.
- System sends an OTP to this phone number; user completes registration by providing the OTP.
- On OTP success, inside one database transaction:
  1. System creates the Company using the company detail.
  2. System creates the user account under this company.
  3. System assigns this user to the **Company Admin** group.
- User can now log in; new company starts on the **Free plan** (up to 1 open site).

### P1.3 — Reset forgotten password
- User gives registered phone number.
- System validates the phone number and confirms an account exists (without leaking which numbers exist).
- System sends OTP via SMS; user verifies OTP.
- On success user sets a new password; all existing refresh tokens are invalidated.

### P1.4 — Change password
- Logged-in user provides current password + new password.
- System verifies current password, applies password rules, saves new password.
- Other active sessions are logged out (refresh tokens blacklisted).

### P1.5 — Logout
- User triggers logout; system blacklists the refresh token.
- Client discards both tokens.

---

## P2 — Manage Company

### P2.1 — Create company
- Not a user-facing form — runs inside registration (P1.2).
- Creates Company record (name, active flag, billing fields); registrant becomes Company Admin.

### P2.2 — View company profile & status
- Company Admin opens company page.
- Shows name, active status, open site count, current plan, and subscription validity.

### P2.3 — Edit company details
- Company Admin edits company name and profile fields.
- System saves and records the change in the audit trail.

---

## P3 — Manage Company Subscription

Plan tiers cap open site count: **Free** (1), **Basic** (5), **Popular** (10), **Business** (20), **Custom** (20+, negotiated). Durations: 1 / 6 / 12 months, longer = per-month discount.

### P3.1 — View subscription status
- Company Admin sees current plan, open-site limit vs current usage, expiry date, payment history.

### P3.2 — Pay for plan
- Admin picks a plan tier and duration (1 / 6 / 12 months).
- System computes the price from the plan's per-month rate × duration (rate snapshot stored).
- Admin starts payment → system creates a payment attempt and redirects to the payment gateway.
- Gateway sends confirmation (IPN/webhook); system verifies signature and amount.
- On success: subscription record saved (plan, duration, amount, transaction id), `paid_until` extended from the activation date.
- On failure/cancel: nothing changes; user can retry.

### P3.3 — Renew plan
- Admin can renew plan at any time

### P3.4 — Upgrade plan
- **Before expiry:** remaining value of the current plan is calculated (unused days × current per-day rate) and adjusted against the new plan cost; pay the difference.
- **After expiry:** plain purchase of any higher plan.

### P3.5 — Downgrade plan
- **Before expiry:** not allowed — must wait until the current plan expires.
- **After expiry:** system checks current open site count against the target plan limit:
  - Within limit → downgrade proceeds.
  - Exceeds limit → admin is prompted to close the excess sites or stay on the current plan.

### P3.6 — Disable write access on expiry
- Middleware checks subscription validity on every request.
- Expired → write access to all sites is disabled (read-only); admin gets an alert to renew.

### P3.7 — Send renewal reminders
- Scheduled job sends SMS/notification before expiry and again after expiry.
- Reminder log kept so the same reminder is not repeated.

---

## P4 — Manage Company Users

### P4.1 — Create Staff user
- Company Admin provides name, BD phone number, password role, permitted sites.
- System validates BD phone_number and checks it is not already registered.
- System sends an OTP to this phone number; admin completes registration by providing the OTP.
- System will creates user under the same company.
- If provide role and permitted sites then Assign this user to that group and permitted sites.
> Lately this staff user will login using this phone_number and password. and can change the password. There is no security concern about account missused by admin. Because, admin need the otp to register or login staff user account. But, otp will send to this user phone_number. So, Account owner only can login. Admin just has activate, deactivate, role management, permission management and delete this account autority.

### P4.2 — Assign role to user
- Admin picks a role (Company Admin / Company Manager / Site Manager) → user added to that group.
- Role change takes effect on next request (permissions read from group).

### P4.3 — Assign user to sites
- Admin assigns user to one or more sites (user–site link records).
- Site-scoped actions check this assignment: managers only act on assigned sites.

### P4.4 — Assign permissions to user
- Admin grants/revokes fine-grained permissions on top of the role defaults.

### P4.5 — Activate / deactivate user
- Deactivated user cannot log in; existing tokens stop working.
- Reactivation restores access; history is untouched.

### P4.6 — Delete user
- Allowed only if the user has no created records.

### P4.7 — View and search users
- List company users with filters: role, site, active status; search by name/phone.

---



## P5 — Manage Sites

### P5.1 — Create / edit site
- Admin provides site name (and detail fields). New site starts open + active.
- System validates open site count against the active plan limit before creating; at the limit → creation blocked with an upgrade prompt (P3.4).

### P5.2 — Activate & Deactivate site
- Deactivate: 
  - Sets `is_active = False`
  - No new attendance/cash/cost/bill entries; old data stays readable; reversible any time.
  - Users & labourer is not consider with that. They are relvent with company.
- Activate:
  - Sets `is_active = True`; new data entry allowed again.

### P5.3 — Close site permanently
- Admin confirms closure → `is_closed = True`.
- company users lose access to this site's data
- Data may later be deleted or used for research by system users. Irreversible from the company side.

### P5.4 — Delete site
- Allowed only when the site has no financial records; otherwise must close instead.

### P5.5 — Assign users to site
- Admin links users to the site.

### P5.6 — View company sites
- Admin sees all sites; othere users see only assigned sites. Filters: open/closed, active/inactive.

### P5.7 — View site Report
- Shows current balance = total cash - total cost
- Shows site revenew
- Show site total attendence count
- Show site total cost
- Show site Labour Payment

### P5.8 — Create site billing & expense category
- Admin defines category names used by cost (P11) and bill (P13) entries, optionally per floor.
- Category list feeds dropdowns at entry time and grouping in reports.

---




## P6 — Manage Labour Accounts

### P6.1 — Create / edit labourer
- Manager (with site permission) provides name, daily salary, site.
- System check name uniqeness
- Labour starts active, assigned to that site.

### P6.2 — Assign labourer to site
- Sets or change the labour's current site.
- Previous site manager no longer create new record against this labour.
- Now new site manager has autority to create new record for this labour

### P6.3 — Activate / deactivate labour account
- Inactive labour: no new attendance, no new payments; history stays.
- Reactivation allowed any time.

### P6.4 — Update labour salary for a date range
- New salary takes effect for a date range; range must start after the last session end date (locked period cannot be re-priced).
- Attendance records snapshot the salary at entry time, so past earnings stay correct.

### P6.6 — View and search labourers
- Filter by site, active status; search by name. Shows current site, salary, balance.

### P6.7 — Delete labour account
- Allowed only when the labour has no attendance/payment records; otherwise Balance is zero.
- All of his record stays with null labour id. Kind of unknown labour.

---




## P7 — Manage Labour Payment

### P7.1 — Issue labour payment
- Manager picks labour, enters amount, type, note, date.
- Blocked if labour is inactive.
- Saves payment with running totals: `labour_total` (labour's cumulative payments) and `site_total` (site's cumulative labour payments) computed from the previous row.

### P7.2 — Track labour balance
- Balance = total earnings (from attendance) − total payments + total returns.
- Read from the latest running totals — no full scan needed.

### P7.3 — View labour payment history
- Ledger view per labour or per site, ordered by date; each row shows amount + running totals.




---

## P8 — Manage Labour Payment Return

### P8.1 — Record labour return
- Labour may return overpaid money. Manager will create labour return with amount,notes
- Same lock rule as payments.

### P8.2 — View return history
- Ledger of returns per labour/site.

---

## P9 — Manage Labour Worksession

### P9.1 — Create work session
- A labour may work continuously across different sites by moving from one site to another. After a while, a labour can go on vacation. The **period** from the **first record** after returning from vacation to the **next vacation date** is considered a Work Session.
- A Work Session only keeps the start date (the date of the first record — labour payment or attendance — after returning from vacation) and end date (the next vacation date).
- Later, based on this date range, it should be possible to show a specific work session's total attendance, total payments taken, and total work and payments broken down by site, etc.
- After a work session is closed, the labour's account will be deactivated.
- After returning from vacation, the account must be activated first before creating any records.

### P9.2 — View work session history
- Timeline of sessions per labour: site, start, end, duration.

---

## P10 — Manage Daily Attendance

### P10.1 — Record daily attendance
- Site Manager picks date, marks labour present (full/half/overtime units) and any extra amount, mark floor.
- Validations: labour active and assigned to this site, site active, one record per labour per date, date inside the last worksession end date to today date and.
- Row stores salary snapshot and running totals: labour present-days, labour extra, labour earnings; site present, site extra, site labour total.
> **allow create today and yesterday date record**. This rules also applied for other entity where need date field not created_at field. such as- site expense, site cash, Site other expense etc

### P10.2 — View attendance history
- Filter by labour, site, or date range; shows daily rows + running totals.

---

## P11 — Manage Site Expense

### P11.1 — Record site construction cost
- Manager enters site, date, floor, amount, note.
- Row computes running `site_total` and `floor_total` from the previous cost row.

### P11.2 — Record other cost
- Same shape as construction cost but a separate record type — kept apart so permissions can differ.
- It is not paid from site cash, it is directly paid from company admin.
- It will use to calculate revenuew of a site, not for balance calculation.

### P11.3 — Track and categorise costs
- Costs grouped by site / floor / type; totals come from running fields, detail from grouping.

### P11.4 — View cost history
- Ledger per site, filterable by floor, category, date range.

---

## P12 — Manage Site Cash

### P12.1 — Record cash deposit
- Manager records incoming cash with notes
- Running site cash total increases.

### P12.2 — Record cash return 
- Outgoing cash: return to owner or other source with note. This is not site cost, kind of withdraw.
- Cannot go below zero — insufficient balance is rejected.
- Running site return total increases.

### P12.3 — View site cash history
- Passbook view: date, type, note, amount (±), running balance per row.

---

## P13 — Manage Site Bills

### P13.1 — Create site bill
- Manager records revenue: site, date, category, floor, amount, note.
- Running `site_total` and `floor_total` per bill row. Feeds profit: `bills − (labour cost + site cost + other cost)`.

### P13.2 — View bill history
- Ledger per site, filterable by floor, category, date range.

---

## P14 — Generate Reports

All reports are tenant-scoped and respect site assignments (managers see only their sites).

### P14.1 — Labour balance report
- Per labour: earnings, payments, returns, net balance. Read from latest running totals.

### P14.2 — Site expense report
- Costs grouped by category/floor for a site and date range (construction + other shown separately).

### P14.3 — Site balance report
- `last cash total − (cost total + labour payment total)` per site — current spendable cash position.

### P14.4 — Site revenue report
- Bills total per site/date range; with cost data gives profit.

### P14.5 — Site labour cost report
- Attendance earnings aggregated per site (and per floor where recorded).

### P14.6 — Summary for a date range
- Company-level roll-up between two dates: cash in/out, costs, bills, labour cost, per-site rows.

### P14.7 — Company dashboard
- Open sites overview, balances, subscription expiry alert, pending update requests, pending transfers, recent activity.

---

## P15 — Handle Update Requests & Approvals

### P15.1 — Raise update request
- Site Manager selects any locked record (attendance, payment, cash, cost, bill), proposes new values + reason.
- Stored as a generic request (points at target record type + id, proposed changes, status `pending`).

### P15.2 — Approve / reject request
- Company Manager/Admin of that site reviews; approves or rejects with a note.

### P15.3 — Apply approved change
- On approval, in one transaction: target record updated, then all later rows in the same ledger get their running totals recalculated (totals chain stays consistent).
- Audit records written for the change.

### P15.4 — View request status and history
- Requester sees own requests; approvers see pending queue per site; full history kept.

---

## P16 — Manage Platform

System-level users; not tied to any company.

### P16.1 — System user login
- Separate login for platform staff (no company context); same OTP + JWT pattern.

### P16.2 — View and search all companies
- List with open site count, billing status, activity.

### P16.3 — Activate / deactivate a company
- Deactivated company: all its users blocked from login; data retained.

### P16.4 — Manage subscription plans
- System Admin creates/edits plan tiers: open-site limit, per-month rate per duration (1/6/12 months).
- Price changes apply to new purchases/renewals only; running subscriptions keep their rate snapshot.
- Custom plan: limit and price negotiated and set manually per company.

### P16.5 — Monitor subscription status
- Dashboard of all companies: plan, active / expiring soon / expired, revenue summary.

### P16.6 — Create system users
- System Admin creates platform staff accounts.

### P16.7 — Assign system roles
- System Admin assigns staff to system-level groups (System Admin / System Manager).

### P16.8 — Assign system-level permissions
- Fine-grained platform permissions per staff user (e.g., System Manager: monitor only).
