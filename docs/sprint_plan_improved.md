# Horus Project — Enhanced Sprint & Deliverables Plan (Nov 2025 – Jan 2026)

## Executive Summary

This plan outlines a 4-sprint roadmap to transform the Horus MVP into a production-ready system with persistent storage, RBAC, observability, and comprehensive testing. The project is organized into three core components: **MAS (Multi-Agent System Orchestrator)**, **Agent (AI Runtime)**, and **Web (Frontend Dashboard)**.

---

## Current Implementation Snapshot

### ✅ What Works (MVP Baseline)

**MAS Component:**
- Multi-agent orchestrator online with FastAPI exposing agent, chat, task, and conversation APIs
- RabbitMQ-backed task dispatch and heartbeat monitoring
- In-memory agent registry and conversation history
- WebSocket support for real-time chat updates
- **Files:** `src/services/mas/core/app.py`, `src/services/mas/tasks/routes.py`, `src/services/mas/agents/registry_tool_functions.py`

**Agent Component:**
- FastAPI agent server registers with MAS and consumes RabbitMQ jobs
- Full RAG pipeline with KnowledgeRetrievalAgent and DecisionMakingAgent
- Heartbeat mechanism (30s interval) and task processing
- **Files:** `src/services/agent/app/agent_server/server.py`, `src/services/agent/app/ai_agents/rag_pipeline.py`

**Web Component:**
- Next.js dashboard with working chat interface
- WebSocket integration for real-time agent responses
- Conversation history display
- **Files:** `src/services/web-client/app/pages/chat.tsx`

**Infrastructure:**
- Docker Compose orchestration (RabbitMQ, MAS, Agent, Knowledge Store, Web Client)
- Live-reload mounts for development
- **File:** `src/infra/docker-compose.yml`

### ⚠️ MVP Constraints & Technical Debt

**MAS Component:**
- ❌ Volatile in-memory registries (`agent_registry: dict`, `conversation_history: dict`) — data lost on restart
- ❌ Module-level RabbitMQ connection (no pooling, health checks, or graceful shutdown)
- ❌ Hardcoded RabbitMQ host (`localhost` fallback)
- ❌ No database layer (PostgreSQL not in docker-compose.yml)

**Agent Component:**
- ❌ Mock knowledge store (`mock_knowledge_store`) instead of HTTP client to knowledge-store service
- ❌ Hardcoded model selection (`t5-small`) without GPU acceleration configuration
- ❌ No connection to production knowledge-store API

**Web Component:**
- ❌ Hardcoded MAS endpoints (`http://localhost:8000`) — no environment configuration
- ❌ No authentication/authorization flows
- ❌ No admin UI for user/role management

**Infrastructure:**
- ❌ Missing PostgreSQL service in docker-compose.yml
- ❌ Missing Redis service (needed for WebSocket session management)
- ❌ No secrets management (credentials in environment variables)
- ❌ No migration system for database schema

---

## Planning Assumptions

1. **Sprint Cadence:** Two-week sprints starting November 11, 2025
2. **Issue Tracking:** All work tracked via GitHub issues with backlog IDs
3. **Database:** PostgreSQL becomes system of record for MAS (agents, conversations, tasks, users, roles)
4. **Caching:** Redis used for WebSocket connection metadata and session management
5. **Testing:** Minimum 70% code coverage for new persistence and API layers
6. **Demo Target:** Half-demo by January 5, 2026 must demonstrate:
   - Durable persistence (survives restarts)
   - RBAC-protected endpoints
   - Real knowledge-store integration
   - Baseline observability (logs, metrics)
7. **Component Ownership:**
   - **MAS:** Orchestration, persistence, RBAC, API contracts
   - **Agent:** RAG pipeline, knowledge-store integration, GPU acceleration
   - **Web:** UI/UX, auth flows, admin panels, configuration

---

## Sprint Schedule

---

## Sprint 1 (Nov 11 – Nov 24, 2025) — Stabilize Core Services & Persistence

**Sprint Goal:** Replace in-memory stores with PostgreSQL persistence, ensuring data survives restarts and enabling multi-worker deployments.

### Current State Assessment

**Already Implemented (MAS Component):**
- ✅ **SQLAlchemy models exist** (`db/models.py`): Users, Conversations, Messages, CriticalLogs models are defined
- ✅ **Database connection setup** (`db/database.py`): SessionLocal, get_db() dependency, PostgreSQL connection
- ✅ **Authentication system** (`auth/`): JWT authentication, bcrypt password hashing, OAuth2 bearer tokens, `get_current_user()` dependency
- ✅ **Configuration management** (`core/config.py`): Centralized config with environment variables
- ✅ **Logging infrastructure** (`core/logger.py`, `core/hybrid_logging.py`): Structured logging, security event logging
- ✅ **Redis setup** (`db/redis.py`): Redis connection and configuration
- ✅ **Conversations/Messages persistence**: Already using database (not in-memory) via `conversation_tool_functions.py`
- ✅ **User management** (`users/routes.py`): User CRUD operations
- ✅ **WebSocket authentication**: Token extraction from WebSocket connections
- ✅ **LLM integration**: MAS uses Qwen3-4B-Instruct for agent routing (`core/llm_setup.py`)

**Still In-Memory (MAS Component):**
- ❌ **Agent registry** (`agents/registry_tool_functions.py`): Still uses `agent_registry: dict` - needs database migration
- ❌ **No Agent model in database**: Agents not persisted
- ❌ **No Task model in database**: Tasks not tracked in database
- ❌ **No Alembic migrations**: Models exist but no migration system set up

**Infrastructure:**
- ❌ **No PostgreSQL/Redis in docker-compose.yml**: Services not defined (but code expects them)

**Agent Component:**
- ✅ Basic agent configuration file exists (`src/services/agent/app/config/settings.py`) with `ORCHESTRATOR_URL`
- ❌ Agent still uses `mock_knowledge_store` instead of real HTTP client

**Web Component:**
- ✅ Web client uses `process.env.NEXT_PUBLIC_KNOWLEDGE_STORE_URL` in `knowledge-store.tsx` (partial env var usage)
- ✅ Basic TypeScript interfaces exist (`Message`, `Document`) in component files
- ✅ WebSocket implementation exists in `chat.tsx` (basic, no reconnection logic)
- ❌ Web client has hardcoded URLs in `chat.tsx` (`http://localhost:8000`)
- ❌ No API client abstraction layer in web client
- ❌ No error boundaries, toast notifications, or notification context
- ❌ No WebSocket hook or reconnection logic
- ❌ No centralized configuration file for web client
- ❌ No comprehensive TypeScript API type definitions

