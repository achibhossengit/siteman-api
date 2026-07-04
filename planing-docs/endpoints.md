# SiteMan — API Endpoints

## F1 — Manage Authentication

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/auth/register` | Validate name/phone/email/company/password; stash payload + OTP in Redis; return ticket | MVP | pending |
| `POST` | `/api/v1/auth/register/resend-otp` | Resend OTP for ticket (60s cooldown, max 5/hr); regenerate code, drop old | MVP | pending |
| `POST` | `/api/v1/auth/register/confirm` | Verify OTP; one tx: create company + admin user + Company Admin group + seed Free plan; auto-login (issue JWT) | MVP | pending |
| `POST` | `/api/v1/auth/token/obtain` | Phone + password; validate BD phone + active account/company; issue JWT access + refresh (refresh token set in httponly cookie) | MVP | pending |
| `POST` | `/api/v1/auth/token/refresh` | Exchange refresh for new access; rotate refresh | MVP | pending |
| `POST` | `/api/v1/auth/token/blacklist` | Blacklist current refresh token in database | MVP | pending |
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
| `POST` | `/api/v1/users` | Create staff (name/phone/role/sites); validate phone + check user limit/permissions; send OTP to new user's phone; stash payload in Redis; return ticket (no user row yet) | MVP | pending |
| `POST` | `/api/v1/users/resend-otp` | Resend create OTP for ticket (60s cooldown, max 5/hr) | MVP | pending |
| `POST` | `/api/v1/users/verify-otp` | Verify OTP {ticket, code}; create user (is_staff=false) + assign role/sites; auto-gen random password; SMS it to user ("login with this, reset it, don't share") | MVP | pending |
| `GET`  | `/api/v1/users/{id}` | View user detail | MVP | pending |
| `PATCH`| `/api/v1/users/{id}` | Admin edit name (instant) / phone/email (held in Redis pending OTP to user's phone, return ticket) | L1 | pending |
| `POST` | `/api/v1/users/{id}/verify-otp` | Verify OTP {ticket, code}; apply pending detail change | L1 | pending |
| `POST` | `/api/v1/users/{id}/roles` | Assign/change role (group); union capability | MVP | pending |
| `POST` | `/api/v1/users/{id}/sites` | Assign user to multiple sites (array payload); UserSite links | MVP | pending |
| `DELETE` | `/api/v1/users/{id}/sites` | Unassign user from multiple sites (array payload) | MVP | pending |
| `POST` | `/api/v1/users/{id}/permissions` | Grant/revoke fine-grained permissions | L2 | pending |
| `POST` | `/api/v1/users/{id}/activate` | Set is_active=true | L1 | pending |
| `POST` | `/api/v1/users/{id}/deactivate` | Set is_active=false | L1 | pending |
| `DELETE`| `/api/v1/users/{id}` | Soft-delete user (deleted_at); RESTRICT if referenced | L1 | pending |
| `POST` | `/api/v1/users/{id}/restore` | Restore soft-deleted user (clear deleted_at) | L1 | pending |

## F6 — Manage Sites

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/sites` | List sites; filters open/closed active/inactive; scoped by assignment | MVP | pending |
| `POST`| `/api/v1/sites` | Create site (open+active); checks open-site limit | MVP | pending |
| `GET`  | `/api/v1/sites/{id}` | View site detail | MVP | pending |
| `PATCH`| `/api/v1/sites/{id}` | Edit site name/fields | MVP | pending |
| `POST` | `/api/v1/sites/{id}/activate` | is_active=true | L1 | pending |
| `POST` | `/api/v1/sites/{id}/deactivate` | is_active=false | L1 | pending |
| `POST` | `/api/v1/sites/{id}/close` | Zero cash check; set closed_at; build closure summary | L1 | pending |
| `POST` | `/api/v1/sites/{id}/reopen` | Check slot; clear closed_at; delete summary (detail not purged) | L1 | pending |
| `DELETE` | `/api/v1/sites/{id}` | Delete site only if no financial records / refs | L1 | pending |
| `GET` | `/api/v1/sites/{id}/config` | View SiteConfig (windows/quotas/validation ranges) | MVP | pending |
| `PATCH` | `/api/v1/sites/{id}/config` | Edit SiteConfig; future checks only; activity-logged | L1 | pending |
| `POST` | `/api/v1/sites/{id}/config/reset` | Reset SiteConfig to defaults; activity-logged | L2 | pending |
| `GET` | `/api/v1/billing-categories` | List site billing categories; filter by sites, etc | MVP | pending |
| `POST` | `/api/v1/billing-categories` | Create billing category(name, site, etc) + 1:1 details | L1 | pending |
| `PATCH` | `/api/v1/billing-categories/{id}` | Edit billing category & details | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/activate` | is_active=true | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/deactivate` | is_active=false; block new records except SiteBill | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/mark-done` | is_done=true; deactivates this billing category | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/unmark-done` | is_done=false; allow reactivation | L1 | pending |
| `DELETE` | `/api/v1/billing-categories/{id}` | Delete & set-null on rows; confirm + activity-logged | L1 | pending |
| `POST` | `/api/v1/billing-categories/{id}/merge` | Merge into another same-site category | L2 | pending |

