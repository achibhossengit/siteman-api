# SiteMan — Feature List

Construction site labour and cost management SaaS. Each company is an isolated tenant; the platform owner manages companies and subscriptions.

## Tenant Feature Groups

| # | Feature |
|---| --- |
| F1 | Manage Authentication |
| F2 | Manage Company |
| F3 | Manage Company Subscription |
| F4 | Manage Company Users |
| F5 | Manage Sites |
| F6 | Manage Labour Accounts |
| F7 | Manage Labour Payments (Advance, Fooding & Return) |
| F8 | Manage Labour Work Session |
| F9 | Manage Daily Attendance & Extra Work |
| F10 | Manage Site Expense |
| F11 | Manage Site Cash |
| F12 | Manage Site Bills |
| F13 | Generate Reports |
| F14 | Record Edits & Audit Trail |

## System Feature Groups

| # | Feature |
|---| --- |
| S1 | Manage Platform |

See also [endpoints.md](endpoints.md) (tenant) and [system-endpoint.md](system-endpoint.md) (platform).

---

### F1 → Manage Authentication
| # | Feature |
|---|---|
| F1.1 | Login |
| F1.2 | Register |
| F1.3 | Reset forgotten password |
| F1.4 | Change password |
| F1.5 | Logout |
| F1.6 | Manage profile |

### F2 → Manage Company
| # | Feature |
|---|---|
| F2.1 | Create company |
| F2.2 | View company profile & status |
| F2.3 | Edit company details |
| F2.4 | Manage custom categories |
| F2.5 | Manage company configuration |

### F3 → Manage Company Subscription
| # | Feature |
|---|---|
| F3.1 | View subscription status |
| F3.2 | Pay for plan |
| F3.3 | Renew plan |
| F3.4 | Upgrade plan |
| F3.5 | Downgrade plan |
| F3.6 | Disable write access on expiry |
| F3.7 | Send renewal reminders |

### F4 → Manage Company Users
| # | Feature |
|---|---|
| F4.1 | Create Staff user |
| F4.2 | Assign role to user |
| F4.3 | Assign user to sites |
| F4.4 | Assign permissions to user |
| F4.5 | Activate / deactivate user |
| F4.6 | Delete user |
| F4.7 | View and search users |

### F5 → Manage Sites
| # | Feature |
|---|---|
| F5.1 | Create / edit site |
| F5.2 | Activate / deactivate site |
| F5.3 | Close site permanently |
| F5.4 | Reopen a closed site |
| F5.5 | Delete site |
| F5.6 | Assign users to site |
| F5.7 | View company sites |
| F5.8 | View site report |
| F5.9 | Manage site floors |
| F5.10 | Activate / deactivate site floors |
| F5.11 | Mark floor as done |
| F5.12 | Manage site configuration |
| F5.13 | View site activity log |
| F5.14 | Admin records on a site |
| F5.15 | Remove a billing category (delete or merge) |

### F6 → Manage Labour Accounts
| # | Feature |
|---|---|
| F6.1 | Create / edit labourer |
| F6.2 | Assign / move labourer to site |
| F6.3 | Activate / deactivate labour account |
| F6.4 | Update labour salary |
| F6.5 | View and search labourers |
| F6.6 | Delete labour account |

### F7 → Manage Labour Payments (Advance, Fooding & Return)
| # | Feature |
|---|---|
| F7.1 | Issue advance pay |
| F7.2 | Issue fooding pay |
| F7.3 | Track labour balance |
| F7.4 | View payment history |
| F7.5 | Record labour return |
| F7.6 | View return history |

### F8 → Manage Labour Work Session
| # | Feature |
|---|---|
| F8.1 | Create / seal a labour work session |
| F8.2 | View session history |
| F8.3 | Delete a work session (unseal) |

### F9 → Manage Daily Attendance & Extra Work
| # | Feature |
|---|---|
| F9.1 | Record daily attendance |
| F9.2 | Record extra work |
| F9.3 | View attendance & extra work history |

### F10 → Manage Site Expense
| # | Feature |
|---|---|
| F10.1 | Record site construction cost |
| F10.2 | Record hidden cost |
| F10.3 | View cost history |

### F11 → Manage Site Cash
| # | Feature |
|---|---|
| F11.1 | Record cash deposit |
| F11.2 | Record cash return / withdrawal |
| F11.3 | View site cash history |

### F12 → Manage Site Bills
| # | Feature |
|---|---|
| F12.1 | Create site bill |
| F12.2 | View bill history |

### F13 → Generate Reports
| # | Feature |
|---|---|
| F13.1 | Labour balance report |
| F13.2 | Site expense report |
| F13.3 | Site balance report |
| F13.4 | Site profit report |
| F13.5 | Site labour cost report |
| F13.6 | Summary for a date range |
| F13.7 | Company dashboard |
| F13.8 | Floor costing & revenue report |

### F14 → Record Edits & Activity Log
| # | Feature |
|---|---|
| F14.1 | Edit / delete a record |
| F14.2 | View the activity log |
| F14.3 | Activity logs are permanent |
| F14.4 | Activity view (admin oversight) |

### S1 → Manage Platform
| # | Feature |
|---|---|
| S1.1 | System user login |
| S1.2 | View and search all companies |
| S1.3 | Activate / deactivate a company |
| S1.4 | Manage subscription plans |
| S1.5 | Monitor subscription status |
| S1.6 | Create system users |
| S1.7 | Assign system roles |
| S1.8 | Assign system-level permissions |
| S1.9 | Data correction on sealed / closed data |
| S1.10 | Manage system configuration |
| S1.11 | Reset a company (system user only, OTP dual-control) |