### MAS Component Tasks

#### 1.1 Database Infrastructure Setup
- **Estimated Hours:** 4 hours
- **Task:** Add PostgreSQL and Redis services to docker-compose.yml
- **Details:**
  - Add `postgres` service (PostgreSQL 15+) with health checks
  - Add `redis` service (Redis 7+) for WebSocket session management
  - Configure persistent volumes for both services
  - Add connection environment variables to MAS service
- **Files:** `src/infra/docker-compose.yml`
- **Acceptance Criteria:**
  - `docker compose up` brings up PostgreSQL and Redis
  - MAS can connect to both services on startup
  - Data persists across container restarts

#### 1.2 SQLAlchemy Models & Alembic Setup
- **Estimated Hours:** 8 hours
- **Task:** Add missing models (Agent, Task) and set up Alembic migrations
- **Details:**
  - **Note:** Models already exist for Users, Conversations, Messages, CriticalLogs in `db/models.py`
  - Add `Agent` model to `db/models.py` (id, name, description, skills, status, last_heartbeat, created_at)
  - Add `Task` and `TaskResult` models to `db/models.py` (id, conversation_id, agent_id, status, query, parameters, result, created_at)
  - Set up Alembic for migrations (`alembic init alembic`)
  - Configure Alembic to use existing models from `db.models`
  - Create initial migration for all existing models
  - Add indexes on frequently queried fields (agent_id, conversation_id, status, last_heartbeat)
- **Files:** `src/services/mas/db/models.py` (enhance), `src/services/mas/alembic/` (new)
- **Acceptance Criteria:**
  - `alembic upgrade head` creates all tables including Agent and Task
  - Agent and Task models match existing in-memory data structures
  - Foreign key relationships properly defined
  - Migrations can be applied and rolled back

#### 1.3 Replace In-Memory Agent Registry
- **Estimated Hours:** 6 hours
- **Task:** Migrate `registry_tool_functions.py` to use SQLAlchemy
- **Details:**
  - Replace `agent_registry: dict` with database queries
  - Update `create_agent()`, `get_agent_details()`, `update_alive_agent_status()`, `get_available_agents()`
  - Add database session management (dependency injection)
  - Update heartbeat controller to use database
- **Files:** `src/services/mas/agents/registry_tool_functions.py`, `src/services/mas/agents/controller.py`
- **Acceptance Criteria:**
  - Agent registration persists across MAS restarts
  - Heartbeat updates work with database
  - All existing API endpoints continue to work

#### 1.4 Verify Conversation History Persistence
- **Estimated Hours:** 4 hours
- **Task:** Verify and enhance conversation persistence (already using database)
- **Details:**
  - **Note:** `conversation_tool_functions.py` already uses database (SessionLocal, Messages model)
  - Verify all conversation operations use database correctly
  - Ensure `create_conversation()` creates database records (currently done in routes)
  - Verify `get_history()` and `add_messages()` work correctly with database
  - Add error handling and transaction management if missing
  - Ensure conversation_id types are consistent (int vs str)
- **Files:** `src/services/mas/conversations/conversation_tool_functions.py`, `src/services/mas/conversations/routes.py`
- **Acceptance Criteria:**
  - Conversation history persists across restarts (verified)
  - Message ordering preserved (timestamp/index)
  - Web client can retrieve full history
  - All conversation operations use database transactions properly

#### 1.5 RabbitMQ Connection Management
- **Estimated Hours:** 6 hours
- **Task:** Refactor RabbitMQ connection into injectable dependency
- **Details:**
  - Create `RabbitMQManager` class with connection pooling
  - Add health check endpoint for RabbitMQ connectivity
  - Support graceful shutdown (close connections on app shutdown)
  - Externalize host/credentials via environment variables
  - Add retry logic with exponential backoff
- **Files:** `src/services/mas/core/rabbitmq_tool.py` (refactor), `src/services/mas/core/rabbitmq_manager.py` (new)
- **Acceptance Criteria:**
  - Connection failures handled gracefully
  - Health check endpoint returns RabbitMQ status
  - No import-time connections (lazy initialization)

#### 1.6 Database Session Management Verification
- **Estimated Hours:** 3 hours
- **Task:** Verify and enhance database session management (already implemented)
- **Details:**
  - **Note:** `get_db()` dependency already exists in `db/database.py`
  - Verify all routes use `Depends(get_db)` for database access
  - Review connection pooling configuration (add if missing)
  - Ensure proper transaction rollback on errors (verify existing implementation)
  - Add connection pool monitoring/logging if needed
- **Files:** `src/services/mas/db/database.py` (verify/enhance), review all route files
- **Acceptance Criteria:**
  - All routes use dependency injection for DB access (verified)
  - Sessions properly closed after request (verified)
  - Connection pool limits configured
  - Error handling and rollback working correctly

### Agent Component Tasks

#### 1.7 Replace Mock Knowledge Store
- **Estimated Hours:** 8 hours
- **Task:** Integrate agent with real knowledge-store HTTP API
- **Details:**
  - **Note:** `mock_knowledge_store` currently exists and returns dummy sales data
  - Create `KnowledgeStoreClient` class using `httpx` for async HTTP calls
  - Replace `mock_knowledge_store` usage in `KnowledgeRetrievalAgent` initialization
  - Add configuration for knowledge-store URL (environment variable via task 1.8)
  - Implement timeout and retry logic
  - Handle API errors gracefully (fallback to empty results or error message)
  - Remove or deprecate `mock_store.py` after migration
- **Files:** `src/services/agent/app/ai_agents/mock_store.py` (remove after migration), `src/services/agent/app/ai_agents/knowledge_store_client.py` (new), `src/services/agent/app/agent_server/server.py` (update), `src/services/agent/app/ai_agents/knowledge_retrieval_agent.py` (update)
- **Acceptance Criteria:**
  - Agent queries real knowledge-store API
  - Timeout/error handling works correctly
  - RAG pipeline uses real document retrieval
  - Mock store no longer used in production code

#### 1.8 Configuration Management
- **Estimated Hours:** 4 hours
- **Task:** Enhance agent configuration with Pydantic Settings and additional variables
- **Details:**
  - **Note:** Basic `config/settings.py` exists with `ORCHESTRATOR_URL` only
  - Convert to Pydantic Settings for validation and type safety
  - Externalize additional variables: `RABBITMQ_HOST`, `KNOWLEDGE_STORE_URL`, model selection
  - Add validation on startup with helpful error messages
  - Document all configuration options
