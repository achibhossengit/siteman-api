# SiteMan — Feature Details

## Conventions
- **Tenant isolation** — every tenant row carries `company_id`; See **Access Control & User Model**.
- **Running totals** — ledger rows store cumulative fields (`site_total`, `floor_total` etc). Need to update all later rows after update or delete any rows.
- **`editable` flag** — every labour-linked row (attendance, extra work, advance pay, fooding pay, return) starts `editable = true`.
- **Direct edit + audit** — authorized users edit/delete directly; the system auto-writes an audit entry (actor, time, before/after, note) and bumps `updated_at` / `deleted_at` (F16). Ledger rows are **soft-deleted**.
- **Future dates blocked** — no record's `date` may be in the future, for every date-bearing entity.
- **Configuration tiers**
  - **System config** (`SystemConfig`, single global row, System Admin) — Governs platform behaviour only. See **System Configuration** under F2.
  - **Company config** (`CompanyConfig`, one per company, Company Admin) — per-tenant feature flags, e.g. `allow_labour_transfer` (default `true`); created with its **own built-in defaults** at registration. See **Company Configuration** under F3.
  - **Site config** (`SiteConfig`, one per site, Company Admin) — per-site create/update/delete windows + per-day quotas. See **Site Configuration** under F6.

## Roles
- **System Admin** — manages all companies and subscriptions.
- **System Manager** — monitors subscriptions and payments (assigned permissions).
- **Company Admin** — full control of one company: users, sites, labour, subscription.
- **Company Manager** — manages assigned sites and reviews the audit trail for them.
- **Site Manager** — records attendance, cash, and cost for permitted sites; edits are logged.

## Access Control & User Model
### One `User` table, two scopes:
- **System** (`scope = system`, `company = null`) — platform staff (F2); uses the **Platform API** (`/api/platform/…`), cross-company.
- **Tenant** (`scope = tenant`, `company` set) — company user (F5); uses the **Tenant API** (`/api/…`), auto-scoped to its company.
- One phone = one account, so a person is system **or** tenant. Same OTP + JWT login (F1.1 / F2.1); token carries `user_id`, `scope`, `company_id`, groups. A system user reaches tenant data only through explicit platform endpoints (e.g. F2.9).
- **Why separate login endpoints** 
  - Phone is globally unique, so `scope` alone *could* drive one shared endpoint; they are split for security, not necessity.
  - The platform login is an isolated route with its own rate-limit / IP-allowlist / hardening, kept off the tenant attack surface.
  - A system account can never authenticate on the tenant endpoint (scope mismatch → rejected), shrinking coupling and blast radius. 
  - It avoids the account enumeration a shared endpoint leaks (which phones are platform staff). OTP generation, JWT issue, and BD-phone normalization live in a **shared service**; each endpoint is a thin wrapper that fixes the scope and applies its own policy — **one core logic, two doors**.

### Who can do what — two independent layers:
- **Capability** (*what*) — a Django **Group**: System Admin / System Manager; Company Admin / Company Manager / Site Manager. Global within its scope, never per-site.
- **Scope** (*which sites*) — **`UserSite`** links a tenant user to sites. A site can have many managers; a user many sites.
- A **write** is allowed when: capability (Group) **+** assigned to the site (`UserSite`) **+** inside the entity's window (F6.12) **+** the row is `editable`. The Company Admin manages all sites by default, but to **record** on a site must self-assign and join the Site Manager group (F6.14) — the same write rule then applies.
---

## F1 — Manage Authentication

### F1.1 — Login
- User gives phone number and password.
- System validates BD phone number (normalize to `+8801XXXXXXXXX`, reject invalid operator codes).
- System verifies password against the user account; account must be active and company must be active.
- System sends an OTP to this phone number via SMS (6-digit, short expiry, limited attempts).
- User submits the OTP to complete login.
- On success system issues JWT access + refresh tokens (token carries `user_id`, `company_id`, role).
- Resend OTP: allowed after a cooldown, limited number of resends per hour.

### F1.2 — Register
- Visitor provides name, phone_number, email, company detail, and password.
- System validates BD phone_number and checks it is not already registered.
- System sends an OTP to this phone number; user completes registration by providing the OTP.
- On OTP success, inside one database transaction:
  1. System creates the Company using the company detail.
  2. System creates the user account under this company.
  3. System assigns this user to the **Company Admin** group.
- User can now log in; new company starts on the **Free plan** if available.

### F1.3 — Reset forgotten password
- User gives registered phone number.
- System validates the phone number and confirms an account exists (without leaking which numbers exist).
- System sends OTP via SMS; user verifies OTP.
- On success user sets a new password; all existing refresh tokens are invalidated.

### F1.4 — Change password
- Logged-in user provides current password + new password.
- System verifies current password, applies password rules, saves new password.
- Other active sessions are logged out (refresh tokens blacklisted).

### F1.5 — Logout
- User triggers logout; system blacklists the refresh token.
- Client discards both tokens.

