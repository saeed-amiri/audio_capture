"""Shared configuration loading utilities for the project.

This module is intentionally service-agnostic and is meant to be reused by all
workers and services that need runtime settings from the repository config.
"""

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.isdigit():
        return int(value)
    return value.strip("\"'")


def _fallback_yaml_load(text: str) -> dict[str, Any]:
    """Parse a very small subset of YAML used by this project.

    This is intentionally limited and only meant to keep the CLI working when
    PyYAML is unavailable in the runtime environment.
    """

    result: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(0, result)]
    lines = text.splitlines()
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            index += 1
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        parent = stack[-1][1]
        if stripped.startswith("- "):
            if not isinstance(parent, list):
                raise ValueError(
                    "Fallback YAML parser only supports list values for block lists"
                )
            parent.append(_parse_scalar(stripped[2:].strip()))
            index += 1
            continue

        if ":" not in stripped:
            index += 1
            continue

        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()

        if value:
            parent[key] = _parse_scalar(value)
            index += 1
            continue

        next_index = index + 1
        next_indent = None
        while next_index < len(lines):
            candidate = lines[next_index]
            if not candidate.strip() or candidate.lstrip().startswith("#"):
                next_index += 1
                continue
            next_indent = len(candidate) - len(candidate.lstrip(" "))
            break

        if (
            next_index < len(lines)
            and next_indent is not None
            and next_indent > indent
            and lines[next_index].strip().startswith("- ")
        ):
            child: list[Any] | dict[str, Any] = []
        else:
            child = {}

        parent[key] = child
        stack.append((indent, child))
        index += 1

    return result


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "settings.yaml"
"""Default configuration file path used when no override is provided."""


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dictionary.

    Args:
        path: The YAML file to read.

    Returns:
        A dictionary containing the parsed YAML content.

    Raises:
        RuntimeError: If no YAML parser is available.
    """
    with path.open("r", encoding="utf-8") as handle:
        text = handle.read()

    if yaml is not None:
        return yaml.safe_load(text) or {}

    return _fallback_yaml_load(text)


def resolve_config_path(config_path: Path | None = None) -> Path:
    """Resolve the configuration path using the available override sources.

    Resolution order:
    1. an explicitly supplied path
    2. the CONFIG_FILE environment variable
    3. the repository default config file

    Args:
        config_path: Optional explicit config path to use.

    Returns:
        The selected configuration path.
    """
    if config_path is not None:
        return config_path

    env_path = os.getenv("CONFIG_FILE")
    if env_path:
        return Path(env_path)

    return DEFAULT_CONFIG_PATH


def validate_required_sections(
    config: dict[str, Any],
    required_sections: set[str],
    path: Path,
) -> dict[str, Any]:
    """Validate that the config contains the required top-level sections.

    Args:
        config: Parsed configuration dictionary.
        required_sections: Set of top-level sections that must be present.
        path: The config file path being validated.

    Returns:
        The validated config dictionary.

    Raises:
        ValueError: If any required sections are missing.
    """
    if not isinstance(config, dict):
        raise TypeError(
            f"Config file '{path}' must contain a YAML mapping at the top level"
        )

    missing_sections = sorted(required_sections - set(config.keys()))
    if missing_sections:
        raise ValueError(
            f"Config file '{path}' is missing required top-level section(s): {', '.join(missing_sections)}"
        )

    return config


def validate_required_mapping_fields(
    config: dict[str, Any],
    section_name: str,
    required_fields: set[str],
    path: Path,
) -> dict[str, Any]:
    """Validate that a nested mapping section contains the required fields.

    Args:
        config: Parsed configuration dictionary.
        section_name: The nested section name to validate.
        required_fields: Fields that must be present inside the section.
        path: The config file path being validated.

    Returns:
        The validated config dictionary.

    Raises:
        ValueError: If the section is missing or incomplete.
    """
    if not isinstance(config, dict):
        raise TypeError(
            f"Config file '{path}' must contain a YAML mapping at the top level"
        )

    section = config.get(section_name)
    if not isinstance(section, dict):
        raise TypeError(
            f"Config file '{path}' must define '{section_name}' as a mapping"
        )

    missing_fields = sorted(required_fields - set(section.keys()))
    if missing_fields:
        raise ValueError(
            f"Config file '{path}' is missing required field(s) for '{section_name}': {', '.join(missing_fields)}"
        )

    return config


def load_config(
    config_path: Path | None = None,
    required_sections: set[str] | None = None,
) -> dict[str, Any]:
    """Load the YAML configuration from the resolved config path.

    Shared, project-wide sections are validated by default. Additional validations
    can be applied by callers when needed.

    Args:
        config_path: Optional explicit config path to use instead of the defaults.
        required_sections: Optional set of top-level sections that must be present.

    Returns:
        The parsed configuration values as a dictionary.

    Raises:
        ValueError: If the YAML content is invalid or missing required sections.
    """
    path = resolve_config_path(config_path)
    if not path.exists():
        return {}

    config = _load_yaml(path)
    if required_sections is not None:
        validate_required_sections(config, required_sections, path)
    return config
