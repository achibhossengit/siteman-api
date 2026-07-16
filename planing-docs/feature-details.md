# SiteMan — Feature Details

## Conventions
- **Tenant isolation** — every tenant row carries `company_id`; See **Access Control & User Model**.
- **Totals on read** — ledger rows do **not** store running `site_total*` fields. Site balance, profit, labour balance, and as-of-date figures are **aggregated on read** (`SUM` / filters by `site_id`, `type`, `date`). Indexes on `(site_id, date)` / `(site_id, type, date)` support this. Prefer pagination for history lists.
- **Merged ledgers** — related payout/expense streams share one table with a `type` discriminator:
  - `attendance` — `type = attendance | extrawork` (F9)
  - `labour_pay_return` — `type = advance | fooding | return` (F7)
  - `site_cost` — `type = food | equipment | others` (F10); `hidden_cost` separate for visibility/permissions
  - `site_cash` — `type = cash | return` (F11)
- **`is_sealed` flag** — every labour-linked row (`attendance`, `labour_pay_return`) starts `is_sealed = false` (editable); a work-session seal (F8) sets `is_sealed = true` (immutable).
- **Direct edit + activity log** — authorized users edit/delete directly; the system auto-writes an **activity log** entry (actor, time, before/after, note). Ledger rows are **soft-deleted**. Activity logs are **permanent** — no one, not even Company Admin, can edit or delete them (F14.3).
- every model keeps `created_at`, `created_by`, `updated_at`
- **Removing a billing category** — `billing_id` is nullable on ledgers that use it. Deleting a billing category prompts the admin to either (a) **delete & set the FK null** on all its rows (`ON DELETE SET NULL`), or (b) **merge** — re-point its rows to another same-site category, then delete it. The action is **activity-logged and not undoable**; the admin must confirm first. `updated_at` is untouched (it is not a per-row user edit). See F5.9 / F5.15. **No `custom_category` model** — keep the schema lean; free-text `note` covers ad-hoc labels.
- **Future dates blocked** — no record's `date` may be in the future, for every date-bearing entity.
- **Configuration tiers**
  - **System config** (`SystemConfig`, single global row, System Admin) — Governs platform behaviour only. See **System Configuration** under S1.
  - **Company config** (`CompanyConfig`, one per company, Company Admin) — per-tenant feature flags (e.g. `allow_labour_transfer`) **and** company-wide validation ranges / attendance choices (salary, fooding, advance, present choices). Created with built-in defaults at registration. See **Company Configuration** under F2.
  - **No SiteConfig** — sites stay lean; windows/quotas are not per-site (kept flexible at company / product level).

## Roles
- **System Admin** — manages all companies and subscriptions.
- **System Manager** — monitors subscriptions and payments (assigned permissions).
- **Company Admin** — full control of one company: users, sites, labour, subscription.
- **Site Manager** — full CRUD on assigned sites (attendance, cash, cost, etc.); edits are logged.
- **Site Auditor** — **view-only** on assigned sites (data + their activity log); cannot create / edit / delete.

## Access Control & User Model
### One `User` table, two kinds of user — split by Django's `is_staff`:
- **System** (`is_staff = true`, often `is_superuser`; `company_id = null`) — platform staff (S1). Sign in to the **Django admin site** (`/admin/`) with **session auth**; cross-company.
- **Tenant** (`is_staff = false`, `company_id` set) — company user (F4). Use the **Tenant API** (`/api/…`) with **JWT**, auto-scoped to its company.
- One phone = one account, so a person is system **or** tenant — Django's `is_staff` distinguishes them (no separate `scope` column). Tenant login (F1.1) issues JWT; the token carries `user_id`, `company_id`, groups. A system user reaches tenant data only through the Django admin / explicit platform actions (e.g. S1.9), never the tenant JWT API.
- **Why two auth backends** (session for admin, JWT for API)
  - Different surfaces, different hardening: the **admin panel uses Django session auth**, the **tenant API uses JWT**. The admin site is an isolated route (its own rate-limit / IP-allowlist), kept off the tenant attack surface.
  - `is_staff` gates the admin site — a tenant user (`is_staff = false`) can never reach it; and a system account is in no company group, so it cannot act on tenant API data. Shrinks coupling and blast radius.
  - It avoids the account enumeration a shared login leaks (which phones are platform staff). OTP generation and BD-phone normalization live in a **shared service**; each surface is a thin wrapper applying its own auth + policy — **one core logic, two doors**.

### Who can do what — capability + (for site records) assignment:
- **Capability** (*what*) — Django **groups + permissions** (`group_permissions`). System tier: System Admin / System Manager. Tenant tier roles **nest**: **Site Auditor** (view) ⊂ **Site Manager** (CRUD) ⊂ **Company Admin** (all). Multiple groups allowed — effective capability = **union** (= the highest). Permissions are **model-level / global** (e.g. `change_attendance`).
- **Scope** (*which sites*) — **`UserSite`** links a tenant user to sites. A site can have many users; a user many sites.
- **Two authorization modes:**
  1. **Site-scoped records** — every ledger (`attendance`, `labour_pay_return`, `site_cost`, `hidden_cost`, `site_cash`, `site_bill`; F7 / F9–F12): allowed when **has the permission** **AND** **assigned to that site** (`UserSite`) **AND** (for labour-linked rows) the row is **unsealed** (`is_sealed = false`). The site-scope check is enforced in **app code** (queryset / object filter by `UserSite`), not by the model-level permission. Visibility of `hidden_cost` may be restricted to Company Admin (F10 / F14.2).
  2. **Everything else** — company config, users, subscription, plans, billing categories, site lifecycle, reports: **permission only** (no `UserSite`).