- **Files:** `src/services/agent/app/config/settings.py` (enhance existing)
- **Acceptance Criteria:**
  - All hardcoded values moved to config
  - Startup fails fast with invalid configuration
  - Configuration documented in README

### Web Component Tasks

#### 1.9 Environment-Based Configuration Setup
- **Estimated Hours:** 4 hours
- **Task:** Centralize and standardize configuration infrastructure
- **Details:**
  - **Note:** `knowledge-store.tsx` already uses `process.env.NEXT_PUBLIC_KNOWLEDGE_STORE_URL`, but `chat.tsx` has hardcoded URLs
  - Create `app/config.ts` with centralized environment variable definitions
  - Define TypeScript types for configuration
  - Add `NEXT_PUBLIC_MAS_URL` and `NEXT_PUBLIC_WS_URL` environment variables
  - Replace hardcoded `http://localhost:8000` in `chat.tsx` with config values
  - Add `.env.local.example` template file
  - Validate configuration on app initialization
- **Files:** `src/services/web-client/app/config.ts` (new), `src/services/web-client/app/pages/chat.tsx` (update), `src/services/web-client/.env.local.example` (new)
- **Acceptance Criteria:**
  - Configuration centralized in one file
  - All hardcoded URLs removed from components
  - Environment variables documented
  - Type-safe configuration access

#### 1.10 API Client Abstraction Layer
- **Estimated Hours:** 6 hours
- **Task:** Create reusable API client for MAS communication
- **Details:**
  - Create `app/lib/api-client.ts` with typed API methods
  - Define TypeScript interfaces for API request/response types
  - Implement error handling and retry logic
  - Support for both REST and WebSocket connections
  - Replace direct `fetch` calls in components
- **Files:** `src/services/web-client/app/lib/api-client.ts` (new), `src/services/web-client/app/lib/types.ts` (new)
- **Acceptance Criteria:**
  - All API calls go through client abstraction
  - Type-safe API methods
  - Consistent error handling

#### 1.11 WebSocket Reconnection & Error Handling
- **Estimated Hours:** 8 hours
- **Task:** Improve WebSocket reliability and user experience
- **Details:**
  - **Note:** Basic WebSocket implementation exists in `chat.tsx` with error handlers (console.error only)
  - Extract WebSocket logic into reusable `useWebSocket` hook
  - Implement automatic reconnection logic with exponential backoff
  - Add connection status indicator in UI
  - Replace console.error with user-friendly error messages
  - Queue messages when disconnected and send on reconnect
  - Add connection state management (connecting, connected, disconnected, error)
- **Files:** `src/services/web-client/app/pages/chat.tsx` (refactor), `src/services/web-client/app/hooks/useWebSocket.ts` (new)
- **Acceptance Criteria:**
  - WebSocket reconnects automatically on failure
  - Users see connection status
  - Messages not lost during disconnection
  - Error handling is user-friendly (not just console logs)

#### 1.12 Enhanced Conversation History Display
- **Estimated Hours:** 6 hours
- **Task:** Improve conversation history UI to work with persisted data
- **Details:**
  - Update history fetching to handle pagination (if needed)
  - Add loading states for history retrieval
  - Display timestamps in user-friendly format
  - Add scroll-to-bottom functionality for new messages
  - Handle empty state when no history exists
  - Show message status indicators (sending, sent, error)
- **Files:** `src/services/web-client/app/pages/chat.tsx`, `src/services/web-client/app/components/MessageList.tsx` (new, optional)
- **Acceptance Criteria:**
  - History loads correctly from persisted backend
  - Smooth scrolling and loading states
  - Better visual feedback for message states

#### 1.13 Error Handling & User Feedback
- **Estimated Hours:** 8 hours
- **Task:** Add comprehensive error handling and user notifications
- **Details:**
  - Create error boundary component for React error catching
  - Add toast/notification system for user feedback (success, error, warning)
  - Handle API errors gracefully (network errors, 4xx, 5xx)
  - Show user-friendly error messages instead of technical errors
  - Add retry mechanisms for failed requests
- **Files:** `src/services/web-client/app/components/ErrorBoundary.tsx` (new), `src/services/web-client/app/components/Toast.tsx` (new), `src/services/web-client/app/contexts/NotificationContext.tsx` (new)
- **Acceptance Criteria:**
  - Users see helpful error messages
  - Errors don't crash the app
  - Success/error feedback visible

#### 1.14 Loading States & UX Improvements
- **Estimated Hours:** 6 hours
- **Task:** Enhance loading states and overall user experience
- **Details:**
  - Add skeleton loaders for conversation history
  - Improve loading indicator for agent responses
  - Add disabled states for buttons during operations
  - Prevent duplicate message submissions
  - Add input validation and character limits
  - Improve responsive design for mobile devices
- **Files:** `src/services/web-client/app/pages/chat.tsx`, `src/services/web-client/app/components/LoadingSpinner.tsx` (new)
- **Acceptance Criteria:**
  - Clear loading indicators throughout UI
  - Better mobile experience
  - Input validation prevents errors

#### 1.15 TypeScript Type Definitions
- **Estimated Hours:** 6 hours
- **Task:** Create comprehensive TypeScript types for all API contracts
- **Details:**
  - **Note:** Basic interfaces exist (`Message`, `Document`) but are defined inline in components
  - Extract and centralize all types into shared type definition files
  - Define types for Agent, Conversation, Message, Task models matching backend schemas
  - Create types for API request/response payloads
  - Add types for WebSocket message formats
  - Ensure type safety across all API interactions
  - Document types with JSDoc comments
- **Files:** `src/services/web-client/app/lib/types.ts` (new), `src/services/web-client/app/lib/api-types.ts` (new), `src/services/web-client/app/pages/chat.tsx` (update to use shared types), `src/services/web-client/app/pages/knowledge-store.tsx` (update to use shared types)
- **Acceptance Criteria:**
  - All API interactions are type-safe
  - Type definitions match backend schemas
  - No `any` types in API code
  - Types are reusable across components

### Testing & Documentation

#### 1.16 Unit Tests for Persistence Layer
- **Estimated Hours:** 8 hours
- **Task:** Write tests for database models and tool functions
- **Details:**
  - Test agent CRUD operations
  - Test conversation and message persistence
  - Test heartbeat updates
  - Use pytest with test database (SQLite in-memory or separate PostgreSQL)
  - Mock RabbitMQ for integration tests
