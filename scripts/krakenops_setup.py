#!/usr/bin/env python3
"""KrakenOps interactive setup wizard.

Walks the user through:
  1. Creating ``~/.krakenops/`` and writing a ``config.toml`` with the
     GitHub Projects v2 PAT + project ID (optional — the user can skip
     to keep the kanban poller dormant).
  2. Configuring the per-process allowlist (defaults to ``claude``;
     opt-in extras like ``ollama``, ``python``, ``node``).
  3. Installing the Claude Code OTel telemetry env block into the user's
     shell rc so the dashboard's External Activity panel lights up.
  4. Verifying the backend is reachable on its expected port.

Standalone (stdlib only) so it can be invoked before backend deps are synced.
Idempotent: re-running updates the same files in place.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

KRAKENOPS_HOME = Path(os.environ.get("KRAKENOPS_HOME") or Path.home() / ".krakenops")
CONFIG_PATH = KRAKENOPS_HOME / "config.toml"
DEFAULT_BACKEND_PORT = int(os.environ.get("KRAKENOPS_PORT", "8787"))
DEFAULT_ENDPOINT = f"http://localhost:{DEFAULT_BACKEND_PORT}"

REPO_ROOT = Path(__file__).resolve().parent.parent
TELEMETRY_SCRIPT = REPO_ROOT / "scripts" / "install-claude-code-telemetry.sh"
PLUGIN_DIR = REPO_ROOT / "packages" / "krakenops-claude-plugin"


# --- ANSI helpers ---------------------------------------------------------

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, s: str) -> str:
    if not _USE_COLOR:
        return s
    return f"\033[{code}m{s}\033[0m"


def bold(s: str) -> str:
    return _c("1", s)


def dim(s: str) -> str:
    return _c("2", s)


def green(s: str) -> str:
    return _c("32", s)


def yellow(s: str) -> str:
    return _c("33", s)


def cyan(s: str) -> str:
    return _c("36", s)


def red(s: str) -> str:
    return _c("31", s)


# --- prompts --------------------------------------------------------------


def banner() -> None:
    print()
    print(bold(cyan("  ╭─ KrakenOps setup ─────────────────────────────────────╮")))
    print(bold(cyan("  │                                                        │")))
    print(bold(cyan("  │   Local-first observability for your AI agents.        │")))
    print(bold(cyan("  │                                                        │")))
    print(bold(cyan("  ╰────────────────────────────────────────────────────────╯")))
    print()
    print(dim(f"  config dir: {KRAKENOPS_HOME}"))
    print(dim(f"  backend:    {DEFAULT_ENDPOINT}"))
    print()


def section(title: str) -> None:
    print()
    print(bold(f"▸ {title}"))
    print()


def ask(prompt: str, default: str | None = None, *, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    full = f"  {prompt}{suffix}: "
    if secret:
        import getpass

        try:
            value = getpass.getpass(full)
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(130)
    else:
        try:
            value = input(full)
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(130)
    value = value.strip()
    if not value and default is not None:
        return default
    return value


def confirm(prompt: str, *, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            ans = input(f"  {prompt} {suffix}: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(130)
        if not ans:
            return default
        if ans in {"y", "yes"}:
            return True
        if ans in {"n", "no"}:
            return False


# --- actions --------------------------------------------------------------


def ensure_home() -> None:
    KRAKENOPS_HOME.mkdir(parents=True, exist_ok=True)


def _gh_graphql(pat: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST a GraphQL query to the GitHub API. Returns the raw payload."""
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": "krakenops-setup",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def github_check(pat: str, project_id: str) -> tuple[bool, str]:
    """Make a minimal Projects v2 GraphQL call to verify the PAT + ID."""
    try:
        payload = _gh_graphql(
            pat,
            "query($id: ID!) { node(id: $id) { ... on ProjectV2 { title } } }",
            {"id": project_id},
        )
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except (urllib.error.URLError, TimeoutError) as e:
        return False, f"network: {e}"
    except Exception as e:  # pragma: no cover - defensive
        return False, str(e)

    if payload.get("errors"):
        first = payload["errors"][0].get("message", "unknown error")
        return False, first
    node = (payload.get("data") or {}).get("node")
    if not node:
        return False, "project not found (check the project_id)"
    return True, str(node.get("title") or "(untitled project)")


