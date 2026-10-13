# SPDX-License-Identifier: Apache-2.0
import importlib.util
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "claims.py"


def load_claims():
    spec = importlib.util.spec_from_file_location("kit_stale_claims", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


claims = load_claims()
NOW = datetime(2026, 10, 30, 6, 17, tzinfo=timezone.utc)


def ago(days, hours=0):
    return NOW - timedelta(days=days, hours=hours)


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGitHub(claims.GitHub):
    def __init__(self, items, events=None, comments=None):
        super().__init__("example/kit", "token")
        self.items = items
        self.events = events or {}
        self.comments = comments or {}
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        url = urllib.parse.urlsplit(path.removeprefix("/repos/example/kit"))
        page = dict(urllib.parse.parse_qsl(url.query)).get("page")
        parts = url.path.strip("/").split("/")
        if method != "GET":
            return None
        if page != "1":
            return []
        if parts == ["issues"]:
            return self.items
        number = int(parts[1])
        return self.events.get(number, []) if parts[2] == "events" else self.comments.get(number, [])

    def written(self):
        return [(method, path.removeprefix("/repos/example/kit"), body)
                for method, path, body in self.calls if method != "GET"]


def claimed(number=7, assignees=("ada",), created=None):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "labels": [{"name": "good first issue"}, {"name": "claimed"}],
        "assignees": [{"login": login} for login in assignees],
        "created_at": stamp(created or ago(30)),
    }


def assigned(login, when):
    return {"event": "assigned", "assignee": {"login": login}, "created_at": stamp(when)}


def comment(login, when, body="Still on it", kind="User"):
    return {"user": {"login": login, "type": kind}, "created_at": stamp(when), "body": body}


def reminder(login, when):
    return comment("github-actions[bot]", when, body=claims.reminder_mark(login) + f"\nHi @{login}", kind="Bot")


def pull_request(login, body, number=40):
    return {"number": number, "title": "A change", "body": body, "state": "open", "labels": [], "assignees": [],
            "user": {"login": login}, "pull_request": {}, "created_at": stamp(ago(1))}


class TestRules:
    @pytest.mark.parametrize(
        ("idle", "reminded", "expected"),
        [
            (ago(6, 23), False, claims.NOTHING),
            (ago(7), False, claims.REMIND),
            (ago(7), True, claims.NOTHING),
            (ago(13, 23), True, claims.NOTHING),
            (ago(14), True, claims.RELEASE),
            (ago(14), False, claims.RELEASE),
        ],
    )
    def test_a_reminder_at_seven_days_and_a_release_at_fourteen(self, idle, reminded, expected):
        assert claims.stale_action(NOW, idle, reminded, has_open_pull_request=False) == expected

    def test_an_open_pull_request_keeps_the_claim(self):
        assert claims.stale_action(NOW, ago(30), False, has_open_pull_request=True) == claims.NOTHING

    @pytest.mark.parametrize(
        "text",
        ["Fixes #7", "Part of #7.", "(#7)", "Fixes example/kit#7", "Closes https://github.com/example/kit/issues/7"],
    )
    def test_a_pull_request_mentions_the_issue_by_number_or_link(self, text):
        assert claims.mentions({"title": "A change", "body": text}, 7, "example/kit")
        assert claims.mentions({"title": text, "body": None}, 7, "example/kit")

    @pytest.mark.parametrize(
        "text",
        ["Fixes #70", "Fixes other/repo#7", "See https://github.com/other/repo/issues/7", "issue 7", ""],
    )
    def test_another_number_or_another_repository_is_not_a_mention(self, text):
        assert not claims.mentions({"title": "A change", "body": text}, 7, "example/kit")

    def test_the_last_activity_is_the_assignment_or_the_assignees_last_comment(self):
        events = [assigned("ada", ago(10)), assigned("grace", ago(2))]
        comments = [comment("ada", ago(9)), comment("grace", ago(1)), comment("Ada", ago(8))]
        assert claims.last_activity("ada", events, comments, ago(30)) == ago(8)
        assert claims.last_activity("lin", events, comments, ago(30)) == ago(30)


