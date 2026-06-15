# SiteMan — Feature and user Flow

## Conventions (cross-cutting)
- **Tenant isolation** — every row carries `company_id`; all queries are scoped to the caller's company.
- **Global phone uniqueness** — one phone = one account across the whole platform.
- **Running totals** — ledger rows store cumulative fields (`site_total`, `floor_total`, and on attendance `site_total_present` / `site_total_salary` / `floor_total_present` / `floor_total_salary`). Current value = the latest row's total; **per-floor totals chain per floor** (latest row *per floor*), per-site totals chain per site.
- **Labour balance** — `balance = last_balance + earnings − advance − fooding + returns`, where `earnings = Σ(present × salary) + Σ extra work`. Carried across vacations via `LabourSession` (`last_balance` → `balance`).
- **`editable` flag** — every labour-linked row (attendance, extra work, advance pay, fooding pay, return) starts `editable = true`. Sealing a `LabourSession` (P10) sets the sealed rows `editable = false` → immutable. **This flag is the lock** (replaces any date-based lock).
- **Direct edit + audit** — authorized users edit/delete directly; the system auto-writes an audit entry (actor, time, before/after, note) and bumps `updated_at` (P16). Ledger rows are **soft-deleted**.
- **Site cash balance** — `deposits − withdrawals(returns) − site cost − advance pay − fooding pay`. Hidden cost is **excluded** (paid by admin, not from the site box).

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

### P2.9 — Data correction on sealed/closed data
- Only a system user can correct a sealed (`editable=false`) row or restore/repair a closed site's data on support request — the company side has no such override.

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
- **Company-level** master data: Admin creates/edits expense categories (name, display order, active flag).
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
A site typically runs ~2 years, then work is done. Closing frees a plan slot and lets the system shed the large detail dataset **in the same database** (no separate archive store) while keeping a permanent summary.

1. **Zero the site cash balance (manual, by site manager):**
   - balance > 0 → withdraw the surplus via a SiteCashReturn (P13.2).
   - balance < 0 → cover the deficit via a SiteCash deposit (P13.1).
   - Close is blocked until the site cash balance = 0.
2. **Set `closed_at = now()`** (a null `closed_at` = open, non-null = closed). Closed sites do not count toward the plan's open-site limit.
3. **Build the closure summary** (immutable snapshot): totals from SiteCost, HiddenCost, SiteBill, DailyAttendance (total present, total salary), LabourExtraWork totals, total cost, total bills, total paid bills, profit, floor contract vs billed — everything the admin needs after the detail is gone.
4. **Access changes immediately** — authorized users now see **only the summary**; the detail rows stay in the same DB but are hidden from the company side.
5. **Cron purge** — a scheduled job deletes the detail rows of any site whose `closed_at` is **more than 30 days** old, **except** rows still `editable = true`. Those belong to an unsealed `LabourSession`; they are kept until the next session seals them (`editable = false`), after which a later cron run may delete them.

### P6.4 — Reopen a closed site
- Admin requests reopen.
- System checks the subscription / open-site count against the plan limit (must have a free slot).
- **Set `closed_at = null`** → delete the closure summary → detail info is accessible again; the site counts as open.
- Only possible while the detail still exists (closed < 30 days, not yet purged). Once the cron has purged the detail, reopen can no longer restore it — recovery becomes a system-user support task (P2.9).

### P6.5 — Delete site
- Allowed only when the site has no financial records; otherwise must close instead.
- Later, when no entity ref this site then allow to delete.

### P6.6 — Assign users to site
- Admin links users to the site.

### P6.7 — View company sites
- Admin sees all sites; othere users see only assigned sites. Filters: open/closed, active/inactive.

### P6.8 — View site Report
- Shows current cash balance (per Conventions: `deposits − returns − site cost − advance pay − fooding pay - hidden cost`).
- Shows site revenue (bills vs floor contract).
- Show site total attendance count and total salary.
- Show site total cost.
- Show site labour payouts (advance + fooding).
- Floor breakdown line: per-floor contract value, billed, cost and profit (detail in P15.8).

