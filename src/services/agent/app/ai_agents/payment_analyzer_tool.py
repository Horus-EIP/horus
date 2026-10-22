import json
import logging
from typing import Any

from langchain.tools import BaseTool

logger = logging.getLogger(__name__)


class PaymentAnalyzerTool(BaseTool):
    """
    Tool for performing financial analysis on structured payment data.

    Capabilities:
    - total: Calculate sum of payments by currency.
    - average: Calculate average payment amount by currency.
    - by_payee: Group payments by payee and sum amounts.
    - forecast: Simple projection for next month (+10%).
    """

    name: str = "payment_analytics_tool"
    description: str = (
        "Use this tool to perform financial analysis on a list of payment data. "
        "Supported analysis_types: 'total', 'average', 'by_payee', 'forecast'."
    )

    def _run(self, payments_data: str, analysis_type: str) -> str:
        """
        Main entry point for the tool.

        Args:
            payments_data (str): JSON string representing a list of payment dictionaries.
            analysis_type (str): The type of analysis to perform ('total', 'average', 'by_payee', 'forecast').

        Returns:
            str: The result of the analysis as a string.

        Raises:
            ValueError: If JSON is invalid or analysis type is unsupported.
        """
        logger.info(f"Starting Payment Analysis. Type: {analysis_type}")

        try:
            payments = json.loads(payments_data)
            if not isinstance(payments, list):
                logger.error("Input data is not a list")
                raise ValueError("Input payment data must be a JSON list")
        except json.JSONDecodeError as e:
            logger.error(f"JSON Decode Error: {e}")
            raise ValueError("Invalid JSON format for payments_data")

        logger.debug(f"Loaded {len(payments)} payment records")

        if analysis_type == "total":
            return self._calculate_total(payments)

        elif analysis_type == "average":
            return self._calculate_average(payments)

        elif analysis_type == "by_payee":
            return self._get_payee_breakdown(payments)

        elif analysis_type == "forecast":
            return self._predict_next_month(payments)

        else:
            logger.warning(f"Unknown analysis type requested: {analysis_type}")
            raise ValueError(
                f"Invalid analysis type: {analysis_type}. Supported: total, average, by_payee, forecast"
            )

    def _arun(self, payments_data: str, analysis_type: str) -> str:
        raise NotImplementedError("Async analysis not implemented.")

    def _calculate_total(self, data: list[dict[str, Any]]) -> str:
        """
        Calculates the total amount per currency.

        Args:
            data (List[Dict[str, Any]]): List of payment records.

        Returns:
            str: Formatted string regarding total amounts.
        """
        logger.info("Calculating total amounts...")
        total_eur = 0.0
        total_usd = 0.0
        msg_parts = []

        if not data:
            return "No data to calculate total"

        for element in data:
            amount = element.get("amount")
            currency = element.get("currency", "UNKNOWN")

            if amount is not None:
                try:
                    val = float(amount)
                    if currency == "EUR":
                        total_eur += val
                    elif currency == "USD":
                        total_usd += val
                    else:
                        # Log or handle other currencies if needed
                        pass
                except (ValueError, TypeError):
                    logger.debug(f"Skipping invalid amount value: {amount}")
                    continue

        if total_eur > 0:
            msg_parts.append(f"Total amount EUR: {round(total_eur, 2)}")
        if total_usd > 0:
            msg_parts.append(f"Total amount USD: {round(total_usd, 2)}")

        if not msg_parts:
            return "No valid EUR or USD amounts found to calculate total."

        return " | ".join(msg_parts)

    def _calculate_average(self, data: list[dict[str, Any]]) -> str:
        """
        Calculates the average payment amount per currency.

        Args:
            data (List[Dict[str, Any]]): List of payment records.

        Returns:
            str: Formatted string regarding average amounts.
        """
        logger.info("Calculating average amounts...")
        values_eur = []
        values_usd = []

        if not data:
            return "No data to calculate average"

        for element in data:
            amount = element.get("amount")
            currency = element.get("currency", "UNKNOWN")

            if amount is not None:
                try:
                    val = float(amount)
                    if currency == "EUR":
                        values_eur.append(val)
                    elif currency == "USD":
                        values_usd.append(val)
                except (ValueError, TypeError):
                    continue

        results = []
        if values_eur:
            avg_eur = sum(values_eur) / len(values_eur)
            results.append(f"Average EUR: {round(avg_eur, 2)}")

        if values_usd:
            avg_usd = sum(values_usd) / len(values_usd)
            results.append(f"Average USD: {round(avg_usd, 2)}")

        if not results:
            return "No valid amounts to calculate average"

        return " | ".join(results)

    def _get_payee_breakdown(self, data: list[dict[str, Any]]) -> str:
        """
        Aggregates payment amounts by Payee (grouped by currency).

        Args:
            data (List[Dict[str, Any]]): List of payment records.

        Returns:
            str: JSON string of the breakdown.
        """
        logger.info("Generating payee breakdown...")
        if not data:
            return "No data to calculate payee breakdown"

        breakdown = {}

        for element in data:
            # Determine Payee Name
            payee = element.get("payee")
            if not payee:
                # Fallback to context or Unknown
                context_val = element.get("context")
                payee = context_val.strip() if context_val else "Unknown Payee"

            currency = element.get("currency", "UNKNOWN")
            key = f"{payee} ({currency})"

            try:
                amount = float(element.get("amount", 0))
            except (ValueError, TypeError):
                continue

            breakdown[key] = breakdown.get(key, 0.0) + amount

        # Round values for display
        final_breakdown = {k: round(v, 2) for k, v in breakdown.items()}
        return json.dumps(final_breakdown, indent=2)

    def _predict_next_month(self, data: list[dict[str, Any]]) -> str:
        """
        Predicts next month's spending based on a simple +10% heuristic.

        Args:
            data (List[Dict[str, Any]]): List of payment records.

        Returns:
            str: Forecast string.
        """
        logger.info("Calculating forecast (current + 10%)...")
        if not data:
            return "No data to calculate forecast"

        total_eur = 0.0
        total_usd = 0.0

        for element in data:
            amount = element.get("amount")
            currency = element.get("currency")

            if amount is not None:
                try:
                    val = float(amount)
                    if currency == "EUR":
                        total_eur += val
                    elif currency == "USD":
                        total_usd += val
                except (ValueError, TypeError):
                    continue

        projections = []

        if total_eur > 0:
            res = total_eur * 1.10
            projections.append(f"{round(res, 2)} EUR")

        if total_usd > 0:
            res = total_usd * 1.10
            projections.append(f"{round(res, 2)} USD")

        if not projections:
            return "No valid amounts to calculate forecast"

        final_res = " | ".join(projections)
        return f"Projected spend next month (Current + 10%): {final_res}"
