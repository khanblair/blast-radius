"""Unit tests for PR delivery (agent/dossier/pr.py).

SAFETY: every test here either exercises the dry_run=True path (which must
perform zero subprocess/git/network calls) or the dry_run=False path against
a small hand-rolled fake `github_client` stub defined in this file -- NEVER
a real PyGithub `Github` instance and NEVER a real network call. See
agent/dossier/pr.py's module docstring for the full safety rationale.
"""
from __future__ import annotations

import subprocess

import pytest

from agent.dossier.pr import create_pr

DBT_FILE_PATH = "models/staging/stg_customers.sql"
PATCHED_CONTENT = "select\n    customer_id as cust_id,\n    name\nfrom {{ source('warehouse', 'raw_customers') }}\n"
ORIGINAL_CONTENT = "select\n    cust_id,\n    name\nfrom {{ source('warehouse', 'raw_customers') }}\n"
DOSSIER_MARKDOWN = "# Blast Radius Dossier -- fake dossier body for testing\n\nSTATUS: PASSED"
BRANCH_NAME = "blast-radius/raw_customers-cust_id-to-customer_id"


# --- dry_run=True: zero side effects -----------------------------------------


def test_dry_run_returns_none(monkeypatch, capsys):
    result = create_pr(
        dbt_file_path=DBT_FILE_PATH,
        patched_content=PATCHED_CONTENT,
        dossier_markdown=DOSSIER_MARKDOWN,
        branch_name=BRANCH_NAME,
        dry_run=True,
    )
    assert result is None


