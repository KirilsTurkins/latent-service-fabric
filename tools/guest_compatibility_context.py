"""Bounded build/runtime provenance beside an immutable compatibility report."""
from __future__ import annotations

import re

from tools import guest_compatibility as compatibility
from tools.dev_workflow.common import decode, digest, encode, integer, members, require, sha

SCHEMA = "lsf.guest.compatibility.context.v1"
MAX_BYTES = 65536
MAX_MATERIALS = 64
KINDS = {"sdk", "compiler", "runtime", "patch", "build-tool", "generated", "dependency"}
BUFFER_PROFILE = 'lsf-node-buffer-v1'
BUFFER_MATERIALS = ('typescript-standard-buffer', 'typescript-standard-buffer-backend',
                    'typescript-standard-buffer-declaration')
NET_PROFILE = 'lsf-node-net-tcp-v1'
NET_PARTS = ('backend', 'transport', 'bindings', 'resolver', 'declaration', 'interface')
NET_MATERIALS = ('typescript-standard-net', *(f'typescript-standard-net-{part}' for part in NET_PARTS))


def net_module(value):
    """Identify the complete source-bound Socket subgroup, never API support."""
    rows = {row['name']: row for row in value['materials']
            if row['kind'] == 'runtime' and row['name'] in NET_MATERIALS}
    if not rows:
        return None
    require(value['language'] == 'typescript' and set(rows) == set(NET_MATERIALS)
            and all(row.get('profile') == NET_PROFILE for row in rows.values()),
            'compatibility-context-net-module-group')
    owner = value['standardRuntime']
    require(owner.get('state') == 'selected-unqualified'
            and owner.get('receiptName') == 'standard-runtime-selection.json' and owner.get('ownerIssue') == 745,
            'compatibility-context-net-module-owner')
    recipes = [row for row in value['materials'] if row['kind'] == 'compiler' and row['name'] == 'build-recipe']
    require(len(recipes) == 1, 'compatibility-context-net-module-recipe')
    return {**rows, 'build-recipe': recipes[0]}


def buffer_module(value):
    """A complete fixed API-level subgroup; package names never select it."""
    rows = {row['name']: row for row in value['materials']
            if row['kind'] == 'runtime' and row['name'] in BUFFER_MATERIALS}
    if not rows:
        return None
    require(value['language'] == 'typescript' and set(rows) == set(BUFFER_MATERIALS)
            and all(row.get('profile') == BUFFER_PROFILE for row in rows.values()),
            'compatibility-context-buffer-module-group')
    owner = value['standardRuntime']
    require(owner.get('state') == 'selected-unqualified'
            and owner.get('receiptName') == 'standard-runtime-selection.json' and owner.get('ownerIssue') == 745,
            'compatibility-context-buffer-module-owner')
    recipes = [row for row in value['materials'] if row['kind'] == 'compiler' and row['name'] == 'build-recipe']
    require(len(recipes) == 1, 'compatibility-context-buffer-module-recipe')
    return {**rows, 'build-recipe': recipes[0]}


def version_token(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}', value),
            'compatibility-context-dependency-version')
    return value


def material(kind: str, name: str, identity: str, *, profile=None,
             original=None, transformation=None, version=None) -> dict:
    value = {"kind": kind, "name": name, "digest": identity}
    for key, item in (("profile", profile), ("originalDigest", original), ("transformDigest", transformation),
                      ("version", version)):
        if item is not None:
            value[key] = item
    validate_material(value)
    return value


def validate_material(value):
    members(value, {"kind", "name", "digest"}, {"profile", "originalDigest", "transformDigest", "version"})
    require(value['kind'] in KINDS, 'compatibility-context-material-kind')
    compatibility.token(value['name'])
    sha(value['digest'])
    if 'profile' in value:
        compatibility.token(value['profile'])
    if 'version' in value:
        require(value['kind'] == 'dependency', 'compatibility-context-version-owner')
        version_token(value['version'])
    for key in ('originalDigest', 'transformDigest'):
        if key in value:
            sha(value[key])
    require(value['kind'] != 'patch' or {'originalDigest', 'transformDigest'} <= value.keys(),
            'compatibility-context-patch-preimage-required')


def create(report: dict, materials: list[dict], selection: dict, *, omitted=0) -> dict:
    compatibility.validate(report)
    value = {'schemaVersion': SCHEMA, 'language': report['language'],
             'sourceDigest': report['sourceDigest'], 'componentDigest': report['componentDigest'],
             'compatibilityReportIdentity': report['identity'], 'hostAbiProfile': report['runtimeProfile'],
             'standardRuntime': selection, 'materials': materials, 'omittedMaterials': omitted,
             'reachability': 'unknown', 'initialization': 'unknown', 'workerDrain': 'unproven',
             'qualification': 'unknown', 'authority': 'none'}
    value['identity'] = digest(encode(value))
    return validate(value, report=report)


