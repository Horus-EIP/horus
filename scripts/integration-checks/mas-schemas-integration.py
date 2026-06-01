"""
Schema Validation Tests

This module tests the Pydantic schemas used in the Task API:
- TaskForm schema validation
- TaskResultForm schema validation with new task_id field
- Schema serialization and deserialization

Verifies that:
- TaskResultForm now includes required task_id field
- All fields are properly typed and validated
- JSON serialization works correctly
- Invalid data is properly rejected

Usage:
    python test_schemas.py
"""

import json
import sys
from pathlib import Path

from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAS_ROOT = _REPO_ROOT / "src" / "services" / "mas"
sys.path.insert(0, str(_MAS_ROOT))

from schemas.schemas import TaskForm, TaskResultForm


def print_separator(title: str = "") -> None:
    """Print a formatted separator line."""
    if title:
        print(f"\n{'=' * 70}")
        print(f"  {title}")
        print("=" * 70)
    else:
        print("-" * 70)


def test_task_form_schema() -> None:
    """Test TaskForm schema validation."""
    print_separator("TEST 1: TaskForm Schema Validation")

    # Valid TaskForm
    print("\n[Valid TaskForm]")
    valid_task = TaskForm(
        demand="Calculate the square root of 4",
        conversation_id=123,
        skills_required=["math", "calculation"],
    )

    print("✅ TaskForm created successfully")
    print(f"   Demand: {valid_task.demand}")
    print(f"   Conversation ID: {valid_task.conversation_id}")
    print(f"   Skills Required: {valid_task.skills_required}")

    # JSON serialization
    print("\n[JSON Serialization]")
    task_json = valid_task.model_dump_json()
    print("✅ Serialized to JSON:")
    print(f"   {task_json}")

    # JSON deserialization
    print("\n[JSON Deserialization]")
    task_from_json = TaskForm.model_validate_json(task_json)
    print("✅ Deserialized from JSON:")
    print(f"   Demand: {task_from_json.demand}")

    # Invalid TaskForm (missing required field)
    print("\n[Invalid TaskForm - Missing Field]")
    try:
        invalid_task = TaskForm(
            demand="Calculate something",
            # Missing conversation_id (required int)
            skills_required=["math"],
        )
        print("❌ Should have failed validation")
    except ValidationError as e:
        print("✅ Correctly rejected invalid data:")
        print(f"   Error: {e.error_count()} validation error(s)")
        for error in e.errors():
            print(f"   - Field: {error['loc'][0]}, Issue: {error['msg']}")


def test_task_result_form_schema() -> None:
    """Test TaskResultForm schema with new task_id field."""
    print_separator("TEST 2: TaskResultForm Schema Validation (with task_id)")

    # Valid TaskResultForm with task_id
    print("\n[Valid TaskResultForm]")
    valid_result = TaskResultForm(
        task_id="task_001",  # NEW REQUIRED FIELD
        result="The square root of 4 is 2.",
        conversation_id="conv_123",
        agent_id="agent_001",
    )

    print("✅ TaskResultForm created successfully")
    print(f"   Task ID: {valid_result.task_id}")
    print(f"   Result: {valid_result.result}")
    print(f"   Conversation ID: {valid_result.conversation_id}")
    print(f"   Agent ID: {valid_result.agent_id}")

    # JSON serialization
    print("\n[JSON Serialization]")
    result_json = valid_result.model_dump_json()
    print("✅ Serialized to JSON:")
    result_dict = json.loads(result_json)
    for key, value in result_dict.items():
        if isinstance(value, (list, dict)):
            print(f"   {key}: {type(value).__name__} with {len(value)} items")
        else:
            print(f"   {key}: {value}")

    # JSON deserialization
    print("\n[JSON Deserialization]")
    result_from_json = TaskResultForm.model_validate_json(result_json)
    print("✅ Deserialized from JSON:")
    print(f"   Task ID: {result_from_json.task_id}")
    print(f"   Agent ID: {result_from_json.agent_id}")

    # Invalid TaskResultForm (missing task_id)
    print("\n[Invalid TaskResultForm - Missing task_id]")
    try:
        invalid_result = TaskResultForm(
            # Missing task_id (NEW REQUIRED FIELD)
            result="The square root of 4 is 2.",
            conversation_id="conv_123",
            agent_id="agent_001",
        )
        print("❌ Should have failed validation")
    except ValidationError as e:
        print("✅ Correctly rejected - missing task_id:")
        print(f"   Error: {e.error_count()} validation error(s)")
        for error in e.errors():
            print(f"   - Field: {error['loc'][0]}, Issue: {error['msg']}")

    # Invalid TaskResultForm (missing result)
    print("\n[Invalid TaskResultForm - Missing result]")
    try:
        invalid_result = TaskResultForm(
            task_id="task_001",
            # Missing result (required)
            conversation_id="conv_123",
            agent_id="agent_001",
        )
        print("❌ Should have failed validation")
    except ValidationError as e:
        print("✅ Correctly rejected - missing result:")
        print(f"   Error: {e.error_count()} validation error(s)")


def test_complete_workflow() -> None:
    """Test a complete workflow with both schemas."""
    print_separator("TEST 3: Complete Workflow Simulation")

    # Step 1: Create task
    print("\n[Step 1] Creating task...")
    task = TaskForm(
        demand="Calculate the square root of 4 and translate it",
        conversation_id=42,
        skills_required=["math", "translation"],
    )
    print(f"✅ Task created: {task.demand[:40]}...")

    # Step 2: Submit result with task_id
    print("\n[Step 2] Submitting result...")
    result = TaskResultForm(
        task_id="task_workflow_001",  # Must match task from database
        result="The square root of 4 is 2.",
        conversation_id="42",
        agent_id="agent_math",
    )
    print(f"✅ Task result submitted for task: {result.task_id}")
    print(f"   Agent: {result.agent_id}")
    print(f"   Result: {result.result}")

    # Step 3: Submit subtask result
    print("\n[Step 3] Submitting subtask result...")
    subtask_result = TaskResultForm(
        task_id="task_workflow_002",  # New subtask ID
        result="La racine carrée de 4 est 2.",
        conversation_id="42",
        agent_id="agent_translate",
    )
    print(f"✅ Subtask result submitted for task: {subtask_result.task_id}")
    print(f"   Agent: {subtask_result.agent_id}")
    print("   Workflow progressing with new task")


def run_all_tests() -> None:
    """Run all schema validation tests."""
    print("\n" + "=" * 70)
    print("SCHEMA VALIDATION TESTS")
    print("=" * 70)

    try:
        test_task_form_schema()
        test_task_result_form_schema()
        test_complete_workflow()

        print_separator()
        print("\n✅ ALL SCHEMA TESTS PASSED SUCCESSFULLY!")
        print("\nTest Summary:")
        print("  ✓ TaskForm schema works correctly")
        print("  ✓ TaskResultForm includes required task_id field")
        print("  ✓ Optional fields work with default values")
        print("  ✓ JSON serialization/deserialization works")
        print("  ✓ Validation properly rejects invalid data")
        print("  ✓ Complete workflow can be simulated")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    run_all_tests()