- **Files:** `src/services/mas/tests/test_agents_persistence.py` (new), `src/services/mas/tests/test_conversations_persistence.py` (new)
- **Acceptance Criteria:**
  - 70%+ code coverage for persistence layer
  - Tests run in CI pipeline
  - All tests pass with new database layer

#### 1.17 API Integration Tests
- **Estimated Hours:** 8 hours
- **Task:** Test agent registration, heartbeat, and task dispatch end-to-end
- **Details:**
  - Test agent registration → heartbeat → task assignment flow
  - Test conversation creation → message history → WebSocket delivery
  - Use testcontainers or Docker Compose for integration tests
- **Files:** `src/services/mas/tests/test_integration.py` (enhance)
- **Acceptance Criteria:**
  - Full agent lifecycle tested
  - Task dispatch and result handling tested
  - Tests run in CI

#### 1.18 Frontend Component Tests
- **Estimated Hours:** 6 hours
- **Task:** Add unit tests for Web component
- **Details:**
  - Test API client methods with mocked responses
  - Test WebSocket hook reconnection logic
  - Test error boundary component
  - Test notification/toast system
  - Use React Testing Library and Jest
- **Files:** `src/services/web-client/app/__tests__/` (new directory)
- **Acceptance Criteria:**
  - Critical components have test coverage
  - Tests run in CI pipeline
  - Mock API responses properly

#### 1.19 Architecture Documentation
- **Estimated Hours:** 4 hours
- **Task:** Update architecture docs with persistence topology
- **Details:**
  - Document database schema (ER diagram)
  - Document connection lifecycle (PostgreSQL, Redis, RabbitMQ)
  - Document configuration contract (environment variables)
  - Add sequence diagrams for agent registration and task flow
- **Files:** `docs/architecture.md` (new or enhance)
- **Acceptance Criteria:**
  - New developers can understand data flow
  - Configuration requirements documented
  - Database schema documented

### Sprint 1 Time Summary

**Total Estimated Hours:** 115 hours

**Breakdown by Component:**
- MAS Component Tasks (1.1-1.6): 31 hours
- Agent Component Tasks (1.7-1.8): 12 hours
- Web Component Tasks (1.9-1.15): 48 hours
- Testing & Documentation (1.16-1.19): 24 hours

**Note:** Estimates assume a single developer working full-time. For a 2-week sprint (80 working hours), consider parallel work or task prioritization.

### Sprint 1 Deliverables

**MAS Component:**
- ✅ PostgreSQL and Redis services in docker-compose.yml
- ✅ SQLAlchemy models with Alembic migrations
- ✅ Agent registry and conversation history persisted in database
- ✅ RabbitMQ connection management refactored
- ✅ Database session dependency injection

**Agent Component:**
- ✅ Real knowledge-store HTTP client integrated
- ✅ Configuration externalized

**Web Component:**
- ✅ Environment-based configuration infrastructure
- ✅ API client abstraction layer with type safety
- ✅ WebSocket reconnection and error handling
- ✅ Enhanced conversation history display
- ✅ Comprehensive error handling and user feedback
- ✅ Improved loading states and UX
- ✅ Complete TypeScript type definitions

**Testing & Docs:**
- ✅ Unit tests for persistence (70%+ coverage)
- ✅ Integration tests for agent lifecycle
- ✅ Frontend component tests
- ✅ Updated architecture documentation

**Issues:** #1, #3, #15, #17, #25, #36, #39, #71, #76

---

## Sprint 2 (Nov 25 – Dec 8, 2025) — Access Control, Configurability & Admin UX

**Sprint Goal:** Enhance RBAC enforcement, add authentication flows to Web, and harden service configuration.

### Current State Assessment (Sprint 2)

**Already Implemented (MAS Component):**
- ✅ **JWT Authentication** (`auth/auth_tool_functions.py`): JWT token generation, validation, `get_current_user()` dependency
- ✅ **User Model** (`db/models.py`): Users table with username, hashed_password, role (basic roles: user/admin)
- ✅ **Password Hashing**: bcrypt implemented
- ✅ **Auth Routes** (`auth/routes.py`): Login and token endpoints exist
- ✅ **User Management** (`users/routes.py`): User CRUD operations exist
- ✅ **Basic Role System**: Users have `role` field (user/admin)

**Still Needed:**
- ❌ **Granular Permissions**: No permission-based access control (only role-based)
- ❌ **RBAC Enforcement**: Not all routes protected, no permission checks
- ❌ **Admin UI**: No web interface for user/role management
- ❌ **Web Auth**: Frontend doesn't have login/register pages

### MAS Component Tasks

#### 2.1 Enhance RBAC with Permissions (Optional)
- **Estimated Hours:** 6 hours
- **Task:** Add granular permission system if needed, or enhance existing role-based system
- **Details:**
  - **Note:** Basic role system exists (user/admin in Users.role field)
  - Evaluate if granular permissions needed or if role-based is sufficient
  - If needed: Add Permission, RolePermission, UserRole models
  - If keeping role-based: Enhance role checks and document permission mapping
  - Add permission constants/helpers for consistent checks
- **Files:** `src/services/mas/db/models.py` (enhance if needed), `src/services/mas/auth/permissions.py` (new)
- **Acceptance Criteria:**
  - Permission system documented and consistent
  - Role-based access clearly defined
  - Easy to add new permissions/roles if needed

#### 2.2 RBAC Enforcement on All Routes
- **Estimated Hours:** 8 hours
- **Task:** Ensure all routes are protected and enforce role-based access
- **Details:**
  - **Note:** Some routes already use `user_dependency = Depends(get_current_user)`
  - Review all routes and ensure authentication required
  - Add role checks for admin-only operations
  - Protect agent routes (require `agents:read`/`agents:write` equivalent)
  - Protect conversation routes (owner-only or admin)
  - Protect task routes (authenticated users)
  - Document which routes require which roles
- **Files:** `src/services/mas/agents/routes.py`, `src/services/mas/conversations/routes.py`, `src/services/mas/tasks/routes.py`, `src/services/mas/auth/routes.py`
- **Acceptance Criteria:**
  - All routes require authentication (except public endpoints)
  - Admin routes restricted to admin role
  - Users can only access their own conversations
  - Unauthorized requests return 401/403

#### 2.3 WebSocket Authentication Enhancement
- **Estimated Hours:** 4 hours
- **Task:** Ensure WebSocket connections are properly authenticated
- **Details:**
  - **Note:** `_extract_token_from_ws()` exists in `chat/chat_tool_functions.py`
  - Verify WebSocket routes validate tokens before accepting connections
  - Add user context to WebSocket connection metadata
  - Ensure users can only connect to their own conversations
  - Add connection logging for security
