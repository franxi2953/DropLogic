DEFAULT_INITIAL_VOLTAGE_PROFILE = (60, 55, 55, 55, 55, 55, 55, 55, 55)


def default_initial_voltage_profile():
    return list(DEFAULT_INITIAL_VOLTAGE_PROFILE)


def resolve_initial_voltage_profile(config):
    config = config or {}
    initial_voltages = config.get("initial_voltages")
    if initial_voltages is not None:
        return initial_voltages
    if "voltage" in config:
        value = int(config.get("voltage", DEFAULT_INITIAL_VOLTAGE_PROFILE[0]))
        return [value] * 9
    return default_initial_voltage_profile()