### P6.9 — Manage site floors
- Site-level master data: Admin defines the site's floors — name (e.g. Basement, Floor-1, Floor-2, Floor-2-Extra), display order (serial), measurement (`sqft`), and `rate_per_sqft`.
- Derived `contract_value = sqft × rate` is the floor's revenue target.
- Floor list feeds the floor dropdown on attendance (P11.1), extra work (P11.2), site cost (P12.1), hidden cost (P12.2), and bill (P14.1) entries.
- Editable while the site is open; a floor cannot be deleted once any record references it.
- Expense categories are company-level (P3.4), not defined here.

### P6.10 — Deactivate/Activate site floors
- Floor may activate or deactivate. Deactivate means no new records allow to create under this floor execpt the SiteBill. But, historic data is accessable.

### P6.11 — Mark floor as done
- This floor work is done, no need new expense or work.
- Floor will deactivate.
- To activate the floor again need to unmark as done first.

---

## P7 — Manage Labour Accounts

### P7.1 — Create / edit labourer
- Manager (with site permission) provides name, `default_salary`, `default_present`, `default_fooding`, and current site.
- System checks name uniqueness.
- Labour starts active, assigned to that site. New attendance / fooding rows seed their values from these defaults if not provide explicitly (each row still keeps its own snapshot).

### P7.2 — Assign / move labourer to site
- Sets or changes the labour's current site (one site at a time — assigning to a new site **is** the move).
- Previous site manager no longer creates new records against this labour.
- New site manager now has authority to create new records for this labour.

### P7.3 — Activate / deactivate labour account
- Inactive labour: no new attendance, extra work, or payments; history stays.
- A sealed `LabourSession` (vacation) deactivates the account automatically; returning from vacation requires reactivation **before** any new record (P10.1).

### P7.4 — Update labour salary for a date range
Salary is snapshotted on each DailyAttendance row (`Labour.default_salary` only seeds new rows). To re-price work, the attendance rows themselves are updated — and only while still **editable** (not yet sealed into a LabourSession).
1. Open the labour's attendance page.
2. Select a **single cell** (one row) or a **date range** or **particular site** of rows to re-price.
3. Enter the new salary.
4. System updates `salary` on each selected (`editable = true`) row and recomputes the running `site_total_salary` and `floor_total_salary` of those and all later rows.
5. Each change is written to the audit log (P16).
- Rows already sealed (`editable = false`) cannot be re-priced.

### P7.5 — View and search labourers
- Filter by site, active status; search by name. Shows current site, salary, balance.

### P7.6 — Delete Labour Account

Many labourers work short engagements and never return; their accounts accumulate and must be cleanable without losing site financial data.

**Pre-condition:** Labour balance must be zero before deletion is allowed.

1. Set `labour.deleted_at = now()` — labour hidden from all active views; write to audit log
2. Admin can view and restore deleted labourers within a configurable retention window (default: 30 days)
3. Scheduled job permanently purges labourers whose `deleted_at` exceeds the retention threshold
4. On purge, database-level `ON DELETE SET NULL` cascades handle all foreign key references automatically

---

## P8 — Manage Labour Payments (Advance & Fooding)

A labour is paid through two ledgers — **advance pay** (cash advances) and **fooding pay** (meal allowance). Both are payouts that draw down site cash and reduce the labour's balance.

