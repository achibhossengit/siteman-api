# SiteMan — API Endpoints

## F1 — Manage Authentication

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/auth/register` | Validate name/phone/email/company/password; stash payload + OTP in Redis; return ticket | MVP | pending |
| `POST` | `/api/v1/auth/register/resend-otp` | Resend OTP for ticket (60s cooldown, max 5/hr); regenerate code, drop old | MVP | pending |
| `POST` | `/api/v1/auth/register/confirm` | Verify OTP; one tx: create company + admin user + Company Admin group + seed Free plan; auto-login (issue JWT) | MVP | pending |
| `POST` | `/api/v1/auth/login` | Phone + password; validate BD phone + active account/company; issue JWT access + refresh (refresh token set in httponly cookie) | MVP | pending |
| `POST` | `/api/v1/auth/token/refresh` | Exchange refresh for new access; rotate refresh | MVP | pending |
| `POST` | `/api/v1/auth/logout` | Blacklist current refresh token in database | MVP | pending |
| `POST` | `/api/v1/auth/password/reset` | Registered phone; always 200 (no enumeration); send OTP; return ticket | MVP | pending |
| `POST` | `/api/v1/auth/password/reset/resend-otp` | Resend reset OTP for ticket (cooldown) | MVP | pending |
| `POST` | `/api/v1/auth/password/reset/confirm` | Verify OTP {ticket, code, new_password}; set password; bump token_version (invalidate all tokens) | MVP | pending |
| `POST` | `/api/v1/auth/password/change` | Logged-in: current + new password; bump token_version then re-issue current pair (kills all other tokens) | MVP | pending |
| `GET` | `/api/v1/auth/me` | Logged-in user profile (id/name/phone/email/company/groups) | MVP | pending |

## F2 — Manage Platform

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/platform/companies` | List/search all companies (site count/billing/activity). MVP via Django admin | L2 | pending |
| `POST` | `/api/v1/platform/companies/{id}/activate` | Activate a company | L2 | pending |
| `POST` | `/api/v1/platform/companies/{id}/deactivate` | Deactivate company; block all its logins; retain data | L2 | pending |
| `GET` | `/api/v1/platform/subscriptions/monitor` | Dashboard of plans/expiry/revenue across companies | L2 | pending |
| `POST` | `/api/v1/platform/payments/manual` | Record offline/manual subscription payment for any company | L2 | pending |
| `POST` | `/api/v1/platform/users` | Create system staff (is_staff=true company_id=null) | L2 | pending |
| `POST` | `/api/v1/platform/users/{id}/roles` | Assign system group (System Admin / System Manager) | L2 | pending |
| `POST` | `/api/v1/platform/users/{id}/permissions` | Assign fine-grained platform permissions | L2 | pending |
| `POST` | `/api/v1/platform/data-correction` | Correct sealed row / repair closed-site data (system only) | L2 | pending |
| `GET` | `/api/v1/platform/system-config` | View SystemConfig singleton | L2 | pending |
| `PATCH` | `/api/v1/platform/system-config` | Edit SystemConfig (maintenance/notify/deactivate/purge days) | L2 | pending |
| `POST` | `/api/v1/platform/companies/{id}/reset/request-otp` | Start company reset; type company name; OTP to Company Admin | L2 | pending |
| `POST` | `/api/v1/platform/companies/{id}/reset/confirm` | Verify OTP; hard-delete tenant data in one tx; write reset log | L2 | pending |

