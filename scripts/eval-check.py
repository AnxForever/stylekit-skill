#!/usr/bin/env python3
"""Static StyleKit rule checks. Exit 0=pass, 1=fail, 2=error, 3=inconclusive.

Use --spec with a saved implementation brief for reproducible offline checks.
Required checks cover a single input file, not each element. --strict enforces
missing requirements; runtime expressions still need manual review.
"""

import argparse
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

from spec_input import load_spec_file


def load_script(name):
    module_spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


fetcher = load_script("fetch-style")
detector = load_script("detect-project")
BASE = fetcher.BASE
get_json = fetcher.get_json
ATTR = re.compile(r"\b(?:className|class)\s*=\s*")


def string_end(code, start):
    quote = code[start]
    pos = start + 1
    while pos < len(code):
        if code[pos] == "\\":
            pos += 2
            continue
        if code[pos] == quote:
            return pos
        pos += 1
    return -1


def brace_end(code, start):
    depth = 0
    pos = start
    while pos < len(code):
        char = code[pos]
        if char in "\"'`":
            end = string_end(code, pos)
            if end < 0:
                return -1
            pos = end + 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    return -1


def blank_interpolations(text):
    pos = 0
    while pos < len(text):
        start = text.find("${", pos)
        if start < 0:
            break
        end = brace_end(text, start + 1)
        stop = len(text) if end < 0 else end + 1
        text = text[:start] + " " * (stop - start) + text[stop:]
        pos = stop
    return text


def _attribute_tokens(code, match):
    start = match.end()
    while start < len(code) and code[start].isspace():
        start += 1
    if start >= len(code):
        return [], start, True
    opener = code[start]
    end = string_end(code, start) if opener in "\"'" else brace_end(code, start) if opener == "{" else -1
    if end < 0:
        return [], start + 1, True
    begin, stop = (start, end + 1) if opener in "\"'" else (start + 1, end)
    value = code[begin:stop].strip()
    literal = re.fullmatch(r'''(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`]*`)''', value, re.S)
    dynamic = not literal or "\\" in value or (value.startswith("`") and "${" in value)
    found = []
    pos = begin
    while pos < stop:
        if code[pos] in "\"'`":
            close = string_end(code, pos)
            if close < 0 or close >= stop:
                break
            text = code[pos + 1:close]
            if code[pos] == "`":
                text = blank_interpolations(text)
            for token in re.finditer(r"\S+", text):
                found.append((token.group(), pos + 1 + token.start()))
            pos = close + 1
        else:
            pos += 1
    return found, end + 1, dynamic


def _is_top_level_tag_position(code, start, end):
    quote, brace_depth, cursor = None, 0, start
    while cursor < end:
        char = code[cursor]
        if quote:
            if char == "\\":
                cursor += 2
                continue
            if char == quote:
                quote = None
        elif brace_depth:
            if char in "\"'`":
                quote = char
            elif char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
        elif char in "\"'`":
            quote = char
        elif char == "{":
            brace_depth = 1
        cursor += 1
    return quote is None and brace_depth == 0


def _is_control_header_close(code, close_position):
    """Return whether this parenthesis closes an if/loop/switch header."""
    stack, position = [], 0
    while position <= close_position:
        if code.startswith("//", position):
            end = code.find("\n", position + 2)
            position = close_position + 1 if end < 0 else end + 1
            continue
        if code.startswith("/*", position):
            end = code.find("*/", position + 2)
            position = close_position + 1 if end < 0 else end + 2
            continue
        char = code[position]
        if char in "\"'`":
            end = string_end(code, position)
            if end < 0:
                return False
            position = end + 1
            continue
        if char == "(":
            before = code[:position].rstrip()
            is_control = re.search(
                r"(?:^|[^\w$.])(?:if|while|for(?:\s+await)?|with|switch|catch)\s*$",
                before,
            )
            stack.append(bool(is_control))
        elif char == ")":
            if not stack:
                return False
            is_control = stack.pop()
            if position == close_position:
                return is_control
        position += 1
    return False


