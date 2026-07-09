"""Factory for front panel display implementations."""


class FrontPanelFactory:
    """Create front panel controller instances for supported versions."""

    VERSION_ALIASES = {
        "DroptiBot v1.0": "DroptiBotV1",
        "DroptiBotV1": "DroptiBotV1",
        "DroptiBot1": "DroptiBotV1",
    }

    @classmethod
    def normalize_version(cls, version):
        return cls.VERSION_ALIASES.get(version, version)

    @classmethod
    def create_front_panel(cls, version, config=None, parent=None):
        normalized = cls.normalize_version(version)
        config = dict(config or {})
        config.pop("enabled", None)
        config.pop("version", None)

        if normalized == "DroptiBotV1":
            from .versions.droptibot_v1 import DroptiBotV1

            return DroptiBotV1(parent=parent, **config)

        raise ValueError(f"Unsupported front panel version: {version}")
