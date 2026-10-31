"""Original-Node boot entry AFTER the full, unchanged 485-source capacity image.

The owning programme captures this file, all three materials and the actual
upstream Kbuild files before loading. No execution, production funding or
retirement certificate is produced by this source transformation.
"""
import hashlib
import json
from pathlib import Path
import stat

ROOT = Path(__file__).resolve().parents[4]
INPUT_SHA = "a5b280e3bddd7f947118bf9d581ace122d36d7473cacdced69b7c0795fe866f6"
MATERIAL_PINS = {'factory-node-boot.c': {'bytes': 1759, 'sha256': '6fb0330516718829850cb6f247f2d3ae174338321d6fedae81b71dec185935cb'}, 'Kconfig.fragment': {'bytes': 613, 'sha256': '6ec89531b03e80f6dd1fdfe37bcfee5de99b68482260d6a8ceeab98cfddce873'}, 'Makefile.fragment': {'bytes': 107, 'sha256': 'f6da199a724e3439ee123027b59b07a23e5a5db6bc47fe7874424cb1c834cdbe'}}
MATERIAL_ROOT = "research/standard-outbound/linux-6.12-lineage/node-boot"
OLD_ENTRY = b"""    /* Same NULL consumer and closed installation gate. A flag/environment or
     * NODE_ATTACH cannot select these fops or authorize an unqualified image.
     * The trusted Rust installed-image permit MUST precede this syscall. */
    if (!lsf_factory_selected_consumer())
        return error;
"""
NEW_ENTRY = b"""    /* The immutable built-in preparation image uses only its registered Node
     * fops. The original escrow must precede this syscall. This is not a
     * network consumer, NodeFunding approval or a native retirement issuer. */
#ifdef CONFIG_LSF_STREAM_NODE_BOOTSTRAP
    if (!lsf_node_boot_entry_ready())
        return error;
#else
    if (!lsf_factory_selected_consumer())
        return error;
#endif
"""
OLD_INCLUDE = b'#include "factory-node-bootstrap.c"\n'
NEW_INCLUDE = (b"#ifdef CONFIG_LSF_STREAM_NODE_BOOTSTRAP\n"
               b"static bool lsf_node_boot_entry_ready(void);\n#endif\n" + OLD_INCLUDE)
BOOT_INCLUDE = b'\n#ifdef CONFIG_LSF_STREAM_NODE_BOOTSTRAP\n#include "factory-node-boot.c"\n#endif\n'


def require(value, reason):
    if not value:
        raise ValueError("node-boot-" + reason)


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def identities(values):
    return {name: identity(raw) for name, raw in sorted(values.items())}


def materials(root=ROOT):
    result = {}
    for name, expected in MATERIAL_PINS.items():
        path = Path(root) / MATERIAL_ROOT / name
        status = path.lstat()
        require(stat.S_ISREG(status.st_mode) and not path.is_symlink() and
                status.st_size == expected["bytes"], "material-kind-length")
        with path.open("rb") as stream:
            raw = stream.read(expected["bytes"] + 1)
        require(identity(raw) == expected and b"\r" not in raw, "material-identity")
        raw.decode("utf-8", "strict")
        result[name] = raw
    return result


def inverse_factory(raw):
    require(raw.count(NEW_INCLUDE) == 1 and raw.endswith(BOOT_INCLUDE), "factory-inverse-shape")
    return raw[:-len(BOOT_INCLUDE)].replace(NEW_INCLUDE, OLD_INCLUDE, 1)


def inverse_bootstrap(raw):
    require(raw.count(NEW_ENTRY) == 1, "entry-inverse-shape")
    return raw.replace(NEW_ENTRY, OLD_ENTRY, 1)


GEOMETRY_SOURCE = "include/linux/lsf-node-irq-geometry.c"
GEOMETRY_SECTION = b'__section(".lsf_node_geometry")'
GEOMETRY_LINK_SECTION = b'__section(".rodata.lsf_node_geometry")'


def inverse_geometry_for_link(raw):
    require(type(raw) is bytes and raw.count(GEOMETRY_LINK_SECTION) == 1 and
            GEOMETRY_SECTION not in raw, "geometry-link-inverse-shape")
    return raw.replace(GEOMETRY_LINK_SECTION, GEOMETRY_SECTION, 1)


