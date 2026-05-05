"""Load + parse ~/.krakenops/config.toml.

The file is optional. Missing file (or missing [github] block) means the
poller stays dormant — KrakenOps still ingests traces and serves /v1/* fine.

Schema is documented in ADR 0002 and apps/backend/README.md.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

from app.config import KRAKENOPS_HOME

_log = logging.getLogger("krakenops.config_file")

CONFIG_PATH = KRAKENOPS_HOME / "config.toml"
_PAT_ENV = "KRAKENOPS_GITHUB_PAT"
_PROCESS_ALLOWLIST_ENV = "KRAKENOPS_PROCESS_ALLOWLIST"
_PROCESS_DENYLIST_ENV = "KRAKENOPS_PROCESS_DENYLIST"
MIN_POLL_INTERVAL_S = 5
DEFAULT_POLL_INTERVAL_S = 30
DEFAULT_PROCESS_ALLOWLIST: tuple[str, ...] = ("claude",)
# Substrings that nuke "obvious shell noise" out of the discovered list. Any
# process whose joined cmdline contains one of these (case-insensitive) is
# dropped even if it would otherwise match the allowlist. Users can override
# via [processes] denylist in config.toml.
DEFAULT_PROCESS_DENYLIST: tuple[str, ...] = (
    "/bin/zsh",
    "/bin/bash",
    "/bin/sh",
    "/usr/bin/login",
    "tmux: ",
)


@dataclass
class GitHubConfig:
    pat: str
    project_id: str
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S


@dataclass
class AgentConfig:
    name: str
    script_path: Path
    match_label: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class ProcessesConfig:
    """Per-process sampler config. ADR 0005."""

    # Lower-cased substrings matched against the joined cmdline.
    allowlist: tuple[str, ...] = DEFAULT_PROCESS_ALLOWLIST
    # Lower-cased substrings that, when present in the cmdline, drop the
    # process from the discovered list (even when allowlist matches).
    # Empty tuple disables the filter.
    denylist: tuple[str, ...] = DEFAULT_PROCESS_DENYLIST

    @property
    def enabled(self) -> bool:
        return bool(self.allowlist)


@dataclass
class FileConfig:
    """Result of reading config.toml. Either field can be None."""

    github: GitHubConfig | None
    agents: list[AgentConfig]
    processes: ProcessesConfig = field(default_factory=ProcessesConfig)

    @property
    def poller_enabled(self) -> bool:
        return self.github is not None


def load(path: Path | None = None) -> FileConfig:
    path = path or CONFIG_PATH
    raw: dict = {}
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text())
        except Exception as e:
            _log.warning("failed to parse %s: %s — treating as empty", path, e)
            raw = {}

    github = _parse_github(raw.get("github") or {})
    agents = _parse_agents(raw.get("agents") or [])
    processes = _parse_processes(raw.get("processes") or {})
    return FileConfig(github=github, agents=agents, processes=processes)


def _parse_github(block: dict) -> GitHubConfig | None:
    pat = os.environ.get(_PAT_ENV) or block.get("pat")
    project_id = block.get("project_id")
    if not pat or not project_id:
        return None
    poll = int(block.get("poll_interval_s") or DEFAULT_POLL_INTERVAL_S)
    poll = max(poll, MIN_POLL_INTERVAL_S)
    return GitHubConfig(pat=pat, project_id=project_id, poll_interval_s=poll)


def _parse_agents(blocks: list[dict]) -> list[AgentConfig]:
    out: list[AgentConfig] = []
    for b in blocks:
        name = b.get("name")
        script = b.get("script")
        if not name or not script:
            _log.warning("skipping agent block missing name/script: %r", b)
            continue
        script_path = Path(script).expanduser()
        if not script_path.is_absolute():
            script_path = (KRAKENOPS_HOME / script_path).resolve()
        env_block = b.get("env") or {}
        out.append(
            AgentConfig(
                name=str(name),
                script_path=script_path,
                match_label=b.get("match_label"),
                args=[str(a) for a in (b.get("args") or [])],
                env={str(k): str(v) for k, v in env_block.items()},
            )
        )
    return out


def _parse_processes(block: dict) -> ProcessesConfig:
    """Build the per-process allowlist + denylist.

    Allowlist precedence (highest first): config.toml `[processes] allowlist`,
    `KRAKENOPS_PROCESS_ALLOWLIST` env var, built-in default ("claude").
    An explicitly empty list (env or file) disables the sampler.

    Denylist precedence: config.toml `[processes] denylist`,
    `KRAKENOPS_PROCESS_DENYLIST` env var, built-in default (shell noise).
    An explicitly empty list disables the noise filter.
    """
    if not isinstance(block, dict):
        block = {}

    # Allowlist
    file_allow = block.get("allowlist")
    if file_allow is not None:
        entries = [file_allow] if isinstance(file_allow, str) else list(file_allow)
        allowlist = _normalize_allowlist(entries)
    else:
        env_allow = os.environ.get(_PROCESS_ALLOWLIST_ENV)
        if env_allow is not None:
            allowlist = _normalize_allowlist(env_allow.split(","))
        else:
            allowlist = DEFAULT_PROCESS_ALLOWLIST

    # Denylist
    file_deny = block.get("denylist")
    if file_deny is not None:
        entries = [file_deny] if isinstance(file_deny, str) else list(file_deny)
        denylist = _normalize_allowlist(entries)
    else:
        env_deny = os.environ.get(_PROCESS_DENYLIST_ENV)
        if env_deny is not None:
            denylist = _normalize_allowlist(env_deny.split(","))
        else:
            denylist = DEFAULT_PROCESS_DENYLIST

    return ProcessesConfig(allowlist=allowlist, denylist=denylist)


def _normalize_allowlist(entries: list) -> tuple[str, ...]:
    """Lowercase + strip + drop empties. Preserves order, dedupes."""
    seen: list[str] = []
    for e in entries:
        s = str(e).strip().lower()
        if s and s not in seen:
            seen.append(s)
    return tuple(seen)


def pick_agent_for(label: str | None, agents: list[AgentConfig]) -> AgentConfig | None:
    """First mapping whose match_label is None or equals `label` (case-sensitive)."""
    for agent in agents:
        if agent.match_label is None or agent.match_label == label:
            return agent
    return None