---

## F2 — Manage Platform
System-level users; not tied to any company.

> **MVP scope** — in the MVP the entire platform side (F2.*) is operated through the **Django admin site** (`/admin/`, Django session auth); there is no platform frontend or public platform API yet, and system users are Django staff/superusers. The dedicated **Platform API** + system OTP/JWT login (F2.1) and custom actions like company reset (F2.11) are a **later phase**. The **tenant** side (F1, F3–F16) ships with its real API + frontend now.

### F2.1 — System user login
- Separate login for platform staff (no company context); same OTP + JWT pattern.

### F2.2 — View and search all companies
- List with open site count, billing status, activity, audit logs.

### F2.3 — Activate / deactivate a company
- Deactivated company: all its users blocked from login; data retained.

### F2.4 — Manage subscription plans
- System Admin creates/edits plan tiers: **open-site limit**, **active-user limit**, **active-labour limit**, per-month rate per duration (1/6/12 months). Each limit `-1` = no limit; `N` = cap.
- Price changes apply to new purchases/renewals only; running subscriptions keep their rate snapshot.
- Custom plan: limits and price negotiated and set manually per company.
- **Manual payment** — a System user can record a subscription payment that bypasses the gateway (offline / bank / cash, or after a gateway failure) for any company.

### F2.5 — Monitor subscription status
- Dashboard of all companies: plan, active / expiring soon / expired, revenue summary.

### F2.6 — Create system users
- System Admin creates platform staff accounts (`scope = system`, `company = null`); assigned a system group (F2.7).

### F2.7 — Assign system roles
- System Admin assigns staff to system-level groups (System Admin / System Manager).

### F2.8 — Assign system-level permissions
- Fine-grained platform permissions per staff user (e.g., System Manager: monitor only).

### F2.9 — Data correction on sealed/closed data
- Only a system user can correct a sealed (`editable=false`) row or restore/repair a closed site's data on support request — the company side has no such override.

### F2.10 — Manage system configuration
- System Admin views/edits `SystemConfig` (single global row, auto-created with defaults).
- Implementation note: SystemConfig is a Singleton (django-solo)

**Examples:**
| Field | Default | Meaning |
|---|---|---|
| `maintenance_mode` | false | When `true`, show a maintenance banner to all users. |
| `subscription_renew_notification` | 5 (days) | Begin renewal reminders this many days **before** `valid_until` — SMS + dashboard to every Company Admin (F4.7). |
| `company_deactivate_after_expiry` | 10 (days) | Days **after** expiry to auto-deactivate the company. On expiry, write access is cut immediately (F4.6); after this many further days the cron deactivates the company — no user can log in, reactivation needs a support request (F2.3). |
| `delete_deactivated_company` | 60 (days) | Days a company may stay deactivated before a cron **purges** its data. |

**How it drives cron** — the scheduled jobs run on a **fixed schedule** (daily, set at deploy). They read these **threshold values** at run time and decide what to act on. So changing a value takes effect on the next run.

> **Lifecycle timeline:** `valid_until` reached → write disabled immediately (F4.6) → **+ `company_deactivate_after_expiry` days** still unpaid → company deactivated, logins blocked → **+ `delete_deactivated_company` days** → data purged.

### F2.11 — Reset a company (system user only, OTP dual-control)
A low-frequency support action for clients who tested the app on a real account and want a clean production start. Destructive and **irreversible**, so it lives only on the platform side under two-party control.

1. Company Admin requests a reset via support (email / contact) — there is **no reset button on the tenant side**.
2. An authorized **System user** opens the company, hits **Reset**, and types the **company name** to confirm.
3. System sends a **single-use, short-expiry OTP to the Company Admin's phone** (shared OTP service, F1.1) — this proves the company consents.
4. The Company Admin relays the OTP to the system user, who enters it; the system **validates** it.
5. On a valid OTP, in **one transaction** the system **hard-deletes** all tenant data (FK-safe order): sites, floors, labours, work sessions, every ledger (attendance, extra work, advance, fooding, return, cash, cost, bill), expense categories, all **non-admin** users (+ `UserSite` links), and the company's **audit logs**. `CompanyConfig` returns to built-in defaults; all `SiteConfig` rows are gone with their sites.
6. **Kept:** the Company record, **all Company Admin** accounts, and the active subscription (`plan`, `paid_until` untouched) — the company is now like new with zero entities.
7. The system writes a **platform-level reset log** (system user, company id, timestamp, OTP-verified) stored system-side — it survives the wipe (the company-side audit cannot, per step 5).
---

## F3 — Manage Company

### F3.1 — Create company
- Not a user-facing form — runs inside registration (F1.2).
- Creates Company record (name, active flag, billing fields); registrant becomes Company Admin.

### F3.2 — View company profile & status
- Company Admin opens company page.
- Shows name, active status, open site count, current plan, and subscription validity.

### F3.3 — Edit company details
- Company Admin edits company name and profile fields.
- System saves and records the change in the audit trail.

