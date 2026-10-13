# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
import re
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "claims.py"


def load_claims():
    spec = importlib.util.spec_from_file_location("kit_claims_bot", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


claims = load_claims()
PHRASES = claims.load_phrases()


def issue(number=7, state="open", labels=("good first issue",), assignees=(), pull_request=False):
    return claims.Issue(number, state, frozenset(labels), tuple(assignees), pull_request)


def decide(body, commenter="ada", open_claims=0, bot=False, **fields):
    return claims.decide(body, commenter, issue(**fields), open_claims, PHRASES, commenter_is_bot=bot)


class FakeGitHub(claims.GitHub):
    def __init__(self, items, labels=("claimed",)):
        super().__init__("example/kit", "token")
        self.items = {item["number"]: item for item in items}
        self.labels = set(labels)
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        url = urllib.parse.urlsplit(path.removeprefix("/repos/example/kit"))
        query = dict(urllib.parse.parse_qsl(url.query))
        parts = url.path.strip("/").split("/")
        if method == "GET" and parts == ["issues"]:
            return self.open_issues(query) if query.get("page") == "1" else []
        if method == "GET" and parts[0] == "issues" and len(parts) == 2:
            return self.items[int(parts[1])]
        if method == "GET" and parts[0] == "labels":
            if urllib.parse.unquote(parts[1]) not in self.labels:
                raise urllib.error.HTTPError(path, 404, "Not Found", None, None)
            return {"name": parts[1]}
        if method == "POST" and parts == ["labels"]:
            self.labels.add(body["name"])
        return None

    def open_issues(self, query):
        found = [item for item in self.items.values() if item["state"] == "open"]
        if "labels" in query:
            found = [item for item in found if query["labels"] in {label["name"] for label in item["labels"]}]
        if query.get("assignee") == "none":
            found = [item for item in found if not item["assignees"]]
        elif "assignee" in query:
            found = [item for item in found if query["assignee"] in {user["login"] for user in item["assignees"]}]
        return found

    def written(self):
        return [(method, path.removeprefix("/repos/example/kit"), body)
                for method, path, body in self.calls if method != "GET"]

    def comments(self):
        return [body["body"] for method, path, body in self.calls if path.endswith("/comments")]


def item(number, labels=("good first issue",), assignees=(), title=None, pull_request=False, state="open"):
    data = {
        "number": number,
        "title": title or f"Issue {number}",
        "state": state,
        "labels": [{"name": label} for label in labels],
        "assignees": [{"login": login} for login in assignees],
        "created_at": "2026-10-01T00:00:00Z",
    }
    if pull_request:
        data["pull_request"] = {}
    return data


def comment_event(number, body, login="ada", user_type="User", issue_data=None):
    return {
        "comment": {"body": body, "user": {"login": login, "type": user_type}},
        "issue": issue_data or {"number": number, "labels": [], "assignees": []},
    }


class TestPhrases:
    @pytest.mark.parametrize(
        "body",
        [
            "I'd like to work on this!",
            "I’d like to work on this one",
            "Hello! I would like to work on this issue.",
            "Can I work on this?",
            "may I work on it",
            "I WANT TO WORK ON this",
            "Please assign me",
            "Je voudrais travailler sur ce ticket.",
            "Bonjour, je peux m’en occuper ?",
            "je peux m'en occuper",
            "/assign",
            "/take",
            "  /assign please",
            "Looks fun.\n/take",
            "Like this:\n```\nrun()\n```\n/take",
        ],
    )
    def test_a_claim_in_english_or_french_or_a_command(self, body):
        assert claims.is_claim(body, PHRASES)

    @pytest.mark.parametrize(
        "body",
        [
            "> I'd like to work on this",
            "Nice idea, thanks",
            "/assignee",
            "/taken",
            "I'd like someone to work on this",
            "type /assign to claim it",
            "Je voudrais savoir comment",
            "Sorry, please unassign me",
            "Can you reassign me?",
            "We should assign metadata to each run",
            "/assign @grace",
            "/take @grace",
            "Run this:\n```\n/assign\n```",
            "~~~\nI'd like to work on this\n~~~",
        ],
    )
    def test_quotes_code_other_words_and_commands_for_someone_else_are_not_claims(self, body):
        assert not claims.is_claim(body, PHRASES)

    def test_unassign_is_a_command_at_the_start_of_a_line(self):
        assert claims.is_release("/unassign", PHRASES)
        assert claims.is_release("Sorry, no time.\n/unassign", PHRASES)
        assert not claims.is_release("/unassigned", PHRASES)
        assert not claims.is_release("please /unassign me", PHRASES)
        assert not claims.is_release("/unassign @grace", PHRASES)

    def test_the_phrases_file_holds_the_english_and_french_phrases_and_the_commands(self):
        data = json.loads((SCRIPT.parents[1] / "claim-phrases.json").read_text(encoding="utf-8"))
        assert data == {
            "phrases": [
                "I'd like to work on",
                "I would like to work on",
                "can I work on",
                "may I work on",
                "I want to work on",
                "assign me",
                "je voudrais travailler sur",
                "je peux m'en occuper",
            ],
            "commands": ["/assign", "/take"],
            "release": ["/unassign"],
        }


class TestDecisions:
    def test_a_free_eligible_issue_is_assigned(self):
        assert decide("I'd like to work on this") == claims.ASSIGN
        assert decide("/take", labels=("help wanted",)) == claims.ASSIGN

    def test_an_issue_held_by_someone_else_is_taken(self):
        assert decide("Can I work on this?", assignees=("grace",)) == claims.TAKEN

    def test_two_open_claims_is_the_limit(self):
        assert decide("/assign", open_claims=1) == claims.ASSIGN
        assert decide("/assign", open_claims=2) == claims.LIMIT

    def test_the_assignee_can_give_the_issue_back_and_nobody_else_can(self):
        assert decide("/unassign", commenter="Ada", assignees=("ada",)) == claims.UNASSIGN
        assert decide("/unassign", commenter="grace", assignees=("ada",)) == claims.IGNORE

    @pytest.mark.parametrize(
        "fields",
        [{"state": "closed"}, {"labels": ()}, {"labels": ("bug", "enhancement")}],
    )
    def test_a_closed_or_unlabelled_issue_is_not_eligible(self, fields):
        assert decide("I'd like to work on this", **fields) == claims.NOT_ELIGIBLE

    def test_bots_pull_requests_ordinary_comments_and_the_assignee_are_ignored(self):
        assert decide("/assign", bot=True) == claims.IGNORE
        assert decide("/assign", pull_request=True) == claims.IGNORE
        assert decide("Thanks for the report") == claims.IGNORE
        assert decide("/assign", assignees=("ada",)) == claims.IGNORE


class TestReplies:
    @pytest.mark.parametrize("name", ["assigned", "taken", "limit", "unassigned", "stale-reminder", "stale-released"])
    def test_every_placeholder_is_filled(self, name):
        text = claims.reply(name, user="ada", issue=7, suggestions="- #8 Issue 8", mark=claims.reminder_mark("ada"))
        assert re.search(r"\{[a-z_]+\}", text) is None
        assert "@ada" in text

    def test_the_assigned_reply_gives_the_steps_and_the_rules(self):
        text = claims.reply("assigned", user="ada", issue=7)
        for expected in ("`7-<short-name>`", "git commit -s", 'pip install -e ".[test]"', "Fixes #7",
                         "within 7 days", "at most 2 claimed", "`/unassign`", "After 14 days"):
            assert expected in text


class TestHandleComment:
    def test_a_claim_assigns_labels_and_replies_and_creates_the_label_if_missing(self):
        github = FakeGitHub([item(7)], labels=())
        assert claims.handle_comment(comment_event(7, "I'd like to work on this"), github, PHRASES) == claims.ASSIGN
        written = github.written()
        assert written[0] == ("POST", "/issues/7/assignees", {"assignees": ["ada"]})
        assert written[1] == ("POST", "/labels", {"name": "claimed", "color": "c5def5",
                                                   "description": "Someone is working on this issue"})
        assert written[2] == ("POST", "/issues/7/labels", {"labels": ["claimed"]})
        assert "issue #7 is yours" in github.comments()[0]

    def test_the_issue_is_read_again_so_an_older_event_does_not_assign_twice(self):
        github = FakeGitHub([item(7, assignees=("grace",)), item(8), item(9, pull_request=True)])
        stale_event = comment_event(7, "/assign", issue_data=item(7))
        assert claims.handle_comment(stale_event, github, PHRASES) == claims.TAKEN
        assert ("POST", "/issues/7/assignees", {"assignees": ["ada"]}) not in github.written()

    def test_a_taken_issue_lists_up_to_five_free_good_first_issues(self):
        free = [item(number) for number in range(10, 17)]
        others = [item(8, assignees=("lin",)), item(9, pull_request=True), item(20, labels=("help wanted",))]
        github = FakeGitHub([item(7, assignees=("grace",)), *free, *others])
        claims.handle_comment(comment_event(7, "Can I work on this?"), github, PHRASES)
        listed = re.findall(r"^- #(\d+) ", github.comments()[0], re.MULTILINE)
        assert listed == ["10", "11", "12", "13", "14"]

    def test_no_free_issue_says_so(self):
        github = FakeGitHub([item(7, assignees=("grace",))])
        claims.handle_comment(comment_event(7, "/take"), github, PHRASES)
        assert "no other free good first issue" in github.comments()[0]

    def test_the_limit_counts_open_claimed_issues_of_the_commenter(self):
        held = [item(1, labels=("good first issue", "claimed"), assignees=("ada",)),
                item(2, labels=("help wanted", "claimed"), assignees=("ada",))]
        github = FakeGitHub([item(7), *held])
        assert claims.handle_comment(comment_event(7, "/assign"), github, PHRASES) == claims.LIMIT
        assert "already hold 2 claimed issues" in github.comments()[0]
        assert not any(path.endswith("/assignees") for _, path, _ in github.written())

    def test_unassign_removes_the_assignee_and_the_label(self):
        github = FakeGitHub([item(7, labels=("good first issue", "claimed"), assignees=("ada",))])
        assert claims.handle_comment(comment_event(7, "/unassign"), github, PHRASES) == claims.UNASSIGN
        assert github.written()[:2] == [
            ("DELETE", "/issues/7/assignees", {"assignees": ["ada"]}),
            ("DELETE", "/issues/7/labels/claimed", None),
        ]
        assert "free again" in github.comments()[0]

    def test_an_ordinary_comment_or_a_bot_makes_no_request(self):
        github = FakeGitHub([item(7)])
        assert claims.handle_comment(comment_event(7, "Thanks!"), github, PHRASES) == claims.IGNORE
        bot = comment_event(7, "/assign", login="helper[bot]", user_type="Bot")
        assert claims.handle_comment(bot, github, PHRASES) == claims.IGNORE
        assert github.calls == []

    def test_a_claim_on_an_issue_that_is_not_eligible_changes_nothing(self):
        github = FakeGitHub([item(7, labels=("bug",))])
        assert claims.handle_comment(comment_event(7, "/assign"), github, PHRASES) == claims.NOT_ELIGIBLE
        assert github.written() == []


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"" if self.payload is None else json.dumps(self.payload).encode("utf-8")


class Api:
    def __init__(self):
        self.sent = []
        self.replies = []

    def urlopen(self, request, timeout):
        self.sent.append((request, timeout))
        answer = self.replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Response(answer)


class TestGitHubApi:
    @pytest.fixture
    def api(self, monkeypatch):
        api = Api()
        monkeypatch.setattr(claims.urllib.request, "urlopen", api.urlopen)
        return api

    def test_a_request_sends_the_token_the_api_version_and_a_json_body(self, api):
        api.replies.append({"id": 1})
        github = claims.GitHub("example/kit", "secret")
        assert github.request("POST", "/repos/example/kit/issues/7/comments", {"body": "Hi"}) == {"id": 1}
        request, timeout = api.sent[0]
        assert (request.get_method(), request.full_url) == ("POST", "https://api.github.com/repos/example/kit/issues/7/comments")
        assert request.get_header("Authorization") == "Bearer secret"
        assert request.get_header("Accept") == "application/vnd.github+json"
        assert request.get_header("X-github-api-version") == "2022-11-28"
        assert json.loads(request.data) == {"body": "Hi"}
        assert timeout == 30

    def test_an_empty_answer_is_none_and_a_get_has_no_body(self, api):
        api.replies.append(None)
        assert claims.GitHub("example/kit", "secret").request("GET", "/repos/example/kit/labels/claimed") is None
        assert api.sent[0][0].data is None

    def test_every_page_is_read_until_one_is_not_full(self, api):
        api.replies.extend([[{"number": n} for n in range(100)], [{"number": n} for n in range(100, 103)]])
        github = claims.GitHub("example/kit", "secret")
        found = github.open_items(labels="good first issue", assignee="none")
        assert [item["number"] for item in found] == list(range(103))
        assert [request.full_url for request, _ in api.sent] == [
            "https://api.github.com/repos/example/kit/issues?state=open&labels=good+first+issue&assignee=none"
            f"&per_page=100&page={page}"
            for page in (1, 2)
        ]

    def test_a_path_without_a_query_gets_one(self, api):
        api.replies.append([])
        assert claims.GitHub("example/kit", "secret").every("/repos/example/kit/issues/7/events") == []
        assert api.sent[0][0].full_url.endswith("/issues/7/events?per_page=100&page=1")

    def test_the_claimed_label_is_created_only_when_it_is_missing(self, api):
        missing = urllib.error.HTTPError("url", 404, "Not Found", None, None)
        api.replies.extend([missing, {"name": "claimed"}, {"name": "claimed"}])
        github = claims.GitHub("example/kit", "secret")
        github.ensure_claimed_label()
        github.ensure_claimed_label()
        assert [(request.get_method(), request.full_url.rsplit("/kit", 1)[1]) for request, _ in api.sent] == [
            ("GET", "/labels/claimed"), ("POST", "/labels"), ("GET", "/labels/claimed"),
        ]

    def test_other_errors_are_not_hidden(self, api):
        api.replies.append(urllib.error.HTTPError("url", 500, "Server Error", None, None))
        with pytest.raises(urllib.error.HTTPError):
            claims.GitHub("example/kit", "secret").ensure_claimed_label()


def test_main_needs_one_known_command():
    assert claims.main([], {}) == 2
    assert claims.main(["assign"], {}) == 2