def _regex_literal_end(code, start):
    """Skip likely JavaScript regex literals so their text cannot become JSX context."""
    if code.startswith("/=", start):
        return None
    prefix = code[:start].rstrip()
    if prefix:
        last = prefix[-1]
        expression_start = last in "([{,:;=!?&|+*%^~<>-"
        if last == ")":
            expression_start = _is_control_header_close(code, len(prefix) - 1)
        keyword_start = re.search(r"(?:^|[^\w$])(?:return|throw|case|delete|void|typeof|yield|await|else|do)\s*$", prefix)
        if not expression_start and not keyword_start:
            return None
    cursor, in_character_class = start + 1, False
    while cursor < len(code):
        char = code[cursor]
        if char in "\r\n":
            return len(code)
        if char == "\\":
            cursor += 2
            continue
        if char == "[":
            in_character_class = True
        elif char == "]":
            in_character_class = False
        elif char == "/" and not in_character_class:
            cursor += 1
            while cursor < len(code) and code[cursor].isalpha():
                cursor += 1
            return cursor
        cursor += 1
    return len(code)


def _opening_elements(code):
    """Read enough JSX/HTML structure to scope exceptions conservatively."""
    elements, position = [], 0
    while position < len(code):
        if code.startswith("<!--", position):
            end = code.find("-->", position + 4)
            position = len(code) if end < 0 else end + 3
            continue
        if code.startswith("//", position):
            end = code.find("\n", position + 2)
            position = len(code) if end < 0 else end + 1
            continue
        if code.startswith("/*", position):
            end = code.find("*/", position + 2)
            position = len(code) if end < 0 else end + 2
            continue
        if code[position] == "/":
            end = _regex_literal_end(code, position)
            if end is not None:
                position = end
                continue
        if code[position] in "\"'`":
            end = string_end(code, position)
            position = len(code) if end < 0 else end + 1
            continue
        if code[position] != "<" or code.startswith("</", position):
            position += 1
            continue
        tag_match = re.match(r"<\s*([A-Za-z][A-Za-z0-9:._$-]*)\b", code[position:])
        if not tag_match:
            position += 1
            continue
        tag = tag_match.group(1).lower()
        start = position
        cursor = position + tag_match.end()
        brace_depth, quote, end = 0, None, -1
        while cursor < len(code):
            char = code[cursor]
            if quote:
                if char == "\\":
                    cursor += 2
                    continue
                if char == quote:
                    quote = None
            elif brace_depth:
                if char in "\"'`":
                    quote = char
                elif char == "{":
                    brace_depth += 1
                elif char == "}":
                    brace_depth -= 1
            elif char in "\"'`":
                quote = char
            elif char == "{":
                brace_depth = 1
            elif char == ">":
                end = cursor
                break
            cursor += 1
        if end < 0:
            position = position + tag_match.end()
            continue
        attrs = [
            attr for attr in ATTR.finditer(code, position + tag_match.end(), end)
            if attr.start() > position + tag_match.end() and code[attr.start() - 1].isspace()
            and _is_top_level_tag_position(code, position + tag_match.end(), attr.start())
        ]
        classes, known = set(), len(attrs) <= 1
        for attr in attrs:
            tokens, _, dynamic = _attribute_tokens(code, attr)
            classes.update(raw for raw, _ in tokens)
            known = known and not dynamic
        elements.append({"start": start, "end": end + 1, "tag": tag, "classes": classes, "classesKnown": known,
                         "attributeStarts": {attr.start() for attr in attrs}})
        position = end + 1
    return elements


