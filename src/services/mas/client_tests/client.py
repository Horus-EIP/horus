import asyncio

import httpx
import websockets

BASE_URL = "http://localhost:8000"


async def test_http_endpoints():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # 1. Register an agent
        resp = await client.post(
            "/agents/register",
            json={"name": "agent_test", "skills": ["skill1", "skill2"]},
        )
        print("POST /agents/register →", resp.status_code, resp.json())
        agent_id = resp.json().get("agent_id")

        # 2. Get details for that agent
        resp = await client.get(f"/agents/details/{agent_id}")
        print(f"GET /agents/details/{agent_id} →", resp.status_code, resp.json())

        # 3. Get all agents
        resp = await client.get("/agents/details/")
        print("GET /agents/details/ →", resp.status_code, resp.json())

        # 4. Send a heartbeat
        resp = await client.post(f"/agents/heartbeat/{agent_id}")
        print(f"POST /agents/heartbeat/{agent_id} →", resp.status_code, resp.json())

        # 5. Create a new conversation
        resp = await client.post("/conversations/create-conversation/")
        print(
            "POST /conversations/create-conversation/ →", resp.status_code, resp.json()
        )
        conv_id = resp.json().get("conversation_id")

        # 6. Assign a new task to the agent
        task_payload = {
            "demand": "Faire une analyse de données",
            "conversation_id": conv_id,
            "skills_required": ["skill1"],
        }
        resp = await client.post("/tasks/new_task/", json=task_payload)
        print("POST /tasks/new_task/ →", resp.status_code, resp.json())

        # 7. Simulate the agent sending back a result
        result_payload = {
            "result": "Analyse terminée, voici le rapport.",
            "conversation_id": conv_id,
            "agent_id": agent_id,
        }
        resp = await client.post("/tasks/task-result/", json=result_payload)
        print("POST /tasks/task-result/ →", resp.status_code, resp.json())

        # 8. Retrieve conversation history
        # Note : votre route est définie sans slash leading, donc on l'appelle exactement :
        resp = await client.get(f"/conversations/get_history/{conv_id}")
        print(
            f"GET /conversations/get_history/{conv_id} →", resp.status_code, resp.json()
        )

        # 9. Unregister the agent
        resp = await client.delete(f"/agents/unregister/{agent_id}")
        print(f"DELETE /unregister/{agent_id} →", resp.status_code, resp.json())


async def test_websocket(conversation_id: str):
    uri = f"ws://localhost:8000/chat/{conversation_id}/"
    print("👾 Tentative de connexion WS à", uri)
    try:
        async with websockets.connect(uri) as ws:
            print("✅ WebSocket connecté.")
            # On écoute quelques messages entrants (s'il y en a)
            for _ in range(3):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    print("← Message reçu:", msg)
                except asyncio.TimeoutError:
                    break
            # On ferme la connexion
            await ws.close()
            print("❌ WebSocket fermé.")
    except Exception as e:
        print("❌ Erreur WS :", e)


async def main():
    # Tester d'abord les routes HTTP
    await test_http_endpoints()

    # Recréer une conversation pour tester le WS
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.post("/conversations/create-conversation/")
        conv_id = resp.json().get("conversation_id")

    # Lancer le test WebSocket
    await test_websocket(conv_id)


if __name__ == "__main__":
    asyncio.run(main())
