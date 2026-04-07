import asyncio

import httpx

BASE_URL = "http://localhost:8000"

USERNAME_ADMIN = "admin"
PASSWORD_ADMIN = "secret"

TEST_USER = "bob"
TEST_PASS = "password123"


def bearer_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def register_user(username: str, password: str):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        r = await client.post(
            "/auth/register", json={"username": username, "password": password}
        )
        if r.is_success:
            print(f"REGISTERED {username} →", r.json())
        else:
            print(f"REGISTER {username} failed:", r.status_code, r.text)


async def login(username: str, password: str) -> str:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        r = await client.post(
            "/auth/token",
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        data = r.json()
        print(f"LOGIN {username} →", data)
        return data["access_token"]


async def logout(headers: dict):
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=120.0
    ) as client:
        r = await client.post("/auth/logout")
        print("LOGOUT →", r.json())


async def make_admin(target_user: str, headers: dict):
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=120.0
    ) as client:
        r = await client.post(
            "/users/update_role",
            json={"user_id": target_user, "new_role": "admin"},
        )
        print(f"MAKE-ADMIN {target_user} →", r.status_code, r.text)


async def remove_admin(target_user: str, headers: dict):
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=120.0
    ) as client:
        r = await client.post(
            "/users/update_role",
            json={"user_id": target_user, "new_role": "user"},
        )
        print(f"REMOVE-ADMIN {target_user} →", r.status_code, r.text)


async def main():
    try:
        # 1) Register a normal user (bob)
        await register_user(TEST_USER, TEST_PASS)

        # 2) Login as admin
        admin_token = await login(USERNAME_ADMIN, PASSWORD_ADMIN)
        admin_headers = bearer_headers(admin_token)

        # 3) Login as bob
        bob_token = await login(TEST_USER, TEST_PASS)
        bob_headers = bearer_headers(bob_token)

        # 4) Admin gives bob admin rights
        await make_admin(TEST_USER, admin_headers)

        # 5) Admin removes bob’s admin rights
        await remove_admin(TEST_USER, admin_headers)

        # 6) Bob tries to make himself admin → doit échouer (401 ou 403)
        await make_admin(TEST_USER, bob_headers)

        # 7) Bob tries to remove admin rights from "admin" → doit échouer (403)
        await remove_admin("admin", bob_headers)

        # 8) Logout bob
        await logout(bob_headers)

        # 9) Logout admin
        await logout(admin_headers)

    except httpx.HTTPStatusError as e:
        resp = e.response
        print(
            f"HTTP error {resp.status_code} on {resp.request.method} {resp.request.url}"
        )
        try:
            print("Body:", resp.json())
        except Exception:
            print("Body:", resp.text)
        raise
    except Exception as e:
        print("Unexpected error:", repr(e))
        raise


if __name__ == "__main__":
    asyncio.run(main())
