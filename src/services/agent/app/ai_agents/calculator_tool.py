"""
calculator_tool.py
-------------------
Safe arithmetic calculator tool implementing the Tool interface.
"""

from __future__ import annotations

import ast
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


class CalculatorTool:
    name = "calculate"

    _ALLOWED_BINARY_OPS = (
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
    )
    _ALLOWED_UNARY_OPS = (ast.UAdd, ast.USub)

    _ALLOWED_FUNCS = {
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "pow": math.pow,
        "ceil": math.ceil,
        "floor": math.floor,
        "fabs": math.fabs,
        "radians": math.radians,
        "degrees": math.degrees,
    }

    _ALLOWED_CONSTS = {
        "pi": math.pi,
        "e": math.e,
        "tau": math.tau,
        "inf": math.inf,
        "nan": math.nan,
    }

    def run(self, payload: dict[str, Any]) -> str:
        """
        Execute the calculation tool.

        Args:
            payload: Dictionary containing 'expression' or 'query'.

        Returns:
            The calculated result as a string.
        """
        expression = payload.get("expression") or payload.get("query") or ""
        logger.debug(f"CalculatorTool.run requested with expression: '{expression}'")
        try:
            result_value = self.evaluate(expression)
            logger.info(f"CalculatorTool result: {result_value}")
            return str(result_value)
        except Exception as e:
            logger.error(f"CalculatorTool failed: {e}")
            raise ValueError(e)

    def evaluate(self, expression: str) -> float:
        """
        Safely evaluate a mathematical expression using AST.

        Args:
            expression: The math string to evaluate.

        Returns:
            The float result.
        """
        try:
            parsed = ast.parse(expression, mode="eval")
            return float(self._eval_node(parsed.body))
        except Exception as exc:
            raise ValueError(f"Invalid expression: {exc}")

    def _eval_node(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Only numeric constants are allowed")
        if isinstance(node, ast.BinOp) and isinstance(node.op, self._ALLOWED_BINARY_OPS):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            return self._apply_binop(node.op, left, right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, self._ALLOWED_UNARY_OPS):
            operand = self._eval_node(node.operand)
            return +operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.Call):
            func_name = self._resolve_name(node.func)
            if func_name not in self._ALLOWED_FUNCS:
                raise ValueError(f"Function '{func_name}' is not allowed")
            func = self._ALLOWED_FUNCS[func_name]
            args = [self._eval_node(arg) for arg in node.args]
            if node.keywords:
                raise ValueError("Keyword arguments are not allowed")
            return float(func(*args))
        if isinstance(node, ast.Name):
            if node.id in self._ALLOWED_CONSTS:
                return float(self._ALLOWED_CONSTS[node.id])
            raise ValueError(f"Name '{node.id}' is not allowed")
        if isinstance(node, ast.Expr):
            return self._eval_node(node.value)
        raise ValueError("Unsupported expression")

    def _apply_binop(self, op: ast.AST, left: float, right: float) -> float:
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.FloorDiv):
            return left // right
        if isinstance(op, ast.Mod):
            return left % right
        if isinstance(op, ast.Pow):
            return left**right
        raise ValueError("Operator not allowed")

    def _resolve_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        raise ValueError("Invalid function reference")
