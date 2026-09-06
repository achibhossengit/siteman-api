<p align="center">
  <img src="docs/logo.png" alt="সাইটম্যান (SiteMan)">
</p>

<h3 align="center">
  A SaaS application that helps construction companies manage sites, workers, expenses and operational activities.
</h3>

<p align="center">
  <a href="https://sitemaan.netlify.app">Live app</a>
  ·
  <a href="https://siteman-api-production.up.railway.app/api/docs">API docs</a>
  ·
  <a href="https://youtube.com/playlist?list=PLB6H2J30mWdg">Tutorials</a>
</p>

## Overview
Siteman is a SaaS-based construction management platform designed to help construction companies manage their day-to-day operations from a centralized system.

The backend provides the REST API that powers the Siteman application, handling business logic, data management, authentication, authorization, and communication between the frontend and supporting services.

The platform is designed around a multi-tenant structure where each company operates within its own isolated workspace. Companies can manage their construction sites, users, workforce, expenses, and operational activities while controlling access through role- and permission-based authorization.


## Features

- Multi-tenant company workspaces with isolated data
- JWT-based authentication with token blacklisting
- Role- and permission based authorization
- Site, billing category, site expense and site bills management
- Labour roster, daily attendance and work period management
- Staff acccount management
- Date- and site-based summary reports
- Change tracking and review system for accountability
- Subscription entitlements and usage limits
- Image and file management
- RESTful versioned API with OpenAPI docs
- Automated test suite
- PostgreSQL persistence with Redis caching


## Workflow

- Register a company with your name, company name, phone number, and password
- Log in with phone number and password to receive a JWT
- Create sites and billing categories
- Add staff accounts and assign them to sites
- Add labour to a site and record daily attendance and wages
- Log site expenses and private bills
- Close work periods to seal daily records
- Review activity logs for accountability
- Use date- and site-based reports to summarize operations


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
- Docs (`DEBUG=True`): `http://127.0.0.1:8000/api/docs/`


## Tests

```bash
python manage.py test
```

Tests use the local file backend for media so they never touch R2.


## Author

Develope by [Achib Hossen](https://achibhossen.me) - backend (this repo) and the [React frontend](https://github.com/achibhossengit/siteman-client) behind the live app.
