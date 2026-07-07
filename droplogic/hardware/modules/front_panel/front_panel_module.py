"""Front panel display module facade."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .front_panel_factory import FrontPanelFactory
from .versions.droptibot_v1 import DroptiBotV1


class FrontPanelModule:
    """Handles front panel operations with version control."""

    SUPPORTED_VERSIONS = {
        "DroptiBot v1.0": "DroptiBotV1",
        "DroptiBotV1": "DroptiBotV1",
    }

    DEFAULT_VERSION = "DroptiBot v1.0"
    DEFAULT_PORT = DroptiBotV1.DEFAULT_PORT
    DEFAULT_BAUDRATE = DroptiBotV1.DEFAULT_BAUDRATE
    DEFAULT_ADDRESS = DroptiBotV1.DEFAULT_ADDRESS
    DEFAULT_WIDTH = DroptiBotV1.DEFAULT_WIDTH
    DEFAULT_HEIGHT = DroptiBotV1.DEFAULT_HEIGHT

    def __init__(self, parent=None, version: str = DEFAULT_VERSION, **config):
        self.parent = parent
        normalized = FrontPanelFactory.normalize_version(version)
        if normalized not in self.SUPPORTED_VERSIONS.values():
            raise ValueError(f"Unsupported front panel version: {version}")
        self.version = version
        self.front_panel = FrontPanelFactory.create_front_panel(version, config=config, parent=parent)

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]], parent=None):
        """Create a front panel module from a DropLogic config block."""
        config = dict(config or {})
        version = config.pop("version", cls.DEFAULT_VERSION)
        return cls(parent=parent, version=version, **config)

    @staticmethod
    def is_ack(response: str) -> bool:
        """Return whether a response looks like a front panel ACK."""
        return DroptiBotV1.is_ack(response)

    def build_text_packet(self, text: Any, **kwargs):
        """Build a version-specific text packet."""
        return self.front_panel.build_text_packet(text, **kwargs)

    def build_clear_packet(self):
        """Build a version-specific clear packet."""
        return self.front_panel.build_clear_packet()

    def build_program_packet(self, program: int):
        """Build a version-specific program switch packet."""
        return self.front_panel.build_program_packet(program)

    def set_text(self, text: Any, **kwargs):
        """Display text on the front panel."""
        return self.front_panel.set_text(text, **kwargs)

    def clear(self):
        """Clear the front panel."""
        return self.front_panel.clear()

    def select_program(self, program: int):
        """Switch to a stored program on the front panel controller."""
        return self.front_panel.select_program(program)

    def set_expression(self, expression: str, **kwargs):
        """Show an animated DroptiBot expression."""
        return self.front_panel.set_expression(expression, **kwargs)

    def notify_action(self, path: str, value: Any = None):
        """Let the face react to a BOXMini hardware action."""
        return self.front_panel.notify_action(path, value)

    def close(self):
        """Close the version-specific controller."""
        return self.front_panel.close()
