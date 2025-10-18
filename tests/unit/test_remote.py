"""Unit coverage for RemoteManager convenience helpers."""

from types import SimpleNamespace

import pytest

from pushback.remote import RemoteManager


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