def extract(code):
    found, attributes, dynamic = [], 0, 0
    elements = _opening_elements(code)
    attribute_starts = {start for element in elements for start in element["attributeStarts"]}
    position = 0
    while True:
        match = ATTR.search(code, position)
        if match is None:
            break
        if match.start() not in attribute_starts:
            position = match.end()
            continue
        attributes += 1
        tokens, end, is_dynamic = _attribute_tokens(code, match)
        if is_dynamic:
            dynamic += 1
        context = next((element for element in elements if match.start() in element["attributeStarts"]), None)
        for raw, token_position in tokens:
            found.append({"raw": raw, "line": code.count("\n", 0, token_position) + 1, "element": context})
        position = end
    tokens = code.strip().split()
    plain = {"block", "inline", "flex", "grid", "hidden", "relative", "absolute", "fixed", "sticky", "italic", "underline", "truncate", "uppercase", "lowercase"}
    if not found and tokens and all(re.fullmatch(r'''[^\s"'{}=<>;`]+''', token) and (re.search(r"[-:\[\]]", token) or token in plain) for token in tokens):
        found = [{"raw": match.group(), "line": code.count("\n", 0, match.start()) + 1, "element": None} for match in re.finditer(r"\S+", code)]
    return found, {"classAttributes": attributes, "dynamicAttributes": dynamic, "requiredScope": "file"}


def strip_variants(token):
    depth, colon = 0, -1
    for pos, char in enumerate(token):
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif char == ":" and depth == 0:
            colon = pos
    return token[colon + 1:].removeprefix("!").removesuffix("!")


def class_tokens(code: str) -> set:
    return {entry["raw"] for entry in extract(code)[0]}


