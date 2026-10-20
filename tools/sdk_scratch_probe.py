"""Finite ordinary filesystem results, without granting a filesystem provider."""
from tools.phase2_operator_process import require
from tools.sdk_scratch_fixture import CASES, LANGUAGES

RUNTIME_CAPABILITIES = frozenset(('latent:clock/monotonic@0.1.0',
    'latent:clock/wall@0.1.0', 'latent:random/random@0.1.0'))
LABELS = {
    'rust': ('io-error|kind=unsupported', 'io-error|kind=permission-denied', 'io-error|kind=not-found'),
    'c': ('errno=notsup', 'errno=nosys', 'errno=badf', 'errno=noent', 'errno=access'),
    'java': ('file-not-found', 'io-error', 'unsupported-operation', 'security-error'),
    'dotnet': ('platform-not-supported', 'file-not-found', 'directory-not-found',
               'unauthorized-access', 'io-error'),
}
# WASI's closed numeric errno set, not arbitrary guest-provided text or codes.
GO_ERRNOS = (8, 28, 44, 52, 58, 63, 76)
UNSUPPORTED = frozenset(('io-error|kind=unsupported', 'errno=notsup', 'errno=nosys',
    'path-error|errno=52', 'platform-not-supported', 'unsupported-operation'))


def refusal(language, decoded):
    require(language in LANGUAGES, 'scratch-probe-language')
    require(type(decoded) is list and len(decoded) == 1 and type(decoded[0]) is dict
            and set(decoded[0]) == {'ok'} and type(decoded[0]['ok']) is str,
            'scratch-caught-result-shape')
    value = decoded[0]['ok']
    labels = tuple('path-error|errno=' + str(code) for code in GO_ERRNOS) if language == 'go' else LABELS[language]
    matched = [label for label in labels if value == 'scratch|' + language + '|' + label + '|fresh=1']
    require(len(matched) == 1, 'scratch-standard-api-refusal-not-observed')
    return {'category': matched[0], 'unsupported': matched[0] in UNSUPPORTED,
            'source': 'caught-standard-api-result', 'genericTrapCauseInferred': False}


def probe(client, target, accounting, result, population, *, language):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    require(language in LANGUAGES, 'scratch-probe-language')
    grants = target.get('grants', [])
    require(type(grants) is list and all(type(row) is dict
            and row.get('capability') in RUNTIME_CAPABILITIES for row in grants),
            'scratch-no-filesystem-or-storage-grant')
    rows = []

    def invoke(mode):
        row = call(client, target, 'greeting', 'greet', ['scratch:' + mode], 'scratch-' + language + '-' + mode)
        result['invocations'].append(row)
        require(row['processReaped'] and row['response']['outcomeKnown'] is True,
                'scratch-known-reaped-invocation')
        consumption = row['response']['data']['consumption']
        require(0 < int(consumption['cpuFuel']) <= target['budget']['cpuFuel']
                and 0 < int(consumption['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and int(consumption['outboundRequests']) == int(consumption['logBytes']) == 0
                and int(consumption['effectCount']) == 0, 'scratch-original-bounds-zero-effects')
        return row

    def retired(label):
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, 'scratch-' + label + '-retired', population))

    entry = invoke('entry')
    assert_value(client, entry, [{'ok': 'scratch|' + language + '|entry|fresh=1'}])
    retired('entry')
    for mode in CASES[language]:
        row = invoke(mode)
        require(row['exitCode'] == 0, 'scratch-standard-api-error-must-be-caught')
        observation = refusal(language, row.get('decoded'))
        rows.append({'mode': mode, 'observation': observation, 'invocation': row})
        retired(mode)
    failed = invoke('trap')
    require(failed['exitCode'] == 4 and failed['response']['error']['code'] == 'guest-trap'
            and failed['response']['data']['terminalState'] == 'guest_trap',
            'scratch-explicit-fixture-trap-required')
    retired('explicit-fixture-trap')
    fresh = invoke('fresh')
    assert_value(client, fresh, [{'ok': 'scratch|' + language + '|entry|fresh=1'}])
    retired('fresh')
    result['standardScratchRefusal'] = {'status': 'passed', 'language': language,
        'entry': entry, 'cases': rows, 'explicitTrap': failed, 'fresh': fresh,
        'preservedRuntimeGrants': grants, 'filesystemGrantsAdded': False,
        'scratchStorageImplemented': False, 'allErrorsAreUnsupported': all(row['observation']['unsupported'] for row in rows),
        'persistentFilesystemClaimed': False,
        'fullTicketQualification': False}
