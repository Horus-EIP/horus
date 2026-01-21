
import pytest
from fastapi import HTTPException
from starlette import status
from unittest.mock import MagicMock, patch

from auth.permissions import Permission, Role, check_permission, ROLE_PERMISSION
from auth.auth_tool_functions import PermissionChecker

class TestPermissions:
    def test_role_permission_mapping(self):
        """Test that roles have the expected permissions."""
        assert Permission.USER_CREATE in ROLE_PERMISSION[Role.ADMIN]
        assert Permission.USER_READ in ROLE_PERMISSION[Role.ADMIN]
        assert Permission.USER_READ in ROLE_PERMISSION[Role.MANAGER]
        assert Permission.TASK_READ in ROLE_PERMISSION[Role.USER]
        
        # Check that USER role doesn't have ADMIN permissions
        assert Permission.USER_DELETE not in ROLE_PERMISSION[Role.USER]

    def test_check_permission_success(self):
        """Test check_permission returns True for valid role/permission."""
        assert check_permission("admin", Permission.USER_DELETE) is True
        assert check_permission("manager", Permission.USER_READ) is True
        assert check_permission("user", Permission.TASK_READ) is True

    def test_check_permission_failure(self):
        """Test check_permission returns False for invalid role/permission."""
        assert check_permission("user", Permission.USER_DELETE) is False
        assert check_permission("manager", Permission.USER_DELETE) is False
        assert check_permission("unknown_role", Permission.USER_READ) is False

    def test_check_permission_case_insensitive(self):
        """Test check_permission handles role case insensitivity."""
        assert check_permission("ADMIN", Permission.USER_DELETE) is True
        assert check_permission("Admin", Permission.USER_DELETE) is True

class TestPermissionChecker:
    def test_permission_checker_success(self):
        """Test PermissionChecker allows access when user has permission."""
        checker = PermissionChecker(Permission.USER_READ)
        user = {"username": "test", "role": "admin"}
        
        result = checker(user)
        assert result == user

    def test_permission_checker_denied(self):
        """Test PermissionChecker raises 403 when user lacks permission."""
        checker = PermissionChecker(Permission.USER_DELETE)
        user = {"username": "test", "role": "user"}
        
        with pytest.raises(HTTPException) as exc_info:
            checker(user)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc_info.value.detail == "Insufficient permissions"

    def test_permission_checker_invalid_role(self):
        """Test PermissionChecker raises 403 for invalid role."""
        checker = PermissionChecker(Permission.USER_READ)
        user = {"username": "test", "role": "invalid_role"}
        
        with pytest.raises(HTTPException) as exc_info:
            checker(user)
            
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
