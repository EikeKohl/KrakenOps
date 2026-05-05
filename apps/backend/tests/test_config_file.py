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


def test_legacy_single_project_form_still_works(tmp_path: Path) -> None:
    """ADR 0006: ``project_id = "..."`` becomes a single [[github.projects]]
    entry inheriting the top-level poll_interval_s."""
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
    assert len(cfg.github.projects) == 1
    assert cfg.github.projects[0].id == "PVT_test"
    assert cfg.github.projects[0].poll_interval_s == 15
    assert len(cfg.agents) == 2


def test_multi_project_array_form(tmp_path: Path) -> None:
    """ADR 0006: ``[[github.projects]]`` blocks compose into a list."""
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
pat = "ghp_test"
poll_interval_s = 30

[[github.projects]]
id = "PVT_backend"

[[github.projects]]
id = "PVT_frontend"
poll_interval_s = 60
""")
    cfg = load(p)
    assert cfg.poller_enabled
    assert cfg.github.pat == "ghp_test"
    assert [p.id for p in cfg.github.projects] == ["PVT_backend", "PVT_frontend"]
    # Default cascades to projects without an override.
    assert cfg.github.projects[0].poll_interval_s == 30
    # Per-project override wins.
    assert cfg.github.projects[1].poll_interval_s == 60


def test_legacy_and_array_coexist_dedupes_ids(tmp_path: Path) -> None:
    """If the user has both forms, projects merge but duplicate ids drop."""
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
pat = "ghp_test"
project_id = "PVT_legacy"

[[github.projects]]
id = "PVT_legacy"

[[github.projects]]
id = "PVT_other"
""")
    cfg = load(p)
    assert [p.id for p in cfg.github.projects] == ["PVT_legacy", "PVT_other"]


def test_min_poll_interval_enforced(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
pat = "x"
project_id = "y"
poll_interval_s = 1
""")
    cfg = load(p)
    assert cfg.github.projects[0].poll_interval_s == 5  # MIN_POLL_INTERVAL_S


def test_min_poll_interval_per_project(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
pat = "x"

[[github.projects]]
id = "PVT_a"
poll_interval_s = 2
""")
    cfg = load(p)
    assert cfg.github.projects[0].poll_interval_s == 5


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


def test_dormant_when_pat_present_but_no_projects(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""
[github]
pat = "x"
""")
    cfg = load(p)
    assert cfg.poller_enabled is False


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


def test_processes_default_allowlist_is_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KRAKENOPS_PROCESS_ALLOWLIST", raising=False)
    cfg = load(tmp_path / "no_such.toml")
    assert cfg.processes.allowlist == ("claude",)
    assert cfg.processes.enabled is True


def test_processes_env_var_overrides_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KRAKENOPS_PROCESS_ALLOWLIST", "claude,Cursor, continue")
    cfg = load(tmp_path / "no_such.toml")
    # Lowercased, trimmed, deduped, order-preserved.
    assert cfg.processes.allowlist == ("claude", "cursor", "continue")


def test_processes_empty_env_disables_sampler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KRAKENOPS_PROCESS_ALLOWLIST", "")
    cfg = load(tmp_path / "no_such.toml")
    assert cfg.processes.allowlist == ()
    assert cfg.processes.enabled is False


def test_processes_file_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KRAKENOPS_PROCESS_ALLOWLIST", "from_env")
    p = tmp_path / "config.toml"
    p.write_text("""
[processes]
allowlist = ["claude", "cursor"]
""")
    cfg = load(p)
    assert cfg.processes.allowlist == ("claude", "cursor")
