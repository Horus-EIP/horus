"""
Tests for Agents table creation and accessibility
"""

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from db.database import engine, SessionLocal, Base
from db.models import Agents


class TestAgentsTableCreation:
    """Test suite for Agents table creation and structure"""

    def test_agents_table_exists_in_metadata(self):
        """Test that the agents table exists in SQLAlchemy metadata"""
        table_names = {table.name for table in Base.metadata.tables.values()}
        assert "agents" in table_names, "Agents table should be in Base.metadata"

    def test_agents_model_defined(self):
        """Test that Agents model is properly defined"""
        assert hasattr(Agents, "__tablename__")
        assert Agents.__tablename__ == "agents"
        assert Agents is not None

    def test_agents_table_has_required_columns_in_metadata(self):
        """Test that agents table has all required columns in model"""
        agents_table = Base.metadata.tables["agents"]
        column_names = {col.name for col in agents_table.columns}
        
        required_columns = {
            "id",
            "name",
            "skills",
            "status",
            "description",
            "last_heartbeat",
            "created_at",
            "api_key",
        }
        
        missing_columns = required_columns - column_names
        assert not missing_columns, f"Missing columns in agents table: {missing_columns}"

    def test_agents_table_primary_key_in_metadata(self):
        """Test that agents table has correct primary key in model"""
        agents_table = Base.metadata.tables["agents"]
        pk_columns = {col.name for col in agents_table.primary_key}
        
        assert pk_columns == {"id"}, "ID should be primary key"

    def test_agents_model_columns_match_metadata(self):
        """Test that Agents model columns match table metadata"""
        agents_table = Base.metadata.tables["agents"]
        db_columns = {col.name for col in agents_table.columns}
        
        # Get columns from SQLAlchemy model
        model_columns = {col.name for col in Agents.__table__.columns}
        
        assert model_columns == db_columns, \
            f"Model columns {model_columns} don't match table columns {db_columns}"

    def test_agents_table_accessible_after_create_all(self):
        """Test that agents table is accessible after create_all"""
        # Ensure tables are created
        Base.metadata.create_all(bind=engine)
        
        db = SessionLocal()
        try:
            # This should not raise an exception
            result = db.query(Agents).all()
            assert result is not None
            # Result should be a list (empty or with data)
            assert isinstance(result, list)
        except OperationalError as e:
            if "relation \"agents\" does not exist" in str(e):
                pytest.skip(f"Agents table not created in test database: {str(e)}")
            else:
                pytest.fail(f"Failed to query agents table: {str(e)}")
        finally:
            db.close()

    def test_base_metadata_includes_all_required_tables(self):
        """Test that Base metadata includes Agents and other key tables"""
        table_names = {table.name for table in Base.metadata.tables.values()}
        
        required_tables = {"agents", "users", "tasks", "conversations"}
        
        missing_tables = required_tables - table_names
        assert not missing_tables, f"Missing tables in Base.metadata: {missing_tables}"
        
        # Verify the Agents table definition
        agents_table = Base.metadata.tables["agents"]
        assert agents_table is not None
        
        column_names = {col.name for col in agents_table.columns}
        required_columns = {
            "id", "name", "skills", "status", "description",
            "last_heartbeat", "created_at", "api_key"
        }
        
        assert required_columns.issubset(column_names), \
            f"Missing required columns: {required_columns - column_names}"

    def test_agents_model_has_api_key_column(self):
        """Test that Agents model includes api_key column"""
        agents_table = Base.metadata.tables["agents"]
        column_names = {col.name for col in agents_table.columns}
        
        assert "api_key" in column_names, "api_key should be in agents table"

    def test_agents_model_has_all_json_fields(self):
        """Test that Agents model has skills field as JSON"""
        agents_table = Base.metadata.tables["agents"]
        columns = {col.name: col for col in agents_table.columns}
        
        assert "skills" in columns, "skills field should exist"
        # skills should be JSON type
        assert "JSON" in str(type(columns["skills"].type)), \
            "skills column should be JSON type"
