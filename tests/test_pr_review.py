import json

import pytest

from scripts import pr_review


def _threads_payload() -> str:
    def node(tid: str, resolved: bool, login: str) -> dict:
        return {
            "id": tid,
            "isResolved": resolved,
            "isOutdated": False,
            "path": "a.py",
            "line": 3,
            "comments": {
                "nodes": [{"databaseId": 11, "author": {"login": login}, "body": "fix", "url": "u"}]
            },
        }

    nodes = [node("T1", False, "copilot-pull-request-reviewer"), node("T2", True, "jaspax")]
    return json.dumps(
        {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}}
    )


def test_threads_skips_resolved_and_flags_copilot():
    calls = []

    def gh(args):
        calls.append(args)
        return _threads_payload()

    out = pr_review.threads(5, gh=gh)
    assert [t["thread"] for t in out] == ["T1"]
    assert out[0]["copilot"] and out[0]["comments"][0]["id"] == 11
    assert "number=5" in calls[0]
    assert [t["thread"] for t in pr_review.threads(5, include_resolved=True, gh=gh)] == ["T1", "T2"]


def test_copilot_reviewed_reads_paginated_reviews():
    page = [
        [{"user": {"login": "someone"}}],
        [{"user": {"login": "copilot-pull-request-reviewer[bot]"}}],
    ]
    assert pr_review.copilot_reviewed(1, gh=lambda a: json.dumps(page))
    assert not pr_review.copilot_reviewed(1, gh=lambda a: json.dumps([[{"user": {"login": "x"}}]]))
    assert not pr_review.copilot_reviewed(1, gh=lambda a: "[]")


def test_wait_polls_until_reviewed_or_timeout():
    t = [0.0]
    answers = iter(
        [
            "[[]]",
            "[[]]",
            json.dumps([[{"user": {"login": "Copilot"}}]]),
            json.dumps([[{"user": {"login": "copilot-pull-request-reviewer[bot]"}}]]),
        ]
    )

    def sleep(s):
        t[0] += s

    assert pr_review.wait_for_review(
        1, 100, 30, gh=lambda a: next(answers), sleep=sleep, clock=lambda: t[0]
    )
    assert t[0] == 90

    t[0] = 0.0
    assert not pr_review.wait_for_review(
        1, 50, 30, gh=lambda a: "[[]]", sleep=sleep, clock=lambda: t[0]
    )
    assert t[0] == 30


def test_reply_posts_to_the_comment_thread_and_rejects_empty():
    calls = []

    def gh(args):
        calls.append(args)
        return json.dumps({"html_url": "https://x/1"})

    assert pr_review.reply(7, 99, "Fixed in abc.", gh=gh) == "https://x/1"
    assert "repos/jaspax/patristica/pulls/7/comments/99/replies" in calls[0]
    assert "body=Fixed in abc." in calls[0]
    with pytest.raises(ValueError):
        pr_review.reply(7, 99, "  ", gh=gh)


def test_resolve():
    out = json.dumps(
        {"data": {"resolveReviewThread": {"thread": {"id": "T1", "isResolved": True}}}}
    )
    assert pr_review.resolve("T1", gh=lambda a: out)
