"""DropSystem module package.

Modules are imported lazily so lightweight systems such as DMLite do not load
optional BOXMini-only integrations and native drivers at import time.
"""

_MODULE_EXPORTS = {
    "TemperatureModule": (".temperature", "TemperatureModule"),
    "ElectrodeMatrixModule": (".electrode_matrix", "ElectrodeMatrixModule"),
    "CapacitiveFeedbackModule": (".capacitive_feedback", "CapacitiveFeedbackModule"),
    "MicroscopeModule": (".microscope", "MicroscopeModule"),
    "XYStageModule": (".xy_stage", "XYStageModule"),
    "CameraModule": (".camera", "CameraModule"),
    "LightModule": (".light", "LightModule"),
}

__all__ = [
    "TemperatureModule",
    "ElectrodeMatrixModule",
    "CapacitiveFeedbackModule",
    "MicroscopeModule",
    "XYStageModule",
    "CameraModule",
    "LightModule",  
]


def __getattr__(name):
    if name not in _MODULE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _MODULE_EXPORTS[name]
    from importlib import import_module

    module = import_module(module_name, __name__)
    attr = getattr(module, attr_name)
    globals()[name] = attr
    return attr
