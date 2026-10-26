"""
Load and validate RSS-Syphon global settings and selected profile configuration.

syphon.toml selects the profile directory, enables integrations globally, and
supplies shared credentials and module settings. Profiles own feed lists,
keywords, jobs, and output routing. No integration or network clients are
imported while configuration is loaded.
"""

import logging
import os
import re
import tomllib
from pathlib import Path


# Local scripts run under src/. Docker copies src/ directly into /app/.
_PACKAGE_DIR = Path(__file__).resolve().parent
_SOURCE_DIR = _PACKAGE_DIR.parent
PROJECT_ROOT = _SOURCE_DIR if (_SOURCE_DIR / "syphon.toml").is_file() else _SOURCE_DIR.parent

_NAME_PATTERN = r"[a-z][a-z0-9_]*"
logger = logging.getLogger(__name__)

# TODO set up secret management. For now credentials come from environment
# references rather than being stored in the checked-in profile files.


def _profile_path(root: Path, filename: str) -> Path:
    """
    Resolve a config-owned path without allowing directory escape.

    :param root: Expected parent directory.
    :param filename: Relative path from configuration.
    :return: Canonical child path.
    :raises ValueError: If the path is absolute or escapes its parent.
    """
    if not isinstance(filename, str) or not filename or Path(filename).is_absolute():
        raise ValueError(f"Config path must be relative: {filename!r}")

    parent = root.resolve()
    path = (parent / filename).resolve()
    if not path.is_relative_to(parent):
        raise ValueError(f"Config path escapes {parent}: {filename}")
    return path


def _resolve_env(value: object) -> object:
    """
    Resolve explicit ``env:NAME`` references without exposing their values.

    :param value: TOML value or nested table/list.
    :return: Equivalent value with environment references resolved.
    :raises ValueError: If an environment reference has an invalid name.
    """
    if isinstance(value, dict):
        return {key: _resolve_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env(item) for item in value]
    if isinstance(value, str) and value.startswith("env:"):
        name = value[4:]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("Invalid environment variable reference in configuration")
        return os.getenv(name, "")
    return value


def _merge_module_settings(module_name: str, defaults: dict, overrides: dict) -> dict:
    """
    Apply profile choices without allowing profiles to supply credentials.

    Global module settings provide defaults, while profile settings may select
    their own destination details. Credential-looking
    fields always belong to the global config, even for disabled modules.

    :param module_name: Name of the configured integration.
    :param defaults: Settings from syphon.toml.
    :param overrides: Settings from the selected profile.
    :return: Merged integration settings with global credentials retained.
    """
    params = {**defaults, **overrides}
    for key in overrides:
        lowered = key.lower()
        if (any(part in lowered for part in ("key", "token", "secret", "password", "credential"))
                or lowered.endswith(("_pass", "_user"))):
            # Keep profiles portable without permitting them to replace credentials.
            # Log the field name, never the potentially sensitive value.
            logger.warning("Ignoring profile credential field '%s' for module '%s'", key, module_name)
            if key in defaults:
                params[key] = defaults[key]
            else:
                params.pop(key, None)
    return params


