"""
mock_store.py
-------------
This module provides a mock knowledge store function that simulates data retrieval by returning detailed dummy data for a given query.
It is used during development to test the AI model integration.
"""

from typing import Dict, Any


def mock_knowledge_store(query: str) -> Dict[str, Any]:
    """
    Simulated knowledge store function returning detailed dummy data.

    Args:
        query: The search query.

    Returns:
        A dict with detailed dummy data simulating a sales analysis report.
    """
    detailed_data = (
        f"Sales Analysis Report for '{query}':\n\n"
        "In Q1 2025, the company experienced a revenue growth of 15% compared to Q4 2024. "
        "Key regions such as North America, Europe, and Asia-Pacific showed significant improvements, "
        "with North America leading a 20% increase in sales volume. Marketing campaigns contributed to a "
        "25% rise in new customer acquisition and enhanced brand engagement. Operational efficiencies improved "
        "due to supply chain optimizations and cost reductions. A strategic shift towards premium products resulted "
        "in a higher profit margin. Investments in technology and data analytics have enabled more informed decision-making "
        "for sustained future growth."
    )
    return {
        "query": query,
        "data": detailed_data
    }
