# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

GITHUB_FOLDER = Path(__file__).resolve().parents[1]
REPLIES = GITHUB_FOLDER / "replies"
PHRASES = GITHUB_FOLDER / "claim-phrases.json"
API = "https://api.github.com"
ELIGIBLE_LABELS = frozenset({"good first issue", "help wanted"})
SUGGESTED_LABEL = "good first issue"
CLAIMED = "claimed"
CLAIMED_COLOR = "c5def5"
CLAIMED_DESCRIPTION = "Someone is working on this issue"
CLAIM_LIMIT = 2
REMINDER_DAYS = 7
RELEASE_DAYS = 14
SUGGESTIONS = 5
REMINDER_MARK = "<!-- claim-reminder:{user} -->"
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})

IGNORE = "ignore"
NOT_ELIGIBLE = "not eligible"
ASSIGN = "assign"
TAKEN = "taken"
LIMIT = "limit"
UNASSIGN = "unassign"
REMIND = "remind"
RELEASE = "release"
NOTHING = "nothing"


@dataclass(frozen=True)
class Phrases:
    phrases: tuple[str, ...]
    commands: tuple[str, ...]
    release: tuple[str, ...]


@dataclass(frozen=True)
class Issue:
    number: int
    state: str
    labels: frozenset[str]
    assignees: tuple[str, ...]
    is_pull_request: bool = False


def load_phrases(path: Path = PHRASES) -> Phrases:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Phrases(
        tuple(normalized(text) for text in data["phrases"]),
        tuple(normalized(text) for text in data["commands"]),
        tuple(normalized(text) for text in data["release"]),
    )


def normalized(text: str) -> str:
    return " ".join(text.translate(APOSTROPHES).lower().split())


def own_words(body: str) -> list[str]:
    lines, fenced = [], False
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and not stripped.startswith(">"):
            lines.append(normalized(line))
    return lines


def starts_with_command(lines: list[str], commands: tuple[str, ...]) -> bool:
    return any(
        re.match(rf"{re.escape(command)}(?![\w-])(?!\s*@)", line)
        for line in lines
        for command in commands
    )


def has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", text) is not None


def is_claim(body: str, phrases: Phrases) -> bool:
    lines = own_words(body)
    text = " ".join(lines)
    return starts_with_command(lines, phrases.commands) or any(
        has_phrase(text, phrase) for phrase in phrases.phrases
    )


def is_release(body: str, phrases: Phrases) -> bool:
    return starts_with_command(own_words(body), phrases.release)


def same_login(first: str, second: str) -> bool:
    return first.lower() == second.lower()


def is_bot(user: dict) -> bool:
    return user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]")


def decide(
    body: str,
    commenter: str,
    issue: Issue,
    open_claims: int,
    phrases: Phrases,
    commenter_is_bot: bool = False,
) -> str:
    if commenter_is_bot or issue.is_pull_request:
        return IGNORE
    holds_it = any(same_login(commenter, assignee) for assignee in issue.assignees)
    if is_release(body, phrases):
        return UNASSIGN if holds_it else IGNORE
    if not is_claim(body, phrases):
        return IGNORE
    if issue.state != "open" or not issue.labels & ELIGIBLE_LABELS:
        return NOT_ELIGIBLE
    if holds_it:
        return IGNORE
    if issue.assignees:
        return TAKEN
    if open_claims >= CLAIM_LIMIT:
        return LIMIT
    return ASSIGN


def stale_action(
    now: datetime, since: datetime, reminded: bool, has_open_pull_request: bool
) -> str:
    if has_open_pull_request:
        return NOTHING
    idle = now - since
    if idle >= timedelta(days=RELEASE_DAYS):
        return RELEASE
    if idle >= timedelta(days=REMINDER_DAYS) and not reminded:
        return REMIND
    return NOTHING


