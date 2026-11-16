#!/usr/bin/env python3
"""Exercise the catalogue checker's rejection paths with isolated in-memory mutations."""
import copy
import json
import validate_catalogue as v

folder = v.SKILL / "references"
catalogue = json.loads((folder / "modules.json").read_text())
schema = json.loads((folder / "modules.schema.json").read_text())
assert not v.check(catalogue, schema, folder)


def rejects(change, expected):
    fixture = copy.deepcopy(catalogue)
    change(fixture)
    errors = v.check(fixture, schema, folder)
    assert any(expected in error for error in errors), errors


rejects(lambda c: c["modules"][0].pop("prerequisites"), "missing prerequisites")
rejects(lambda c: c["modules"][0].update(id="Unstable Label"), "invalid identifier")
rejects(lambda c: c["modules"][1].update(id=c["modules"][0]["id"]), "duplicate ID")
rejects(lambda c: c["modules"][1].update(aliases=[c["modules"][0]["name"]]), "ambiguous label")
rejects(lambda c: c["modules"][0].update(reference="missing.md"), "missing or out-of-scope")
rejects(lambda c: c["modules"][0].update(reference="../SKILL.md#missing-anchor"), "missing heading anchor")
rejects(lambda c: c["modules"][0].update(reference="../../../../LICENSE"), "out-of-scope")
rejects(lambda c: c["modules"][0].update(settings="not an array"), "expected array")
rejects(lambda c: c["modules"][0].update(validation={"status": "planned", "scenarios": []}), "too few items")
rejects(lambda c: c.update(schema_version=True), "incorrect constant")
rejects(lambda c: c["modules"][0]["validation"].update(evidence=[{"kind":"test"}]), "missing source")
print("Catalogue checker: valid catalogue and 11 malformed/ambiguous/reference fixtures passed")
