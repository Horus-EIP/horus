import asyncio
import sys

import httpx

BASE_URL = "http://localhost:8000"

# Default admin credentials (must exist in DB)
USERNAME_ADMIN = "admin"
PASSWORD_ADMIN = "secret"

# Test user credentials
TEST_USER = "test_mgmt_user"
TEST_PASS = "Horus#Pass123"


def bearer_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def register_user(username: str, password: str):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        r = await client.post(
            "/auth/register", json={"username": username, "password": password}
        )
        if r.status_code == 201:
            print(f"✅ REGISTERED {username}")
            return r.json()
        elif r.status_code == 409:
            print(f"ℹ️  User {username} already exists")
            return None
        else:
            print(f"❌ REGISTER {username} failed:", r.status_code, r.text)
            return None


async def login(username: str, password: str) -> str:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        r = await client.post(
            "/auth/token",
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            print(f"❌ LOGIN {username} failed: {r.status_code} {r.text}")
            return None
        data = r.json()
        print(f"✅ LOGIN {username} successful")
        return data["access_token"]


async def get_me(headers: dict):
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=120.0
    ) as client:
        r = await client.get("/users/me")
        if r.status_code == 200:
            print(f"✅ GET /users/me successful: {r.json()}")
            return r.json()
        else:
            print(f"❌ GET /users/me failed: {r.status_code} {r.text}")
            return None


async def get_users_list(headers: dict):
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=120.0
    ) as client:
        r = await client.get("/users/users_list")
        if r.status_code == 200:
            users = r.json()
            print(f"✅ GET /users/users_list successful. Count: {len(users)}")
            return users
        else:
            print(f"❌ GET /users/users_list failed: {r.status_code} {r.text}")
            return None


async def get_user_details(user_id: int, headers: dict):
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=120.0
    ) as client:
        r = await client.get(f"/users/user_details/{user_id}")
        if r.status_code == 200:
            print(f"✅ GET /users/user_details/{user_id} successful: {r.json()}")
            return r.json()
        else:
            print(
                f"❌ GET /users/user_details/{user_id} failed: {r.status_code} {r.text}"
            )
            return None


async def delete_user(user_id: int, headers: dict):
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=120.0
    ) as client:
        r = await client.delete(f"/users/{user_id}")
        if r.status_code == 200:
            print(f"✅ DELETE /users/{user_id} successful: {r.json()}")
            return True
        else:
            print(f"❌ DELETE /users/{user_id} failed: {r.status_code} {r.text}")
            return False


async def main():
    print("=" * 60)
    print("TESTING USER MANAGEMENT ENDPOINTS")
    print("=" * 60)

    try:
        # 1. Register a test user
        user_data = await register_user(TEST_USER, TEST_PASS)

        # 2. Login as Admin
        print("\n[Step 1] Admin Login")
        admin_token = await login(USERNAME_ADMIN, PASSWORD_ADMIN)
        if not admin_token:
            print(
                "⚠️  Cannot proceed without admin access. Ensure 'admin' user exists."
            )
            return
        admin_headers = bearer_headers(admin_token)

        # 3. Login as Test User
        print("\n[Step 2] Test User Login")
        user_token = await login(TEST_USER, TEST_PASS)
        if not user_token:
            return
        user_headers = bearer_headers(user_token)

        # 4. Test /users/me
        print("\n[Step 3] Testing /users/me")
        me_info = await get_me(user_headers)
        if not me_info:
            return
        test_user_id = me_info["id"]

        # 5. Test /users/users_list (Admin only)
        print("\n[Step 4] Testing /users/users_list (Admin)")
        users_list = await get_users_list(admin_headers)

        print("\n[Step 5] Testing /users/users_list (Regular User - Should Fail)")
        async with httpx.AsyncClient(
            base_url=BASE_URL, headers=user_headers, timeout=120.0
        ) as client:
            r = await client.get("/users/users_list")
            if r.status_code == 403:
                print("✅ Access correctly denied for regular user (403)")
            else:
                print(f"❌ Unexpected status code: {r.status_code}")

        # 6. Test /users/user_details/{id} (Admin only)
        print(f"\n[Step 6] Testing /users/user_details/{test_user_id} (Admin)")
        await get_user_details(test_user_id, admin_headers)

        # 7. Test DELETE /users/{id} (Admin only)
        print(f"\n[Step 7] Testing DELETE /users/{test_user_id} (Admin)")
        success = await delete_user(test_user_id, admin_headers)

        if success:
            # Verify user is gone
            print("\n[Step 8] Verifying deletion (Login should fail)")
            token = await login(TEST_USER, TEST_PASS)
            if token is None:
                print("✅ User successfully deleted (Login failed as expected)")
            else:
                print("❌ User still exists (Login succeeded)")

    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
