import asyncio
import json

import httpx
import websockets

BASE_URL = "http://localhost:8000"


async def setup_agent_and_conversation():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # 1. Register an agent
        r = await client.post(
            "/agents/register",
            json={"name": "agent_test", "skills": ["skill1", "skill2"]},
        )
        r.raise_for_status()
        agent_id = r.json()["agent_id"]
        print("REGISTERED agent_id =", agent_id)

        # 2. Create a conversation
        r = await client.post("/conversations/create-conversation/")
        r.raise_for_status()
        conv_id = r.json()["conversation_id"]
        print("CREATED conversation_id =", conv_id)

        # 3. Post a new task
        r = await client.post(
            "/tasks/new_task/",
            json={
                "demand": "Faire une analyse de données",
                "conversation_id": conv_id,
                "skills_required": ["skill1"],
            },
        )
        r.raise_for_status()
        print("NEW_TASK →", r.json())

    return agent_id, conv_id


async def websocket_and_trigger(agent_id: str, conv_id: str):
    ws_uri = f"ws://localhost:8000/chat/{conv_id}/"
    print(f"WS connecting to {ws_uri} …")
    async with websockets.connect(ws_uri) as ws:
        print("✅ WS connected, now triggering task-result…")

        # 4. Trigger the task-result via HTTP to push into the WS
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            r = await client.post(
                "/tasks/task-result/",
                json={
                    "result": "Analyse terminée, voici le rapport envoyé via WS 📨",
                    "conversation_id": conv_id,
                    "agent_id": agent_id,
                    "question": "Faire une analyse de données",
                },
            )
            r.raise_for_status()
            print("TASK-RESULT →", r.json())

        # 5. Await the pushed message
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = raw
            print("← Received via WS:", msg)
        except asyncio.TimeoutError:
            print("⚠️ No message received on WS (timeout)")

        print("❌ WS connection closed.")

        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            r = await client.delete(f"/agents/unregister/{agent_id}")
            r.raise_for_status()
            print("UNREGISTERED_AGENT →", r.json())


async def main():
    agent_id, conv_id = await setup_agent_and_conversation()
    await websocket_and_trigger(agent_id, conv_id)


if __name__ == "__main__":
    asyncio.run(main())
