"""
server.py
---------
This module implements the agent server that integrates with the MAS Orchestrator API.
The agent registers itself with the orchestrator, periodically sends heartbeat signals,
and exposes an endpoint to receive tasks.
When a task is received, it processes the task using the RAG pipeline and sends the result
back to the MAS via the /agents/result endpoint.
"""

import uuid
import threading
import time
import json
import os
import requests
import pika
from fastapi import FastAPI
from pydantic import BaseModel
from ai_agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.rag_pipeline import RAGPipeline
from ai_agents.mock_store import mock_knowledge_store
from config.settings import ORCHESTRATOR_URL

app = FastAPI()

# Agent details
# Will be set after successful registration with MAS
AGENT_ID = None
AGENT_NAME = "HorusAgent"
SKILLS = ["knowledge_retrieval", "decision_making", "rag_pipeline"]

# Initialize the RAG pipeline components
retrieval_agent = KnowledgeRetrievalAgent(store_interface=mock_knowledge_store)
decision_agent = DecisionMakingAgent(model_name="t5-small")
rag_pipeline = RAGPipeline(retrieval_agent, decision_agent)

class Task(BaseModel):
    """
    Model for tasks received from the MAS Orchestrator.
    """
    task_id: str = None  # Auto-generated if not provided.
    query: str
    conversation_id: str

class Result(BaseModel):
    """
    Model for sending task results back to the MAS Orchestrator.
    """
    agent_id: str
    result: str

def register_agent():
    """Register the agent with MAS. Keep retrying until successful.

    Uses a simple backoff to handle MAS not being ready at container start.
    """
    global AGENT_ID
    url = f"{ORCHESTRATOR_URL}/agents/register"
    base_name = AGENT_NAME
    name_variant = base_name
    backoff_seconds = 1
    while not AGENT_ID:
        try:
            payload = {"name": name_variant, "skills": SKILLS}
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                AGENT_ID = data.get("agent_id")
                print("Agent registered with id:", AGENT_ID)
                break
            if response.status_code == 409:
                name_variant = f"{base_name}-{uuid.uuid4().hex[:6]}"
                print(f"Agent name conflict. Retrying with name '{name_variant}'…")
            else:
                print("Agent registration failed:", response.status_code, response.text)
        except Exception as e:
            print("Error registering agent (will retry):", e)
        time.sleep(backoff_seconds)
        backoff_seconds = min(backoff_seconds * 2, 30)

def send_heartbeat():
    """
    Sends a heartbeat to the MAS Orchestrator using the /agents/heartbeat endpoint.
    """
    if not AGENT_ID:
        return
    url = f"{ORCHESTRATOR_URL}/agents/heartbeat/{AGENT_ID}"
    try:
        response = requests.post(url)
        if response.status_code != 200:
            print("Heartbeat failed:", response.text)
        else:
            print("Heartbeat sent:", response.json())
    except Exception as e:
        print("Error sending heartbeat:", e)

def heartbeat_task():
    """
    Background task that sends a heartbeat every 30 seconds.
    """
    while True:
        send_heartbeat()
        time.sleep(30)  # Adjust the interval as needed.


def _consume_messages():
    """
    Connect to RabbitMQ and consume tasks sent to this agent's queue. Each message
    is expected to be a JSON string with at least 'demand' and 'conversation_id'.
    It is transformed into the internal task format and processed by the RAG pipeline.
    """
    if not AGENT_ID:
        print("Cannot start consumer: AGENT_ID not set")
        return

    try:
        rabbit_host = os.getenv("RABBITMQ_HOST", "localhost")
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=rabbit_host,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
        )
        channel = connection.channel()
        # Declare a durable queue to avoid RabbitMQ 'transient_nonexcl_queues' deprecation
        channel.queue_declare(
            queue=AGENT_ID,
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
        )

        def _on_message(ch, method, properties, body):
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                # Fallback: treat body as plain text demand
                payload = {"demand": body.decode("utf-8")}

            demand = payload.get("demand", "")
            conversation_id = payload.get("conversation_id", "")
            task_id = payload.get("task_id") or ("task_" + uuid.uuid4().hex)

            print(f"[Consumer] Received task: {task_id} demand='{demand}' conv='{conversation_id}'")

            # Adapt to pipeline expected schema
            task_dict = {"task_id": task_id, "query": demand}
            result_dict = rag_pipeline.process_task(task_dict)

            # Send result back to MAS (requires conversation_id)
            if conversation_id:
                send_result(result_dict["response"], conversation_id)

            # Acknowledge the message
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=AGENT_ID, on_message_callback=_on_message)
        print(f"[Consumer] Listening on RabbitMQ queue '{AGENT_ID}'…")
        channel.start_consuming()
    except Exception as e:
        print("Error in RabbitMQ consumer:", e)

def send_result(result: str, conversation_id: str):
    """
    Sends the processed task result to the MAS Orchestrator using the /agents/result endpoint.

    Args:
        result: The result string generated by the RAG pipeline.
    """
    url = f"{ORCHESTRATOR_URL}/tasks/task-result/"
    payload = {
        "agent_id": AGENT_ID,
        "result": result,
        "conversation_id": conversation_id,
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print("Failed to send result:", response.text)
    else:
        print("Result sent:", response.json())

@app.on_event("startup")
async def startup_event():
    """
    On startup, register the agent with the MAS Orchestrator and start the heartbeat thread.
    """
    register_agent()
    # Start heartbeat if registration succeeded and we have an id
    heartbeat_thread = threading.Thread(target=heartbeat_task, daemon=True)
    heartbeat_thread.start()

    # Start RabbitMQ consumer in background
    consumer_thread = threading.Thread(target=_consume_messages, daemon=True)
    consumer_thread.start()

@app.post("/task")
async def receive_task(task: Task):
    """
    Endpoint to receive a task from the MAS Orchestrator.

    When a POST request with a task payload is received, the agent:
      1. Auto-generates a task_id if one isn't provided.
      2. Processes the task using the RAG pipeline.
      3. Sends the result back to the MAS Orchestrator.
      4. Returns the task result.
    """
    if not task.task_id:
        task.task_id = "task_" + uuid.uuid4().hex
    print(f"Received task: {task.task_id} with query: {task.query}")

    # Process the task using the RAG pipeline.
    result_dict = rag_pipeline.process_task(task.dict())

    # Send the result back to the orchestrator.
    send_result(result_dict["response"], task.conversation_id)

    return result_dict