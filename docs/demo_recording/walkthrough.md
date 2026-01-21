# Demo Walkthrough Documentation

**Version:** 1.0  
**Target Audience:** Stakeholders, Evaluators, Technical Reviewers

---

## Demo Overview

This document provides a comprehensive walkthrough of the Horus Multi-Agent System, designed to accompany live demonstrations or serve as standalone documentation.

### Demo Duration
- **Quick Demo:** 15 minutes (core features)
- **Standard Demo:** 30 minutes (all features)
- **Technical Deep Dive:** 45-60 minutes (architecture + features)

---

## System Access

### URLs

| Component | URL | Credentials |
|-----------|-----|-------------|
| Web Client | http://localhost:3000 | demo_user / demo123 |
| API Documentation | http://localhost:8000/docs | - |
| Grafana Dashboards | http://localhost:3001 | admin / admin |
| Jaeger Tracing | http://localhost:16686 | - |
| Prometheus | http://localhost:9090 | - |

### Demo User Accounts

| Username | Password | Role | Purpose |
|----------|----------|------|---------|
| admin | admin | Administrator | Full access demo |
| demo_user | demo123 | User | Standard user demo |
| demo_manager | manager123 | Manager | Team management demo |

---

## Demo Scenes

### Scene 1: Introduction (3 min)

**Objective:** Set the context and explain what Horus does.

**Talking Points:**
1. "Horus is an AI-powered multi-agent system for enterprise task automation"
2. "It orchestrates specialized AI agents to handle complex queries"
3. "The system uses RAG (Retrieval-Augmented Generation) for accurate, document-grounded responses"

**Screenshot Reference:**

```
┌─────────────────────────────────────────────────────┐
│                    HORUS                             │
│         Multi-Agent System Dashboard                 │
│                                                      │
│  ┌─────────────────┐  ┌─────────────────────────┐  │
│  │   Sidebar       │  │   Chat Interface         │  │
│  │                 │  │                          │  │
│  │   Conversations │  │   Welcome to Horus       │  │
│  │   - Demo 1      │  │                          │  │
│  │   - Demo 2      │  │   How can I help you?    │  │
│  │                 │  │                          │  │
│  │                 │  │   [___________________]  │  │
│  │                 │  │   [Send]                 │  │
│  └─────────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

### Scene 2: User Authentication (2 min)

**Objective:** Demonstrate secure authentication.

**Steps:**
1. Navigate to http://localhost:3000
2. Show login page
3. Login with demo_user / demo123
4. Point out JWT token in browser storage (dev tools)

**Key Points:**
- "JWT-based authentication"
- "Role-based access control"
- "Secure password storage with bcrypt"

---

### Scene 3: Knowledge-Based Query (5 min)

**Objective:** Demonstrate RAG-powered question answering.

**Steps:**

1. **Create new conversation**
   - Click "New Conversation"
   - Name: "Financial Analysis Demo"

2. **Ask first query**
   ```
   What was our Q1 2025 revenue?
   ```
   **Expected Response:** ~$12.5 million, 18% YoY growth

3. **Follow-up query**
   ```
   How are the different regions performing?
   ```
   **Expected Response:** North America 60%, Europe 25%, Asia Pacific 15%

4. **Complex query**
   ```
   Compare our customer acquisition cost with customer lifetime value
   ```
   **Expected Response:** CAC $245 vs LTV $2,850

**Key Points:**
- "The system retrieves relevant documents from the Knowledge Store"
- "Responses are grounded in actual data, reducing hallucination"
- "Multiple queries maintain conversation context"

---

### Scene 4: Agent Orchestration (5 min)

**Objective:** Show how tasks are routed to agents.

**Steps:**

1. **Show API Documentation**
   - Navigate to http://localhost:8000/docs
   - Highlight endpoints: /agents/, /tasks/

2. **View Registered Agents**
   - Execute `GET /agents/`
   - Show agent list with skills and status

3. **Create Task via API**
   ```bash
   POST /tasks/new_task/
   {
     "demand": "Summarize the product roadmap",
     "conversation_id": "1",
     "skills_required": ["nlp"]
   }
   ```

4. **Show Task Status**
   - Execute `GET /tasks/stats/queue`
   - Explain pending → running → completed flow

**Key Points:**
- "LLM-based agent selection for optimal routing"
- "Skills matching ensures tasks go to capable agents"
- "Task cancellation available for long-running jobs"

---

### Scene 5: Real-Time Communication (3 min)

**Objective:** Demonstrate WebSocket integration.

**Steps:**

1. Open browser developer tools → Network → WS
2. Send a message in the chat
3. Show WebSocket frames in real-time
4. Point out the correlation IDs

**Key Points:**
- "Real-time updates via WebSocket"
- "No polling required - instant responses"
- "Connection resilience with automatic reconnection"

---

### Scene 6: Observability (5 min)

**Objective:** Show monitoring and tracing capabilities.

**Steps:**

1. **Prometheus Metrics**
   - Navigate to http://localhost:9090
   - Query: `mas_http_requests_total`
   - Query: `mas_agents_total{status="active"}`

2. **Grafana Dashboard**
   - Navigate to http://localhost:3001
   - Login: admin / admin
   - Show request rate panel
   - Show agent status panel

3. **Jaeger Tracing**
   - Navigate to http://localhost:16686
   - Select service: "mas"
   - Find a recent trace
   - Walk through span hierarchy

**Key Points:**
- "Full visibility into system operations"
- "Distributed tracing across services"
- "Structured logging with correlation IDs"

---

### Scene 7: RBAC & Security (3 min)

**Objective:** Demonstrate access control.

**Steps:**

1. **Show Role Differences**
   - Login as admin - show full access
   - Login as demo_user - show restricted access

2. **API Authorization**
   ```bash
   # Without token - 401
   curl http://localhost:8000/agents/
   
   # With token - 200
   curl http://localhost:8000/agents/ \
     -H "Authorization: Bearer <token>"
   ```

3. **Permission Denied**
   - Try accessing admin endpoint as regular user
   - Show 403 response

**Key Points:**
- "Role-based access control"
- "Fine-grained permissions"
- "Secure by default"

---

### Scene 8: Task Management (3 min)

**Objective:** Show task lifecycle management.

**Steps:**

1. **Create a Task**
   - Use Web Client or API

2. **View Task Status**
   ```bash
   GET /tasks/{task_id}
   ```

3. **Cancel Task**
   ```bash
   PATCH /tasks/{task_id}/cancel
   ```

4. **Queue Statistics**
   ```bash
   GET /tasks/stats/queue
   ```

**Key Points:**
- "Full task lifecycle management"
- "Cancellation for long-running tasks"
- "Real-time status tracking"

---

## Technical Deep Dive (Optional)

### Architecture Overview

```
                    ┌─────────────────────────┐
                    │      Web Client         │
                    │      (Next.js)          │
                    └───────────┬─────────────┘
                                │ HTTPS
                    ┌───────────▼─────────────┐
                    │      MAS API            │
                    │      (FastAPI)          │
                    │  ┌─────────────────┐    │
                    │  │ Auth │ Agents │ Tasks│
                    │  └─────────────────┘    │
                    └───────────┬─────────────┘
              ┌─────────────────┼─────────────────┐
              │                 │                 │
    ┌─────────▼─────┐  ┌───────▼──────┐  ┌──────▼──────┐
    │  PostgreSQL   │  │   RabbitMQ   │  │    Agent    │
    │  (Persistence)│  │   (Queue)    │  │  (RAG/LLM)  │
    └───────────────┘  └──────────────┘  └──────┬──────┘
                                                │
                                      ┌─────────▼─────────┐
                                      │  Knowledge Store  │
                                      │    (ChromaDB)     │
                                      └───────────────────┘
