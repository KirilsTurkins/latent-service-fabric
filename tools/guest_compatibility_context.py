"""Bounded build/runtime provenance beside an immutable compatibility report."""
from __future__ import annotations

from tools import guest_compatibility as compatibility
from tools.dev_workflow.common import decode, digest, encode, integer, members, require, sha

SCHEMA = "lsf.guest.compatibility.context.v1"
MAX_BYTES = 65536
MAX_MATERIALS = 64
KINDS = {"sdk", "compiler", "runtime", "patch", "build-tool", "generated"}


def material(kind: str, name: str, identity: str, *, profile=None,
             original=None, transformation=None) -> dict:
    value = {"kind": kind, "name": name, "digest": identity}
    for key, item in (("profile", profile), ("originalDigest", original), ("transformDigest", transformation)):
        if item is not None:
            value[key] = item
    validate_material(value)
    return value


def validate_material(value):
    members(value, {"kind", "name", "digest"}, {"profile", "originalDigest", "transformDigest"})
    require(value['kind'] in KINDS, 'compatibility-context-material-kind')
    compatibility.token(value['name'])
    sha(value['digest'])
    if 'profile' in value:
        compatibility.token(value['profile'])
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
    return (f"Standard runtime: {runtime}; qualification unknown.\n"
            f"Host ABI: {value['hostAbiProfile']}.\n"
            f"{owner}"
            "Reachability and initialization remain unknown; worker drain remains unproven.\n"
            "Use the ordinary captured dependency/profile workflow; review grants separately.\n")
