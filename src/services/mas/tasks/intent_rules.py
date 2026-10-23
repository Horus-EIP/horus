import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class TrivialIntent(str, Enum):
    GREETING = "greeting"
    SMALL_TALK = "small_talk"
    ARITHMETIC = "arithmetic"


class ComplexCue(str, Enum):
    COMPARISON = "comparison"
    AND_ALSO = "and_also"
    SEVERAL_QUESTIONS = "several_questions"


@dataclass(frozen=True)
class TrivialClause:
    intent: TrivialIntent
    text: str


_ADDRESSEE_WORDS = (
    "there",
    "all",
    "everyone",
    "everybody",
    "world",
    "horus",
    "team",
    "guys",
    "folks",
    "friend",
    "buddy",
    "mate",
    "bot",
)

_GREETING_PHRASES = (
    r"h+i+",
    r"he+y+",
    r"hel+o+",
    r"hiya",
    r"heya",
    r"howdy",
    r"greetings",
    r"yo",
    r"good\s+(?:morning|afternoon|evening|day)",
    r"morning",
    r"evening",
    r"bonjour",
    r"salut",
    r"hola",
    r"hallo",
    r"ciao",
)

_THANKS_OBJECT = (
    r"(?:\s+for\s+(?:the\s+|your\s+|all\s+the\s+)?(?:help|answer|info|information|reply))?"
)

_SMALL_TALK_PHRASES = (
    r"how\s+are\s+(?:you|u)(?:\s+doing)?(?:\s+today)?",
    r"how\s+r\s+u",
    r"how(?:'s|s|\s+is)\s+it\s+going",
    r"how\s+have\s+you\s+been",
    r"how\s+do\s+you\s+do",
    r"what'?s\s+up",
    r"sup",
    r"wh?assup",
    r"(?:thanks(?:\s+(?:a\s+lot|so\s+much|a\s+bunch))?|thank\s+you(?:\s+(?:so|very)\s+much)?"
    rf"|thx|ty|cheers){_THANKS_OBJECT}(?:\s+again)?",
    r"much\s+appreciated",
    r"appreciate\s+it",
    r"(?:good\s*)?bye(?:\s+bye)?",
    r"see\s+(?:you|ya)(?:\s+(?:later|soon|tomorrow))?",
    r"good\s+night",
    r"take\s+care",
    r"that(?:'s|\s+is|\s+will\s+be|'ll\s+be)\s+all(?:\s+for\s+(?:now|today))?",
    r"nothing\s+else",
    r"(?:nice|pleased)\s+to\s+meet\s+you",
    r"who\s+are\s+you",
    r"what\s+are\s+you",
    r"what(?:'s|\s+is)\s+your\s+name",
    r"what\s+can\s+you\s+do",
    r"are\s+you\s+there",
    r"ok(?:ay)?",
    r"k",
    r"cool",
    r"great",
    r"awesome",
    r"nice",
    r"perfect",
    r"got\s+it",
    r"sounds\s+good",
    r"alright",
    r"all\s+right",
    r"you'?re\s+welcome",
    r"no\s+problem",
    r"my\s+pleasure",
    r"good\s+job",
    r"well\s+done",
    r"lol",
    r"haha+",
)

_ARITHMETIC_LEADS = (
    r"what\s+is",
    r"what's",
    r"whats",
    r"how\s+much\s+is",
    r"calculate",
    r"compute",
    r"evaluate",
    r"solve",
    r"work\s+out",
)

_ARITHMETIC_TAIL_WORDS = ("equals", "equal", "please")

_BINARY_WORD_OPERATORS = (
    r"plus",
    r"minus",
    r"times",
    r"multiplied\s+by",
    r"divided\s+by",
    r"over",
    r"modulo",
    r"mod",
    r"to\s+the\s+power\s+of",
)

_SQUARE_ROOT_WORDS = (r"(?:the\s+)?square\s+root\s+of", r"sqrt")

_POWER_WORD_EXPONENTS = {"squared": "^2", "cubed": "^3"}

_MAX_TRIVIAL_LENGTH = 200

_MIN_QUESTION_WORDS = 3


def _any_of(phrases) -> str:
    return "(?:" + "|".join(phrases) + ")"


_ADDRESSEE_WORD = _any_of(_ADDRESSEE_WORDS)
_TRAILING_ADDRESSEES = rf"(?:\s+{_ADDRESSEE_WORD})*"

_CLAUSE_SEPARATOR = re.compile(r"[!?;:\n]+|(?<!\d)[.,]|[.,](?!\d)")
_NON_WORD = re.compile(r"[^\w\s']")
_ADDRESSEE_ONLY = re.compile(_ADDRESSEE_WORD + _TRAILING_ADDRESSEES)
_GREETING_WORDS = _any_of(_GREETING_PHRASES) + _TRAILING_ADDRESSEES
_GREETING = re.compile(_GREETING_WORDS)
_SMALL_TALK = re.compile(
    rf"(?:{_GREETING_WORDS}\s+)?" + _any_of(_SMALL_TALK_PHRASES) + _TRAILING_ADDRESSEES
)

