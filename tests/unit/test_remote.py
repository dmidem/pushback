"""Unit coverage for RemoteManager convenience helpers."""

from types import SimpleNamespace

import pytest

from pushback.remote import RemoteManager

# ---------------------------------------------------------------------------
# ssh_opts — multiplexing behaviour
# ---------------------------------------------------------------------------


def test_ssh_opts_disabled():
    """ssh_multiplex=0 → no ControlMaster/ControlPersist options."""
    mgr = RemoteManager(ssh_multiplex=0)
    opts = mgr.ssh_opts(22)
    assert opts == ["-p", "22"]
    assert "ControlMaster" not in " ".join(opts)


def test_ssh_opts_default():
    """Default (1 s) enables multiplexing with ControlPersist=3."""
    mgr = RemoteManager()
    opts = mgr.ssh_opts(22)
    assert "-o" in opts
    assert "ControlMaster=auto" in opts
    persist_idx = opts.index("ControlPersist=3")
    assert persist_idx >= 0


def test_ssh_opts_custom_timeout():
    """ssh_multiplex=60 → ControlPersist=60."""
    mgr = RemoteManager(ssh_multiplex=60)
    opts = mgr.ssh_opts(22)
    assert "ControlPersist=60" in opts


def test_ssh_opts_port_forwarded():
    """Port is always included in opts regardless of multiplex setting."""
    for mux in (0, 1, 300):
        opts = RemoteManager(ssh_multiplex=mux).ssh_opts(2222)
        assert "-p" in opts
        assert "2222" in opts


# ---------------------------------------------------------------------------
# _unpack_server_config
# ---------------------------------------------------------------------------


def test_unpack_server_config_from_mapping():
    mgr = RemoteManager()
    user, host, port, base = mgr._unpack_server_config(  # noqa: SLF001 - testing helper
        "main",
        {"user": "alice", "host": "host", "port": "23", "base": "/data"},
    )
    assert (user, host, port, base) == ("alice", "host", 23, "/data")


def test_unpack_server_config_from_namespace():
    mgr = RemoteManager()
    config = SimpleNamespace(user="bob", host="srv", port=2022, base="~/backups")
    user, host, port, base = mgr._unpack_server_config("secondary", config)  # noqa: SLF001
    assert user == "bob"
    assert host == "srv"
    assert port == 2022
    assert base == "~/backups"


def test_unpack_server_config_invalid_port():
    mgr = RemoteManager()
    with pytest.raises(ValueError):
        mgr._unpack_server_config(
            "broken",
            {"user": "bad", "host": "srv", "port": "nan", "base": "/tmp"},
        )


def test_list_backups_uses_mapping(monkeypatch, capsys):
    mgr = RemoteManager()
    monkeypatch.setattr(mgr, "test_dir", lambda *args, **kwargs: True)
    monkeypatch.setattr(mgr, "list_all", lambda *args, **kwargs: ["proj_hash_1", "foo"])
    monkeypatch.setattr(mgr, "list_siblings", lambda *args, **kwargs: [])
    items = mgr.list_backups(
        "main",
        {"user": "alice", "host": "example.com", "base": "/data", "port": 22},
        "",
    )
    assert items == ["proj_hash_1"]  # only folder with '_' are considered as backups
