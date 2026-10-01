"""Explicit source-bound Java URLConnection profile; qualification is separate."""
from __future__ import annotations

import json
from pathlib import Path

from tools.rust_capsule_project import canonical, digest, inventory, snapshot

PROFILE_ID = "lsf.java.httpurlconnection.streaming.v1"
RECIPE = ("tools/java_http_client.py",)


def selection(value: object) -> dict:
    if not isinstance(value, dict) or value != {"profile": PROFILE_ID}:
        raise ValueError("unknown Java standard HTTP profile")
    return {"profile": PROFILE_ID}


def profile(sdk: Path, recipe_inputs: bytes, source_inputs: bytes, component: bytes) -> bytes:
    inputs = inventory(snapshot(sdk / "client"))
    return canonical({"schemaVersion": "latent.java.http.profile.v1", "profile": PROFILE_ID,
        "compiler": "teavm-c-0.15.0", "runtimeAdapterDigest": digest(inputs),
        "recipeDigest": digest(recipe_inputs), "sourceDigest": digest(source_inputs),
        "componentDigest": digest(component), "inputs": json.loads(inputs),
        "boundary": "standard-url-default-handler-to-latent-http-streaming-0.3.0",
        "qualification": "pending", "schemes": ["http"],
        "limits": {"requestBodyBytes": 262144, "responseBodyBytes": 262144, "chunkBytes": 4096},
        "unsupported": ["https-standard-type", "separate-phase-timeouts", "automatic-redirects",
            "explicit-chunk-framing", "status-line-and-reason-phrase", "indexed-response-headers"]})
