# SiteMan — Feature and user Flow

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
- System validates BD phone_number and checks it is not already registered (**phone is globally unique across the whole platform — one phone = one account**).
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

## P2 — Manage Platform

System-level users; not tied to any company.

### P2.1 — System user login
- Separate login for platform staff (no company context); same OTP + JWT pattern.

### P2.2 — View and search all companies
- List with open site count, billing status, activity, audit logs.

### P2.3 — Activate / deactivate a company
- Deactivated company: all its users blocked from login; data retained.

### P2.4 — Manage subscription plans
- System Admin creates/edits plan tiers: open-site limit, per-month rate per duration (1/6/12 months).
- Price changes apply to new purchases/renewals only; running subscriptions keep their rate snapshot.
- Custom plan: limit and price negotiated and set manually per company.

### P2.5 — Monitor subscription status
- Dashboard of all companies: plan, active / expiring soon / expired, revenue summary.

### P2.6 — Create system users
- System Admin creates platform staff accounts.

### P2.7 — Assign system roles
- System Admin assigns staff to system-level groups (System Admin / System Manager).

### P2.8 — Assign system-level permissions
- Fine-grained platform permissions per staff user (e.g., System Manager: monitor only).

---

## P3 — Manage Company

### P3.1 — Create company
- Not a user-facing form — runs inside registration (P1.2).
- Creates Company record (name, active flag, billing fields); registrant becomes Company Admin.

### P3.2 — View company profile & status
- Company Admin opens company page.
- Shows name, active status, open site count, current plan, and subscription validity.

### P3.3 — Edit company details
- Company Admin edits company name and profile fields.
- System saves and records the change in the audit trail.

### P3.4 — Manage expense categories
- Company-level master data: Admin creates/edits expense categories (name, display order, active flag).
- Shared by **all sites** of the company — every SiteCost (P12.1) and HiddenCost (P12.2) row references the same category set, so cross-site reporting stays consistent.
- Category cannot be deleted once referenced by any cost row → deactivate instead (hidden from new-entry dropdowns, old rows keep their link).

---

## P4 — Manage Company Subscription

Plan tiers cap open site count: **Free** (1), **Basic** (5), **Popular** (10), **Business** (20), **Custom** (20+, negotiated). Durations: 1 / 6 / 12 months, longer = per-month discount.

### P4.1 — View subscription status
- Company Admin sees current plan, open-site limit vs current usage, expiry date, payment history.

### P4.2 — Pay for plan
- Admin picks a plan tier and duration (1 / 6 / 12 months).
- System computes the price from the plan's per-month rate × duration (rate snapshot stored).
- Admin starts payment → system creates a payment attempt and redirects to the payment gateway.
- Gateway sends confirmation (IPN/webhook); system verifies signature and amount.
- On success: subscription record saved (plan, duration, amount, transaction id), `paid_until` extended from the activation date.
- On failure/cancel: nothing changes; user can retry.

### P4.3 — Renew plan
- Admin can renew plan at any time

### P4.4 — Upgrade plan
- **Before expiry:** remaining value of the current plan is calculated (unused days × current per-day rate) and adjusted against the new plan cost; pay the difference.
- **After expiry:** plain purchase of any higher plan.

### P4.5 — Downgrade plan
- **Before expiry:** not allowed — must wait until the current plan expires.
- **After expiry:** system checks current open site count against the target plan limit:
  - Within limit → downgrade proceeds.
  - Exceeds limit → admin is prompted to close the excess sites or stay on the current plan.

### P4.6 — Disable write access on expiry
- Middleware checks subscription validity on every request.
- Expired → write access to all sites is disabled (read-only); admin gets an alert to renew.

### P4.7 — Send renewal reminders
- Scheduled job sends SMS/notification before expiry and again after expiry.
- Reminder log kept so the same reminder is not repeated.

---

## P5 — Manage Company Users

