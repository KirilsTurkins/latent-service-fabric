"""Observe the fixed adapter's actual Cargo units without exporting cache paths."""
from pathlib import Path

from tools.build_inventory_manifests import ManifestReader
from tools.build_inventory_units import collect_units
from tools.build_observation import file_identity
from tools.build_sbom_inputs import cargo_home
from tools.build_snapshot import SnapshotError, canonical
from tools.angular_build.tools import ROOT


def observe(output: bytes, tools) -> list[dict]:
    names = ('Cargo.toml', 'Cargo.lock', 'tools/angular-renderer-adapter/Cargo.toml')
    source = []
    for name in names:
        row = file_identity(ROOT / name, name, 4 * 1024 * 1024)
        source.append({'path': name, 'digest': row['digest'], 'size': row['size']})
    reader = ManifestReader(ROOT, canonical(source), cargo_home(tools.environment))
    units = collect_units(output.decode('utf-8'), Path(tools.environment['CARGO_TARGET_DIR']),
                          component_library='latent_angular_renderer_adapter')
    rows = []
    for unit in units:
        facts = reader.package(unit.manifest)
        if unit.role == 'component' and unit.manifest != ROOT / names[2]:
            raise SnapshotError('Angular adapter observation selected an unexpected source')
        role = 'guest-dependency' if unit.role == 'component' else unit.role
        row = {'kind': role, 'name': facts.name, 'version': facts.version, 'origin': facts.source_kind,
               'manifestDigest': facts.manifest_digest, 'manifestSize': facts.manifest_size}
        if facts.archive_digest is None:
            relative = unit.manifest.relative_to(ROOT).as_posix()
            row.update(digest=facts.manifest_digest, digestScope='source-manifest',
                       source=facts.repository or 'urn:lsf:workspace:' + relative)
        else:
            row.update(digest=facts.archive_digest, digestScope='registry-archive-declared',
                       source=facts.repository or 'urn:lsf:registry:crates.io/' + facts.name)
        if facts.license_expression in ('MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'ISC', 'CC0-1.0', '0BSD'):
            row['licenseExpression'] = facts.license_expression
        rows.append(row)
    reader.verify_unchanged()
    return rows