```

### Data Flow

1. User submits query via Web Client
2. MAS receives request, authenticates user
3. Task published to RabbitMQ
4. Agent consumes task
5. Agent queries Knowledge Store
6. RAG pipeline generates response
7. Response published to RabbitMQ
8. MAS delivers to user via WebSocket

---

## Demo Troubleshooting

### Common Issues During Demo

| Issue | Quick Fix |
|-------|-----------|
| Services not responding | `docker compose restart` |
| No agents available | Wait 30s or restart agent service |
| Authentication failed | Check credentials, get fresh token |
| Empty query results | Re-run seed script |

### Recovery Commands

```bash
# Quick restart
cd src/infra
docker compose restart

# Full reset
docker compose down && docker compose up -d

# Re-seed data
python scripts/demo/seed_demo_data.py
```

---

## Key Messages

### For Business Stakeholders

1. **Efficiency:** "Automates complex knowledge work"
2. **Accuracy:** "Responses grounded in your documents"
3. **Security:** "Enterprise-grade access control"
4. **Scalability:** "Handles growing workloads"

### For Technical Evaluators

1. **Architecture:** "Clean microservices design"
2. **Observability:** "Full monitoring stack"
3. **Integration:** "Standard REST/WebSocket APIs"
4. **Extensibility:** "Easy to add new agents/skills"

---

## Appendix: Sample Queries

### Financial Queries
- "What was our Q1 revenue?"
- "What is our customer acquisition cost?"
- "How does North America compare to Europe in revenue?"

### Product Queries
- "What's on the Q2 roadmap?"
- "When will mobile apps be available?"
- "What features were completed in Q1?"

### Sales Queries
- "Which sales team is performing best?"
- "What is our average deal size?"
- "What's the current pipeline value?"

### General Knowledge
- "What is Horus?"
- "How does the RAG pipeline work?"
- "What security features are available?"

---

**Document Owner:** Demo Team  
**Last Updated:** January 2026
