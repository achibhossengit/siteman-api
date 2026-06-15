# SiteMan — DFD Process List

## Definitions
**1. Process:** Transforms input data into output. *(verbs)*
**2. Data Flow:** Movement of information between components.
**3. Data Store:** Where data is kept for later use.
**4. External Entity:** Users or systems outside the system boundary.


## Level 0 — Context Diagram
The entire SiteMan system = exactly **1 Process**.
Only the external entities that talk to the system are identified here.

| External Entity | Sends to System | Receives from System |
|---|---|---|
| System Admin | Company activation, subscription control | Company list, subscription status |
| System Manager | Subscription monitoring queries | Subscription/payment status |
| Company Admin | Registration, user/site/labour data, subscription payment | Reports, dashboards, company status |
| Company Manager | Labour/site entries, record edits | Site reports, audit trail |
| Site Manager | Attendance, cash, cost entries, record edits | history, statements |
| Payment Gateway | Payment confirmation (IPN/webhook) | Payment request |

---


## Level 1 — Major Process Groups
The single Level 0 system is divided by major functional area. Each section heading of the feature list maps to roughly one Level 1 process:

| # | Process |
|---| --- |
| P1 | Manage Authentication |
| P2 | Manage Platform |
| P3 | Manage Company |
| P4 | Manage Company Subscription |
| P5 | Manage Users |
| P6 | Manage Sites |
| P7 | Manage Labour Accounts |
| P8 | Manage Labour Payments (Advance & Fooding) |
| P9 | Manage Labour Payment Return |
| P10 | Manage Labour Session |
| P11 | Manage Daily Attendance & Extra Work |
| P12 | Manage Site Expense |
| P13 | Manage Site Cash |
| P14 | Manage Site Bills |
| P15 | Generate Reports |
| P16 | Record Edits & Audit Trail |

---

## Level 2

### P1 → Manage Authentication
| # | Process |
|---|---|
| P1.1 | Login with phone & password |
| P1.2 | Register and create company (registrant becomes Company Admin) |
| P1.3 | Reset forgotten password |
| P1.4 | Change password |
| P1.5 | Logout |

### P2 → Manage Platform
| # | Process |
|---|---|
| P2.1 | System user login |
| P2.2 | View and search all companies |
| P2.3 | Activate / deactivate a company |
| P2.4 | Manage subscription plans (tiers, pricing, durations) |
| P2.5 | Monitor subscription status of all companies |
| P2.6 | System admin will create system users |
| P2.7 | System admin will assign user to different system roles |
| P2.8 | System admin will assign user to system level permissions |
| P2.9 | Data correction on sealed/closed company data (support) |

### P3 → Manage Company
| # | Process |
|---|---|
| P3.1 | Create company (auto-created on registration) |
| P3.2 | View company profile & status |
| P3.3 | Edit company details (name, recent activity) |
| P3.4 | Manage expense categories (company-level, shared by all sites) |

### P4 → Manage Company Subscription
| # | Process |
|---|---|
| P4.1 | View subscription status, current plan, and validity |
| P4.2 | Pay for plan via payment gateway |
| P4.3 | Renew Plan |
| P4.4 | Upgrade plan |
| P4.5 | Downgrade plan |
| P4.6 | Disable write access on expiry |
| P4.7 | Send renewal reminders |

### P5 → Manage Users
| # | Process |
|---|---|
| P5.1 | Create user |
| P5.2 | Assign role to user |
| P5.3 | Assign user to one or more sites |
| P5.4 | Assign permissions to user |
| P5.5 | Activate / deactivate user |
| P5.6 | Delete user |
| P5.7 | View and search users |

### P6 → Manage Sites
| # | Process |
|---|---|
| P6.1 | Create / edit site (validate open site count against plan limit) |
| P6.2 | Deactivate & Activate Site |
| P6.3 | Close site permanently (zero cash, set closed_at, build summary, cron purge details after 30d except editable=true) |
| P6.4 | Reopen a closed site (check plan slot, clear closed_at, delete summary; only while details un-purged) |
| P6.5 | Delete site |
| P6.6 | Assign managers to site |
| P6.7 | View company sites (managers see only assigned sites) |
| P6.8 | View site report (balance, revenue, floor breakdown) |
| P6.9 | Manage site floors (name, serial, sqft, rate → contract value) |
| P6.10 | Deactivate/Activate site floors |
| P6.11 | Mark floor as done |

### P7 → Manage Labour Accounts
| # | Process |
|---|---|
| P7.1 | Create / edit labourer |
| P7.2 | Move labourer to site|
| P7.3 | Activate / deactivate labour account |
| P7.4 | Update labour salary for a date range |
| P7.5 | View and search labourers by site / status |
| P7.6 | Delete labour account |