_ARITHMETIC_LEAD = re.compile(
    r"^\s*(?:(?:can|could)\s+you\s+)?(?:please\s+)?" + _any_of(_ARITHMETIC_LEADS) + "?"
)
_REVERSED_ARITHMETIC_TAIL = re.compile(
    r"(?:=|\s|\b" + _any_of(word[::-1] for word in _ARITHMETIC_TAIL_WORDS) + r"\b)*"
)
_DASHED_DIGIT_GROUPS = re.compile(r"\d{3,}-\d{3,}|\d+-\d+-\d+")
_SQUARE_ROOT_WORD = re.compile(r"\b" + _any_of(_SQUARE_ROOT_WORDS) + r"\b")
_POWER_WORD = re.compile(r"\b" + _any_of(_POWER_WORD_EXPONENTS) + r"\b")
_PERCENT_WORD = re.compile(r"\bpercent\b")
_PERCENT_OF = re.compile(r"%\s*of\b")
_BINARY_WORD_OPERATOR = re.compile(r"\b" + _any_of(_BINARY_WORD_OPERATORS) + r"\b")
_EXPRESSION = re.compile(r"[\d\s.,+\-*/x×÷^%()√]+")
_NUMBER = re.compile(r"\d[\d.,]*")
_GROUPING = re.compile(r"[\s()]")
_OPERATION_SHAPE = re.compile(r"n[+\-*/x×÷^%][+\-]*n|√[+\-]*n")
_COMPARISON = re.compile(r"\b(?:compar(?:e|es|ed|ing|ison|isons)|versus)\b")
_VS_BETWEEN_OPERANDS = re.compile(r"\w\s+vs\.?\s+(?!code\b)\w")
_AND_ALSO = re.compile(r"\band\s+also\b")
_SENTENCE_BREAK = re.compile(r"[!;:\n]|(?<!\d)\.|\.(?!\d)")
_QUESTION_WORD = re.compile(r"[\w']+")


def classify_trivial_intent(text: str | None) -> TrivialIntent | None:
    found = {clause.intent for clause in trivial_clauses(text)}
    for intent in (TrivialIntent.ARITHMETIC, TrivialIntent.SMALL_TALK, TrivialIntent.GREETING):
        if intent in found:
            return intent
    return None


def trivial_clauses(text: str | None) -> list[TrivialClause]:
    if not text or len(text) > _MAX_TRIVIAL_LENGTH:
        return []
    clauses: list[TrivialClause] = []
    for clause in _CLAUSE_SEPARATOR.split(_normalise(text)):
        expression = _arithmetic_expression(clause)
        if expression is not None:
            clauses.append(TrivialClause(TrivialIntent.ARITHMETIC, expression))
            continue
        words = _words(clause)
        if not words or _ADDRESSEE_ONLY.fullmatch(words):
            continue
        if _GREETING.fullmatch(words):
            clauses.append(TrivialClause(TrivialIntent.GREETING, words))
        elif _SMALL_TALK.fullmatch(words):
            clauses.append(TrivialClause(TrivialIntent.SMALL_TALK, words))
        else:
            return []
    return clauses


def find_complex_cue(text: str | None) -> ComplexCue | None:
    if not text:
        return None
    normalised = _normalise(text)
    if _COMPARISON.search(normalised) or _VS_BETWEEN_OPERANDS.search(normalised):
        return ComplexCue.COMPARISON
    if _AND_ALSO.search(normalised):
        return ComplexCue.AND_ALSO
    questions = sum(1 for asked in normalised.split("?")[:-1] if _is_a_full_question(asked))
    if questions >= 2:
        return ComplexCue.SEVERAL_QUESTIONS
    return None


def _is_a_full_question(text_before_mark: str) -> bool:
    question = _SENTENCE_BREAK.split(text_before_mark)[-1]
    return len(_QUESTION_WORD.findall(question)) >= _MIN_QUESTION_WORDS


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return folded.replace("’", "'").replace("‘", "'")


def _words(clause: str) -> str:
    tokens = (token.strip("'") for token in _NON_WORD.sub(" ", clause).split())
    return " ".join(token for token in tokens if token)


def _arithmetic_expression(clause: str) -> str | None:
    if _DASHED_DIGIT_GROUPS.search(clause):
        return None
    expression = _without_arithmetic_tail(_ARITHMETIC_LEAD.sub("", clause, count=1))
    symbols = _SQUARE_ROOT_WORD.sub(" √ ", expression)
    symbols = _POWER_WORD.sub(lambda word: _POWER_WORD_EXPONENTS[word.group()], symbols)
    symbols = _PERCENT_WORD.sub("%", symbols)
    symbols = _PERCENT_OF.sub("%", symbols)
    symbols = _BINARY_WORD_OPERATOR.sub(" + ", symbols)
    if not _EXPRESSION.fullmatch(symbols):
        return None
    operand_shape = _GROUPING.sub("", _NUMBER.sub("n", symbols))
    if not _OPERATION_SHAPE.search(operand_shape):
        return None
    return " ".join(expression.split())


def _without_arithmetic_tail(expression: str) -> str:
    tail_length = _REVERSED_ARITHMETIC_TAIL.match(expression[::-1]).end()
    return expression[: len(expression) - tail_length]
