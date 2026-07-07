"""Shared front panel data types."""

from dataclasses import dataclass


@dataclass
class FrontPanelResponse:
    """Result returned after writing a command to the front panel."""

    ok: bool
    response: str
    packet: str