def geometry_for_link(raw):
    # All six allocating TUs include this one read-only constant declaration.
    # Linux's normal .rodata.* placement admits it without an orphan bypass.
    # The earlier ET_REL-only geometry programme keeps its original section.
    require(type(raw) is bytes and raw.count(GEOMETRY_SECTION) == 1 and
            GEOMETRY_LINK_SECTION not in raw, "geometry-link-declaration")
    result = raw.replace(GEOMETRY_SECTION, GEOMETRY_LINK_SECTION, 1)
    require(inverse_geometry_for_link(result) == raw, "geometry-link-whole-file-inverse")
    return result


def transform(values, build_files, selected_materials):
    require(type(values) is dict and len(values) == 485 and
            all(type(n) is str and type(r) is bytes for n, r in values.items()), "input-set")
    before = identities(values)
    require(hashlib.sha256(json.dumps(before, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest() == INPUT_SHA, "complete-input-identity")
    require(type(selected_materials) is dict and set(selected_materials) == set(MATERIAL_PINS) and
            all(identity(selected_materials[n]) == pin for n, pin in MATERIAL_PINS.items()), "materials")
    require(type(build_files) is dict and set(build_files) == {"net/Kconfig", "net/Makefile"} and
            all(type(raw) is bytes and len(raw) <= 256 * 1024 for raw in build_files.values()), "kbuild-set")
    # These full files come from the pinned archive plus the original owning
    # factory Kbuild additions. Capture BOTH before/after; no phantom Git modes.
    require(build_files["net/Kconfig"].count(b"config LSF_STREAM_FACTORY\n") == 1 and
            build_files["net/Makefile"].count(b"obj-$(CONFIG_LSF_STREAM_FACTORY) += factory.o\n") == 1 and
            all(b"LSF_STREAM_NODE_BOOTSTRAP" not in raw for raw in build_files.values()), "original-kbuild")
    factory = values["net/factory.c"]
    bootstrap = values["net/factory-node-bootstrap.c"]
    require(factory.count(OLD_INCLUDE) == 1 and BOOT_INCLUDE not in factory and
            b"#define LSF_STREAM_NODE_CAPACITY_IMAGE 1\n" in factory and
            b"#define LSF_STREAM_NODE_BOOTSTRAP_IMAGE 1\n" in factory, "compiled-capacity-profile")
    require(bootstrap.count(OLD_ENTRY) == 1 and
            b"#define LSF_NODE_VERSION 3u" in bootstrap and
            b"    struct lsf_node_capacity capacity;" in bootstrap, "native-entry")
    result = dict(values)
    result[GEOMETRY_SOURCE] = geometry_for_link(values[GEOMETRY_SOURCE])
    result["net/factory.c"] = factory.replace(OLD_INCLUDE, NEW_INCLUDE, 1) + BOOT_INCLUDE
    result["net/factory-node-bootstrap.c"] = bootstrap.replace(OLD_ENTRY, NEW_ENTRY, 1)
    require("net/factory-node-boot.c" not in result, "material-collision")
    result["net/factory-node-boot.c"] = selected_materials["factory-node-boot.c"]
    for name, fragment in [("net/Kconfig", "Kconfig.fragment"), ("net/Makefile", "Makefile.fragment")]:
        require(name not in result, "kbuild-collision")
        result[name] = build_files[name] + b"\n" + selected_materials[fragment]
        require(result[name][:-len(selected_materials[fragment])-1] == build_files[name], "kbuild-inverse")
    require(inverse_factory(result["net/factory.c"]) == factory and
            inverse_bootstrap(result["net/factory-node-bootstrap.c"]) == bootstrap and
            inverse_geometry_for_link(result[GEOMETRY_SOURCE]) == values[GEOMETRY_SOURCE],
            "whole-body-inverses")
    return result, {"stage": "q35-node-boot-entry", "before": before, "after": identities(result),
        "nativeBuildBefore": identities(build_files), "materialInputs": identities(selected_materials),
        "compiledAbi": "lsf-q35-node-capacity-v2", "wireVersion": 3,
        "beforeCount": 485, "afterCount": 488, "originalBodiesInverseExact": True,
        "geometryLinkPlacement": {"source": GEOMETRY_SOURCE, "declarations": 1,
            "section": ".rodata.lsf_node_geometry", "wholeFileInverseExact": True},
        "registrationOwner": "original-platform-prerequisite-not-Node",
        "nodeFundingQualified": False, "nodeRetirementQualified": False,
        "irqEnabled": False, "consumerInstalled": False, "booted": False}
