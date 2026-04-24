"""Demo-visual logger — noisy, bordered output used during live walkthroughs."""

from core.logger import get_logger

logger = get_logger("task_tool_functions")


def pretty_log(msg: str, icon: str = "ℹ️"):
    """Log a message designed to be visible and clean for demo videos."""
    border = "=" * 60
    print(f"\n{border}\n {icon}  {msg}\n{border}\n")
    logger.info(f"[DEMO-VISUAL] {icon} {msg}")