### P5.1 — Create Staff user
- Company Admin provides name, BD phone number, password role, permitted sites.
- System validates BD phone_number and checks it is not already registered.
- System sends an OTP to this phone number; admin completes registration by providing the OTP.
- System will creates user under the same company.
- If provide role and permitted sites then Assign this user to that group and permitted sites.
> Lately this staff user will login using this phone_number and password. and can change the password. There is no security concern about account missused by admin. Because, admin need the otp to register or login staff user account. But, otp will send to this user phone_number. So, Account owner only can login. Admin just has activate, deactivate, role management, permission management and delete this account autority.

### P5.2 — Assign role to user
- Admin picks a role (Company Admin / Company Manager / Site Manager) → user added to that group.
- Role change takes effect on next request (permissions read from group).

### P5.3 — Assign user to sites
- Admin assigns user to one or more sites (user–site link records).
- Site-scoped actions check this assignment: managers only act on assigned sites.

### P5.4 — Assign permissions to user
- Admin grants/revokes fine-grained permissions on top of the role defaults.

### P5.5 — Activate / deactivate user
- Deactivated user cannot log in; existing tokens stop working.
- Reactivation restores access; history is untouched.

### P5.6 — Delete user
- **Not referenced by any entity** (no created records, no site assignments, not an actor on any audit entry) → hard delete allowed; the deletion itself is written to the audit log.
- **Referenced by any entity** → delete blocked; deactivate instead (P5.5).
- Implementation: FK references stay `NOT NULL` with `on_delete=PROTECT`; the DB itself enforces "no delete while referenced".

### P5.7 — View and search users
- List company users with filters: role, site, active status; search by name/phone.

---



## P6 — Manage Sites

### P6.1 — Create / edit site
- Admin provides site name (and detail fields). New site starts open + active.
- System validates open site count against the active plan limit before creating; at the limit → creation blocked with an upgrade prompt (P4.4).

### P6.2 — Activate & Deactivate site
- Deactivate: 
  - Sets `is_active = False`
  - No new attendance/cash/cost/bill entries; old data stays readable; reversible any time.
  - Users & labourer is not consider with that. They are relvent with company.
- Activate:
  - Sets `is_active = True`; new data entry allowed again.

### P6.3 — Close site permanently
- Admin confirms closure → `is_closed = True`.
- company users lose access to this site's data
- Data may later be deleted or used for research by system users. Irreversible from the company side.

### P6.4 — Delete site
- Allowed only when the site has no financial records; otherwise must close instead.

### P6.5 — Assign users to site
- Admin links users to the site.

### P6.6 — View company sites
- Admin sees all sites; othere users see only assigned sites. Filters: open/closed, active/inactive.

### P6.7 — View site Report
- Shows current cash balance = `deposits − returns − site cost − labour payments` (hidden cost excluded — paid by admin, not from the site box; see P12.2)
- Shows site revenew
- Show site total attendence count
- Show site total cost
- Show site Labour Payment
- Floor breakdown line: per-floor contract value, billed, cost and profit (detail in P15.8).

### P6.8 — Manage site floors
- Site-level master data: Admin defines the site's floors — name (e.g. Basement, Floor-1, Floor-2, Floor-2-Extra), display order (serial), measurement (`sqft`), and `rate_per_sqft`.
- Derived `contract_value = sqft × rate` is the floor's revenue target.
- Floor list feeds the floor dropdown on attendance (P11.1), site cost (P12.1), hidden cost (P12.2), and bill (P14.1) entries.
- Editable while the site is open; a floor cannot be deleted once any record references it.
- Expense categories are company-level (P3.4), not defined here.

### P6.9 — Deactivate/Activate site floors
- Floor may activate or deactivate. Deactivate means no new records allow to create under this floor execpt the SiteBill. But, historic data is accessable.

### P6.10 — Mark as done
- This floor work is done, no need new expense or work.
- Floor will deactivate
- To activate the floor again need to unmark as done first.

---




## P7 — Manage Labour Accounts

### P7.1 — Create / edit labourer
- Manager (with site permission) provides name, daily salary, site.
- System check name uniqeness
- Labour starts active, assigned to that site.

### P7.2 — Assign / move labourer to site
- Sets or changes the labour's current site (one site at a time — assigning to a new site **is** the move).
- Previous site manager no longer creates new records against this labour.
- New site manager now has authority to create new records for this labour.

