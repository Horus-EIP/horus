# ADR-001: Selection of RabbitMQ for Message Brokering

**Date:** 2026-04-14
**Status:** Accepted

## Context
In this architecture, we needed a robust communication and task distribution mechanism between the MAS orchestrator and the various connected agents. In case of a system restart, the architecture must be able to preserve and recover the tasks planned for each agent. Another key constraint was optimizing execution time: LLM requests are inherently slow and resource-intensive. We had to ensure that while an agent is processing a long LLM request, the orchestrator remains completely non-blocking and can continue distributing tasks for other connected clients.

## Decision
We selected **RabbitMQ** as the primary message broker, utilizing a queue system for task routing and agent heartbeat monitoring.

## Consequences
**Pros:**
- **Reduced load on the orchestrator:** Prevents bottlenecks during heavy LLM inference.
- **Faster perceived execution time:** The orchestrator can respond to users immediately while agents work in the background.
- **System decoupling & fault tolerance:** The solution is broken down into independent modules. If one agent crashes, it doesn't bring down the entire system or the orchestrator.
- **Ecosystem fit:** Excellent integration with Python and Docker Compose.
- **Performance evidence:** According to our Comparative Tech Brief, native AMQP task routing overhead is `<100ms`. 
- **Reliability & Time saved:** Testing showed a 100% success rate on task routing (BTP F18: 15/15). Choosing RabbitMQ over a custom dispatcher saved an estimated 2 weeks of development time.

**Cons / Accepted Risks:**
- **Added complexity:** An additional infrastructure component to configure and maintain within our stack.
 
## Alternatives considered
- **Kafka:** Rejected. While excellent for high-throughput data streaming, it is unnecessarily complex to operate for our specific need of a simple, reliable task queue.
- **Redis Streams:** Rejected. Although very fast and already present in our stack (for caching), it offers less robust delivery guarantees and routing semantics than RabbitMQ's native AMQP for this specific use case.
- **Celery:** Rejected. It acts as an abstraction layer (a worker framework) over a broker. Given our architecture based on autonomous AI agents, adding Celery would introduce unnecessary abstraction and reduce our custom control over the agents.

## References
- Comparative Tech Brief
- Architecture Overview