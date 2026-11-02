from unittest.mock import MagicMock

from app.kpi.catalog_cache import (
    PROJECT_SCOPE,
    cache_generation_stamp,
    cache_scope_key,
)


def _scalar(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def test_scope_key_is_project_or_canonical_capture_set():
    assert cache_scope_key() == PROJECT_SCOPE
    assert cache_scope_key(["c2", "c1", "c2"]) == "captures:c1,c2"


def test_generation_stamp_includes_scope_and_all_content_generations():
    db = MagicMock()
    db.execute.side_effect = [_scalar("decode-hash"), _scalar("identity-hash")]

    stamp = cache_generation_stamp(
        db, "project-a", "2.60.0", scope_key="captures:c1,c2"
    )

    assert stamp == (
        "decode-hash|identity=identity-hash|cat=2.60.0|scope=captures:c1,c2"
    )
    assert all(call.args[1] == {"pid": "project-a"} for call in db.execute.call_args_list)


def test_project_and_capture_scopes_cannot_share_a_persisted_key():
    project_key = ("project-a", cache_scope_key())
    capture_key = ("project-a", cache_scope_key(["capture-a"]))

    assert project_key != capture_key