- **Company Admin** holds **all** permissions, but **site-scoped records still require a `UserSite` assignment** for that site — capability alone is not enough there. "**Managed by admin**" = **assign the admin to the specific site** (F5.14); the admin then records on it like a manager. Non-site operations need no assignment. Every write is traceable via `created_by` / `activity_log.actor_id`.
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

## S1 — Manage Platform
System-level users; not tied to any company.

> **MVP scope** — in the MVP the entire platform side (S1.*) is operated through the **Django admin site** (`/admin/`, Django session auth); there is no platform frontend or public platform API yet, and system users are Django staff/superusers. The dedicated **Platform API** + system OTP/JWT login (S1.1) and custom actions like company reset (S1.11) are a **later phase**. The **tenant** side (F1, F2–F14) ships with its real API + frontend now.

### S1.1 — System user login
- Platform staff sign in to the **Django admin site** with **session auth** (no company context) — MVP. A dedicated OTP + JWT platform-API login is a later phase (see S1 MVP note). Identified by `is_staff = true`.

### S1.2 — View and search all companies
- List with open site count, billing status, activity, and activity logs.

### S1.3 — Activate / deactivate a company
- Deactivated company: all its users blocked from login; data retained.

### S1.4 — Manage subscription plans
- System Admin creates/edits plan tiers: **open-site limit**, **active-user limit**, **active-labour limit**, and one or more **durations** — each duration (any month count, e.g. 1 / 3 / 6 / 12 / 24) with its own **per-month rate**. Durations are stored as `plan_variant` rows (not fixed columns), so adding a new duration needs **no schema change**. Each limit `-1` = no limit; `N` = cap.
- Price changes apply to new purchases/renewals only; running subscriptions keep their rate snapshot.
- Custom plan: limits and price negotiated and set manually per company.
- **Manual payment** — a System user can record a subscription payment that bypasses the gateway (offline / bank / cash, or after a gateway failure) for any company.

### S1.5 — Monitor subscription status
- Dashboard of all companies: plan, active / expiring soon / expired, revenue summary.

### S1.6 — Create system users
- System Admin creates platform staff accounts (`is_staff = true`, `company_id = null`); assigned a system group (S1.7).

### S1.7 — Assign system roles
- System Admin assigns staff to system-level groups (System Admin / System Manager).

### S1.8 — Assign system-level permissions
- Fine-grained platform permissions per staff user (e.g., System Manager: monitor only).

### S1.9 — Data correction on sealed/closed data
- Only a system user can correct a sealed (`is_sealed = true`) row or restore/repair a closed site's data on support request — the company side has no such override.

### S1.10 — Manage system configuration
- System Admin views/edits `SystemConfig` (single global row, auto-created with defaults).
- Implementation note: SystemConfig is a Singleton (django-solo)

**Examples:**
| Field | Default | Meaning |
|---|---|---|
| `maintenance_mode` | false | When `true`, show a maintenance banner to all users. |
| `subscription_renew_notification` | 5 (days) | Begin renewal reminders this many days **before** `paid_until` — SMS + dashboard to every Company Admin (F3.7). |
| `company_deactivate_after_expiry` | 10 (days) | Days **after** expiry to auto-deactivate the company. On expiry, write access is cut immediately (F3.6); after this many further days the cron deactivates the company — no user can log in, reactivation needs a support request (S1.3). |
| `delete_deactivated_company` | 60 (days) | Days a company may stay deactivated before a cron **purges** its data. |
| `trial_plan` | null | JSON: the plan + limits used to seed a trial subscription at registration; null = no trial. |

**How it drives cron** — the scheduled jobs run on a **fixed schedule** (daily, set at deploy). They read these **threshold values** at run time and decide what to act on. So changing a value takes effect on the next run.

> **Lifecycle timeline:** `paid_until` reached → write disabled immediately (F3.6) → **+ `company_deactivate_after_expiry` days** still unpaid → company deactivated, logins blocked → **+ `delete_deactivated_company` days** → data purged.

### S1.11 — Reset a company (system user only, OTP dual-control)
A low-frequency support action for clients who tested the app on a real account and want a clean production start. Destructive and **irreversible**, so it lives only on the platform side under two-party control.

1. Company Admin requests a reset via support (email / contact) — there is **no reset button on the tenant side**.
2. An authorized **System user** opens the company, hits **Reset**, and types the **company name** to confirm.
3. System sends a **single-use, short-expiry OTP to the Company Admin's phone** (shared OTP service, F1.1) — this proves the company consents.
4. The Company Admin relays the OTP to the system user, who enters it; the system **validates** it.
5. On a valid OTP, in **one transaction** the system **hard-deletes** all tenant data (FK-safe order): sites, billing categories, labours, work sessions, every ledger (`attendance`, `labour_pay_return`, `site_cash`, `site_cost`, `hidden_cost`, `site_bill`), all **non-admin** users (+ `UserSite` links), and the company's **activity logs**. `CompanyConfig` returns to built-in defaults.
6. **Kept:** the Company record, **all Company Admin** accounts, and the active subscription (`plan`, `paid_until` untouched) — the company is now like new with zero entities.
7. The system writes a **platform-level reset log** (system user, company id, timestamp, OTP-verified) stored system-side — it survives the wipe (the company-side activity log cannot, per step 5).
---