### P7.3 — Activate / deactivate labour account
- Inactive labour: no new attendance, no new payments; history stays.
- Reactivation allowed any time.

### P7.4 — Update labour salary for a date range
- New salary takes effect for a date range; range must start after the last session end date (locked period cannot be re-priced).
- Attendance records snapshot the salary at entry time, so past earnings stay correct.

### P7.5 — View and search labourers
- Filter by site, active status; search by name. Shows current site, salary, balance.

### P7.6 — Delete labour account
- **No attendance / payment / return records** → hard delete allowed; the deletion is written to the audit log.
- **Referenced by any record** → delete blocked; deactivate instead (P7.3).
- Implementation: labour FK on ledger rows stays `NOT NULL` with `on_delete=PROTECT`; no orphan/null-labour rows.

---




## P8 — Manage Labour Payment

### P8.1 — Issue labour payment
- Manager picks labour, enters amount, type, note, date.
- Blocked if labour is inactive.
- Saves payment with running totals: `labour_total` (labour's cumulative payments) and `site_total` (site's cumulative labour payments) computed from the previous row.

### P8.2 — Track labour balance
- Balance = total earnings (from attendance) − total payments + total returns.
- Read from the latest running totals — no full scan needed.

### P8.3 — View labour payment history
- Ledger view per labour or per site, ordered by date; each row shows amount + running totals.




---

## P9 — Manage Labour Payment Return

### P9.1 — Record labour return
- Labour may return overpaid money. Manager will create labour return with amount,notes
- Same lock rule as payments.

### P9.2 — View return history
- Ledger of returns per labour/site.

---

## P10 — Manage Labour Worksession

### P10.1 — Create work session
- A labour may work continuously across different sites by moving from one site to another. After a while, a labour can go on vacation. The **period** from the **first record** after returning from vacation to the **next vacation date** is considered a Work Session.
- A Work Session only keeps the start date (the date of the first record — labour payment or attendance — after returning from vacation) and end date (the next vacation date).
- Later, based on this date range, it should be possible to show a specific work session's total attendance, total payments taken, and total work and payments broken down by site, etc.
- After a work session is closed, the labour's account will be deactivated.
- After returning from vacation, the account must be activated first before creating any records.

### P10.2 — View work session history
- Timeline of sessions per labour: site, start, end, duration.

---

## P11 — Manage Daily Attendance

