"""Facade re-exporting the MAS task pipeline helpers.

The implementation is split across:

- :mod:`tasks.prompts` — LLM prompt templates + JSON-fence stripper
- :mod:`tasks.decomposition` — planner, agent selection, action-list builders
- :mod:`tasks.task_crud` — DB-bound task lifecycle helpers
- :mod:`tasks.demo_log` — ``pretty_log`` visual helper

This module keeps the original import path working so callers can do
``from tasks.task_tool_functions import <name>`` unchanged.
"""

from tasks.decomposition import (
    aggregate_results,
    build_action_list,
    build_subtask_list,
    decompose_task,
    select_agent_for_task,
    sort_subtasks_by_dependency,
)
from tasks.demo_log import pretty_log
from tasks.prompts import (
    clean_json_output,
    get_decomposition_prompt,
    get_prompt,
    get_prompt_final_answer_generation,
)
from tasks.task_crud import (
    _get_all_tasks_internal,
    get_tasks_in_progress,
    insert_new_task,
    interrupt_task,
    validating_task_results,
)

__all__ = [
    "aggregate_results",
    "build_action_list",
    "build_subtask_list",
    "clean_json_output",
    "decompose_task",
    "get_decomposition_prompt",
    "get_prompt",
    "get_prompt_final_answer_generation",
    "get_tasks_in_progress",
    "insert_new_task",
    "interrupt_task",
    "pretty_log",
    "select_agent_for_task",
    "sort_subtasks_by_dependency",
    "validating_task_results",
    "_get_all_tasks_internal",
]
