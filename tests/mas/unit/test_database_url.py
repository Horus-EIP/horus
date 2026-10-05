from __future__ import annotations

import configparser
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy
from packaging.requirements import Requirement
from sqlalchemy.engine import make_url

from core import config

MAS_ROOT = Path(__file__).resolve().parents[3] / "src" / "services" / "mas"
PSYCOPG2_URL_SCHEME = "postgresql+psycopg2"
REQUIREMENT_FILES = ("requirements.txt", "requirements-cpu.txt", "requirements-gpu.txt")

POSTGRES_SETTINGS = {
    "postgres_user": "horus",
    "postgres_password": "secret",
    "postgres_db": "mas_db",
    "db_host": "postgres",
    "db_port": 5432,
}


def listed_requirements(file_name: str) -> list[Requirement]:
    found: list[Requirement] = []
    for raw in (MAS_ROOT / file_name).read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if line.startswith("-r "):
            found.extend(listed_requirements(line.split(None, 1)[1]))
        elif line and not line.startswith(("#", "-")):
            found.append(Requirement(line))
    return found


def requirement(file_name: str, project: str) -> Requirement:
    for parsed in listed_requirements(file_name):
        if parsed.name.lower() == project.lower():
            return parsed
    raise AssertionError(f"{file_name} does not list {project}")


@pytest.fixture
def database_outside_test_mode(monkeypatch):
    monkeypatch.delenv("TEST_MODE", raising=False)
    for name, value in POSTGRES_SETTINGS.items():
        monkeypatch.setattr(config.settings, name, value, raising=False)
    spec = importlib.util.spec_from_file_location(
        "database_outside_test_mode", MAS_ROOT / "db" / "database.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    module.engine.dispose()


def test_the_engine_loads_psycopg2_whatever_sqlalchemy_maps_postgresql_to(
    database_outside_test_mode,
):
    assert database_outside_test_mode.engine.dialect.driver == "psycopg2"


def test_the_database_url_names_the_psycopg2_driver(database_outside_test_mode):
    url = make_url(database_outside_test_mode.URL_DATABASE)

    assert url.drivername == PSYCOPG2_URL_SCHEME
    assert (url.username, url.host, url.port, url.database) == (
        "horus",
        "postgres",
        5432,
        "mas_db",
    )


def test_the_alembic_ini_fallback_url_names_the_psycopg2_driver():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(MAS_ROOT / "db" / "alembic.ini", encoding="utf-8")

    assert make_url(parser["alembic"]["sqlalchemy.url"]).drivername == PSYCOPG2_URL_SCHEME


@pytest.mark.parametrize("file_name", REQUIREMENT_FILES)
def test_both_requirement_files_install_psycopg2(file_name):
    assert requirement(file_name, "psycopg2-binary").specifier


@pytest.mark.parametrize("file_name", REQUIREMENT_FILES)
def test_sqlalchemy_is_held_to_the_release_range_the_suite_runs_on(file_name):
    specifier = requirement(file_name, "SQLAlchemy").specifier

    assert any(spec.operator in ("<", "<=", "==", "~=") for spec in specifier), str(specifier)
    assert specifier.contains(sqlalchemy.__version__), (str(specifier), sqlalchemy.__version__)


def test_both_requirement_files_allow_the_same_sqlalchemy_releases():
    assert len({str(requirement(name, "SQLAlchemy").specifier) for name in REQUIREMENT_FILES}) == 1