def _unknown_keys(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {label}: expected an object")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ValueError(f"Unsupported {label} field(s): {', '.join(unknown)}")


def _validate_exception(exception, index):
    label = f"forbiddenExceptions[{index}]"
    _unknown_keys(exception, {"className", "reason", "variants", "element"}, label)
    class_name, reason = exception.get("className"), exception.get("reason")
    if not isinstance(class_name, str) or not class_name or strip_variants(class_name) != class_name:
        raise ValueError(f"Invalid {label}.className: expected one base utility")
    if not isinstance(reason, str) or not reason:
        raise ValueError(f"Invalid {label}.reason: expected a non-empty string")
    scoped = False
    if "variants" in exception:
        variants = exception["variants"]
        _unknown_keys(variants, {"all", "none"}, f"{label}.variants")
        if not variants:
            raise ValueError(f"Invalid {label}.variants: expected at least one condition")
        for condition, entries in variants.items():
            if not isinstance(entries, list) or any(not isinstance(item, str) or not item for item in entries):
                raise ValueError(f"Invalid {label}.variants.{condition}: expected strings")
            scoped = scoped or bool(entries)
    if "element" in exception:
        element = exception["element"]
        _unknown_keys(element, {"tags", "classesAll", "classPrefixesAll", "squareDimensions", "maxDimension"}, f"{label}.element")
        if not element:
            raise ValueError(f"Invalid {label}.element: expected at least one condition")
        for field in ("tags", "classesAll", "classPrefixesAll"):
            if field in element and (not isinstance(element[field], list) or any(not isinstance(item, str) or not item for item in element[field])):
                raise ValueError(f"Invalid {label}.element.{field}: expected strings")
        if "tags" in element and any(tag != tag.lower() for tag in element["tags"]):
            raise ValueError(f"Invalid {label}.element.tags: tags must be lowercase")
        if "squareDimensions" in element and element["squareDimensions"] is not True:
            raise ValueError(f"Unsupported {label}.element.squareDimensions value")
        scoped = scoped or any(element.get(field) for field in ("tags", "classesAll", "classPrefixesAll")) or element.get("squareDimensions") is True or "maxDimension" in element
        if "maxDimension" in element:
            maximum = element["maxDimension"]
            if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or not math.isfinite(maximum) or maximum < 0 or maximum > 1024:
                raise ValueError(f"Invalid {label}.element.maxDimension")
    if not scoped:
        raise ValueError(f"Invalid {label}: exception must have a non-empty state or element scope")


def _validate_lint_contract(contract):
    if not isinstance(contract, dict):
        raise ValueError("Invalid lint rule contract: expected an object")
    v1_fields = {"schemaVersion", "sources", "forbiddenClasses", "forbiddenPatterns", "required", "exempt", "unsupportedRules"}
    version = contract.get("schemaVersion")
    if version == "stylekit-lint-v1":
        allowed = v1_fields
    elif version == "stylekit-lint-v2":
        allowed = v1_fields | {"forbiddenExceptions"}
    else:
        raise ValueError("Unsupported lint rule contract")
    if version == "stylekit-lint-v1" and "forbiddenExceptions" in contract:
        raise ValueError("forbiddenExceptions requires stylekit-lint-v2")
    _unknown_keys(contract, allowed, "lint rule contract")
    required_fields = v1_fields - {"schemaVersion", "unsupportedRules"}
    if not required_fields.issubset(contract):
        missing = sorted(required_fields - set(contract))
        raise ValueError(f"Incomplete lint rule contract: missing {', '.join(missing)}")
    if version == "stylekit-lint-v2":
        exceptions = contract.get("forbiddenExceptions")
        if not isinstance(exceptions, list):
            raise ValueError("Invalid forbiddenExceptions: expected an array")
        for index, exception in enumerate(exceptions):
            _validate_exception(exception, index)
    for field in ("sources", "forbiddenClasses", "forbiddenPatterns", "exempt"):
        if not isinstance(contract[field], list):
            raise ValueError(f"Invalid lint rule contract field '{field}': expected an array")
    if "unsupportedRules" in contract and not isinstance(contract["unsupportedRules"], list):
        raise ValueError("Invalid lint rule contract field 'unsupportedRules': expected an array")
    if any(not isinstance(source, str) for source in contract["sources"]):
        raise ValueError("Invalid lint rule sources")
    for index, entry in enumerate(contract["forbiddenClasses"]):
        _unknown_keys(entry, {"className", "reason", "source"}, f"forbiddenClasses[{index}]")
        if any(not isinstance(entry.get(field), str) or not entry[field] for field in ("className", "reason", "source")):
            raise ValueError(f"Invalid forbiddenClasses[{index}]")
    for index, entry in enumerate(contract["forbiddenPatterns"]):
        _unknown_keys(entry, {"pattern", "flags", "source", "reasons"}, f"forbiddenPatterns[{index}]")
        if not isinstance(entry.get("pattern"), str) or not isinstance(entry.get("source"), str):
            raise ValueError(f"Invalid forbiddenPatterns[{index}]")
        if "flags" in entry and not isinstance(entry["flags"], str):
            raise ValueError(f"Invalid forbiddenPatterns[{index}].flags")
        if "reasons" in entry and (not isinstance(entry["reasons"], dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in entry["reasons"].items())):
            raise ValueError(f"Invalid forbiddenPatterns[{index}].reasons")
    if any(not isinstance(item, str) for item in contract["exempt"] + contract.get("unsupportedRules", [])):
        raise ValueError("Invalid lint rule exempt or unsupportedRules entries")
    if not isinstance(contract["required"], dict):
        raise ValueError("Invalid lint rule required field")
    for component, requirement in contract["required"].items():
        _unknown_keys(requirement, {"classes", "source"}, f"required.{component}")
        if not isinstance(requirement.get("classes"), list) or any(not isinstance(item, str) for item in requirement["classes"]):
            raise ValueError(f"Invalid required.{component}.classes")
        if not isinstance(requirement.get("source"), str):
            raise ValueError(f"Invalid required.{component}.source")


def _token_forbidden_exceptions(spec):
    tokens = spec.get("tokens")
    if tokens is None:
        return []
    if not isinstance(tokens, dict):
        raise ValueError("Invalid tokens payload")
    if "forbidden" not in tokens:
        return []
    forbidden = tokens["forbidden"]
    if not isinstance(forbidden, dict):
        raise ValueError("Invalid token forbidden payload")
    exceptions = forbidden.get("exceptions", [])
    if not isinstance(exceptions, list):
        raise ValueError("Invalid token forbidden exceptions: expected an array")
    return exceptions


def normalized_rules(spec):
    canonical = spec.get("lintRules")
    token_exceptions = _token_forbidden_exceptions(spec)
    if canonical is not None:
        _validate_lint_contract(canonical)
        rules = dict(canonical)
        rules.setdefault("forbiddenExceptions", [])
        if token_exceptions and canonical["schemaVersion"] == "stylekit-lint-v1":
            raise ValueError("Token forbidden exceptions require stylekit-lint-v2")
        if any(exception not in rules["forbiddenExceptions"] for exception in token_exceptions):
            raise ValueError("Lint contract omits token forbidden exceptions")
        return rules, []
    tokens = spec.get("tokens") or {}
    if not isinstance(tokens, dict):
        raise ValueError("Invalid tokens payload")
    forbidden = tokens.get("forbidden") or {}
    if not isinstance(forbidden, dict):
        raise ValueError("Invalid token forbidden payload")
    for index, exception in enumerate(token_exceptions):
        _validate_exception(exception, index)
    required = {component: {"classes": " ".join(entries).split(), "source": "tokens"}
                for component, entries in (tokens.get("required") or {}).items()}
    return {
        "sources": ["tokens"] if tokens else [],
        "forbiddenClasses": [{"className": cls, "reason": (forbidden.get("reasons") or {}).get(cls, f'"{cls}" is forbidden in this style'), "source": "tokens"} for cls in forbidden.get("classes", [])],
        "forbiddenPatterns": [{"pattern": pattern, "flags": "", "source": "tokens", "reasons": forbidden.get("reasons") or {}} for pattern in forbidden.get("patterns", [])],
        "required": required,
        "exempt": list({strip_variants(cls) for requirement in required.values() for cls in requirement["classes"]}),
        "forbiddenExceptions": token_exceptions,
        "unsupportedRules": [],
    }, ["Legacy spec: only token rules are available; curated overrides require an implementation brief."]


def _variant_stack(token):
    value = token.removeprefix("!").removesuffix("!")
    depth, separators = 0, []
    for position, char in enumerate(value):
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif char == ":" and depth == 0:
            separators.append(position)
    if not separators:
        return [], value.removeprefix("!").removesuffix("!")
    parts = []
    start = 0
    for separator in separators:
        parts.append(value[start:separator])
        start = separator + 1
    return parts, value[start:].removeprefix("!").removesuffix("!")


def _dimension_value(value):
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)
    arbitrary = re.fullmatch(r"\[(\d+(?:\.\d+)?)(px|rem)\]", value)
    if arbitrary:
        amount = float(arbitrary.group(1))
        return amount / 4 if arbitrary.group(2) == "px" else amount * 4
    return None


