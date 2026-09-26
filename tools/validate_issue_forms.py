#!/usr/bin/env python3
"""Validate the repository's small supported GitHub issue-form YAML subset offline."""

from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlparse

import yaml
from yaml.resolver import BaseResolver
from yaml.tokens import AliasToken, AnchorToken, DirectiveToken, TagToken

MAX_FILE_BYTES = 65_536
MAX_DEPTH = 12
MAX_NODES = 1_024
MAX_COLLECTION_ITEMS = 128
MAX_STRING_BYTES = 32_768
MAX_BODY_ELEMENTS = 64
MAX_LABELS = 32
MAX_CONTACT_LINKS = 16
MAX_URL_BYTES = 2_048

KNOWN_FORMS = (
    Path(".github/ISSUE_TEMPLATE/bug_report.yml"),
    Path(".github/ISSUE_TEMPLATE/architecture.yml"),
)
CONFIG_PATH = Path(".github/ISSUE_TEMPLATE/config.yml")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class ValidationError(Exception):
    """Bounded issue-form validation failure."""


class UniqueSafeLoader(yaml.SafeLoader):
    """Reject excessive composition before recursive construction begins."""

    def __init__(self, stream):
        self._compose_depth = 0
        self._compose_nodes = 0
        super().__init__(stream)

    def compose_node(self, parent, index):
        self._compose_nodes += 1
        if self._compose_nodes > MAX_NODES:
            raise ValidationError("yaml-node-limit")
        if self._compose_depth > MAX_DEPTH:
            raise ValidationError("yaml-depth-limit")
        self._compose_depth += 1
        try:
            return super().compose_node(parent, index)
        finally:
            self._compose_depth -= 1


