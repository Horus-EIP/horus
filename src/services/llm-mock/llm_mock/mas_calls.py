import ast
import re
from dataclasses import dataclass

from llm_mock.call import Call
from llm_mock.schemas import dumps, example
from llm_mock.settings import Settings
from llm_mock.words import plain_words, word_set, words

SMALL_TALK_REPLY = "Hello! Horus is running in mock AI mode."
SMALL_TALK = re.compile(
    r"(hi|hello|hey|hiya|good (morning|afternoon|evening|day)|thanks|thank you"
    r"( (so|very) much)?|many thanks|cheers|bye|goodbye|see you( later| soon)?"
    r"|how are you( doing)?( today)?)( there| horus| everyone| all)?"
)
COMPARISON_WORDS = frozenset(
    {"compare", "compared", "comparing", "comparison", "versus", "vs", "against"}
)
DOMAINS = {
    "finance": frozenset(
        {
            "revenue", "profit", "margin", "earning", "income", "ebitda", "budget", "financial",
            "finance", "quarter", "quarterly", "q1", "q2", "q3", "q4", "sale", "spend", "spent",
            "cost", "cash", "forecast", "segment", "fiscal", "opex", "payroll",
        }
    ),
    "hr": frozenset(
        {
            "hr", "leave", "vacation", "holiday", "benefit", "handbook", "employee", "remote",
            "onboard", "pto", "conduct", "parental", "sick", "recruit", "salary", "overtime",
            "probation", "staff", "workplace", "harassment",
        }
    ),
    "compliance": frozenset(
        {
            "compliance", "sox", "gdpr", "mica", "finra", "audit", "regulatory", "regulation",
            "aml", "kyc", "sanction",
        }
    ),
    "it_security": frozenset(
        {
            "password", "security", "mfa", "encryption", "phish", "incident", "vpn",
            "classification", "breach", "malware", "access", "laptop", "device",
        }
    ),
    "expenses": frozenset(
        {
            "expense", "reimbursement", "reimburse", "hotel", "travel", "diem", "meal",
            "mileage", "receipt", "allowance",
        }
    ),
}
DOMAIN_HINTS = {
    "finance": frozenset({"finance", "financial"}),
    "hr": frozenset({"hr", "human", "handbook"}),
    "compliance": frozenset({"compliance"}),
    "it_security": frozenset({"security"}),
    "expenses": frozenset({"expense"}),
}
ROSTER_LINE = re.compile(r"^- (?P<name>[^:\n]+?)(?:: (?P<description>.*))?$")
PLAN_ROSTER_LINE = re.compile(r"^- Type: [^\n]*? \(Name: (?P<name>[^)\n]+)\)(?:: (?P<description>.*))?$")
TYPE_SUFFIX = re.compile(r" \(Type: [^)]*\)$")
DOCUMENTS_OF = re.compile(r"From the (.+?) documents:")
PLANNED_STEP = re.compile(r"^ {2}\d+\. ([^:\n]+):", re.MULTILINE)
SOURCE_TAG = re.compile(r"\[Source: ([^\]]+)\]")
NO_STEP_LEFT = "(none"
RETRY_KEYS = frozenset({"status", "reason", "attempt"})
MANAGER = "manager"


@dataclass(frozen=True)
class Agent:
    name: str
    description: str = ""

    @property
    def words(self) -> frozenset[str]:
        return word_set(f"{self.name.replace('-', ' ')} {self.description}")


def after(text: str, marker: str) -> str:
    at = text.find(marker)
    return text[at + len(marker):] if at >= 0 else text


def question_of(call: Call) -> str:
    return after(call.user, "USER INPUT:\n").strip()


def is_small_talk(question: str) -> bool:
    return bool(SMALL_TALK.fullmatch(" ".join(re.sub(r"[^a-z ]+", " ", question.lower()).split())))


def is_comparison(question: str) -> bool:
    return bool(plain_words(question) & COMPARISON_WORDS)


def roster_from(system: str, line_pattern: re.Pattern = ROSTER_LINE) -> list[Agent]:
    agents = []
    for line in system.splitlines():
        match = line_pattern.match(line.strip())
        if match is None:
            continue
        description = TYPE_SUFFIX.sub("", match.group("description") or "")
        agent = Agent(match.group("name").strip(), description.strip())
        if agent.name.lower() != MANAGER and agent.name not in {a.name for a in agents}:
            agents.append(agent)
    return agents


def domains_in(question: str) -> list[str]:
    found: dict[str, int] = {}
    for position, word in enumerate(words(question)):
        for domain, keywords in DOMAINS.items():
            if word in keywords:
                found.setdefault(domain, position)
    return sorted(found, key=found.get)


def agent_for(domain: str, roster: list[Agent], question: frozenset[str],
              taken: list[str]) -> Agent | None:
    hinted = [agent for agent in roster if agent.words & DOMAIN_HINTS[domain]]
    fresh = [agent for agent in hinted if agent.name not in taken] or hinted
    if not fresh:
        return None
    return max(fresh, key=lambda agent: len(agent.words & question))


