"""Conversation-routes contract tests (hermetic).

Routes under test (``src/services/mas/conversations/routes.py``):

* ``POST   /conversations/create-conversation/``    body: ConversationCreation(name)
* ``GET    /conversations/get-conversations/``      list user's conversations
* ``GET    /conversations/get_history/{chat_id}``   message history
* ``DELETE /conversations/delete-conversation/{chat_id}``  delete (TASK_DELETE)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from conversations.routes import router


class TestConversationCreate:
    def test_user_can_create_conversation(self, make_client, mock_db, as_user):
        # db.refresh(conv) is expected to populate conv.id from the database.
        # Simulate that so the response model (conversation_id: int) validates.
        def _refresh(conv):
            conv.id = 42
        mock_db.refresh.side_effect = _refresh
        client = make_client(router, current_user=as_user)
        r = client.post(
            "/conversations/create-conversation/",
            json={"name": "My chat"},
        )
        assert r.status_code == 200
        assert r.json() == {"conversation_id": 42}

    def test_create_requires_authentication(self, make_client, mock_db):
        client = make_client(router, current_user=None)
        r = client.post(
            "/conversations/create-conversation/",
            json={"name": "x"},
        )
        assert r.status_code == 401

    def test_create_rejects_missing_name(self, make_client, mock_db, as_user):
        client = make_client(router, current_user=as_user)
        r = client.post("/conversations/create-conversation/", json={})
        assert r.status_code == 422


class TestConversationList:
    def test_list_returns_200_with_empty_array(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        client = make_client(router, current_user=as_user)
        r = client.get("/conversations/get-conversations/")
        assert r.status_code == 200


class TestConversationDetail:
    def test_get_returns_404_for_unknown(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(router, current_user=as_user)
        r = client.get("/conversations/get_history/9999")
        assert r.status_code == 404


class TestConversationDelete:
    def test_owner_can_delete(self, make_client, mock_db, as_user):
        conv = MagicMock(owner_username=as_user["username"])
        # delete handler uses db.get(Conversations, id), not query.filter.first
        mock_db.get.return_value = conv
        client = make_client(router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 200

    def test_delete_missing_returns_404(self, make_client, mock_db, as_user):
        mock_db.get.return_value = None
        client = make_client(router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/9999")
        assert r.status_code == 404

    def test_non_owner_non_admin_gets_404(self, make_client, mock_db, as_user):
        conv = MagicMock(owner_username="someone-else")
        mock_db.get.return_value = conv
        client = make_client(router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        # Handler returns 404 (not 403) to avoid leaking existence
        assert r.status_code == 404
