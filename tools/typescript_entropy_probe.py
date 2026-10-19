"""Finite ordinary Math.random qualification under explicit RANDOM authority."""
import json
from pathlib import Path
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file, snapshot, write_json

RANDOM = 'latent:random/random@0.1.0'
CASES = ('one', 'many', 'bounds', 'budget', 'fresh')
LIBRARY = '''let calls = 0;
export function entropyCase(mode: string): string {
  if (++calls !== 1) throw new Error('entropy-state-reused');
  let count = 0;
  const draw = () => {
    const value = Math.random();
    if (typeof value !== 'number' || !(value >= 0 && value < 1)
        || !Number.isInteger(value * 9007199254740992)) throw new Error('entropy-range-or-width');
    count++;
  };
  if (mode === 'budget') {
    try {for (let index = 0; index < 8193; index++) draw();}
    catch (error) {
      const payload = error && typeof error === 'object' && 'payload' in error ? error.payload : null;
      if (payload && typeof payload === 'object' && 'tag' in payload && payload.tag === 'budget-exhausted') {
        return 'entropy:budget:bounded';
      }
      throw error;
    }
    throw new Error('entropy-budget-was-not-enforced');
  }
  const expected = mode === 'many' ? 33 : mode === 'bounds' ? 256 : mode === 'one' || mode === 'fresh' ? 1 : 0;
  if (!expected) throw new Error('entropy-case');
  for (let index = 0; index < expected; index++) draw();
  if (count !== expected) throw new Error('entropy-draw-count');
  return 'entropy:' + mode + ':ok';
}
'''


