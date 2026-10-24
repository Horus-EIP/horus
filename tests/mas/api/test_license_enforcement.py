"""License-state simulation and restricted-mode API integration tests."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from licensing.verification import LicenseCheck, LicenseState, verify_license
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from auth.auth_tool_functions import create_access_token, get_current_user
from chat.routes import router as chat_router
from db.database import get_db
from db.models import Conversations, Messages, Users

SITE_ID = str(uuid.uuid4())
KEY_ID = "license-integration-test-key"
SIMULATED_NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@pytest.fixture
def signed_license():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def sign(valid_until: date) -> bytes:
        header = {
            "alg": "EdDSA",
            "kid": KEY_ID,
            "typ": "HORUS-LICENSE",
        }
        payload = {
            "format_version": 1,
            "license_id": str(uuid.uuid4()),
            "license_type": "commercial",
            "customer_id": str(uuid.uuid4()),
            "customer_name": "License Integration Test",
            "site_ids": [SITE_ID],
            "tier": "team",
            "user_cap": 100,
            "issued_at": "2026-10-24T12:00:00Z",
            "valid_from": "2026-01-01",
            "valid_until": valid_until.isoformat(),
            "grace_days": 15,
            "features": ["core"],
        }
        header_segment = _base64url(
            json.dumps(header, separators=(",", ":")).encode("utf-8")
        )
        payload_segment = _base64url(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
        signature = private_key.sign(signing_input)
        return f"{header_segment}.{payload_segment}.{_base64url(signature)}".encode(
            "ascii"
        )

    return sign, public_key


def _check_state(signed_license, valid_until: date):
    sign, public_key = signed_license
    return verify_license(
        sign(valid_until),
        {KEY_ID: public_key},
        SITE_ID,
        now=SIMULATED_NOW,
    )


@pytest.mark.parametrize(
    ("valid_until", "expected_state"),
    [
        (date(2026, 11, 22), LicenseState.WARNING),
        (date(2026, 10, 23), LicenseState.GRACE),
        (date(2026, 10, 8), LicenseState.RESTRICTED),
    ],
)
def test_license_states_are_simulated_with_injected_now(
    signed_license, valid_until, expected_state
):
    result = _check_state(signed_license, valid_until)

    assert result.state is expected_state


def test_restricted_license_denies_chat_websocket_with_403(signed_license):
    license_check = _check_state(signed_license, date(2026, 10, 8))
    assert license_check.state is LicenseState.RESTRICTED

    app = FastAPI()
    app.include_router(chat_router)
    app.state.license = license_check
    client = TestClient(app)

    with pytest.raises(WebSocketDenialResponse) as denied:
        with client.websocket_connect("/chat/1/"):
            pytest.fail("Restricted license unexpectedly accepted the chat socket.")

    assert denied.value.status_code == 403


def test_uninitialized_license_status_denies_chat_websocket_with_503():
    app = FastAPI()
    app.include_router(chat_router)
    client = TestClient(app)

    with pytest.raises(WebSocketDenialResponse) as denied:
        with client.websocket_connect("/chat/1/"):
            pytest.fail("Chat unexpectedly accepted a request before license initialization.")

    assert denied.value.status_code == 503


def test_suspended_user_cannot_open_chat_with_an_existing_token(routing_db):
    account = Users(
        username="suspended-chat-user",
        hashed_password="not-used",
        role="user",
        is_active=False,
    )
    routing_db.add(account)
    routing_db.commit()
    routing_db.refresh(account)
    token = create_access_token(
        account.username,
        account.id,
        timedelta(minutes=20),
        account.role,
    )

    app = FastAPI()
    app.include_router(chat_router)
    app.state.license = LicenseCheck(state=LicenseState.VALID)
    app.dependency_overrides[get_db] = lambda: routing_db
    client = TestClient(app)

    with pytest.raises((WebSocketDenialResponse, WebSocketDisconnect)) as denied:
        with client.websocket_connect(f"/chat/1/?token={token}"):
            pytest.fail("A suspended user unexpectedly opened a chat socket.")

    if isinstance(denied.value, WebSocketDenialResponse):
        assert denied.value.status_code == 403
    else:
        assert denied.value.code == 1008


@pytest.mark.parametrize(
    "state",
    [
        LicenseState.MISSING,
        LicenseState.INVALID,
        LicenseState.NOT_YET_VALID,
        LicenseState.CLOCK_ROLLBACK,
    ],
)
def test_other_non_active_license_states_deny_chat_websocket_with_403(state):
    app = FastAPI()
    app.include_router(chat_router)
    app.state.license = LicenseCheck(state=state)
    client = TestClient(app)

    with pytest.raises(WebSocketDenialResponse) as denied:
        with client.websocket_connect("/chat/1/"):
            pytest.fail("A non-active license unexpectedly accepted the chat socket.")

    assert denied.value.status_code == 403


def test_restricted_license_still_allows_permissioned_data_export(
    routing_db, as_admin, signed_license
):
    from admin.routes import router as admin_router

    license_check = _check_state(signed_license, date(2026, 10, 8))
    assert license_check.state is LicenseState.RESTRICTED

    conversation = routing_db.query(Conversations).filter_by(id=7).one()
    routing_db.add(
        Messages(
            role="user",
            content="Export test message",
            conversation_id=conversation.id,
        )
    )
    routing_db.commit()

    app = FastAPI()
    app.include_router(admin_router)
    app.state.license = license_check
    app.dependency_overrides[get_db] = lambda: routing_db
    app.dependency_overrides[get_current_user] = lambda: as_admin

    with TestClient(app) as client:
        response = client.get("/admin/export")

    assert app.state.license.state is LicenseState.RESTRICTED
    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="horus-export.json"'
    )
    exported = response.json()
    assert exported["conversations"][0]["messages"][0]["content"] == (
        "Export test message"
    )


def test_restricted_license_export_still_requires_export_permission(
    routing_db, as_user, signed_license
):
    from admin.routes import router as admin_router

    app = FastAPI()
    app.include_router(admin_router)
    app.state.license = _check_state(signed_license, date(2026, 10, 8))
    app.dependency_overrides[get_db] = lambda: routing_db
    app.dependency_overrides[get_current_user] = lambda: as_user

    with TestClient(app) as client:
        response = client.get("/admin/export")

    assert app.state.license.state is LicenseState.RESTRICTED
    assert response.status_code == 403
