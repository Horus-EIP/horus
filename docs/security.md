# Security and Compliance

Access control, security audit findings, data protection commitments, and telemetry policy. The RBAC matrix is the source of truth for who can do what; the audit lists known risks and mitigations.

---

## Role-Based Access Control (RBAC)

The Horus system implements a comprehensive Role-Based Access Control (RBAC) mechanism to manage user permissions and secure resources at the API level.

### Overview

RBAC provides:
- **Roles**: Groups of users with similar permissions (Admin, Manager, User, System, Agent)
- **Permissions**: Granular rights to perform specific actions
- **Role-Permission Mapping**: Defines which permissions each role has
- **API Protection**: Endpoints enforce permission checks before executing actions

---

### Roles

The system defines five roles:

#### 1. **Admin** (`admin`)
- **Purpose**: Full system access and administration
- **Use Case**: System administrators, project leads
- **Permissions**: All permissions (create/read/update/delete for users, agents, tasks)
- **Responsibilities**:
  - User account management
  - System configuration
  - Agent registration and lifecycle management
  - Task approval workflows
  - Analytics and reporting

#### 2. **Manager** (`manager`)
- **Purpose**: Operational management without administrative privileges
- **Use Case**: Team leads, operations managers
- **Permissions**: Task/agent operations and analytics (no user management)
- **Can do**:
  - Create, read, and approve tasks
  - View and execute agents
  - View analytics and export data
  - Cannot: Create/edit/delete users, create/update agents

#### 3. **User** (`user`)
- **Purpose**: Standard application users
- **Use Case**: Task creators, analysts
- **Permissions**: Basic task creation and agent execution
- **Can do**:
  - Create and read tasks
  - Execute agents
  - Cannot: Manage users, approve tasks, create agents

#### 4. **System** (`system`)
- **Purpose**: Internal system processes
- **Use Case**: Automated workflows, scheduled tasks
- **Permissions**: Limited to task execution and reading
- **Can do**:
  - Read tasks and agents
  - Execute tasks and agents
- **Cannot**: Create/modify/delete resources, access management functions

