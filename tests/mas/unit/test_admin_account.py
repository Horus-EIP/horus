from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.models  # noqa: F401
from auth.auth_tool_functions import bcrypt_context
from auth.permissions import Role
from db import admin_account, init_setup
from db.database import Base
from db.models import Users

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
            name: stack.enter_context(patch.object(admin_account, name))
            for name in ("log_error", "log_success", "log_user_action", "logger")
        }
        yield mocks


def logged_text(logs) -> str:
    calls = [
        *logs["log_error"].call_args_list,
        *logs["log_success"].call_args_list,
        *logs["log_user_action"].call_args_list,
        *logs["logger"].info.call_args_list,
        *logs["logger"].warning.call_args_list,
    ]
    return " ".join(str(call) for call in calls)


def add_admin(db, password: str) -> Users:
    admin = Users(
        username="admin", hashed_password=bcrypt_context.hash(password), role=Role.ADMIN.value
    )
    db.add(admin)
    db.commit()
    return admin


def stored_hash(db) -> str:
    return db.query(Users).filter_by(username="admin").one().hashed_password


class TestANewInstall:
    def test_the_admin_account_gets_the_password_from_the_environment(self, session, logs):
        assert admin_account.ensure_admin_account(session, "admin", GENERATED) == "created"
        admin = session.query(Users).filter_by(username="admin").one()
        assert admin.role == Role.ADMIN.value
        assert bcrypt_context.verify(GENERATED, admin.hashed_password)

    @pytest.mark.parametrize("password", ["", "   ", "admin", " admin "])
    def test_an_empty_or_shipped_password_creates_no_account(self, session, logs, password):
        assert admin_account.ensure_admin_account(session, "admin", password) == "refused"
        assert session.query(Users).count() == 0
        message = logs["log_error"].call_args.args[1]
        assert "SUPER_USER_PASSWORD" in message
        assert "src/infra/.env" in message
        assert "docker compose up -d mas agent" in message


class TestAnUpgradeFromAnInstallThatStillHasAdmin:
    def test_the_shipped_password_is_replaced_by_the_one_in_the_environment(self, session, logs):
        add_admin(session, "admin")

        assert admin_account.ensure_admin_account(session, "admin", GENERATED) == "replaced"

        assert bcrypt_context.verify(GENERATED, stored_hash(session))
        assert not bcrypt_context.verify("admin", stored_hash(session))
        logs["log_user_action"].assert_called_once()

    def test_a_second_start_finds_the_account_already_on_the_new_password(self, session, logs):
        add_admin(session, "admin")
        admin_account.ensure_admin_account(session, "admin", GENERATED)

        assert admin_account.ensure_admin_account(session, "admin", GENERATED) == "matches"

    def test_an_environment_still_on_admin_keeps_it_and_says_how_to_change_it(self, session, logs):
        add_admin(session, "admin")
        before = stored_hash(session)

        assert admin_account.ensure_admin_account(session, "admin", "admin") == "shipped"

        assert stored_hash(session) == before
        assert "SUPER_USER_PASSWORD" in logs["log_error"].call_args.args[1]


class TestAnUpgradeWhereTheAdminChangedThePassword:
    def test_a_password_set_in_the_environment_is_left_as_it_is(self, session, logs):
        add_admin(session, CHOSEN)
        before = stored_hash(session)

        assert admin_account.ensure_admin_account(session, "admin", CHOSEN) == "matches"

        assert stored_hash(session) == before

    @pytest.mark.parametrize("environment", ["admin", GENERATED, ""])
    def test_a_password_changed_in_horus_is_never_touched(self, session, logs, environment):
        add_admin(session, CHOSEN)
        before = stored_hash(session)

        assert admin_account.ensure_admin_account(session, "admin", environment) == "differs"

        assert stored_hash(session) == before
        assert bcrypt_context.verify(CHOSEN, stored_hash(session))
        assert "SUPER_USER_PASSWORD" in logs["logger"].warning.call_args.args[0]


class TestThePasswordStaysOutOfTheLogs:
    @pytest.mark.parametrize("stored", [None, "admin", CHOSEN])
    def test_no_outcome_logs_the_password(self, session, logs, stored):
        if stored is not None:
            add_admin(session, stored)

        admin_account.ensure_admin_account(session, "admin", GENERATED)

        assert GENERATED not in logged_text(logs)
        assert CHOSEN not in logged_text(logs)


class TestTheCommandTheInstallerRuns:
    def test_it_prints_the_outcome_and_never_the_password(self, session, logs, capsys):
        add_admin(session, "admin")
        settings = MagicMock(super_user_username="admin", super_user_password=GENERATED)
        session.close = MagicMock()

        with (
            patch.object(admin_account, "SessionLocal", return_value=session),
            patch.object(admin_account, "settings", settings),
        ):
            assert admin_account.main() == 0

        printed = capsys.readouterr().out
        assert printed.splitlines()[-1] == "admin-account: replaced"
        assert GENERATED not in printed
        session.close.assert_called_once()

    def test_an_unhashed_value_counts_as_another_password(self):
        assert not admin_account.has_password(MagicMock(hashed_password=MagicMock()), "admin")
        assert not admin_account.has_password(MagicMock(hashed_password="not-a-hash"), "admin")


def test_startup_checks_both_accounts_with_the_configured_values():
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["users"]
    engine = MagicMock()
    engine.dialect.name = "sqlite"
    settings = MagicMock(
        super_user_username="root",
        super_user_password=GENERATED,
        super_agent_username="agent",
        super_agent_password=CHOSEN,
    )
    with ExitStack() as stack:
        stack.enter_context(patch.object(init_setup, "run_migrations", return_value=True))
        stack.enter_context(patch.object(init_setup, "engine", engine))
        stack.enter_context(patch("sqlalchemy.inspect", return_value=inspector))
        stack.enter_context(
            patch.object(init_setup, "create_critical_logs_table", return_value=True)
        )
        session = MagicMock()
        stack.enter_context(patch.object(init_setup, "SessionLocal", return_value=session))
        stack.enter_context(patch("db.seed_agents.seed_manager_agent"))
        stack.enter_context(patch.object(init_setup, "settings", settings))
        ensure = stack.enter_context(patch.object(init_setup, "ensure_admin_account"))
        ensure_agent = stack.enter_context(patch.object(init_setup, "ensure_agent_account"))
        init_setup.init_db()

    ensure.assert_called_once_with(session, "root", GENERATED)
    ensure_agent.assert_called_once_with(session, "agent", CHOSEN)