### P8.1 — Issue advance pay
- Manager picks labour, enters amount, note, date → creates a `LabourAdvancePay` row (`editable = true`).
- Blocked if labour is inactive.
- Running `site_total` (site's cumulative advance) computed from the previous row.

### P8.2 — Issue fooding pay
- Manager picks labour, enters amount (seeded from `default_fooding`), note, date → creates a `LabourFoodingPay` row (`editable = true`).
- Blocked if labour is inactive.
- Running `site_total` (site's cumulative fooding) computed from the previous row.

### P8.3 — Track labour balance
- `balance = balance (from last worksession) + earnings from dailyattendence(editable=true) − advance(editable=true) − fooding(editable=true) + returns(editable=true)`.
- Read from the latest carried balance / running totals — no full scan needed.

### P8.4 — View payment history
- Advance and fooding ledgers per labour or per site, ordered by date; each row shows amount + running totals.

---

## P9 — Manage Labour Return

### P9.1 — Record labour return
- Labour may return overpaid money. Manager creates a `LabourReturn` (amount, note, date; `editable = true`).
- Running `site_total` computed from the previous row; increases the labour's balance.

### P9.2 — View return history
- Ledger of returns per labour/site.

---

## P10 — Manage Labour Session

A labour works continuously — moving site to site — then takes a vacation. The **period** between two vacations is one Work Session, recorded as a `LabourSession` plus one `LabourSiteSession` per site touched.

### P10.1 — Create / seal a labour session (vacation flow)
Triggered when the labour wants to go on vacation:
1. **Review** — all still-`editable` rows (attendance, extra work, advance, fooding, return) are reviewed; any correction is applied now, while they are still editable.
2. **Settle** — a final payment is made based on the current balance (pay out the payable, or collect an overpayment) so the balance reflects reality.
3. **Per-site rollup** — for each site the labour touched this session, create a `LabourSiteSession` aggregating that site's `present`, `extrawork`, `fooding`, `advance`, `salary`, `earnings`, `payable`.
4. **Session record** — create one `LabourSession` linking all its LabourSiteSessions, with:
   - `start_date` = date of the first record after the previous session's end,
   - `end_date` = date of the **last** record in this session,
   - `last_balance` = balance carried in, `balance` = balance carried out.
5. **Seal** — set `editable = false` on every row rolled into the session (now immutable).
6. **Deactivate** the labour account → vacation.

Rules:
- Records created after sealing belong to the **next** session.
- The session `end_date` is the latest sealed record's date.
- Any new record's date must be **≥ the last session's end_date**.
- After returning from vacation, the account must be **reactivated first** (P7.3) before creating any record.

### P10.2 — View session history
- Timeline of sessions per labour with per-site breakdown (present, earnings, payouts), start/end dates, and carried balances.

---

## P11 — Manage Daily Attendance & Extra Work

### P11.1 — Record daily attendance
- Grain is **labour / floor / day**: Site Manager picks date, floor (from the site's floor list, P6.9), `present` units (full/half/overtime), and `salary` (seeded from the labour default, editable per row).
- A labour may have **multiple attendance rows on the same day** when he works on different floors — uniqueness is **(labour, floor, date)**, not (labour, date).
- Floor is required so the earnings attribute to floor costing.
- Validations: labour active and assigned to this site, site active, floor active, one row per (labour, floor, date), date inside the allowed window (see below). New row is `editable = true`.
- Row stores the salary snapshot and running totals: `site_total_present`, `site_total_salary`, `floor_total_present`, `floor_total_salary`.
> **Allow create for today and yesterday only** (and date ≥ last session end date). This rule also applies to other date-bearing entities: extra work, site cost, hidden cost, site cash, etc.

### P11.2 — Record extra work
- Separate ledger (`Labour ExtraWork`): site, floor (P6.9), labour, date, amount, note; `editable = true`.
- Kept apart from attendance so ad-hoc extra earnings are tracked on their own.
- Running `site_total_amount` and `floor_total_amount`. Adds to the labour's earnings.

### P11.3 — View attendance & extra work history
- Filter by labour, site, floor, or date range; shows daily rows + running totals.

---

## P12 — Manage Site Expense

### P12.1 — Record site construction cost (SiteCost)
- Manager enters site, date, **floor (required, P6.9)**, **expense category (company-level — P3.4)**, amount, note.
- Row computes running `site_total` and `floor_total` from the previous cost row.
- **Expense category is nullable**: null = "Generalized expense".
- Paid from site cash (draws down the cash balance).

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
- Manager records incoming cash with notes (`SiteCash`).
- Running site cash total increases.

### P13.2 — Record cash return / withdrawal
- Outgoing cash: return to owner or other source with note (`SiteCashReturn`). This is not a site cost — a withdrawal.
- Cannot go below zero — insufficient balance is rejected.
- Running site return total increases.

### P13.3 — View site cash history
- Passbook view: date, type, note, amount (±), running balance per row (per Conventions formula).

---

## P14 — Manage Site Bills

### P14.1 — Create site bill
- Authorized user records a bill: site, date, **floor (required, P6.9)**, amount, note.
- Running `site_total` and `floor_total` per bill row; floor bills accumulate against that floor's contract value (sqft × rate, P6.9).

### P14.2 — View bill history
- Ledger per site, filterable by floor, date range; shows billed vs floor contract value vs remaining receivable.

---

## P15 — Generate Reports

All reports are tenant-scoped and respect site assignments (managers see only their sites).

### P15.1 — Labour balance report
- Per labour: earnings (attendance salary + extra work), advance, fooding, returns, net balance. Read from latest running totals / carried balance.

### P15.2 — Site expense report
- Costs grouped by company expense category / floor for a site and date range (SiteCost and HiddenCost shown separately).

### P15.3 — Site balance report
- `deposits − returns − site cost total − advance pay total − fooding pay total` per site — current spendable cash (matches P6.8; hidden cost excluded).

### P15.4 — Site profit report
- Profit per site: `bills − (labour cost + site cost + hidden cost)`, where labour cost = attendance salary + extra work (payouts are cash, not cost).
- Profit per floor of site: `bills of floor − (labour cost of floor + site cost of floor + hidden cost of floor)`.

### P15.5 — Site labour cost report
- Attendance salary per site / date / floor.
- Extra work per site / date / floor.
- Advance pay and fooding pay per site / date.
- Labour cost per site: `latest attendance site_total_salary` + extra work total.
- Labour cost per floor of site.

### P15.6 — Summary for a date range
- Company-level roll-up between two dates: cash in/out, costs, bills, labour cost, per-site rows.
- Site-level summary.

### P15.7 — Company dashboard
- Open sites overview, balances, subscription expiry alert, recent edits (from audit trail), recent activity.

### P15.8 — Floor costing & revenue report
- Per floor of a site: `sqft`, `rate`, contract value (sqft × rate), billed, remaining receivable (contract − billed), labour cost, construction cost, allocated hidden cost, total cost, profit (billed − total cost), cost per sqft.
- Site-general hidden cost (floor = null) is shown as its own row, **not** pro-rated across floors.
- Reconciles to site profit: `site profit = (Σ floor profit) − general hidden cost`, which equals `bills − (labour + site cost + all hidden cost)`.

---

## P16 — Record Edits & Audit Trail

Edits happen directly; the `editable` flag is the hard lock, and the audit log makes every live edit accountable.

### P16.1 — Edit / delete a record (direct, with auto audit)
- Allowed only on rows that are still `editable = true` (sealed rows are immutable — see P10).
- An authorized user edits or deletes a record from its own module (attendance P11, extra work P11, advance/fooding P8, return P9, cash P13, cost/hidden cost P12, bill P14, plus master data).
- In one transaction the system:
  1. Applies the change (financial/ledger rows are **soft-deleted**, not hard-deleted).
  2. Writes an **audit log entry**: company, actor, timestamp, target record type + id, action (update/delete), **before snapshot**, **after snapshot**, and a **note (required for update/delete of financial records)**.
  3. Bumps the record's `updated_at`.
  4. Recalculates running totals of all later rows in the same ledger (per floor and per site) so the chain stays consistent.

### P16.2 — View audit trail
- Any authorized user views the log, filtered by record, site, user, action, or date range.
- Each entry shows who changed what, when, the before/after values, and the note.

### P16.3 — Remove audit log entries
- Only Admin (or an explicitly authorized user) can **soft delete** audit entries. No one can **edit** an entry. The company then loses access to that data — only the system can see and manage it; if a company removes audit logs accidentally, the system can restore them via support. A scheduled cron permanently deletes soft-deleted audit logs after a retention period.
- Even after removal, the affected record's `updated_at` still shows it was modified — tamper-evident backstop.

> **Note** — there is intentionally no admin override to edit a **sealed** (`editable = false`) record. The seal is the hard boundary; if a settled session truly needs a fix, the correction is done by a system user (P2.9), not a normal edit.
