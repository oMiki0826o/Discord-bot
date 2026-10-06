"""
tests/test_message_autoreply.py

Modification():

- 提供 test message autoreply 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

import json

import pytest

from bot.mod.message.autoreply.matcher import AutoReplyMatcher, MatchInput
from bot.mod.message.autoreply.model import AutoReplyDocument, AutoReplyRule, MatchMode
from bot.mod.message.autoreply.repository import AutoReplyRepository


def rule(**overrides) -> AutoReplyRule:
    values = {
        "id": "hello",
        "enabled": True,
        "priority": 10,
        "mode": MatchMode.CONTAINS,
        "pattern": "你好",
        "case_sensitive": False,
        "response": "嗨，{username}",
        "allowed_channel_ids": (),
        "blocked_channel_ids": (),
        "cooldown_seconds": 5.0,
    }
    values.update(overrides)
    return AutoReplyRule(**values)


def input_value(**overrides) -> MatchInput:
    values = {
        "guild_id": 1,
        "channel_id": 2,
        "user_id": 3,
        "content": "你好呀",
        "user_name": "小明",
        "user_mention": "@小明",
        "channel_mention": "#聊天",
        "guild_name": "測試服",
    }
    values.update(overrides)
    return MatchInput(**values)


def test_repository_round_trip_and_last_known_good(tmp_path) -> None:
    repository = AutoReplyRepository(tmp_path)
    document = AutoReplyDocument(schema_version=1, guild_id=1, rules=(rule(),))
    repository.save(1, document)

    assert repository.load(1) == document
    (tmp_path / "1.json").write_text("{broken", encoding="utf-8")
    assert repository.load(1, force=True) == document
    assert repository.health(1).healthy is False


def test_repository_rejects_invalid_regex_and_keeps_last_known_good(tmp_path) -> None:
    repository = AutoReplyRepository(tmp_path)
    good = AutoReplyDocument(schema_version=1, guild_id=1, rules=(rule(),))
    repository.save(1, good)
    path = tmp_path / "1.json"
    payload = good.to_dict()
    payload["rules"][0]["match"] = {
        "mode": "regex",
        "pattern": "(",
        "case_sensitive": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert repository.load(1, force=True) == good
    assert repository.health(1).healthy is False


def test_repository_rejects_duplicate_ids_without_replacing_file(tmp_path) -> None:
    repository = AutoReplyRepository(tmp_path)
    good = AutoReplyDocument(schema_version=1, guild_id=1, rules=(rule(),))
    repository.save(1, good)
    before = (tmp_path / "1.json").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="重複"):
        repository.save(1, AutoReplyDocument(1, 1, (rule(), rule())))

    assert (tmp_path / "1.json").read_text(encoding="utf-8") == before


def test_matcher_honors_priority_channel_and_cooldown() -> None:
    matcher = AutoReplyMatcher(regex_timeout_seconds=0.05)
    document = AutoReplyDocument(
        1,
        1,
        (
            rule(id="low", priority=1, response="低"),
            rule(id="high", priority=20, response="高 {guild}"),
        ),
    )

    found = matcher.find(document, input_value(), now=10.0)
    assert found is not None and found.rule_id == "high"
    assert found.rendered_response == "高 測試服"
    assert matcher.find(document, input_value(), now=11.0) is None
    assert matcher.find(document, input_value(), now=16.0) is not None


def test_matcher_supports_exact_contains_regex_and_casefold() -> None:
    matcher = AutoReplyMatcher(regex_timeout_seconds=0.05)
    cases = (
        (rule(mode=MatchMode.EXACT, pattern="HELLO"), "hello"),
        (rule(mode=MatchMode.CONTAINS, pattern="straße"), "STRASSE!"),
        (rule(mode=MatchMode.REGEX, pattern=r"鑽石\s*劍"), "鑽石 劍"),
    )
    for index, (candidate, content) in enumerate(cases):
        document = AutoReplyDocument(1, 1, (candidate,))
        assert matcher.find(document, input_value(content=content), now=100.0 + index * 10)


def test_invalid_placeholder_and_guild_mismatch_are_rejected(tmp_path) -> None:
    repository = AutoReplyRepository(tmp_path)
    with pytest.raises(ValueError, match="placeholder"):
        repository.save(1, AutoReplyDocument(1, 1, (rule(response="{token}"),)))
    with pytest.raises(ValueError, match="guild"):
        repository.save(1, AutoReplyDocument(1, 2, (rule(),)))


def test_export_is_human_readable_utf8_json(tmp_path) -> None:
    repository = AutoReplyRepository(tmp_path)
    repository.save(1, AutoReplyDocument(1, 1, (rule(),)))
    exported = repository.export_bytes(1).decode("utf-8")
    assert "你好" in exported
    assert json.loads(exported)["rules"][0]["id"] == "hello"


def test_repository_detects_manual_json_changes(tmp_path) -> None:
    repository = AutoReplyRepository(tmp_path)
    repository.save(1, AutoReplyDocument(1, 1, (rule(response="舊"),)))
    payload = repository.load(1).to_dict()
    payload["rules"][0]["response"] = "新"
    path = tmp_path / "1.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert repository.load(1).rules[0].response == "新"
