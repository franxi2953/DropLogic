"""Front panel display module facade."""

from __future__ import annotations

import threading
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
        self._control_lock = threading.RLock()
        self._owner = "local"

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

    def start_animation(self, expression: Optional[str] = None):
        """Start the underlying background animation loop."""
        return self.front_panel.start_animation(expression)

    def stop_animation(self):
        """Stop the underlying background animation loop."""
        return self.front_panel.stop_animation()

    def notify_action(self, path: str, value: Any = None):
        """Let the face react to a BOXMini hardware action."""
        return self.front_panel.notify_action(path, value)

    def claim_control(
        self,
        owner: str,
        *,
        expression: Optional[str] = None,
        immediate: bool = False,
        start_animation: Optional[bool] = None,
    ):
        """Mark a logical owner and optionally update the displayed state."""
        with self._control_lock:
            self._owner = str(owner or "unknown")
            if start_animation is True:
                self.front_panel.start_animation(
                    expression,
                    source="claim_control",
                    reason=f"owner={self._owner}",
                )
            elif start_animation is False:
                self.front_panel.stop_animation(
                    source="claim_control",
                    reason=f"owner={self._owner}",
                )
            if expression is not None:
                return self.front_panel.set_expression(
                    expression,
                    immediate=immediate,
                    source="claim_control",
                    reason=f"owner={self._owner}",
                )
            return True

    def release_control(
        self,
        owner: str,
        *,
        fallback_owner: Optional[str] = None,
        expression: Optional[str] = None,
        immediate: bool = False,
        start_animation: Optional[bool] = None,
    ):
        """Release a logical owner and optionally switch to a fallback state."""
        with self._control_lock:
            if self._owner == owner:
                self._owner = str(fallback_owner or "unclaimed")
            if start_animation is True:
                self.front_panel.start_animation(
                    expression,
                    source="release_control",
                    reason=f"owner={owner};fallback={self._owner}",
                )
            elif start_animation is False:
                self.front_panel.stop_animation(
                    source="release_control",
                    reason=f"owner={owner};fallback={self._owner}",
                )
            if expression is not None:
                return self.front_panel.set_expression(
                    expression,
                    immediate=immediate,
                    source="release_control",
                    reason=f"owner={owner};fallback={self._owner}",
                )
            return True

    @property
    def owner(self) -> str:
        return self._owner

    def blackout(self):
        """Turn the panel black and stop background animation."""
        self.front_panel.stop_animation()
        return self.front_panel.blackout()

    def close(self, *, blackout: bool = False):
        """Close the version-specific controller."""
        return self.front_panel.close(blackout=blackout)