### F3.4 — Manage expense categories
- **Company-level** master data: Admin creates/edits expense categories (name, display order, active flag).
- Shared by **all sites** of the company — every SiteCost (F12.1) and HiddenCost (F12.2) row references the same category set, so cross-site reporting stays consistent.
- **Deactivate** — hidden from new-entry dropdowns; no new row may reference it, existing rows keep their link.
- **Delete** — all referencing rows get `null`, treated as "Generalized expense".

### F3.5 — Manage company configuration
- Company Admin views/edits the company's `CompanyConfig` (one row per company, auto-created at F3.1 with its own built-in defaults).
- Tenant-wide feature flags that apply to every site of the company. The change is audit-logged.
- Example: **`allow_labour_transfer`** (bool, default `true`) — when `false`, moving a labour from one site to another (F7.2) is blocked company-wide; a labour stays on its original site for its whole lifecycle. Existing assignments are untouched.
- **Reset to defaults** — Company Admin can reset `CompanyConfig` back to its built-in defaults in one action; config-only (no entity data touched), audit-logged.

---

## F4 — Manage Company Subscription

### F4.1 — View subscription status
- Company Admin sees current plan, expiry date, payment history, and **usage vs limit** for each capped resource: open sites, active users, active labour.

### F4.2 — Pay for plan
- Admin picks a plan tier and duration (1 / 6 / 12 months).
- Admin starts payment → system creates a payment attempt and redirects to the payment gateway.
- Gateway sends confirmation (IPN/webhook); system verifies signature and amount.
- On success: subscription record saved (plan, duration, amount, transaction id), `paid_until` extended from the activation date.
- On failure/cancel: nothing changes; user can retry.

### F4.3 — Renew plan
- Admin can renew plan at any time

### F4.4 — Upgrade plan
- **Before expiry:** remaining value of the current plan is calculated (unused days × current per-day rate) and adjusted against the new plan cost; pay the difference.
- **After expiry:** plain purchase of any higher plan.

### F4.5 — Downgrade plan
- **Before expiry:** not allowed — must wait until the current plan expires.
- **After expiry:** system checks current usage of every capped resource (open sites, active users, active labour) against the target plan limits:
  - All within limits → downgrade proceeds.
  - Any exceeds its limit → admin is prompted to shed the excess (close sites / deactivate users / deactivate labour) or stay on the current plan.

### F4.6 — Disable write access on expiry
- Middleware checks subscription validity on every request.
- Expired → write access to all sites is disabled immediately (read-only); admin gets an alert to renew.
- If still unpaid `company_deactivate_after_expiry` days later (SystemConfig, F2.10), a cron **deactivates** the company — all logins blocked; reactivation then needs a support request (F2.3). Left deactivated for `delete_deactivated_company` days → data purged.

### F4.7 — Send renewal reminders
- Scheduled job sends SMS + dashboard notification to every Company Admin starting `subscription_renew_notification` days before expiry (SystemConfig, F2.10), and again after expiry.
- Reminder log kept so the same reminder is not repeated.

### Subscription Model (reference)
Pricing is driven by **open site count**; the user and labour caps default to `-1` (no limit) today and exist so a tier can be tightened later without a schema change. Longer durations get a **per-month discount**. Prices in BDT.

| Plan | Open Sites | Active Users | Active Labour | 1 Month | 6 Months | 1 Year |
|---|---|---|---|---|---|---|
| **Free** | Up to 1 | −1 | −1 | Free | — | — |
| **Basic** | Up to 5 | −1 | −1 | 600 × 1 = **600** | 550 × 6 = **3,300** | 500 × 12 = **6,000** |
| **Popular** | Up to 10 | −1 | −1 | 1,000 × 1 = **1,000** | 950 × 6 = **5,700** | 900 × 12 = **10,800** |
| **Business** | Up to 20 | −1 | −1 | 3,000 × 1 = **3,000** | 2,900 × 6 = **17,400** | 2,500 × 12 = **30,000** |
| **Custom** | 20+ | negotiated | negotiated | negotiated | negotiated | negotiated |

> **Limit scale (all three):** `-1` = no limit, `N ≥ 0` = hard cap.
---

## F5 — Manage Company Users