def list_user_projects(pat: str) -> tuple[list[dict[str, str]] | None, str | None]:
    """List the PAT owner's ProjectV2s. Returns (projects, error).

    Each project dict has ``id``, ``title``, ``owner`` keys. ``error`` is set
    when the call fails (e.g. missing scope) so the caller can fall back to
    a manual prompt with a useful message.
    """
    query = (
        "query { viewer { login projectsV2(first: 30) { nodes {"
        " id title closed owner { __typename ... on User { login }"
        " ... on Organization { login } } } } } }"
    )
    try:
        payload = _gh_graphql(pat, query)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except (urllib.error.URLError, TimeoutError) as e:
        return None, f"network: {e}"
    except Exception as e:  # pragma: no cover - defensive
        return None, str(e)

    if payload.get("errors"):
        first = payload["errors"][0].get("message", "unknown error")
        return None, first
    nodes = (payload.get("data") or {}).get("viewer", {}).get("projectsV2", {}).get("nodes") or []
    out: list[dict[str, str]] = []
    for n in nodes:
        if n.get("closed"):
            continue
        owner = (n.get("owner") or {}).get("login") or ""
        out.append(
            {
                "id": str(n.get("id") or ""),
                "title": str(n.get("title") or "(untitled)"),
                "owner": owner,
            }
        )
    return out, None


def _pick_projects_interactive(pat: str) -> list[str] | None:
    """List projects via GraphQL and let the user pick **one or more**.

    Returns the chosen project ids (in display order) or ``None`` on cancel.
    Accepts comma- or space-separated indices ("1,3,4" or "1 3 4"), the
    literal "all", or a manually pasted PVT_ id.
    """
    print()
    print(dim("  fetching your projects…"))
    projects, err = list_user_projects(pat)
    if projects is None:
        print(yellow(f"  ! couldn't list projects: {err}"))
        if err and "scope" in err.lower():
            print(
                dim(
                    "    Your PAT is missing the 'read:project' scope.\n"
                    "    Edit it at https://github.com/settings/tokens (classic)\n"
                    "    or regenerate a fine-grained token with 'Projects: read & write'."
                )
            )
        return None
    if not projects:
        print(yellow("  ! the PAT can read projects, but none were returned."))
        print(
            dim(
                "    If the project is owned by an organization, ensure the PAT has SSO\n"
                "    authorized for that org and that 'read:project' is granted."
            )
        )
        return None

    print()
    print(bold("  your projects:"))
    for i, p in enumerate(projects, start=1):
        owner_prefix = f"{p['owner']}/" if p["owner"] else ""
        idx_label = cyan(f"{i:>2}")
        meta = dim(f"· {owner_prefix}{p['id']}")
        print(f"    {idx_label}. {bold(p['title'])} {meta}")
    print()
    print(dim('  multi-select: "1,3,4" or "1 3 4" or "all". paste a PVT_… id'))
    print(dim("  to add one not on the list. blank skips."))
    while True:
        sel = ask("projects to mirror", default="").strip()
        if not sel:
            return None
        if sel.lower() == "all":
            return [p["id"] for p in projects]
        # Manually-pasted node id (accepts a comma-separated list of ids).
        if not any(c.isdigit() for c in sel.split(",")[0].strip()):
            return [s.strip() for s in sel.split(",") if s.strip()]
        # Indices — accept commas or whitespace as separators.
        tokens = [t for t in sel.replace(",", " ").split() if t]
        chosen: list[str] = []
        invalid = False
        for tok in tokens:
            if tok.isdigit():
                idx = int(tok)
                if 1 <= idx <= len(projects):
                    pid = projects[idx - 1]["id"]
                    if pid not in chosen:
                        chosen.append(pid)
                    continue
                print(yellow(f"  ! {idx} out of range (1–{len(projects)})"))
                invalid = True
                break
            # Mixed: "1, PVT_..." — treat the non-digit as a manual id.
            if tok not in chosen:
                chosen.append(tok)
        if invalid or not chosen:
            continue
        return chosen


def github_block() -> dict[str, Any] | None:
    section("GitHub Projects integration (optional)")
    print(
        "  KrakenOps mirrors one or more GitHub Projects v2 boards into the\n"
        "  Kanban panel. Each board becomes a tab; tickets are auto-grouped."
    )
    print(dim("  Skip this step to leave the poller dormant — telemetry still works."))
    print()
    if not confirm("Configure GitHub now?", default=False):
        return None

    print()
    print(dim("  Required PAT scope: 'read:project' (classic) or 'Projects: read'"))
    print(dim("  (add 'project' / 'Projects: write' if you want KrakenOps to flip ticket statuses)"))
    print(dim("  Generate one at: https://github.com/settings/tokens"))
    pat = ask("GitHub PAT", secret=True)
    if not pat:
        print(yellow("  ✗ no PAT entered — skipping."))
        return None

    project_ids = _pick_projects_interactive(pat)
    if not project_ids:
        # Fall back to manual entry so the wizard still works when listing failed.
        print()
        print(
            dim(
                "  paste one or more project node ids manually, comma-separated\n"
                "  (looks like PVT_kwDOAxxxxxxxxxxxxxxxxxx). Blank skips."
            )
        )
        manual = ask("GitHub Projects v2 node id(s)", default="")
        if not manual:
            print(yellow("  ✗ no project id — skipping."))
            return None
        project_ids = [s.strip() for s in manual.split(",") if s.strip()]

    poll_s = ask("default poll interval seconds", default="30")
    try:
        poll = max(int(poll_s), 5)
    except ValueError:
        poll = 30

    # Verify each id resolves before saving — bad ids are easy to typo.
    print()
    print(dim("  testing GitHub credentials…"))
    verified: list[str] = []
    for pid in project_ids:
        ok, info = github_check(pat, pid)
        if ok:
            print(green(f"  ✓ {pid} → {info}"))
            verified.append(pid)
        else:
            print(red(f"  ✗ {pid}: {info}"))
            if confirm(f"  keep {pid} in the config anyway?", default=False):
                verified.append(pid)
    if not verified:
        print(yellow("  ✗ no projects passed validation — skipping GitHub config."))
        return None

    return {
        "pat": pat,
        "project_ids": verified,
        "poll_interval_s": poll,
    }


