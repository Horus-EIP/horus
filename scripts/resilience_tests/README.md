# Resilience Tests

End-to-end tests to verify system behavior under failure conditions.

## Quick Start

```bash
# Install dependencies
pip install httpx

# Run all tests
python test_resilience.py --url http://localhost:8000 --ks-url http://localhost:8080
```

## Tests Included

### 1. Data Persistence
Verifies that data created in the system persists correctly and can be retrieved.

### 2. Conversation Recovery
Tests that conversation data survives and can be queried after system operations.

### 3. Agent Re-registration
Verifies agents are tracked correctly and status is maintained.

### 4. Knowledge Store Recovery
Tests that the Knowledge Store is accessible and can handle queries.

### 5. Graceful Degradation
Verifies the system returns appropriate error codes (404, 401) for error conditions.

### 6. Concurrent Requests
Tests system behavior under concurrent load (10 simultaneous requests).

## Manual Resilience Testing

### Test MAS Restart

```bash
# 1. Create some data
curl -X POST http://localhost:8000/conversations/create \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Conversation"}'

# 2. Restart MAS
docker restart mas

# 3. Wait for MAS to come back
sleep 30

# 4. Verify data persists
curl http://localhost:8000/conversations/all \
  -H "Authorization: Bearer <token>"
```

### Test RabbitMQ Restart

```bash
# 1. Restart RabbitMQ
docker restart rabbitmq

# 2. Wait for recovery
sleep 30

# 3. Verify MAS reconnects
curl -X POST http://localhost:8000/rabbitmq/heartbeat

# 4. Verify agents re-register
curl http://localhost:8000/agents/
```

### Test PostgreSQL Restart

```bash
# 1. Restart PostgreSQL
docker restart postgres

# 2. Wait for recovery
sleep 20

# 3. Verify MAS reconnects
curl http://localhost:8000/conversations/all \
  -H "Authorization: Bearer <token>"
```

### Test Agent Failure

```bash
# 1. Stop agent
docker stop agent

# 2. Verify MAS handles absence
curl http://localhost:8000/agents/

# 3. Restart agent
docker start agent

# 4. Wait for re-registration
sleep 30

# 5. Verify agent is back
curl http://localhost:8000/agents/
```

### Test Knowledge Store Unavailability

```bash
# 1. Stop knowledge store
docker stop knowledge_store

# 2. Verify system handles gracefully
# (Tasks should fail with appropriate error)

# 3. Restart knowledge store
docker start knowledge_store

# 4. Verify recovery
curl http://localhost:8080/health
```

## Expected Behavior

| Scenario | Expected Behavior |
|----------|-------------------|
| MAS restart | Data persists, connections re-establish |
| RabbitMQ restart | MAS reconnects, agents re-register |
| PostgreSQL restart | MAS reconnects, data preserved |
| Agent failure | Tasks fail gracefully, no data loss |
| Knowledge Store down | Queries fail with error, system stable |

## Success Criteria

- ✅ All data persists across restarts
- ✅ Services reconnect automatically
- ✅ No data corruption
- ✅ Graceful error handling
- ✅ Concurrent requests handled correctly