### F5.1 — Create Staff user
- Company Admin provides name, BD phone number, password, role, permitted sites.
- System validates BD phone_number and checks it is not already registered.
- System checks the company's **active-user count** against the plan's active-user limit (skip if `-1`); at the cap → blocked with an upgrade prompt (F4.4).
- System sends an OTP to this phone number; admin completes registration by providing the OTP.
- System will creates user under the same company (`scope = tenant`, `company` = admin's company).
- If provide role and permitted sites then Assign this user to that group and permitted sites.
> Lately this staff user will login using this phone_number and password. and can change the password. There is no security concern about account missused by admin. Because, admin need the otp to register or login staff user account. But, otp will send to this user phone_number. So, Account owner only can login. Admin just has activate, deactivate, role management, permission management and delete this account autority.

### F5.2 — Assign role to user
- Admin picks a role (Company Admin / Company Manager / Site Manager) → user added to that group.
- Role change takes effect on next request (permissions read from group).

### F5.3 — Assign user to sites
- Admin assigns user to one or more sites (`UserSite` link records).
- Site-scoped actions check this assignment: managers only act on assigned sites.
- A site may have multiple Site Managers / Company Managers; a user may be assigned to multiple sites. See **Access Control & User Model**.

### F5.4 — Assign permissions to user
- Admin grants/revokes fine-grained permissions on top of the role defaults.

### F5.5 — Activate / deactivate user
- Deactivated user cannot log in; existing tokens stop working.
- Reactivation restores access; history is untouched.

### F5.6 — Delete user
1. Set `user.deleted_at = now()`, disable account; write to audit log
2. Admin can view and restore deleted users within a configurable retention window (default: 30 days)
3. Scheduled job permanently purges users whose `deleted_at` exceeds the retention threshold
4. On purge, database-level `ON DELETE SET NULL` cascades handle all foreign key references automatically

### F5.7 — View and search users
- List company users with filters: role, site, active status; search by name/phone.

---

## F6 — Manage Sites

### Site States (reference)
Two independent state axes for a site:

| Field | Value | Meaning |
|---|---|---|
| `closed_at` | `null` | **Open** — site is ongoing. Counts toward the plan's open-site limit. |
| `closed_at` | timestamp | **Closed** — work permanently done. Company users see only the closure summary; detail rows stay in the same DB but are hidden, then a cron purges them 30 days after `closed_at` (except `editable=true` rows). Does not count toward the plan limit. Reopen possible until purge. |
| `is_active` | `True` | **Active** — new data (attendance, cash, cost) can be recorded. |
| `is_active` | `False` | **Inactive** — temporarily paused. No new data can be created. Old data remains accessible. Can be reactivated at any time. |

> A site may be open (`closed_at=null`) and inactive (`is_active=False`) at the same time — temporarily paused but still ongoing. The plan limit counts all open sites regardless of active/inactive state.

### Site Configuration (reference)
Every site has a one-to-one `SiteConfig` (managed in F6.12), auto-created with sensible defaults and editable by the Company Admin. It lets each site tune how strictly records may be created and edited — without code changes.

**Window scale** — used by `*_create_window`, `*_update_window` and `*_delete_window`:

| Value | Meaning |
|---|---|
| `-1` | Any date ≤ today (no lower bound) |
| `0` | Disabled — no date qualifies (turns that action off for the entity) |
| `N ≥ 1` | Last `N` days including today, i.e. `[today − (N−1) … today]` (1 = today only, 2 = today + yesterday, 3 = today + 2 days back, …) |

> Future dates are **always** rejected, regardless of any window.

**Per-day quota scale** — `*_per_day_limit` (labour-scoped entities only):

| Value | Meaning |
|---|---|
| `-1` | Unlimited |
| `0` | Blocked — no rows that day |
| `N ≥ 1` | At most `N` rows per labour per date (across floors). The (labour, floor, date) uniqueness already blocks duplicate site+floor rows. |

**Cross-site, same date** — there is no separate multisite flag. By default a labour has one record per date; to record the same labour/date at a **different** site, first free the existing row (remove it) or transfer the labour to the new site (F7.2). To genuinely allow both sites on the same date, raise the relevant `*_per_day_limit`.

**Out-of-window override (manual)** — there is no per-row verification. To touch a date outside the current window, a manager asks the admin; the admin widens the matching window (a temporary `N` covering the date, or `-1` to allow any past date), the manager creates/edits/deletes, and the admin reviews the result via the date based activity / audit trail (F16.2). If misused, the admin asks the manager to correct it — no system-enforced approval step.

**Fields by entity** (field name pattern `<entity>_<axis>`, e.g. `attendance_create_window`, `sitecost_update_window`, `advance_delete_window`, `fooding_per_day_limit`):

| Entity | create_window | update_window | delete_window | per_day_limit |
|---|---|---|---|---|
| attendance | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) |
| fooding | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) |
| advance | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) | ✓ (def −1) |
| return | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) | — |
| extrawork | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) | — |
| sitecost | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) | — |
| hiddencost | ✓ (def -1) | ✓ (def -1) | ✓ (def -1) | — |
| sitecash (deposit) | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) | — |
| sitecashreturn | ✓ (def 1) | ✓ (def 1) | ✓ (def 1) | — |
| sitebill | ✓ (def -1) | ✓ (def -1) | ✓ (def -1) | — |

