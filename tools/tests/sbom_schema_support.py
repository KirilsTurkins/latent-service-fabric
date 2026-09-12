"""Offline upstream CycloneDX validation with exact pinned source integrity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "tools/data/cyclonedx-1.6"
REVISION = "55343ba19dee1785acf1ce9191540d5fd7b590db"
EXPECTED = {
    "bom-1.6.schema.json": "3e92dddbc30cf7f6a02b80f0942b1a4cfd4fb1c26f1dfc4310afa9d613cafb93",
    "spdx.schema.json": "baa9d3bd1ed57b6751b0887edead6b5063ff53ff7429cf85d476c6c94af0166e",
    "jsf-0.82.schema.json": "8bae002c25e723db7ee1f26afde680ae1a2b1a8f6b4b4b0fd65dc3becb090aae",
    "LICENSE": "6c29f22a4a7385285c6f579ec9f33c5e989f00739d6b257243a0b082ec9447ae",
}


def no_remote_resource(uri: str):
    """A schema reference outside the local closure must fail without network I/O."""
    raise NoSuchResource(ref=uri)


def upstream_validator():
    manifest = json.loads((UPSTREAM / "SOURCES.json").read_bytes())
    assert manifest["revision"] == REVISION
    assert manifest["repository"] == "https://github.com/CycloneDX/specification"
    assert set(manifest["files"]) == set(EXPECTED)
    schemas = {}
    registry = Registry(retrieve=no_remote_resource)
    for name, expected in EXPECTED.items():
        raw = (UPSTREAM / name).read_bytes()
        source_path = name if name == "LICENSE" else "schema/" + name
        record = manifest["files"][name]
        assert record == {
            "source": f"https://raw.githubusercontent.com/CycloneDX/specification/{REVISION}/{source_path}",
            "bytes": len(raw), "sha256": expected,
        }
        assert hashlib.sha256(raw).hexdigest() == expected
        if name.endswith(".schema.json"):
            schema = json.loads(raw)
            Draft7Validator.check_schema(schema)
            schemas[name] = schema
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft7Validator(schemas["bom-1.6.schema.json"], registry=registry)
