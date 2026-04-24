# COPY-PASTE CHEAT SHEET

Keep this open on a second monitor or phone during the demo. Every value is ready to paste.

---

## DEPLOY COMMANDS

```bash
docker compose pull
docker compose up -d
docker compose ps
```

Open afterwards: http://localhost:3000

---

## ADMIN ACCOUNT (Alice)

| Field | Value |
|-------|-------|
| Username | `alice.chen` |
| Password | `FinCorp2026!` |
| Email | `alice.chen@fincorp.com` |

---

## AGENT REGISTRATION

| Field | Value |
|-------|-------|
| Name | `FinCorp-Analyst` |
| Description | `Financial analyst agent for FinCorp — reasons over internal financial reports, compliance docs, and company policy.` |
| Skills | `financial_analysis, compliance, reporting, document_qa` |
| Model | (leave default) |

---

## DOCUMENTS TO UPLOAD

All in `demo_assets/`, upload in this order:

1. `1_Q4_2025_Financial_Report.md`
2. `2_Employee_Handbook.md`
3. `3_Compliance_Guidelines.md`
4. `4_Expense_Policy.md`
5. `5_IT_Security_Policy.md`

---

## CHAT PROMPTS

**Conversation name:** `FinCorp Finance Review`

**Prompt 1 — simple retrieval (expect < 15s):**

```
What was FinCorp's Q4 2025 revenue and who signed the report?
```

**Prompt 2 — multi-step reasoning (expect < 60s):**

```
Cross-reference our expense policy with the Q4 report — are there any reimbursement categories where we spent more than the policy allows, and who would be the approver for an overage?
```

**Prompt 3 — backup if time allows:**

```
Summarize FinCorp's GDPR obligations from the compliance document and list any deadlines we have in the next 90 days.
```

---

## KNOWLEDGE STORE QUERIES

| # | Query | Filter |
|---|-------|--------|
| 1 | `password policy` | none |
| 2 | `GDPR` | Category = Compliance |
| 3 | (empty search) | Entity = person: Michael Brown |
| 4 | `reimbursement` | Entity type = amount |
| 5 | `incident response` | Category = Security |

---

## USERS TO CREATE (Admin Panel)

| Username | Password | Role |
|----------|----------|------|
| bob.martinez | Manager2026! | manager |
| carol.white | User2026! | user |
| david.kim | User2026! | user |
| test.user | Test2026! | user *(create then delete on stage)* |

**Role change demo:** `carol.white` → `manager` → back to `user`.

---

## STRESS TEST TASKS (if running manually instead of script)

Paste these one per task, all with skill `financial_analysis`:

1. `Summarize the key financial risks from the Q4 2025 report.`
2. `List all reimbursable expense categories over $500.`
3. `What is our SOX compliance audit schedule?`
4. `Who is the designated Data Protection Officer?`
5. `What are the maximum vacation days per year?`
6. `Explain our incident response SLA.`
7. `What is the minimum password length required?`
8. `Summarize Q4 2025 operating expenses.`
9. `Who approves expense reports over $5,000?`
10. `What is the notice period for terminating an employee?`

---

## USEFUL URLS

| Service | URL | Credentials |
|---------|-----|-------------|
| Web client | http://localhost:3000 | alice.chen / FinCorp2026! |
| Grafana | http://localhost:3001 | admin / admin |
| Jaeger | http://localhost:16686 | — |
| Prometheus | http://localhost:9090 | — |
| RabbitMQ | http://localhost:15672 | guest / guest |

---

## RESET EVERYTHING (if demo breaks mid-run)

```bash
docker compose down -v
docker compose up -d
```

~2 minutes to come back up clean.
