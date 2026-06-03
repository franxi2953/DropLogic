from .versions.xy_stage_v1 import XYStageV1


class XYStageFactory:
    SUPPORTED_VERSIONS = {
        "XYStageV1": XYStageV1,
        # Future versions can be added here
    }

    @staticmethod
    def create_stage(version="XYStageV1", parent=None):
        """Creates and returns an instance of the requested stage version."""
        if version not in XYStageFactory.SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported XYZ stage version: {version}")

        return XYStageFactory.SUPPORTED_VERSIONS[version](parent=parent)