## F7 — Manage Labour Accounts

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/labours` | List/search labour; filters site/active, current_site, etc; | MVP | pending |
| `POST` | `/api/v1/labours` | Create labour (name/defaults/site); checks labour limit & name uniqueness | MVP | pending |
| `GET` | `/api/v1/labours/{id}` | View labour detail | MVP | pending |
| `PATCH` | `/api/v1/labours/{id}` | Edit labour fields/defaults | MVP | pending |
| `POST` | `/api/v1/labours/{id}/transfer` | change the current_site; gated by allow_labour_transfer | L1 | pending |
| `POST` | `/api/v1/labours/{id}/activate` | Reactivate labour; re-runs labour-limit check | L1 | pending |
| `POST` | `/api/v1/labours/{id}/deactivate` | Deactivate labour; no new records | L1 | pending |
| `DELETE` | `/api/v1/labours/{id}` | Delete labour; requires zero balance; RESTRICT if referenced | L1 | pending |

## F8 — Manage Labour Payments (Advance, Fooding & Return)

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/advance-pays` | List advance filtered by labour, site, non-seald | MVP | pending |
| `POST` | `/api/v1/advance-pays` | Create advance; body always array (single = array of 1, hajira sheet = many); one tx per request; blocked if labour inactive; recompute site_total once; returns {created, errors[]} | MVP | pending |
| `PATCH` | `/api/v1/advance-pays/{id}` | Edit unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/advance-pays/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `GET` | `/api/v1/fooding-pays` | List fooding filtered by labour, site, non-sealed | MVP | pending |
| `POST` | `/api/v1/fooding-pays` | Create fooding (seeded default_fooding); body always array (single = array of 1, hajira sheet = many); one tx per request; blocked if inactive; recompute site_total once; returns {created, errors[]} | MVP | pending |
| `PATCH` | `/api/v1/fooding-pays/{id}` | Edit unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/fooding-pays/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `GET` | `/api/v1/labour-returns` | List returns filtered by user, site, sealed, non-sealed | MVP | pending |
| `POST` | `/api/v1/labour-returns` | Record return (amount/note/date); increases balance; running site_total | MVP | pending |
| `PATCH` | `/api/v1/labour-returns/{id}` | Edit unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/labour-returns/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | L1 | pending |


