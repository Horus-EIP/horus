from __future__ import annotations

import time
from fractions import Fraction

import pytest

from tasks.arithmetic import (
    NotArithmeticError,
    arithmetic_answer,
    evaluate_arithmetic,
    format_number,
)


@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("2+2", 4),
        ("6x7", 42),
        ("6 × 7", 42),
        ("12 * (3 + 4)", 84),
        ("(1+2)*(3+4)", 21),
        ("2 - -3", 5),
        ("10 / 4", Fraction(5, 2)),
        ("100 ÷ 4", 25),
        ("1,000 + 2,500", 3500),
        ("3.5 times 2", 7),
        ("12 multiplied by 7", 84),
        ("100 divided by 4", 25),
        ("9 over 3", 3),
        ("10 minus 4 plus 1", 7),
        ("15% of 200", 30),
        ("15 percent of 200", 30),
        ("10 % 3", 1),
        ("10 mod 3", 1),
        ("2^10", 1024),
        ("2 ** 3", 8),
        ("2 to the power of 3", 8),
        ("4 squared", 16),
        ("5 cubed", 125),
        ("2^3^2", 512),
        ("-2^2", -4),
        ("√16", 4),
        ("square root of 16", 4),
        ("the square root of 0.25", Fraction(1, 2)),
        ("0.1 + 0.2", Fraction(3, 10)),
    ],
)
def test_expressions_are_evaluated_exactly(expression, value):
    assert evaluate_arithmetic(expression) == value


@pytest.mark.parametrize(
    "expression",
    [
        "50% + 10",
        "10 %",
        "2(3+4)",
        "(1+2",
        "1,5 + 1",
        "2 ^ 0.5",
        "√-4",
        "import os",
        "",
    ],
)
def test_ambiguous_or_unsupported_expressions_are_not_evaluated(expression):
    with pytest.raises(NotArithmeticError):
        evaluate_arithmetic(expression)


def test_a_result_too_large_to_show_is_not_evaluated():
    started = time.perf_counter()
    with pytest.raises(NotArithmeticError):
        evaluate_arithmetic("9^9^9")
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    "expression",
    [
        "9^100*9^100*9^100*9^100",
        "10^99*10^99*10^99*10^99",
        "10^100 + 1",
        "1/10^99/10^99/10^99/10^99",
        "0.5^300 * 0.5^300",
    ],
)
def test_a_result_beyond_ten_to_the_hundred_either_way_is_not_evaluated(expression):
    with pytest.raises(NotArithmeticError):
        evaluate_arithmetic(expression)


@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("10^100", Fraction(10) ** 100),
        ("(1/10)^100", Fraction(1, 10**100)),
        ("0 * 10^99", 0),
        ("5 - 5", 0),
    ],
)
def test_results_up_to_ten_to_the_hundred_either_way_and_zero_are_evaluated(expression, value):
    assert evaluate_arithmetic(expression) == value


class TestArithmeticAnswer:
    def test_the_answer_repeats_the_expression_and_gives_the_result(self):
        assert arithmetic_answer("2+2") == "2+2 = 4"

    def test_word_operators_are_kept_as_the_user_wrote_them(self):
        assert arithmetic_answer("12 multiplied by 7") == "12 multiplied by 7 = 84"

    def test_division_by_zero_is_explained_instead_of_answered(self):
        assert arithmetic_answer("1/0") == ("1/0 is undefined: a number cannot be divided by zero.")

    @pytest.mark.parametrize(
        "expression",
        ["50% + 10", "9^9^9", "√-1", "9^100*9^100*9^100*9^100", "1/10^99/10^99/10^99/10^99"],
    )
    def test_an_expression_that_cannot_be_evaluated_has_no_answer(self, expression):
        assert arithmetic_answer(expression) is None

    def test_the_largest_and_smallest_results_are_shown(self):
        assert arithmetic_answer("10^100") == "10^100 = 1e+100"
        assert arithmetic_answer("(1/10)^100") == "(1/10)^100 = 1e-100"


class TestFormatNumber:
    @pytest.mark.parametrize(
        ("value", "text"),
        [
            (Fraction(4), "4"),
            (Fraction(-679), "-679"),
            (Fraction(3500), "3500"),
            (Fraction(1_000_000), "1,000,000"),
            (Fraction(5, 2), "2.5"),
            (Fraction(10, 3), "3.333333333"),
            (Fraction(2**64), "1.844674407e+19"),
        ],
    )
    def test_numbers_are_shown_exactly_or_to_ten_significant_digits(self, value, text):
        assert format_number(value) == text
