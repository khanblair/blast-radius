"""PR delivery (spec Stage 6 "Deliver" / Loop 4 gate #2): hand the verified,
self-corrected patch -- plus its dossier as justification -- to a human as a
pull request, rather than merging on autopilot.

SAFETY-CRITICAL MODULE. Read this docstring before changing anything here.

`dry_run=True` (the default, and the ONLY mode this codebase's own tests or
live-verification runs ever exercise) performs ZERO git or GitHub operations
of any kind -- not a subprocess call, not an import of `github`, nothing that
touches the network or the filesystem beyond printing. It only ever builds
and returns a text preview.

`dry_run=False` is built for completeness (a real Loop-4-gate-#2 "open the
PR" action some future, deliberately-invoked run could use) but is
deliberately implemented WITHOUT any local git at all: rather than cloning
`repo_full_name` into a temp directory and shelling out to `git`, it does the
whole thing through PyGithub's Contents/Git-Refs API (`get_branch` ->
`create_git_ref` -> `create_file`/`update_file` -> `create_pull`). This is a
deliberate deviation from a literal "clone to temp dir, `git commit`, `git
push`" implementation: it is strictly safer, because there is no local `git`
subprocess invocation anywhere in this module, in any mode -- there is
nothing that could ever be pointed, by a bug or a bad cwd, at this actual
working directory's git state. The GitHub API is the only side effect
surface, and even that is only reached when `dry_run=False` AND a caller
explicitly provides or triggers construction of a real `github_client`.

Per the task's absolute safety rules: `github_client` is injectable
specifically so tests can pass a fake/mock stub and assert on the calls made
to it -- a real `Github(...)` instance is only ever constructed lazily,
inside the `dry_run=False` branch, and only when the caller passed
`github_client=None`. Neither this module's own tests nor this task's live
verification run ever take that branch.
"""
from __future__ import annotations

import difflib


def _diff_block(original_content: str | None, patched_content: str, dbt_file_path: str) -> str:
    if original_content is None:
        return (
            f"(no pre-patch original_content supplied -- showing new content only)\n\n"
            f"```\n{patched_content}\n```"
        )
    diff_lines = list(
        difflib.unified_diff(
            original_content.splitlines(keepends=True),
            patched_content.splitlines(keepends=True),
            fromfile=f"{dbt_file_path} (before)",
            tofile=f"{dbt_file_path} (after)",
        )
    )
    if not diff_lines:
        return "_No textual difference._"
    diff_text = "".join(diff_lines)
    if not diff_text.endswith("\n"):
        diff_text += "\n"
    return f"```diff\n{diff_text}```"


def render_dry_run_preview(
    dbt_file_path: str,
    patched_content: str,
    dossier_markdown: str,
    branch_name: str,
    repo_full_name: str,
    base_branch: str,
    original_content: str | None = None,
) -> str:
    """Builds the dry-run preview text. Factored out from `create_pr` so it
    can be unit-tested directly and so `create_pr`'s dry-run branch is a
    trivial print+return with no logic of its own to go wrong."""
    lines = [
        "=" * 72,
        "DRY RUN -- no git or GitHub operations were performed.",
        "=" * 72,
        "",
        f"Would open a PR against: {repo_full_name} ({base_branch} <- {branch_name})",
        f"Would modify: {dbt_file_path}",
        "",
        "--- File change ---",
        "",
        _diff_block(original_content, patched_content, dbt_file_path),
        "",
        "--- Would-be PR body (the dossier) ---",
        "",
        dossier_markdown,
    ]
    return "\n".join(lines)


def _live_create_pr(
    dbt_file_path: str,
    patched_content: str,
    dossier_markdown: str,
    branch_name: str,
    repo_full_name: str,
    base_branch: str,
    github_client,
) -> str:
    """The real (non-dry-run) path. NEVER exercised by this task's tests or
    live-verification run against a real `github_client` -- see module
    docstring. Only reached from `create_pr` when `dry_run=False`.
    """
    if github_client is None:
        # Lazy import: `github` (PyGithub) is only imported here, inside the
        # branch that constructs a REAL client -- so importing this module,
        # and every test that injects a fake `github_client`, never requires
        # PyGithub to be importable and never risks touching the real API.
        import os

        from github import Github

        github_client = Github(os.environ["GITHUB_TOKEN"])

    repo = github_client.get_repo(repo_full_name)
    base_ref = repo.get_branch(base_branch)
    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_ref.commit.sha)

    commit_message = f"blast-radius: patch {dbt_file_path}"
    try:
        existing = repo.get_contents(dbt_file_path, ref=branch_name)
        repo.update_file(
            path=dbt_file_path,
            message=commit_message,
            content=patched_content,
            sha=existing.sha,
            branch=branch_name,
        )
    except Exception:
        # File doesn't exist yet on this branch (PyGithub raises on a 404
        # from get_contents) -- create it instead of updating.
        repo.create_file(
            path=dbt_file_path,
            message=commit_message,
            content=patched_content,
            branch=branch_name,
        )

    pr = repo.create_pull(
        title=f"blast-radius: patch {dbt_file_path}",
        body=dossier_markdown,
        head=branch_name,
        base=base_branch,
    )
    return pr.html_url


def create_pr(
    dbt_file_path: str,
    patched_content: str,
    dossier_markdown: str,
    branch_name: str,
    repo_full_name: str = "khanblair/blast-radius",
    base_branch: str = "main",
    dry_run: bool = True,
    github_client=None,
    original_content: str | None = None,
) -> str | None:
    """See module docstring for the full safety contract.

    `original_content` is optional and used only to render a real diff in
    the dry-run preview (falls back to showing `patched_content` alone when
    not given) -- it has no effect on the `dry_run=False` path, which never
    needs the pre-patch content since PyGithub's contents API only needs the
    new content plus (when updating) the existing blob's sha.

    Returns None in dry-run mode (after printing the preview). Returns the
    live PR's html_url when `dry_run=False`.
    """
    if dry_run:
        preview = render_dry_run_preview(
            dbt_file_path=dbt_file_path,
            patched_content=patched_content,
            dossier_markdown=dossier_markdown,
            branch_name=branch_name,
            repo_full_name=repo_full_name,
            base_branch=base_branch,
            original_content=original_content,
        )
        print(preview)
        return None

    return _live_create_pr(
        dbt_file_path=dbt_file_path,
        patched_content=patched_content,
        dossier_markdown=dossier_markdown,
        branch_name=branch_name,
        repo_full_name=repo_full_name,
        base_branch=base_branch,
        github_client=github_client,
    )
