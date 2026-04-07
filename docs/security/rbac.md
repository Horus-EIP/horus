# Role-Based Access Control (RBAC)

The Horus system implements a comprehensive Role-Based Access Control (RBAC) mechanism to manage user permissions and secure resources at the API level.

## Overview

RBAC provides:
- **Roles**: Groups of users with similar permissions (Admin, Manager, User, System)
- **Permissions**: Granular rights to perform specific actions
- **Role-Permission Mapping**: Defines which permissions each role has
- **API Protection**: Endpoints enforce permission checks before executing actions

---

## Roles

The system defines four standard roles:

### 1. **Admin** (`admin`)
- **Purpose**: Full system access and administration
- **Use Case**: System administrators, project leads
- **Permissions**: All permissions (create/read/update/delete for users, agents, tasks)
- **Responsibilities**:
  - User account management
  - System configuration
  - Agent registration and lifecycle management
  - Task approval workflows
  - Analytics and reporting

### 2. **Manager** (`manager`)
- **Purpose**: Operational management without administrative privileges
- **Use Case**: Team leads, operations managers
- **Permissions**: Task/agent operations and analytics (no user management)
- **Can do**:
  - Create, read, and approve tasks
  - View and execute agents
  - View analytics and export data
  - Cannot: Create/edit/delete users, create/update agents

### 3. **User** (`user`)
- **Purpose**: Standard application users
- **Use Case**: Task creators, analysts
- **Permissions**: Basic task creation and agent execution
- **Can do**:
  - Create and read tasks
  - Execute agents
  - Cannot: Manage users, approve tasks, create agents

### 4. **System** (`system`)
- **Purpose**: Internal system processes
- **Use Case**: Automated workflows, scheduled tasks
- **Permissions**: Limited to task execution and reading
- **Can do**:
  - Read tasks and agents
  - Execute tasks and agents
- **Cannot**: Create/modify/delete resources, access management functions

---

## Permissions

Permissions are granular rights that control access to specific API operations.

### User Management
| Permission | Description |
|-----------|-------------|
| `user:create` | Create new user accounts |
| `user:read` | View user details and profile |
| `user:update` | Modify user information |
| `user:delete` | Delete user accounts |

### Task Management
| Permission | Description |
|-----------|-------------|
| `task:create` | Create new tasks for agents |
| `task:read` | View task details and history |
| `task:execute` | Run/execute tasks |
| `task:delete` | Delete tasks |
| `task:approve` | Approve tasks in workflows |

### Agent Management
| Permission | Description |
|-----------|-------------|
| `agent:create` | Register new agents |
| `agent:read` | View agent details and capabilities |
| `agent:update` | Modify agent configuration |
| `agent:delete` | Unregister agents |
| `agent:execute` | Execute/invoke agents |

### System & Analytics
| Permission | Description |
|-----------|-------------|
| `analytics:view` | View system analytics and metrics |
| `data:export` | Export data from the system |
| `system:config` | Modify system configuration |

---

## Role-Permission Matrix

Complete permission mapping for all roles:

| Permission | Admin | Manager | User | System |
|:-----------|:-----:|:-------:|:----:|:------:|
| **User management** | | | | |
| `user:create` | Yes | No | No | No |
| `user:read` | Yes | Yes | Yes | No |
| `user:update` | Yes | No | No | No |
| `user:delete` | Yes | No | No | No |
| **Task management** | | | | |
| `task:create` | Yes | Yes | Yes | No |
| `task:read` | Yes | No | Yes | Yes |
| `task:execute` | Yes | Yes | No | Yes |
| `task:delete` | Yes | Yes | Yes | No |
| `task:approve` | Yes | Yes | No | No |
| **Agent management** | | | | |
| `agent:create` | Yes | No | No | No |
| `agent:read` | Yes | Yes | Yes | Yes |
| `agent:update` | Yes | No | No | No |
| `agent:delete` | Yes | No | No | No |
| `agent:execute` | Yes | Yes | Yes | Yes |
| **System and analytics** | | | | |
| `analytics:view` | Yes | Yes | Yes | No |
| `data:export` | Yes | Yes | No | No |
| `system:config` | Yes | No | No | No |

Source of truth: `src/services/mas/auth/permissions.py` (`ROLE_PERMISSION`). The **manager** role does not include `task:read`, which affects WebSocket chat access (see WebSocket API documentation).

---

## Implementation Details

### Architecture

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

### How Permission Checks Work

1. **Request arrives** at an API endpoint
2. **User authentication** extracts JWT token and validates signature
3. **User role** is retrieved from database
4. **Permission required** for endpoint is defined in route
5. **`PermissionChecker` dependency** verifies: `role has permission?`
6. **Access granted/denied** based on check result

