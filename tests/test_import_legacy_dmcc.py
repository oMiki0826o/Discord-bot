from tools.import_legacy_dmcc import migrate
from bot.mod.dmcc.config import DEFAULT_SETTINGS, DmccSettings
from bot.mod.dmcc.repositories.state import JsonStateRepository


def test_migrate_combines_matching_legacy_channels_without_copying_tokens():
    legacy = [
        ("survival", "生存服", {"generic": {"channelId": "123456789012345678", "consoleLogChannelId": "223456789012345678", "announceHighMspt": True, "msptLimit": 150}, "customMessage": {"serverStarted": "生存服已啟動"}}),
        ("creative", "創造服", {"generic": {"channelId": "123456789012345678", "consoleLogChannelId": "323456789012345678", "announceHighMspt": False, "msptLimit": 65, "botToken": "never-copy"}, "customMessage": {"serverStarted": "創造服已啟動"}}),
        ("mirror", "鏡像服", {"generic": {"channelId": "123456789012345678", "consoleLogChannelId": "323456789012345678", "announceHighMspt": False, "msptLimit": 65}, "customMessage": {"serverStarted": "創造服已啟動"}}),
    ]
    result = migrate(legacy)
    assert result["state"]["channel_groups"]["123456789012345678"]["server_ids"] == ["survival", "creative", "mirror"]
    assert result["dmcc"]["monitoring"]["servers"]["survival"]["mspt_threshold"] == 150
    assert result["dmcc"]["monitoring"]["servers"]["creative"]["alert_channel_id"] is None
    assert result["state"]["channel_groups"]["123456789012345678"]["attachments"] is True
    assert result["state"]["channel_groups"]["123456789012345678"]["embeds"] is False
    assert result["dmcc"]["presentation"]["servers"]["mirror"]["label"] == "鏡像服"
    assert "never-copy" not in str(result)


def test_migrated_fragment_is_accepted_by_the_new_settings_parser():
    legacy = {"generic": {
        "channelId": "123456789012345678", "consoleLogChannelId": "223456789012345678",
        "announceHighMspt": True, "msptLimit": 150, "avatarApi": True,
    }}
    fragment = migrate([("survival", "生存服", legacy)])["dmcc"]
    settings = DmccSettings.from_mapping({
        **DEFAULT_SETTINGS, **fragment,
        "servers": [{"server_id": "survival", "bridge": {
            "enabled": True, "secret_env": "SURVIVAL_SECRET",
        }}],
    }, environ={"SURVIVAL_SECRET": "local-test-secret"})
    assert settings.monitoring.servers["survival"].mspt_threshold == 150
    assert settings.console_stream.servers["survival"] == "223456789012345678"
    assert settings.avatar_refresh.source == "fabric"
    assert settings.private_messages.enabled is False


def test_migrated_shared_channel_state_is_accepted_by_state_repository(tmp_path):
    result = migrate([
        ("survival", "生存服", {"generic": {"channelId": "123456789012345678"}}),
        ("creative", "創造服", {"generic": {"channelId": "123456789012345678"}}),
        ("mirror", "鏡像服", {"generic": {"channelId": "123456789012345678"}}),
    ])
    state_path = tmp_path / "state.json"
    state = JsonStateRepository(state_path)
    state._file.write(result["state"])
    assert state.channel_group_for_channel("123456789012345678")["server_ids"] == [
        "survival", "creative", "mirror",
    ]


def test_migration_drops_invalid_optional_ids_and_normalizes_mspt():
    result = migrate([("survival", "生存服", {"generic": {
        "channelId": "invalid", "consoleLogChannelId": "short", "announceHighMspt": True,
        "updateChannelTopic": True, "msptLimit": "too-high",
    }})])
    monitor = result["dmcc"]["monitoring"]["servers"]["survival"]
    assert monitor["alert_channel_id"] is None
    assert monitor["topic_channel_id"] is None
    assert monitor["mspt_threshold"] == 65.0
    assert result["dmcc"]["console_stream"]["servers"] == {}


def test_migration_drops_templates_that_the_new_parser_cannot_render():
    result = migrate([("survival", "生存服", {"customMessage": {
        "serverStarted": "{unknown}", "joinServer": "{player!r}", "leftServer": "{player}",
    }})])
    templates = result["dmcc"]["presentation"]["servers"]["survival"]["templates"]
    assert templates == {"player_quit": "{player}"}