**Validation ranges** — per-site, customizable by Company Admin. `labour.default_salary` / `default_fooding` are validated against the labour's **current_site** config at create/edit time:
- `attendance_present_choices` — explicit allowed set for the `present` value, e.g. `[0, 0.5, 1, 1.5, 2, 3]` (only these accepted; the set is not a uniform step, so it is a list not a min/max).
- `salary_min` / `salary_max` — bounds for attendance `salary` and `labour.default_salary` (e.g. 500–1500).
- `fooding_min` / `fooding_max` — bounds for fooding pay amount and `labour.default_fooding` (e.g. 50–200).
- `advance_min` / `advance_max` — bounds for a **single** advance row amount (e.g. 0–10000); caps the per-row amount, not the daily count (`advance_per_day_limit`).

### F6.1 — Create / edit site
- Admin provides site name (and detail fields). New site starts open + active.
- System validates open site count against the active plan limit before creating; at the limit → creation blocked with an upgrade prompt (F4.4).

### F6.2 — Activate & Deactivate site
- Deactivate:
  - Sets `is_active = False`
  - No new attendance/cash/cost/bill entries; old data stays readable; reversible any time.
  - Users & labourer is not consider with that. They are relvent with company.
- Activate:
  - Sets `is_active = True`; new data entry allowed again.

### F6.3 — Close site permanently
A site typically runs ~2 years, then work is done. Closing frees a plan slot and lets the system shed the large detail dataset **in the same database** (no separate archive store) while keeping a permanent summary.

1. **Zero the site cash balance (manual, by site manager):**
   - balance > 0 → withdraw the surplus via a SiteCashReturn (F13.2).
   - balance < 0 → cover the deficit via a SiteCash deposit (F13.1).
   - Close is blocked until the site cash balance = 0.
2. **Set `closed_at = now()`** (a null `closed_at` = open, non-null = closed). Closed sites do not count toward the plan's open-site limit.
3. **Build the closure summary** (immutable snapshot): totals from SiteCost, HiddenCost, SiteBill, DailyAttendance (total present, total salary), LabourExtraWork totals, total cost, total bills, total paid bills, profit, floor contract vs billed — everything the admin needs after the detail is gone.
4. **Access changes immediately** — authorized users now see **only the summary**; the detail rows stay in the same DB but are hidden from the company side.
5. **Cron purge** — a scheduled job deletes the detail rows of any site whose `closed_at` is **more than 30 days** old, **except** rows still `editable = true`. Those belong to an unsealed `LabourWorkSession`; they are kept until the next session seals them (`editable = false`), after which a later cron run may delete them.

### F6.4 — Reopen a closed site
- Admin requests reopen.
- System checks the subscription / open-site count against the plan limit (must have a free slot).
- **Set `closed_at = null`** → delete the closure summary → detail info is accessible again; the site counts as open.
- Only possible while the detail still exists (closed < 30 days, not yet purged). Once the cron has purged the detail, reopen can no longer restore it — recovery becomes a system-user support task (F2.9).

### F6.5 — Delete site
- Allowed only when the site has no financial records; otherwise must close instead.
- Later, when no entity ref this site then allow to delete.

### F6.6 — Assign users to site
- Admin links users to the site.

### F6.7 — View company sites
- Admin sees all sites; othere users see only assigned sites. Filters: open/closed, active/inactive.

### F6.8 — View site Report
- Shows current cash balance (per Conventions: `deposits − returns − site cost − advance pay − fooding pay`).
- Shows site revenue (bills vs floor contract).
- Show site total attendance count and total salary.
- Show site total cost.
- Show site labour payouts (advance + fooding).
- Floor breakdown line: per-floor contract value, billed, cost and profit (detail in F15.8).

### F6.9 — Manage site floors
- Site-level master data: Admin defines the site's floors — name (e.g. Basement, Floor-1, Floor-2, Floor-2-Extra), display order (serial), measurement (`sqft`), and `rate_per_sqft`.
- Derived `contract_value = sqft × rate` is the floor's revenue target.
- Floor list feeds the floor dropdown on attendance (F11.1), extra work (F11.2), site cost (F12.1), hidden cost (F12.2), and bill (F14.1) entries.
- Editable while the site is open; a floor cannot be deleted once any record references it.
- Expense categories are company-level (F3.4), not defined here.

### F6.10 — Deactivate/Activate site floors
- Floor may activate or deactivate. Deactivate means no new records allow to create under this floor execpt the SiteBill. But, historic data is accessable.

### F6.11 — Mark floor as done
- This floor work is done, no need new expense or work.
- Floor will deactivate.
- To activate the floor again need to unmark as done first.

### F6.12 — Manage site configuration
- Company Admin views/edits the site's `SiteConfig` (one row per site, auto-created at F6.1 with the defaults above).
- Controls, per entity type: create window, update window, delete window, and per-day quota (see **Site Configuration** above).
- Changes apply to **future** create / edit checks only — existing rows are untouched. Every change is audit-logged (F16).
- Setting a `*_create_window = 0` freezes new entries of that type at the site without deactivating the whole site.
- **Reset to defaults** — Company Admin can reset this site's `SiteConfig` back to its built-in defaults in one action; config-only (no entity data touched), applies to future checks only, audit-logged.
- **Out-of-window override (manual)** — a manager requests the admin to widen a window (temporary `N` covering the date, or `-1` for any past date); the admin grants it, the manager acts, and the admin reviews via the activity / audit trail (F16.2), asking for a fix if misused. No system-enforced approval step.

