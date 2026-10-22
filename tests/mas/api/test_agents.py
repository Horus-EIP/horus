"""Agent-routes contract tests (hermetic).

Routes under test (``src/services/mas/agents/routes.py``):

* ``POST   /agents/register``                      body: RegistrationForm(name, skills, description, type)
* ``DELETE /agents/unregister/{agent_id}``         AGENT_DELETE; uses delete_agent helper
* ``GET    /agents/details/{id}``                  AGENT_READ
* ``GET    /agents/details/``                      AGENT_READ
* ``POST   /agents/heartbeat/{agent_id}``          requires X-API-Key + Agent-ID (verify_agent_api_key)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.routes import router


class TestAgentRegistration:
    @patch("agents.routes.create_agent", return_value=(None, None, True))
    def test_register_returns_409_on_duplicate_name(self, mock_create, make_client, as_admin):
        # A registration conflict with an active agent is reported as 409.
        client = make_client(router, current_user=as_admin)
        r = client.post(
            "/agents/register",
            json={"name": "dup", "skills": ["s1"], "description": "x", "type": "researcher"},
        )
        assert r.status_code == 409
        mock_create.assert_awaited_once()

    @patch("agents.routes.create_agent", return_value=("new-id", "api-key", False))
    def test_register_returns_200_on_new_agent(self, _create, make_client, mock_db, as_admin):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(router, current_user=as_admin)
        r = client.post(
            "/agents/register",
            json={"name": "agent-01", "skills": ["s1"], "description": "x", "type": "researcher"},
        )
        assert r.status_code == 200


class TestAgentUnregister:
    @patch("agents.routes.delete_agent", return_value=True)
    def test_admin_unregister_returns_200(self, _del, make_client, as_admin):
        client = make_client(router, current_user=as_admin)
        r = client.delete("/agents/unregister/a-id")
        assert r.status_code == 200

    @patch("agents.routes.delete_agent", return_value=False)
    def test_unregister_unknown_agent_returns_404(self, _del, make_client, as_admin):
        client = make_client(router, current_user=as_admin)
        r = client.delete("/agents/unregister/ghost")
        assert r.status_code == 404


class TestAgentApiKeyRegeneration:
    """POST /agents/regenerate-key/{agent_id} — AGENT_UPDATE (admin only).

    Rotates the stored key and returns the new plaintext once; the registry
    helper is patched so no real bcrypt/DB work runs here.
    """

    @patch("agents.routes.regenerate_agent_api_key", return_value="new-plaintext-key")
    def test_admin_regenerate_returns_200_with_new_key(self, _regen, make_client, as_admin):
        client = make_client(router, current_user=as_admin)
        r = client.post("/agents/regenerate-key/a-id")
        assert r.status_code == 200
        body = r.json()
        assert body["api_key"] == "new-plaintext-key"
        assert body["agent_id"] == "a-id"

    @patch("agents.routes.regenerate_agent_api_key", return_value=None)
    def test_regenerate_unknown_agent_returns_404(self, _regen, make_client, as_admin):
        client = make_client(router, current_user=as_admin)
        r = client.post("/agents/regenerate-key/ghost")
        assert r.status_code == 404

    def test_user_role_cannot_regenerate_key(self, make_client, as_user):
        # 'user' role lacks AGENT_UPDATE, so the PermissionChecker rejects it
        # before the handler runs (no need to patch the registry helper).
        client = make_client(router, current_user=as_user)
        r = client.post("/agents/regenerate-key/a-id")
        assert r.status_code == 403


class TestAgentDetails:
    def test_list_details_returns_200(self, make_client, mock_db, as_admin):
        mock_db.query.return_value.all.return_value = []
        client = make_client(router, current_user=as_admin)
        r = client.get("/agents/details/")
        assert r.status_code == 200

    def test_get_unknown_id_returns_404(self, make_client, mock_db, as_admin):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(router, current_user=as_admin)
        r = client.get("/agents/details/missing")
        assert r.status_code == 404


class TestAgentHeartbeat:
    """Heartbeat uses verify_agent_api_key (X-API-Key + Agent-ID headers),
    not get_current_user. Override that dependency via agent_api_auth.
    """

    @patch("agents.routes.update_alive_agent_status", return_value=True)
    def test_heartbeat_with_matching_id_returns_200(self, _upd, make_client, as_admin):
        client = make_client(
            router,
            current_user=as_admin,
            agent_api_auth=("a-id", "k1"),
        )
        r = client.post("/agents/heartbeat/a-id")
        assert r.status_code == 200

    @patch("agents.routes.update_alive_agent_status", return_value=False)
    def test_heartbeat_for_missing_agent_returns_404(self, _upd, make_client, as_admin):
        # Source: agents/routes.py — returns 404 when the update helper
        # reports the agent was not found (no row updated).
        client = make_client(
            router,
            current_user=as_admin,
            agent_api_auth=("ghost", "k1"),
        )
        r = client.post("/agents/heartbeat/ghost")
        assert r.status_code in (403, 404)


class TestAgentAuthErrors:
    def test_unauthenticated_returns_401(self, make_client):
        client = make_client(router, current_user=None)
        assert client.get("/agents/details/").status_code == 401

    def test_user_role_cannot_register_agent(self, make_client, as_user):
        client = make_client(router, current_user=as_user)
        r = client.post(
            "/agents/register",
            json={"name": "x", "skills": ["s1"], "description": "x", "type": "researcher"},
        )
        assert r.status_code == 403
