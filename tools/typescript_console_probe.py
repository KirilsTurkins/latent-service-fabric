"""Owned ordinary-console fixture and strict signed-node assertions for #681."""
import json
from pathlib import Path

from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file, write_json

CASES = ('initializer', 'format', 'unicode', 'boundary', 'oversize', 'objects', 'budget', 'fresh')
LIBRARY = '''console.info('ordinary transitive initializer');
const initialized = true;
let calls = 0;
export function consoleCase(name: string): string {
  if (!initialized || ++calls !== 1) throw new Error('console-initialization-or-fresh-state');
  if (!name.startsWith('console:')) return '';
  const mode = name.slice(8);
  if (mode === 'initializer' || mode === 'fresh') return '1';
  if (mode === 'format') {console.log('ordinary %s %i', 'library', '42.8');return '1';}
  if (mode === 'unicode') {console.warn('Grüße 😀');return '1';}
  if (mode === 'boundary') {console.debug('λ'.repeat(128));return '1';}
  if (mode === 'oversize') {
    try {console.error('λ'.repeat(129));} catch (error) {if(error instanceof RangeError)return '1';throw error;}
  }
  if (mode === 'objects') {
    let inspected = 0;
    try {console.log({toString(){inspected++;return 'must-not-inspect';}});}
    catch (error) {if(error instanceof TypeError && inspected === 0)return '1';throw error;}
  }
  if (mode === 'budget') {
    try {for(let count=0;count<64;count++)console.info('x'.repeat(256));}
    catch (error) {
      const payload = error && typeof error === 'object' && 'payload' in error ? error.payload : null;
      if (payload && typeof payload === 'object' && 'tag' in payload && payload.tag === 'budget-exhausted')return '1';
      throw error;
    }
  }
  throw new Error('console-case-failed');
}
'''


def prepare(project: Path) -> dict:
    world = project/'wit/world.wit'
    original = read_file(world).decode()
    require(original.count('world service {') == 1 and 'latent:log/' not in original,
            'typescript-console-original-world-required')
    world.write_text(original.replace('world service {', 'world service {\n    import latent:log/log@0.1.0;', 1), encoding='utf-8')
    source = project/'src/main.ts'
    original = read_file(source).decode()
    require(original.count('  greet(name) {') == 1, 'typescript-console-original-greeting-required')
    source.write_text("import {consoleCase} from './console-library.js';\nconsole.warn('ordinary direct initializer');\n" +
        original.replace('  greet(name) {', "  greet(name) {\n    const logged = consoleCase(name);\n    if (name.startsWith('console:')) return logged;", 1), encoding='utf-8')
    (project/'src/console-library.ts').write_text(LIBRARY, encoding='utf-8')
    dependency = project/'wit/deps/log'
    dependency.mkdir(parents=True)
    (dependency/'package.wit').write_bytes(read_file(ROOT/'wit/platform/log/package.wit'))
    configuration = json.loads(read_file(project/'capsule-project.json'))
    configuration['limits']['logBytes'] = 16384
    (project/'capsule-project.json').write_text(json.dumps(configuration, indent=2)+'\n', encoding='utf-8')
    lock = json.loads(read_file(project/'sdk-lock.json'))
    lock['template'].update(sourceDigest=digest(read_file(source)), witDigest=digest(read_file(world)))
    (project/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf-8')
    return {'profile': 'lsf-console-strict-v1', 'direct': digest(read_file(source)),
            'transitive': digest(read_file(project/'src/console-library.ts')), 'cases': list(CASES),
            'signedExecution': 'pending'}


def configure(settings):
    providers = settings['providers']
    require('log' not in providers, 'typescript-console-provider-already-installed')
    providers['log'] = {'identity': {'id': 'log', 'tenant': 'examples', 'service': 'runtime-host', 'epoch': 1}}
    providers['bindings'].append({'name': 'console-greeting', 'tenant': 'examples',
        'consumerService': 'examples/my-greeting', 'providerService': 'runtime-host',
        'contract': 'latent:log/log@0.1.0', 'providerBinding': 'log-installed'})


def grant_and_probe(client, node, fixture, targets, publications, result):
    from tools.rust_capsule_node import assert_value, call, deploy, provider_idle
    target = targets['greeting']
    denied = call(client, target, 'greeting', 'greet', ['console:initializer'], 'ts-console-denied')
    result['invocations'].append(denied)
    response = denied['response']
    consumption = response['data']['consumption']
    require(denied['exitCode'] == 4 and response['error']['code'] == 'permission-denied'
            and response['outcomeKnown'] is True and response['data']['terminalState'] == 'rejected'
            and all(consumption[key] == '0' for key in ('cpuFuel', 'peakMemoryBytes', 'logBytes')),
            'typescript-console-missing-grant-must-reject-before-guest')
    capability = 'latent:log/log@0.1.0'
    installed = [row for row in node.startup_record['providers'] if row['id'] == 'log']
    require(len(installed) == 1 and installed[0]['capability'] == capability
            and installed[0]['profile'] == 'activation-log-v1'
            and installed[0]['tenant'] == 'examples' and installed[0]['service'] == 'runtime-host',
            'typescript-console-provider-identity')
    descriptor = installed[0]
    binding = client.directory/'console-binding.json'
    write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': capability,
        'providerProfile': descriptor['profile'], 'configurationDigest': descriptor['configurationDigest'],
        'configurationEpoch': 1, 'restriction': {'operations': ['write']}})
    client.call('policy', '--kind', 'provider-binding', 'apply', '--id', 'log-installed', '--file', binding,
                '--operation-id', 'install-typescript-console', '--expected-generation', '0')
    policy = client.directory/'console-policy.json'
    write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'console', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']], 'capability': capability,
        'operations': ['write'], 'resources': {'kind': 'log', 'levels': ['info', 'debug', 'warn', 'error']},
        'ceiling': {'operations': 64, 'inputBytes': 16384, 'outputBytes': 0, 'wallTimeMillis': 5000}}]})
    client.call('policy', 'apply', '--id', 'typescript-console', '--file', policy,
                '--operation-id', 'grant-typescript-console', '--expected-generation', '0')
    targets['greeting'] = target = deploy(client, fixture/'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=[{'capability': capability, 'policy': 'typescript-console'}])
    result['typescriptConsoleCases'] = []
    for ordinal, name in enumerate(CASES):
        row = call(client, target, 'greeting', 'greet', ['console:'+name], 'ts-console-'+str(ordinal))
        result['invocations'].append(row)
        assert_value(client, row, [{'ok': '1'}])
        usage = row['response']['data']['consumption']
        require(0 < int(usage['logBytes']) <= target['budget']['logBytes']
                and all(int(usage[key]) == 0 for key in ('outboundRequests', 'childCalls', 'effectCount')),
                'typescript-console-real-log-accounting')
        result['providerIdle'].append(provider_idle(client))
        result['typescriptConsoleCases'].append({'case': name, 'activation': row['activation'],
                                                'logBytes': usage['logBytes']})