### F6.13 — View site activity & audit history
- Site-scoped view of the audit trail (F16.2) and activity feed (F16.4): labour transfers (F7.2) and all create / update / delete events for this site, filterable by user, entity type, and date.
- View only — audit entries are never edited here; removal is authorized user.

### F6.14 — Admin records on a site
- By default the Company Admin has config + read access to **all** sites and need not be assigned to any site.
- To **record** on a site, the admin assigns himself to that site (`UserSite`) and joins the **Site Manager** group — he then belongs to both Company Admin and Site Manager (for the self-assigned sites), and the normal write rule (Access Control) applies.
- Reversible any time — the admin can unassign himself or leave the Site Manager group; the change is audit-logged.
- No extra security concern: every row keeps `created_by` / `updated_by`, so who created or changed it is always traceable — if the admin created it, he acted as that site's manager.

---

## F7 — Manage Labour Accounts

### F7.1 — Create / edit labourer
- Manager (with site permission) provides name, `default_salary`, `default_present`, `default_fooding`, and current site.
- System checks name uniqueness.
- System checks the company's **active-labour count** against the plan's active-labour limit (skip if `-1`); at the cap → blocked with an upgrade prompt (F4.4). Reactivation (F7.3) runs the same check.
- Labour starts active, assigned to that site. New attendance / fooding rows seed their values from these defaults if not provide explicitly (each row still keeps its own snapshot).

### F7.2 — Assign / move labourer to site
- Sets or changes the labour's current site (one site at a time — assigning to a new site **is** the move).
- **Gated by `CompanyConfig.allow_labour_transfer`** (F3.5): if `false`, moving an already-assigned labour to a different site is blocked (first assignment of a new labour still allowed).
- Previous site manager no longer creates new records against this labour.
- New site manager now has authority to create new records for this labour.

### F7.3 — Activate / deactivate labour account
- Inactive labour: no new attendance, extra work, or payments; history stays.
- A sealed `LabourWorkSession` (vacation) deactivates the account automatically; returning from vacation requires reactivation **before** any new record (F10.1).

