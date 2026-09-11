"""Size-qualified roots and handoff from the actual collector process."""
import re
import secrets

from tools.optimization_evidence.common import canonical, fields, require, sha256, uint
from ..catalog import data as shared
from . import model

MARKER_SCHEMA = "latent.optimization.catalog-mutation-data-owner.v1"
REOPEN_SCHEMA = "latent.optimization.catalog-mutation-reopen.v1"
CATALOG_PATH = shared.CATALOG_PATH
MAX_TREE_BYTES = shared.MAX_TREE_BYTES
MAX_TREE_FILES = shared.MAX_TREE_FILES
MAX_TREE_DIRECTORIES = shared.MAX_TREE_DIRECTORIES
reserve = shared.reserve
close_tree = shared.close_tree
remove_owned = shared.remove_owned
create = shared.create
identity = shared.identity


def marker(selected, commit, *, nonce=None):
    value = {"schema": MARKER_SCHEMA, "nonce": secrets.token_hex(16) if nonce is None else nonce,
             "group": model.group_id(selected), "variant": selected["variant"], "shape": selected["shape"],
             "repetition": selected["repetition"], "populated_size": selected["populated_size"],
             "source_commit": commit}
    validate_marker(value, selected, commit)
    return value


def validate_marker(value, selected, commit):
    fields(value, "schema nonce group variant shape repetition populated_size source_commit")
    require(value["schema"] == MARKER_SCHEMA and isinstance(value["nonce"], str)
            and re.fullmatch("[0-9a-f]{32}", value["nonce"]) is not None
            and isinstance(commit, str) and re.fullmatch("[0-9a-f]{40}", commit) is not None,
            "catalog-mutation-data-marker-format")
    require(type(value["repetition"]) is int and type(value["populated_size"]) is int
            and value == {**value, "group": model.group_id(selected), "variant": selected["variant"],
                          "shape": selected["shape"], "repetition": selected["repetition"],
                          "populated_size": selected["populated_size"], "source_commit": commit},
            "catalog-mutation-data-marker-selection")
    return value


def post_exit(root, value, initial_process, initial_raw):
    # The caller supplies the source PID/start tuple, not Heaptrack's wrapper PID.
    # The suite additionally binds that tuple to the reaped wrapper, ready/result
    # events, actual executable, observed source exit, and original raw header.
    require(type(initial_process["process_id"]) is int and initial_process["process_id"] > 0
            and uint(initial_process["start_time_ticks"]) > 0,
            "catalog-mutation-handoff-source-process")
    result = shared.post_exit(root, value, initial_process, initial_raw)
    result["schema"] = REOPEN_SCHEMA
    return result


def validate_identity(value, selected, commit):
    fields(value, "device inode marker_sha256 marker")
    uint(value["device"])
    require(uint(value["inode"]) > 0, "catalog-mutation-data-inode-missing")
    validate_marker(value["marker"], selected, commit)
    require(value["marker_sha256"] == sha256(canonical(value["marker"]) + b"\n"),
            "catalog-mutation-data-marker-byte-binding")
    return value
