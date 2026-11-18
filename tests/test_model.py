# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import pytest

from mqtt_acl_verify.model import ConfigError, load_config

CONFIG = """
endpoints:
  plain: {host: 127.0.0.1, port: 1883}
observer: admin
identities:
  admin: {username: admin, password_env: PW_ADMIN}
  dev: {username: dev, password_env: PW_DEV}
"""


def write(tmp_path: Path, cases: str) -> tuple[Path, Path]:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG)
    cs = tmp_path / "cases.yaml"
    cs.write_text(cases)
    return cfg, cs


def test_example_files_load():
    root = Path(__file__).parents[1]
    config = load_config(root / "examples/config.example.yaml", root / "examples/cases.example.yaml")
    assert config.observer == "admin"
    assert len(config.cases) > 5


def test_probe_placeholder_is_replaced(tmp_path):
    cfg, cs = write(tmp_path, """
cases:
  - {id: a, client: dev, action: receive, topic: "cmnd/dev/#",
     publish_topic: "cmnd/dev/{probe}", expect: allow}
""")
    case = load_config(cfg, cs).cases[0]
    topic_filter, topic = case.resolve_topics()
    assert topic_filter == "cmnd/dev/#"
    assert topic.startswith("cmnd/dev/_aclprobe_")


def test_topic_without_probe_is_refused(tmp_path):
    cfg, cs = write(tmp_path, """
cases:
  - {id: a, client: dev, action: publish, topic: "cmnd/dev/POWER", expect: deny}
""")
    with pytest.raises(ConfigError, match="placeholder"):
        load_config(cfg, cs)


def test_live_topic_is_allowed_explicitly(tmp_path):
    cfg, cs = write(tmp_path, """
cases:
  - {id: a, client: dev, action: publish, topic: "cmnd/dev/POWER", live: true, expect: deny}
""")
    assert load_config(cfg, cs).cases[0].live


def test_receive_with_wildcard_needs_publish_topic(tmp_path):
    cfg, cs = write(tmp_path, """
cases:
  - {id: a, client: dev, action: receive, topic: "stat/#", expect: allow}
""")
    with pytest.raises(ConfigError, match="publish_topic"):
        load_config(cfg, cs)


def test_unknown_client_is_refused(tmp_path):
    cfg, cs = write(tmp_path, """
cases:
  - {id: a, client: ghost, action: connect, expect: deny}
""")
    with pytest.raises(ConfigError, match="unknown client"):
        load_config(cfg, cs)


def test_missing_password_env_is_reported(tmp_path, monkeypatch):
    cfg, cs = write(tmp_path, "cases: []\n")
    monkeypatch.delenv("PW_DEV", raising=False)
    ident = load_config(cfg, cs).identities["dev"]
    with pytest.raises(ConfigError, match="PW_DEV"):
        ident.password()


def test_generated_client_id_is_unique(tmp_path):
    cfg, cs = write(tmp_path, "cases: []\n")
    ident = load_config(cfg, cs).identities["dev"]
    assert ident.make_client_id() != ident.make_client_id()