def reply(name: str, **values: object) -> str:
    text = (REPLIES / f"{name}.md").read_text(encoding="utf-8")
    values = {
        "limit": CLAIM_LIMIT,
        "reminder_days": REMINDER_DAYS,
        "release_days": RELEASE_DAYS,
        **values,
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def mentions(pull_request: dict, number: int, repository: str) -> bool:
    text = f"{pull_request.get('title') or ''}\n{pull_request.get('body') or ''}"
    forms = (
        rf"(?<![\w/.-])#{number}(?!\d)",
        rf"(?<![\w.-]){re.escape(repository)}#{number}(?!\d)",
        rf"github\.com/{re.escape(repository)}/issues/{number}(?!\d)",
    )
    return any(re.search(form, text, re.IGNORECASE) for form in forms)


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def as_issue(data: dict) -> Issue:
    return Issue(
        number=int(data["number"]),
        state=str(data.get("state", "open")),
        labels=frozenset(str(label["name"]).lower() for label in data.get("labels", [])),
        assignees=tuple(str(user["login"]) for user in data.get("assignees", [])),
        is_pull_request="pull_request" in data,
    )


class GitHub:
    def __init__(self, repository: str, token: str):
        self.repository = repository
        self.token = token

    def request(self, method: str, path: str, body: object = None) -> object:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{API}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def every(self, path: str) -> list[dict]:
        found, page = [], 1
        separator = "&" if "?" in path else "?"
        while True:
            batch = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            found.extend(batch)
            if len(batch) < 100:
                return found
            page += 1

    def repo(self, path: str) -> str:
        return f"/repos/{self.repository}{path}"

    def comment(self, number: int, body: str) -> None:
        self.request("POST", self.repo(f"/issues/{number}/comments"), {"body": body})

    def open_items(self, **filters: str) -> list[dict]:
        query = urllib.parse.urlencode({"state": "open", **filters})
        return self.every(self.repo(f"/issues?{query}"))

    def ensure_claimed_label(self) -> None:
        try:
            self.request("GET", self.repo(f"/labels/{urllib.parse.quote(CLAIMED)}"))
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            self.request(
                "POST",
                self.repo("/labels"),
                {"name": CLAIMED, "color": CLAIMED_COLOR, "description": CLAIMED_DESCRIPTION},
            )

    def release(self, number: int, login: str, others_remain: bool) -> None:
        self.request("DELETE", self.repo(f"/issues/{number}/assignees"), {"assignees": [login]})
        if others_remain:
            return
        try:
            self.request(
                "DELETE", self.repo(f"/issues/{number}/labels/{urllib.parse.quote(CLAIMED)}")
            )
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise


def open_claims(github: GitHub, login: str) -> int:
    return sum(
        1
        for item in github.open_items(assignee=login, labels=CLAIMED)
        if "pull_request" not in item
    )


def suggestions(github: GitHub, current: int) -> str:
    free = [
        item
        for item in github.open_items(labels=SUGGESTED_LABEL, assignee="none")
        if "pull_request" not in item and int(item["number"]) != current
    ][:SUGGESTIONS]
    if not free:
        return (
            "There is no other free good first issue right now: watch the repository for new ones."
        )
    return "\n".join(f"- #{item['number']} {item['title']}" for item in free)


def reminder_mark(login: str) -> str:
    return REMINDER_MARK.format(user=login.lower())


def handle_comment(event: dict, github: GitHub, phrases: Phrases) -> str:
    user = event["comment"]["user"]
    login = str(user["login"])
    body = str(event["comment"].get("body") or "")
    if is_bot(user) or not (is_claim(body, phrases) or is_release(body, phrases)):
        return IGNORE
    issue = as_issue(github.request("GET", github.repo(f"/issues/{event['issue']['number']}")))
    claims = open_claims(github, login) if is_claim(body, phrases) and not issue.assignees else 0
    action = decide(body, login, issue, claims, phrases, commenter_is_bot=is_bot(user))
    if action == ASSIGN:
        github.request(
            "POST", github.repo(f"/issues/{issue.number}/assignees"), {"assignees": [login]}
        )
        github.ensure_claimed_label()
        github.request("POST", github.repo(f"/issues/{issue.number}/labels"), {"labels": [CLAIMED]})
        github.comment(issue.number, reply("assigned", user=login, issue=issue.number))
    elif action == TAKEN:
        github.comment(
            issue.number, reply("taken", user=login, suggestions=suggestions(github, issue.number))
        )
    elif action == LIMIT:
        github.comment(issue.number, reply("limit", user=login))
    elif action == UNASSIGN:
        others = [name for name in issue.assignees if not same_login(name, login)]
        github.release(issue.number, login, bool(others))
        github.comment(issue.number, reply("unassigned", user=login))
    return action


def last_activity(
    login: str, events: list[dict], comments: list[dict], fallback: datetime
) -> datetime:
    times = [
        timestamp(event["created_at"])
        for event in events
        if event.get("event") == "assigned"
        and same_login(str((event.get("assignee") or {}).get("login", "")), login)
    ]
    times += [
        timestamp(comment["created_at"])
        for comment in comments
        if same_login(str(comment["user"]["login"]), login)
    ]
    return max(times, default=fallback)


def handle_stale(github: GitHub, now: datetime) -> list[tuple[int, str, str]]:
    items = github.open_items()
    pull_requests = [item for item in items if "pull_request" in item]
    done = []
    for data in items:
        issue = as_issue(data)
        if issue.is_pull_request or CLAIMED not in issue.labels:
            continue
        events = github.every(github.repo(f"/issues/{issue.number}/events"))
        comments = github.every(github.repo(f"/issues/{issue.number}/comments"))
        released = []
        for login in issue.assignees:
            since = last_activity(login, events, comments, timestamp(data["created_at"]))
            reminded = any(
                is_bot(comment["user"])
                and reminder_mark(login) in str(comment.get("body") or "").lower()
                and timestamp(comment["created_at"]) > since
                for comment in comments
            )
            has_pull_request = any(
                same_login(str(pull["user"]["login"]), login)
                and mentions(pull, issue.number, github.repository)
                for pull in pull_requests
            )
            action = stale_action(now, since, reminded, has_pull_request)
            if action == REMIND:
                github.comment(
                    issue.number,
                    reply(
                        "stale-reminder", user=login, issue=issue.number, mark=reminder_mark(login)
                    ),
                )
            elif action == RELEASE:
                released.append(login)
                remaining = [name for name in issue.assignees if name not in released]
                github.release(issue.number, login, bool(remaining))
                github.comment(
                    issue.number, reply("stale-released", user=login, issue=issue.number)
                )
            done.append((issue.number, login, action))
    return done


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    environ = dict(os.environ) if environ is None else environ
    if argv not in (["comment"], ["stale"]):
        print("usage: claims.py comment | stale", file=sys.stderr)
        return 2
    github = GitHub(environ["GITHUB_REPOSITORY"], environ["GITHUB_TOKEN"])
    if argv == ["comment"]:
        event = json.loads(Path(environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        print(handle_comment(event, github, load_phrases()))
        return 0
    for number, login, action in handle_stale(github, datetime.now(timezone.utc)):
        print(f"#{number} {login}: {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
