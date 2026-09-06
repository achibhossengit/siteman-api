<p align="center">
  <img src="docs/logo.png" alt="সাইটম্যান (SiteMan)">
</p>

<h3 align="center">
  A SaaS application for construction companies to manage workers and expenses with accountability.
</h3>

<p align="center">
  <a href="https://sitemaan.netlify.app">Live app</a>
  ·
  <a href="https://siteman-api-production.up.railway.app/api/docs">API docs</a>
  ·
  <a href="https://github.com/achibhossengit/siteman-client">Frontend Repo</a>
  ·
  <a href="https://youtube.com/playlist?list=PLB6H2J30mWdg">Tutorials</a>
  <!-- TODO: add case study link later -->
</p>

## Overview
The platform is designed around a multi-tenant structure where each company operates within its own isolated workspace. Companies can manage their construction sites, users, workforce, expenses, and operational activities while controlling access through role- and permission-based authorization.

The backend provides the REST API that powers the Siteman application, handling business logic, data management, authentication, authorization, and communication between the frontend and supporting services.


## Features

- Multi-tenant company workspaces with isolated data
- JWT-based authentication with token blacklisting
- Role- and permission based authorization
- Site, billing category, site expense and site bills management
- Staff acccount and their permission management
- Worker accounts, daily attendance and work period management

- Worker account transfer between sites
- Date- and site-based summary reports
- Change tracking and review system for accountability
- Subscription entitlements and usage limits
- Image and file management


## Workflow

### Typical path

- Register a company (the registrant becomes company admin) or log in with phone number and password
- Create sites
- Add labour to a site; pick a site and date; record attendance, wages, and cash paid that day
- Log site cash: deposit, cost, or withdrawal
- Check the site balance for a day or a date range
- Close a labour work session when the period is finished
- Review unreviewed changes

### Company

The registering user is `is_companyadmin` and can see every site. Staff created later are not company admins; they only see assigned sites.

- Subscription fields (`paid_until`, site / user / labour limits) are visible, not self-serve. Expired companies stay read-only
- Company name and labour transfer (`labour_transfer_allowed`) can be updated
- Company delete requires the acting user's password. That hard-deletes the tenant: sites, records, and all user accounts including the admin

### Sites

A site is a project. Records are scoped to that site. Company admin sees all sites; other users only see sites they are assigned to.

- Create sites
- Optional billing categories (e.g. floor or basement) to tag attendance and cash
- Site delete requires the acting user's password. Blocked while **unsealed** daily records exist. If every attendance row is sealed, those rows are removed and the site is deleted

### Staff accounts

A company admin can run the company alone, or create staff and assign **sites** plus a **role**:

| Role | Typical use |
|------|-------------|
| Site Manager | Day-to-day attendance, site cash, labour, work sessions |
| Site Auditor | Read operations and **review** audit entries |

- Create staff with name, phone, initial password, groups, and allowed sites
- Staff log in with that phone and password, then change their own password
- Admin can disable or delete staff (delete confirms the admin's password)
- After create, admin cannot change a staff password, which prevents misuse of staff accounts by an admin


### Money on a site

Three books sit under a site:

1. **Daily attendance** — presence, wage, extra earn, fooding, advance, returns
2. **Site cash** — `deposit`, `cost`, `withdrawal`
3. **Private cash** — `bill` or `cost`, meant for company admin (not the site manager’s public ledger)

### Labour (workers)

A labour is a person on the company roster, assigned to **one site at a time**. Attendance is one row per labour per date.

- Create labour
- Record daily attendance and cash paid that day (fooding / advance) plus any amount returned by the labour
- Deactivate labour so they drop off the live attendance roster; past rows still show in history
- Delete labour only when they have **no** daily records. Closing a session does not unlock delete — the sealed rows still exist. Sessions themselves cascade if the labour is removed

### Transfer between sites

Site managers can only record against labour currently on a site they can access. Moving labour to another site updates `current_site` (company setting `labour_transfer_allowed` must be on).

- After transfer, the previous site’s managers no longer see that labour on the roster and cannot add new rows for them
- Historical attendance on the previous site remains on that site
- Only company admin can leave labour unassigned (no site)

### Work sessions

During a period, labour often take fooding/advance; the rest stays as **payable**. Closing a session snapshots every daily row **after** the last session end date:

- Totals: present days, earnings, fooding, advance, returns, payable
- `previous_payable` carries credit or debt into the next period (`cumulative_payable`)
- Those daily rows are **sealed** — no further edit or delete
- Only the **latest** session can be deleted, and only if the sealed row count still matches; delete unseals those rows

### Site balance

Cash sent to a site, minus cash that left the box.

For a day or range:

`balance = previous_balance + deposits + labour returns − withdrawals − site costs − fooding − advance`

- `previous_balance` is the running total through the day before the range (0 for all-time)
- Wage/salary is **payable**, not cash out, until fooding or advance is recorded
- Users with private-cash permission also see private totals on the report

### Audit

Creates, updates, and deletes on attendance, site cash, and work sessions are logged (who, what, when). Unreviewed changes show a badge on the record.

- Site Manager work is logged; they can **view** logs for their sites
- Review (clear the badge, optional note) needs `change_activitylog` — **Site Auditor** in the default roles. The registering company admin has that permission too
- Review is site-scoped for non-admins.


## Tech stack

| Area              | Choice                                                  |
| ----------------- | ------------------------------------------------------- |
| API               | Django REST Framework                                   |
| Auth              | SimpleJWT                                               |
| Database          | PostgreSQL 17                                           |
| Cache             | Redis 7                                                 |
| Docs              | drf-spectacular                                         |
| Email             | Anymail                                                 |
| Files             | django-storages → Cloudflare R2 (S3 API)                |
| Runtime           | Gunicorn, WhiteNoise                                    |
| Hosting           | Railway                                                 |


## Getting started

Requires Python 3.10+, and Postgres 17 + Redis 7 (via Docker Compose or installed locally).

```bash
git clone <this-repo-url>
cd siteman-api
python -m venv .venv
```

Activate the venv, then:

```bash
pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
docker compose up -d
python manage.py migrate
python manage.py runserver
```

- API: `http://127.0.0.1:8000/api/v1/`
- Docs: `http://127.0.0.1:8000/api/docs/`


## Tests

```bash
python manage.py test
```

Tests use the local file backend for media so they never touch R2.


## Author

Develope by [Achib Hossen](https://achibhossen.me) - backend (this repo) and the [React frontend](https://github.com/achibhossengit/siteman-client) behind the live app.