### P11.1 — Record daily attendance
- Grain is **labour / floor / day**: Site Manager picks date, floor (from the site's floor list, P6.8), present units (full/half/overtime) and any extra amount.
- A labour may have **multiple attendance rows on the same day** when he works on different floors — uniqueness is **(labour, floor, date)**, not (labour, date).
- Floor is required so the earnings attribute to floor costing.
- Validations: labour active and assigned to this site, site active, one row per (labour, floor, date), date inside the last worksession end date → today.
- Row stores salary snapshot and running totals: labour present-days, labour extra, labour earnings; site present, site extra, site labour total. Earnings also roll up per floor.
> **allow create today and yesterday date record**. This rule also applies to other entities that use a date field (not created_at): site cost, hidden cost, site cash, etc.

### P11.2 — View attendance history
- Filter by labour, site, or date range; shows daily rows + running totals.

---

## P12 — Manage Site Expense

### P12.1 — Record site construction cost (SiteCost)
- Manager enters site, date, **floor (required)**, **expense category (company-level — P3.4)**, amount, note.
- Row computes running `site_total` and `floor_total` from the previous cost row.
- **Expense category is nullable**: null = "Generalized expense".

### P12.2 — Record hidden cost (HiddenCost)
- Separate record type from SiteCost — kept apart so permissions/visibility can differ ("hidden" from normal site views).
- It is not paid from site cash; it is paid directly by the company admin.
- It is used to calculate the **profit/revenue** of a site, not the cash balance.
- **Floor is nullable**: set → cost allocates to that floor; null → site-general (not tied to any floor).
- **Expense category is nullable**: null = "Generalized expense".

### P12.3 — View cost history
- Ledger per site, filterable by floor, expense category, record type (site cost / hidden cost), date range.

---

## P13 — Manage Site Cash

### P13.1 — Record cash deposit
- Manager records incoming cash with notes
- Running site cash total increases.

### P13.2 — Record cash return 
- Outgoing cash: return to owner or other source with note. This is not site cost, kind of withdraw.
- Cannot go below zero — insufficient balance is rejected.
- Running site return total increases.

### P13.3 — View site cash history
- Passbook view: date, type, note, amount (±), running balance per row.

---

## P14 — Manage Site Bills

### P14.1 — Create site bill
- Authorized user records Bill: site, date, **floor (required)**, amount, note.
- Running `site_total` and `floor_total` per bill row; floor bills accumulate against that floor's contract value (sqft × rate, P6.8).

### P14.2 — View bill history
- Ledger per site, filterable by floor, date range; shows billed vs floor contract value vs remaining receivable.

---

## P15 — Generate Reports

All reports are tenant-scoped and respect site assignments (managers see only their sites).

### P15.1 — Labour balance report
- Per labour: earnings, payments, returns, net balance. Read from latest running totals.

### P15.2 — Site expense report
- Costs grouped by company expense category / floor for a site and date range (SiteCost and HiddenCost shown separately).

### P15.3 — Site balance report
- `deposits − returns − site cost total − labour payment total` per site — current spendable cash (matches P6.7; hidden cost excluded).

### P15.4 — Site Profit report
- Profit per site: `bills − (labour cost + site cost + hidden cost)`.
- Profit Per floor of site: `bills of floor - (labour cost of floor + site cost of floor + hidden cost of floor)`

### P15.5 — Site labour cost report
- Labour payment per site per date
- Labour attendence per site per date per floor
- Labour extra per site per date per floor
- Labour cost per site: `latest dailyattendence site total`.
- Labour cost Per floor of site

### P15.6 — Summary for a date range
- Company-level roll-up between two dates: cash in/out, costs, bills, labour cost, per-site rows.
- Site lavel summary

### P15.7 — Company dashboard
- Open sites overview, balances, subscription expiry alert, recent edits (from audit trail), recent activity.

### P15.8 — Floor costing & revenue report
- Per floor of a site: `sqft`, `rate`, contract value (sqft × rate), billed, remaining receivable (contract − billed), labour cost, construction cost, allocated hidden cost, total cost, profit (billed − total cost), cost per sqft.
- Site-general hidden cost (floor = null) is shown as its own row, **not** pro-rated across floors.
- Reconciles to site profit: `site profit = (Σ floor profit) − general hidden cost`, which equals `bills − (labour + site cost + all hidden cost)`.

---

## P16 — Record Edits & Audit Trail

Edits happen directly; the audit log makes every change accountable.

### P16.1 — Edit / delete a record (direct, with auto audit)
- An authorized user edits or deletes a record from its own module (attendance P11, payment P8, return P9, cash P13, cost/hidden cost P12, bill P14, plus master data).
- In one transaction the system:
  1. Applies the change (financial/ledger rows are **soft-deleted**, not hard-deleted).
  2. Writes an **audit log entry**: company, actor, timestamp, target record type + id, action (update/delete), **before snapshot**, **after snapshot**, and a **note (required for update/delete of financial records)**.
  3. Bumps the record's `updated_at`.
  4. Recalculates running totals of all later rows in the same ledger so the chain stays consistent.

### P16.2 — View audit trail
- Any authorized user views the log, filtered by record, site, user, action, or date range.
- Each entry shows who changed what, when, the before/after values, and the note.

### P16.3 — Remove audit log entries
- Only Admin (or an explicitly authorized user) can **soft delete** audit entries. No one can **edit** an entry. Now company lose this data accessability only system can see and manage it. If company remove the audit logs accedentally system will allow to back their data by suppport system. System will permanently delete soft deleted audit log for several month or based on its policies using schduled corn job.
- Even after removal, the affected record's `updated_at` still shows it was modified — tamper-evident backstop.

> **Note** — there is intentionally no admin override to edit a **locked** record. Locking is the hard boundary; if a settled period truly needs a fix, the company-level decision is to reopen via data correction by a system user (P2), not a normal edit.