def _axis_dimension(classes, axis):
    candidates = []
    for token in classes:
        base = token
        if base.startswith("size-"):
            candidates.append(base[5:])
        elif base.startswith(axis + "-"):
            candidates.append(base[len(axis) + 1:])
    if not candidates:
        return "ok", None
    values = [_dimension_value(candidate) for candidate in candidates]
    if any(value is None for value in values) or len(set(values)) != 1:
        return "conflict", None
    return "ok", values[0]


def _square_scope(context, maximum):
    if context is None or not context["classesKnown"]:
        return None
    raw_classes = context["classes"]
    for token in raw_classes:
        variants, base = _variant_stack(token)
        if variants and re.match(r"^(?:w|h|size|aspect)-", base):
            return None
    classes = [strip_variants(token) for token in raw_classes]
    width_status, explicit_width = _axis_dimension(classes, "w")
    height_status, explicit_height = _axis_dimension(classes, "h")
    size_status, size = _axis_dimension(classes, "size")
    if "conflict" in {width_status, height_status, size_status}:
        return None
    if ((explicit_width is not None and size is not None and explicit_width != size) or
            (explicit_height is not None and size is not None and explicit_height != size)):
        return None
    width = explicit_width if explicit_width is not None else size
    height = explicit_height if explicit_height is not None else size
    aspect_square = "aspect-square" in classes
    if width is not None and height is not None:
        if width != height:
            return False
        dimension = width
    elif aspect_square:
        dimension = width if width is not None else height
        if maximum is None:
            return True
        if dimension is None:
            return None
    else:
        return None
    return maximum is None or dimension <= maximum