- **Files:** `src/services/mas/chat/routes.py`, `src/services/mas/chat/chat_tool_functions.py`
- **Acceptance Criteria:**
  - Unauthenticated WebSocket connections rejected
  - User context available in WebSocket handlers
  - Users can only access their own conversations via WebSocket

#### 2.4 Database Seeding & Initial Setup
- **Estimated Hours:** 4 hours
- **Task:** Create seed scripts for initial data and admin user
- **Details:**
  - **Note:** Configuration exists for SUPER_USER_USERNAME and SUPER_USER_PASSWORD
  - Create Alembic data migration or separate seed script
  - Seed default admin user from environment variables
  - Document how to run migrations and seeds
  - Ensure seed script is idempotent (can run multiple times)
- **Files:** `src/services/mas/db/init_setup.py` (verify/enhance), `src/services/mas/alembic/versions/seed_data.py` (new if needed)
- **Acceptance Criteria:**
  - Admin user created automatically on first run
  - Seed script idempotent (can run multiple times)
  - Documentation for setup process

#### 2.5 Agent Authentication
- **Estimated Hours:** 6 hours
- **Task:** Add authentication to agent-MAS communication
- **Details:**
  - Agent registers with API key or service account token
  - Include token in registration and heartbeat requests
  - MAS validates agent credentials
  - Store agent credentials securely
- **Files:** `src/services/agent/app/agent_server/server.py`, `src/services/mas/agents/routes.py`
- **Acceptance Criteria:**
  - Unauthenticated agents rejected
  - Agent credentials stored securely
  - Registration and heartbeat include authentication

### Web Component Tasks

#### 2.6 Environment-Based Configuration
- **Estimated Hours:** 2 hours
- **Task:** Replace hardcoded URLs with environment variables
- **Details:**
  - Create `.env.local` template
  - Use `NEXT_PUBLIC_MAS_URL` for API endpoints
  - Use `NEXT_PUBLIC_WS_URL` for WebSocket connections
  - Add configuration validation on app startup
- **Files:** `src/services/web-client/app/pages/chat.tsx`, `src/services/web-client/app/config.ts` (new)
- **Acceptance Criteria:**
  - No hardcoded URLs in frontend code
  - Configuration documented

#### 2.7 Authentication UI
- **Estimated Hours:** 10 hours
- **Task:** Add login/register pages and auth context
- **Details:**
  - Create `/login` and `/register` pages
  - Implement React context for auth state
  - Store JWT token in localStorage or httpOnly cookie
  - Add protected route wrapper
  - Redirect unauthenticated users to login
- **Files:** `src/services/web-client/app/pages/login.tsx` (new), `src/services/web-client/app/pages/register.tsx` (new), `src/services/web-client/app/contexts/AuthContext.tsx` (new)
- **Acceptance Criteria:**
  - Users can login and register
  - Protected pages require authentication
  - Token refresh handled

#### 2.8 Admin UI for User/Role Management
- **Estimated Hours:** 12 hours
- **Task:** Create admin dashboard for managing users and roles
- **Details:**
  - Admin-only route `/admin/users` and `/admin/roles`
  - List users, create/edit users, assign roles
  - List roles, create/edit roles, assign permissions
  - Use MAS admin APIs
- **Files:** `src/services/web-client/app/pages/admin/` (new directory)
- **Acceptance Criteria:**
  - Admin can manage users and roles
  - Non-admin users cannot access admin routes
  - UI matches design system

### Infrastructure & Configuration

#### 2.9 Centralized Configuration Schema
- **Estimated Hours:** 6 hours
- **Task:** Create 12-factor configuration management
- **Details:**
  - Document all environment variables in `.env.example` files
  - Add validation schemas (Pydantic Settings for Python, Zod for TypeScript)
  - Add secrets management documentation (use Docker secrets or external vault)
  - Create configuration matrix (dev, staging, prod)
- **Files:** `src/services/*/.env.example` (new files), `docs/configuration.md` (new)
- **Acceptance Criteria:**
  - All services have `.env.example`
  - Configuration validated on startup
  - Secrets management documented

#### 2.10 Docker Compose Environment Variables
- **Estimated Hours:** 3 hours
- **Task:** Externalize all secrets and configuration
- **Details:**
  - Move hardcoded values to `.env` file (gitignored)
  - Add `.env.example` with placeholder values
  - Document required environment variables
- **Files:** `src/infra/docker-compose.yml`, `src/infra/.env.example` (new)
- **Acceptance Criteria:**
  - No secrets in docker-compose.yml
  - `.env.example` documents all variables

### Documentation

#### 2.11 Developer Onboarding Guide
- **Estimated Hours:** 4 hours
- **Task:** Create step-by-step setup instructions
- **Details:**
  - Prerequisites (Docker, Git, etc.)
  - Clone repository → set up `.env` → run migrations → start services
  - Troubleshooting common issues
  - How to run tests
- **Files:** `docs/onboarding.md` (new)
- **Acceptance Criteria:**
  - New developer can set up environment in < 30 minutes
  - All steps verified

#### 2.12 RBAC Setup Documentation
- **Estimated Hours:** 4 hours
- **Task:** Document RBAC model and setup
- **Details:**
  - Explain roles and permissions
  - How to create users and assign roles
  - How to add new permissions
  - API examples for admin operations
- **Files:** `docs/rbac.md` (new)
- **Acceptance Criteria:**
  - Administrators can set up RBAC
  - Permission model clear

### Sprint 2 Time Summary

**Total Estimated Hours:** 69 hours

**Breakdown by Component:**
- MAS Component Tasks (2.1-2.5): 28 hours
- Web Component Tasks (2.6-2.8): 24 hours
- Infrastructure & Configuration (2.9-2.10): 9 hours
- Documentation (2.11-2.12): 8 hours

**Note:** Estimates assume a single developer working full-time. For a 2-week sprint (80 working hours), this sprint is more manageable than Sprint 1.

### Sprint 2 Deliverables

**MAS Component:**
- ✅ RBAC enforcement on all routes (enhanced)
- ✅ WebSocket authentication verified/enhanced
- ✅ Database seeding for admin user
- ✅ Agent authentication implemented

**Agent Component:**
- ✅ Agent authentication with MAS

**Web Component:**
- ✅ Environment-based configuration
- ✅ Login/register pages
- ✅ Admin UI for user/role management

**Infrastructure:**
- ✅ Centralized configuration schema
- ✅ Secrets externalized

**Documentation:**
- ✅ Developer onboarding guide
- ✅ RBAC setup documentation

