"""Uninstalled, distinct compiled node-bootstrap custody ABI.

Append to the complete frozen456 source map; preserve the ordinary profile.
This does not approve Node funding/retirement, IRQs, boot, useful fit or TCP.
The owning loader must capture all85 physical inputs before loading this file.
"""
import hashlib
import json
from pathlib import Path
import stat
from tools.host_stream_kernel_device_security import function

ROOT = Path(__file__).resolve().parents[4]
INPUT_SHA = "93c9663fd6ded622c4745b01b387f6506dd687bd86443ef97f71dfb6aeeef5a4"
FACTORY_PIN = (38360, "558f4740e3c17286c1b23beb08ae80781cd11a87cf90e630b0ac62370f682ec4")
MATERIAL_PATH = "research/standard-outbound/linux-6.12-lineage/node-bootstrap/factory-node-bootstrap.c"
MATERIAL_NAME = "net/factory-node-bootstrap.c"
MATERIAL_PIN = (12610, "815b3f0eec0d6b54d0c2c93860e9deaeb3958ae0982a5eac6ccb9ea22797093b")
COMPILED_ABI = "lsf-q35-node-bootstrap-v1"
PREFIX = b"#define LSF_STREAM_NODE_BOOTSTRAP_IMAGE 1\n"
ANCHOR = b"static struct miscdevice lsf_factory_device = {\n"
INCLUDE = b'#include "factory-node-bootstrap.c"\n'
OLD_FOPS = b"    .fops = &lsf_factory_operations,\n"
NEW_FOPS = (b"#ifdef LSF_STREAM_NODE_BOOTSTRAP_IMAGE\n"
    b"    .fops = &lsf_factory_node_operations,\n"
    b"#else\n" + OLD_FOPS + b"#endif\n")


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _bound(raw, pin):
    return (type(raw) is bytes and len(raw) == pin[0]
            and hashlib.sha256(raw).hexdigest() == pin[1])


def materials(root=ROOT):
    path = Path(root) / MATERIAL_PATH
    status = path.lstat()
    _require(stat.S_ISREG(status.st_mode) and not path.is_symlink()
             and status.st_size == MATERIAL_PIN[0], "node-material-kind-length")
    with path.open("rb") as stream:
        raw = stream.read(MATERIAL_PIN[0] + 1)
    _require(_bound(raw, MATERIAL_PIN), "node-material-identity")
    raw.decode("utf-8", "strict")
    _require(b"\r" not in raw, "node-material-line-endings")
    node_body_obligations(raw)
    return {MATERIAL_NAME: raw}


def node_body_obligations(raw):
    _require(type(raw) is bytes, "node-body-bytes")
    text = raw.decode("utf-8", "strict")
    opened = function(text, "static int lsf_node_open(")
    _require(opened.index("if (!lsf_factory_selected_consumer())")
             < opened.index("factory.pages = alloc_pages("), "node-closed-entry-order")
    _require(opened.count("error = -EIO;") == 2, "node-retained-failure-negative-errno")
    _require("lsf_factory_operations.open != lsf_factory_open" in opened
             and "lsf_factory_operations.release != lsf_factory_release" in opened,
             "node-ordinary-static-callback-reference")
    _require(opened.index("lsf_cleanup_observers_prebank_enter()")
             < opened.index("lsf_factory_device_uevent_bank_enter()")
             < opened.index("factory.pages = alloc_pages("), "node-native-prebank-fences")
    _require(opened.index("*record = (struct lsf_prepaid_view)")
             < opened.index("memset(node,") < opened.index("mmgrab(node->mm)")
             < opened.index("file->private_data = node"), "node-header-prepay-order")
    _require("sizeof(struct lsf_node_parent)" in opened
             and "lsf_factory_device_initialize(" not in opened,
             "node-own-typed-storage-not-device-adoption")
    released = function(text, "static int lsf_node_release(")
    _require("node->state = LSF_NODE_RETAINED" in released
             and all(name not in released for name in (
                 "__free_pages(", "mmput(", "put_pid(", "put_cred(", "put_net(",
                 "lsf_prepaid_return(", "lsf_prepaid_recycle(")), "node-no-refund-producer")


def _identity(values):
    return {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(values.items())}


def inverse_factory(raw):
    _require(type(raw) is bytes and raw.startswith(PREFIX), "node-profile-prefix")
    _require(raw.count(INCLUDE) == 1 and raw.count(NEW_FOPS) == 1, "node-profile-shape")
    return raw[len(PREFIX):].replace(INCLUDE, b"", 1).replace(NEW_FOPS, OLD_FOPS, 1)


def edit_factory(old):
    _require(type(old) is bytes and old.count(ANCHOR) == 1 and old.count(OLD_FOPS) == 1
             and PREFIX not in old and INCLUDE not in old, "node-profile-before")
    new = PREFIX + old.replace(ANCHOR, INCLUDE + ANCHOR, 1).replace(OLD_FOPS, NEW_FOPS, 1)
    _require(inverse_factory(new) == old, "node-ordinary-profile-inverse")
    return new


def transform(values, selected_materials=None):
    _require(type(values) is dict and len(values) == 456
             and all(type(name) is str and type(raw) is bytes
                     for name, raw in values.items()), "node-input-set")
    before = _identity(values)
    digest = hashlib.sha256(json.dumps(before, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    _require(digest == INPUT_SHA, "node-complete-456-identity")
    _require(_bound(values["net/factory.c"], FACTORY_PIN), "node-factory-before")
    supplied = materials() if selected_materials is None else selected_materials
    _require(type(supplied) is dict and set(supplied) == {MATERIAL_NAME}
             and _bound(supplied[MATERIAL_NAME], MATERIAL_PIN), "node-material-set")
    old = values["net/factory.c"]
    # Selection is immutable SOURCE of this separate image, not a request bit,
    # environment variable, path fallback or a NODE_ATTACH interpretation.
    new = edit_factory(old)
    result = dict(values)
    result["net/factory.c"] = new
    _require(MATERIAL_NAME not in result, "node-output-collision")
    result[MATERIAL_NAME] = supplied[MATERIAL_NAME]
    return result, {
        "stage": "node-bootstrap-custody",
        "compiledAbi": COMPILED_ABI,
        "beforeCount": 456, "afterCount": 457,
        "changed": ["net/factory.c"], "added": [MATERIAL_NAME],
        "ordinaryProfileInverseExact": True,
        "nodeFundingQualified": False,
        "nodeRetirementQualified": False,
        "irqEnableQualified": False,
        "consumerInstalled": False,
    }

