import re

WORD = re.compile(r"\d+(?:[.,]\d+)*[a-z]*|[a-z][a-z0-9]*")
DOUBLED_ENDINGS = frozenset("bdgmnprt")
STOPWORDS = frozenset(
    """
    a about above after again all also am an and any are as at be been before being below
    between both but by can could describe did do does doing during each explain few find for
    from further give had has have having he her here hers him his how i if in into is it its
    itself just know list many me more most much my no nor not now of off on once only or other
    our ours out over own please same she should show so some such tell than that the their
    them then there these they this those through to too under until up us very was we were
    what when where which while who whom why will with would you your yours anything everything
    something compare compared comparing flag get gets got say says said summarise summarize
    """.split()
)


def stem(word: str) -> str:
    if not word.isalpha() or len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith(("sses", "xes", "ches", "shes")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            if word[-1] == word[-2] and word[-1] in DOUBLED_ENDINGS:
                word = word[:-1]
            break
    return word


def words(text: str) -> list[str]:
    return [
        stem(word)
        for word in WORD.findall(text.lower())
        if word not in STOPWORDS and (len(word) > 1 or word.isdigit())
    ]


def word_set(text: str) -> frozenset[str]:
    return frozenset(words(text))


def plain_words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", text.lower()))
