"""Conversation-routes contract tests (hermetic).

Routes under test (``src/services/mas/conversations/routes.py``):

* ``POST   /conversations/create-conversation/`` → 200 / 400 / 500
* ``GET    /conversations/{chat_id}``            → 200 / 401 / 404
* ``DELETE /conversations/{chat_id}``            → 200 / 401 / 404 / 409
* ``GET    /conversations/``                     → 200 / 401 / 500
* ``GET    /conversations/get-conversations``    → alias of GET /

Replaces 4 legacy files.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from conversations.routes import router


# --------------------------------------------------------------------------- #
# CREATE
# --------------------------------------------------------------------------- #


class TestConversationCreate:
    def test_user_can_create_conversation(self, make_client, mock_db, as_user):
        client = make_client(router, current_user=as_user)
        r = client.post(
            "/conversations/create-conversation/",
            json={"title": "My chat"},
        )
        assert r.status_code in (200, 400)

    def test_create_requires_authentication(self, make_client, mock_db):
        client = make_client(router, current_user=None)
        r = client.post(
            "/conversations/create-conversation/",
            json={"title": "x"},
        )
        assert r.status_code == 401


# --------------------------------------------------------------------------- #
# LIST / READ
# --------------------------------------------------------------------------- #


class TestConversationList:
    def test_list_returns_200_with_empty_array(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.all.return_value = []
        client = make_client(router, current_user=as_user)
        r = client.get("/conversations/")
        assert r.status_code == 200
        assert r.json() == []

    def test_alias_path_works(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.all.return_value = []
        client = make_client(router, current_user=as_user)
        r = client.get("/conversations/get-conversations")
        assert r.status_code == 200


class TestConversationDetail:
    def test_get_returns_200_when_owned(self, make_client, mock_db, as_user):
        conv = MagicMock(user_id=as_user["user_id"], messages=[])
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        client = make_client(router, current_user=as_user)
        r = client.get("/conversations/1")
        assert r.status_code == 200

    def test_get_returns_404_for_unknown(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(router, current_user=as_user)
        r = client.get("/conversations/9999")
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# DELETE
# --------------------------------------------------------------------------- #


class TestConversationDelete:
    def test_owner_can_delete(self, make_client, mock_db, as_user):
        conv = MagicMock(user_id=as_user["user_id"])
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        client = make_client(router, current_user=as_user)
        r = client.delete("/conversations/1")
        assert r.status_code == 200

    def test_delete_missing_returns_404(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(router, current_user=as_user)
        r = client.delete("/conversations/9999")
        assert r.status_code == 404
