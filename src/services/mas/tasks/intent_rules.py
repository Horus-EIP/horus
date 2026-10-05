import re
import unicodedata
from enum import Enum


class TrivialIntent(str, Enum):
    GREETING = "greeting"
    SMALL_TALK = "small_talk"
    ARITHMETIC = "arithmetic"


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

_THANKS_OBJECT = r"(?:\s+for\s+(?:the\s+|your\s+|all\s+the\s+)?(?:help|answer|info|information|reply))?"

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


def _any_of(phrases) -> str:
    return "(?:" + "|".join(phrases) + ")"


_ADDRESSEE_WORD = _any_of(_ADDRESSEE_WORDS)
_TRAILING_ADDRESSEES = rf"(?:\s+{_ADDRESSEE_WORD})*"

_CLAUSE_SEPARATOR = re.compile(r"[!?;:\n]+|(?<!\d)[.,]|[.,](?!\d)")
_NON_WORD = re.compile(r"[^\w\s']")
_ADDRESSEE_ONLY = re.compile(_ADDRESSEE_WORD + _TRAILING_ADDRESSEES)
_GREETING = re.compile(_any_of(_GREETING_PHRASES) + _TRAILING_ADDRESSEES)
_SMALL_TALK = re.compile(_any_of(_SMALL_TALK_PHRASES) + _TRAILING_ADDRESSEES)

_ARITHMETIC_LEAD = re.compile(
    r"^\s*(?:(?:can|could)\s+you\s+)?(?:please\s+)?" + _any_of(_ARITHMETIC_LEADS) + "?"
)
_REVERSED_ARITHMETIC_TAIL = re.compile(
    r"(?:=|\s|\b" + _any_of(word[::-1] for word in _ARITHMETIC_TAIL_WORDS) + r"\b)*"
)
_ISO_DATE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b")
_SQUARE_ROOT_WORD = re.compile(r"\b" + _any_of(_SQUARE_ROOT_WORDS) + r"\b")
_POWER_WORD = re.compile(r"\b" + _any_of(_POWER_WORD_EXPONENTS) + r"\b")
_PERCENT_WORD = re.compile(r"\bpercent\b")
_PERCENT_OF = re.compile(r"%\s*of\b")
_BINARY_WORD_OPERATOR = re.compile(r"\b" + _any_of(_BINARY_WORD_OPERATORS) + r"\b")
_EXPRESSION = re.compile(r"[\d\s.,+\-*/x×÷^%()√]+")
_NUMBER = re.compile(r"\d[\d.,]*")
_GROUPING = re.compile(r"[\s()]")
_OPERATION_SHAPE = re.compile(r"n[+\-*/x×÷^%][+\-]*n|√[+\-]*n")


def classify_trivial_intent(text: str | None) -> TrivialIntent | None:
    if not text or len(text) > _MAX_TRIVIAL_LENGTH:
        return None
    found: set[TrivialIntent] = set()
    for clause in _CLAUSE_SEPARATOR.split(_normalise(text)):
        if _is_arithmetic(clause):
            found.add(TrivialIntent.ARITHMETIC)
            continue
        words = _words(clause)
        if not words or _ADDRESSEE_ONLY.fullmatch(words):
            continue
        if _GREETING.fullmatch(words):
            found.add(TrivialIntent.GREETING)
        elif _SMALL_TALK.fullmatch(words):
            found.add(TrivialIntent.SMALL_TALK)
        else:
            return None
    for intent in (TrivialIntent.ARITHMETIC, TrivialIntent.SMALL_TALK, TrivialIntent.GREETING):
        if intent in found:
            return intent
    return None


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return folded.replace("’", "'").replace("‘", "'")


def _words(clause: str) -> str:
    tokens = (token.strip("'") for token in _NON_WORD.sub(" ", clause).split())
    return " ".join(token for token in tokens if token)


def _is_arithmetic(clause: str) -> bool:
    if _ISO_DATE.search(clause):
        return False
    expression = _without_arithmetic_tail(_ARITHMETIC_LEAD.sub("", clause, count=1))
    expression = _SQUARE_ROOT_WORD.sub(" √ ", expression)
    expression = _POWER_WORD.sub(lambda word: _POWER_WORD_EXPONENTS[word.group()], expression)
    expression = _PERCENT_WORD.sub("%", expression)
    expression = _PERCENT_OF.sub("%", expression)
    expression = _BINARY_WORD_OPERATOR.sub(" + ", expression)
    if not _EXPRESSION.fullmatch(expression):
        return False
    operand_shape = _GROUPING.sub("", _NUMBER.sub("n", expression))
    return bool(_OPERATION_SHAPE.search(operand_shape))


def _without_arithmetic_tail(expression: str) -> str:
    tail_length = _REVERSED_ARITHMETIC_TAIL.match(expression[::-1]).end()
    return expression[: len(expression) - tail_length]
