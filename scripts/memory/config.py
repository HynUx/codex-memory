"""Memory system configuration loading."""

import os

DEFAULT_CONFIG = {
    "auto_evolve_enabled": True,
    "auto_evolve_threshold": 10,
    "stale_evolve_days": 7,
    "learner_model": "deepseek-v4-flash",
}


def load_config(config_path=None):
    """Load TOML config from config_path, falling back to defaults.

    Args:
        config_path: Path to config.toml. If None, uses CONFIG_PATH from
                     the caller's module (backward-compatible).

    Returns:
        dict with keys from DEFAULT_CONFIG, overlaid with file values.
    """
    cfg = dict(DEFAULT_CONFIG)
    # Simple TOML-ish parser — enough for our flat key=value format
    if config_path is not None and os.path.exists(config_path):
        with open(config_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if val.lower() in ("true", "yes"):
                        val = True
                    elif val.lower() in ("false", "no"):
                        val = False
                    else:
                        try:
                            val = int(val)
                        except ValueError:
                            pass
                    cfg[key] = val
    return cfg
