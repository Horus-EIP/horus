import os
import sys

import requests

# Add parent directory to path to import config if needed, though we'll use hardcoded URL for simplicity or env var
BASE_URL = "http://localhost:8000"


def print_separator(title: str = "") -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)


def test_user_modifications():
    print_separator("TEST: User Modifications (Password & Username)")

    # 1. Register a new user for testing
    username = "mod_test_user"
    password = "password123"

    print(f"\n[Setup] Registering user '{username}'...")
    requests.post(
        f"{BASE_URL}/auth/register",
        json={"username": username, "password": password},
        timeout=120.0,
    )

    # 2. Login to get token
    print(f"[Setup] Logging in...")
    response = requests.post(
        f"{BASE_URL}/auth/token",
        data={"username": username, "password": password},
        timeout=120.0,
    )
    if response.status_code != 200:
        print(f"❌ Login failed: {response.text}")
        return

    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✅ Login successful")

    # 3. Test Password Modification
    print("\n[Test 1] Change Password")
    new_password = "newpassword456"
    payload = {"old_password": password, "new_password": new_password}

    resp = requests.post(
        f"{BASE_URL}/users/me/password_modification",
        json=payload,
        headers=headers,
        timeout=120.0,
    )
    if resp.status_code == 200:
        print("✅ Password changed successfully")
    else:
        print(f"❌ Password change failed: {resp.text}")

    # 4. Verify new password works (re-login)
    print("\n[Test 2] Verify New Password Login")
    resp = requests.post(
        f"{BASE_URL}/auth/token", data={"username": username, "password": new_password}
    )
    if resp.status_code == 200:
        print("✅ Login with new password successful")
        # Update token just in case, though old one should still be valid until expiry
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
    else:
        print(f"❌ Login with new password failed: {resp.text}")

    # 5. Test Username Modification
    print("\n[Test 3] Change Username")
    new_username = "mod_test_user_updated"

    resp = requests.post(
        f"{BASE_URL}/users/me/username_modification/{new_username}", headers=headers
    )
    if resp.status_code == 200:
        print(f"✅ Username changed to '{new_username}' successfully")
    else:
        print(f"❌ Username change failed: {resp.text}")

    # 6. Verify new username works (re-login)
    print("\n[Test 4] Verify New Username Login")
    resp = requests.post(
        f"{BASE_URL}/auth/token",
        data={"username": new_username, "password": new_password},
    )
    if resp.status_code == 200:
        print("✅ Login with new username successful")
    else:
        print(f"❌ Login with new username failed: {resp.text}")

    # Cleanup (optional, if delete endpoint exists and we have admin rights, but we are a regular user here)
    # We could try to delete ourselves if that endpoint allows it, but usually it's admin only or restricted.
    # The delete_user endpoint in routes.py seems to be admin only.

    print("\n" + "=" * 70)
    print("USER MODIFICATION TESTS COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    try:
        test_user_modifications()
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