## F2 — Manage Company

### F2.1 — Create company
- Not a user-facing form — runs inside registration (F1.2).
- Creates Company record (name, active flag, billing fields); registrant becomes Company Admin.

### F2.2 — View company profile & status
- Company Admin opens company page.
- Shows name, active status, open site count, current plan, and subscription validity.

### F2.3 — Edit company details
- Company Admin edits company name and profile fields.
- System saves and records the change in the activity log.

### F2.4 — _(removed)_ Custom categories
- **`custom_category` is intentionally not used.** Keep the database lean; ledger rows use optional `billing_id` (where relevant) and free-text `note` instead of a second category taxonomy.

### F2.5 — Manage company configuration
- Company Admin views/edits the company's `CompanyConfig` (one row per company, auto-created at F2.1 with its own built-in defaults).
- Tenant-wide feature flags that apply to every site of the company. The change is activity-logged.
- Also holds **company-wide validation ranges / attendance present choices** (salary, fooding, advance, `attendance_present_choices`) — formerly SiteConfig; see **Company validation ranges** under F5.
- Example: **`allow_labour_transfer`** (bool, default `true`) — when `false`, moving a labour from one site to another (F6.2) is blocked company-wide; a labour stays on its original site for its whole lifecycle. Existing assignments are untouched.
- Example: **`auto_renew`** (bool, default `false`) — opt into automatic subscription renewal (F3.3); `false` (default) = let a term lapse at `paid_until` (i.e. "cancel").
- **Reset to defaults** — Company Admin can reset `CompanyConfig` back to its built-in defaults in one action; config-only (no entity data touched), activity-logged.

---

## F3 — Manage Company Subscription

> **MVP scope** — the whole subscription lifecycle (create, pay, renew, upgrade / downgrade) is operated by a **System Admin through the Django admin site** (S1). There is **no tenant-facing subscription API in the MVP**; a company's plan is managed for it. The rest of this section is the data model and the manual flow.

### Data model
- **`plan` / `plan_variant`** — the public tiers and their `(duration, price)` offerings (Free / Basic / Popular / Business).
- **`custom_plan`** — a negotiated deal created for **one specific company** (own limits, duration, price); only that company may be put on it.
- **`subscription`** — **one row per company**, the current entitlement cache: a snapshot of the active limits (`open_site_limit`, `active_user_limit`, `active_labour_limit`) plus `paid_until`. It points at the `plan_variant` **or** `custom_plan` it is on — never both, and neither for a hand-set / trial term. Updated in place; dies with the company.
- **`payment`** — a financial record: `amount`, `method` (gateway / manual), `status`, the coverage window (`period_start` / `period_end`), and trace FKs to the `variant` / `custom_plan`. `payment.company` is **SET NULL** on company delete, so the money trail survives.

### F3.1 — View subscription status
- Current plan, `paid_until`, **usage vs limit** (open sites / active users / active labour), and payment history.

### F3.2 — Pay for a plan
- A `success` `payment` activates the term: `period_start = max(paid_until, today)`, `period_end = period_start + the chosen plan's duration`, then the subscription's `paid_until = period_end` and its limits are snapshotted from that plan. `method` is `gateway` or `manual`.

### F3.3 — Renew plan
- Same as paying; renewing early keeps the unused tail (`period_start` stacks on the current `paid_until`).

### F3.4 — Upgrade plan
- Move to a higher tier (higher `open_site_limit`). Hitting a plan limit while creating a user / site / labour blocks the action with an upgrade prompt.

### F3.5 — Downgrade plan
- Move to a lower tier after expiry; allowed only if current usage fits the smaller limits.

### F3.6 — Disable write access on expiry
- `paid_until` in the past → write access is cut (read-only). If left unpaid, the SystemConfig cron timeline (S1.10) deactivates and later purges the company.

### F3.7 — Renewal reminders
- Reminder to the Company Admin starting `subscription_renew_notification` days before expiry (S1.10).

### Free & trial
- **Free** is an ordinary tier — a `0`-price, long-duration variant, so its `paid_until` is just a far-future date; no special-casing.
- **Trial** — an optional `trial_plan` (SystemConfig, S1.10) may seed a limited-time plan at registration; it is a normal subscription with a near `paid_until` and no payment.

### Subscription Model (reference)
Pricing is driven by **open site count**; the user and labour caps default to `-1` (no limit) today and exist so a tier can be tightened later without a schema change. Longer durations get a **per-month discount**. Prices in BDT. The durations below (1 / 6 / 12 months) are the **current offering** only — they are `plan_variant` rows, not fixed by schema, so any duration can be added as data.

| Plan | Open Sites | Active Users | Active Labour | 1 Month | 6 Months | 1 Year |
|---|---|---|---|---|---|---|
| **Free** | Up to 1 | −1 | −1 | Free | — | — |
| **Basic** | Up to 5 | −1 | −1 | 600 × 1 = **600** | 550 × 6 = **3,300** | 500 × 12 = **6,000** |
| **Popular** | Up to 10 | −1 | −1 | 1,000 × 1 = **1,000** | 950 × 6 = **5,700** | 900 × 12 = **10,800** |
| **Business** | Up to 20 | −1 | −1 | 3,000 × 1 = **3,000** | 2,900 × 6 = **17,400** | 2,500 × 12 = **30,000** |
| **Custom** | 20+ | negotiated | negotiated | negotiated | negotiated | negotiated |

