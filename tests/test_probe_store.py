import json

from maplebot.probe_store import ProbeStore


def test_probe_store_only_restores_matching_context_and_individual_bindings(tmp_path):
    store = ProbeStore(tmp_path / "confirmed-probes.json")
    context = {"title": "MapleStory", "crop": {"x": 0, "width": 1024}}
    keys = {"left": {"key": "left"}, "jump": {"key": "alt"}}
    store.save(context, keys, set(keys))
    loaded = ProbeStore(store.path)
    assert loaded.restore(context, keys) == {"left", "jump"}
    assert loaded.restore(context, {**keys, "jump": {"key": "space"}}) == {"left"}
    assert loaded.restore({**context, "title": "Other game"}, keys) == set()
    assert loaded.restore({**context, "crop": {"x": 1, "width": 1023}}, keys) == set()


def test_probe_store_revocation_is_atomic_and_keeps_previous_backup(tmp_path):
    store = ProbeStore(tmp_path / "confirmed-probes.json")
    keys = {"left": {"key": "left"}}
    store.save({"title": "MapleStory"}, keys, {"left"})
    store.save({"title": "MapleStory"}, keys, set())
    assert store.restore({"title": "MapleStory"}, keys) == set()
    backups = list(tmp_path.glob("confirmed-probes.*.bak"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text())["confirmed"] == keys
    assert not store.path.with_suffix(".tmp").exists()


def test_missing_or_damaged_probe_store_never_grants_confirmation(tmp_path):
    store = ProbeStore(tmp_path / "confirmed-probes.json")
    keys = {"left": {"key": "left"}}
    assert store.restore({}, keys) == set()
    for body in ("broken", "[]", '{"version":1,"context":{},"confirmed":[]}'):
        store.path.write_text(body)
        assert store.restore({}, keys) == set()
