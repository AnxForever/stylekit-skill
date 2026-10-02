#!/usr/bin/env python3
"""Load and normalize StyleKit specs from HTTP, CLI, or MCP JSON files."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


BRIEF_SCHEMA = "stylekit-brief-v1"


def normalize_base_url(value: str | None, default: str) -> str:
    """Accept an origin, an /api prefix, or the complete /api/styles base."""
    raw = (value or default).strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("base URL must be an http:// or https:// URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL must not contain credentials, a query, or a fragment")
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/styles"):
        path = f"{path}/styles" if path.endswith("/api") else f"{path}/api/styles"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def normalize_spec(spec: dict) -> dict:
    """Flatten the legacy `{styleSlug, recipes}` wrapper without losing metadata."""
    result = dict(spec)
    recipes = result.get("recipes") or {}
    for _ in range(3):
        if not isinstance(recipes, dict):
            recipes = {}
            break
        nested = recipes.get("recipes")
        if isinstance(nested, dict):
            recipes = nested
            continue
        components = recipes.get("components")
        if isinstance(components, dict):
            recipes = components
            continue
        break
    result["recipes"] = recipes
    return result


def _require_string_fields(value: object, fields: tuple[str, ...], label: str) -> dict:
    if not isinstance(value, dict) or not all(isinstance(value.get(field), str) for field in fields):
        raise ValueError(f"incomplete stylekit-brief-v1: {label} must include string fields {', '.join(fields)}")
    return value


def _require_string_array(value: object, label: str) -> list:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"incomplete stylekit-brief-v1: {label} must be a string array")
    return value


def _validate_tokens(tokens: object) -> None:
    if tokens is None:
        return
    if not isinstance(tokens, dict):
        raise ValueError("incomplete stylekit-brief-v1: tokens must be null or an object")

    border = _require_string_fields(tokens.get("border"), ("width", "color", "radius"), "tokens.border")
    if "style" in border and not isinstance(border["style"], str):
        raise ValueError("incomplete stylekit-brief-v1: tokens.border.style must be a string")

    shadow = _require_string_fields(tokens.get("shadow"), ("sm", "md", "lg", "none", "hover", "focus"), "tokens.shadow")
    if "colored" in shadow and (
        not isinstance(shadow["colored"], dict)
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in shadow["colored"].items())
    ):
        raise ValueError("incomplete stylekit-brief-v1: tokens.shadow.colored must map strings to strings")
    interaction = _require_string_fields(tokens.get("interaction"), ("transition",), "tokens.interaction")
    for field in ("hoverScale", "hoverTranslate", "hoverOpacity", "active"):
        if field in interaction and not isinstance(interaction[field], str):
            raise ValueError(f"incomplete stylekit-brief-v1: tokens.interaction.{field} must be a string")

    typography = _require_string_fields(tokens.get("typography"), ("heading", "body"), "tokens.typography")
    _require_string_fields(typography.get("sizes"), ("hero", "h1", "h2", "h3", "body", "small"), "tokens.typography.sizes")
    for field in ("subtitle", "mono"):
        if field in typography and not isinstance(typography[field], str):
            raise ValueError(f"incomplete stylekit-brief-v1: tokens.typography.{field} must be a string")

    spacing = _require_string_fields(tokens.get("spacing"), ("section", "container", "card"), "tokens.spacing")
    _require_string_fields(spacing.get("gap"), ("sm", "md", "lg"), "tokens.spacing.gap")

    colors = tokens.get("colors")
    if not isinstance(colors, dict):
        raise ValueError("incomplete stylekit-brief-v1: tokens.colors must be an object")
    background = _require_string_fields(colors.get("background"), ("primary", "secondary"), "tokens.colors.background")
    _require_string_array(background.get("accent"), "tokens.colors.background.accent")
    _require_string_fields(colors.get("text"), ("primary", "secondary", "muted"), "tokens.colors.text")
    button = _require_string_fields(colors.get("button"), ("primary", "secondary"), "tokens.colors.button")
    if "danger" in button and not isinstance(button["danger"], str):
        raise ValueError("incomplete stylekit-brief-v1: tokens.colors.button.danger must be a string")

    forbidden = tokens.get("forbidden")
    if not isinstance(forbidden, dict):
        raise ValueError("incomplete stylekit-brief-v1: tokens.forbidden must be an object")
    _require_string_array(forbidden.get("classes"), "tokens.forbidden.classes")
    _require_string_array(forbidden.get("patterns"), "tokens.forbidden.patterns")
    reasons = forbidden.get("reasons")
    if not isinstance(reasons, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in reasons.items()):
        raise ValueError("incomplete stylekit-brief-v1: tokens.forbidden.reasons must map strings to strings")

    required = tokens.get("required")
    if not isinstance(required, dict):
        raise ValueError("incomplete stylekit-brief-v1: tokens.required must be an object")
    for component in ("button", "card", "input"):
        _require_string_array(required.get(component), f"tokens.required.{component}")


def _validate_readiness(readiness: object) -> None:
    if not isinstance(readiness, dict):
        raise ValueError("incomplete stylekit-brief-v1: readiness must be an object")
    for key in ("styleSlug", "source"):
        if not isinstance(readiness.get(key), str):
            raise ValueError(f"incomplete stylekit-brief-v1: readiness.{key} must be a string")
    for key in ("themeModes", "promptAddons"):
        _require_string_array(readiness.get(key), f"readiness.{key}")

    dark_mode = _require_string_fields(readiness.get("darkMode"), ("support", "strategy"), "readiness.darkMode")
    _require_string_array(dark_mode.get("guidance"), "readiness.darkMode.guidance")
    states = readiness.get("states")
    if not isinstance(states, dict):
        raise ValueError("incomplete stylekit-brief-v1: readiness.states must be an object")
    for name, check in states.items():
        check = _require_string_fields(check, ("support",), f"readiness.states.{name}")
        _require_string_array(check.get("guidance"), f"readiness.states.{name}.guidance")
    components = readiness.get("components")
    if not isinstance(components, dict):
        raise ValueError("incomplete stylekit-brief-v1: readiness.components must be an object")
    for name, component in components.items():
        component = _require_string_fields(component, (), f"readiness.components.{name}")
        _require_string_array(component.get("states"), f"readiness.components.{name}.states")
        _require_string_array(component.get("guidance"), f"readiness.components.{name}.guidance")
    for key, extra in (("motion", ("duration", "easing", "reducedMotion")),
                       ("accessibility", ("focus", "targetSize", "aria")),
                       ("performance", ())):
        check = _require_string_fields(readiness.get(key), ("support", *extra), f"readiness.{key}")
        _require_string_array(check.get("guidance"), f"readiness.{key}.guidance")
        if key == "performance":
            _require_string_array(check.get("costs"), "readiness.performance.costs")
    coverage = readiness.get("coverage")
    coverage_keys = ("darkMode", "states", "motion", "accessibility", "performance", "overall")
    if not isinstance(coverage, dict) or not all(
        isinstance(coverage.get(key), (int, float)) and not isinstance(coverage.get(key), bool)
        for key in coverage_keys
    ):
        raise ValueError("incomplete stylekit-brief-v1: readiness.coverage must contain numeric coverage scores")


def _validate_brief(spec: dict) -> None:
    strings = ("name", "nameEn", "category", "styleType", "description", "philosophy", "aiRules", "globalCss")
    for key in strings:
        if not isinstance(spec.get(key), str):
            raise ValueError(f"incomplete stylekit-brief-v1: '{key}' must be a string")
    for key in ("tags", "keywords", "doList", "dontList", "variants"):
        value = spec.get(key)
        if not isinstance(value, list) or (key != "variants" and not all(isinstance(item, str) for item in value)):
            raise ValueError(f"incomplete stylekit-brief-v1: '{key}' must be an array")

    colors = spec.get("colors")
    if not isinstance(colors, dict) or not isinstance(colors.get("primary"), str) or not isinstance(colors.get("secondary"), str):
        raise ValueError("incomplete stylekit-brief-v1: colors must include primary and secondary strings")
    if not isinstance(colors.get("accent"), list) or not all(isinstance(item, str) for item in colors["accent"]):
        raise ValueError("incomplete stylekit-brief-v1: colors.accent must be a string array")

    components = spec.get("components")
    recipes = spec.get("recipes")
    if not isinstance(components, dict) or not all(isinstance(item, dict) and isinstance(item.get("code"), str) for item in components.values()):
        raise ValueError("incomplete stylekit-brief-v1: components must map to objects with code strings")
    if not isinstance(recipes, dict):
        raise ValueError("incomplete stylekit-brief-v1: recipes must be an object")

    _validate_tokens(spec.get("tokens"))
    _validate_readiness(spec.get("readiness"))

    rules = spec.get("lintRules")
    if not isinstance(rules, dict) or rules.get("schemaVersion") != "stylekit-lint-v1":
        raise ValueError("incomplete stylekit-brief-v1: lintRules must use stylekit-lint-v1")
    for key in ("sources", "forbiddenClasses", "forbiddenPatterns", "exempt", "unsupportedRules"):
        if not isinstance(rules.get(key), list):
            raise ValueError(f"incomplete stylekit-brief-v1: lintRules.{key} must be an array")
    if not all(isinstance(value, str) for value in rules["sources"] + rules["exempt"] + rules["unsupportedRules"]):
        raise ValueError("incomplete stylekit-brief-v1: lint rule sources, exemptions, and unsupported rules must be strings")
    if not isinstance(rules.get("required"), dict):
        raise ValueError("incomplete stylekit-brief-v1: lintRules.required must be an object")
    if not all(isinstance(item, dict) and all(isinstance(item.get(key), str) for key in ("className", "reason", "source")) for item in rules["forbiddenClasses"]):
        raise ValueError("incomplete stylekit-brief-v1: forbiddenClasses entries must include className, reason, and source")
    if not all(isinstance(item, dict) and isinstance(item.get("pattern"), str) and isinstance(item.get("source"), str) for item in rules["forbiddenPatterns"]):
        raise ValueError("incomplete stylekit-brief-v1: forbiddenPatterns entries must include pattern and source")
    for component, requirement in rules["required"].items():
        if not isinstance(requirement, dict) or not isinstance(requirement.get("classes"), list) or not all(isinstance(item, str) for item in requirement["classes"]) or not isinstance(requirement.get("source"), str):
            raise ValueError(f"incomplete stylekit-brief-v1: required rules for '{component}' must include string classes and source")

    provenance = spec.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("source") not in ("bundled", "static", "community") or not all(isinstance(provenance.get(key), str) for key in ("contentHash", "url")):
        raise ValueError("incomplete stylekit-brief-v1: provenance must include source, contentHash, and url")


def _contract(spec: object, expected_slug: str | None) -> tuple[dict, str]:
    if not isinstance(spec, dict):
        raise ValueError("file does not contain a JSON StyleKit style object")
    actual = spec.get("slug")
    if not isinstance(actual, str) or not actual:
        raise ValueError("StyleKit spec is missing its slug")
    if expected_slug and actual != expected_slug:
        raise ValueError(f"spec slug mismatch: expected '{expected_slug}', got '{actual}'")
    schema = spec.get("schemaVersion")
    if schema == BRIEF_SCHEMA:
        _validate_brief(spec)
        return spec, BRIEF_SCHEMA
    if schema is not None:
        raise ValueError(f"unsupported StyleKit schemaVersion: {schema}")
    components = spec.get("components")
    recipes = spec.get("recipes")
    tokens = spec.get("tokens")
    if (
        isinstance(components, dict)
        and all(isinstance(item, dict) and isinstance(item.get("code"), str) for item in components.values())
        and "recipes" in spec and (recipes is None or isinstance(recipes, dict))
        and "tokens" in spec and (tokens is None or isinstance(tokens, dict))
        and isinstance(spec.get("aiRules"), str)
    ):
        return spec, "legacy-style-spec"
    raise ValueError("incomplete legacy style spec; use the full style API response or stylekit_get_implementation_brief")


def validate_spec_object(spec: object, expected_slug: str) -> tuple[dict, str]:
    """Validate a complete brief or legacy response and its requested slug."""
    return _contract(spec, expected_slug)


def _parse_text_block(value: str) -> dict:
    text = value.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("MCP text content is not a complete JSON StyleKit brief; save structuredContent when available") from error
    if not isinstance(parsed, dict):
        raise ValueError("MCP text content JSON must be an object")
    return parsed


def _extract_mcp_payload(payload: object, expected_slug: str | None) -> tuple[dict, str]:
    if not isinstance(payload, dict):
        raise ValueError("MCP result must be a JSON object")
    if payload.get("isError") is True:
        raise ValueError("MCP tool result isError=true; save a successful tool result")

    structured = payload.get("structuredContent", payload.get("structured_content"))
    if structured is not None:
        return _contract(structured, expected_slug)[0], "mcp-structuredContent"

    result = payload.get("result")
    if isinstance(result, dict):
        return _extract_mcp_payload(result, expected_slug)

    content = payload.get("content")
    if isinstance(content, list):
        errors = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
                continue
            try:
                candidate = _parse_text_block(block["text"])
                spec, _ = _contract(candidate, expected_slug)
                return spec, "mcp-text-content"
            except ValueError as error:
                errors.append(str(error))
        detail = f": {errors[-1]}" if errors else ""
        raise ValueError("MCP result has no usable structuredContent or JSON text block" + detail)

    # A CLI brief is often copied directly to a file and passed through --from-file.
    return _contract(payload, expected_slug)[0], "direct-json"


def load_spec_file(path: Path, expected_slug: str | None, *, from_mcp: bool = False) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON spec from {path}: {error}") from error

    inherited = payload.get("_stylekitSource") if isinstance(payload, dict) else None
    if from_mcp:
        spec, transport = _extract_mcp_payload(payload, expected_slug)
        source = {
            "kind": transport,
            "contract": spec.get("schemaVersion", "legacy-style-spec"),
            "degraded": spec.get("schemaVersion") != BRIEF_SCHEMA,
        }
        upstream = spec.get("_stylekitSource")
        if isinstance(upstream, dict):
            source["upstream"] = upstream
    else:
        spec, contract = _contract(payload, expected_slug)
        if isinstance(inherited, dict):
            source = {**inherited, "contract": contract, "degraded": contract != BRIEF_SCHEMA}
            if contract == BRIEF_SCHEMA:
                source.pop("reason", None)
        else:
            source = {"kind": "file", "contract": contract, "degraded": contract != BRIEF_SCHEMA}

    if source.get("degraded") and not source.get("reason"):
        source = {**source, "reason": "legacy specs do not include the complete stylekit-brief-v1 lint contract"}
    normalized = normalize_spec(spec)
    normalized["_stylekitSource"] = source
    return normalized