> **Limit scale (all three):** `-1` = no limit, `N ≥ 0` = hard cap.
---

## F4 — Manage Company Users

### F4.1 — Create Staff user
- Company Admin provides name, BD phone number, password, role, permitted sites.
- System validates BD phone_number and checks it is not already registered.
- System checks the company's **active-user count** against the plan's active-user limit (skip if `-1`); at the cap → blocked with an upgrade prompt (F3.4).
- System sends an OTP to this phone number; admin completes registration by providing the OTP.
- System will creates user under the same company (`is_staff = false`, `company` = admin's company).
- If provide role and permitted sites then Assign this user to that group and permitted sites.
> Lately this staff user will login using this phone_number and password. and can change the password. There is no security concern about account missused by admin. Because, admin need the otp to register or login staff user account. But, otp will send to this user phone_number. So, Account owner only can login. Admin just has activate, deactivate, role management, permission management and delete this account autority.

### F4.2 — Assign role to user
- Admin picks a role (Company Admin / Site Manager / Site Auditor) → user added to that group. A user may hold more than one group; effective capability is the **union** (roles nest, so the highest wins).
- Role change takes effect on next request (permissions read from group).

### F4.3 — Assign user to sites
- Admin assigns user to one or more sites (`UserSite` link records).
- Site-scoped actions check this assignment: managers only act on assigned sites.
- A site may have multiple Site Managers / Site Auditors; a user may be assigned to multiple sites. See **Access Control & User Model**.

### F4.4 — Assign permissions to user
- Admin grants/revokes fine-grained permissions on top of the role defaults.

### F4.5 — Activate / deactivate user
- Deactivated user cannot log in; existing tokens stop working.
- Reactivation restores access; history is untouched.

### F4.6 — Delete (deactivate) user
- **No user is ever orphaned.** Every reference to a user (`created_by` on records, `actor_id` on activity logs, etc.) is **`ON DELETE RESTRICT`** — a user who has acted on anything **cannot be hard-deleted**.
1. Set `user.deleted_at = now()`, disable the account; write to activity log. The account is hidden and can no longer log in.
2. Admin can view and restore deactivated users at any time.
3. Hard purge happens **only** if the user has **zero** references (e.g. an account that never acted), or wholesale via a **company reset** (S1.11). Otherwise the user stays soft-deleted/deactivated permanently — its `created_by` / `actor_id` history stays intact.

### F4.7 — View and search users
- List company users with filters: role, site, active status; search by name/phone.

---

## F5 — Manage Sites

### Site States (reference)
Two independent state axes for a site:

| Field | Value | Meaning |
|---|---|---|
| `closed_at` | `null` | **Open** — site is ongoing. Counts toward the plan's open-site limit. |
| `closed_at` | timestamp | **Closed** — work permanently done. Company users see only the closure summary; detail rows stay in the same DB but are hidden, then a cron purges them 30 days after `closed_at` (except `is_sealed = false` rows). Does not count toward the plan limit. Reopen possible until purge. |
| `is_active` | `True` | **Active** — new data (attendance, cash, cost) can be recorded. |
| `is_active` | `False` | **Inactive** — temporarily paused. No new data can be created. Old data remains accessible. Can be reactivated at any time. |

> A site may be open (`closed_at=null`) and inactive (`is_active=False`) at the same time — temporarily paused but still ongoing. The plan limit counts all open sites regardless of active/inactive state.

### Company validation ranges (reference)
Live on `CompanyConfig` (F2.5) — company-wide, not per site. Applied to labour defaults and ledger amounts:
- `attendance_present_choices` — allowed `present` values when `attendance.type = attendance`, e.g. `[0, 0.5, 1, 1.5, 2, 3]`.
- `salary_min` / `salary_max` — attendance salary and `labour.default_salary`.
- `fooding_min` / `fooding_max` — `labour_pay_return` fooding amount and `labour.default_fooding`.
- `advance_min` / `advance_max` — `labour_pay_return` advance amount.

**Dates** — future dates are always rejected. There is **no** per-site daily-record create/update/delete window (SiteConfig removed for flexibility). Soft product limits (e.g. per-labour/day quotas) can be added later at company level if needed.

**Cross-site, same date** — by default move/transfer the labour (F6.2) or clear the other site's row before recording the same date elsewhere.

### F5.1 — Create / edit site
- Admin provides site name (and detail fields). New site starts open + active.
- System validates open site count against the active plan limit before creating; at the limit → creation blocked with an upgrade prompt (F3.4).
- No auto-created SiteConfig row (sites stay lean).

### F5.2 — Activate & Deactivate site
- Deactivate:
  - Sets `is_active = False`
  - No new attendance/cash/cost/bill entries; old data stays readable; reversible any time.
  - Users & labourer is not consider with that. They are relvent with company.
- Activate:
  - Sets `is_active = True`; new data entry allowed again.

### F5.3 — Close site permanently
A site typically runs ~2–4 years, then work is done. Closing frees a plan slot and lets the system shed the large detail dataset **in the same database** (no separate archive store) while keeping a permanent summary.

1. **Zero the site cash balance (manual, by site manager):**
   - balance > 0 → withdraw the surplus via `site_cash` with `type = return` (F11.2).
   - balance < 0 → cover the deficit via `site_cash` with `type = cash` (F11.1).
   - Close is blocked until the site cash balance = 0 (computed on read — Conventions).
2. **Set `closed_at = now()`** (a null `closed_at` = open, non-null = closed). Closed sites do not count toward the plan's open-site limit.
3. **Build the closure summary** (immutable snapshot): aggregated totals from `site_cost`, `hidden_cost`, `site_bill`, `attendance` (present/salary and extrawork), cash, labour payouts — everything the admin needs after the detail is gone.
4. **Access changes immediately** — authorized users now see **only the summary**; the detail rows stay in the same DB but are hidden from the company side.
5. **Cron purge** — a scheduled job deletes the detail rows of any site whose `closed_at` is **more than 30 days** old, **except** rows still `is_sealed = false`. Those belong to an as-yet-unsealed period; they are kept until the next session seals them (`is_sealed = true`), after which a later cron run may delete them.

### F5.4 — Reopen a closed site
- Admin requests reopen.
- System checks the subscription / open-site count against the plan limit (must have a free slot).
- **Set `closed_at = null`** → delete the closure summary → detail info is accessible again; the site counts as open.
- Only possible while the detail still exists (closed < 30 days, not yet purged). Once the cron has purged the detail, reopen can no longer restore it — recovery becomes a system-user support task (S1.9).

### F5.5 — Delete site
- Allowed only when the site has no financial records; otherwise must close instead.
- Later, when no entity ref this site then allow to delete.

### F5.6 — Assign users to site
- Admin links users to the site.

### F5.7 — View company sites
- Admin sees all sites; othere users see only assigned sites. Filters: open/closed, active/inactive.

### F5.8 — View site Report
- Shows current cash balance (on read):  
  `Σ site_cash(type=cash) − Σ site_cash(type=return) − Σ site_cost − Σ labour_pay_return(type=advance|fooding) + Σ labour_pay_return(type=return)`
  (exact product formula may omit labour return from cash; see F13.3). Hidden cost is **excluded** from cash balance.
- Optional **as-of date** — same formula with `date <= D` on each ledger (Conventions).
- Shows site revenue (bills vs billing-category contract).
- Show site total attendance (`type = attendance`) present/salary and extrawork totals (aggregated).
- Show site total cost (`site_cost`) and hidden cost (`hidden_cost`) separately.
- Billing-category breakdown line: per-billing-category contract value, billed, cost and profit (detail in F13.8).

### F5.9 — Manage billing categories
- Site-level master data: Admin defines the site's **billing categories** — header row `billing_category` (`id`, `company_id`, `site_id`, `name` e.g. Basement / Floor-1 / Floor-2-Extra, `display_order`, `is_active`).
- Measurement lives in a **1:1 `billing_category_details`** row: `sqft`, `rate_per_sqft`, `custom_amount`.
- **Optional** — billing categories are not mandatory. A site may run with **none** (simple project, or to avoid complexity), so every ledger's `billing_id` is **nullable**; categories can be added later and old rows keep `null`.
- Billing-category list feeds the dropdown on `attendance` (F9), `site_cost` / `hidden_cost` (F10), and `site_bill` (F12) entries.
- Editable while the site is open. **Removing** a billing category prompts the admin to delete-with-set-null or merge-into-another — see F5.15.

### F5.10 — Deactivate/Activate billing categories
- A billing category may activate or deactivate. Deactivate means no new records allow to create under this billing category execpt the SiteBill. But, historic data is accessable.

### F5.11 — Mark billing category as done
- This billing category's work is done, no need new expense or work.
- Billing category will deactivate (`is_done = true`).
- To activate the billing category again need to unmark as done first.

### F5.12 — _(removed)_ Site configuration
- **SiteConfig is intentionally not used.** Validation ranges / attendance choices live on `CompanyConfig` (F2.5). Sites only use `is_active` / `closed_at` for operational gating.
- Per-site daily-record windows and per-labour/day quotas are deferred (can return later as company-level settings if needed).

### F5.13 — View site activity log
- Site-scoped view of the **activity log** (F14.2 / F14.4): labour transfers (F6.2), billing-category removals/merges (F5.15), and all create / update / delete events for this site, filterable by user, entity type, and date.
- **View only** — activity entries are **never** edited or deleted (F14.3). Sensitive events (`hidden_cost`, company-level) are hidden from site / non-admin users (F14.2).

### F5.14 — Admin records on a site (managed by admin)
- Company Admin holds **all** permissions and has config + read access to all sites without assignment, but **site-scoped records require a `UserSite` assignment** — capability alone does not let the admin record on a site (Access Control).
- **Managed by admin** = the admin is **assigned to that specific site** (`UserSite`, via F5.6 / F4.3) — the site(s) the admin wants to run directly, alongside or instead of a Site Manager. The admin then records there exactly like a manager.
- **No group-join needed** — the admin already holds the record permissions; the `UserSite` assignment is the only thing that unlocks that site's ledgers. (Non-site operations need no assignment at all.)
- Reversible any time — unassign the admin from the site; the change is activity-logged.
- No extra security concern: every row keeps `created_by`, and every change is in the **activity log** (`actor_id`), so the actual writer is always traceable.

### F5.15 — Remove a billing category (delete or merge)
A billing category that already has records can be removed two ways; the admin is prompted to pick, **confirms**, and the choice is **activity-logged and not undoable**.

1. **Delete & set null** — the category is deleted and every referencing ledger row (`attendance`, `site_cost`, `hidden_cost`, `site_bill`) has its `billing_id` set to **null** (`ON DELETE SET NULL`). Those rows become site-general (no billing category).
2. **Merge into another (same site)** — the admin picks a target A; the source B's rows are re-pointed to A (plain `UPDATE billing_id = A`), then B is deleted (now unreferenced). `updated_at` is untouched. Per-category report figures stay correct because they are aggregated on read (Conventions).

One activity log entry records the action (`action_flag = deletion` or `merge`, with affected-row count). `billing_category_details` cascades away with the deleted category.

---

## F6 — Manage Labour Accounts

### F6.1 — Create / edit labourer
- Manager (with site permission) provides name, `default_salary`, `default_present`, `default_fooding`, and current site.
- System checks name uniqueness.
- System checks the company's **active-labour count** against the plan's active-labour limit (skip if `-1`); at the cap → blocked with an upgrade prompt (F3.4). Reactivation (F6.3) runs the same check.
- Labour starts active, assigned to that site. New attendance / fooding rows seed their values from these defaults if not provide explicitly (each row still keeps its own snapshot).

### F6.2 — Assign / move labourer to site
- Sets or changes the labour's current site (one site at a time — assigning to a new site **is** the move).
- **Gated by `CompanyConfig.allow_labour_transfer`** (F2.5): if `false`, moving an already-assigned labour to a different site is blocked (first assignment of a new labour still allowed).
- Previous site manager no longer creates new records against this labour.
- New site manager now has authority to create new records for this labour.

### F6.3 — Activate / deactivate labour account
- Inactive labour: no new attendance (including extrawork) or pay/return rows; history stays.
- A sealed `LabourSession` (vacation) deactivates the account automatically; returning from vacation requires reactivation **before** any new record (F8.1).

### F6.4 — Update labour salary for a date range
Salary is stored on each `attendance` row with `type = attendance`. `labour.default_salary` is used only when creating new attendance records.
1. Open the labour's attendance page.
2. Select a **single cell** (one row) or a **date range** or **particular site** of rows to re-price.
3. Enter the new salary (must be within the company's `salary_min` / `salary_max` on CompanyConfig).
4. System updates `salary` on each selected (`is_sealed = false`) attendance row. Site labour-cost reports recompute via `SUM` on read — no stored running totals to bump.
- Rows already sealed (`is_sealed = true`) cannot be re-priced.
- No per-site update window — any unsealed row may be re-priced (date still cannot be in the future when creating new attendance).
- No activity log needed for salary change of daily attendance.

### F6.5 — View and search labourers
- Filter by site, active status; search by name. Shows current site, salary, balance (balance aggregated on read — F7.3).

### F6.6 — Delete Labour Account
Many labourers work short engagements and never return; their accounts accumulate and must be cleanable without losing site financial data.

**Pre-condition:** Labour balance must be zero before deletion is allowed.
---

## F7 — Manage Labour Payments (Advance, Fooding & Return)

One ledger — **`labour_pay_return`** — with `type`:
- **`advance`** — cash advances (draw site cash / reduce labour balance)
- **`fooding`** — meal allowance (same cash/balance effect)
- **`return`** — money the labour gives back (increases labour balance)

### F7.1 — Issue advance payment
- Manager picks labour, enters amount, note, date → creates a `labour_pay_return` row with `type = advance` (`is_sealed = false`).
- Amount validated against `advance_min` / `advance_max`.
- Blocked if labour is inactive.

### F7.2 — Issue fooding payment
- Manager picks labour, enters amount (seeded from `default_fooding`), note, date → creates a `labour_pay_return` row with `type = fooding` (`is_sealed = false`).
- Amount validated against `fooding_min` / `fooding_max`.
- Blocked if labour is inactive.

### F7.3 — Track labour balance
- `balance = last LabourSession.balance + Σ earnings from unsealed attendance − Σ labour_pay_return(advance|fooding, unsealed) + Σ labour_pay_return(return, unsealed)`.
- Earnings from attendance: for `type = attendance` use salary (and present as needed for costing); for `type = extrawork` use `amount`.
- Computed **on read** (and optionally cached only for hot UI cards) — no per-row running totals.

### F7.4 — View payment / return history
- `labour_pay_return` rows per labour or per site, filterable by `type`, ordered by date; paginated. Optional running column on a page may use a window/`SUM` base for that page only.

### F7.5 — Record labour return
- Labour may return overpaid money. Manager creates `labour_pay_return` with `type = return` (amount, note, date; `is_sealed = false`). Increases the labour's balance.

### F7.6 — _(merged into F7.4)_ View return history
- Same ledger as F7.4 with `type = return` filter.
---

## F8 — Manage Labour Work Session

A labour works continuously — moving site to site — then takes a vacation. The **period** between two vacations is one work session, recorded as a `LabourSession` plus one `LabourSiteSession` per site touched. Ledger rows belong to a session by **date range + labour** (`[start_date … end_date]`), not a per-row FK.

### F8.1 — Create / seal a labour work session (vacation flow)
Triggered when the labour wants to go on vacation:
1. **Review** — all still-**unsealed** (`is_sealed = false`) rows (`attendance`, `labour_pay_return`) are reviewed; any correction is applied now, while they are still unsealed.
2. **Settle** — a final payment is made based on the current balance (pay out the payable, or collect an overpayment) so the balance reflects reality.
3. **Per-site rollup** — for each site the labour touched this session, create a `LabourSiteSession` aggregating that site's `present`, `extrawork`, `fooding`, `advance`, `salary`, `earnings`, `payable` (from source ledgers via `SUM`/filters).
4. **Session record** — create one `LabourSession` (links its LabourSiteSessions), with:
   - `start_date` = the **first** (earliest) entity date in this session, `end_date` = the **last** (latest) entity date;
   - carried totals `total_present`, `total_salary`, `total_extrawork`, `total_earnings`, `total_taken`, and `balance` (carried forward to the next session);
   - both `start_date` and `end_date` must be **after** the previous session's `created_at` date.
5. **Seal** — set `is_sealed = true` on every one of this labour's `attendance` / `labour_pay_return` rows whose `date` falls in `[start_date … end_date]` (rows bind to the session by **date range + labour**, not a stored FK).
6. **Deactivate** the labour account → vacation.

Rules:
- **One session per labour per day** — a labour may have at most one `LabourSession` created on a given day (`(labour, created_at::date)` unique).
- **New record date gate** — any new ledger entity's `date` must be **> the last work session's `created_at` date** (and never in the future).
- **Amend a sealed day** — to create a record after a session was already made the same day, **delete that session** (F8.3), create the record, then create the session again.
- Records created after sealing belong to the **next** session.
- After returning from vacation, the account must be **reactivated first** (F6.3) before creating any record.

### F8.2 — View session history
- Timeline of sessions per labour with per-site breakdown (present, earnings, payouts), start/end dates, and carried totals/balance.

### F8.3 — Delete a work session (unseal)
- Deleting a `LabourSession` **unseals** it: every one of this labour's rows with `date` in `[start_date … end_date]` is set back to `is_sealed = false`, then the session row (and its `LabourSiteSession` rollups) is deleted. One activity log entry is written.
- Use when an already-sealed day must be amended: **delete the session → create/correct the entity → create the session again** (re-seal).

---

## F9 — Manage Attendance & Extra Work

One table — **`attendance`** — with `type = attendance | extrawork`.

### F9.1 — Record daily attendance
- Creates `attendance` with `type = attendance`. Grain is **labour / day** (optionally split by billing category): Site Manager picks date, optional billing category (F5.9), `present` units (full/half/overtime), and `salary` (seeded from the labour default, editable per row). `amount` is null.
- **No DB uniqueness** on (labour, billing_category, date) — a labour may have **multiple attendance rows on the same date**.
- Billing category is **optional**; when set, the earnings attribute to billing-category costing. When the site has none it stays null.
- Validations: labour active and assigned to this site, site active, billing category active (if chosen), `present` ∈ CompanyConfig choices, salary within CompanyConfig range. New row is `is_sealed = false`.
> A creatable date must be **> the last work session's `created_at` date** and **never in the future** (F8). No SiteConfig daily-record windows.

### F9.2 — Record extra work
- Same table: `attendance` with `type = extrawork`. Fields: site, optional billing category (F5.9), labour, date, `amount`, `note`; `present` / `salary` null; `is_sealed = false`.
- Kept as a type (not a separate table) so ad-hoc extra earnings stay in one labour time ledger.
- Adds to the labour's earnings (aggregated on read).
- **No DB uniqueness** — multiple extrawork rows per labour/date are allowed.

### F9.3 — View attendance & extra work history
- Filter by labour, site, billing category, `type`, or date range; paginated. Optional running column via window/`SUM` on the page — no stored `site_total*`.

---

## F10 — Manage Site Expense

Two tables — **`site_cost`** (construction, paid from site cash) and **`hidden_cost`** (admin/office, for profit; not from site cash).

### F10.1 — Record site construction cost
- Manager enters site, date, **type** (`food` | `equipment` | `others`), **optional billing category (F5.9)**, amount, note → `site_cost`.
- Paid from site cash (draws down the cash balance — balance computed on read).

### F10.2 — Record hidden cost
- Separate model `hidden_cost` — kept apart so permissions/visibility can differ ("hidden" from normal site views).
- It is not paid from site cash; it is paid directly by the company admin.
- **Not** date-window gated — hidden cost is an admin/office record, allowed on any date ≤ today (entered late).
- Used for **profit/revenue**, not the cash balance.
- **Billing category is optional**: set → cost allocates to that billing category; null → site-general (not tied to any billing category, F13.8).

### F10.3 — View cost history
- Ledgers per site, filterable by billing category, `site_cost.type` (food / equipment / others), record type (site cost / hidden cost), date range; paginated.

---

## F11 — Manage Site Cash

One table — **`site_cash`** — with `type = cash | return`.

### F11.1 — Record cash deposit
- Manager records incoming cash with notes → `site_cash` with `type = cash`.

### F11.2 — Record cash return / withdrawal
- Outgoing cash: return to owner or other source with note → `site_cash` with `type = return`. This is not a site cost — a withdrawal.
- Cannot go below zero — insufficient **computed** balance is rejected.

### F11.3 — View site cash history
- Passbook view: date, type, note, amount (±). Running balance on a page via window/`SUM` base if needed; site balance reports use full `SUM` (Conventions / F13.3).

---

## F12 — Manage Site Bills

### F12.1 — Create site bill
- Authorized user records a bill: site, date, **optional billing category (F5.9)**, amount, note.
- Bills accumulate against that billing category's contract value (sqft × rate, F5.9) when set — compared via aggregates on read.
- **Not** date-window gated — site bill is an admin/office record, allowed on any date ≤ today.

### F12.2 — View bill history
- Ledger per site, filterable by billing category, date range; shows billed vs billing-category contract value vs remaining receivable (aggregates).

---

## F13 — Generate Reports

All reports are tenant-scoped and respect site assignments (managers see only their sites).  
**All money totals are computed on read** (`SUM` with `site_id` / `type` / optional `date <= as_of` or date range). No reliance on stored running `site_total*`.

### F13.1 — Labour balance report
- Per labour: earnings (`attendance` salary + extrawork amounts), advance, fooding, returns, net balance — from session carried balance + unsealed aggregates (F7.3).

### F13.2 — Site expense report
- Costs from `site_cost` (optionally grouped by `type`: food / equipment / others) and `hidden_cost`, plus billing category, for a site and date range.

### F13.3 — Site balance report
- Spendable cash per site (hidden cost excluded):  
  `Σ cash − Σ cash_return − Σ site_cost − Σ labour_pay_return(advance|fooding) [± labour return per product rule]`.  
- Supports **as-of date D** via `date <= D` on each sum.

### F13.4 — Site profit report
- Profit per site: `Σ bills − (labour cost + Σ site_cost + Σ hidden_cost)`, where labour cost = `Σ (attendance salary for type=attendance) + Σ (amount for type=extrawork)` (payouts are cash, not cost).
- Profit per billing category: same shape filtered by `billing_id`.
- Optional as-of / date range.

### F13.5 — Site labour cost report
- Attendance salary per site / date / billing category (`type = attendance`).
- Extra work per site / date / billing category (`type = extrawork`).
- Labour payments (`labour_pay_return` advance | fooding) per site / date.
- Labour cost per site / billing category = attendance salary sum + extrawork sum.

### F13.6 — Summary for a date range
- Company-level roll-up between two dates: cash in/out, costs, bills, labour cost, per-site rows — all via filtered `SUM`s.
- Site-level summary.

### F13.7 — Company dashboard
- Open sites overview, balances (aggregated), subscription expiry alert, recent edits (from activity log), recent activity.

### F13.8 — Billing-category costing & revenue report
- Per billing category of a site: `sqft`, `rate_per_sqft`, contract value (sqft × rate, or `custom_amount`), billed, remaining receivable (contract − billed), labour cost, construction cost (`site_cost`), allocated hidden cost (`hidden_cost`), total cost, profit (billed − total cost), cost per sqft.
- Site-general hidden cost (`billing_id = null` on `hidden_cost`) is shown as its own row, **not** pro-rated across billing categories.
- Reconciles to site profit: `site profit = (Σ billing-category profit) − general hidden cost`, which equals `bills − (labour + site cost + all hidden)`.

---

## F14 — Record Edits & Activity Log

Edits happen directly; the `is_sealed` flag is the hard lock, and the **activity log** makes every live edit accountable. The activity log replaces the old per-row `updated_by` — the actor lives on `activity_log.actor_id`.

### F14.1 — Edit / delete a record (direct, with auto activity log)
- Allowed only on rows that are still **unsealed** where applicable (`is_sealed = false`; sealed labour-linked rows are immutable — see F8). Future dates remain blocked on create. Hidden cost / site bill follow product rules (hidden often admin-only; bill anytime ≤ today).
- An authorized user edits or deletes a record from its own module (`attendance` F9, `labour_pay_return` F7, `site_cash` F11, `site_cost` / `hidden_cost` F10, `site_bill` F12, plus master data).
- In one transaction the system:
  1. Applies the change (financial/ledger rows are **soft-deleted**, not hard-deleted).
  2. Writes an **activity log entry**: company, actor, timestamp, target (`content_type` + `object_id`, a Django generic FK), `action_flag` (`addition` / `change` / `deletion` / `merge` — Django LogEntry style), **before snapshot**, **after snapshot**, and a **note (required for change/deletion of financial records)**.
  3. Bumps the record's `updated_at` — **only** for an explicit user field edit. A **billing-category removal/merge** (F5.15) re-points or nulls the row's `billing_id` and leaves `updated_at` untouched.
- **No running-total chain to maintain** — reports and balances recompute via aggregates on read (Conventions).

### F14.2 — View the activity log
- Any authorized user views the log, filtered by record, site, user, action, or date range.
- Each entry shows who changed what, when, the before/after values, and the note.
- **Visibility** — a Site Manager / Site Auditor sees all activity for their **authorized sites**, **except sensitive entries** — e.g. `hidden_cost` (F10.2) plus company-level events, **derived from the entry payload / content type**, **not** a stored flag. Sensitive entries are shown to the Company Admin only.

### F14.3 — Activity logs are permanent
- Activity entries can **never** be edited or deleted — **not even by the Company Admin**. There is no soft-delete and no removal action on the tenant side.
- The only way they leave the database is a full **company reset** (S1.11), which hard-deletes them system-side under OTP dual-control.
- This makes the log a tamper-evident backstop: the affected record's `updated_at` and the permanent entry together always show that, and how, it was modified.

### F14.4 — Activity view (admin oversight)
- The admin reviews the **activity log** (F14.2): all records created / updated / deleted / merged, filterable by site, user, entity type, and date.
- This is the verification mechanism — instead of a per-row `verified` flag, the admin watches activity (especially after a merge, F5.15) and manually asks a manager to correct anything wrong.

> **Note** — there is intentionally no admin override to edit a **sealed** (`is_sealed = true`) record. The seal is the hard boundary; if a settled session truly needs a fix, the correction is done by a system user (S1.9), not a normal edit.