def validate(value, *, report=None, source=None, component=None, expected_materials=None):
    members(value, {'schemaVersion', 'language', 'sourceDigest', 'componentDigest',
        'compatibilityReportIdentity', 'hostAbiProfile', 'standardRuntime', 'materials', 'omittedMaterials',
        'reachability', 'initialization', 'workerDrain', 'qualification', 'authority', 'identity'})
    require(value['schemaVersion'] == SCHEMA and value['language'] in compatibility.LANGUAGES,
            'compatibility-context-version')
    for key in ('sourceDigest', 'compatibilityReportIdentity', 'identity'):
        sha(value[key])
    if value['componentDigest'] is not None:
        sha(value['componentDigest'])
    compatibility.token(value['hostAbiProfile'])
    selection = members(value['standardRuntime'], {'state'}, {'profile', 'receiptDigest', 'receiptName', 'ownerIssue'})
    require(selection['state'] in {'absent', 'selected-unqualified'}, 'compatibility-context-runtime-state')
    if selection['state'] == 'selected-unqualified':
        require({'profile', 'receiptDigest'} <= selection.keys(), 'compatibility-context-runtime-identity')
        compatibility.token(selection['profile']); sha(selection['receiptDigest'])
        if 'receiptName' in selection:
            require(selection['receiptName'] in {'runtime-profile.json', 'standard-runtime-selection.json'},
                    'compatibility-context-runtime-receipt-name')
        if 'ownerIssue' in selection:
            integer(selection['ownerIssue'], 1, 2**31 - 1)
            require(selection.get('receiptName') == 'standard-runtime-selection.json',
                    'compatibility-context-runtime-owner-without-receipt')
    else:
        require(set(selection) == {'state'}, 'compatibility-context-absent-runtime')
    require(isinstance(value['materials'], list) and len(value['materials']) <= MAX_MATERIALS,
            'compatibility-context-material-limit')
    seen = set()
    for item in value['materials']:
        validate_material(item)
        key = item['kind'], item['name']
        require(key not in seen, 'compatibility-context-duplicate-material')
        seen.add(key)
    buffer_module(value)
    net_module(value)
    if selection['state'] == 'selected-unqualified':
        require(any(item['kind'] == 'runtime' and item['digest'] == selection['receiptDigest']
                    and item.get('profile') == selection['profile'] for item in value['materials']),
                'compatibility-context-unbound-runtime')
    integer(value['omittedMaterials'], 0, 10000000)
    require((value['reachability'], value['initialization'], value['workerDrain'],
             value['qualification'], value['authority']) == ('unknown', 'unknown', 'unproven', 'unknown', 'none'),
            'compatibility-context-cannot-certify-support')
    require(digest(encode({key: item for key, item in value.items() if key != 'identity'})) == value['identity']
            and len(encode(value)) <= MAX_BYTES, 'compatibility-context-identity-or-size')
    if report is not None:
        compatibility.validate(report)
        require((value['language'], value['sourceDigest'], value['componentDigest'],
                 value['compatibilityReportIdentity'], value['hostAbiProfile']) ==
                (report['language'], report['sourceDigest'], report['componentDigest'],
                 report['identity'], report['runtimeProfile']), 'compatibility-context-stale-report')
    if source is not None:
        require(value['sourceDigest'] == sha(source), 'compatibility-context-stale-source')
    if component is not None:
        require(value['componentDigest'] == sha(component), 'compatibility-context-stale-component')
    if expected_materials is not None:
        require(value['materials'] == expected_materials, 'compatibility-context-stale-runtime-or-patch')
    return value


def read(raw: bytes, **bindings):
    return validate(decode(raw, MAX_BYTES), **bindings)


def present(value):
    validate(value)
    selected = value['standardRuntime']
    runtime = selected.get('profile', 'not-observed')
    owner = f"Implementation/qualification owner: #{selected['ownerIssue']}.\n" if 'ownerIssue' in selected else ''
    text = (f"Standard runtime: {runtime}; qualification unknown.\n"
            f"Host ABI: {value['hostAbiProfile']}.\n"
            f"{owner}"
            "Reachability and initialization remain unknown; worker drain remains unproven.\n"
            "Use the ordinary captured dependency/profile workflow; review grants separately.\n")
    module = buffer_module(value)
    if module is not None:
        text += ('SELECTED runtime module: buffer, node:buffer; profile ' + BUFFER_PROFILE
                 + '; qualification unknown; authority none; receipt ' + module[BUFFER_MATERIALS[0]]['digest']
                 + '; backend ' + module[BUFFER_MATERIALS[1]]['digest']
                 + '; declaration ' + module[BUFFER_MATERIALS[2]]['digest']
                 + '; recipe ' + module['build-recipe']['digest'] + '.\n')
    net = net_module(value)
    if net is not None:
        text += ('SELECTED runtime module: net, node:net; profile ' + NET_PROFILE
                 + '; implementation/qualification owner #745; qualification unknown; authority none'
                 + '; receipt ' + net[NET_MATERIALS[0]]['digest']
                 + ''.join('; ' + part + ' ' + net[name]['digest']
                           for part, name in zip(NET_PARTS, NET_MATERIALS[1:]))
                 + '; recipe ' + net['build-recipe']['digest'] + '.\n')
    for row in value['materials']:
        if module is not None and row['kind'] == 'runtime' and row['name'] in BUFFER_MATERIALS:
            continue
        if net is not None and row['kind'] == 'runtime' and row['name'] in NET_MATERIALS:
            continue
        transformed = row['kind'] == 'generated' and {'originalDigest', 'transformDigest'} <= row.keys()
        if row['kind'] not in {'runtime', 'patch', 'dependency'} and not transformed:
            continue
        label = ('Generated transformation' if transformed else
                 'Captured dependency' if row['kind'] == 'dependency' else row['kind'].capitalize())
        details = [f"{label}: {row['name']}", "selected " + row['digest']]
        if row['kind'] == 'dependency':
            details.append('captured version ' + row.get('version', 'not-observed'))
        if 'profile' in row:
            details.append('profile ' + row['profile'])
        if 'originalDigest' in row:
            details.append('original ' + row['originalDigest'])
        if 'transformDigest' in row:
            details.append('transformation ' + row['transformDigest'])
        text += '; '.join(details) + '.\n'
    if value['omittedMaterials']:
        text += f"Additional materials omitted: {value['omittedMaterials']}.\n"
    text += 'Linked libraries share capsule authority; package attribution creates no separate principal.\n'
    return text
