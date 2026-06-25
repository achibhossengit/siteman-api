# SiteMan — Feature Details

## Conventions
- **Tenant isolation** — every tenant row carries `company_id`; See **Access Control & User Model**.
- **Running totals** — ledger rows store a **per-site** cumulative `site_total*` only; **per-billing-category figures are aggregated on read (no stored `billing_total*`)**. Update all later rows' `site_total*` after a relevant update/delete.
- **`is_sealed` flag** — every labour-linked row (attendance, extra work, advance pay, fooding pay, return) starts `is_sealed = false` (editable); a work-session seal (F10) sets `is_sealed = true` (immutable).
- **Direct edit + activity log** — authorized users edit/delete directly; the system auto-writes an **activity log** entry (actor, time, before/after, note). Ledger rows are **soft-deleted**. Activity logs are **permanent** — no one, not even Company Admin, can edit or delete them (F16.3).
- every model keeps `created_at`, `created_by`, `updated_at`
- **Removing a category** — `billing_category` / `custom_category` are nullable. Deleting one prompts the admin to either (a) **delete & set the FK null** on all its rows (`ON DELETE SET NULL`), or (b) **merge** — re-point its rows to another same-scope category, then delete it. The action is **activity-logged and not undoable**; the admin must confirm first. `updated_at` is untouched (it is not a per-row user edit). See F3.4 / F6.9 / F6.15.
- **Future dates blocked** — no record's `date` may be in the future, for every date-bearing entity.
- **Configuration tiers**
  - **System config** (`SystemConfig`, single global row, System Admin) — Governs platform behaviour only. See **System Configuration** under F2.
  - **Company config** (`CompanyConfig`, one per company, Company Admin) — per-tenant feature flags, e.g. `allow_labour_transfer` (default `true`); created with its **own built-in defaults** at registration. See **Company Configuration** under F3.
  - **Site config** (`SiteConfig`, one per site, Company Admin) — one shared daily-record create/update/delete window + per-labour/day quotas. See **Site Configuration** under F6.

## Roles
- **System Admin** — manages all companies and subscriptions.
- **System Manager** — monitors subscriptions and payments (assigned permissions).
- **Company Admin** — full control of one company: users, sites, labour, subscription.
- **Company Manager** — manages assigned sites and reviews the activity log for them.
- **Site Manager** — records attendance, cash, and cost for permitted sites; edits are logged.

## Access Control & User Model
### One `User` table, two kinds of user — split by Django's `is_staff`:
- **System** (`is_staff = true`, often `is_superuser`; `company_id = null`) — platform staff (F2). Sign in to the **Django admin site** (`/admin/`) with **session auth**; cross-company.
- **Tenant** (`is_staff = false`, `company_id` set) — company user (F5). Use the **Tenant API** (`/api/…`) with **JWT**, auto-scoped to its company.
- One phone = one account, so a person is system **or** tenant — Django's `is_staff` distinguishes them (no separate `scope` column). Tenant login (F1.1) issues JWT; the token carries `user_id`, `company_id`, groups. A system user reaches tenant data only through the Django admin / explicit platform actions (e.g. F2.9), never the tenant JWT API.
- **Why two auth backends** (session for admin, JWT for API)
  - Different surfaces, different hardening: the **admin panel uses Django session auth**, the **tenant API uses JWT**. The admin site is an isolated route (its own rate-limit / IP-allowlist), kept off the tenant attack surface.
  - `is_staff` gates the admin site — a tenant user (`is_staff = false`) can never reach it; and a system account is in no company group, so it cannot act on tenant API data. Shrinks coupling and blast radius.
  - It avoids the account enumeration a shared login leaks (which phones are platform staff). OTP generation and BD-phone normalization live in a **shared service**; each surface is a thin wrapper applying its own auth + policy — **one core logic, two doors**.

### Who can do what — two independent layers:
- **Capability** (*what*) — a Django **Group**: System Admin / System Manager; Company Admin / Company Manager / Site Manager. Global within its tier (system vs company), never per-site.
- **Scope** (*which sites*) — **`UserSite`** links a tenant user to sites. A site can have many managers; a user many sites.
- A **write** is allowed when: capability (Group) **+** assigned to the site (`UserSite`) **+** inside the entity's window (F6.12) **+** the row is **unsealed** (`is_sealed = false`). The Company Admin manages all sites by default, but to **record** on a site must self-assign and join the Site Manager group (F6.14) — the same write rule then applies.
---