def _exception_scope(exception, entry):
    conditions = []
    variants, _ = _variant_stack(entry["raw"])
    variant_condition = exception.get("variants")
    if variant_condition:
        conditions.extend(item in variants for item in variant_condition.get("all", []))
        conditions.extend(item not in variants for item in variant_condition.get("none", []))
    element_condition = exception.get("element")
    if element_condition:
        context = entry.get("element")
        if context is None or not context["classesKnown"]:
            conditions.append(None)
        else:
            tags = element_condition.get("tags", [])
            if tags:
                conditions.append(context["tag"] in tags)
            # Exception predicates describe this exact element. A responsive or
            # state utility cannot prove that the unmodified element has a class.
            element_classes = set(context["classes"])
            for required in element_condition.get("classesAll", []):
                conditions.append(True if required in element_classes else False if context["classesKnown"] else None)
            for prefix in element_condition.get("classPrefixesAll", []):
                matches = any(token.startswith(prefix) for token in element_classes)
                conditions.append(True if matches else False if context["classesKnown"] else None)
            if element_condition.get("squareDimensions") or "maxDimension" in element_condition:
                conditions.append(_square_scope(context, element_condition.get("maxDimension")))
    if any(condition is False for condition in conditions):
        return False
    if any(condition is None for condition in conditions):
        return None
    return True


def lint_code(spec: dict, code: str, component: str | None = None, strict: bool = False) -> dict:
    rules, warnings = normalized_rules(spec)
    extracted, coverage = extract(code)
    exact = {entry["className"]: entry for entry in rules["forbiddenClasses"]}
    exempt = set(rules["exempt"])
    patterns, unsupported = [], list(rules.get("unsupportedRules") or [])
    for entry in rules["forbiddenPatterns"]:
        try:
            flags = entry.get("flags", "")
            if any(flag not in "imsu" for flag in flags):
                raise ValueError("Unsupported regular expression flags")
            mask = (re.I if "i" in flags else 0) | (re.M if "m" in flags else 0) | (re.S if "s" in flags else 0)
            patterns.append((re.compile(entry["pattern"], mask), entry))
        except (ValueError, re.error):
            unsupported.append(entry["pattern"])
    violations, scope_uncertainties = [], []
    exceptions = rules.get("forbiddenExceptions") or []
    for entry in extracted:
        raw, base = entry["raw"], strip_variants(entry["raw"])
        if base in exempt:
            continue
        rule = exact.get(base)
        kind = "forbidden-class"
        if rule is None:
            match = next(((pattern, rule) for pattern, rule in patterns if pattern.search(base)), None)
            if match:
                pattern, rule = match
                kind = "forbidden-pattern"
                rule = {**rule, "reason": rule.get("reasons", {}).get(base, f'"{base}" matches a forbidden pattern for this style ({rule["pattern"]})')}
        if rule:
            candidates = [exception for exception in exceptions if exception["className"] == base]
            exception_results = [_exception_scope(exception, entry) for exception in candidates]
            if True in exception_results:
                continue
            if None in exception_results:
                scope_uncertainties.append({
                    "className": raw,
                    "baseClassName": base,
                    "line": entry["line"],
                    "reasons": [exception["reason"] for exception, result in zip(candidates, exception_results) if result is None],
                })
                continue
            violations.append({"className": raw, "baseClassName": base, "line": entry["line"], "severity": "error", "source": rule["source"], "rule": kind, "reason": rule["reason"]})
    present = {entry["raw"] for entry in extracted}
    present_base = {strip_variants(raw) for raw in present if raw.removeprefix("!").removesuffix("!") == strip_variants(raw)}
    missing = []
    if component:
        requirement = rules["required"].get(component) or {}
        classes = [cls for cls in requirement.get("classes", []) if cls not in present and not (cls == strip_variants(cls) and cls in present_base)]
        if classes:
            missing.append({"component": component, "missing": classes, "source": requirement["source"]})
    if not rules["sources"]:
        warnings.append("No lint rules are available for this style.")
    if not extracted:
        warnings.append("No statically readable class tokens were found.")
    if coverage["dynamicAttributes"]:
        warnings.append("Runtime class expressions require manual review; only their string literals were checked.")
    if unsupported:
        warnings.append("Some forbidden patterns could not be compiled.")
    if scope_uncertainties:
        warnings.append("A scoped forbidden-class exception could not be verified because element or state context is incomplete.")
    if missing and not strict:
        warnings.append("Missing required classes are advisory; enable strict to fail them.")
    failed = bool(violations or (strict and missing and not coverage["dynamicAttributes"]))
    uncertain = not rules["sources"] or not extracted or coverage["dynamicAttributes"] or unsupported or scope_uncertainties
    status = "fail" if failed else "inconclusive" if uncertain else "pass"
    return {"slug": spec.get("slug", ""), "ok": status == "pass", "status": status, "violations": violations,
            "missingRequired": missing, "scopeUncertainties": scope_uncertainties, "checkedClasses": len(extracted), "ruleSources": rules["sources"],
            "specSource": spec.get("_stylekitSource"), "coverage": coverage, "warnings": warnings}