def _config_directory(project_root: Path, setting: str, value: str) -> Path:
    """
    Resolve a main-config directory setting relative to syphon.toml.

    Absolute directory locations are intentional and permitted here. Paths
    inside the selected profile directory remain separately contained.

    :param project_root: Directory containing syphon.toml.
    :param setting: Setting name for diagnostic messages.
    :param value: Absolute or relative directory path.
    :return: Resolved directory.
    :raises ValueError: If the configured directory is invalid.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"[system].{setting} must be a nonempty directory path")
    return (project_root / value).resolve()


def load_system(*, project_root: Path = PROJECT_ROOT) -> dict:
    """
    Read the single global configuration file without importing integrations.

    :param project_root: Directory containing syphon.toml.
    :return: Validated settings, enabled module names, and shared credentials.
    :raises ValueError: If the main configuration is missing or malformed.
    """
    project_root = Path(project_root).resolve()
    try:
        with (project_root / "syphon.toml").open("rb") as stream:
            global_config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Cannot load syphon.toml: {exc}") from exc

    for section in ("system", "modules"):
        if not isinstance(global_config.get(section, {}), dict):
            raise ValueError(f"syphon.toml [{section}] must be a TOML table")

    system = global_config.get("system", {})
    enabled = global_config.get("modules", {}).get("enabled", [])
    if not isinstance(enabled, list) or any(
        not isinstance(name, str) or not re.fullmatch(_NAME_PATTERN, name)
        for name in enabled
    ) or len(enabled) != len(set(enabled)):
        raise ValueError("syphon.toml [modules].enabled must contain unique module names")

    # A globally enabled module is an explicit deployment dependency. Modules
    # mentioned only in a profile can be absent or disabled on this host.
    for name in enabled:
        if not (_PACKAGE_DIR / "modules" / f"{name}.py").is_file():
            raise ValueError(f"Globally enabled module '{name}' is not installed")

    modules = dict(global_config.get("modules", {}))
    modules.pop("enabled", None)
    if any(not re.fullmatch(_NAME_PATTERN, name) or not isinstance(params, dict)
           for name, params in modules.items()):
        raise ValueError("syphon.toml [modules.<name>] entries must be TOML tables")

    selected = system.get("default_profile", "security")
    if not isinstance(selected, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", selected):
        raise ValueError("syphon.toml [system].default_profile is invalid")

    return {
        "default_profile": selected,
        "profiles_dir": _config_directory(
            project_root, "profiles_dir", system.get("profiles_dir")
        ),
        "root_data_dir": _config_directory(
            project_root, "root_data_dir", system.get("root_data_dir", "./output")
        ),
        "logging": {
            "level": os.getenv("LOG_LEVEL") or system.get("log_level", "INFO"),
            "format": os.getenv("LOG_FORMAT") or system.get(
                "log_format", "%(levelname)s:%(name)s: %(message)s"
            ),
        },
        "enabled_modules": enabled,
        "modules": _resolve_env(modules),
    }


def load_config(name: str | None = None, *, project_root: Path = PROJECT_ROOT) -> dict:
    """
    Read and combine the global configuration and one selected profile.

    Preserves original integration parameter dictionaries at dispatch. Dataset
    validation and dataset loading belong to data.load_data().

    :param name: Profile name, defaulting to RSS_PROFILE or the main config.
    :param project_root: Directory containing syphon.toml.
    :return: Resolved configuration containing dataset definitions and paths.
    :raises ValueError: If configuration is missing, malformed, or unsafe.
    """
    project_root = Path(project_root).resolve()
    global_config = load_system(project_root=project_root)
    selected = name or os.getenv("RSS_PROFILE") or global_config["default_profile"]
    if not isinstance(selected, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", selected):
        raise ValueError(f"Invalid profile name: {selected!r}")

    profile_root = global_config["profiles_dir"]
    profile_dir = _profile_path(profile_root, selected)
    config_file = _profile_path(profile_dir, "profile.toml")
    try:
        with config_file.open("rb") as stream:
            profile = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Cannot load profile '{selected}': {exc}") from exc

    for section in ("jobs", "outputs", "modules"):
        if not isinstance(profile.get(section, {}), dict):
            raise ValueError(f"[{section}] must be a TOML table")

    # Keep profile configuration separate from the datasets consumed by data.py.
    for section in ("feeds", "keywords"):
        if section in profile:
            raise ValueError(f"Move [{section}] from profile.toml to {section}.toml")

    profile["name"] = selected
    profile["logging"] = global_config["logging"]
    profile["enabled_modules"] = global_config["enabled_modules"]
    profile["_profile_root"] = profile_dir

    modules = profile.get("modules", {})
    for module_name, params in modules.items():
        if not re.fullmatch(_NAME_PATTERN, module_name) or not isinstance(params, dict):
            raise ValueError(f"Invalid profile module: {module_name}")

    for job, destinations in profile.get("outputs", {}).items():
        if not isinstance(destinations, list) or any(
            not isinstance(module, str) or not re.fullmatch(_NAME_PATTERN, module)
            for module in destinations
        ):
            raise ValueError(f"Invalid destinations for [outputs].{job}")

    # The main config owns enablement and credentials; profile-specific module
    # options override global defaults.
    # Preserve the old module dispatch shape.
    profile["modules"] = {}
    for module_name in sorted(modules.keys() | global_config["modules"].keys()
                              | set(profile["enabled_modules"])):
        params = _merge_module_settings(
            module_name, global_config["modules"].get(module_name, {}), modules.get(module_name, {})
        )
        params[f"{module_name}_enabled"] = module_name in profile["enabled_modules"]
        profile["modules"][module_name] = _resolve_env(params)

    # Configured file output stays under root_data_dir/<profile>. The legacy explicit
    # RSS_LOCAL_OUTPUT_FILE override remains unrestricted and user-controlled.
    files = profile["modules"].get("files", {})
    if files:
        if files.get("destination", "stdout") not in ("stdout", "file"):
            raise ValueError("[modules.files].destination must be stdout or file")
        if not isinstance(files.get("report", False), bool):
            raise ValueError("[modules.files].report must be true or false")
        profile_output_root = _profile_path(global_config["root_data_dir"], selected)
        files["path"] = str(_profile_path(
            profile_output_root, files.get("path", "results.ndjson")
        ))

    return profile