## F3 — Manage Company

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET`   | `/api/v1/company` | View company profile & status (name/active/site count/plan/validity) | MVP | pending |
| `PATCH` | `/api/v1/company` | Edit company name & profile; activity-logged | MVP | pending |
| `GET`   | `/api/v1/company-config` | View CompanyConfig (allow_labour_transfer/auto_renew) | MVP | pending |
| `PATCH` | `/api/v1/company-config` | Edit CompanyConfig flags; activity-logged | L1 | pending |
| `POST`  | `/api/v1/company-config/reset` | Reset CompanyConfig to built-in defaults; activity-logged | L2 | pending |
| `GET`   | `/api/v1/custom-categories` | List custom categories filtered by scope | MVP | pending |
| `POST`  | `/api/v1/custom-categories` | Create custom category (scope/name/note/order) | L1 | pending |
| `PATCH` | `/api/v1/custom-categories/{id}` | Edit custom category | L1 | pending |
| `DELETE`| `/api/v1/custom-categories/{id}` | Delete & set-null on referencing rows; confirm + activity-logged | L1 | pending |
| `POST`  | `/api/v1/custom-categories/{id}/merge` | Merge into another same-scope category | L2 | pending |

## F4 — Manage Company Subscription

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/plans` | List plan tiers + variants (durations/prices) | MVP | pending |
| `GET` | `/api/v1/payments` | Payment history for company | L1 | pending |
| `GET` | `/api/v1/payments/{id}` | Payment details | L1 | pending |
| `POST`| `/api/v1/payments` | Create payment attempt + redirect to gateway | L1 | pending |
| `POST`| `/api/v1/payments/webhook` | Gateway IPN/webhook (unauthenticated, signature-verified, idempotent — dedupe by transaction_id); verify amount; stack paid_until | L1 | pending |
| `GET` | `/api/v1/subscription` | Current plan/expiry/payment history + usage vs limit | MVP | pending |
| `POST`| `/api/v1/subscription/renew` | Manual renew; current subscription or pick variant; stack paid_until | L1 | pending |
| `POST`| `/api/v1/subscription/upgrade` | Upgrade plan; pro-rate before expiry / plain after | L2 | pending |
| `POST`| `/api/v1/subscription/downgrade` | Downgrade after expiry; check usage vs target limits | L2 | pending |