PROCESS_PRESETS: list[tuple[str, str]] = [
    ("claude", "Claude Code CLI sessions and agent SDK usage"),
    ("ollama", "local Ollama model server processes"),
    ("python", "any python interpreter (verbose)"),
    ("node", "node.js processes"),
    ("uv", "uv-managed Python runs"),
]


def processes_block() -> dict[str, Any]:
    section("Process discovery allowlist")
    print(
        "  KrakenOps's per-process sampler matches host processes by\n"
        "  case-insensitive substring against their full command-line."
    )
    print()
    print(dim("  Default is just 'claude'. Pick extras you want to track:"))
    print()

    selected: list[str] = []
    for needle, desc in PROCESS_PRESETS:
        default = needle == "claude"
        if confirm(f"  include {bold(needle):<14} — {desc}", default=default):
            selected.append(needle)

    extra = ask("extra substrings (comma-separated, blank for none)", default="").strip()
    if extra:
        for s in extra.split(","):
            s = s.strip().lower()
            if s and s not in selected:
                selected.append(s)

    if not selected:
        print(yellow("  ✗ allowlist empty — process sampler will be disabled."))

    return {"allowlist": selected}


def write_config(github: dict[str, Any] | None, processes: dict[str, Any]) -> None:
    """Render config.toml. Preserves existing [[agents]] blocks if any."""
    section("Writing config.toml")

    existing_agents = ""
    if CONFIG_PATH.exists():
        try:
            existing = CONFIG_PATH.read_text()
            # Lift any existing [[agents]] sections verbatim — we don't manage them here.
            chunks = []
            buf: list[str] = []
            in_agent = False
            for line in existing.splitlines():
                stripped = line.strip()
                if stripped.startswith("[[agents]]"):
                    if buf:
                        chunks.append("\n".join(buf))
                        buf = []
                    in_agent = True
                    buf.append(line)
                elif in_agent:
                    if stripped.startswith("[") and not stripped.startswith("[["):
                        chunks.append("\n".join(buf))
                        buf = []
                        in_agent = False
                    else:
                        buf.append(line)
            if buf and in_agent:
                chunks.append("\n".join(buf))
            if chunks:
                existing_agents = "\n\n" + "\n\n".join(chunks).strip() + "\n"
        except Exception:
            existing_agents = ""

    lines: list[str] = []
    lines.append("# KrakenOps backend config — generated by scripts/setup.sh")
    lines.append("# See ADRs 0002, 0005, 0006 for the full schema.")
    lines.append("")

    if github:
        lines.append("[github]")
        lines.append(f'pat = "{github["pat"]}"')
        lines.append(f"poll_interval_s = {github['poll_interval_s']}")
        lines.append("")
        for pid in github["project_ids"]:
            lines.append("[[github.projects]]")
            lines.append(f'id = "{pid}"')
            lines.append("")
    else:
        lines.append("# [github] — not configured. Add when you're ready:")
        lines.append('# pat = "ghp_…"          # or set $KRAKENOPS_GITHUB_PAT')
        lines.append("# poll_interval_s = 30")
        lines.append("")
        lines.append("# [[github.projects]]")
        lines.append('# id = "PVT_…"')
        lines.append("")

    lines.append("[processes]")
    quoted = ", ".join(f'"{s}"' for s in processes["allowlist"])
    lines.append(f"allowlist = [{quoted}]")

    if existing_agents:
        lines.append(existing_agents.rstrip())
    else:
        lines.append("")
        lines.append("# [[agents]]")
        lines.append('# name = "researcher"')
        lines.append('# script = "agents/researcher.py"   # relative to ~/.krakenops/')
        lines.append('# match_label = "agent:researcher"  # GH ticket label')
        lines.append("# args = []")
        lines.append("# env = {}")

    body = "\n".join(lines).rstrip() + "\n"

    # Back up an existing config once so the user can recover hand edits.
    if CONFIG_PATH.exists():
        backup = CONFIG_PATH.with_suffix(".toml.bak")
        try:
            shutil.copy2(CONFIG_PATH, backup)
            print(dim(f"  ↳ existing config backed up to {backup}"))
        except Exception as e:
            print(yellow(f"  ! could not back up existing config: {e}"))

    CONFIG_PATH.write_text(body)
    # Keep the PAT readable only by the owner.
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    print(green(f"  ✓ wrote {CONFIG_PATH}"))


