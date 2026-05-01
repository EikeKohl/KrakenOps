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
MIN_POLL_INTERVAL_S = 5
DEFAULT_POLL_INTERVAL_S = 30


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
class FileConfig:
    """Result of reading config.toml. Either field can be None."""

    github: GitHubConfig | None
    agents: list[AgentConfig]

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
    return FileConfig(github=github, agents=agents)


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


def pick_agent_for(label: str | None, agents: list[AgentConfig]) -> AgentConfig | None:
    """First mapping whose match_label is None or equals `label` (case-sensitive)."""
    for agent in agents:
        if agent.match_label is None or agent.match_label == label:
            return agent
    return None