## F1 — Manage Authentication

### F1.1 — Login
- User gives phone number and password.
- System validates BD phone number (normalize to `+8801XXXXXXXXX`, reject invalid operator codes).
- System verifies password against the user account; account must be active and company must be active.
- System sends a digit OTP (short expiry, limited attempts) via the user's chosen channel — **SMS or email**.
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

### F1.6 — Manage Profile
- Logged-in user edits name, phone number, email.
- OTP goes to the user's chosen channel (SMS or email). A new **phone** is verified by SMS to the new number; a new **email** by a code to the new address (sets `email_verified = true`).
- The pending new value is held in **cache** until the OTP is verified, then swapped onto the account — the old value stays active until then. Phone stays globally unique (rejected if already registered).

---

## F2 — Manage Platform
System-level users; not tied to any company.

> **MVP scope** — in the MVP the entire platform side (F2.*) is operated through the **Django admin site** (`/admin/`, Django session auth); there is no platform frontend or public platform API yet, and system users are Django staff/superusers. The dedicated **Platform API** + system OTP/JWT login (F2.1) and custom actions like company reset (F2.11) are a **later phase**. The **tenant** side (F1, F3–F16) ships with its real API + frontend now.

### F2.1 — System user login
- Platform staff sign in to the **Django admin site** with **session auth** (no company context) — MVP. A dedicated OTP + JWT platform-API login is a later phase (see F2 MVP note). Identified by `is_staff = true`.

### F2.2 — View and search all companies
- List with open site count, billing status, activity, and activity logs.

### F2.3 — Activate / deactivate a company
- Deactivated company: all its users blocked from login; data retained.

### F2.4 — Manage subscription plans
- System Admin creates/edits plan tiers: **open-site limit**, **active-user limit**, **active-labour limit**, and one or more **durations** — each duration (any month count, e.g. 1 / 3 / 6 / 12 / 24) with its own **per-month rate**. Durations are stored as `plan_price` rows (not fixed columns), so adding a new duration needs **no schema change**. Each limit `-1` = no limit; `N` = cap.
- Price changes apply to new purchases/renewals only; running subscriptions keep their rate snapshot.
- Custom plan: limits and price negotiated and set manually per company.
- **Manual payment** — a System user can record a subscription payment that bypasses the gateway (offline / bank / cash, or after a gateway failure) for any company.

### F2.5 — Monitor subscription status
- Dashboard of all companies: plan, active / expiring soon / expired, revenue summary.

### F2.6 — Create system users
- System Admin creates platform staff accounts (`is_staff = true`, `company_id = null`); assigned a system group (F2.7).

### F2.7 — Assign system roles
- System Admin assigns staff to system-level groups (System Admin / System Manager).

### F2.8 — Assign system-level permissions
- Fine-grained platform permissions per staff user (e.g., System Manager: monitor only).

### F2.9 — Data correction on sealed/closed data
- Only a system user can correct a sealed (`is_sealed = true`) row or restore/repair a closed site's data on support request — the company side has no such override.

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
5. On a valid OTP, in **one transaction** the system **hard-deletes** all tenant data (FK-safe order): sites, billing categories, labours, work sessions, every ledger (attendance, extra work, advance, fooding, return, cash, cost, bill), all per-ledger categories, all **non-admin** users (+ `UserSite` links), and the company's **activity logs**. `CompanyConfig` returns to built-in defaults; all `SiteConfig` rows are gone with their sites.
6. **Kept:** the Company record, **all Company Admin** accounts, and the active subscription (`plan`, `paid_until` untouched) — the company is now like new with zero entities.
7. The system writes a **platform-level reset log** (system user, company id, timestamp, OTP-verified) stored system-side — it survives the wipe (the company-side activity log cannot, per step 5).
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
- System saves and records the change in the activity log.

