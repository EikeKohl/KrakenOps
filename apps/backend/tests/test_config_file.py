"""Config loader for ~/.krakenops/config.toml."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config_file import load, pick_agent_for


def test_missing_file_returns_dormant(tmp_path: Path) -> None:
    cfg = load(tmp_path / "no_such.toml")
    assert cfg.poller_enabled is False
    assert cfg.agents == []


def test_block_without_pat_or_project_is_dormant(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
poll_interval_s = 60
""")
    cfg = load(p)
    assert cfg.poller_enabled is False


def test_complete_config_parsed(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
pat = "ghp_test"
project_id = "PVT_test"
poll_interval_s = 15

[[agents]]
name = "research"
script = "/abs/path/to/agent.py"
match_label = "research"
args = ["--count", "1"]

[[agents]]
name = "default"
script = "/abs/path/to/default.py"
""")
    cfg = load(p)
    assert cfg.poller_enabled
    assert cfg.github.pat == "ghp_test"
    assert cfg.github.project_id == "PVT_test"
    assert cfg.github.poll_interval_s == 15
    assert len(cfg.agents) == 2
    assert cfg.agents[0].name == "research"
    assert cfg.agents[0].args == ["--count", "1"]
    assert cfg.agents[0].match_label == "research"
    assert cfg.agents[1].match_label is None


def test_min_poll_interval_enforced(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
pat = "x"
project_id = "y"
poll_interval_s = 1
""")
    cfg = load(p)
    assert cfg.github.poll_interval_s == 5  # MIN_POLL_INTERVAL_S


def test_env_pat_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KRAKENOPS_GITHUB_PAT", "from_env")
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
pat = "from_file"
project_id = "x"
""")
    cfg = load(p)
    assert cfg.github.pat == "from_env"


def test_pick_agent_label_match_then_catchall(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
pat = "x"
project_id = "y"

[[agents]]
name = "research"
script = "/x.py"
match_label = "research"

[[agents]]
name = "default"
script = "/y.py"
""")
    cfg = load(p)
    assert pick_agent_for("research", cfg.agents).name == "research"
    assert pick_agent_for("nope", cfg.agents).name == "default"
    assert pick_agent_for(None, cfg.agents).name == "default"


def test_pick_agent_returns_none_when_no_match() -> None:
    from app.config_file import AgentConfig

    agents = [AgentConfig(name="r", script_path=Path("/x.py"), match_label="research")]
    assert pick_agent_for("not-research", agents) is None
