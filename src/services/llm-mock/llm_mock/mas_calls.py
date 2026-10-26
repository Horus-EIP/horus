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
    r"|how are you( doing)?( today)?)( there| horus| everyone| all)?|what can you do\?"
)
COMPARISON_WORDS = frozenset(
    {"compare", "compared", "comparing", "comparison", "versus", "vs", "against"}
)
MATH_WORDS = frozenset({"divided", "divide", "square", "root", "power", "multiply", "multiplied", "minus", "math"})
STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "but", "in", "on",
    "at", "to", "for", "of", "with", "by", "about", "as", "this", "that", "it",
    "from", "be", "have", "has", "do", "does", "did", "what", "how", "who", "when",
    "where", "why", "which", "can", "could", "will", "would", "should",
    "i", "you", "he", "she", "they", "we", "me", "my", "your", "their", "our", "us"
})

DOMAINS = {
    "finance": frozenset(
        {
            "revenue", "revenues", "profit", "profits", "margin", "margins", "earning", "earnings", "earn",
            "income", "incomes", "ebitda", "budget", "budgets", "financial", "financials", "finance", "finances",
            "quarter", "quarterly", "quarters", "q1", "q2", "q3", "q4", "sale", "sales", "spend", "spending",
            "spent", "cost", "costs", "cash", "forecast", "forecasts", "segment", "segments", "fiscal", "opex",
            "payroll", "growth", "operating", "net", "contract", "contracts", "ticker", "tickers", "licensing",
            "value", "values", "report", "reports", "stock", "stocks", "asset", "assets",
            "management", "technology", "cloud", "rate", "rates", "results", "exceed", "exceeds", "period"
        }
    ),
    "hr": frozenset(
        {
            "hr", "leave", "leaves", "vacation", "vacations", "holiday", "holidays", "benefit", "benefits",
            "handbook", "handbooks", "employee", "employees", "remote", "onboard", "onboarding", "onboarded",
            "pto", "conduct", "conducts", "parental", "sick", "recruit", "recruiting", "salary", "salaries",
            "overtime", "probation", "staff", "workplace", "harassment", "working", "work", "hours", "hour", "office",
            "retirement", "notice", "notices", "grievance", "grievances", "dog", "dogs", "pay", "manager",
            "managers", "director", "directors", "days", "policy", "policies", "collaboration", "window",
            "dependents", "insurance", "premium", "premiums", "service", "base", "senior", "year", "years",
            "daily", "standard"
        }
    ),
    "compliance": frozenset(
        {
            "compliance", "sox", "gdpr", "mica", "finra", "audit", "audits", "regulatory", "regulator", "regulators",
            "regulation", "regulations", "aml", "kyc", "sanction", "sanctions", "protection", "protections", "access",
            "breach", "breaches", "processing", "ropa", "suspicious", "activity", "activities", "simulations", "simulation",
            "insider", "classification", "classifications", "password", "passwords", "mfa", "factor", "factors",
            "incident", "incidents", "encryption", "logs", "phishing", "phish", "security", "dpo", "subject", "request",
            "requests", "transactions", "diligence", "trading", "trade", "trades", "mitigation", "privacy", "sms",
            "revoked", "terminated", "p1", "p2", "p3", "restricted", "pre", "approve", "approves",
            "clear", "executive", "detection", "blocked", "reuse", "flag", "flagged", "tests", "test",
            "soc", "type", "ii", "controls", "control", "officer", "records", "record", "rules", "rule",
            "levels", "characters", "privileged", "account", "accounts", "administrator", "reported", "address",
            "email", "organises", "organizes", "organise", "organize"
        }
    ),
    "expenses": frozenset(
        {
            "expense", "expenses", "reimbursement", "reimbursements", "reimburse", "hotel", "hotels", "travel",
            "travels", "diem", "meal", "meals", "mileage", "receipt", "receipts", "allowance", "allowances",
            "plane", "planes", "business", "trip", "trips", "claim", "claims", "alcohol", "corporate", "card",
            "cards", "ticket", "tickets", "limit", "limits", "cap", "caps", "domestic", "class", "nightly", "night",
            "car", "drive", "bank", "approved"
        }
    ),
    "research": frozenset(
        {
            "cite", "citations", "citation", "all", "files", "every", "document", "documents", "knowledge", "across", "sources",
            "source", "summary", "summaries", "summarise", "summarize", "store", "stores", "passages", "passage", "published",
            "base", "bases", "list", "lists", "collect", "look", "appears", "everything", "references", "search",
            "find", "deadline", "deadlines", "related"
        }
    ),
}

DOMAIN_HINTS = {
    "finance": frozenset({"finance"}),
    "hr": frozenset({"hr", "human", "handbook"}),
    "compliance": frozenset({"compliance", "security"}),
    "expenses": frozenset({"finance", "hr"}),
    "research": frozenset({"research", "researcher"}),
}