### F3.4 — Manage custom categories
- **One model** `custom_category` (`site_id`, `scope`, `name`, `note`, `display_order`, `is_active`) replaces the old per-ledger type tables. `scope` (enum) ties a category to one ledger: `sitecost` (F12.1), `hiddencost` (F12.2), `sitecash` (F13.1), `sitecashreturn` (F13.2), `sitebill` (F14.1). Admin creates/edits each.
- **Site-scoped** — each **site** owns its own category set; the ledger dropdown filters by **(site, scope)**. A site may start with **zero** categories or some defaults.
- **Optional on the ledger** — each ledger's `custom_category_id` is **nullable**. On create the user is prompted to pick one **only when** that site has `count(scope) > 0`; otherwise (or by choice) it stays null.
- **Deactivate** — hidden from new-entry dropdowns; existing rows keep their link.
- **Remove (delete or merge)** — deleting a category prompts the admin to choose: **(a) set null** — the FK on every referencing row becomes null (`ON DELETE SET NULL`); or **(b) merge** — re-point its rows to another same-site, same-`scope` category (plain `UPDATE`), then delete the emptied one. One activity log entry is written (`action = delete` or `merge`). The action is **not undoable** — the admin must confirm first.

### F3.5 — Manage company configuration
- Company Admin views/edits the company's `CompanyConfig` (one row per company, auto-created at F3.1 with its own built-in defaults).
- Tenant-wide feature flags that apply to every site of the company. The change is activity-logged.
- Example: **`allow_labour_transfer`** (bool, default `true`) — when `false`, moving a labour from one site to another (F7.2) is blocked company-wide; a labour stays on its original site for its whole lifecycle. Existing assignments are untouched.
- **Reset to defaults** — Company Admin can reset `CompanyConfig` back to its built-in defaults in one action; config-only (no entity data touched), activity-logged.

---

## F4 — Manage Company Subscription

### F4.1 — View subscription status
- Company Admin sees current plan, expiry date, payment history, and **usage vs limit** for each capped resource: open sites, active users, active labour.