def general_agent(roster: list[Agent]) -> Agent | None:
    return next((agent for agent in roster if "general" in agent.words), None)


def choose_agents(question: str, roster: list[Agent]) -> list[str]:
    if not roster:
        return []
    asked = word_set(question)
    chosen: list[str] = []
    for domain in domains_in(question):
        agent = agent_for(domain, roster, asked, chosen)
        if agent is not None and agent.name not in chosen:
            chosen.append(agent.name)
    if chosen:
        return chosen
    best = max(roster, key=lambda agent: len(agent.words & asked))
    if best.words & asked:
        return [best.name]
    return [(general_agent(roster) or roster[0]).name]


def is_complex(question: str, agents: list[str]) -> bool:
    return len(agents) > 1 or is_comparison(question)


def task_route(call: Call, settings: Settings) -> str:
    properties = call.schema.get("properties") or {}
    allowed = list((properties.get("agent") or {}).get("enum") or [])
    routes = list((properties.get("route") or {}).get("enum") or [])
    if not allowed or not routes:
        return dumps(example(call.schema, SMALL_TALK_REPLY))
    described = {agent.name: agent for agent in roster_from(call.system)}
    roster = [described.get(name, Agent(name)) for name in allowed if name.lower() != MANAGER]
    question = call.user.strip()
    agents = choose_agents(question, roster) or allowed[:1]
    wanted = "COMPLEX_TASK" if is_complex(question, agents) else "SINGLE_AGENT"
    return dumps({"route": wanted if wanted in routes else routes[0], "agent": agents[0]})


def intent(call: Call, settings: Settings) -> str:
    question = question_of(call)
    if is_small_talk(question):
        return dumps({
            "classification": "DIRECT_ANSWER",
            "agent_name": "",
            "rewritten_input": "",
            "final_answer": SMALL_TALK_REPLY,
        })
    agents = choose_agents(question, roster_from(after(call.system, "AVAILABLE AGENTS")))
    return dumps({
        "classification": "COMPLEX_TASK" if is_complex(question, agents) else "SINGLE_AGENT",
        "agent_name": agents[0] if agents else "",
        "rewritten_input": question,
        "final_answer": "",
    })


def plan(call: Call, settings: Settings) -> str:
    question = question_of(call)
    roster = roster_from(after(call.system, "AVAILABLE AGENT TYPES:"), PLAN_ROSTER_LINE)
    sub_tasks = []
    for number, name in enumerate(choose_agents(question, roster), start=1):
        sub_tasks.append({
            "id": str(number),
            "agent_type": name,
            "description": f"From the {name} documents: {question}",
            "depends_on": [str(number - 1)] if number > 1 else [],
            "status": "pending",
        })
    return dumps({"sub_tasks": sub_tasks})


def announce(call: Call, settings: Settings) -> str:
    steps = call.user
    at = steps.rfind("\n\nUSER DEMAND:\n")
    steps = steps[:at] if at >= 0 else steps
    names = DOCUMENTS_OF.findall(steps) or PLANNED_STEP.findall(steps)
    ordered = list(dict.fromkeys(name.strip() for name in names))
    if not ordered:
        return "I'm asking a specialist to work on this."
    return f"I'm asking {' then '.join(ordered)} to work on this."


def review(call: Call, settings: Settings) -> str:
    text = call.user
    start = text.rfind("REMAINING PLANNED STEPS:\n")
    remaining = text[start + len("REMAINING PLANNED STEPS:\n"):] if start >= 0 else ""
    remaining = remaining.split("\n\nAVAILABLE AGENT TYPES", 1)[0].strip()
    if not remaining or remaining.startswith(NO_STEP_LEFT):
        return dumps({
            "decision": "DONE",
            "next_agent_type": None,
            "next_action": None,
            "reasoning": "No planned step remains.",
        })
    return dumps({
        "decision": "CONTINUE",
        "next_agent_type": None,
        "next_action": None,
        "reasoning": "The next planned step can start.",
    })


def aggregate(call: Call, settings: Settings) -> str:
    text = after(call.user, "FINAL AGENT OUTPUT (Containing cumulative results):\n")
    final_output, _, history = text.rpartition("\n\nORIGINAL USER REQUEST:\n")
    results = step_results(history) or [final_output.strip() or text.strip()]
    lines = ["## Answer", ""]
    for number, result in enumerate(results, start=1):
        lines += [f"### Step {number}", "", result, ""]
    sources = list(dict.fromkeys(
        source.strip() for result in results for source in SOURCE_TAG.findall(result)
    ))
    if sources:
        lines += [f"**Sources:** {', '.join(sources)}", ""]
    return "\n".join(lines).strip()


def step_results(history: str) -> list[str]:
    try:
        entries = ast.literal_eval(history.strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return []
    if not isinstance(entries, list):
        return []
    results = [
        str(entry.get("message", "")).strip()
        for entry in entries
        if isinstance(entry, dict) and entry.get("role") == "assistant"
        and not RETRY_KEYS & set(entry)
    ]
    return list(dict.fromkeys(result for result in results if result))
