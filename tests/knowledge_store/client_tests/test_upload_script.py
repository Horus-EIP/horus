import httpx
import asyncio
import os

async def main():
    url = "http://localhost:8080/upload"
    filepath = "client_test_file.txt"
    
    with open(filepath, "w") as f:
        f.write("This is a client test document.")
        
    try:
        async with httpx.AsyncClient() as client:
            files = {'file': (filepath, open(filepath, 'rb'), 'text/plain')}
            response = await client.post(url, files=files)
            print("Status:", response.status_code)
            print("Response:", response.json())
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

if __name__ == "__main__":
    asyncio.run(main())
