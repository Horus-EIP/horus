# Horus Demo Playbook

Step-by-step guide for demonstrating the Horus Multi-Agent System.

## Pre-Demo Checklist

### System Requirements
- [ ] Docker Desktop running
- [ ] At least 8GB RAM available
- [ ] Ports 3000, 8000, 8080, 3001, 16686 available

### Start the Demo Environment

```bash
cd scripts/demo
chmod +x run_demo.sh
./run_demo.sh
```

Wait for all services to be ready (~2-3 minutes).

### Verify Services

| Service | URL | Expected |
|---------|-----|----------|
| Web Client | http://localhost:3000 | UI loads |
| MAS API Docs | http://localhost:8000/docs | Swagger UI |
| Knowledge Store | http://localhost:8080/docs | Swagger UI |
| Grafana | http://localhost:3001 | Login page |
| Jaeger | http://localhost:16686 | Trace search |

---

## Demo Script

### Part 1: System Overview (5 minutes)

**Objective:** Introduce the architecture and key components.

1. **Show Architecture Diagram**
   - Explain MAS (Multi-Agent System Orchestrator)
   - Explain Agent service and RAG pipeline
   - Explain Knowledge Store

2. **Show Web Client Interface**
   - Navigate to http://localhost:3000
   - Point out the chat interface
   - Explain conversation management

3. **Show API Documentation**
   - Navigate to http://localhost:8000/docs
   - Highlight key endpoints:
     - `/auth/token` - Authentication
     - `/agents/` - Agent management
     - `/tasks/` - Task orchestration
     - `/conversations/` - Chat management

---

### Part 2: Knowledge Retrieval Demo (10 minutes)

**Objective:** Demonstrate RAG-powered question answering.

1. **Open Web Client** (http://localhost:3000)

2. **Create a New Conversation**
   - Click "New Conversation"
   - Name it "Financial Analysis Demo"

3. **Ask Financial Questions**

   **Query 1: Revenue Overview**
   ```
   What was our Q1 2025 revenue?
   ```
   **Expected Response:** ~$12.5 million, 18% YoY growth
   
   **Query 2: Regional Performance**
   ```
   How is each region performing?
   ```
   **Expected Response:** North America 60%, Europe 25%, Asia Pacific 15%
   
   **Query 3: Key Metrics**
   ```
   What are our key customer metrics?
   ```
   **Expected Response:** CAC $245, LTV $2,850, MRR $2.73M

4. **Explain What's Happening**
   - User query → MAS → Agent selection
   - Agent queries Knowledge Store
   - RAG pipeline retrieves relevant documents
   - AI generates contextual response

---

### Part 3: Multi-Agent Orchestration (10 minutes)

**Objective:** Show how tasks are distributed to agents.

1. **Show Registered Agents**
   - Navigate to http://localhost:8000/docs
   - Execute `GET /agents/`
   - Show agent list with skills and status

2. **Create a Task** (via API)
   ```bash
   curl -X POST http://localhost:8000/tasks/new_task/ \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "demand": "Summarize the product roadmap for Q2",
       "conversation_id": "1",
       "skills_required": ["nlp", "summarization"]
     }'
   ```

3. **Show Task Queue Statistics**
   - Execute `GET /tasks/stats/queue`
   - Explain pending, running, completed states

4. **Demonstrate Task Cancellation** (if time permits)
   - Create a task
   - Cancel it: `PATCH /tasks/{task_id}/cancel`

---

### Part 4: Observability Demo (10 minutes)

**Objective:** Show monitoring and tracing capabilities.

1. **Prometheus Metrics**
   - Navigate to http://localhost:9090
   - Show query: `rate(mas_http_requests_total[5m])`
   - Show query: `mas_agents_total{status="active"}`

2. **Grafana Dashboard**
   - Navigate to http://localhost:3001
   - Login: admin/admin
   - Create a simple dashboard panel showing request rate

3. **Jaeger Tracing**
   - Navigate to http://localhost:16686
   - Select service: "mas"
   - Find a recent trace
   - Walk through the trace spans

4. **Structured Logs**
   ```bash
   docker logs mas --tail 20
   ```
   - Show JSON structured logs
   - Point out correlation IDs

---

### Part 5: Security & RBAC (5 minutes)

**Objective:** Demonstrate authentication and access control.

1. **Show Authentication Flow**
   - POST `/auth/token` with credentials
   - Show JWT token structure

2. **Demonstrate RBAC**
   - Show different user roles (admin, manager, user)
   - Show how permissions restrict access

3. **Show Task Permissions**
   - Regular users can create tasks
   - Admins can cancel any task
   - Show permission denied response

---

## Demo Talking Points

### Key Value Propositions

1. **Intelligent Task Routing**
   - LLM-based agent selection
   - Skills matching
   - Load balancing

2. **RAG-Powered Responses**
   - Context-aware answers
   - Document-grounded responses
   - Reduced hallucination

3. **Enterprise-Ready**
   - RBAC security
   - Audit logging
   - Comprehensive observability

4. **Scalable Architecture**
   - Microservices design
   - Horizontal scaling
   - Message queue decoupling

### Common Questions & Answers

**Q: What models does it support?**
A: Currently uses T5 for text generation with GPU acceleration support. Can be extended to other models.

**Q: How is data stored?**
A: PostgreSQL for structured data, ChromaDB for vector embeddings, Redis for caching.

**Q: Can it integrate with existing systems?**
A: Yes, via RESTful APIs and WebSocket for real-time communication.

**Q: What about data security?**
A: JWT authentication, RBAC, encrypted communications, and audit logging.

---

## Post-Demo

### Cleanup

```bash
# Stop services
./run_demo.sh --stop

# Reset all data (optional)
./run_demo.sh --reset
```

### Follow-up Materials
- Architecture documentation: `docs/architecture.md`
- API documentation: http://localhost:8000/docs
- Observability guide: `docs/observability.md`

---

## Troubleshooting During Demo

### Service Not Responding

```bash
# Check service status
docker ps

# Restart specific service
docker restart mas
```

### No Agents Available

```bash
# Check agent logs
docker logs agent

# Restart agent
docker restart agent
```

### Query Returns No Results

- Verify documents are seeded: `curl http://localhost:8080/store/query -d '{"query":"revenue"}'`
- Re-run seeder: `python scripts/demo/seed_demo_data.py`

### Authentication Issues

- Default credentials: admin/admin
- Get fresh token: `curl -X POST http://localhost:8000/auth/token -d "username=admin&password=admin"`