def _construct_unique_mapping(
    loader: UniqueSafeLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ValidationError("non-scalar-mapping-key") from error
        if duplicate:
            raise ValidationError("duplicate-mapping-key")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueSafeLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _bounded_shape(value: object, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_NODES:
        raise ValidationError("yaml-node-limit")
    if depth > MAX_DEPTH:
        raise ValidationError("yaml-depth-limit")
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise ValidationError("yaml-string-limit")
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise ValidationError("yaml-collection-limit")
        for item in value:
            _bounded_shape(item, depth + 1, counter)
        return
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise ValidationError("yaml-collection-limit")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError("non-string-mapping-key")
            _bounded_shape(key, depth + 1, counter)
            _bounded_shape(item, depth + 1, counter)
        return
    raise ValidationError("unsupported-yaml-scalar")


def read_yaml(path: Path) -> object:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValidationError("file-unavailable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ValidationError("unsafe-file-type")
    if metadata.st_size > MAX_FILE_BYTES:
        raise ValidationError("file-size-limit")
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ValidationError("unsafe-file-type")
            if opened.st_size > MAX_FILE_BYTES:
                raise ValidationError("file-size-limit")
            # Bound the read itself, including growth since either stat call.
            encoded = source.read(MAX_FILE_BYTES + 1)
    except OSError as error:
        reason = "unsafe-file-type" if error.errno == errno.ELOOP else "file-unavailable"
        raise ValidationError(reason) from error
    if len(encoded) > MAX_FILE_BYTES:
        raise ValidationError("file-size-limit")
    try:
        text = encoded.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ValidationError("invalid-utf8") from error
    try:
        tokens = yaml.scan(text, Loader=UniqueSafeLoader)
        for token in tokens:
            if isinstance(token, (AliasToken, AnchorToken, DirectiveToken, TagToken)):
                raise ValidationError("unsupported-yaml-feature")
        loader = UniqueSafeLoader(text)
        try:
            if not loader.check_data():
                raise ValidationError("yaml-document-count")
            value = loader.get_data()
            if loader.check_data():
                raise ValidationError("yaml-document-count")
        finally:
            loader.dispose()
        _bounded_shape(value)
        return value
    except ValidationError:
        raise
    except UnicodeError as error:
        raise ValidationError("invalid-unicode-scalar") from error
    except (yaml.YAMLError, ValueError) as error:
        raise ValidationError("malformed-yaml") from error


def _mapping(value: object, reason: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError(reason)
    return value


def _keys(
    value: dict[str, object], *, allowed: set[str], required: set[str], reason: str
) -> None:
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(allowed):
        raise ValidationError(reason)


def _nonempty(value: object, reason: str, maximum: int = MAX_STRING_BYTES) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise ValidationError(reason)
    return value


def _optional_string(mapping: dict[str, object], key: str, reason: str) -> None:
    if key in mapping:
        value = mapping[key]
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise ValidationError(reason)


def _validations(value: object) -> None:
    mapping = _mapping(value, "invalid-validations")
    _keys(mapping, allowed={"required"}, required=set(), reason="invalid-validations")
    if "required" in mapping and not isinstance(mapping["required"], bool):
        raise ValidationError("invalid-required-boolean")


def _attributes(kind: str, value: object) -> str | None:
    mapping = _mapping(value, "invalid-attributes")
    if kind == "markdown":
        _keys(mapping, allowed={"value"}, required={"value"}, reason="invalid-markdown-attributes")
        _nonempty(mapping["value"], "invalid-markdown-value")
        return None
    if kind == "input":
        allowed = {"label", "description", "placeholder", "value"}
    elif kind == "textarea":
        allowed = {"label", "description", "placeholder", "value", "render"}
    else:
        raise ValidationError("unsupported-element-type")
    _keys(mapping, allowed=allowed, required={"label"}, reason="invalid-field-attributes")
    label = _nonempty(mapping["label"], "invalid-field-label")
    for key in allowed - {"label"}:
        _optional_string(mapping, key, f"invalid-{key}")
    return label


def validate_issue_form(value: object) -> None:
    form = _mapping(value, "invalid-form-object")
    _keys(
        form,
        allowed={"name", "description", "title", "labels", "body"},
        required={"name", "description", "body"},
        reason="invalid-form-keys",
    )
    _nonempty(form["name"], "invalid-form-name")
    _nonempty(form["description"], "invalid-form-description")
    if "title" in form and not isinstance(form["title"], str):
        raise ValidationError("invalid-form-title")
    if "labels" in form:
        labels = form["labels"]
        if isinstance(labels, str):
            labels = _nonempty(labels, "invalid-form-labels").split(",")
        if not isinstance(labels, list) or len(labels) > MAX_LABELS:
            raise ValidationError("invalid-form-labels")
        for label in labels:
            _nonempty(label, "invalid-form-label")

    body = form["body"]
    if not isinstance(body, list) or not body or len(body) > MAX_BODY_ELEMENTS:
        raise ValidationError("invalid-form-body")
    ids: set[str] = set()
    labels: set[str] = set()
    has_input = False
    for element in body:
        item = _mapping(element, "invalid-form-element")
        if "type" not in item or not isinstance(item["type"], str):
            raise ValidationError("invalid-element-type")
        kind = item["type"]
        if kind not in {"markdown", "input", "textarea"}:
            raise ValidationError("unsupported-element-type")
        allowed = {"type", "attributes"} if kind == "markdown" else {
            "type", "id", "attributes", "validations"
        }
        _keys(item, allowed=allowed, required={"type", "attributes"}, reason="invalid-element-keys")
        label = _attributes(kind, item["attributes"])
        if kind == "markdown":
            continue
        has_input = True
        if label in labels:
            raise ValidationError("duplicate-field-label")
        assert label is not None
        labels.add(label)
        if "id" in item:
            identity = item["id"]
            if not isinstance(identity, str) or ID_PATTERN.fullmatch(identity) is None:
                raise ValidationError("invalid-field-id")
            if identity in ids:
                raise ValidationError("duplicate-field-id")
            ids.add(identity)
        if "validations" in item:
            _validations(item["validations"])
    if not has_input:
        raise ValidationError("form-requires-input")


def validate_config(value: object) -> None:
    config = _mapping(value, "invalid-config-object")
    _keys(
        config,
        allowed={"blank_issues_enabled", "contact_links"},
        required=set(),
        reason="invalid-config-keys",
    )
    if "blank_issues_enabled" in config and not isinstance(config["blank_issues_enabled"], bool):
        raise ValidationError("invalid-blank-issues-boolean")
    if "contact_links" not in config:
        return
    links = config["contact_links"]
    if not isinstance(links, list) or len(links) > MAX_CONTACT_LINKS:
        raise ValidationError("invalid-contact-links")
    for link in links:
        item = _mapping(link, "invalid-contact-link")
        _keys(
            item,
            allowed={"name", "url", "about"},
            required={"name", "url", "about"},
            reason="invalid-contact-link",
        )
        _nonempty(item["name"], "invalid-contact-name")
        _nonempty(item["about"], "invalid-contact-about")
        url = _nonempty(item["url"], "invalid-contact-url", MAX_URL_BYTES)
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url) or "\\" in url:
            raise ValidationError("invalid-contact-url")
        try:
            parsed = urlparse(url)
            # Accessing port also rejects malformed and out-of-range ports.
            port = parsed.port
            hostname = parsed.hostname
        except ValueError as error:
            raise ValidationError("invalid-contact-url") from error
        if (parsed.scheme != "https" or not hostname or parsed.netloc.endswith(":")
                or parsed.username is not None or parsed.password is not None
                or port == 0):
            raise ValidationError("invalid-contact-url")


def validate_repository(root: Path) -> int:
    checked = 0
    for relative in (*KNOWN_FORMS, CONFIG_PATH):
        path = root
        # Missing known files are allowed (including deletion and an absent
        # chooser), but existing paths must not cross a symlink or special file.
        for index, part in enumerate(relative.parts):
            path /= part
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                break
            except OSError as error:
                raise ValidationError("file-unavailable") from error
            directory = index < len(relative.parts) - 1
            if not (stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)):
                raise ValidationError("unsafe-file-type")
        else:
            validate = validate_config if relative == CONFIG_PATH else validate_issue_form
            validate(read_yaml(path))
            checked += 1
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        checked = validate_repository(args.repo)
        print(f"Validated {checked} known GitHub issue-form/config file(s)")
        return 0
    except ValidationError as error:
        print(f"Issue-form validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