### F7.4 — Update labour salary for a date range
Salary is stored on each DailyAttendance row. `labour.default_salary` is used only when creating new attendance records.
1. Open the labour's attendance page.
2. Select a **single cell** (one row) or a **date range** or **particular site** of rows to re-price.
3. Enter the new salary (must be within the site's `salary_min` / `salary_max`).
4. System updates `salary` on each selected (`editable = true`) row and recomputes the running `site_total_salary` and `floor_total_salary` of those and all later rows.
- Rows already sealed (`editable = false`) cannot be re-priced.
- `attendance_update_window` applies to the `present` field only — salary may be re-priced on any still-editable row regardless of the window.
- No audit logs need for salary change of dailyattendence.

### F7.5 — View and search labourers
- Filter by site, active status; search by name. Shows current site, salary, balance.

### F7.6 — Delete Labour Account
Many labourers work short engagements and never return; their accounts accumulate and must be cleanable without losing site financial data.

**Pre-condition:** Labour balance must be zero before deletion is allowed.

1. Set `labour.deleted_at = now()` — labour hidden from all active views; write to audit log
2. Admin can view and restore deleted labourers within a configurable retention window (default: 30 days)
3. Scheduled job permanently purges labourers whose `deleted_at` exceeds the retention threshold
4. On purge, database-level `ON DELETE SET NULL` cascades handle all foreign key references automatically

---

## F8 — Manage Labour Payments (Advance & Fooding)

A labour is paid through two ledgers — **advance pay** (cash advances) and **fooding pay** (meal allowance). Both are payouts that draw down site cash and reduce the labour's balance.

### F8.1 — Issue advance pay
- Manager picks labour, enters amount, note, date → creates a `LabourAdvancePay` row (`editable = true`).
- Blocked if labour is inactive.
- Running `site_total` (site's cumulative advance) computed from the previous row.

### F8.2 — Issue fooding pay
- Manager picks labour, enters amount (seeded from `default_fooding`), note, date → creates a `LabourFoodingPay` row (`editable = true`).
- Blocked if labour is inactive.
- Running `site_total` (site's cumulative fooding) computed from the previous row.

### F8.3 — Track labour balance
- `balance = balance (from last work session) + earnings from dailyattendence(editable=true) − advance(editable=true) − fooding(editable=true) + returns(editable=true)`.
- Read from the latest carried balance / running totals — no full scan needed.

### F8.4 — View payment history
- Advance and fooding ledgers per labour or per site, ordered by date; each row shows amount + running totals.

---

## F9 — Manage Labour Return

### F9.1 — Record labour return
- Labour may return overpaid money. Manager creates a `LabourReturn` (amount, note, date; `editable = true`).
- Running `site_total` computed from the previous row; increases the labour's balance.

### F9.2 — View return history
- Ledger of returns per labour/site.

---

## F10 — Manage Labour Work Session

A labour works continuously — moving site to site — then takes a vacation. The **period** between two vacations is one work session, recorded as a `LabourWorkSession` plus one `LabourSiteWorkSession` per site touched.

### F10.1 — Create / seal a labour work session (vacation flow)
Triggered when the labour wants to go on vacation:
1. **Review** — all still-`editable` rows (attendance, extra work, advance, fooding, return) are reviewed; any correction is applied now, while they are still editable.
2. **Settle** — a final payment is made based on the current balance (pay out the payable, or collect an overpayment) so the balance reflects reality.
3. **Per-site rollup** — for each site the labour touched this session, create a `LabourSiteWorkSession` aggregating that site's `present`, `extrawork`, `fooding`, `advance`, `salary`, `earnings`, `payable`.
4. **Session record** — create one `LabourWorkSession` linking all its LabourSiteWorkSessions, with:
   - `start_date` = date of the first record after the previous session's end,
   - `end_date` = date of the **last** record in this session,
   - `last_balance` = balance carried in, `balance` = balance carried out.
5. **Seal** — set `editable = false` on every row rolled into the session (now immutable).
6. **Deactivate** the labour account → vacation.

Rules:
- Records created after sealing belong to the **next** session.
- The session `end_date` is the latest sealed record's date.
- Any new record's date must be **≥ the last work session's end_date**.
- After returning from vacation, the account must be **reactivated first** (F7.3) before creating any record.

### F10.2 — View session history
- Timeline of sessions per labour with per-site breakdown (present, earnings, payouts), start/end dates, and carried balances.

---

## F11 — Manage Daily Attendance & Extra Work

### F11.1 — Record daily attendance
- Grain is **labour / floor / day**: Site Manager picks date, floor (from the site's floor list, F6.9), `present` units (full/half/overtime), and `salary` (seeded from the labour default, editable per row).
- A labour may have **multiple attendance rows on the same day** when he works on different floors — uniqueness is **(labour, floor, date)**, not (labour, date).
- Floor is required so the earnings attribute to floor costing.
- Validations: labour active and assigned to this site, site active, floor active, one row per (labour, floor, date), and the site config gates (`attendance_create_window`, `attendance_per_day_limit` — F6.12). New row is `editable = true`.
- Row stores the salary snapshot and running totals: `site_total_present`, `site_total_salary`, `floor_total_present`, `floor_total_salary`.
> **Creatable dates are governed by the site's `attendance_create_window`** (default today + yesterday), must be **≥ the last work session end date**, and **never in the future**. The same pattern (each entity's own `*_create_window` / `*_update_window` / `*_delete_window`, and for labour entities `*_per_day_limit`) applies to extra work, advance, fooding, return, site cost, hidden cost, site cash, site cash return, and site bill. See **Site Configuration** (F6) and F6.12.

### F11.2 — Record extra work
- Separate ledger (`Labour ExtraWork`): site, floor (F6.9), labour, date, amount, note; `editable = true`.
- Kept apart from attendance so ad-hoc extra earnings are tracked on their own.
- Running `site_total_amount` and `floor_total_amount`. Adds to the labour's earnings.

### F11.3 — View attendance & extra work history
- Filter by labour, site, floor, or date range; shows daily rows + running totals.

---

## F12 — Manage Site Expense

### F12.1 — Record site construction cost (SiteCost)
- Manager enters site, date, **floor (required, F6.9)**, **expense category (company-level — F3.4)**, amount, note.
- Row computes running `site_total` and `floor_total` from the previous cost row.
- **Expense category is nullable**: null = "Generalized expense".
- Paid from site cash (draws down the cash balance).

### F12.2 — Record hidden cost (HiddenCost)
- Separate record type from SiteCost — kept apart so permissions/visibility can differ ("hidden" from normal site views).
- It is not paid from site cash; it is paid directly by the company admin.
- Gated by `hiddencost_create_window` / `hiddencost_update_window` / `hiddencost_delete_window` (default `-1` = any date — admin enters hidden costs late); see F6.12.
- It is used to calculate the **profit/revenue** of a site, not the cash balance.
- **Floor is nullable**: set → cost allocates to that floor; null → site-general (not tied to any floor).
- **Expense category is nullable**: null = "Generalized expense".

### F12.3 — View cost history
- Ledger per site, filterable by floor, expense category, record type (site cost / hidden cost), date range.

---

## F13 — Manage Site Cash

### F13.1 — Record cash deposit
- Manager records incoming cash with notes (`SiteCash`).
- Running site cash total increases.

### F13.2 — Record cash return / withdrawal
- Outgoing cash: return to owner or other source with note (`SiteCashReturn`). This is not a site cost — a withdrawal.
- Cannot go below zero — insufficient balance is rejected.
- Running site return total increases.

### F13.3 — View site cash history
- Passbook view: date, type, note, amount (±), running balance per row (per Conventions formula).

---

## F14 — Manage Site Bills

### F14.1 — Create site bill
- Authorized user records a bill: site, date, **floor (required, F6.9)**, amount, note.
- Running `site_total` and `floor_total` per bill row; floor bills accumulate against that floor's contract value (sqft × rate, F6.9).
- Gated by `sitebill_create_window` / `sitebill_update_window` / `sitebill_delete_window` (default `-1` = any date, so the admin/office can record bills anytime); see F6.12.

### F14.2 — View bill history
- Ledger per site, filterable by floor, date range; shows billed vs floor contract value vs remaining receivable.

---

## F15 — Generate Reports

All reports are tenant-scoped and respect site assignments (managers see only their sites).

### F15.1 — Labour balance report
- Per labour: earnings (attendance salary + extra work), advance, fooding, returns, net balance. Read from latest running totals / carried balance.

### F15.2 — Site expense report
- Costs grouped by company expense category / floor for a site and date range (SiteCost and HiddenCost shown separately).

### F15.3 — Site balance report
- `deposits − returns − site cost total − advance pay total − fooding pay total` per site — current spendable cash (matches F6.8; hidden cost excluded).

### F15.4 — Site profit report
- Profit per site: `bills − (labour cost + site cost + hidden cost)`, where labour cost = attendance salary + extra work (payouts are cash, not cost).
- Profit per floor of site: `bills of floor − (labour cost of floor + site cost of floor + hidden cost of floor)`.

### F15.5 — Site labour cost report
- Attendance salary per site / date / floor.
- Extra work per site / date / floor.
- Advance pay and fooding pay per site / date.
- Labour cost per site: `latest attendance site_total_salary` + extra work total.
- Labour cost per floor of site.

### F15.6 — Summary for a date range
- Company-level roll-up between two dates: cash in/out, costs, bills, labour cost, per-site rows.
- Site-level summary.

### F15.7 — Company dashboard
- Open sites overview, balances, subscription expiry alert, recent edits (from audit trail), recent activity.

### F15.8 — Floor costing & revenue report
- Per floor of a site: `sqft`, `rate`, contract value (sqft × rate), billed, remaining receivable (contract − billed), labour cost, construction cost, allocated hidden cost, total cost, profit (billed − total cost), cost per sqft.
- Site-general hidden cost (floor = null) is shown as its own row, **not** pro-rated across floors.
- Reconciles to site profit: `site profit = (Σ floor profit) − general hidden cost`, which equals `bills − (labour + site cost + all hidden cost)`.

---

## F16 — Record Edits & Audit Trail

Edits happen directly; the `editable` flag is the hard lock, and the audit log makes every live edit accountable.

### F16.1 — Edit / delete a record (direct, with auto audit)
- Allowed only on rows that are still `editable = true` (sealed rows are immutable — see F10) **and** whose date is inside the site's `*_update_window` (for edits) or `*_delete_window` (for deletes) — F6.12. Sealed always blocks; otherwise the stricter of the two limits wins.
- An authorized user edits or deletes a record from its own module (attendance F11, extra work F11, advance/fooding F8, return F9, cash F13, cost/hidden cost F12, bill F14, plus master data).
- In one transaction the system:
  1. Applies the change (financial/ledger rows are **soft-deleted**, not hard-deleted).
  2. Writes an **audit log entry**: company, actor, timestamp, target record type + id, action (update/delete), **before snapshot**, **after snapshot**, and a **note (required for update/delete of financial records)**.
  3. Bumps the record's `updated_at`.
  4. Recalculates running totals of all later rows in the same ledger (per floor and per site) so the chain stays consistent.

### F16.2 — View audit trail
- Any authorized user views the log, filtered by record, site, user, action, or date range.
- Each entry shows who changed what, when, the before/after values, and the note.

### F16.3 — Remove audit log entries
- Only Admin (or an explicitly authorized user) can **soft delete** audit entries. No one can **edit** an entry. The company then loses access to that data — only the system can see and manage it; if a company removes audit logs accidentally, the system can restore them via support. A scheduled cron permanently deletes soft-deleted audit logs after a retention period.
- Even after removal, the affected record's `updated_at` still shows it was modified — tamper-evident backstop.

### F16.4 — Activity view (admin oversight)
- The admin reviews an **activity feed** built from the audit trail (F16.2): all records created / updated / deleted, filterable by site, user, entity type, and date.
- This is the verification mechanism — instead of a per-row `verified` flag, the admin watches activity (especially after granting an out-of-window override, F6.12) and manually asks a manager to correct anything wrong.

> **Note** — there is intentionally no admin override to edit a **sealed** (`editable = false`) record. The seal is the hard boundary; if a settled session truly needs a fix, the correction is done by a system user (F2.9), not a normal edit.