**Issues:** #4, #15, #17, #25, #27, #41, #76

---

## Sprint 3 (Dec 9 – Dec 22, 2025) — Observability, Performance & Intelligent Retrieval

**Sprint Goal:** Add comprehensive observability, validate GPU acceleration, benchmark performance, and complete knowledge-store integration.

### MAS Component Tasks

#### 3.1 Structured Logging
- **Task:** Implement structured logging with correlation IDs
- **Details:**
  - Use `structlog` or `loguru` for structured logs
  - Add correlation ID middleware (X-Request-ID)
  - Log all API requests/responses, agent events, task dispatches
  - Output JSON format for log aggregation
- **Files:** `src/services/mas/core/logging.py` (new), `src/services/mas/core/middleware.py` (new)
- **Acceptance Criteria:**
  - All logs structured (JSON)
  - Correlation IDs trace requests across services
  - Log levels configurable

#### 3.2 Metrics Collection
- **Task:** Add Prometheus metrics endpoint
- **Details:**
  - Metrics: request count, latency, agent count, task queue depth, error rates
  - Use `prometheus-fastapi-instrumentator`
  - Expose `/metrics` endpoint
- **Files:** `src/services/mas/core/metrics.py` (new)
- **Acceptance Criteria:**
  - Prometheus can scrape metrics
  - Key business metrics exposed

#### 3.3 Distributed Tracing
- **Task:** Implement OpenTelemetry tracing
- **Details:**
  - Instrument FastAPI with OpenTelemetry
  - Trace agent registration, task dispatch, RabbitMQ operations
  - Export traces to Jaeger or similar
  - Add trace context propagation to RabbitMQ messages
- **Files:** `src/services/mas/core/tracing.py` (new)
- **Acceptance Criteria:**
  - Traces visible in Jaeger UI
  - End-to-end request tracing works

#### 3.4 Task Cancellation & Timeouts
- **Task:** Add graceful task cancellation
- **Details:**
  - Add `PATCH /tasks/{task_id}/cancel` endpoint
  - Store task status in database (pending, running, completed, cancelled, failed)
  - Send cancellation signal via RabbitMQ
  - Agent handles cancellation gracefully
  - Add task timeout configuration
- **Files:** `src/services/mas/tasks/routes.py`, `src/services/mas/models/` (add TaskStatus enum)
- **Acceptance Criteria:**
  - Tasks can be cancelled
  - Timeout handling works
  - Status tracked in database

### Agent Component Tasks

#### 3.5 GPU Acceleration Configuration
- **Task:** Validate and document GPU acceleration
- **Details:**
  - Add configuration for model device (CPU/GPU/CUDA)
  - Detect GPU availability on startup
  - Fallback to CPU if GPU unavailable
  - Document hardware requirements
  - Add performance comparison (CPU vs GPU)
- **Files:** `src/services/agent/app/config/settings.py`, `src/services/agent/app/ai_agents/decision_making_agent.py`
- **Acceptance Criteria:**
  - GPU acceleration works when available
  - CPU fallback works
  - Performance documented

#### 3.6 Knowledge Store Integration Completion
- **Task:** Remove all mock code and integrate fully
- **Details:**
  - Ensure all RAG queries use real knowledge-store API
  - Handle Chroma collection lifecycle (create if not exists)
  - Add cleanup jobs for old embeddings (optional)
  - Remove `mock_store.py` and all references
- **Files:** `src/services/agent/app/ai_agents/` (cleanup), `src/services/agent/app/agent_server/server.py`
- **Acceptance Criteria:**
  - No mock code remaining
  - All queries hit real knowledge store
  - Error handling robust

#### 3.7 Agent Observability
- **Task:** Add logging and metrics to agent
- **Details:**
  - Structured logging for task processing, RAG queries, model inference
  - Metrics: task processing time, RAG latency, model inference time, error rates
  - Correlation IDs propagated from MAS
- **Files:** `src/services/agent/app/agent_server/server.py`, `src/services/agent/app/core/logging.py` (new)
- **Acceptance Criteria:**
  - Agent logs structured
  - Metrics exposed (if FastAPI, use same pattern as MAS)

### Knowledge Store Component Tasks

#### 3.8 Knowledge Store Observability
- **Task:** Add logging and metrics to knowledge store
- **Details:**
  - Structured logging for document ingest, queries, deletions
  - Metrics: query latency, document count, embedding generation time
  - Health check endpoint
- **Files:** `src/services/knowledge-store/app/main.py`, `src/services/knowledge-store/app/core/logging.py` (new)
- **Acceptance Criteria:**
  - Knowledge store observable
  - Health checks work

### Performance & Benchmarking

#### 3.9 Performance Benchmark Suite
- **Task:** Create benchmark scripts and baseline metrics
- **Details:**
  - Benchmark RabbitMQ throughput (messages/second)
  - Benchmark RAG latency (query → response time)
  - Benchmark agent registration and heartbeat overhead
  - Benchmark database query performance
  - Document baseline metrics and target improvements
- **Files:** `scripts/benchmarks/` (new directory)
- **Acceptance Criteria:**
  - Benchmark scripts runnable
  - Baseline metrics documented
  - Performance regression tests (optional)

#### 3.10 Load Testing
- **Task:** Stress test system under load
- **Details:**
  - Use Locust or k6 for load testing
  - Test scenarios: concurrent conversations, agent registration bursts, task queue backpressure
  - Document breaking points and bottlenecks
- **Files:** `scripts/load_tests/` (new directory)
- **Acceptance Criteria:**
  - Load test scenarios defined
  - System behavior under load documented

### Infrastructure

#### 3.11 Observability Stack
- **Task:** Add observability services to docker-compose.yml
- **Details:**
  - Add Prometheus service (scrape MAS, Agent, Knowledge Store)
  - Add Grafana service (dashboards for metrics)
  - Add Jaeger service (trace collection)
  - Configure service discovery for scraping
- **Files:** `src/infra/docker-compose.yml`, `src/infra/grafana/dashboards/` (new)
- **Acceptance Criteria:**
  - Observability stack runs with `docker compose up`
  - Dashboards show key metrics
  - Traces visible in Jaeger

### Documentation

#### 3.12 Observability Documentation
- **Task:** Document observability setup and usage
- **Details:**
  - How to access Grafana dashboards
  - How to query Prometheus
  - How to search traces in Jaeger
  - Key metrics to monitor
  - Alerting recommendations
- **Files:** `docs/observability.md` (new)
- **Acceptance Criteria:**
  - Operators can use observability tools
  - Key metrics explained