def eval_code(spec: dict, code: str, component: str | None = None) -> list:
    """Compatibility adapter for the benchmark; uncertainty never counts as a pass."""
    report = lint_code(spec, code, component, strict=component is not None)
    issues = [f'{report["slug"]}: {entry["className"]}: {entry["reason"]}' for entry in report["violations"]]
    issues.extend(f'{report["slug"]}: missing {entry["component"]}: {" ".join(entry["missing"])}' for entry in report["missingRequired"])
    if report["status"] == "inconclusive":
        issues.append("inconclusive: " + " ".join(report["warnings"]))
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("file", nargs="?", type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--stdin", action="store_true")
    source.add_argument("--dir", type=Path)
    spec_inputs = parser.add_mutually_exclusive_group()
    spec_inputs.add_argument("--spec", type=Path, help="Use a saved complete CLI/API brief or legacy spec")
    spec_inputs.add_argument("--from-file", type=Path, help="Use a saved MCP tool result JSON envelope")
    parser.add_argument("--base-url", default=BASE, help="StyleKit API base used when no spec file is supplied")
    parser.add_argument("--component", choices=("button", "card", "input"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.file and (args.stdin or args.dir):
        parser.error("use one source: file, --stdin, or --dir")
    if not (args.file or args.stdin or args.dir):
        parser.error("provide a file, --stdin, or --dir")
    if args.strict and not args.component:
        parser.error("--strict requires --component")
    try:
        if args.spec:
            spec = load_spec_file(args.spec, args.slug)
        elif args.from_file:
            spec = load_spec_file(args.from_file, args.slug, from_mcp=True)
        else:
            spec = fetcher.fetch_spec(args.slug, args.base_url)
        if spec.get("slug") != args.slug:
            raise ValueError("Spec slug does not match the requested style")
        if args.stdin:
            sources = {"<stdin>": sys.stdin.read()}
        elif args.dir:
            if not args.dir.is_dir():
                raise ValueError(f"Not a directory: {args.dir}")
            sources = {str(p): p.read_text(encoding="utf-8") for p in detector.source_files(args.dir) if p.suffix in (".tsx", ".ts", ".jsx", ".js", ".html", ".vue", ".svelte")}
        else:
            sources = {str(args.file): args.file.read_text(encoding="utf-8")}
        if not sources:
            raise ValueError("No source files found")
        reports = [{"file": name, "report": lint_code(spec, code, args.component, args.strict)} for name, code in sources.items()]
        statuses = {entry["report"]["status"] for entry in reports}
        status = "fail" if "fail" in statuses else "inconclusive" if "inconclusive" in statuses else "pass"
        if args.json:
            print(json.dumps({"slug": args.slug, "status": status, "ok": status == "pass", "files": reports}, ensure_ascii=False, indent=2))
        else:
            for entry in reports:
                report = entry["report"]
                print(f'{entry["file"]}: {report["status"]} ({report["checkedClasses"]} classes)')
                for violation in report["violations"]:
                    print(f'  line {violation["line"]}: {violation["className"]}: {violation["reason"]}')
                for missing in report["missingRequired"]:
                    print(f'  missing {missing["component"]}: {" ".join(missing["missing"])}')
                for warning in report["warnings"]:
                    print(f"  {warning}")
        sys.exit({"pass": 0, "fail": 1, "inconclusive": 3}[status])
    except (OSError, ValueError, TypeError, KeyError) as err:
        print(json.dumps({"error": str(err)}) if args.json else f"Error: {err}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
