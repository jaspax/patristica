"""
Review comments on a pull request, for agents acting on them (#815).

Every PR gets a Copilot code review a few minutes after it opens (sometimes
hours). An agent that opens a PR reads the review's threads, fixes what is
right, and replies to and resolves each thread, so the owner sees what was
done. This wraps the few ``gh api`` calls that takes, so the nightly agent's
allowlist (``.claude/settings.json``) can name one command instead of a raw
``gh api`` (which could also merge or close PRs):

- ``wait PR`` waits until Copilot has reviewed the PR (default up to 9 minutes,
  under a foreground Bash call's limit) and prints whether it did; exit 0 when
  reviewed, 3 when not yet.
- ``threads PR`` prints the unresolved review threads as JSON: thread id, path,
  line, whether it is outdated, and its comments (id, author, body).
  ``--all`` includes resolved threads.
- ``reply PR COMMENT_ID --body-file F`` replies in the thread of a review
  comment (the first comment's ``id`` from ``threads``).
- ``resolve THREAD_ID`` marks a thread resolved (the ``thread`` id).

Usage::

    python -m scripts.pr_review wait 812
    python -m scripts.pr_review threads 812
    python -m scripts.pr_review reply 812 2551234567 --body-file logs/reply.md
    python -m scripts.pr_review resolve PRRT_kwDOR0Dgm868KoIO
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = "jaspax/patristica"
# REST spells the bot's login with "[bot]", GraphQL without.
COPILOT_LOGIN = "copilot-pull-request-reviewer"
EXIT_NOT_REVIEWED = 3

THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          id isResolved isOutdated path line
          comments(first: 50) { nodes { databaseId author { login } body url } }
        }
      }
    }
  }
}
"""

RESOLVE_MUTATION = """
mutation($thread: ID!) {
  resolveReviewThread(input: {threadId: $thread}) { thread { id isResolved } }
}
"""

Runner = Callable[[list[str]], str]


class GhError(RuntimeError):
    """A ``gh`` call failed."""


def run_gh(args: list[str]) -> str:
    """Run ``gh`` with ``args`` and return its stdout."""
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhError(f"gh {' '.join(args[:3])} … failed: {proc.stderr.strip()}")
    return proc.stdout


def is_copilot(login: str | None) -> bool:
    return bool(login) and login.removesuffix("[bot]") == COPILOT_LOGIN


def copilot_reviewed(pr: int, gh: Runner = run_gh, repo: str = REPO) -> bool:
    """Whether Copilot has submitted a review of the PR."""
    reviews = json.loads(gh(["api", f"repos/{repo}/pulls/{pr}/reviews", "--paginate", "--slurp"]))
    flat = (
        [r for page in reviews for r in page]
        if reviews and isinstance(reviews[0], list)
        else reviews
    )
    return any(is_copilot((r.get("user") or {}).get("login")) for r in flat)


def wait_for_review(
    pr: int,
    timeout: float,
    interval: float,
    gh: Runner = run_gh,
    repo: str = REPO,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Poll until Copilot has reviewed ``pr`` or ``timeout`` seconds pass."""
    end = clock() + timeout
    while True:
        if copilot_reviewed(pr, gh, repo):
            return True
        if clock() + interval > end:
            return False
        sleep(interval)


def threads(
    pr: int, include_resolved: bool = False, gh: Runner = run_gh, repo: str = REPO
) -> list[dict[str, Any]]:
    """The PR's review threads, unresolved ones only unless ``include_resolved``."""
    owner, name = repo.split("/")
    out = json.loads(
        gh(
            [
                "api",
                "graphql",
                "-f",
                f"query={THREADS_QUERY}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={pr}",
            ]
        )
    )
    nodes = out["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    result = []
    for t in nodes:
        if t["isResolved"] and not include_resolved:
            continue
        comments = [
            {
                "id": c["databaseId"],
                "author": (c.get("author") or {}).get("login"),
                "body": c["body"],
                "url": c.get("url"),
            }
            for c in t["comments"]["nodes"]
        ]
        result.append(
            {
                "thread": t["id"],
                "resolved": t["isResolved"],
                "outdated": t["isOutdated"],
                "path": t["path"],
                "line": t["line"],
                "copilot": bool(comments) and is_copilot(comments[0]["author"]),
                "comments": comments,
            }
        )
    return result


def reply(pr: int, comment_id: int, body: str, gh: Runner = run_gh, repo: str = REPO) -> str:
    """Reply in the thread of review comment ``comment_id``; returns the reply's URL."""
    if not body.strip():
        raise ValueError("the reply is empty")
    out = json.loads(
        gh(
            [
                "api",
                "-X",
                "POST",
                f"repos/{repo}/pulls/{pr}/comments/{comment_id}/replies",
                "-f",
                f"body={body}",
            ]
        )
    )
    return out.get("html_url", "")


def resolve(thread_id: str, gh: Runner = run_gh) -> bool:
    out = json.loads(
        gh(["api", "graphql", "-f", f"query={RESOLVE_MUTATION}", "-F", f"thread={thread_id}"])
    )
    return bool(out["data"]["resolveReviewThread"]["thread"]["isResolved"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.pr_review", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--repo", default=REPO)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("wait", help="wait for Copilot's review")
    p.add_argument("pr", type=int)
    p.add_argument("--timeout", type=float, default=540, help="seconds (default 540)")
    p.add_argument("--interval", type=float, default=30, help="seconds between checks (default 30)")
    p = sub.add_parser("threads", help="unresolved review threads as JSON")
    p.add_argument("pr", type=int)
    p.add_argument("--all", action="store_true", help="include resolved threads")
    p = sub.add_parser("reply", help="reply in a review comment's thread")
    p.add_argument("pr", type=int)
    p.add_argument("comment_id", type=int)
    p.add_argument("--body-file", type=Path, required=True)
    p = sub.add_parser("resolve", help="resolve a review thread")
    p.add_argument("thread_id")
    args = parser.parse_args(argv)

    if args.cmd == "wait":
        done = wait_for_review(args.pr, args.timeout, args.interval, repo=args.repo)
        print(json.dumps({"pr": args.pr, "copilot_reviewed": done}))
        return 0 if done else EXIT_NOT_REVIEWED
    if args.cmd == "threads":
        print(json.dumps(threads(args.pr, args.all, repo=args.repo), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "reply":
        print(
            reply(
                args.pr, args.comment_id, args.body_file.read_text(encoding="utf-8"), repo=args.repo
            )
        )
        return 0
    print(json.dumps({"thread": args.thread_id, "resolved": resolve(args.thread_id)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