def prepare(project: Path, template: str):
    require(template in {'greeting', 'word-count'}, 'typescript-entropy-template')
    source = project/'src/main.ts'
    original = read_file(source).decode('utf-8')
    world = project/'wit/world.wit'
    wit = read_file(world).decode('utf-8')
    require(RANDOM not in wit and wit.count('world service {') == 1,
            'typescript-entropy-original-world')
    if template == 'greeting':
        require(original.count('  greet(name) {') == 1, 'typescript-entropy-original-greeting')
        selected = "import {entropyCase} from './entropy-library.js';\n"+original.replace('  greet(name) {',
            "  greet(name) {\n    if (name.startsWith('entropy:')) return entropyCase(name.slice(8));", 1)
        (project/'src/entropy-library.ts').write_bytes(LIBRARY.encode())
        world.write_bytes(wit.replace('world service {', 'world service {\n    import '+RANDOM+';', 1).encode())
        for name, body in snapshot(ROOT/'wit/platform/random').items():
            destination = project/'wit/deps/random'/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as output: output.write(body)
    else:
        require(original.count('  count(text) {') == 1, 'typescript-entropy-original-word-count')
        selected = original.replace('  count(text) {', '''  count(text) {
    if (text === 'entropy:undeclared') {
      try {Math.random();} catch (error) {
        if (error instanceof Error && error.message === 'unsupported:Math.random-without-approved-entropy') return 681;
        throw error;
      }
      throw new Error('undeclared-entropy-returned-a-value');
    }''', 1)
    source.write_bytes(selected.encode())
    lock = json.loads(read_file(project/'sdk-lock.json'))
    lock['template'].update(sourceDigest=digest(read_file(source)), witDigest=digest(read_file(world)))
    (project/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    return {'template': template, 'source': digest(read_file(source)), 'world': digest(read_file(world)),
        'applicationLibrary': digest(LIBRARY.encode()) if template == 'greeting' else None,
        'publishedLibraryQualification': False, 'snapshotTimeDraws': 'refused', 'signedExecution': 'pending'}


def configure(settings):
    providers = settings['providers']
    require('random' not in providers and len(providers['bindings']) < 16,
            'typescript-entropy-original-provider-capacity')
    providers['random'] = {'identity': {'id': 'ts-entropy', 'tenant': 'examples', 'service': 'entropy-host', 'epoch': 1}}
    providers['bindings'].append({'name': 'ts-entropy-greeting', 'tenant': 'examples',
        'consumerService': 'examples/my-greeting', 'providerService': 'entropy-host',
        'contract': RANDOM, 'providerBinding': 'ts-entropy-installed'})


def grant(client, node, fixture, targets, publications, result):
    from tools.c_standard_facilities_probe import require_denied_before_guest
    from tools.rust_capsule_node import call, deploy, provider_idle
    target = targets['greeting']
    require(RANDOM not in {row['capability'] for row in target['grants']}, 'typescript-entropy-initial-authority')
    denied = call(client, target, 'greeting', 'greet', ['entropy:one'], 'ts-entropy-missing-grant')
    result['invocations'].append(denied)
    require_denied_before_guest(denied)
    require(denied['processReaped'], 'typescript-entropy-denial-process')
    result['providerIdle'].append(provider_idle(client))
    installed = [row for row in node.startup_record['providers'] if row['id'] == 'ts-entropy']
    require(len(installed) == 1 and installed[0]['capability'] == RANDOM
            and installed[0]['profile'] == 'system-random-v1'
            and installed[0]['tenant'] == 'examples' and installed[0]['service'] == 'entropy-host',
            'typescript-entropy-installed-identity')
    descriptor = installed[0]
    binding = client.directory/'entropy-binding.json'
    write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': RANDOM,
        'providerProfile': descriptor['profile'], 'configurationDigest': descriptor['configurationDigest'],
        'configurationEpoch': 1, 'restriction': {'operations': ['u64-value']}})
    client.call('policy', '--kind', 'provider-binding', 'apply', '--id', 'ts-entropy-installed', '--file', binding,
        '--operation-id', 'install-typescript-entropy', '--expected-generation', '0')
    policy = client.directory/'entropy-policy.json'
    write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'entropy', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']], 'capability': RANDOM,
        'operations': ['u64-value'], 'resources': {'kind': 'random'},
        'ceiling': {'operations': 4096, 'inputBytes': 8, 'outputBytes': 8, 'wallTimeMillis': 5000}}]})
    client.call('policy', 'apply', '--id', 'typescript-entropy', '--file', policy,
        '--operation-id', 'grant-typescript-entropy', '--expected-generation', '0')
    # Policy ceilings are per operation, independently of the unchanged 65536-byte provider aggregate.
    ceiling = json.loads(read_file(policy))
    ceiling['rules'][0]['ceiling']['inputBytes'] = 0
    ceiling_path = client.directory/'entropy-policy-ceiling.json'
    write_json(ceiling_path, ceiling)
    client.call('policy', 'apply', '--id', 'typescript-entropy-policy-ceiling', '--file', ceiling_path,
        '--operation-id', 'grant-typescript-entropy-policy-ceiling', '--expected-generation', '0')
    targets['greeting'] = deploy(client, fixture/'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=[*target['grants'], {'capability': RANDOM, 'policy': 'typescript-entropy'}])
    result['typescriptEntropyDenial'] = denied


def probe(client, targets, accounting, result, population, fixture, publications):
    from tools.rust_capsule_node import assert_value, call, deploy, provider_idle, sample
    original = targets['greeting']['grants']
    require([row for row in original if row['capability'] == RANDOM] ==
            [{'capability': RANDOM, 'policy': 'typescript-entropy'}], 'typescript-entropy-original-policy')
    rows, authority = [], []
    for mode in ('undeclared', *CASES):
        if mode in {'budget', 'fresh'}:
            grants = [{**row, 'policy': 'typescript-entropy-policy-ceiling'} if row['capability'] == RANDOM
                      else row for row in original] if mode == 'budget' else original
            target = targets['greeting']
            targets['greeting'] = deploy(client, fixture/'my-greeting/deployment.json', publications['greeting'],
                generation=str(target['generation']), grants=grants)
            authority.append({'case': 'policy-ceiling' if mode == 'budget' else 'fresh',
                'randomInputBytesPerCall': 0 if mode == 'budget' else 8,
                'generation': targets['greeting']['generation'], 'grants': grants})
        template, function = ('word-count', 'count') if mode == 'undeclared' else ('greeting', 'greet')
        target = targets[template]
        row = call(client, target, template, function, ['entropy:'+mode], 'ts-entropy-'+mode)
        result['invocations'].append(row)
        expected = 681 if mode == 'undeclared' else 'entropy:budget:bounded' if mode == 'budget' else 'entropy:'+mode+':ok'
        assert_value(client, row, [{'ok': expected}])
        used = row['response']['data']['consumption']
        require(row['processReaped'] and 0 < int(used['cpuFuel']) <= target['budget']['cpuFuel']
                and 0 < int(used['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and all(int(used[key]) == 0 for key in ('outboundRequests', 'childCalls', 'logBytes', 'effectCount')),
                'typescript-entropy-original-budget-and-effects')
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, 'ts-entropy-'+mode+'-retired', population))
        rows.append({'case': mode, 'decoded': row['decoded'], 'activation': row['activation']})
    result['typescriptStandardEntropy'] = {'status': 'passed', 'cases': rows,
        'cryptographicAPI': False, 'statisticalQualityTest': False, 'randomPayloadRetained': False,
        'publishedLibraryQualification': False, 'providerAggregateBytesUnchanged': 65536,
        'providerAggregateExhaustionQualified': False, 'budgetCase': 'zero-input-per-operation-policy-ceiling',
        'policyTransitions': authority, 'originalPolicyRestoredBeforeFresh': True}