ROSTER_LINE = re.compile(r"^[-\s]*(?P<name>[a-zA-Z0-9_-]+)(?:: (?P<description>.*))?$")
PLAN_ROSTER_LINE = re.compile(
    r"^[-\s]*Type: [^\n]*? \(Name: (?P<name>[^)\n]+)\)(?:: (?P<description>.*))?$"
)
TYPE_SUFFIX = re.compile(r" \(Type: [^)]*\)$")
DOCUMENTS_OF = re.compile(r"From the (.+?) documents:")
PLANNED_STEP = re.compile(r"^ {2}\d+\. ([^:\n]+):", re.MULTILINE)

SOURCE_TAG = re.compile(r"\[(?:Source:\s*)?([a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+)\]")

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
    text = call.user
    for marker in ["ORIGINAL USER REQUEST:\n", "USER DEMAND:\n", "USER INPUT:\n"]:
        if marker in text:
            text = after(text, marker)
            break
    return text.strip()


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
    scores = {}
    clean_q = question.replace('-', ' ').replace("'", ' ')
    for word in words(clean_q):
        for domain, keywords in DOMAINS.items():
            if word in keywords:
                scores[domain] = scores.get(domain, 0) + 1
    return sorted(scores, key=scores.get, reverse=True)


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
    
    clean_q = question.replace('-', ' ').replace("'", ' ')
    asked = word_set(clean_q)
    
    is_multi = multiple_question(question) or is_comparison(question)
    chosen: list[str] = []
    
    for domain in domains_in(question):
        agent = agent_for(domain, roster, asked, chosen)
        if agent is not None and agent.name not in chosen:
            chosen.append(agent.name)
            
    if (is_multi or " and " in question.lower()) and len(chosen) >= 2:
        return chosen
        
    if chosen:
        return [chosen[0]]
        
    asked_clean = asked - STOP_WORDS
    best = max(roster, key=lambda agent: len(agent.words & asked_clean))
    if len(best.words & asked_clean) > 0:
        return [best.name]
    return [(general_agent(roster) or roster[0]).name]


def multiple_question(question: str) -> bool:
    q_lower = question.lower()
    if question.count("?") >= 2 or ";" in question:
        return True

    complex_phrases = [
        "and also", "as well as", "in addition to", 
        "and how", "and what", "and when", "and who", "and which", "and why", "and where"
    ]
    if any(phrase in q_lower for phrase in complex_phrases):
        return True

    wh_words = {"who", "what", "when", "where", "why", "how", "which"}
    words_in_q = set(re.findall(r'\b[a-z]+\b', q_lower))
    if len(words_in_q & wh_words) >= 2 and " and " in q_lower:
        return True

    return False


def is_complex(question: str, agents: list[str]) -> bool:
    return len(agents) > 1 or is_comparison(question) or multiple_question(question)


def is_direct(question: str) -> bool:
    q_lower = question.lower().strip()

    if any(c in q_lower for c in ["+", "*", "%", "="]) or re.search(r'\d+\s*[\-\/]\s*\d+', q_lower):
        return True

    clean_q = " ".join(re.sub(r"[^a-z ]+", " ", q_lower).split())
    if SMALL_TALK.fullmatch(q_lower) or SMALL_TALK.fullmatch(clean_q) or SMALL_TALK.fullmatch(clean_q + "?"):
        return True

    if bool(plain_words(clean_q) & MATH_WORDS):
        return True

    extra_greetings = {
        "ok bye", "nice to meet you", "thanks that s all for today", 
        "hi there how s it going", "hey horus", "good evening everyone", "thank you so much",
        "good night", "goodnight", "see ya", "talk to you later",
        "good day to you horus", "hey horus what can you do", "what can you do"
    }
    if clean_q in extra_greetings:
        return True

    words_in_q = plain_words(clean_q)
    has_math = bool(words_in_q & MATH_WORDS)
    has_domain = any(bool(words_in_q & keywords) for keywords in DOMAINS.values())
    if has_math and not has_domain:
        return True

    return False


def task_route(call: Call, settings: Settings) -> str:
    properties = call.schema.get("properties") or {}
    allowed = list((properties.get("agent") or {}).get("enum") or [])
    routes = list((properties.get("route") or {}).get("enum") or [])

    question = question_of(call)

    if is_direct(question):
            wanted_route = "DIRECT_ANSWER" if "DIRECT_ANSWER" in routes else "SINGLE_AGENT"
            agent_name = "General-Assistant"
            if allowed:
                described = {a.name: a for a in roster_from(call.system)}
                roster = [described.get(n, Agent(n)) for n in allowed if n.lower() != MANAGER]
                agent_name = (general_agent(roster) or roster[0]).name if roster else allowed[0]
                
            return dumps({
                "route": wanted_route if wanted_route in routes else (routes[0] if routes else "SINGLE_AGENT"), 
                "agent": agent_name
            })

    if not allowed or not routes:
        return dumps(example(call.schema, SMALL_TALK_REPLY))

    described = {agent.name: agent for agent in roster_from(call.system)}
    roster = [described.get(name, Agent(name)) for name in allowed if name.lower() != MANAGER]

    agents = choose_agents(question, roster) or allowed[:1]
    wanted = "COMPLEX_TASK" if is_complex(question, agents) else "SINGLE_AGENT"

    return dumps({"route": wanted if wanted in routes else routes[0], "agent": agents[0]})


def intent(call: Call, settings: Settings) -> str:
    question = question_of(call)
    if is_direct(question):
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