### Sprint 3 Deliverables

**MAS Component:**
- ✅ Structured logging with correlation IDs
- ✅ Prometheus metrics endpoint
- ✅ OpenTelemetry tracing
- ✅ Task cancellation and timeouts

**Agent Component:**
- ✅ GPU acceleration validated and documented
- ✅ Full knowledge-store integration (no mocks)
- ✅ Agent observability (logs, metrics)

**Knowledge Store Component:**
- ✅ Observability added

**Performance:**
- ✅ Benchmark suite and baseline metrics
- ✅ Load testing results

**Infrastructure:**
- ✅ Observability stack (Prometheus, Grafana, Jaeger)

**Documentation:**
- ✅ Observability documentation

**Issues:** #10, #11, #38, #42, #53, #54, #55

---

## Sprint 4 (Dec 23, 2025 – Jan 5, 2026) — Half-Demo Packaging & Review

**Sprint Goal:** Package complete system for half-demo, run end-to-end tests, and prepare compliance documentation.

### Demo Preparation

#### 4.1 Demo Script & Data Seeding
- **Task:** Create reproducible demo with sample data
- **Details:**
  - Seed script: admin user, sample agents, sample documents in knowledge store
  - Demo script: step-by-step walkthrough (document ingest → query → agent response)
  - Ensure all services start in correct order
  - Document demo prerequisites
- **Files:** `scripts/demo/seed_demo_data.sh` (new), `scripts/demo/demo_script.md` (new)
- **Acceptance Criteria:**
  - Demo runs end-to-end without manual intervention
  - Sample data realistic

#### 4.2 Demo Documentation
- **Task:** Create demo playbook and troubleshooting guide
- **Details:**
  - Step-by-step demo script
  - Expected outputs at each step
  - Troubleshooting common issues
  - How to reset demo environment
- **Files:** `docs/demo_playbook.md` (new), `docs/troubleshooting.md` (new)
- **Acceptance Criteria:**
  - Anyone can run demo following playbook
  - Troubleshooting guide covers common issues

### Testing & Quality Assurance

#### 4.3 End-to-End Resilience Tests
- **Task:** Test system resilience to failures
- **Details:**
  - Test MAS restart (agents re-register, conversations persist)
  - Test RabbitMQ restart (tasks queued, no data loss)
  - Test PostgreSQL restart (data recovery)
  - Test agent failure (tasks reassigned)
  - Test knowledge store unavailability (graceful degradation)
- **Files:** `scripts/resilience_tests/` (new directory)
- **Acceptance Criteria:**
  - All resilience scenarios tested
  - Failures handled gracefully
  - Data integrity maintained

#### 4.4 Security Audit
- **Task:** Review security posture
- **Details:**
  - Review authentication/authorization implementation
  - Check for SQL injection, XSS vulnerabilities
  - Review secrets management
  - Document security assumptions and known gaps
- **Files:** `docs/security_audit.md` (new)
- **Acceptance Criteria:**
  - Security review completed
  - Known issues documented

### Documentation

#### 4.5 Compliance Documentation Drafts
- **Task:** Prepare compliance documentation
- **Details:**
  - Architecture fiche (system overview, data flows, security measures)
  - Data protection plan (GDPR considerations, data retention)
  - Telemetry posture (what data collected, how used)
  - Draft documents for Phase 3 review
- **Files:** `docs/compliance/architecture_fiche.md` (new), `docs/compliance/data_protection.md` (new), `docs/compliance/telemetry.md` (new)
- **Acceptance Criteria:**
  - Compliance documents drafted
  - Ready for stakeholder review

#### 4.6 Backlog Prioritization
- **Task:** Create prioritized backlog for May full-demo
- **Details:**
  - List remaining Phase 2 and Phase 3 items
  - Prioritize by business value and dependencies
  - Estimate effort for each item
  - Identify critical path to full-demo
- **Files:** `docs/backlog_may_demo.md` (new)
- **Acceptance Criteria:**
  - Backlog prioritized
  - Critical path identified

### Demo Recording

#### 4.7 Demo Walkthrough Recording
- **Task:** Record or document demo walkthrough
- **Details:**
  - Record video of full demo (optional)
  - Create screenshot walkthrough (alternative)
  - Document all features demonstrated
- **Files:** `docs/demo_recording/` (new directory)
- **Acceptance Criteria:**
  - Demo walkthrough available for stakeholders

### Sprint 4 Deliverables

**Demo:**
- ✅ Reproducible demo with seeded data
- ✅ Demo playbook and troubleshooting guide
- ✅ Demo recording/walkthrough

**Testing:**
- ✅ End-to-end resilience tests
- ✅ Security audit completed

**Documentation:**
- ✅ Compliance documentation drafts
- ✅ Prioritized backlog for May demo

**Issues:** #1-#4, #6, #15-#17, #25-#27, #36, #41, #45-#51, #66-#73, #70, #71, #76, #77

---

## Monthly Deliverables Summary

### November 2025
- ✅ **MAS persistence layer** live on PostgreSQL with migrations
- ✅ **Agent registry and conversations** survive restarts
- ✅ **RabbitMQ connection management** refactored
- ✅ **Agent knowledge-store integration** (real HTTP client)
- ✅ **Web component foundation** (API client, error handling, WebSocket improvements, type safety)
- ✅ **Automated test suite** (70%+ coverage) with CI wiring
- ✅ **Architecture documentation** updated

### December 2025
- ✅ **RBAC-protected MAS APIs** with JWT authentication
- ✅ **Admin workflows** in Next.js dashboard
- ✅ **Observability toolchain** (logs, metrics, traces) with dashboards
- ✅ **Performance benchmarks** and load test results
- ✅ **GPU acceleration** validated with CPU fallback
- ✅ **Developer onboarding** and RBAC documentation

### January 2026 (by Jan 5)
- ✅ **Packaged half-demo** with reproducible environment
- ✅ **Demo playbook** and troubleshooting guide
- ✅ **Compliance documentation** drafts (architecture, data protection, telemetry)
- ✅ **Prioritized backlog** for May full-demo
- ✅ **End-to-end resilience tests** completed
- ✅ **Security audit** completed

---

## Risk Management

### High-Risk Items

1. **Database Migration Complexity**
   - **Risk:** Migrating in-memory stores to PostgreSQL may reveal data model issues
   - **Mitigation:** Start with simple models, iterate. Use Alembic rollback capability.

2. **RBAC Implementation Scope**
   - **Risk:** RBAC may take longer than expected
   - **Mitigation:** Start with basic roles (admin/user), add granular permissions later.

