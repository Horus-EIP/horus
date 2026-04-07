import httpx
import uuid
import time
import asyncio
import os

BASE_URL = "http://localhost:8080"

async def test_knowledge_base_flow():
    print("--- Testing Knowledge Base Flow ---")
    
    doc_id = str(uuid.uuid4())
    doc_data = {
        "title": "Client Test Doc",
        "content": f"This is a unique content for client test {doc_id}",
        "id": doc_id,
        "size": 100
    }
    
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        # 1. Add Document
        print(f"Adding document {doc_id}...")
        resp = await client.post("/", json=doc_data)
        if resp.status_code != 200:
            print(f"Failed to add document: {resp.text}")
            return
        print("Document added.")
        
        # Give DB some time to index if async (Chroma usually fast)
        # 2. Query Document
        print(f"Querying for content '{doc_data['content']}'...")
        # Retry logic just in case
        found = False
        for _ in range(5):
            resp = await client.get("/", params={"query": doc_data["content"]})
            if resp.status_code == 200:
                data = resp.json()
                docs = data.get("documents", [[]])[0]
                if docs and doc_data['content'] in docs:
                    print("Document found in query results.")
                    found = True
                    break
            time.sleep(0.5)
            
        if not found:
            print("Warning: Document not found in query results (consistency delay?)")
            
        # 3. Delete Document
        print(f"Deleting document {doc_id}...")
        resp = await client.delete(f"/{doc_id}")
        if resp.status_code == 200:
            print("Document deleted.")
        else:
            print(f"Failed to delete document: {resp.text}")

async def test_file_flow():
    print("\n--- Testing File Flow ---")
    filename = f"client_test_{uuid.uuid4()}.txt"
    content = b"This is a client test file."
    
    # Create dummy file
    with open(filename, "wb") as f:
        f.write(content)
        
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
            # 1. Upload File (Legacy /file route)
            print(f"Uploading file {filename}...")
            files = {"files": (filename, content, "text/plain")}
            resp = await client.post("/file", files=files)
            if resp.status_code == 200:
                print("File uploaded.")
                # Response is list
                data = resp.json()
                # print(data)
            else:
                print(f"Failed to upload file: {resp.text}")
                return

            # 2. List Files
            print("Listing files...")
            resp = await client.get("/file")
            if resp.status_code == 200:
                data = resp.json()
                docs = data.get("documents", [])
                found = any(d['title'] == filename for d in docs)
                if found:
                    print(f"File {filename} found in list.")
                else:
                    print(f"File {filename} NOT found in list.")
            else:
                print(f"Failed to list files: {resp.text}")

            # 3. Delete File
            print(f"Deleting file {filename}...")
            resp = await client.delete(f"/file/{filename}")
            if resp.status_code == 200:
                print("File deleted.")
            else:
                print(f"Failed to delete file: {resp.text}")
                
            # 4. Test Upload Route (/api/knowledge-store/upload)
            # The app root is /api/knowledge-store if mounted? 
            # In main.py: root_path="/api/knowledge-store". 
            # But uvicorn runs app directly on / usually.
            # Localhost:8080/upload check store.py router @router.post("/upload")
            # store.py is mounted at ""
            
            print(f"Testing /upload endpoint...")
            files = {"file": (f"n2t9_{filename}", content, "text/plain")}
            resp = await client.post("/upload", files=files)
            if resp.status_code == 200:
                data = resp.json()
                if "auto_analysis" in data and "chunks" in data:
                    print("Upload successful with analysis and chunks.")
                else:
                    print("Upload response format unexpected:", data.keys())
            else:
                print(f"Upload failed: {resp.text}")

    finally:
        if os.path.exists(filename):
            os.remove(filename)

async def main():
    await test_knowledge_base_flow()
    await test_file_flow()

if __name__ == "__main__":
    asyncio.run(main())