def test_dry_run_never_invokes_subprocess(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("dry_run must never invoke subprocess.run (no git operations)")

    monkeypatch.setattr(subprocess, "run", _forbidden)

    result = create_pr(
        dbt_file_path=DBT_FILE_PATH,
        patched_content=PATCHED_CONTENT,
        dossier_markdown=DOSSIER_MARKDOWN,
        branch_name=BRANCH_NAME,
        dry_run=True,
    )
    assert result is None


def test_dry_run_never_imports_github(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        if name == "github" or name.startswith("github."):
            raise AssertionError("dry_run must never import PyGithub")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    create_pr(
        dbt_file_path=DBT_FILE_PATH,
        patched_content=PATCHED_CONTENT,
        dossier_markdown=DOSSIER_MARKDOWN,
        branch_name=BRANCH_NAME,
        dry_run=True,
    )


def test_dry_run_preview_shows_branch_repo_diff_and_dossier_as_pr_body(capsys):
    create_pr(
        dbt_file_path=DBT_FILE_PATH,
        patched_content=PATCHED_CONTENT,
        dossier_markdown=DOSSIER_MARKDOWN,
        branch_name=BRANCH_NAME,
        repo_full_name="khanblair/blast-radius",
        base_branch="main",
        dry_run=True,
        original_content=ORIGINAL_CONTENT,
    )
    printed = capsys.readouterr().out

    assert "DRY RUN" in printed
    assert BRANCH_NAME in printed
    assert "khanblair/blast-radius" in printed
    assert DBT_FILE_PATH in printed
    # a real diff of the file change (original_content -> patched_content)
    assert "-    cust_id," in printed
    assert "+    customer_id as cust_id," in printed
    # the dossier rendered verbatim as the would-be PR body
    assert DOSSIER_MARKDOWN in printed


def test_dry_run_preview_without_original_content_shows_new_content_only(capsys):
    create_pr(
        dbt_file_path=DBT_FILE_PATH,
        patched_content=PATCHED_CONTENT,
        dossier_markdown=DOSSIER_MARKDOWN,
        branch_name=BRANCH_NAME,
        dry_run=True,
    )
    printed = capsys.readouterr().out

    assert "no pre-patch original_content supplied" in printed
    assert PATCHED_CONTENT in printed


# --- dry_run=False: exercised ONLY against a fake github_client stub --------


class FakeCommit:
    def __init__(self, sha):
        self.sha = sha


class FakeBranch:
    def __init__(self, sha):
        self.commit = FakeCommit(sha)


class FakeContentFile:
    def __init__(self, sha):
        self.sha = sha


class FakePullRequest:
    def __init__(self, html_url):
        self.html_url = html_url


class FakeRepo:
    """Stub standing in for a PyGithub Repository object -- records every
    call made to it so tests can assert on exactly what create_pr does,
    without ever touching a real PyGithub client or the network."""

    def __init__(self, existing_file_sha=None):
        self.calls = []
        self._existing_file_sha = existing_file_sha

    def get_branch(self, branch):
        self.calls.append(("get_branch", branch))
        return FakeBranch(sha="base-sha-abc123")

    def create_git_ref(self, ref, sha):
        self.calls.append(("create_git_ref", ref, sha))

    def get_contents(self, path, ref=None):
        self.calls.append(("get_contents", path, ref))
        if self._existing_file_sha is None:
            raise FileNotFoundError(f"404: {path} not found on {ref}")
        return FakeContentFile(sha=self._existing_file_sha)

    def create_file(self, path, message, content, branch):
        self.calls.append(("create_file", path, message, content, branch))

    def update_file(self, path, message, content, sha, branch):
        self.calls.append(("update_file", path, message, content, sha, branch))

    def create_pull(self, title, body, head, base):
        self.calls.append(("create_pull", title, body, head, base))
        return FakePullRequest(html_url="https://github.com/khanblair/blast-radius/pull/42")


class FakeGithubClient:
    """Stub standing in for a PyGithub `Github` instance."""

    def __init__(self, existing_file_sha=None):
        self.repo = FakeRepo(existing_file_sha=existing_file_sha)
        self.requested_repo_name = None

    def get_repo(self, full_name):
        self.requested_repo_name = full_name
        return self.repo


def test_live_path_never_constructs_a_real_github_client(monkeypatch):
    import github

    def _forbidden(*args, **kwargs):
        raise AssertionError("must never construct a real Github() client when a fake is injected")

    monkeypatch.setattr(github, "Github", _forbidden)

    fake_client = FakeGithubClient()
    create_pr(
        dbt_file_path=DBT_FILE_PATH,
        patched_content=PATCHED_CONTENT,
        dossier_markdown=DOSSIER_MARKDOWN,
        branch_name=BRANCH_NAME,
        dry_run=False,
        github_client=fake_client,
    )
    # if _forbidden had been called, the AssertionError above would have
    # propagated out of create_pr and failed this test already.


def test_live_path_creates_branch_from_base_and_new_file_when_none_exists():
    fake_client = FakeGithubClient(existing_file_sha=None)

    pr_url = create_pr(
        dbt_file_path=DBT_FILE_PATH,
        patched_content=PATCHED_CONTENT,
        dossier_markdown=DOSSIER_MARKDOWN,
        branch_name=BRANCH_NAME,
        repo_full_name="khanblair/blast-radius",
        base_branch="main",
        dry_run=False,
        github_client=fake_client,
    )

    assert pr_url == "https://github.com/khanblair/blast-radius/pull/42"
    assert fake_client.requested_repo_name == "khanblair/blast-radius"

    calls_by_kind = {c[0] for c in fake_client.repo.calls}
    assert "get_branch" in calls_by_kind
    assert ("get_branch", "main") in fake_client.repo.calls
    assert ("create_git_ref", f"refs/heads/{BRANCH_NAME}", "base-sha-abc123") in fake_client.repo.calls

    create_file_calls = [c for c in fake_client.repo.calls if c[0] == "create_file"]
    assert len(create_file_calls) == 1
    _, path, _, content, branch = create_file_calls[0]
    assert path == DBT_FILE_PATH
    assert content == PATCHED_CONTENT
    assert branch == BRANCH_NAME

    assert not [c for c in fake_client.repo.calls if c[0] == "update_file"]

    create_pull_calls = [c for c in fake_client.repo.calls if c[0] == "create_pull"]
    assert len(create_pull_calls) == 1
    _, _, body, head, base = create_pull_calls[0]
    assert body == DOSSIER_MARKDOWN
    assert head == BRANCH_NAME
    assert base == "main"


def test_live_path_updates_existing_file_with_its_sha():
    fake_client = FakeGithubClient(existing_file_sha="existing-sha-999")

    create_pr(
        dbt_file_path=DBT_FILE_PATH,
        patched_content=PATCHED_CONTENT,
        dossier_markdown=DOSSIER_MARKDOWN,
        branch_name=BRANCH_NAME,
        dry_run=False,
        github_client=fake_client,
    )

    update_file_calls = [c for c in fake_client.repo.calls if c[0] == "update_file"]
    assert len(update_file_calls) == 1
    _, path, _, content, sha, branch = update_file_calls[0]
    assert path == DBT_FILE_PATH
    assert content == PATCHED_CONTENT
    assert sha == "existing-sha-999"
    assert branch == BRANCH_NAME

    assert not [c for c in fake_client.repo.calls if c[0] == "create_file"]