3. **Observability Overhead**
   - **Risk:** Adding observability may impact performance
   - **Mitigation:** Use async logging, sample traces, monitor overhead.

4. **Agent-Knowledge Store Integration**
   - **Risk:** Real integration may reveal API mismatches
   - **Mitigation:** Define API contract early, use integration tests.

### Dependencies

- **Sprint 1 → Sprint 2:** RBAC requires database (Sprint 1)
- **Sprint 2 → Sprint 3:** Observability easier with authenticated users (Sprint 2)
- **Sprint 3 → Sprint 4:** Demo requires all previous work

### Rollback Plans

- Each sprint delivers working software
- Database migrations are reversible (Alembic)
- Feature flags can disable new features if needed
- Keep MVP branch for fallback

---

## Success Criteria

### Technical Success
- ✅ All data persists across restarts
- ✅ RBAC enforced on all endpoints
- ✅ Observability provides actionable insights
- ✅ System handles expected load (baseline metrics met)
- ✅ 70%+ test coverage for new code

### Business Success
- ✅ Half-demo runs smoothly for stakeholders
- ✅ Documentation enables new developers to contribute
- ✅ System ready for Phase 3 enhancements
- ✅ Clear path to May full-demo

---

## Component Ownership Matrix

| Task Area | Primary Owner | Supporting |
|-----------|--------------|------------|
| Database & Persistence | MAS | - |
| RBAC & Auth | MAS | Web (UI) |
| Observability | MAS, Agent, Knowledge Store | - |
| Agent RAG Pipeline | Agent | Knowledge Store (API) |
| Web UI/UX | Web | MAS (APIs) |
| Infrastructure | All | - |
| Testing | All | - |
| Documentation | All | - |

---

## Appendix: File Structure After Sprints

```
src/
├── infra/
│   ├── docker-compose.yml          # + PostgreSQL, Redis, Prometheus, Grafana, Jaeger
│   └── .env.example                # NEW: Configuration template
│
├── services/
│   ├── mas/
│   │   ├── models/                 # NEW: SQLAlchemy models
│   │   │   ├── agent_models.py
│   │   │   ├── conversation_models.py
│   │   │   └── user_models.py
│   │   ├── alembic/                # NEW: Database migrations
│   │   │   ├── versions/
│   │   │   └── env.py
│   │   ├── auth/                   # NEW: Authentication
│   │   │   ├── routes.py
│   │   │   └── dependencies.py
│   │   ├── core/
│   │   │   ├── database.py         # NEW: DB session management
│   │   │   ├── rabbitmq_manager.py # NEW: Refactored RabbitMQ
│   │   │   ├── logging.py          # NEW: Structured logging
│   │   │   ├── metrics.py          # NEW: Prometheus metrics
│   │   │   ├── tracing.py          # NEW: OpenTelemetry
│   │   │   └── dependencies.py     # NEW: Auth dependencies
│   │   ├── agents/
│   │   │   └── registry_tool_functions.py  # UPDATED: Uses DB
│   │   ├── conversations/
│   │   │   └── conversation_tool_functions.py  # UPDATED: Uses DB
│   │   └── scripts/
│   │       └── seed.py             # NEW: Data seeding
│   │
│   ├── agent/
│   │   └── app/
│   │       ├── ai_agents/
│   │       │   ├── knowledge_store_client.py  # NEW: Real HTTP client
│   │       │   └── mock_store.py   # REMOVED
│   │       ├── config/
│   │       │   └── settings.py     # UPDATED: Full configuration
│   │       └── core/
│   │           └── logging.py      # NEW: Structured logging
│   │
│   ├── knowledge-store/
│   │   └── app/
│   │       └── core/
│   │           └── logging.py      # NEW: Structured logging
│   │
│   └── web-client/
│       └── app/
│           ├── pages/
│           │   ├── chat.tsx        # UPDATED: Enhanced with new features
│           │   ├── login.tsx       # NEW (Sprint 2)
│           │   ├── register.tsx    # NEW (Sprint 2)
│           │   └── admin/          # NEW (Sprint 2): Admin UI
│           ├── components/
│           │   ├── ErrorBoundary.tsx      # NEW (Sprint 1)
│           │   ├── Toast.tsx              # NEW (Sprint 1)
│           │   ├── LoadingSpinner.tsx     # NEW (Sprint 1)
│           │   └── MessageList.tsx        # NEW (Sprint 1, optional)
│           ├── contexts/
│           │   ├── AuthContext.tsx        # NEW (Sprint 2): Auth state
│           │   └── NotificationContext.tsx # NEW (Sprint 1)
│           ├── hooks/
│           │   └── useWebSocket.ts        # NEW (Sprint 1)
│           ├── lib/
│           │   ├── api-client.ts          # NEW (Sprint 1)
│           │   ├── types.ts               # NEW (Sprint 1)
│           │   └── api-types.ts           # NEW (Sprint 1)
│           ├── __tests__/                 # NEW (Sprint 1): Component tests
│           ├── config.ts                  # NEW (Sprint 1): Configuration
│           └── .env.local.example         # NEW (Sprint 1)
│
├── scripts/
│   ├── benchmarks/                 # NEW: Performance benchmarks
│   ├── load_tests/                 # NEW: Load testing
│   ├── resilience_tests/           # NEW: Resilience tests
│   └── demo/                       # NEW: Demo scripts
│
└── docs/
    ├── architecture.md             # NEW/UPDATED
    ├── onboarding.md               # NEW
    ├── rbac.md                     # NEW
    ├── observability.md            # NEW
    ├── configuration.md            # NEW
    ├── demo_playbook.md            # NEW
    ├── troubleshooting.md          # NEW
    ├── security_audit.md           # NEW
    ├── backlog_may_demo.md         # NEW
    └── compliance/                 # NEW
        ├── architecture_fiche.md
        ├── data_protection.md
        └── telemetry.md
```

---

## Notes

- **Sprint Planning:** Each sprint should start with a planning meeting to break down tasks into GitHub issues
- **Daily Standups:** Track progress and blockers daily
- **Sprint Reviews:** Demo completed work at end of each sprint
- **Retrospectives:** Identify improvements after each sprint
- **Issue Tracking:** All tasks must have GitHub issues with estimates and assignees
- **Code Reviews:** All PRs require 2 approvals before merge
- **Testing:** No code merged without tests (unit or integration)

---

**Document Version:** 1.0  
**Last Updated:** November 2025  
**Next Review:** End of Sprint 1

