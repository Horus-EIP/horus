import math
import re
from fractions import Fraction

MAX_EXPONENT = 1000
MAX_RESULT_DIGITS = 100
GROUPED_INTEGER_FROM = 10_000
EXACT_INTEGER_BELOW = 10**15
SIGNIFICANT_DIGITS = 10

_PERCENT_OF = "% of"
_OPERAND_STARTS = ("(", "√")

_WORD_OPERATORS = (
    (re.compile(r"\bto\s+the\s+power\s+of\b"), " ^ "),
    (re.compile(r"\bmultiplied\s+by\b"), " * "),
    (re.compile(r"\bdivided\s+by\b"), " / "),
    (re.compile(r"\b(?:the\s+)?square\s+root\s+of\b|\bsqrt\b"), " √ "),
    (re.compile(r"\bsquared\b"), " ^ 2 "),
    (re.compile(r"\bcubed\b"), " ^ 3 "),
    (re.compile(r"\bpercent\b"), " % "),
    (re.compile(r"\bplus\b"), " + "),
    (re.compile(r"\bminus\b"), " - "),
    (re.compile(r"\btimes\b"), " * "),
    (re.compile(r"\bover\b"), " / "),
    (re.compile(r"\bmod(?:ulo)?\b"), " % "),
)

_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"|(?P<percent_of>%\s*of\b)"
    r"|(?P<operator>\*\*|[-+*/x×÷^%()√])"
    r")"
)

_OPERATOR_SYMBOLS = {"x": "*", "×": "*", "÷": "/", "**": "^"}


class NotArithmeticError(ValueError):
    pass


def evaluate_arithmetic(expression: str) -> Fraction:
    tokens = _tokens(expression)
    return _Parser(tokens).parse()


def arithmetic_answer(expression: str) -> str | None:
    try:
        value = evaluate_arithmetic(expression)
    except ZeroDivisionError:
        return f"{expression} is undefined: a number cannot be divided by zero."
    except (NotArithmeticError, OverflowError, ValueError):
        return None
    return f"{expression} = {format_number(value)}"


def format_number(value: Fraction) -> str:
    if value.denominator == 1 and abs(value.numerator) < EXACT_INTEGER_BELOW:
        if abs(value.numerator) >= GROUPED_INTEGER_FROM:
            return f"{value.numerator:,}"
        return str(value.numerator)
    return format(float(value), f".{SIGNIFICANT_DIGITS}g")


def _tokens(expression: str) -> list[Fraction | str]:
    text = expression
    for pattern, symbol in _WORD_OPERATORS:
        text = pattern.sub(symbol, text)
    text = text.strip()
    tokens: list[Fraction | str] = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise NotArithmeticError(expression)
        if match.lastgroup == "number":
            tokens.append(Fraction(match.group("number").replace(",", "")))
        elif match.lastgroup == "percent_of":
            tokens.append(_PERCENT_OF)
        else:
            operator = match.group("operator")
            tokens.append(_OPERATOR_SYMBOLS.get(operator, operator))
        position = match.end()
    if not tokens:
        raise NotArithmeticError(expression)
    return tokens


def _square_root(value: Fraction) -> Fraction:
    if value < 0:
        raise NotArithmeticError("square root of a negative number")
    numerator_root = math.isqrt(value.numerator)
    denominator_root = math.isqrt(value.denominator)
    if numerator_root**2 == value.numerator and denominator_root**2 == value.denominator:
        return Fraction(numerator_root, denominator_root)
    return Fraction(math.sqrt(value))


def _power(base: Fraction, exponent: Fraction) -> Fraction:
    if exponent.denominator != 1 or abs(exponent) > MAX_EXPONENT:
        raise NotArithmeticError("unsupported exponent")
    magnitude = max(abs(base.numerator), base.denominator)
    if magnitude > 1 and math.log10(magnitude) * abs(exponent) > MAX_RESULT_DIGITS:
        raise NotArithmeticError("result too large")
    return base ** int(exponent)


class _Parser:
    def __init__(self, tokens: list[Fraction | str]):
        self._tokens = tokens
        self._position = 0

    def parse(self) -> Fraction:
        value = self._sum()
        if self._position != len(self._tokens):
            raise NotArithmeticError("unexpected token")
        return value

    def _peek(self) -> Fraction | str | None:
        if self._position < len(self._tokens):
            return self._tokens[self._position]
        return None

    def _take(self, *symbols: str) -> str | None:
        token = self._peek()
        if isinstance(token, str) and token in symbols:
            self._position += 1
            return token
        return None

    def _sum(self) -> Fraction:
        value = self._product()
        while (operator := self._take("+", "-")) is not None:
            right = self._product()
            value = value + right if operator == "+" else value - right
        return value

    def _product(self) -> Fraction:
        value = self._signed()
        while (operator := self._take("*", "/", "%", _PERCENT_OF)) is not None:
            if operator == "%" and not self._operand_follows():
                raise NotArithmeticError("a percent sign needs 'of' or a second operand")
            right = self._signed()
            if operator == "*":
                value = value * right
            elif operator == "/":
                value = value / right
            elif operator == "%":
                value = value % right
            else:
                value = value / 100 * right
        return value

    def _operand_follows(self) -> bool:
        token = self._peek()
        return isinstance(token, Fraction) or token in _OPERAND_STARTS

    def _signed(self) -> Fraction:
        operator = self._take("+", "-", "√")
        if operator is None:
            return self._exponentiation()
        operand = self._signed()
        if operator == "-":
            return -operand
        if operator == "√":
            return _square_root(operand)
        return operand

    def _exponentiation(self) -> Fraction:
        base = self._atom()
        if self._take("^") is None:
            return base
        return _power(base, self._signed())

    def _atom(self) -> Fraction:
        token = self._peek()
        if isinstance(token, Fraction):
            self._position += 1
            return token
        if self._take("(") is not None:
            value = self._sum()
            if self._take(")") is None:
                raise NotArithmeticError("unbalanced parenthesis")
            return value
        raise NotArithmeticError("missing operand")