## F5 — Manage Company Users

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET`  | `/api/v1/users` | List/search company users; filters role/site/active | MVP | pending |
| `POST` | `/api/v1/users` | Create staff (name/phone/role/sites); auto-gen random hashed password; check user limit + permissions; SMS-invite user to set password via reset flow | MVP | pending |
| `GET`  | `/api/v1/users/{id}` | View user detail | MVP | pending |
| `PATCH`| `/api/v1/users/{id}` | Admin edit name (instant) / phone/email (held in Redis pending OTP to user's phone, return ticket) | L1 | pending |
| `POST` | `/api/v1/users/{id}/verify-otp` | Verify OTP {ticket, code}; apply pending detail change | L1 | pending |
| `POST` | `/api/v1/users/{id}/roles` | Assign/change role (group); union capability | MVP | pending |
| `POST` | `/api/v1/users/{id}/sites` | Assign user to one or more sites (UserSite) | MVP | pending |
| `POST` | `/api/v1/users/{id}/permissions` | Grant/revoke fine-grained permissions | L2 | pending |
| `PATCH` | `/api/v1/users/{id}/status` | Set activation explicitly {is_active} (not blind toggle) | L1 | pending |
| `DELETE`| `/api/v1/users/{id}` | Soft-delete user (deleted_at); RESTRICT if referenced | L1 | pending |
| `POST` | `/api/v1/users/{id}/restore` | Restore soft-deleted user (clear deleted_at) | L1 | pending |

## F6 — Manage Sites

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/sites` | List sites; filters open/closed active/inactive; scoped by assignment | MVP | pending |
| `POST` | `/api/v1/sites` | Create site (open+active); checks open-site limit | MVP | pending |
| `GET` | `/api/v1/sites/{id}` | View site detail | MVP | pending |
| `PATCH` | `/api/v1/sites/{id}` | Edit site name/fields | MVP | pending |
| `POST` | `/api/v1/sites/{id}/status` | toggle is_active | L1 | pending |
| `POST` | `/api/v1/sites/{id}/close` | Zero cash check; set closed_at; build closure summary | L1 | pending |
| `POST` | `/api/v1/sites/{id}/reopen` | Check slot; clear closed_at; delete summary (detail not purged) | L1 | pending |
| `DELETE` | `/api/v1/sites/{id}` | Delete site only if no financial records / refs | L1 | pending |
| `GET` | `/api/v1/sites/{id}/report` | Site report: cash balance/revenue/attendance/cost/payouts/category breakdown | MVP | pending |
| `GET` | `/api/v1/sites/{id}/config` | View SiteConfig (windows/quotas/validation ranges) | MVP | pending |
| `PATCH` | `/api/v1/sites/{id}/config` | Edit SiteConfig; future checks only; activity-logged | L1 | pending |
| `POST` | `/api/v1/sites/{id}/config/reset` | Reset SiteConfig to defaults; activity-logged | L2 | pending |
| `GET` | `/api/v1/sites/{id}/billing-categories` | List site billing categories + details | MVP | pending |
| `POST` | `/api/v1/sites/{id}/billing-categories` | Create billing category + 1:1 details (sqft/rate/custom_amount) | L1 | pending |
| `PATCH` | `/api/v1/billing-categories/{id}` | Edit billing category & details | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/activate` | Activate billing category | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/deactivate` | Deactivate; block new records except SiteBill | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/mark-done` | Mark done (is_done=true) => deactivates | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/unmark-done` | Unmark done to allow reactivation | L2 | pending |
| `DELETE` | `/api/v1/billing-categories/{id}` | Delete & set-null on rows; confirm + activity-logged | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/merge` | Merge into another same-site category then delete source | L2 | pending |

## F7 — Manage Labour Accounts

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/labours` | List/search labour; filters site/active; shows site/salary/balance | MVP | pending |
| `POST` | `/api/v1/labours` | Create labour (name/defaults/site); checks labour limit & name uniqueness | MVP | pending |
| `GET` | `/api/v1/labours/{id}` | View labour detail | MVP | pending |
| `PATCH` | `/api/v1/labours/{id}` | Edit labour fields/defaults | MVP | pending |
| `POST` | `/api/v1/labours/{id}/transfer` | Move to a site (one at a time); gated by allow_labour_transfer | L1 | pending |
| `POST` | `/api/v1/labours/{id}/activate` | Reactivate labour; re-runs labour-limit check | L1 | pending |
| `POST` | `/api/v1/labours/{id}/deactivate` | Deactivate labour; no new records | L1 | pending |
| `DELETE` | `/api/v1/labours/{id}` | Soft-delete labour; requires zero balance; RESTRICT if referenced | L1 | pending |
| `POST` | `/api/v1/labours/{id}/restore` | Restore deactivated labour | L1 | pending |
| `GET` | `/api/v1/labours/{id}/balance` | Track labour balance from carried totals | MVP | pending |
| `PATCH` | `/api/v1/labours/{id}/salary` | Re-price salary on cell/date-range/site of unsealed rows; recompute totals | L1 | pending |

## F8 — Manage Labour Payments (Advance & Fooding)

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/advance-pays` | Create advance pay row; blocked if labour inactive; running site_total | MVP | pending |
| `GET` | `/api/v1/advance-pays` | List advance pays per labour/site | MVP | pending |
| `PATCH` | `/api/v1/advance-pays/{id}` | Edit unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/advance-pays/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `POST` | `/api/v1/fooding-pays` | Create fooding pay (seeded default_fooding); blocked if inactive | MVP | pending |
| `GET` | `/api/v1/fooding-pays` | List fooding pays per labour/site | MVP | pending |
| `PATCH` | `/api/v1/fooding-pays/{id}` | Edit unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/fooding-pays/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | L1 | pending |

## F9 — Manage Labour Return

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/labour-returns` | Record return (amount/note/date); increases balance; running site_total | MVP | pending |
| `GET` | `/api/v1/labour-returns` | List returns per labour/site | MVP | pending |
| `PATCH` | `/api/v1/labour-returns/{id}` | Edit unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/labour-returns/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | L1 | pending |