### API Route Protection

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

## Administrator Operations

### Setting Up RBAC

#### 1. Initial Setup

On first application startup:

```bash
# The system automatically creates:
# - Postgres database
# - Admin user (from environment variables)
# - Role assignments
# - Permission mappings

# Environment variables set in .env:
SUPER_USER_USERNAME=admin
SUPER_USER_PASSWORD=admin
```

#### 2. Creating Users

**Via API** (Admin only):

```bash
# Get admin token
TOKEN=$(curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin" \
  | jq -r '.access_token')

# Create new user
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
from db.models import Users
from auth.auth_tool_functions import bcrypt_context
from sqlalchemy.orm import Session

def create_user(db: Session, username: str, password: str, role: str = "user"):
    user = Users(
        username=username,
        hashed_password=bcrypt_context.hash(password),
        role=role
    )
    db.add(user)
    db.commit()
    return user

# Usage
create_user(db, "jane_smith", "password123", role="manager")
```

#### 3. Assigning Roles to Users

**Via API** (Admin only):

```bash
# Update user role
curl -X PUT http://localhost:8000/users/{user_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "manager"
  }'
```

**Available roles**: `admin`, `manager`, `user`, `system`

#### 4. Listing Users

```bash
curl -X GET http://localhost:8000/users \
  -H "Authorization: Bearer $TOKEN" | jq '.'

# Response:
# [
#   {
#     "id": 1,
#     "username": "admin",
#     "role": "admin",
#     "created_at": "2025-01-01T00:00:00"
#   },
#   {
#     "id": 2,
#     "username": "john_doe",
#     "role": "user",
#     "created_at": "2025-01-02T10:30:00"
#   }
# ]
```

---

## Adding New Permissions

### Step 1: Define Permission in `permissions.py`

```python
# src/services/mas/auth/permissions.py

class Permission(str, Enum):
    # ... existing permissions ...
    REPORT_GENERATE = "report:generate"  # New permission
```

### Step 2: Add to Role Mappings

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

### Step 3: Protect the API Endpoint

```python
# src/services/mas/reports/routes.py

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

### Step 4: Test the Permission

```python
# tests/test_report_permissions.py

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

## API Examples for Admin Operations

### Example 1: Setup New Organization User

```bash
#!/bin/bash
# Create users for a new team

ADMIN_TOKEN="your-admin-jwt-token"
BASE_URL="http://localhost:8000"

# Create team lead (Manager)
curl -X POST $BASE_URL/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice_team_lead",
    "password": "secure_password_1",
    "role": "manager"
  }'

# Create team member (User)
curl -X POST $BASE_URL/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "bob_developer",
    "password": "secure_password_2",
    "role": "user"
  }'

# Verify users created
curl -X GET $BASE_URL/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.[] | {id, username, role}'
```

### Example 2: Promote User to Manager

```bash
USER_ID=2
curl -X PUT http://localhost:8000/users/$USER_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "manager"}'
```

### Example 3: Test Permission with Different Roles

```python
import requests

BASE_URL = "http://localhost:8000"

# Get token for user
user_response = requests.post(
    f"{BASE_URL}/auth/token",
    data={"username": "bob_developer", "password": "secure_password_2"}
)
user_token = user_response.json()["access_token"]

# Try to create a user (should fail - User role cannot create users)
response = requests.post(
    f"{BASE_URL}/users",
    headers={"Authorization": f"Bearer {user_token}"},
    json={"username": "new_user", "password": "pass"}
)

print(response.status_code)  # 403
print(response.json())
# {"detail": "Insufficient permissions"}
```

---

## Troubleshooting RBAC Issues

### Problem: "Insufficient permissions" error

**Cause**: User's role doesn't have required permission

**Solution**:
```bash
# Check user's current role
curl -X GET http://localhost:8000/users/$USER_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.role'

# Update role if needed
curl -X PUT http://localhost:8000/users/$USER_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "manager"}'
```

### Problem: Permission check isn't working

**Cause**: Permission not added to role mapping

**Solution**:
1. Check `src/services/mas/auth/permissions.py`
2. Verify permission is in `ROLE_PERMISSION` dict
3. Restart MAS service

### Problem: New permission doesn't show in Swagger

**Cause**: Swagger cache

**Solution**:
1. Hard refresh: Ctrl+Shift+R or Cmd+Shift+R
2. Clear browser cache
3. Restart MAS service

---

## Best Practices

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

## References

- **Implementation**: `src/services/mas/auth/permissions.py`
- **Route Protection**: `src/services/mas/*/routes.py` (look for `PermissionChecker`)
- **User Management**: `src/services/mas/users/routes.py`
- **Configuration**: `.env` file (SUPER_USER_* variables)