## F9 — Manage Labour Work Session

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/labour-sessions` | List work sessions, filtered by labour, etc | L1 | pending |
| `GET` | `/api/v1/labours/{id}/sessions` | Session timeline per labour with per-site breakdown | L1 | pending |
| `POST` | `/api/v1/labour-sessions` | Create/seal session; settle; rollup per site; seal date-range rows; deactivate labour | L1 | pending |
| `DELETE` | `/api/v1/labour-sessions/{id}` | Delete session => unseal date-range rows; remove rollups; activity-logged | L1 | pending |
| `GET` | `/api/v1/labour-sessions/current-session` | labour most last sessions + running nonsealed earnings/advance/fooding/returns/net balance | L1 | pending |


## F10 — Manage Daily Attendance & Extra Work

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/attendances` | List/filter attendance by labour/site/category/date | MVP | pending |
| `POST` | `/api/v1/attendances` | Create attendance; body always array (single = array of 1, hajira sheet = many); one tx per request; per-labour gates; recompute site_total once; returns {created, errors[]} | MVP | pending |
| `PATCH` | `/api/v1/attendances/{id}` | Edit unsealed row in window; activity-logged; recompute totals | MVP | pending |
| `PATCH` | `/api/v1/attendances/salary` | change provided attendence and recompute totals;   "attendance_ids": [15, 18, 22], "salary": 900; these attendence may sequential or not so need to recompute the totals carefully | MVP | pending |
| `DELETE` | `/api/v1/attendances/{id}` | Delete unsealed row in window; activity-logged; recompute totals | MVP | pending |
| `POST` | `/api/v1/extra-works` | body always array (single = array of 1, hajira sheet = many); one tx per request; per-labour gates; recompute site_total_amount once; | MVP | pending |
| `GET` | `/api/v1/extra-works` | List/filter extra work | MVP | pending |
| `PATCH` | `/api/v1/extra-works/{id}` | Edit unsealed row in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/extra-works/{id}` | Soft-delete unsealed row in window; activity-logged; recompute totals | L1 | pending |

## F11 — Manage Site Expense

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

## F12 — Manage Site Cash

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/site-cash` | Record cash deposit (optional category); increases site cash total | MVP | pending |
| `GET` | `/api/v1/site-cash` | Passbook view: date/type/note/amount/running | MVP | pending |
| `PATCH` | `/api/v1/site-cash/{id}` | Edit unsealed deposit in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/site-cash/{id}` | Soft-delete unsealed deposit in window; activity-logged; recompute totals | L1 | pending |
| `POST` | `/api/v1/site-cash-returns` | Record cash return/withdrawal; rejected if < 0 | MVP | pending |
| `GET` | `/api/v1/site-cash-returns` | Passbook view: date/type/note/amount/running | MVP | pending |
| `PATCH` | `/api/v1/site-cash-returns/{id}` | Edit unsealed return in window; activity-logged; recompute totals | L1 | pending |
| `DELETE` | `/api/v1/site-cash-returns/{id}` | Soft-delete unsealed return in window; activity-logged; recompute totals | L1 | pending |

## F13 — Manage Site Bills

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `POST` | `/api/v1/site-bills` | Create bill (optional categories); not window-gated; running site_total | MVP | pending |
| `GET` | `/api/v1/site-bills` | List bills filtereable by sites/daterange/etc; | MVP | pending |
| `PATCH` | `/api/v1/site-bills/{id}` | Edit bill; activity-logged; recompute totals | MVP | pending |
| `DELETE` | `/api/v1/site-bills/{id}` | Soft-delete bill; activity-logged; recompute totals | MVP | pending |

## F14 — Generate Reports

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/reports/dashboard` | Company dashboard: open sites/balances/expiry alert/recent activity | MVP | pending |
| `GET` | `/api/v1/reports/site-balance` | Current spendable cash per site | L1 | pending |
| `GET` | `/api/v1/reports/site-profit` | Profit per site & per billing category | L1 | pending |
| `GET` | `/api/v1/reports/site-labour-cost` | Attendance salary/extra/advance/fooding per site & category | L1 | pending |
| `GET` | `/api/v1/reports/summary` | Company & site roll-up between two dates | L1 | pending |
| `GET` | `/api/v1/reports/billing-category-costing` | Per-category contract/billed/cost/profit/cost-per-sqft | L2 | pending |

## F15 — Record Edits & Activity Log

| Method | Endpoint | Description | Priority | Progress |
|---|---|---|---|---|
| `GET` | `/api/v1/activity-logs` | View/filter activity log by record/site/user/action/date; sensitive hidden from non-authorized user | L1 | pending |
| `GET` | `/api/v1/sites/{id}/activity-log` | Site-scoped activity view (transfers/category ops/CRUD events) | L1 | pending |
