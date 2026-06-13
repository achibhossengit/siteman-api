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
| P8 | Manage Labour Payment |
| P9 | Manage Labour Payment Return |
| P10 | Manage Labour Worksession |
| P11 | Manage Daily Attendance |
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
| P6.3 | Close site permanently (data archived, users lose access) |
| P6.4 | Delete site |
| P6.5 | Assign managers to site |
| P6.6 | View company sites (managers see only assigned sites) |
| P6.7 | View site detail (balance, recent activity) |
| P6.8 | Manage site floors (name, serial, sqft, rate → contract value) |
| P6.9 | Deactivate/Activate site floors |
| P6.10 | Mark floor as done |

### P7 → Manage Labour Accounts
| # | Process |
|---|---|
| P7.1 | Create / edit labourer |
| P7.2 | Assign labourer to site |
| P7.3 | Move labourer between sites (one site at a time) |
| P7.4 | Activate / deactivate labour account |
| P7.5 | Update labour salary for a date range |
| P7.6 | View and search labourers by site / status |
| P7.7 | Delete labour account |

### P8 → Manage Labour Payment
| # | Process |
|---|---|
| P8.1 | Issue labour payment (any time, unless labour inactive) |
| P8.2 | Track labour balance |
| P8.3 | View labour payment history |

### P9 → Manage Labour Payment Return
| # | Process |
|---|---|
| P9.1 | Record labour return (overpaid money) |
| P9.2 | View return history |

### P10 → Manage Labour Worksession
| # | Process |
|---|---|
| P10.1 | Create work session |
| P10.2 | View work session history |

### P11 → Manage Daily Attendance
| # | Process |
|---|---|
| P11.1 | Record daily attendance (grain: labour / floor / day) |
| P11.2 | View attendance history (by labourer / site / floor / date) |

### P12 → Manage Site Expense
| # | Process |
|---|---|
| P12.1 | Record site construction cost (SiteCost: floor + category required) |
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
| P16.1 | Edit / delete an unlocked record (auto-write audit log, recalc later rows) |
| P16.2 | View audit trail (by record / site / user / action / date) |
| P16.3 | Remove audit log entries (admin only; never edit) |


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
| `is_closed` | `False` | **Open** — site is ongoing. Counts toward the plan's open-site limit. |
| `is_closed` | `True` | **Closed** — site work is permanently done. Records are archived. Company users lose access. Data may be deleted by system admin. Does not count toward the plan limit. |
| `is_active` | `True` | **Active** — new data (attendance, cash, cost) can be recorded. |
| `is_active` | `False` | **Inactive** — temporarily paused. No new data can be created. Old data remains accessible. Can be reactivated at any time. |

> A site may open (`is_closed=False`) and inactive (`is_active=False`) at the same time — temporarily paused but still ongoing. The plan limit counts all open sites regardless of active/inactive state.