def install_claude_code_telemetry() -> None:
    section("Claude Code telemetry")
    print(
        "  This appends a small env block to your shell rc so the Claude Code\n"
        "  CLI exports its OTel logs + metrics to the local KrakenOps backend."
    )
    print(dim("  (Idempotent — safe to re-run. Reversible via the same script.)"))
    print()
    if not confirm("Install Claude Code telemetry env vars now?", default=True):
        print(dim("  skipped — run scripts/install-claude-code-telemetry.sh anytime."))
        return

    if not TELEMETRY_SCRIPT.exists():
        print(red(f"  ✗ telemetry script missing at {TELEMETRY_SCRIPT}"))
        return

    env = os.environ.copy()
    env["KRAKENOPS_ENDPOINT"] = DEFAULT_ENDPOINT
    try:
        subprocess.run(
            ["bash", str(TELEMETRY_SCRIPT), "install"],
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        print(red(f"  ✗ telemetry install failed (exit {e.returncode})"))


def install_claude_code_plugin() -> None:
    section("Claude Code plugin (TODO + MCP)")
    print(
        "  KrakenOps ships a Claude Code plugin that surfaces TodoWrite\n"
        "  progress in the dashboard and adds four MCP tools the agent\n"
        "  can call (claim_ticket, set_status, set_todos, get_my_tickets)."
    )
    print(dim("  Without it, sessions still appear (auto-discovered from OTel) —"))
    print(dim("  but TODOs and self-claim don't fire. Install once; works in"))
    print(dim("  every future Claude Code session."))
    print()

    if not PLUGIN_DIR.exists():
        print(yellow(f"  ! plugin folder missing at {PLUGIN_DIR} — skipping."))
        return

    if not confirm("Print the install command for me to run?", default=True):
        return

    print()
    cmd = f"claude --plugin-dir {PLUGIN_DIR}"
    print(f"    {bold(cyan(cmd))}")
    print()
    print(
        dim(
            "  Or, when you publish to a marketplace later:\n"
            "    /plugin install krakenops-monitoring@<your-marketplace>"
        )
    )
    print(
        dim(
            "  Requirement: 'uv' on PATH (already needed for the backend);\n"
            "  uv resolves the MCP server's deps via PEP 723 inline metadata\n"
            "  on first run."
        )
    )


def backend_check() -> None:
    section("Backend connectivity check")
    url = f"{DEFAULT_ENDPOINT}/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            print(green(f"  ✓ backend healthy at {url} (version {data.get('version', '?')})"))
            return
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        print(yellow(f"  ! backend not reachable at {url} (this is fine — it's not running yet)"))
        print(dim("    boot it with:  scripts/dev-up.sh"))
    except Exception as e:
        print(yellow(f"  ! backend probe failed: {e}"))


def summary(github: dict[str, Any] | None, processes: dict[str, Any]) -> None:
    section("All set")
    print(f"  ▸ config:     {CONFIG_PATH}")
    if github:
        n = len(github["project_ids"])
        word = "project" if n == 1 else "projects"
        print(f"  ▸ kanban:     {green(f'configured ({n} {word})')}")
    else:
        print(f"  ▸ kanban:     {dim('dormant — no GitHub creds')}")
    if processes["allowlist"]:
        print(f"  ▸ processes:  tracking {', '.join(processes['allowlist'])}")
    else:
        print(f"  ▸ processes:  {dim('sampler disabled (empty allowlist)')}")
    print()
    print(bold("  next:"))
    print(f"    1. start the stack:   {cyan('scripts/dev-up.sh')}")
    print(f"    2. open the dashboard: {cyan('http://localhost:3000')}")
    print(f"    3. run a Claude Code session — events stream into the External Activity panel.")
    print()


def main() -> int:
    banner()
    ensure_home()
    github = github_block()
    processes = processes_block()
    write_config(github, processes)
    install_claude_code_telemetry()
    install_claude_code_plugin()
    backend_check()
    summary(github, processes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
