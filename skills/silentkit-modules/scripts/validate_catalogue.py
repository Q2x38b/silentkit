#!/usr/bin/env python3
"""Offline catalogue/schema-subset and local-reference validation; no third-party dependencies.
Supports every assertion keyword used by modules.schema.json. Not a general JSON Schema implementation.
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote

SKILL = Path(__file__).resolve().parents[1]
TYPES = {"object": dict, "array": list, "string": str}


def validate(value, spec, schema, path="$", errors=None):
    errors = [] if errors is None else errors
    if "$ref" in spec:
        target = schema
        for part in spec["$ref"].removeprefix("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return validate(value, target, schema, path, errors)
    if "type" in spec and not isinstance(value, TYPES[spec["type"]]):
        errors.append(f"{path}: expected {spec['type']}")
        return errors
    if "const" in spec and (type(value) is not type(spec["const"]) or value != spec["const"]):
        errors.append(f"{path}: incorrect constant")
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"{path}: unknown value {value!r}")
    if isinstance(value, str):
        if len(value.strip()) < spec.get("minLength", 0):
            errors.append(f"{path}: empty string")
        if "pattern" in spec and not re.search(spec["pattern"], value):
            errors.append(f"{path}: invalid identifier")
    if isinstance(value, list):
        if len(value) < spec.get("minItems", 0):
            errors.append(f"{path}: too few items")
        if spec.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errors.append(f"{path}: duplicate items")
        if "items" in spec:
            for i, v in enumerate(value):
                validate(v, spec["items"], schema, f"{path}[{i}]", errors)
    if isinstance(value, dict):
        for key in spec.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        properties = spec.get("properties", {})
        for key, v in value.items():
            if key in properties:
                validate(v, properties[key], schema, f"{path}.{key}", errors)
            elif spec.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected {key}")
    return errors


def slug(text):
    return re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")


def reference_errors(ref, folder):
    path, _, anchor = ref.partition("#")
    target = (folder / unquote(path)).resolve()
    if not target.is_relative_to(SKILL.parent) or not target.is_file():
        return [f"missing or out-of-scope reference: {ref}"]
    if anchor:
        headings = re.findall(r"^#{1,6}\s+(.+)$", target.read_text(), re.M)
        if unquote(anchor) not in {slug(h) for h in headings}:
            return [f"missing heading anchor: {ref}"]
    return []


def check(catalogue, schema, folder):
    errors = validate(catalogue, schema, schema)
    if errors:
        return errors
    ids, labels = {}, {}
    for module in catalogue["modules"]:
        key = module["id"]
        if key in ids:
            errors.append(f"duplicate ID: {key}")
        ids[key] = module
        for label in [module["name"], *module.get("aliases", [])]:
            normalized = re.sub(r"[^a-z0-9]", "", label.lower())
            # Labels are resolved with a category; an alias cannot select two entries in that category.
            scope = (module["category"], normalized)
            if scope in labels and labels[scope] != key:
                errors.append(f"ambiguous label {label!r} in {module['category']}: {labels[scope]}, {key}")
            labels[scope] = key
        for field in ("reference", "bypass_reference"):
            if field in module:
                errors.extend(f"{key}: {e}" for e in reference_errors(module[field], folder))
    errors.extend(reference_errors(catalogue["threat_model"]["reference"], folder))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", nargs="?", type=Path, default=SKILL / "references/modules.json")
    args = parser.parse_args()
    schema = json.loads((SKILL / "references/modules.schema.json").read_text())
    try:
        catalogue = json.loads(args.catalogue.read_text())
        errors = check(catalogue, schema, args.catalogue.parent)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Invalid catalogue: {exc}\n")
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    print(f"Catalogue valid: {len(catalogue['modules'])} entries; schema, IDs, aliases and local anchors checked")


if __name__ == "__main__":
    main()
