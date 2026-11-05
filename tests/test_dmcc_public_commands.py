"""Public Minecraft command events require independent gateway-side privacy checks."""
from bot.mod.dmcc.events import MinecraftEvent
from bot.mod.dmcc.services.public_commands import sanitize_public_player_command
from bot.mod.dmcc.services.presentation import PresentationSettings, render_message


def test_public_command_allowlist_and_private_command_filter():
    assert sanitize_public_player_command("/say hello") == "/say hello"
    assert sanitize_public_player_command("/me waves") == "/me waves"
    assert sanitize_public_player_command("/msg Steve password") is None
    assert sanitize_public_player_command("/login password") is None
    assert sanitize_public_player_command("/tellraw @a[tag=private] hi") is None
    assert sanitize_public_player_command("say hi\n/private") is None


def test_public_player_command_presentation_never_renders_private_input():
    profile = PresentationSettings.from_mapping({
        "servers": {"survival": {"label": "生存服"}}
    }).servers["survival"]
    safe = MinecraftEvent("player_command", "survival", {
        "player_name": "Steve", "message": "/say hi",
    })
    assert render_message(safe, profile, "123456789012345678").content.endswith("/say hi**")
    private = MinecraftEvent("player_command", "survival", {
        "player_name": "Steve", "message": "/login secret",
    })
    assert render_message(private, profile, "123456789012345678") is None
