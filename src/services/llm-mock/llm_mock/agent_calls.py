import math
import re
from collections import Counter
from dataclasses import dataclass

from llm_mock.call import Call
from llm_mock.schemas import dumps
from llm_mock.settings import Settings
from llm_mock.words import word_set

REFUSAL = "I don't have that information yet."
ANSWER_SCHEMAS = frozenset({"agent_answer"})
ANSWER_PURPOSES = frozenset({"react_step", "grounded"})
FIGURE_CUES = ("how much", "how many", "what was", "what were", "total")
FIGURE_BONUS = 0.1
CLOSE_TO_BEST = 0.8
MAX_SENTENCES = 3
SEARCH_THOUGHT = "THOUGHT: I need to search the knowledge store."
ANSWER_THOUGHT = "THOUGHT: I now have enough information to answer."

HEADER = re.compile(r"^\[(?:(?P<label>S\d+)\](?: (?P<title>.*))?|Source: (?P<source>[^\]]+)\])$")
HEADER_LINE = re.compile(r"(?m)^\[(?:S\d+\]|Source: [^\]]+\])")
FILE_TITLE = re.compile(r"^\[file: (?P<name>.+?)(?: \(source=[^)]*\))?\]$")
PAGE = re.compile(r", page \d+$")
BOLD_LABEL = re.compile(r"^\*\*[^*]+:\*\*")
LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
SEPARATOR_CELL = re.compile(r":?-{2,}:?")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[*\"'(\[]*[A-Z0-9$])")
FIGURE = re.compile(r"\d")
DOCUMENTS_PREFIX = re.compile(r"^From the .+? documents:\s*")
NOISE = ("--- ", "[Indexed file", "…[")
TASK_MARKERS = (
    "=== Your assigned task ===\n",
    "=== Overall request (context only — do only your part) ===\n",
    "Current request:",
)
REQUEST_MARKER = "\n\nRequest: "
TRACE_ENTRY = re.compile(r"(?m)^(THOUGHT|ACTION|OBSERVATION|FINAL_ANSWER|DELEGATION):[ \t]?")


@dataclass(frozen=True)
class Passage:
    label: str
    title: str
    text: str

    @property
    def cited(self) -> str:
        return self.title or self.label or "the retrieved documents"


@dataclass(frozen=True)
class Sentence:
    text: str
    passage: Passage
    order: int


def is_answer(call: Call) -> bool:
    return call.schema_name in ANSWER_SCHEMAS or (
        not call.structured and call.purpose in ANSWER_PURPOSES
    )


def refusal(call: Call) -> str:
    if call.purpose == "react_step" and not call.structured:
        return f"{ANSWER_THOUGHT}\nFINAL_ANSWER: {REFUSAL}"
    if call.schema_name not in ANSWER_SCHEMAS:
        return REFUSAL
    reply = {"status": "not_found", "answer": REFUSAL}
    if "sources" in (call.schema.get("properties") or {}):
        reply["sources"] = []
    return dumps(reply)


def agent_answer(call: Call, settings: Settings) -> str:
    context, request = answer_prompt(call.user)
    chosen = best_sentences(request, passages(context), settings.min_score)
    if not chosen:
        return refusal(call)
    reply: dict = {"status": "ok", "answer": cited(chosen)}
    properties = call.schema.get("properties") or {}
    if "sources" in properties:
        allowed = ((properties["sources"].get("items") or {}).get("enum")) or []
        labels = dict.fromkeys(sentence.passage.label for sentence in chosen)
        reply["sources"] = [label for label in labels if label in allowed]
    return dumps(reply)


def react_step(call: Call, settings: Settings) -> str:
    text = call.user
    query = text.removeprefix("User query: ")
    query = re.split(r"\n\nReasoning so far:\n|\n\nStep \d+: ", query, maxsplit=1)[0]
    observations = observations_in(text)
    if not observations:
        terms = " ".join(re.sub(r"[,()]", " ", focus(query)).split())
        return f"{SEARCH_THOUGHT}\nACTION: search_knowledge({terms})"
    chosen = best_sentences(focus(query), passages("\n\n".join(observations)), settings.min_score)
    return f"{ANSWER_THOUGHT}\nFINAL_ANSWER: {cited(chosen) if chosen else REFUSAL}"


def grounded(call: Call, settings: Settings) -> str:
    text = call.user.removeprefix("Retrieved Content:\n")
    context, marker, task = text.rpartition("\n\nTask: ")
    if not marker:
        return REFUSAL
    chosen = best_sentences(focus(task), passages(context), settings.min_score)
    return cited(chosen) if chosen else REFUSAL


def instruction(call: Call, settings: Settings) -> str:
    _, colon, data = call.user.partition(":")
    return (data if colon else call.user).strip()


