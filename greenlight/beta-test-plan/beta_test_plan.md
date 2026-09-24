---
title:          Beta Test Plan
subtitle:       Horus Multi-Agent Orchestration System
author:         Horus Team
module:         G-EIP-700
version:        1.1
---

## **1. Project Context**

Horus AI is a self-hosted multi-agent orchestration system designed to enable secure, private, and scalable AI deployments. The platform empowers businesses to build autonomous, real-time, and modular AI workflows without relying on external cloud services.

The system operates through several interconnected components:
- **MAS (Multi-Agent System Orchestrator)**: A FastAPI-based service responsible for agent registry, conversation management, task orchestration, and user authentication
- **Agent Service**: Handles the RAG (Retrieval-Augmented Generation) pipeline, consuming tasks via RabbitMQ and providing intelligent responses grounded in uploaded documents
- **Knowledge Store**: A document management system powered by ChromaDB that allows users to upload, organize, and query documents for context-aware AI responses
- **Web Client**: A Next.js-based dashboard providing chat interface, conversation management, knowledge store UI, admin functionalities, and real-time analytics

The platform uses PostgreSQL for data persistence, Redis for caching, RabbitMQ for message queuing, and integrates comprehensive observability through Prometheus, Loki, and Tempo, surfaced in the web client's admin pages.

---

## **2. User Roles**

The following roles will be involved in beta testing.

| **Role Name** | **Description** |
|---------------|-----------------|
| Admin | An administrator with full system access who can manage users, configure system settings, register/delete agents, assign roles, view analytics, and access all resources |
| Manager | An operational manager who can create and approve tasks, execute agents, view analytics, delete agents, view task queue, and manage team operations without user administration privileges |
| User | A standard application user who can create conversations, send messages, create tasks, execute agents, delete their own conversations, and interact with the knowledge store |

---

## **3. Feature Table**

All of the listed features will be demonstrated during the beta presentation.

| **Feature ID** | **User Role** | **Feature Name** | **Short Description** |
|----------------|---------------|------------------|----------------------|
| F1 | Everyone | Log in | A user can log in to the system using their credentials and receive a JWT token |
| F2 | Admin | Create user | An admin can create new user accounts via the admin panel with username, password, and role assignment |
| F3 | Admin | Delete user | An admin can delete existing user accounts from the system |
| F4 | Admin | Assign role | An admin can assign or change a user's role (admin, manager, user) via the admin panel |
| F5 | Admin | View all users | An admin can view a list of all registered users and their roles |
| F6 | Everyone | Create conversation | A user can create a new conversation with a custom name |
| F7 | Everyone | List conversations | A user can view all their existing conversations via the Conversations page |
| F8 | Owner/Admin/Manager | Delete conversation | A user can delete their own conversation; admins and managers can delete any conversation |
| F9 | Everyone | Upload document | A user can upload a document; the system automatically analyzes, categorizes, and extracts entities (people, amounts, dates) |
| F10 | Everyone | List documents | A user can view all uploaded documents with auto-detected categories and metadata |
| F11 | Everyone | Delete document | A user can delete a document from the knowledge store |
| F12 | Everyone | Query documents | A user can query documents using smart search with category, entity, and topic filters |
| F13 | Admin | Register agent | An admin can register a new agent with specific skills via the admin panel with API key generation |
| F14 | Everyone | View registered agents | Users can view all registered agents with their status and capabilities on the dashboard |
| F15 | Everyone | Send message | A user can send a text message within a conversation |
| F16 | Everyone | Receive AI response | The system returns an AI-generated response using multi-step reasoning for complex queries, with source citations |
| F17 | Everyone | View message history | A user can view the complete message history of a conversation |
| F18 | Everyone | Create task | A user can create a new task specifying the demand and required skills |
| F19 | Manager/Admin | View task queue | A manager can view task queue statistics (pending, running, completed, failed, cancelled, timeout) via the Tasks page |
| F20 | Admin | Cancel task | An admin can cancel a pending or running task via the API |
| F21 | Everyone | Receive task result | A user receives the task result notification upon completion via WebSocket |
| F22 | Everyone | Access dashboard | A user can access the main dashboard with real-time system analytics graph |
| F23 | Everyone | View analytics | Users can view real-time system analytics including active agents, running tasks, and pending tasks via a live graph on the dashboard |
| F24 | Admin/Manager | Delete agent | An admin or manager can unregister an agent from the system via the dashboard or admin panel |

---

## **4. Success Criteria**

| **Feature ID** | **Key Success Criteria** | **Indicator/Metric** | **Result** |
|----------------|-------------------------|----------------------|------------|
| F1 | A user can log in and receive a valid JWT token | 30 attempts, 0 failures | 30/30 PASS |
| F2 | Admin can create users with username, password, and role | 10 creations, all visible with correct roles | 10/10 PASS |
| F3 | Deleted users can no longer access the system | 5 deletions, all blocked | 5/5 PASS |
| F4 | Role changes are immediately reflected in permissions | 10 changes, all updated correctly | 10/10 PASS |
| F5 | Admin can view user list with search and role filter | List displays correctly with filters | 1/1 PASS |
| F6 | Creating a conversation adds it to the user's list | 20 created, all visible | 20/20 PASS |
| F7 | User can list all their conversations with search | 15 lists loaded correctly | 15/15 PASS |
| F8 | Owner/Admin/Manager can delete conversation | 15 deletions, 0 residual data | 15/15 PASS |
| F9 | Upload triggers auto-analysis (category, entities, summary) | 20 uploads, processing < 20s each | 20/20 PASS |
| F10 | Document list shows category and metadata | All uploads display category/summary | 1/1 PASS |
| F11 | Deleted documents removed from search results | 10 deletions, 0 phantom results | 10/10 PASS |
| F12 | Query with filters returns relevant excerpts | 25 queries, response < 3s, 90% accuracy | 23/25 (92%) |
| F13 | Admin can register agent and receive API key | 5 registrations with API key | 5/5 PASS |
| F14 | Agent list shows status and auto-refreshes | Updates within 10s of change | 1/1 PASS |
| F15 | Sent messages appear within 1 second | 50 messages, latency < 1s | 50/50 PASS |
| F16 | AI responds with reasoning and source citations | 30 queries: simple < 15s, complex < 60s | 30/30 PASS |
| F17 | Message history loads with correct ordering | 20 loads, all in order | 20/20 PASS |
| F18 | Tasks are assigned to agents based on skills | 15 tasks, 90% correctly routed | 15/15 PASS |
| F19 | Task queue shows all stats with progress | Stats match API across 20 checks | 20/20 PASS |
| F20 | Cancel task stops pending/running tasks | 5 cancellations within 5 seconds | 5/5 PASS |
| F21 | Task results delivered via WebSocket | 20 completions, all received | 20/20 PASS |
| F22 | Dashboard loads with analytics graph | 25 loads, < 3s load time | 25/25 PASS |
| F23 | Analytics graph updates in real-time | Updates every 10s, 30 data points | 30/30 PASS |
| F24 | Admin/Manager can delete agents | 3 deletions, no tasks routed after | 3/3 PASS |


---

