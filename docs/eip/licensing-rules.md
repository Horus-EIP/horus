# Horus Licensing Rules & State Specifications

**Related:** `ADR-004-closed-source-licence.md`, `LICENSE`
**Target:** Implementation specs for the licensing engine and backend validation.

---

## 1. License Tiers & Active User Caps

The licensing model enforces subscription tiers based on site deployment and active user seats as defined in ADR-004:

| Tier | User Cap | Scope |
|---|---|---|
| **Starter** | Up to 25 active users | Single site, quarterly billing |
| **Team** | Up to 100 active users | Single site, quarterly billing |
| **Enterprise** | Unlimited active users | Multi-site, custom contract |

### User Cap Enforcement & The `capped` Operational Status
* **Active vs. Inactive Accounts:** The cap applies strictly to **active accounts** (`is_active = true`). Deactivated or suspended accounts do not count toward the limit.
* **Orthogonal `capped` Flag:** The `capped` status is an operational flag (`is_capped = true`) that can overlay any valid, warning, or grace state if active users reach or exceed the tier limit (`active_user_count >= user_cap`).
* **Impact of `capped`:** Core product features (chat, RAG, document uploads, agent execution) **remain fully operational**. However, any action attempting to create a new user or reactivate a suspended account is strictly blocked if it causes the active user count to exceed the tier cap (or if it is already at/above the limit) until the count drops below the threshold or a higher tier license is uploaded.

---

## 2. Temporal Boundaries, Grace Period End & Evaluation Frequency

To ensure deterministic behavior across restarts and deployments:
* **Timezone Standard:** All license validity checks, expiration calculations, and clock comparisons are executed strictly in **UTC**.
* **Expiration Boundary:** The `valid_until` date is inclusive, and the license officially expires at **`00:00:00 UTC` on the day immediately following** the `valid_until` date.
* **Grace Period Boundary:** The 15-day grace period begins immediately at `00:00:00 UTC` on the day of expiration and ends strictly at `00:00:00 UTC` on the 16th day. As of that exact instant, the system transitions to `restricted`.
* **Evaluation Frequency:** The license engine evaluates the system state **at application startup** and continuously via an **hourly background verification task**, plus a check before executing any core API request.

---

## 3. Warning Schedule & Precision

Notifications and administrative alerts are triggered based on exact UTC countdowns relative to the expiration instant (`00:00:00 UTC` on the day following `valid_until`):
* **Milestones:** Persistent dashboard banners are triggered whenever the remaining time crosses or is already below:
  * **30 days** remaining (`expiry - 720 hours` or less)
  * **14 days** remaining (`expiry - 336 hours` or less)
  * **7 days** remaining (`expiry - 168 hours` or less)
* **Startup & Offline Resilience:** If the system is offline or stopped when a threshold is crossed, the license evaluation engine determines the most urgent milestone already reached upon application startup and immediately displays the corresponding persistent warning banner.
* **Final Urgency:** The final urgency tier triggers **24 hours or less (`expiry - 24 hours`)** before expiration. During this final 24-hour window, the system evaluates the status hourly but keeps the warning banner **persistently displayed** in the admin UI rather than spamming system logs or duplicate notifications.

---

## 4. Official System License States & Priority

The backend license manager evaluates the license file and environment to report one of eight mutually exclusive lifecycle states, plus the orthogonal `capped` flag:

1. **`missing`**: No license file has been uploaded or configured in the system.
2. **`invalid`**: The license file is malformed, corrupted, or fails cryptographic signature verification (Ed25519 public key mismatch).
3. **`not_yet_valid`**: The license payload is authentic, but current system UTC time is prior to the `valid_from` start date.
4. **`valid`**: The license is authentic, active, and outside any warning or grace windows.
5. **`warning`**: The license is active, but within 30 days of its expiration date.
6. **`grace`**: The expiration date has passed, but the system is currently within the 15-day grace period.
7. **`restricted`**: Both the validity period and the grace period have expired. Core features (chat, uploads, agents, tasks) are disabled; admin access and data export remain active.
8. **`clock_rollback`**: A system clock regression exceeding the 48-hour tolerance threshold has been detected against the persisted high-water mark. Core functions are locked.

The MAS `GET /admin/export` endpoint exports conversations and messages as JSON. It requires the `data:export` permission and deliberately does not use `require_active_license`, so authorized exports remain available in restricted mode.

### State Precedence
* **`clock_rollback`** has **absolute priority** over all other states. If a clock regression is detected, it immediately overrides the system into `clock_rollback`, regardless of whether a valid key is present.
* The `capped` flag can coexist concurrently when the system is in `valid`, `warning`, or `grace` states.

---

## 5. Secure Recovery from `clock_rollback` & Offline Limits

To handle clock tampering and persistence:
* **Persistence Layer:** The highest observed valid UTC timestamp (`last_seen_clock`) is stored in an internal system state table protected by application-level integrity checks.
* **Security Limit (Fully Offline Environment):** In a self-hosted, fully offline deployment, an administrator with physical or root OS access can theoretically alter local files or database records. Therefore, the technical mechanism provides **tamper-detection** rather than absolute tamper-prevention against root users. The ultimate backstop remains the **Commercial Contract and Audit Clause**, making unauthorized bypass legally actionable.
* **Recovery Procedure:** Unlocking a `clock_rollback` state requires either:
  1. Letting natural time advance past the recorded high-water mark.
  2. Uploading a **newly issued, valid license file** signed by the master private key, which explicitly resets the baseline timestamp.

---

## 6. State Transition Lifecycle


```

[ Missing / Invalid / Not Yet Valid ]
│
▼ (Upload valid key & time reached)
[ Valid ] ──(Remaining <= 30d)──► [ Warning ] ──(Expiry reached)──► [ Grace ] ──(Grace elapsed)──► [ Restricted ]

```

*Note: [ Capped ] is an orthogonal flag overlaying Valid/Warning/Grace if active users >= cap.*



---

## 7. Feature Matrix by State

| State | Chat & RAG | Document Uploads | Agent Execution | User Creation / Activation | Admin UI Access | Data & Doc Export | Key Upload / Renewal |
|---|---|---|---|---|---|---|---|
| **`valid` / `warning` / `grace` (under limit)** | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **`valid` / `warning` / `grace` (at or over limit / `capped`)** | ✅ Allowed | ✅ Allowed | ✅ Allowed | ❌ Blocked | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **`restricted`** | ❌ Blocked | ❌ Blocked | ❌ Blocked | ❌ Blocked | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **`clock_rollback`** | ❌ Blocked | ❌ Blocked | ❌ Blocked | ❌ Blocked | ✅ Allowed | ✅ Allowed | ✅ Allowed |
| **`missing` / `invalid` / `not_yet_valid`** | ❌ Blocked | ❌ Blocked | ❌ Blocked | ❌ Blocked | ✅ Allowed | ✅ Allowed | ✅ Allowed |
---