def answer_prompt(user: str) -> tuple[str, str]:
    text = user.removeprefix("Passages:\n")
    headers = list(HEADER_LINE.finditer(text))
    at = text.find(REQUEST_MARKER, headers[-1].end() if headers else 0)
    if at < 0:
        at = text.rfind(REQUEST_MARKER)
    if at < 0:
        return "", focus(text)
    return text[:at], focus(text[at + len(REQUEST_MARKER) :])


def focus(request: str) -> str:
    text = request
    if "=== Your task (" in text:
        text = text.split("=== Your task (", 1)[1].split("\n", 1)[-1]
        text = text.split("\n\nGround your answer in the chain transcript", 1)[0]
    for marker in TASK_MARKERS:
        if marker in text:
            text = text.split(marker, 1)[1]
    return DOCUMENTS_PREFIX.sub("", text.strip()).strip()


def observations_in(text: str) -> list[str]:
    reasoning = text.split("\n\nReasoning so far:\n", 1)
    if len(reasoning) < 2:
        return []
    trace = re.split(r"\n\nStep \d+: ", reasoning[1])[0]
    entries = TRACE_ENTRY.split(trace)[1:]
    return [
        body.strip()
        for kind, body in zip(entries[::2], entries[1::2], strict=True)
        if kind == "OBSERVATION" and body.strip()
    ]


def passages(context: str) -> list[Passage]:
    found: list[Passage] = []
    header: re.Match | None = None
    lines: list[str] = []
    for line in [*context.splitlines(), None]:
        match = HEADER.match(line.strip()) if line is not None else None
        if line is not None and match is None:
            lines.append(line)
            continue
        if header is not None:
            found.append(Passage(header.group("label") or "", title_of(header), "\n".join(lines)))
        header, lines = match, []
    return found


def title_of(header: re.Match) -> str:
    title = (header.group("source") or header.group("title") or "").strip()
    file = FILE_TITLE.match(title)
    return PAGE.sub("", file.group("name") if file else title).strip()


def sentences_of(text: str) -> list[str]:
    found: list[str] = []
    paragraph: list[str] = []

    def close() -> None:
        if paragraph:
            found.extend(part.strip() for part in SENTENCE_END.split(" ".join(paragraph)))
            paragraph.clear()

    lines = [line.strip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        if not line or line.startswith(NOISE) or line.startswith("#"):
            close()
        elif line.startswith("|"):
            close()
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if not is_separator(line) and not is_separator(following):
                found.append(row_text(line))
        else:
            if LIST_ITEM.match(line) or BOLD_LABEL.match(line):
                close()
            paragraph.append(LIST_ITEM.sub("", line))
    close()
    return [sentence for sentence in found if sentence]


def cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def is_separator(row: str) -> bool:
    if not row.startswith("|"):
        return False
    filled = [cell for cell in cells(row) if cell]
    return bool(filled) and all(SEPARATOR_CELL.fullmatch(cell) for cell in filled)


def row_text(row: str) -> str:
    first, *rest = [cell for cell in cells(row) if cell] or [""]
    return f"{first}: {', '.join(rest)}" if rest else first


def best_sentences(question: str, found: list[Passage], min_score: float) -> list[Sentence]:
    asked = word_set(question)
    candidates: dict[str, Sentence] = {}
    for passage in found:
        for text in sentences_of(passage.text):
            key = " ".join(text.lower().split())
            candidates.setdefault(key, Sentence(text, passage, len(candidates)))
    if not asked or not candidates:
        return []
    matched = {key: asked & word_set(sentence.text) for key, sentence in candidates.items()}
    seen = Counter(word for words in matched.values() for word in words)
    weight = {word: math.log((len(candidates) + 1) / (seen[word] + 1)) + 1 for word in asked}
    total = sum(weight.values())
    covered = sum(weight[word] for word in asked if seen[word]) / total
    figures = any(cue in question.lower() for cue in FIGURE_CUES)
    scored = []
    for key, sentence in candidates.items():
        overlap = sum(weight[word] for word in matched[key]) / total
        if not overlap:
            continue
        if figures and FIGURE.search(sentence.text):
            overlap = min(1.0, overlap + FIGURE_BONUS)
        scored.append((overlap * covered**2, sentence))
    best = max((score for score, _ in scored), default=0.0)
    if best < min_score or best == 0:
        return []
    floor = max(min_score, CLOSE_TO_BEST * best)
    ranked = sorted(scored, key=lambda item: (-item[0], item[1].order))
    return [sentence for score, sentence in ranked if score >= floor][:MAX_SENTENCES]


def cited(chosen: list[Sentence]) -> str:
    return " ".join(f"{sentence.text} [Source: {sentence.passage.cited}]" for sentence in chosen)
