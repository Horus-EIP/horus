# Regression log

Every regression gets a failing test first, a docstring saying what broke, how the test checks it and when it was found and fixed, and a row in this file.

| ID | Backlog | What broke | Found in | Regression test (file::name) | Fix commit | Status |
|---|---|---|---|---|---|---|
| F25 | B-48 | `/tasks/new` and the chat file picker crashed ("Duplicate options are not supported") when two knowledge-store documents shared a filename, because the picker used the title as the option value | ATP v7, 18/09/2026 | `tests/mas/api/test_tasks_routes_coverage.py::TestAttachedKnowledgeStoreRefs::test_f25_same_name_documents_dispatch_with_their_doc_ids`, `::TestAttachedKnowledgeStoreRefs::test_f25_filename_only_ref_still_dispatches`, `::TestBuildFilesPayload::test_f25_blank_doc_id_is_not_forwarded`; `src/services/web-client/__tests__/file-attachments.test.tsx` "regression F25 duplicate knowledge-store file names" | `0b93375` | Fixed on `Sprint#1_September2026_Tek5`, in review |
| F28 | B-49 | Total Tasks in the task stats counted subtasks, so it disagreed with the Recent tasks list; the stats also had an always-zero `timeout` count | ATP v7, 18/09/2026 | `tests/mas/api/test_tasks_routes_coverage.py::TestQueueStatsHelper::test_f28_queue_stats_count_root_tasks_not_subtasks` | `ff82920` | Fixed on `Sprint#1_September2026_Tek5`, in review |
| F7 | B-50 | Back after logout showed the logged-in view again: the navbar logged out without the auth context, the login redirect kept the protected page in the history, and a page restored from the back-forward cache did not check the session | ATP v7, 18/09/2026 | `src/services/web-client/__tests__/navbar-logout.test.tsx` "regression F7 navbar logout", "regression F7 back-forward cache restore" | `905cedb` | Fixed on `Sprint#1_September2026_Tek5`, in review |

For these three the test and the fix are in the same commit, so the history cannot show the test failing first. Run them with `pytest -m regression` for MAS, and by their `describe` names in the web client.
