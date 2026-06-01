"""Smoke tests for ``build_where_clause`` (hermetic).

The function lives in ``app.chroma_db.services.file_service`` which has a
circular import with ``app.chroma_db.__init__`` when imported directly
in tests. The conftest mocks chromadb itself but can't easily defeat
that circular chain. We keep this file as a placeholder + skip with a
clear reason; the function is exercised end-to-end by the API tests in
``tests/knowledge_store/api/test_store_routes.py``.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(
    reason=(
        "Direct import of build_where_clause triggers the circular import "
        "in app.chroma_db.__init__ -> services -> file_service -> chroma_db. "
        "The function is covered via the /smart-search route tests in "
        "tests/knowledge_store/api/test_store_routes.py. Re-enable once the "
        "source-side circular import is fixed in app/chroma_db/__init__.py."
    )
)
def test_build_where_clause_placeholder():
    pass