class TestHandleStale:
    def test_seven_quiet_days_bring_one_reminder(self):
        github = FakeGitHub([claimed()], events={7: [assigned("ada", ago(8))]})
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.REMIND)]
        (method, path, body), = github.written()
        assert (method, path) == ("POST", "/issues/7/comments")
        assert body["body"].startswith(claims.reminder_mark("ada"))
        assert "Hi @ada, how is #7 going?" in body["body"]

    def test_the_reminder_is_not_sent_twice(self):
        comments = {7: [reminder("ada", ago(1))]}
        github = FakeGitHub([claimed()], events={7: [assigned("ada", ago(8))]}, comments=comments)
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.NOTHING)]
        assert github.written() == []

    def test_a_reminder_for_someone_else_does_not_count(self):
        comments = {7: [reminder("grace", ago(1))]}
        github = FakeGitHub([claimed()], events={7: [assigned("ada", ago(8))]}, comments=comments)
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.REMIND)]

    def test_a_reminder_mark_written_by_a_person_does_not_count(self):
        comments = {7: [comment("mallory", ago(1), body=claims.reminder_mark("ada"))]}
        github = FakeGitHub([claimed()], events={7: [assigned("ada", ago(8))]}, comments=comments)
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.REMIND)]

    def test_a_reminder_older_than_the_last_activity_does_not_count(self):
        comments = {7: [reminder("ada", ago(12)), comment("ada", ago(10))]}
        github = FakeGitHub([claimed()], events={7: [assigned("ada", ago(20))]}, comments=comments)
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.REMIND)]

    def test_a_comment_from_the_assignee_restarts_the_clock(self):
        github = FakeGitHub([claimed()], events={7: [assigned("ada", ago(20))]}, comments={7: [comment("ada", ago(3))]})
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.NOTHING)]

    def test_fourteen_quiet_days_release_the_issue(self):
        github = FakeGitHub([claimed()], events={7: [assigned("ada", ago(15))]})
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.RELEASE)]
        written = github.written()
        assert written[:2] == [
            ("DELETE", "/issues/7/assignees", {"assignees": ["ada"]}),
            ("DELETE", "/issues/7/labels/claimed", None),
        ]
        assert "is unassigned and free again" in written[2][2]["body"]

    def test_the_label_stays_while_another_assignee_holds_the_issue(self):
        events = {7: [assigned("ada", ago(15)), assigned("grace", ago(2))]}
        github = FakeGitHub([claimed(assignees=("ada", "grace"))], events=events)
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.RELEASE), (7, "grace", claims.NOTHING)]
        assert ("DELETE", "/issues/7/labels/claimed", None) not in github.written()

    def test_an_open_pull_request_from_the_assignee_that_mentions_the_issue_keeps_it(self):
        items = [claimed(), pull_request("ada", "Fixes #7")]
        github = FakeGitHub(items, events={7: [assigned("ada", ago(20))]})
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.NOTHING)]

    def test_a_pull_request_from_someone_else_or_about_another_issue_does_not(self):
        items = [claimed(), pull_request("grace", "Fixes #7"), pull_request("ada", "Fixes #71", number=41)]
        github = FakeGitHub(items, events={7: [assigned("ada", ago(20))]})
        assert claims.handle_stale(github, NOW) == [(7, "ada", claims.RELEASE)]

    def test_issues_without_the_claimed_label_are_left_alone(self):
        unclaimed = dict(claimed(), labels=[{"name": "good first issue"}])
        github = FakeGitHub([unclaimed], events={7: [assigned("ada", ago(20))]})
        assert claims.handle_stale(github, NOW) == []
        assert github.calls == [("GET", "/repos/example/kit/issues?state=open&per_page=100&page=1", None)]
