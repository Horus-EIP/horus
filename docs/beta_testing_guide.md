# Beta Testing Guide

**Last Updated:** January 29, 2026

This document provides instructions for running and verifying the beta test plan success criteria.

---

## Pending Tests (F9, F10, F19)

These features require a running agent service to process tasks. To complete testing:
1. Start the agent service: `docker-compose up -d agent`
2. Ensure the agent registers with the MAS orchestrator
3. Re-run the integration tests

---

## How to Run Tests

```bash
# Start Docker services
cd src/infra && docker-compose up -d

# Run integration tests
cd src/services/mas
python client_tests/test_beta_integration.py

# Or run unit tests with pytest
python -m pytest tests/test_beta_success_criteria.py -v
```

---

## UI Testing Procedures

| Feature | UI Test Steps |
|---------|---------------|
| F1 | Navigate to `/login`, enter credentials, verify redirect to dashboard |
| F2 | Admin Panel → Users → Create User → Fill form → Verify in list |
| F3 | Admin Panel → Users → Delete → Try login with deleted user |
| F4 | Admin Panel → Users → Edit Role → Verify permissions change |
| F5 | Admin Panel → Users → View list with filters |
| F6 | Chat → New Conversation → Enter name → Verify in sidebar |
| F7 | Chat → View conversation list in sidebar |
| F8 | Chat → Right-click conversation → Delete → Confirm removal |
| F9 | Chat → Type message → Verify appears instantly |
| F10 | Chat → Ask question → Verify AI response with citations |
| F11 | Chat → Click conversation → Verify message history loads |
| F12 | Knowledge Store → Upload → Verify processing indicator |
| F13 | Knowledge Store → View documents list with categories |
| F14 | Knowledge Store → Delete document → Search to verify removal |
| F15 | Knowledge Store → Use search with filters |
| F16 | Admin Panel → Agents → Register → Verify API key returned |
| F17 | Dashboard → View agents widget → Verify status updates |
| F18 | Admin Panel → Agents → Delete → Verify removal |
| F19 | Chat → Create task → Verify assignment notification |
| F20 | Dashboard/Tasks → View queue statistics |
| F21 | Tasks → Cancel running task → Verify cancellation |
| F22 | Chat → Submit task → Verify WebSocket notification |
| F23 | Navigate to Dashboard → Verify < 3s load |
| F24 | Dashboard → Watch analytics graph update in real-time |

---

## Test Files

| File | Description |
|------|-------------|
| `src/services/mas/tests/test_beta_success_criteria.py` | Unit tests with mocked dependencies |
| `src/services/mas/client_tests/test_beta_integration.py` | Integration tests against running server |

---

## Related Documentation

- [Beta Test Plan](../beta_test_plan.md) - Success criteria and feature list
- [Testing Policy](./testing_policy.md) - General testing guidelines