## F10 — Manage Labour Work Session

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/labour-sessions` | List work sessions | L1 | pending |
| `GET` | `/api/v1/labours/{id}/sessions` | Session timeline per labour with per-site breakdown | L1 | pending |
| `POST` | `/api/v1/labour-sessions` | Create/seal session; settle; rollup per site; seal date-range rows; deactivate labour | L1 | pending |
| `DELETE` | `/api/v1/labour-sessions/{id}` | Delete session => unseal date-range rows; remove rollups; activity-logged | L1 | pending |

## F11 — Manage Daily Attendance & Extra Work

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/attendances` | Record attendance (date/present/salary/optional categories); gates by config | MVP | pending |
| `GET` | `/api/v1/attendances` | List/filter attendance by labour/site/category/date | MVP | pending |
| `PATCH` | `/api/v1/attendances/{id}` | Edit unsealed row in window; activity-logged; recompute totals | MVP | pending |
| `DELETE` | `/api/v1/attendances/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | MVP | pending |
| `POST` | `/api/v1/extra-works` | Record extra work (amount/note/optional categories); running site_total_amount | MVP | pending |
| `GET` | `/api/v1/extra-works` | List/filter extra work | MVP | pending |
| `PATCH` | `/api/v1/extra-works/{id}` | Edit unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/extra-works/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | L1 | pending |

## F12 — Manage Site Expense

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/site-costs` | Record construction cost (optional categories); draws site cash; running site_total | MVP | pending |
| `GET` | `/api/v1/site-costs` | List/filter site costs | MVP | pending |
| `PATCH` | `/api/v1/site-costs/{id}` | Edit unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/site-costs/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `POST` | `/api/v1/hidden-costs` | Record hidden cost (not window-gated; paid by admin; for profit calc) | L1 | pending |
| `GET` | `/api/v1/hidden-costs` | List/filter hidden costs (admin-visible) | L1 | pending |
| `PATCH` | `/api/v1/hidden-costs/{id}` | Edit hidden cost; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/hidden-costs/{id}` | Soft-delete hidden cost; activity-logged; recompute totals | L1 | pending |

## F13 — Manage Site Cash

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/site-cash` | Record cash deposit (optional category); increases site cash total | MVP | pending |
| `POST` | `/api/v1/site-cash-returns` | Record cash return/withdrawal; rejected if balance < 0 | MVP | pending |
| `GET` | `/api/v1/site-cash` | Passbook view: date/type/note/amount/running balance | MVP | pending |
| `PATCH` | `/api/v1/site-cash/{id}` | Edit unsealed deposit in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/site-cash/{id}` | Soft-delete unsealed deposit in window; activity-logged; recompute totals | L1 | pending |
| `PATCH` | `/api/v1/site-cash-returns/{id}` | Edit unsealed return in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/site-cash-returns/{id}` | Soft-delete unsealed return in window; activity-logged; recompute totals | L1 | pending |

## F14 — Manage Site Bills

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/site-bills` | Create bill (optional categories); not window-gated; running site_total | MVP | pending |
| `GET` | `/api/v1/site-bills` | List bills; billed vs contract vs remaining receivable | MVP | pending |
| `PATCH` | `/api/v1/site-bills/{id}` | Edit bill; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/site-bills/{id}` | Soft-delete bill; activity-logged; recompute totals | L1 | pending |

## F15 — Generate Reports

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/reports/dashboard` | Company dashboard: open sites/balances/expiry alert/recent activity | MVP | pending |
| `GET` | `/api/v1/reports/labour-balance` | Per-labour earnings/advance/fooding/returns/net balance | L1 | pending |
| `GET` | `/api/v1/reports/site-expense` | Costs by ledger/billing category for site + date range | L1 | pending |
| `GET` | `/api/v1/reports/site-balance` | Current spendable cash per site | L1 | pending |
| `GET` | `/api/v1/reports/site-profit` | Profit per site & per billing category | L1 | pending |
| `GET` | `/api/v1/reports/site-labour-cost` | Attendance salary/extra/advance/fooding per site & category | L1 | pending |
| `GET` | `/api/v1/reports/summary` | Company & site roll-up between two dates | L1 | pending |
| `GET` | `/api/v1/reports/billing-category-costing` | Per-category contract/billed/cost/profit/cost-per-sqft | L2 | pending |

## F16 — Record Edits & Activity Log

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/activity-logs` | View/filter activity log by record/site/user/action/date; sensitive hidden from non-admin | L1 | pending |
| `GET` | `/api/v1/sites/{id}/activity-log` | Site-scoped activity view (transfers/category ops/CRUD events) | L1 | pending |