### F4.2 — Pay for plan
- Admin picks a plan tier and one of its offered durations (any `plan_price` for the tier).
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
Pricing is driven by **open site count**; the user and labour caps default to `-1` (no limit) today and exist so a tier can be tightened later without a schema change. Longer durations get a **per-month discount**. Prices in BDT. The durations below (1 / 6 / 12 months) are the **current offering** only — they are `plan_price` rows, not fixed by schema, so any duration can be added as data.

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
- System will creates user under the same company (`is_staff = false`, `company` = admin's company).
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

### F5.6 — Delete (deactivate) user
- **No user is ever orphaned.** Every reference to a user (`created_by` on records, `actor_id` on activity logs, etc.) is **`ON DELETE RESTRICT`** — a user who has acted on anything **cannot be hard-deleted**.
1. Set `user.deleted_at = now()`, disable the account; write to activity log. The account is hidden and can no longer log in.
2. Admin can view and restore deactivated users at any time.
3. Hard purge happens **only** if the user has **zero** references (e.g. an account that never acted), or wholesale via a **company reset** (F2.11). Otherwise the user stays soft-deleted/deactivated permanently — its `created_by` / `actor_id` history stays intact.

### F5.7 — View and search users
- List company users with filters: role, site, active status; search by name/phone.

---

## F6 — Manage Sites

### Site States (reference)
Two independent state axes for a site:

| Field | Value | Meaning |
|---|---|---|
| `closed_at` | `null` | **Open** — site is ongoing. Counts toward the plan's open-site limit. |
| `closed_at` | timestamp | **Closed** — work permanently done. Company users see only the closure summary; detail rows stay in the same DB but are hidden, then a cron purges them 30 days after `closed_at` (except `is_sealed = false` rows). Does not count toward the plan limit. Reopen possible until purge. |
| `is_active` | `True` | **Active** — new data (attendance, cash, cost) can be recorded. |
| `is_active` | `False` | **Inactive** — temporarily paused. No new data can be created. Old data remains accessible. Can be reactivated at any time. |

> A site may be open (`closed_at=null`) and inactive (`is_active=False`) at the same time — temporarily paused but still ongoing. The plan limit counts all open sites regardless of active/inactive state.

### Site Configuration (reference)
Every site has a one-to-one `SiteConfig` (managed in F6.12), auto-created with sensible defaults and editable by the Company Admin. It lets each site tune how strictly records may be created and edited — without code changes.

**Daily-record window** — one shared triplet `daily_record_create_window` / `daily_record_update_window` / `daily_record_delete_window` (default `1` each) gates **all eight daily ledgers**: daily attendance, extra work, advance pay, fooding pay, return, site cost, site cash, site cash return. Scale:

| Value | Meaning |
|---|---|
| `-1` | Any date ≤ today (no lower bound) |
| `0` | Disabled — no date qualifies (turns that action off) |
| `N ≥ 1` | Last `N` days including today, i.e. `[today − (N−1) … today]` (1 = today only, 2 = today + yesterday, 3 = today + 2 days back, …) |

> Future dates are **always** rejected, regardless of any window.
> **Hidden cost** and **site bill** are **not** window-gated — they are admin/office records, allowed on any date ≤ today (late entries expected).

**Per-labour/day quota** — `attendance_per_labour_per_day_limit`, `fooding_per_labour_per_day_limit`, `advance_per_labour_per_day_limit`:

| Value | Meaning |
|---|---|
| `-1` | Unlimited |
| `0` | Blocked — no rows that day |
| `N ≥ 1` | At most `N` rows per labour per date (across billing categories). Applies to **new** rows only; there is no DB uniqueness (F11.1). |

Defaults: attendance `1`, fooding `1`, advance `-1`.

**Cross-site, same date** — there is no separate multisite flag. By default a labour has one record per date; to record the same labour/date at a **different** site, first free the existing row (remove it) or transfer the labour to the new site (F7.2). To genuinely allow both sites on the same date, raise the relevant `*_per_labour_per_day_limit`.

**Out-of-window override (manual)** — there is no per-row verification. To touch a date outside the current window, a manager asks the admin; the admin widens the daily-record window (a temporary `N` covering the date, or `-1` to allow any past date), the manager creates/edits/deletes, and the admin reviews the result via the date-based activity log (F16.2). If misused, the admin asks the manager to correct it — no system-enforced approval step.

**Validation ranges** — per-site, customizable by Company Admin. `labour.default_salary` / `default_fooding` are validated against the labour's **current_site** config at create/edit time:
- `attendance_present_choices` — explicit allowed set for the `present` value, e.g. `[0, 0.5, 1, 1.5, 2, 3]` (only these accepted; the set is not a uniform step, so it is a list not a min/max).
- `salary_min` / `salary_max` — bounds for attendance `salary` and `labour.default_salary` (e.g. 500–1500).
- `fooding_min` / `fooding_max` — bounds for fooding pay amount and `labour.default_fooding` (e.g. 50–200).
- `advance_min` / `advance_max` — bounds for a **single** advance row amount (e.g. 0–10000); caps the per-row amount, not the daily count (`advance_per_labour_per_day_limit`).

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
3. **Build the closure summary** (immutable snapshot): totals from SiteCost, HiddenCost, SiteBill, DailyAttendance (total present, total salary), ExtraWork totals, total cost, total bills, total paid bills, profit, billing-category contract vs billed — everything the admin needs after the detail is gone.
4. **Access changes immediately** — authorized users now see **only the summary**; the detail rows stay in the same DB but are hidden from the company side.
5. **Cron purge** — a scheduled job deletes the detail rows of any site whose `closed_at` is **more than 30 days** old, **except** rows still `is_sealed = false`. Those belong to an as-yet-unsealed period; they are kept until the next session seals them (`is_sealed = true`), after which a later cron run may delete them.

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
- Shows site revenue (bills vs billing-category contract).
- Show site total attendance count and total salary.
- Show site total cost.
- Show site labour payouts (advance + fooding).
- Billing-category breakdown line: per-billing-category contract value, billed, cost and profit (detail in F15.8).

### F6.9 — Manage billing categories
- Site-level master data: Admin defines the site's **billing categories** — header row `billing_category` (`id`, `company_id`, `site_id`, `name` e.g. Basement / Floor-1 / Floor-2-Extra, `display_order`, `is_active`).
- Measurement lives in a **1:1 `billing_category_details`** row: `sqft`, `rate_per_sqft`, `custom_amount`.
- **Optional** — billing categories are not mandatory. A site may run with **none** (simple project, or to avoid complexity), so every ledger's `billing_id` is **nullable**; categories can be added later and old rows keep `null`.
- Billing-category list feeds the dropdown on attendance (F11.1), extra work (F11.2), site cost (F12.1), hidden cost (F12.2), and bill (F14.1) entries.
- Editable while the site is open. **Removing** a billing category prompts the admin to delete-with-set-null or merge-into-another — see F6.15.

### F6.10 — Deactivate/Activate billing categories
- A billing category may activate or deactivate. Deactivate means no new records allow to create under this billing category execpt the SiteBill. But, historic data is accessable.

### F6.11 — Mark billing category as done
- This billing category's work is done, no need new expense or work.
- Billing category will deactivate (`is_done = true`).
- To activate the billing category again need to unmark as done first.

### F6.12 — Manage site configuration
- Company Admin views/edits the site's `SiteConfig` (one row per site, auto-created at F6.1 with the defaults above).
- Controls: one shared daily-record create / update / delete window (gates the eight daily ledgers) + the per-labour/day quotas (attendance, fooding, advance) — see **Site Configuration** above.
- Changes apply to **future** create / edit checks only — existing rows are untouched. Every change is activity-logged (F16).
- Setting `daily_record_create_window = 0` freezes new daily-ledger entries at the site without deactivating the whole site.
- **Reset to defaults** — Company Admin can reset this site's `SiteConfig` back to its built-in defaults in one action; config-only (no entity data touched), applies to future checks only, activity-logged.
- **Out-of-window override (manual)** — see **Site Configuration** (F6): the admin temporarily widens the daily-record window, the manager acts, and the admin reviews via the activity log (F16.2).

### F6.13 — View site activity log
- Site-scoped view of the **activity log** (F16.2 / F16.4): labour transfers (F7.2), category removals/merges (F6.15), and all create / update / delete events for this site, filterable by user, entity type, and date.
- **View only** — activity entries are **never** edited or deleted (F16.3). Sensitive events (hidden cost, company-level) are hidden from site / non-admin users (F16.2).

### F6.14 — Admin records on a site
- By default the Company Admin has config + read access to **all** sites and need not be assigned to any site.
- To **record** on a site, the admin assigns himself to that site (`UserSite`) and joins the **Site Manager** group — he then belongs to both Company Admin and Site Manager (for the self-assigned sites), and the normal write rule (Access Control) applies.
- Reversible any time — the admin can unassign himself or leave the Site Manager group; the change is activity-logged.
- No extra security concern: every row keeps `created_by`, and every change is in the **activity log** (`actor_id`), so who created or changed it is always traceable — if the admin created it, he acted as that site's manager.

### F6.15 — Remove a billing category (delete or merge)
A billing category that already has records can be removed two ways; the admin is prompted to pick, **confirms**, and the choice is **activity-logged and not undoable**.

1. **Delete & set null** — the category is deleted and every referencing ledger row (attendance, extra work, site cost, hidden cost, site bill) has its `billing_id` set to **null** (`ON DELETE SET NULL`). Those rows become site-general (no billing category).
2. **Merge into another (same site)** — the admin picks a target A; the source B's rows are re-pointed to A (plain `UPDATE billing_id = A`), then B is deleted (now unreferenced). `updated_at` is untouched; `site_total*` is unaffected (site never changes); per-category figures are aggregated on read (Conventions).

One activity log entry records the action (`action = delete` or `merge`, with affected-row count). `billing_category_details` cascades away with the deleted category.

> Custom-category removal (sitecost / hiddencost / sitecash / sitecashreturn / sitebill) works the same way — see **F3.4**.

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
- A sealed `LabourSession` (vacation) deactivates the account automatically; returning from vacation requires reactivation **before** any new record (F10.1).

### F7.4 — Update labour salary for a date range
Salary is stored on each DailyAttendance row. `labour.default_salary` is used only when creating new attendance records.
1. Open the labour's attendance page.
2. Select a **single cell** (one row) or a **date range** or **particular site** of rows to re-price.
3. Enter the new salary (must be within the site's `salary_min` / `salary_max`).
4. System updates `salary` on each selected (`is_sealed = false`) row and recomputes the running `site_total_salary` of those and all later rows.
- Rows already sealed (`is_sealed = true`) cannot be re-priced.
- `daily_record_update_window` applies to the `present` field only — salary may be re-priced on any still-unsealed row regardless of the window.
- No activity log needed for salary change of daily attendance.

### F7.5 — View and search labourers
- Filter by site, active status; search by name. Shows current site, salary, balance.

### F7.6 — Delete Labour Account
Many labourers work short engagements and never return; their accounts accumulate and must be cleanable without losing site financial data.

**Pre-condition:** Labour balance must be zero before deletion is allowed.

1. Set `labour.deleted_at = now()` — labour hidden from all active views; write to activity log.
2. Admin can view and restore deactivated labourers at any time.
3. A labour referenced by any ledger row **cannot be hard-deleted** (`ON DELETE RESTRICT`) — it stays soft-deleted/deactivated so site financials keep their link. Hard purge only when it has zero references using corn job, or via a company reset (F2.11).

---

## F8 — Manage Labour Payments (Advance & Fooding)

A labour is paid through two ledgers — **advance pay** (cash advances) and **fooding pay** (meal allowance). Both are payouts that draw down site cash and reduce the labour's balance.

### F8.1 — Issue advance pay
- Manager picks labour, enters amount, note, date → creates a `LabourAdvancePay` row (`is_sealed = false`).
- Blocked if labour is inactive.
- Running `site_total` (site's cumulative advance) computed from the previous row.

### F8.2 — Issue fooding pay
- Manager picks labour, enters amount (seeded from `default_fooding`), note, date → creates a `LabourFoodingPay` row (`is_sealed = false`).
- Blocked if labour is inactive.
- Running `site_total` (site's cumulative fooding) computed from the previous row.

### F8.3 — Track labour balance
- `balance = balance (from last work session) + earnings from dailyattendence(is_sealed=false) − advance(is_sealed=false) − fooding(is_sealed=false) + returns(is_sealed=false)`.
- Read from the latest carried balance / running totals — no full scan needed.

### F8.4 — View payment history
- Advance and fooding ledgers per labour or per site, ordered by date; each row shows amount + running totals.

---

## F9 — Manage Labour Return

### F9.1 — Record labour return
- Labour may return overpaid money. Manager creates a `LabourReturn` (amount, note, date; `is_sealed = false`).
- Running `site_total` computed from the previous row; increases the labour's balance.

### F9.2 — View return history
- Ledger of returns per labour/site.

---

## F10 — Manage Labour Work Session

A labour works continuously — moving site to site — then takes a vacation. The **period** between two vacations is one work session, recorded as a `LabourSession` plus one `LabourSiteSession` per site touched. Ledger rows belong to a session by **date range + labour** (`[start_date … end_date]`), not a per-row FK.

### F10.1 — Create / seal a labour work session (vacation flow)
Triggered when the labour wants to go on vacation:
1. **Review** — all still-**unsealed** (`is_sealed = false`) rows (attendance, extra work, advance, fooding, return) are reviewed; any correction is applied now, while they are still unsealed.
2. **Settle** — a final payment is made based on the current balance (pay out the payable, or collect an overpayment) so the balance reflects reality.
3. **Per-site rollup** — for each site the labour touched this session, create a `LabourSiteSession` aggregating that site's `present`, `extrawork`, `fooding`, `advance`, `salary`, `earnings`, `payable`.
4. **Session record** — create one `LabourSession` (links its LabourSiteSessions), with:
   - `start_date` = the **first** (earliest) entity date in this session, `end_date` = the **last** (latest) entity date;
   - carried totals `total_present`, `total_salary`, `total_extrawork`, `total_earnings`, `total_taken`, and `balance` (carried forward to the next session);
   - both `start_date` and `end_date` must be **after** the previous session's `created_at` date.
5. **Seal** — set `is_sealed = true` on every one of this labour's rows whose `date` falls in `[start_date … end_date]` (rows bind to the session by **date range + labour**, not a stored FK).
6. **Deactivate** the labour account → vacation.

Rules:
- **One session per labour per day** — a labour may have at most one `LabourSession` created on a given day (`(labour, created_at::date)` unique).
- **New record date gate** — any new ledger entity's `date` must be **> the last work session's `created_at` date** (and never in the future).
- **Amend a sealed day** — to create a record after a session was already made the same day, **delete that session** (F10.3), create the record, then create the session again.
- Records created after sealing belong to the **next** session.
- After returning from vacation, the account must be **reactivated first** (F7.3) before creating any record.

### F10.2 — View session history
- Timeline of sessions per labour with per-site breakdown (present, earnings, payouts), start/end dates, and carried totals/balance.

### F10.3 — Delete a work session (unseal)
- Deleting a `LabourSession` **unseals** it: every one of this labour's rows with `date` in `[start_date … end_date]` is set back to `is_sealed = false`, then the session row (and its `LabourSiteSession` rollups) is deleted. One activity log entry is written.
- Use when an already-sealed day must be amended: **delete the session → create/correct the entity → create the session again** (re-seal).

---

## F11 — Manage Daily Attendance & Extra Work

### F11.1 — Record daily attendance
- Grain is **labour / day** (optionally split by billing category): Site Manager picks date, optional billing category (from the site's list, F6.9), `present` units (full/half/overtime), and `salary` (seeded from the labour default, editable per row).
- **No DB uniqueness** on (labour, billing_category, date) — a labour may have **multiple attendance rows on the same date** (different billing categories, or the same one). New rows per labour/date are gated by **`attendance_per_labour_per_day_limit`** (config affects **new** rows only; existing rows untouched).
- Billing category is **optional**; when set, the earnings attribute to billing-category costing. When the site has none it stays null.
- Validations: labour active and assigned to this site, site active, billing category active (if chosen), and the site config gates (`daily_record_create_window`, `attendance_per_labour_per_day_limit` — F6.12). New row is `is_sealed = false`.
- Row stores the salary snapshot and **per-site** running totals: `site_total_present`, `site_total_salary`.
> The shared daily-record window + the per-labour/day limits gate the eight daily ledgers — see **Site Configuration** (F6) / F6.12. A creatable date must additionally be **> the last work session's `created_at` date** and **never in the future** (F10).

### F11.2 — Record extra work
- Separate ledger (`ExtraWork`): site, **optional** billing category (F6.9), labour, date, amount, note; `is_sealed = false`.
- Kept apart from attendance so ad-hoc extra earnings are tracked on their own.
- Running per-site `site_total_amount`. Adds to the labour's earnings.
- **No DB uniqueness** — multiple extra-work rows per labour/date are allowed (gated by config).

### F11.3 — View attendance & extra work history
- Filter by labour, site, billing category, or date range; shows daily rows + running totals.

---

## F12 — Manage Site Expense

### F12.1 — Record site construction cost (SiteCost)
- Manager enters site, date, **optional billing category (F6.9)**, **optional sitecost category** (`custom_category`, `scope = sitecost` — F3.4), amount, note.
- Row computes running per-site `site_total` from the previous cost row.
- Both categories are **optional** — prompted only when entries exist (billing categories for the site, or `custom_category` of that scope for this site); else null.
- Paid from site cash (draws down the cash balance).

### F12.2 — Record hidden cost (HiddenCost)
- Separate record type from SiteCost — kept apart so permissions/visibility can differ ("hidden" from normal site views).
- It is not paid from site cash; it is paid directly by the company admin.
- **Not** gated by the daily-record window — hidden cost is an admin/office record, allowed on any date ≤ today (entered late); see F6.12.
- It is used to calculate the **profit/revenue** of a site, not the cash balance.
- **Billing category is optional**: set → cost allocates to that billing category; null → site-general (not tied to any billing category, F15.8).
- **Hiddencost category optional** (`custom_category`, `scope = hiddencost` — F3.4; prompted when any exist).

### F12.3 — View cost history
- Ledger per site, filterable by billing category, category (sitecost / hiddencost), record type (site cost / hidden cost), date range.

---

## F13 — Manage Site Cash

### F13.1 — Record cash deposit
- Manager records incoming cash with notes (`SiteCash`); **optional sitecash category** (`custom_category`, `scope = sitecash` — F3.4; prompted when any exist).
- Running site cash total increases.

### F13.2 — Record cash return / withdrawal
- Outgoing cash: return to owner or other source with note (`SiteCashReturn`); **optional sitecashreturn category** (`custom_category`, `scope = sitecashreturn` — F3.4). This is not a site cost — a withdrawal.
- Cannot go below zero — insufficient balance is rejected.
- Running site return total increases.

### F13.3 — View site cash history
- Passbook view: date, type, note, amount (±), running balance per row (per Conventions formula).

---

## F14 — Manage Site Bills

### F14.1 — Create site bill
- Authorized user records a bill: site, date, **optional billing category (F6.9)**, **optional sitebill category** (`custom_category`, `scope = sitebill` — F3.4), amount, note.
- Running per-site `site_total` per bill row; bills accumulate against that billing category's contract value (sqft × rate, F6.9) when set.
- **Not** gated by the daily-record window — site bill is an admin/office record, allowed on any date ≤ today (recorded anytime); see F6.12.

### F14.2 — View bill history
- Ledger per site, filterable by billing category, date range; shows billed vs billing-category contract value vs remaining receivable.

---

## F15 — Generate Reports

All reports are tenant-scoped and respect site assignments (managers see only their sites).

### F15.1 — Labour balance report
- Per labour: earnings (attendance salary + extra work), advance, fooding, returns, net balance. Read from latest running totals / carried balance.

### F15.2 — Site expense report
- Costs grouped by ledger category (sitecost / hiddencost) / billing category for a site and date range (SiteCost and HiddenCost shown separately).

### F15.3 — Site balance report
- `deposits − returns − site cost total − advance pay total − fooding pay total` per site — current spendable cash (matches F6.8; hidden cost excluded).

### F15.4 — Site profit report
- Profit per site: `bills − (labour cost + site cost + hidden cost)`, where labour cost = attendance salary + extra work (payouts are cash, not cost).
- Profit per billing category of site: `bills of category − (labour cost of category + site cost of category + hidden cost of category)`.

### F15.5 — Site labour cost report
- Attendance salary per site / date / billing category.
- Extra work per site / date / billing category.
- Advance pay and fooding pay per site / date.
- Labour cost per site: `latest attendance site_total_salary` + extra work total.
- Labour cost per billing category of site.

### F15.6 — Summary for a date range
- Company-level roll-up between two dates: cash in/out, costs, bills, labour cost, per-site rows.
- Site-level summary.

### F15.7 — Company dashboard
- Open sites overview, balances, subscription expiry alert, recent edits (from activity log), recent activity.

### F15.8 — Billing-category costing & revenue report
- Per billing category of a site: `sqft`, `rate_per_sqft`, contract value (sqft × rate, or `custom_amount`), billed, remaining receivable (contract − billed), labour cost, construction cost, allocated hidden cost, total cost, profit (billed − total cost), cost per sqft.
- Site-general hidden cost (billing_category = null) is shown as its own row, **not** pro-rated across billing categories.
- Reconciles to site profit: `site profit = (Σ billing-category profit) − general hidden cost`, which equals `bills − (labour + site cost + all hidden cost)`.

---

## F16 — Record Edits & Activity Log

Edits happen directly; the `is_sealed` flag is the hard lock, and the **activity log** makes every live edit accountable. The activity log replaces the old per-row `updated_by` — the actor lives on `activity_log.actor_id`.

### F16.1 — Edit / delete a record (direct, with auto activity log)
- Allowed only on rows that are still **unsealed** (`is_sealed = false`; sealed rows are immutable — see F10) **and** whose date is inside the site's `daily_record_update_window` (for edits) or `daily_record_delete_window` (for deletes) — F6.12. Hidden cost / site bill are not window-gated. Sealed always blocks; otherwise the window limit applies.
- An authorized user edits or deletes a record from its own module (attendance F11, extra work F11, advance/fooding F8, return F9, cash F13, cost/hidden cost F12, bill F14, plus master data).
- In one transaction the system:
  1. Applies the change (financial/ledger rows are **soft-deleted**, not hard-deleted).
  2. Writes an **activity log entry**: company, actor, timestamp, target record type + id, action (`create` / `update` / `delete` / `merge`), **before snapshot**, **after snapshot**, and a **note (required for update/delete of financial records)**.
  3. Bumps the record's `updated_at` — **only** for an explicit user field edit. A **category removal/merge** (F3.4 / F6.15) re-points or nulls the row's category FK and leaves `updated_at` untouched.
  4. Recalculates the per-**site** running totals (`site_total*`) of all later rows in the same ledger so the chain stays consistent.

### F16.2 — View the activity log
- Any authorized user views the log, filtered by record, site, user, action, or date range.
- Each entry shows who changed what, when, the before/after values, and the note.
- **Visibility** — a Site Manager / Company Manager sees all activity for their **authorized sites**, **except sensitive entries**: hidden cost (admin-only, F12.2) and company-level events. Those are shown to the Company Admin only.

### F16.3 — Activity logs are permanent
- Activity entries can **never** be edited or deleted — **not even by the Company Admin**. There is no soft-delete and no removal action on the tenant side.
- The only way they leave the database is a full **company reset** (F2.11), which hard-deletes them system-side under OTP dual-control.
- This makes the log a tamper-evident backstop: the affected record's `updated_at` and the permanent entry together always show that, and how, it was modified.

### F16.4 — Activity view (admin oversight)
- The admin reviews the **activity log** (F16.2): all records created / updated / deleted / merged, filterable by site, user, entity type, and date.
- This is the verification mechanism — instead of a per-row `verified` flag, the admin watches activity (especially after granting an out-of-window override, F6.12, or running a merge, F6.15) and manually asks a manager to correct anything wrong.

> **Note** — there is intentionally no admin override to edit a **sealed** (`is_sealed = true`) record. The seal is the hard boundary; if a settled session truly needs a fix, the correction is done by a system user (F2.9), not a normal edit.