### P8 → Manage Labour Payments (Advance & Fooding)
| # | Process |
|---|---|
| P8.1 | Issue advance pay (LabourAdvancePay; blocked if labour inactive) |
| P8.2 | Issue fooding pay (LabourFoodingPay; seeded from default_fooding) |
| P8.3 | Track labour balance (earnings − advance − fooding + returns) |
| P8.4 | View payment history (advance + fooding ledgers) |

### P9 → Manage Labour Payment Return
| # | Process |
|---|---|
| P9.1 | Record labour return (overpaid money) |
| P9.2 | View return history |

### P10 → Manage Labour Session
| # | Process |
|---|---|
| P10.1 | Create / seal a labour session (vacation: review → settle → per-site rollup (LabourSiteSession) → LabourSession → seal editable=false → deactivate) |
| P10.2 | View session history (per-site breakdown, carried balances) |

### P11 → Manage Daily Attendance & Extra Work
| # | Process |
|---|---|
| P11.1 | Record daily attendance (grain: labour / floor / day; present + salary snapshot, editable) |
| P11.2 | Record extra work (LabourExtraWork: site / floor / labour / date / amount) |
| P11.3 | View attendance & extra work history (by labourer / site / floor / date) |

### P12 → Manage Site Expense
| # | Process |
|---|---|
| P12.1 | Record site construction cost (SiteCost: floor required, category nullable) |
| P12.2 | Record hidden cost (HiddenCost: floor + category nullable) |
| P12.3 | View cost history |

### P13 → Manage Site Cash
| # | Process |
|---|---|
| P13.1 | Record cash deposit |
| P13.2 | Record cash return |
| P13.3 | View site cash history |

### P14 → Manage Site Bills
| # | Process |
|---|---|
| P14.1 | Create Site Bills |
| P14.2 | View bill history |

### P15 → Generate Reports
| # | Process |
|---|---|
| P15.1 | Labour balance report |
| P15.2 | Site expense report |
| P15.3 | Site balance report |
| P15.4 | Site revenue report |
| P15.5 | Site labour cost report |
| P15.6 | Summary for a desired date range |
| P15.7 | Company dashboard (site overview, alerts) |
| P15.8 | Floor costing & revenue report (per floor: contract, billed, cost, profit) |

### P16 → Record Edits & Audit Trail
| # | Process |
|---|---|
| P16.1 | Edit / delete an editable record (editable=true only; auto-write audit log, recalc later rows) |
| P16.2 | View audit trail (by record / site / user / action / date) |
| P16.3 | Remove audit log entries (admin soft-delete; never edit; system can restore) |


## Subscription Model
Plan tiers are based on open site count only. Longer durations get a per-month discount. Prices in BDT.

| Plan | Open Sites | 1 Month | 6 Months | 1 Year |
|---|---|---|---|---|
| **Free** | Up to 1 | Free | — | — |
| **Basic** | Up to 5 | 600 × 1 = **600** | 550 × 6 = **3,300** | 500 × 12 = **6,000** |
| **Popular** | Up to 10 | 1,000 × 1 = **1,000** | 950 × 6 = **5,700** | 900 × 12 = **10,800** |
| **Business** | Up to 20 | 3,000 × 1 = **3,000** | 2,900 × 6 = **17,400** | 2,500 × 12 = **30,000** |
| **Custom** | 20+ | negotiated | negotiated | negotiated |

## Subscription Renewal & Plan Management

When a subscription expires, write access to all sites is disabled and the
admin receives an alert to renew payment.

#### 1. Renew
- Admin can renew plan at any time.

#### 2. Upgrading (e.g. 10 → 20 open sites)

- **After Expiry:** Admin can choose any upper or same plan — straightforward renewal.
- **Before Expiry:** Calculate the remaining value of the current plan and adjust the difference against the new plan cost.

#### 3. Downgrading (e.g. 10 → 5 open sites)

- **After Expiry:** System checks how many sites are currently opened before allowing a downgrade.
  - If opened sites **exceed** the target plan limit → admin is prompted to either **close the excess sites** or **remain on the current plan**.
  - If opened sites are **within** the target plan limit → downgrade proceeds normally.
- **Before Expiry:** Downgrading is **not allowed** until the current plan expires.

## Site States
Two independent state axes for a site:

| Field | Value | Meaning |
|---|---|---|
| `closed_at` | `null` | **Open** — site is ongoing. Counts toward the plan's open-site limit. |
| `closed_at` | timestamp | **Closed** — work permanently done. Company users see only the closure summary; detail rows stay in the same DB but are hidden, then a cron purges them 30 days after `closed_at` (except `editable=true` rows). Does not count toward the plan limit. Reopen possible until purge. |
| `is_active` | `True` | **Active** — new data (attendance, cash, cost) can be recorded. |
| `is_active` | `False` | **Inactive** — temporarily paused. No new data can be created. Old data remains accessible. Can be reactivated at any time. |

> A site may be open (`closed_at=null`) and inactive (`is_active=False`) at the same time — temporarily paused but still ongoing. The plan limit counts all open sites regardless of active/inactive state.
