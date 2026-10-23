from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.models  # noqa: F401
from auth.permissions import Role
from db import agent_account
from db.database import Base
from db.models import Users
from unit.password_test_helpers import hash_password, verify_password

GENERATED = "Kq3-vT9xLm2_Rw7pZc4Nd8"
CHOSEN = "Chosen-Pass-2026!"


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def logs():
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(patch.object(agent_account, name))
            for name in ("log_error", "log_success", "log_user_action", "logger")
        }
        yield mocks


def add_agent(db, password: str, role: str = Role.AGENT.value) -> Users:
    agent = Users(
        username="agent",
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(agent)
    db.commit()
    return agent


def stored_hash(db) -> str:
    return db.query(Users).filter_by(username="agent").one().hashed_password


class TestANewInstall:
    def test_the_agent_account_gets_the_password_from_the_environment(self, session, logs):
        assert agent_account.ensure_agent_account(session, "agent", GENERATED) == "created"
        agent = session.query(Users).filter_by(username="agent").one()
        assert agent.role == Role.AGENT.value
        assert verify_password(GENERATED, agent.hashed_password)

    @pytest.mark.parametrize("password", ["", "   ", "agent", " agent "])
    def test_an_empty_or_shipped_password_creates_no_account(self, session, logs, password):
        assert agent_account.ensure_agent_account(session, "agent", password) == "refused"
        assert session.query(Users).count() == 0
        message = logs["log_error"].call_args.args[1]
        assert "SUPER_AGENT_PASSWORD" in message
        assert "src/infra/.env" in message
        assert "docker compose up -d mas agent" in message


class TestAnUpgradeFromAnInstallThatStillHasTheShippedAgentPassword:
    def test_the_shipped_password_is_replaced_by_the_one_in_the_environment(
        self, session, logs
    ):
        add_agent(session, "agent")

        assert agent_account.ensure_agent_account(session, "agent", GENERATED) == "replaced"

        assert verify_password(GENERATED, stored_hash(session))
        assert not verify_password("agent", stored_hash(session))
        logs["log_user_action"].assert_called_once()
        assert logs["log_user_action"].call_args.args[0] == "REPLACE_SHIPPED_AGENT_PASSWORD"

    @pytest.mark.parametrize("password", ["", "agent"])
    def test_a_shipped_environment_value_does_not_preserve_the_shipped_password(
        self, session, logs, password
    ):
        add_agent(session, "agent")
        before = stored_hash(session)

        assert agent_account.ensure_agent_account(session, "agent", password) == "shipped"

        assert stored_hash(session) == before


class TestAnUpgradeWhereTheAgentChangedThePassword:
    def test_a_password_set_in_the_environment_is_left_as_it_is(self, session, logs):
        add_agent(session, CHOSEN)
        before = stored_hash(session)

        assert agent_account.ensure_agent_account(session, "agent", CHOSEN) == "matches"

        assert stored_hash(session) == before

    @pytest.mark.parametrize("environment", ["agent", GENERATED, ""])
    def test_a_password_changed_in_horus_is_never_touched(self, session, logs, environment):
        add_agent(session, CHOSEN)
        before = stored_hash(session)

        assert agent_account.ensure_agent_account(session, "agent", environment) == "differs"

        assert stored_hash(session) == before
        assert verify_password(CHOSEN, stored_hash(session))
        assert "SUPER_AGENT_PASSWORD" in logs["logger"].warning.call_args.args[0]

    def test_an_existing_admin_account_is_restricted_without_changing_its_password(
        self, session, logs
    ):
        add_agent(session, CHOSEN, role=Role.ADMIN.value)
        before = stored_hash(session)

        assert agent_account.ensure_agent_account(session, "agent", GENERATED) == "differs"

        account = session.query(Users).filter_by(username="agent").one()
        assert account.role == Role.AGENT.value
        assert account.hashed_password == before
        assert verify_password(CHOSEN, account.hashed_password)


class TestTheCommandTheInstallerRuns:
    def test_it_prints_the_outcome_and_never_the_password(self, session, logs, capsys):
        settings = MagicMock(super_agent_username="agent", super_agent_password=GENERATED)
        session.close = MagicMock()

        with patch.object(agent_account, "SessionLocal", return_value=session), \
                patch.object(agent_account, "settings", settings), \
                patch.object(agent_account, "ensure_agent_account", return_value="matches") as ensure:
            assert agent_account.main() == 0

        printed = capsys.readouterr().out
        assert printed.splitlines()[-1] == "agent-account: matches"
        assert GENERATED not in printed
        ensure.assert_called_once_with(session, "agent", GENERATED)
        session.close.assert_called_once()