#### 5. **Agent** (`agent`)
- **Purpose**: Allow the Agent service to register its worker identities without using the administrator account
- **Use Case**: The MAS login used by the Agent service at startup
- **Permissions**: `agent:create` and `agent:execute` only
- **Can do**:
  - Register agent identities with MAS
  - Send heartbeats (the endpoint also requires that identity's API key)
- **Cannot**: Read or manage users, read agents, delete agents, or access task and system administration routes through role permissions
- **Separate authentication**: Task claim, abandoned-claim, result, and step endpoints authenticate the registered worker with its agent API key; they do not grant the account access to user or admin routes.

---

### Permissions

Permissions are granular rights that control access to specific API operations.

#### User Management
| Permission | Description |
|-----------|-------------|
| `user:create` | Create new user accounts |
| `user:read` | View user details and profile |
| `user:update` | Modify user information |
| `user:delete` | Delete user accounts |

#### Task Management
| Permission | Description |
|-----------|-------------|
| `task:create` | Create new tasks for agents |
| `task:read` | View task details and history |
| `task:execute` | Run/execute tasks |
| `task:delete` | Delete tasks |
| `task:approve` | Approve tasks in workflows |

#### Agent Management
| Permission | Description |
|-----------|-------------|
| `agent:create` | Register new agents |
| `agent:read` | View agent details and capabilities |
| `agent:update` | Modify agent configuration |
| `agent:delete` | Unregister agents |
| `agent:execute` | Execute/invoke agents |

#### System & Analytics
| Permission | Description |
|-----------|-------------|
| `analytics:view` | View system analytics and metrics |
| `data:export` | Export data from the system |
| `system:config` | Modify system configuration |

---

### Role-Permission Matrix

Complete permission mapping for all roles:

| Permission | Admin | Manager | User | System | Agent |
|:-----------|:-----:|:-------:|:----:|:------:|:-----:|
| **User management** | | | | | |
| `user:create` | Yes | No | No | No | No |
| `user:read` | Yes | Yes | Yes | No | No |
| `user:update` | Yes | No | No | No | No |
| `user:delete` | Yes | No | No | No | No |
| **Task management** | | | | | |
| `task:create` | Yes | Yes | Yes | No | No |
| `task:read` | Yes | Yes | Yes | Yes | No |
| `task:execute` | Yes | Yes | No | Yes | No |
| `task:delete` | Yes | Yes | Yes | No | No |
| `task:approve` | Yes | Yes | No | No | No |
| **Agent management** | | | | | |
| `agent:create` | Yes | No | No | No | Yes |
| `agent:read` | Yes | Yes | Yes | Yes | No |
| `agent:update` | Yes | No | No | No | No |
| `agent:delete` | Yes | No | No | No | No |
| `agent:execute` | Yes | Yes | Yes | Yes | Yes |
| **System and analytics** | | | | | |
| `analytics:view` | Yes | Yes | Yes | No | No |
| `data:export` | Yes | Yes | No | No | No |
| `system:config` | Yes | No | No | No | No |

Source of truth: `src/services/mas/auth/permissions.py` (`ROLE_PERMISSION`). These permissions say which routes a role may call; [Who can see what](#who-can-see-what) says which tasks and conversations it then reaches.

---

### Who can see what

The permissions above open the task and conversation routes to several roles; ownership then narrows what each role reaches. Source of truth: `src/services/mas/tasks/task_access.py`, `src/services/mas/conversations/routes.py` and `src/services/mas/chat/routes.py`.

| Role | Read a task and its events | `GET /tasks/list` | Conversation history and chat WebSocket | Cancel a task | Create a task in a conversation |
|:-----|:---------------------------|:------------------|:-----------------------------------------|:--------------|:--------------------------------|
| `admin` | any | every task | any conversation | any | any conversation |
| `manager` | any | every task | only their own | any | only their own |
| `user` | the tasks they own, and every task in a conversation they own | the same tasks | only their own | the same tasks as they read | only their own |
| `system` | as `user` | as `user` | only their own | no (`task:delete` missing) | no (`task:create` missing) |
| `agent` | no role-based task access | no | no | no | no |

- A task's owner is its `owner_username` (the user who queued it), else the owner of its root task. A subtask therefore belongs to whoever owns its chain.
- `GET /tasks/conversation/{id}/running` is for the conversation's owner, a manager or an admin. The agent routes (`/claim`, `/task-result/`, `/task-step/`, `/abandoned-claims`) use the agent's API key, not a role.
- The Agent service logs in to MAS with the dedicated `agent` account to register its worker identities. That account is not an administrator and has only `agent:create` and `agent:execute`. Worker heartbeats require both the role permission and that worker's API key.
- Task claim, abandoned-claim, result and step routes authenticate with a worker API key and verify the worker's relationship to the task; this does not give the `agent` account role-based access to task lists, user data or administrator routes.
- **A conversation's owner reads and cancels every task in it, whoever posted it.** An admin may post into a user's conversation; the answer reaches the user's chat and history anyway, so refusing them the task protected nothing.
- **Managers read every task but not other users' conversations.** A task carries what oversight needs (the question, its status, the answer, the timings and the sources); reading or watching a whole chat live gives more access than that. Least privilege.

---

### Implementation Details

#### Architecture

The RBAC implementation is located in:

**File**: `src/services/mas/auth/permissions.py`

```python
class Permission(str, Enum):
    """Granular permissions for the system"""
    USER_CREATE = "user:create"
    TASK_EXECUTE = "task:execute"
    AGENT_CREATE = "agent:create"
    # ... other permissions

ROLE_PERMISSION: Dict[Role, Set[Permission]] = {
    Role.ADMIN: {Permission.USER_CREATE, Permission.TASK_EXECUTE, ...},
    Role.MANAGER: {Permission.TASK_CREATE, Permission.AGENT_READ, ...},
    # ...
}
```

#### How Permission Checks Work

1. **Request arrives** at an API endpoint
2. **User authentication** extracts JWT token and validates signature
3. **User role** is retrieved from database
4. **Permission required** for endpoint is defined in route
5. **`PermissionChecker` dependency** verifies: `role has permission?`
6. **Access granted/denied** based on check result

#### API Route Protection

Protected endpoints use the `PermissionChecker` dependency:

```python
from auth.permissions import Permission
from fastapi import Depends

@router.post(
    "/users",
    dependencies=[Depends(PermissionChecker(Permission.USER_CREATE))]
)
async def create_user(user_request: CreateUserRequest, db: Session = Depends(get_db)):
    """
    Create a new user (Admin only)
    
    Required Permission: user:create (Admin role)
    """
    return create_user_in_db(user_request, db)
```

---

### Administrator Operations

#### Setting Up RBAC

##### 1. Initial Setup

On first application startup:

```bash
## The system automatically creates:
## - Postgres database
## - Admin user (from environment variables)
## - Role assignments
## - Permission mappings

## Environment variables set in .env (the installer and init-env.sh generate the passwords):
SUPER_USER_USERNAME=admin
SUPER_USER_PASSWORD=<24 generated characters>
SUPER_AGENT_USERNAME=agent
SUPER_AGENT_PASSWORD=<generated agent password>
```

MAS creates the admin account once, on its first start, and refuses to create it when `SUPER_USER_PASSWORD` is empty or `admin`: it logs an error that says how to set one. On every start it also checks the stored password (`src/services/mas/db/admin_account.py`): an account still on the shipped `admin` gets the `SUPER_USER_PASSWORD` from `.env`, and an account whose password was changed in Horus is never touched. The installer shows a password it generated once, at the end, with the login name, and only on a terminal; it never writes it to `install-log.txt`, the `--json-events` stream or `horus-profile.json`. [Upgrades and uninstall](operations.md#upgrades-and-uninstall) says what an upgrade does.

MAS also creates the dedicated `agent` login from `SUPER_AGENT_USERNAME` and `SUPER_AGENT_PASSWORD` on startup (`src/services/mas/db/agent_account.py`). Whenever that account already exists, MAS enforces the `agent` role even if the account previously had administrator privileges; the `users/update_role` route also refuses role changes for the configured agent username. The installer and `init-env.sh` generate this password when needed; unlike the admin password, the installer does not display it. For a direct update from an older install whose `.env` lacks these values, startup temporarily uses the existing admin password for the agent login so the stack remains available; run the installer to generate and store a distinct agent password. Agent workers use this login only to obtain a MAS token and register themselves. The role has only `agent:create` and `agent:execute`; task claims, results and step events are authenticated with each registered worker's API key.

##### 2. Creating Users

**Via API** (Admin only):

```bash
## Get admin token
TOKEN=$(curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=admin" --data-urlencode "password=$SUPER_USER_PASSWORD" \
  | jq -r '.access_token')

## Create new user
curl -X POST http://localhost:8000/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john_doe",
    "password": "secure_password_123",
    "role": "user"
  }'
```

**Python** (Direct database):

```python
import hashlib
import bcrypt

from db.models import Users
from sqlalchemy.orm import Session

def _bcrypt_input(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")

def create_user(db: Session, username: str, password: str, role: str = "user"):
    user = Users(
        username=username,
        hashed_password=bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt()),
        role=role
    )
    db.add(user)
    db.commit()
    return user

## Usage
create_user(db, "jane_smith", "password123", role="manager")
```

##### 3. Assigning Roles to Users

**Via API** (Admin only):

```bash
## Update user role
curl -X PUT http://localhost:8000/users/{user_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "manager"
  }'
```

**Available roles**: `admin`, `manager`, `user`, `system`

##### 4. Listing Users

```bash
curl -X GET http://localhost:8000/users \
  -H "Authorization: Bearer $TOKEN" | jq '.'

## Response:
## [
##   {
##     "id": 1,
##     "username": "admin",
##     "role": "admin",
##     "created_at": "2025-01-01T00:00:00"
##   },
##   {
##     "id": 2,
##     "username": "john_doe",
##     "role": "user",
##     "created_at": "2025-01-02T10:30:00"
##   }
## ]
```

---

### Adding New Permissions

#### Step 1: Define Permission in `permissions.py`

```python
## src/services/mas/auth/permissions.py

class Permission(str, Enum):
    # ... existing permissions ...
    REPORT_GENERATE = "report:generate"  # New permission
```

#### Step 2: Add to Role Mappings

```python
ROLE_PERMISSION: Dict[Role, Set[Permission]] = {
    Role.ADMIN: {
        # ... existing ...
        Permission.REPORT_GENERATE,  # Add to Admin
    },
    Role.MANAGER: {
        # ... existing ...
        Permission.REPORT_GENERATE,  # Add to Manager
    },
    Role.USER: {
        # ... existing (User cannot generate reports)
    },
}
```

#### Step 3: Protect the API Endpoint

```python
## src/services/mas/reports/routes.py

from auth.permissions import Permission
from fastapi import Depends

@router.post(
    "/reports/generate",
    dependencies=[Depends(PermissionChecker(Permission.REPORT_GENERATE))]
)
async def generate_report(report_type: str, db: Session = Depends(get_db)):
    """Generate a system report (Admin/Manager only)"""
    # Implementation
```

#### Step 4: Test the Permission

```python
## tests/test_report_permissions.py

def test_user_cannot_generate_report(user_token):
    response = client.post(
        "/reports/generate",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"report_type": "summary"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions"

def test_admin_can_generate_report(admin_token):
    response = client.post(
        "/reports/generate",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"report_type": "summary"}
    )
    assert response.status_code == 200
```

---

### API Examples for Admin Operations

#### Example 1: Setup New Organization User

```bash
#!/bin/bash
## Create users for a new team

ADMIN_TOKEN="your-admin-jwt-token"
BASE_URL="http://localhost:8000"

## Create team lead (Manager)
curl -X POST $BASE_URL/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice_team_lead",
    "password": "secure_password_1",
    "role": "manager"
  }'

## Create team member (User)
curl -X POST $BASE_URL/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "bob_developer",
    "password": "secure_password_2",
    "role": "user"
  }'

## Verify users created
curl -X GET $BASE_URL/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.[] | {id, username, role}'
```

#### Example 2: Promote User to Manager

```bash
USER_ID=2
curl -X PUT http://localhost:8000/users/$USER_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "manager"}'
```

#### Example 3: Test Permission with Different Roles

```python
import requests

BASE_URL = "http://localhost:8000"

## Get token for user
user_response = requests.post(
    f"{BASE_URL}/auth/token",
    data={"username": "bob_developer", "password": "secure_password_2"}
)
user_token = user_response.json()["access_token"]

## Try to create a user (should fail - User role cannot create users)
response = requests.post(
    f"{BASE_URL}/users",
    headers={"Authorization": f"Bearer {user_token}"},
    json={"username": "new_user", "password": "pass"}
)

print(response.status_code)  # 403
print(response.json())
## {"detail": "Insufficient permissions"}
```

---

### Troubleshooting RBAC Issues

#### Problem: "Insufficient permissions" error

**Cause**: User's role doesn't have required permission

**Solution**:
```bash
## Check user's current role
curl -X GET http://localhost:8000/users/$USER_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.role'

## Update role if needed
curl -X PUT http://localhost:8000/users/$USER_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "manager"}'
```

#### Problem: Permission check isn't working

**Cause**: Permission not added to role mapping

**Solution**:
1. Check `src/services/mas/auth/permissions.py`
2. Verify permission is in `ROLE_PERMISSION` dict
3. Restart MAS service

#### Problem: New permission doesn't show in Swagger

**Cause**: Swagger cache

**Solution**:
1. Hard refresh: Ctrl+Shift+R or Cmd+Shift+R
2. Clear browser cache
3. Restart MAS service

---

### Best Practices

**Do:**

- Use least privilege (assign the minimal role required).  
- Audit user roles and permissions regularly.  
- Document new permissions when you extend the enum.  
- Test permission checks in unit tests.  
- Change default passwords in production and rotate admin credentials.  

**Do not:**

- Grant the admin role broadly.  
- Share admin credentials.  
- Hardcode permission strings (use the `Permission` enum).  
- Skip permission checks on sensitive endpoints.  
- Ship production with default super-user passwords.  

---

### References

- **Implementation**: `src/services/mas/auth/permissions.py`
- **Route Protection**: `src/services/mas/*/routes.py` (look for `PermissionChecker`)
- **User Management**: `src/services/mas/users/routes.py`
- **Configuration**: `.env` file (SUPER_USER_* variables)

---

## Security Audit Report

**System:** Horus Multi-Agent System  
**Version:** 1.0.0  
**Audit Date:** January 2026  
**Status:** Initial Audit Complete

---

### Executive Summary

This document provides a security assessment of the Horus Multi-Agent System, covering authentication, authorization, data protection, and infrastructure security.

#### Overall Security Posture: **MODERATE**

| Category | Status | Notes |
|----------|--------|-------|
| Authentication | Good | JWT-based, bcrypt passwords |
| Authorization | Good | RBAC implemented |
| Data Protection | Moderate | TLS recommended for production |
| Input Validation | Good | Pydantic schemas |
| Logging & Audit | Good | Structured logging and audit hooks |
| Infrastructure | Moderate | Container hardening recommended |

---

### 1. Authentication

#### 1.1 Implementation Review

**Current implementation**

- JWT (JSON Web Token) authentication  
- bcrypt password hashing (cost factor 12)  
- Token expiration (configurable)  
- OAuth2 password bearer flow  

**Code Location:** `src/services/mas/auth/`

#### 1.2 Strengths

1. **Password Hashing:** SHA-256-prehashing passwords before bcrypt, then verifying with bcrypt. Existing raw-password bcrypt hashes are also verified; after a successful login they are replaced with the current pre-hashed format. Agent API keys follow the same migration on their first successful check.
   ```python
   import bcrypt
   import hashlib

   bcrypt.checkpw(
       hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii"),
       stored_hash,
   )
   ```

2. **JWT Tokens:** Industry-standard token format
   ```python
   jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)
   ```

3. **Token Validation:** Proper signature and expiration checks

#### 1.3 Recommendations

| Priority | Recommendation | Status |
|----------|----------------|--------|
| High | Use HTTPS in production | Pending |
| Medium | Implement refresh tokens | Future |
| Medium | Add rate limiting on /auth/token | Future |
| Low | Add password complexity requirements | Future |

#### 1.4 Known Gaps

- No multi-factor authentication (MFA)
- No account lockout after failed attempts
- No password expiration policy

---

### 2. Authorization (RBAC)

#### 2.1 Implementation Review

**Current implementation**

- Role-based access control (RBAC)  
- Permission-based endpoint protection  
- Roles: admin, manager, user, system, agent

**Code Location:** `src/services/mas/auth/permissions.py`

#### 2.2 Role Matrix

See the [Role-Permission Matrix](#role-permission-matrix) above for the complete current mapping. In particular, the `agent` role has `agent:create` and `agent:execute` only; worker API-key routes are separately authenticated and do not grant role-based access to tasks or administration.

#### 2.3 Strengths

1. **Granular Permissions:** Fine-grained access control
2. **Dependency Injection:** Clean permission checks via FastAPI dependencies
3. **Agent Authentication:** Separate API key authentication for agents

#### 2.4 Recommendations

| Priority | Recommendation | Status |
|----------|----------------|--------|
| Medium | Add permission audit logging | Implemented |
| Medium | Implement row-level security | Future |
| Low | Add role hierarchy | Future |

---

### 3. Data Protection

#### 3.1 Data at Rest

**Current implementation**

- PostgreSQL for structured data  
- ChromaDB for vector embeddings  
- No encryption at rest by default  

**Recommendations:**
- Enable PostgreSQL encryption (pgcrypto)
- Use encrypted Docker volumes in production
- Implement field-level encryption for PII

#### 3.2 Data in Transit

**Current implementation**

- HTTP by default in local development  
- Internal service communication on the Docker bridge network  

**Recommendations:**
- **Critical:** Enable TLS/HTTPS for all external endpoints
- Use TLS for internal service communication
- Implement certificate pinning for agent-MAS communication

#### 3.3 Sensitive Data Handling

| Data Type | Storage | Protection |
|-----------|---------|------------|
| Passwords | PostgreSQL | bcrypt hashed |
| JWT Tokens | Client-side | Signed, expiring |
| API Keys | PostgreSQL | bcrypt hashed; legacy hashes are upgraded after a successful check |
| User Data | PostgreSQL | No encryption |
| Documents | ChromaDB | No encryption |

#### 3.4 Recommendations

| Priority | Recommendation | Status |
|----------|----------------|--------|
| Critical | Enable HTTPS/TLS | Pending |
| High | Hash agent API keys | Done |
| Medium | Encrypt sensitive fields | Future |
| Medium | Implement data retention policy | Future |

---

### 4. Input Validation

#### 4.1 Implementation Review

**Current implementation**

- Pydantic schemas for request validation  
- Strong typing on many endpoints  
- SQL injection risk reduced via SQLAlchemy ORM  

**Code Location:** `src/services/mas/schemas/schemas.py`

#### 4.2 Strengths

1. **Schema Validation:** All inputs validated via Pydantic
2. **ORM Usage:** SQLAlchemy prevents SQL injection
3. **Type Safety:** Strong typing throughout

#### 4.3 Potential Vulnerabilities

| Risk | Mitigation |
|------|------------|
| SQL Injection | ORM parameterized queries |
| XSS | JSON APIs (no HTML rendering from MAS) |
| CSRF | Evaluate for browser clients that use cookies |
| Command Injection | Avoid shelling out with user input |

#### 4.4 Recommendations

| Priority | Recommendation | Status |
|----------|----------------|--------|
| Medium | Add input length limits | Implemented |
| Medium | Sanitize log outputs | Implemented |
| Low | Add request size limits | Future |

---

### 5. Logging & Audit

#### 5.1 Implementation Review

**Current implementation**

- Structured JSON logging  
- Correlation ID tracking  
- Security-oriented logging hooks  
- Database operation logging where enabled  

**Code Location:** `src/services/mas/core/structured_logging.py`

#### 5.2 Logged Events

| Event Type | Logged | Details |
|------------|--------|---------|
| Authentication | Yes | Success/failure, username, IP (where configured) |
| Authorization | Yes | Permission checks |
| Data Access | Yes | CRUD-related audit events |
| System Events | Yes | Startup, shutdown |
| Errors | Yes | Stack traces, context |

#### 5.3 Recommendations

| Priority | Recommendation | Status |
|----------|----------------|--------|
| High | Implement log retention policy | Pending |
| Medium | Add log forwarding (ELK/Loki) | Future |
| Medium | Add alerting on security events | Future |

---

### 6. Infrastructure Security

#### 6.1 Docker Security

**Current implementation**

- Some images run as non-root where configured  
- Default Docker bridge network isolation  
- Default Docker security settings (harden for production)  

**Recommendations:**
```dockerfile
## Add to Dockerfiles
USER nonroot
SECURITY_OPT no-new-privileges:true
READ_ONLY_ROOTFS true
```

#### 6.2 Secrets Management

**Current implementation**

- Secrets supplied via environment variables in development  
- Local `.env` (not committed) for Compose  
- The installer and `src/infra/init-env.sh` generate `JWT_SECRET_KEY` and `REDIS_PASSWORD` (64 hex characters each) and `SUPER_USER_PASSWORD` (24 characters that meet the MAS password policy) into `src/infra/.env`, and the installer also generates `CORPUS_SCAN_TOKEN`; `.env.example` leaves `REDIS_PASSWORD` and `SUPER_USER_PASSWORD` empty. On an install that still has the password earlier releases shipped (`redis_password`) or an empty one, the installer writes a generated one, and the `docker compose up -d` it ends with recreates `redis`, `mas` and `agent` with it.
- `POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD` and `PGADMIN_DEFAULT_PASSWORD` still ship as defaults; their ports answer on 127.0.0.1 only (see 6.3 for the Linux Engine caveat).
- `SUPER_USER_PASSWORD` was `admin` in earlier releases, and no install keeps it now. On an install whose `.env` still has `admin` or an empty value, the installer writes a generated one; on its next start MAS gives it to an account still on `admin` (an account whose password was changed in Horus keeps its own), and the installer shows it once, at the end. Before B-116, the agent also used this admin login; it now uses the separate `SUPER_AGENT_USERNAME` / `SUPER_AGENT_PASSWORD` account described above. The web client forwards every `/api/orchestrator/*` request to MAS, `/auth/token` included; port 3000 answers on 127.0.0.1 only, unless `HORUS_WEB_BIND` opens it to the network (6.3).

**Recommendations:**
- Use Docker secrets for production
- Consider HashiCorp Vault integration
- Rotate secrets regularly

#### 6.3 Network Security

| Service | Host port | Bound to | Reached from the host by |
|---|---|---|---|
| Web client | 3000 | 127.0.0.1, or the address in `HORUS_WEB_BIND` | the browser, the desktop app |
| MAS | 8000 | 127.0.0.1 | the browser's chat WebSocket, the installer's smoke test, scripts |
| Knowledge store | 8080 | 127.0.0.1 | the browser (`NEXT_PUBLIC_KNOWLEDGE_STORE_URL`), the smoke test, scripts |
| Agent | 8001 | 127.0.0.1 | `scripts/perf/prompt-tokens.py` (metrics) |
| vLLM (GPU profiles) | 18000 (`VLLM_HOST_PORT`) | 127.0.0.1 | debugging only; it has no API key |
| PostgreSQL | 5432 (`DB_PORT`) | 127.0.0.1 | MAS run on the host |
| Valkey | 6379 (`REDIS_PORT`) | 127.0.0.1 | MAS run on the host |
| RabbitMQ AMQP / management | 5672 (`RABBITMQ_PORT`) / 15672 | 127.0.0.1 | MAS run on the host / the browser |
| Tempo OTLP | 4317, 4318 | 127.0.0.1 | services run on the host |
| PgAdmin (`dev-tools` profile) | 5433 | 127.0.0.1 | the browser |
| Prometheus, Loki, Tempo queries, llama-server | none | not published | containers on `horus-net` only |

By default no port answers other machines, provided Docker Engine is 28.0 or newer on Linux: on older Engines, hosts on the same network segment can reach ports published to 127.0.0.1 (moby/moby#45610, fixed in 28.0.0). The installer, START-HERE and the desktop app open `http://localhost:3000`.

`HORUS_WEB_BIND=0.0.0.0` in `src/infra/.env`, then `START-HERE --start` (or `docker compose up -d`), opens the web client, and only it, to the network on purpose. What that means:

- The sign-in page is on the network. The web client proxies the whole MAS REST API under `/api/orchestrator`, `/auth/token` included, so any machine that reaches port 3000 can try passwords and, once signed in, use the API with that account's role. Binding 8000 to 127.0.0.1 does not change that.
- Chat and the knowledge store do not work from other machines yet (B-133): the chat socket and the knowledge-store calls go to ports that answer on 127.0.0.1 only, and the knowledge store accepts only the origins `http://localhost:3000` and `http://127.0.0.1:3000`. Other machines can sign in, but chat and the knowledge-store page fail.
- Use 127.0.0.1 or 0.0.0.0. With any other address, `http://localhost:3000` no longer answers on the machine itself.

`tests/ci/test_published_ports.py` fails when a port is published on every interface, except 3000 through `HORUS_WEB_BIND`, and when a launcher opens anything but `http://localhost:3000`.

---

### 7. Dependency Security

#### 7.1 Known Vulnerabilities

Run security audit:
```bash
pip-audit -r src/services/mas/requirements.txt
npm audit --prefix src/services/web-client
```

#### 7.2 Recommendations

| Priority | Recommendation | Status |
|----------|----------------|--------|
| High | Regular dependency updates | Ongoing |
| High | Automated vulnerability scanning | Future |
| Medium | Pin dependency versions | Implemented |

---

### 8. Security Checklist for Production

#### Pre-Deployment

- [ ] Enable HTTPS/TLS on all endpoints
- [ ] Configure secure headers (HSTS, CSP, etc.)
- [ ] Set strong JWT secret (256+ bits)
- [ ] Change default passwords
- [ ] Enable database encryption
- [ ] Configure firewall rules
- [ ] Set up log forwarding
- [ ] Enable rate limiting
- [ ] Configure backup encryption

#### Post-Deployment

- [ ] Regular security scans
- [ ] Penetration testing
- [ ] Log monitoring
- [ ] Incident response plan
- [ ] Regular secret rotation

---

### 9. Compliance Considerations

#### GDPR (if applicable)
- [ ] Data processing agreement
- [ ] Right to erasure implementation
- [ ] Data portability
- [ ] Consent management
- [ ] Privacy policy

#### SOC 2 (if applicable)
- [ ] Access control documentation
- [ ] Audit log retention
- [ ] Incident response procedures
- [ ] Change management process

---

### 10. Security Contacts

| Role | Responsibility |
|------|----------------|
| Security Lead | Overall security posture |
| DevOps | Infrastructure security |
| Backend Lead | Application security |
| Frontend Lead | Client-side security |

---

### Appendix: Security Testing Commands

```bash
## Check for common vulnerabilities
## SQL Injection test (should fail)
curl -X POST http://localhost:8000/auth/token \
  -d "username=admin' OR '1'='1&password=test"

## Check rate limiting
for i in {1..100}; do
  curl -s http://localhost:8000/auth/token \
    -d "username=wrong&password=wrong" &
done

## Check for exposed endpoints
nmap -p 1-65535 localhost

## Check TLS configuration (production)
testssl.sh https://your-domain.com
```

---

**Next Review Date:** April 2026  
**Document Owner:** Security Team

---

## Data Protection Plan - Horus Multi-Agent System

**Document Type:** Data Protection & Privacy Policy  
**Version:** 1.0  
**Last Updated:** January 2026  
**Classification:** Internal

---

### 1. Overview

This document outlines the data protection measures, privacy considerations, and compliance requirements for the Horus Multi-Agent System.

#### 1.1 Scope

This plan covers:
- Types of data collected and processed
- Data storage and retention policies
- Access controls and security measures
- User rights and privacy compliance
- Data handling procedures

#### 1.2 Regulatory Considerations

| Regulation | Applicability |
|------------|---------------|
| GDPR | If processing EU resident data |
| CCPA | If processing California resident data |
| LGPD | If processing Brazilian resident data |
| Industry-specific | Depending on deployment context |

---

### 2. Data Classification

#### 2.1 Data Categories

| Category | Examples | Sensitivity |
|----------|----------|-------------|
| **User Data** | Username, email, hashed password | High |
| **Conversation Data** | Chat messages, queries | Medium-High |
| **Document Data** | Uploaded documents, embeddings | Varies |
| **System Data** | Logs, metrics, traces | Low-Medium |
| **Agent Data** | Agent configs, status | Low |

#### 2.2 Personal Data Inventory

| Data Element | Purpose | Legal Basis | Retention |
|--------------|---------|-------------|-----------|
| Username | Authentication | Contract | Account lifetime |
| Password (hashed) | Authentication | Contract | Account lifetime |
| Email (if collected) | Communication | Consent | Account lifetime |
| IP Address | Security logging | Legitimate interest | 90 days |
| Chat Messages | Service delivery | Contract | User-defined |
| Documents | RAG processing | Contract | User-defined |

---

### 3. Data Collection

#### 3.1 Data Collection Points

| Collection Point | Data Collected | Method |
|------------------|----------------|--------|
| User Registration | Username, password | Direct input |
| Authentication | IP, timestamp | Automatic |
| Chat Interface | Messages, queries | Direct input |
| Document Upload | Documents, metadata | Direct input |
| System Operations | Logs, metrics | Automatic |

#### 3.2 Data Minimization

**Principles Applied:**
- Collect only necessary data for service operation
- No excessive collection of personal information
- Anonymous or pseudonymous processing where possible

**Current Implementation:**
- Minimal user profile (username only required)
- No tracking cookies or analytics by default
- Document content processed, not stored long-term (configurable)

---

### 4. Data Storage

#### 4.1 Storage Locations

| Data Type | Storage System | Location | Encryption |
|-----------|----------------|----------|------------|
| User accounts | PostgreSQL | Container volume | At-rest available |
| Conversations | PostgreSQL | Container volume | At-rest available |
| Documents | ChromaDB | Container volume | Not default |
| Logs | Container stdout | Host filesystem | Not default |
| Metrics | Prometheus | Container volume | Not default |

#### 4.2 Data Retention

| Data Category | Retention Period | Rationale |
|---------------|------------------|-----------|
| User accounts | Until deletion requested | Service continuity |
| Conversations | 90 days default (configurable) | User needs |
| Documents | Until manually deleted | User control |
| System logs | 30 days | Troubleshooting |
| Metrics | 15 days | Performance analysis |
| Security logs | 1 year | Audit requirements |

#### 4.3 Data Deletion

**Automatic Deletion:**
- Logs older than retention period
- Expired session data
- Temporary processing files

**Manual Deletion (User Request):**
- User account deletion
- Conversation deletion
- Document removal

---

### 5. Data Access Controls

#### 5.1 Access Matrix

| Role | User Data | Conversations | Documents | Logs |
|------|-----------|---------------|-----------|------|
| Admin | Full | Full | Full | Full |
| Manager | Limited | Team | Team | Limited |
| User | Own | Own | Own | None |
| System | None | Processing | Processing | Write |
| Agent | None | Processing | Read | Write |

#### 5.2 Technical Controls

| Control | Implementation |
|---------|----------------|
| Authentication | JWT tokens, bcrypt passwords |
| Authorization | RBAC with permission checks |
| Encryption | TLS in transit, at-rest available |
| Audit Logging | All data access logged |
| Network Isolation | Docker network segmentation |

---

### 6. Data Processing

#### 6.1 Processing Activities

| Activity | Purpose | Data Involved | Legal Basis |
|----------|---------|---------------|-------------|
| User authentication | Access control | Credentials | Contract |
| Query processing | Service delivery | Messages | Contract |
| RAG retrieval | Answer generation | Documents | Contract |
| Logging | Security & debugging | System data | Legitimate interest |
| Metrics collection | Performance monitoring | Aggregated data | Legitimate interest |

#### 6.2 Third-Party Processing

| Processor | Purpose | Data Shared | Safeguards |
|-----------|---------|-------------|------------|
| None currently | N/A | N/A | N/A |

*Note: System operates fully on-premise. If cloud services are added, this section must be updated.*

#### 6.3 AI/ML Processing

| Process | Data Used | Output | Privacy Measures |
|---------|-----------|--------|------------------|
| Embedding generation | Document text | Vector embeddings | No PII in vectors |
| Query processing | User query + context | Text response | No data stored in model |
| Agent selection | Query metadata | Agent ID | No PII used |

---

### 7. User Rights

#### 7.1 Rights Implementation

| Right | Implementation | How to Exercise |
|-------|----------------|-----------------|
| **Access** | Export user data via API | Admin panel or API request |
| **Rectification** | Update profile endpoint | Admin panel |
| **Erasure** | Delete account endpoint | Admin panel or request |
| **Portability** | JSON export format | API endpoint |
| **Objection** | Opt-out of processing | Contact admin |

#### 7.2 Request Handling

**Process:**
1. User submits request via admin panel or email
2. Admin verifies identity
3. Request processed within 30 days
4. User notified of completion

**Documentation:**
- Request logged with timestamp
- Action taken recorded
- Confirmation sent to user

---

### 8. Security Measures

#### 8.1 Technical Measures

| Measure | Description |
|---------|-------------|
| **Encryption** | TLS 1.3 for transit, AES-256 for rest |
| **Authentication** | JWT + bcrypt passwords |
| **Authorization** | RBAC with least privilege |
| **Network** | Docker network isolation |
| **Logging** | Comprehensive audit logs |
| **Monitoring** | Real-time alerting |

#### 8.2 Organizational Measures

| Measure | Description |
|---------|-------------|
| **Access Control** | Role-based, need-to-know |
| **Training** | Security awareness |
| **Incident Response** | Documented procedures |
| **Vendor Management** | Due diligence for third parties |

---

### 9. Data Breach Response

#### 9.1 Detection

**Indicators:**
- Unusual access patterns
- Failed authentication spikes
- Data exfiltration attempts
- System integrity alerts

#### 9.2 Response Procedure

1. **Containment** (0-4 hours)
   - Isolate affected systems
   - Revoke compromised credentials
   - Preserve evidence

2. **Assessment** (4-24 hours)
   - Determine scope
   - Identify affected data
   - Assess risk to individuals

3. **Notification** (24-72 hours)
   - Notify supervisory authority (if required)
   - Notify affected individuals (if high risk)
   - Document notification

4. **Remediation** (1-4 weeks)
   - Fix vulnerability
   - Implement additional controls
   - Update procedures

#### 9.3 Notification Templates

**Regulatory Notification:**
- Nature of breach
- Categories and approximate number of data subjects
- Contact details for DPO
- Likely consequences
- Measures taken/proposed

**User Notification:**
- Plain language description
- What data was affected
- What we're doing about it
- What they can do
- Contact information

---

### 10. Compliance Monitoring

#### 10.1 Regular Activities

| Activity | Frequency | Responsible |
|----------|-----------|-------------|
| Access review | Quarterly | Admin |
| Retention compliance | Monthly | Automated |
| Policy review | Annually | Security team |
| Risk assessment | Annually | Security team |
| Training | Annually | All staff |

#### 10.2 Documentation

**Required Records:**
- Processing activities register
- Data protection impact assessments
- Consent records
- Data breach log
- Request handling log

---

### 11. International Data Transfers

#### 11.1 Current Status

**Default Configuration:**
- All data processed locally
- No cross-border transfers

**If Transfers Required:**
- Standard Contractual Clauses (SCCs)
- Adequacy decisions
- Binding Corporate Rules

---

### 12. Privacy by Design

#### 12.1 Principles Applied

| Principle | Implementation |
|-----------|----------------|
| **Proactive** | Security built into architecture |
| **Default** | Minimal data collection by default |
| **Embedded** | Privacy in system design |
| **End-to-end** | Protection throughout lifecycle |
| **Visibility** | Transparent operations |
| **User-centric** | User control over data |

#### 12.2 Technical Implementation

```python
## Example: Data minimization in logging
log_entry = {
    "timestamp": datetime.utcnow(),
    "level": "INFO",
    "message": "User logged in",
    "user_id": hash(user_id),  # Pseudonymized
    # NOT included: username, email, IP
}
```

---

### 13. Data Protection Impact Assessment (DPIA)

#### 13.1 When Required

- New processing activities
- Large-scale profiling
- Systematic monitoring
- Sensitive data processing

#### 13.2 Assessment Process

1. Describe processing
2. Assess necessity and proportionality
3. Identify and assess risks
4. Identify measures to mitigate risks
5. Document and review

---

### 14. Contact Information

| Role | Contact |
|------|---------|
| Data Protection Officer | [To be designated] |
| Security Team | [Email] |
| Privacy Inquiries | [Email] |

---

### Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Jan 2026 | Development Team | Initial version |

---

### Appendix: Data Flow Diagram

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    User     │────▶│  Web Client │────▶│     MAS     │
│             │     │  (Browser)  │     │   (API)     │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    │                          │                          │
                    ▼                          ▼                          ▼
             ┌─────────────┐           ┌─────────────┐           ┌─────────────┐
             │ PostgreSQL  │           │  RabbitMQ   │           │    Agent    │
             │ (User Data) │           │  (Tasks)    │           │ (Processing)│
             └─────────────┘           └─────────────┘           └──────┬──────┘
                                                                       │
                                                                       ▼
                                                               ┌─────────────┐
                                                               │  Knowledge  │
                                                               │   Store     │
                                                               └─────────────┘
```

---

## Telemetry Posture - Horus Multi-Agent System

**Document Type:** Telemetry & Data Collection Disclosure  
**Version:** 1.0  
**Last Updated:** January 2026  
**Classification:** Internal

---

### 1. Overview

This document describes the telemetry, metrics, and logging data collected by the Horus Multi-Agent System, how it is used, and how users can control this data collection.

#### 1.1 Purpose

Telemetry is collected to:
- Monitor system health and performance
- Debug issues and improve reliability
- Understand usage patterns for optimization
- Ensure security and detect anomalies

#### 1.2 Principles

- **Transparency:** All data collection documented
- **Minimization:** Collect only what's necessary
- **Control:** Users can opt-out where applicable
- **Security:** Telemetry data protected like other data

---

### 2. Telemetry Categories

#### 2.1 Categories Overview

| Category | Default State | Opt-Out Available | Contains PII |
|----------|---------------|-------------------|--------------|
| System Metrics | Enabled | No | No |
| Application Logs | Enabled | Configurable | Minimal |
| Distributed Traces | Enabled | Configurable | No |
| User Analytics | Disabled | N/A | N/A |
| Error Reports | Enabled | Configurable | Minimal |

---

### 3. System Metrics

#### 3.1 Infrastructure Metrics

**What is collected:**
- CPU and memory usage per container
- Network I/O statistics
- Disk usage and I/O
- Container health status

**How it's collected:**
- Docker stats API
- Prometheus node exporter (if deployed)

**Retention:** 15 days

**Example:**
```
container_cpu_usage_seconds_total{container="mas"} 123.45
container_memory_usage_bytes{container="mas"} 536870912
```

#### 3.2 Application Metrics

**MAS Metrics:**
| Metric | Description | Labels |
|--------|-------------|--------|
| `mas_http_requests_total` | Total HTTP requests | method, endpoint, status |
| `mas_http_request_duration_seconds` | Request latency | method, endpoint |
| `mas_agents_total` | Active agents | status |
| `mas_tasks_total` | Task count | status |
| `mas_errors_total` | Error count | type, component |
| `mas_websocket_connections` | Active WebSocket connections | - |

**Agent Metrics:**
| Metric | Description | Labels |
|--------|-------------|--------|
| `agent_tasks_processed_total` | Tasks processed | status |
| `agent_rag_query_duration_seconds` | RAG query time | - |
| `agent_model_inference_seconds` | Model inference time | - |

**Knowledge Store Metrics:**
| Metric | Description | Labels |
|--------|-------------|--------|
| `ks_queries_total` | Total queries | collection |
| `ks_query_duration_seconds` | Query latency | collection |
| `ks_documents_total` | Document count | collection |

#### 3.3 What is NOT Collected

- Do not include User identities in metrics
- Do not include Message content
- Do not include Document content
- Do not include IP addresses
- Do not include Query text

---

### 4. Application Logs

#### 4.1 Log Content

**Information Logged:**
- Timestamp (ISO 8601)
- Log level (DEBUG, INFO, WARN, ERROR)
- Component/service name
- Correlation ID (for request tracing)
- Event description
- Non-PII context data

**Example Log Entry:**
```json
{
  "timestamp": "2026-01-12T10:30:00Z",
  "level": "INFO",
  "logger": "mas.tasks",
  "message": "Task created",
  "correlation_id": "abc-123-def",
  "task_id": "task_456",
  "agent_id": "agent_789"
}
```

#### 4.2 PII Handling in Logs

**Sanitized:**
- Usernames → User ID only
- Email addresses → Not logged
- IP addresses → Hashed or omitted
- Passwords → Never logged
- Query content → Not logged in production

**Configuration:**
```python
## core/config.py
LOG_SANITIZE_PII = True  # Enable PII sanitization
LOG_LEVEL = "INFO"       # Production default
```

#### 4.3 Log Levels

| Level | Contents | When Used |
|-------|----------|-----------|
| ERROR | Exception details, stack traces | System errors |
| WARN | Potential issues | Degraded operations |
| INFO | Key events | Normal operations |
| DEBUG | Detailed flow | Development only |

#### 4.4 Log Retention

| Environment | Retention | Storage |
|-------------|-----------|---------|
| Production | 30 days | Centralized logging |
| Development | 7 days | Container stdout |

---

### 5. Distributed Traces

#### 5.1 Trace Content

**What is included:**
- Trace ID (unique identifier)
- Span ID (operation identifier)
- Operation name
- Duration
- Service name
- HTTP method and status code
- Non-sensitive attributes

**What is NOT included:**
- Do not include Request/response bodies
- Do not include User identifiers
- Do not include Authentication tokens
- Do not include Document content

#### 5.2 Trace Example

```
Trace: abc123
├── Span: MAS receive request (50ms)
│   ├── method: POST
│   ├── path: /tasks/new_task/
│   └── status: 200
├── Span: Task publish (10ms)
│   └── queue: task_queue
└── Span: Agent process (3000ms)
    └── status: completed
```

#### 5.3 Sampling

**Default Configuration:**
- 100% sampling in development
- 10% sampling in production (adjustable)

```python
## core/tracing.py
SAMPLING_RATE = 0.1  # 10% of traces
```

---

### 6. Error Reporting

#### 6.1 Error Report Content

**Included:**
- Error type and message
- Stack trace (code paths only)
- Correlation ID
- Timestamp
- Service/component name
- Environment (dev/staging/prod)

**Not Included:**
- Do not include User data
- Do not include Request payloads
- Do not include Sensitive configuration

#### 6.2 Example Error Report

```json
{
  "error_type": "DatabaseConnectionError",
  "message": "Connection refused",
  "stack_trace": "File db/database.py, line 45...",
  "correlation_id": "xyz-789",
  "timestamp": "2026-01-12T10:35:00Z",
  "service": "mas",
  "environment": "production"
}
```

---

### 7. User Analytics

#### 7.1 Current State

**User analytics is DISABLED by default.**

No user behavior tracking is performed unless explicitly enabled.

#### 7.2 If Enabled (Future)

If user analytics were enabled, it would collect:
- Feature usage (anonymized)
- Session duration (aggregated)
- Error frequency (no user correlation)

**Would NOT collect:**
- Do not include Individual user tracking
- Do not include Query content
- Do not include Browsing history
- Do not include Third-party tracking

---

### 8. Data Flow

#### 8.1 Telemetry Data Flow

```
┌─────────────┐
│   Service   │
│  (MAS/Agent)│
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│   Metrics   │────▶│ Prometheus  │────▶ Retention: 15 days
└─────────────┘     └─────────────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│    Logs     │────▶│   stdout    │────▶ Retention: 30 days
└─────────────┘     └─────────────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│   Traces    │────▶│    Tempo    │────▶ Retention: 7 days
└─────────────┘     └─────────────┘
```

#### 8.2 Storage Locations

| Data Type | Storage | Encryption | Access Control |
|-----------|---------|------------|----------------|
| Metrics | Prometheus | No | Network isolation |
| Logs | Container/Host | Optional | File permissions |
| Traces | Tempo | No | Network isolation |

---

### 9. Configuration

#### 9.1 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | INFO | Logging verbosity |
| `LOG_FORMAT` | json | Log format (json/text) |
| `OTEL_TRACES_SAMPLER_ARG` | 0.1 | Trace sampling rate |
| `METRICS_ENABLED` | true | Enable/disable metrics |
| `TRACING_ENABLED` | true | Enable/disable tracing |

#### 9.2 Disable Telemetry

**Disable Metrics:**
```yaml
## docker-compose.yml
services:
  mas:
    environment:
      - METRICS_ENABLED=false
```

**Disable Tracing:**
```yaml
services:
  mas:
    environment:
      - TRACING_ENABLED=false
```

**Reduce Logging:**
```yaml
services:
  mas:
    environment:
      - LOG_LEVEL=WARN
```

---

### 10. Third-Party Services

#### 10.1 Current State

**No telemetry is sent to external services by default.**

All telemetry is stored and processed locally within the deployment.

#### 10.2 If External Services Used

If cloud observability services are configured (e.g., Datadog, New Relic):

| Requirement | Implementation |
|-------------|----------------|
| Data Processing Agreement | Required |
| PII Filtering | Must be enabled |
| Region Selection | EU preferred for GDPR |
| Encryption | TLS required |

---

### 11. User Controls

#### 11.1 Available Controls

| Control | How to Apply |
|---------|--------------|
| Disable metrics collection | Set `METRICS_ENABLED=false` |
| Disable tracing | Set `TRACING_ENABLED=false` |
| Reduce log verbosity | Set `LOG_LEVEL=WARN` |
| Request data deletion | Contact administrator |

#### 11.2 Operator Controls

| Control | How to Apply |
|---------|--------------|
| Adjust retention periods | Update Prometheus/Tempo config |
| Configure sampling | Set `OTEL_TRACES_SAMPLER_ARG` |
| Filter sensitive data | Configure log sanitization |
| Export telemetry | Use Prometheus/Tempo export APIs |

---

### 12. Compliance Alignment

#### 12.1 GDPR Alignment

| Requirement | Status |
|-------------|--------|
| Lawful basis for processing | Legitimate interest (system operation) |
| Purpose limitation | Documented purposes only |
| Data minimization | No PII in telemetry |
| Storage limitation | Defined retention periods |
| Transparency | This document |

#### 12.2 Security Measures

| Measure | Implementation |
|---------|----------------|
| Access control | Network isolation |
| Encryption | TLS available |
| Audit logging | Enabled |
| Data integrity | Prometheus TSDB |

---

### 13. Change Log

| Date | Change |
|------|--------|
| Jan 2026 | Initial telemetry posture documented |

---

### 14. Contact

For questions about telemetry:
- **Technical:** Development team
- **Privacy:** Data protection officer (if designated)
- **Compliance:** Legal/compliance team

---

### Appendix: Metric Reference

#### MAS Service Metrics

```prometheus
## HTTP metrics
mas_http_requests_total{method="POST", endpoint="/tasks/new_task/", status_code="200"} 1234
mas_http_request_duration_seconds_bucket{method="GET", endpoint="/agents/", le="0.1"} 500

## Agent metrics
mas_agents_total{status="active"} 3
mas_agent_heartbeats_total{agent_id="agent_001", status="success"} 150

## Task metrics
mas_tasks_total{status="completed"} 500
mas_task_queue_depth{status="pending"} 5

## Error metrics
mas_errors_total{type="ValidationError", component="tasks"} 12
```

#### Knowledge Store Metrics

```prometheus
## Query metrics
ks_queries_total{collection="default"} 1000
ks_query_duration_seconds_bucket{collection="default", le="0.5"} 950

## Document metrics
ks_documents_total{collection="default"} 250
ks_embedding_generation_seconds_bucket{le="1.0"} 240
```
