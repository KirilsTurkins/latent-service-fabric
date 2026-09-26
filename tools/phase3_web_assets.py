"""Bounded immutable asset checks, independent of browser hydration or render HTML."""
from __future__ import annotations

import hashlib
import re

from tools.phase2_operator_process import require
from tools.phase3_web_scenario import MIB, http_response


def locator(publication, path):
    require(re.fullmatch(r"publication:sha256:[0-9a-f]{64}", publication) is not None,
            "angular-asset-publication")
    require(isinstance(path, str) and path.startswith("/") and len(path) <= 240,
            "angular-asset-path")
    return "/_lsf/assets/" + publication + path


def immutable_assets(client, node, record, publication):
    assets = record["assets"]
    require(1 <= len(assets) <= 8, "angular-asset-count")
    for asset in assets:
        require(0 < asset["size"] <= MIB, "angular-asset-size")
        path = locator(publication, asset["path"])
        body, headers = http_response(client, node, "alice.angular.test", path)
        require(len(body) == asset["size"]
                and "sha256:" + hashlib.sha256(body).hexdigest() == asset["digest"],
                "angular-asset-content-identity")
        require(headers.get("content-type") == asset["mediaType"]
                and headers.get("content-length") == str(asset["size"])
                and headers.get("cache-control") == "private, max-age=31536000, immutable"
                and headers.get("x-content-type-options") == "nosniff",
                "angular-asset-representation")
        tag = headers.get("etag", "")
        require(re.fullmatch(r'"identity-sha256-[0-9a-f]{64}"', tag) is not None,
                "angular-asset-validator")
        head, fields = http_response(client, node, "alice.angular.test", path, method="HEAD")
        require(not head and fields.get("content-length") == str(asset["size"])
                and fields.get("etag") == tag, "angular-asset-head")
        body, fields = http_response(client, node, "alice.angular.test", path,
                                     headers={"If-None-Match": tag}, expected=304)
        require(not body and fields.get("etag") == tag, "angular-asset-not-modified")
    denied, headers = http_response(client, node, "foreign.angular.test",
                                    locator(publication, assets[0]["path"]), expected=(403, 404))
    require(not denied and "etag" not in headers, "angular-asset-foreign-publication")
    for private in ("/server/renderer.wasm", "/metadata/source-inputs.json", "/package/sbom.cdx.json"):
        body, headers = http_response(client, node, "alice.angular.test",
                                      locator(publication, private), expected=404)
        require(not body and "etag" not in headers, "angular-private-layer-exposed")
    return {"publication": publication, "verifiedAssets": len(assets),
            "headAndConditional": True, "foreignTenantDenied": True, "privateLayersDenied": 3}


def revoked_assets(client, node, record, publication):
    path = locator(publication, record["assets"][0]["path"])
    for method in ("GET", "HEAD"):
        body, headers = http_response(client, node, "alice.angular.test", path, method=method,
                                      headers={"If-None-Match": "*"}, expected=403)
        require(not body and "etag" not in headers, "angular-revoked-asset-authority")
    return {"publication": publication, "revokedGetAndHeadDenied": True}
