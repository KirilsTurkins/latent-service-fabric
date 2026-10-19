"""Ordinary captured Go fmt/log/os writes on an enforced signed node."""
from pathlib import Path
import json
import shutil

from tools import go_native_authoring as native
from tools.go_application_dependencies import resolve
from tools.go_dependency_authoring import review, status
from tools.phase2_operator_process import require, read_json, write_json
from tools.rust_capsule_project import ROOT, digest, snapshot

IDENTITY = 'outside.example.test/ordinary-standard-logging'
CASES = ('initializer', 'fmt', 'stderr', 'log', 'zero', 'invalid-utf8', 'too-large',
         'host-limit', 'budget', 'panic', 'fmt')
LIBRARY = '''package ordinary
import (
    "fmt"
    "log"
    "os"
    "strings"
    "syscall"
)
var calls int
var initialized bool
func init() {
    n, err := fmt.Fprint(os.Stdout, "ordinary library initializer")
    initialized = n == 28 && err == nil
}
func Exercise(mode string) string {
    calls++
    if calls != 1 || !initialized { panic("logging activation state was reused or initializer failed") }
    switch mode {
    case "initializer": return "1"
    case "fmt":
        n, err := fmt.Fprintf(os.Stdout, "ordinary dependency: %d ü\\n", 42)
        if err == nil && n == len("ordinary dependency: 42 ü\\n") { return "1" }
    case "stderr":
        n, err := fmt.Fprintln(os.Stderr, "ordinary dependency error")
        if err == nil && n == 26 { return "1" }
    case "log":
        if err := log.Output(1, "ordinary standard logger"); err == nil { return "1" }
    case "zero":
        n, err := os.Stdout.Write(nil)
        if n == 0 && err == nil { return "1" }
    case "invalid-utf8":
        for _, data := range [][]byte{{255}, {0xc0, 0x80}, {0xed, 0xa0, 0x80}, {0xf4, 0x90, 0x80, 0x80}, {0xe2, 0x82}} {
            n, err := syscall.Write(1, data)
            if n != 0 || err != syscall.EILSEQ { return "unexpected-encoding-result" }
        }
        return "1"
    case "too-large", "host-limit":
        size := 4097
        if mode == "host-limit" { size = 257 }
        n, err := syscall.Write(1, []byte(strings.Repeat("a", size)))
        if n == 0 && err == syscall.EINVAL { return "1" }
    case "budget":
        for index := 0; index < 16; index++ {
            n, err := syscall.Write(1, []byte(strings.Repeat("a", 256)))
            if err != nil {
                if n == 0 && err == syscall.EAGAIN { return "1" }
                return "unexpected-budget-result"
            }
            if n != 256 { return "unexpected-short-write" }
        }
    case "panic": panic("ordinary logging terminal control")
    }
    return "unexpected-standard-log-result"
}
'''


def install(project: Path, outside: Path, go: Path) -> dict:
    before = snapshot(project)
    outside.mkdir(mode=0o700)
    (outside / 'go.mod').write_text('module ' + IDENTITY + '\n\ngo 1.27.2\n', encoding='utf-8')
    (outside / 'logging.go').write_text(LIBRARY, encoding='utf-8')
    source = before['src/main.go']
    hook = b'func Greet(name string) wit.Result[string, string] {'
    require(source.count(hook) == 1 and source.count(b'import (') == 1, 'go-standard-log-original-template')
    source = source.replace(b'import (', b'import (\n    ordinary "' + IDENTITY.encode() + b'"')
    source = source.replace(hook, hook + b'\n    if strings.HasPrefix(name, "log:") {\n'
        b'        return wit.Ok[string, string](ordinary.Exercise(strings.TrimPrefix(name, "log:")))\n    }')
    (project / 'src/main.go').write_bytes(source)
    wit = before['wit/world.wit']
    require(wit.count(b'world service {') == 1, 'go-standard-log-original-world')
    wit = wit.replace(b'world service {', b'world service {\n    import latent:log/log@0.1.0;')
    (project / 'wit/world.wit').write_bytes(wit)
    for name, raw in snapshot(ROOT / 'wit/platform/log').items():
        path = project / 'wit/deps/log' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    descriptor = read_json(project / 'capsule-project.json')
    descriptor['limits']['logBytes'] = 1024
    write_json(project / 'capsule-project.json', descriptor)
    sdk = read_json(project / 'sdk-lock.json')
    sdk['template']['sourceDigest'], sdk['template']['witDigest'] = digest(source), digest(wit)
    write_json(project / 'sdk-lock.json', sdk)
    sdk_before = (project / 'sdk-lock.json').read_bytes()
    native.edit(project, 'add', identity=IDENTITY, version='v0.0.0', local=outside, go=go)
    native.create_lock(project, go=go)
    candidate = project / 'target/standard-log.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    captured = resolve(project, candidate, go=go)
    rows = [row for row in captured['artifacts'] if row['metadata'].get('module') == IDENTITY]
    require(len(rows) == 1 and rows[0]['role'] == 'application' and not captured['executableInputs'],
            'go-standard-log-ordinary-captured-library')
    review(project, candidate, digest(candidate.read_bytes()))
    require(status(project)['status'] == 'verified' and (project / 'sdk-lock.json').read_bytes() == sdk_before,
            'go-standard-log-reviewed-source-required')
    require(outside.resolve(strict=True).parent == project.resolve(strict=True).parent,
            'go-standard-log-cleanup-owner')
    shutil.rmtree(outside)
    return {'formatVersion': 1, 'identity': IDENTITY, 'artifact': rows[0]['id'],
        'librarySourceDigest': digest(LIBRARY.encode()), 'sourceDigest': digest(source),
        'lockDigest': digest((project / 'latent.dependencies.lock.json').read_bytes()),
        'originalOutsideSource': 'removed-after-review', 'catalogueRegistration': False,
        'customLoggerOrApplicationCallback': False, 'executableInputs': []}


def configure(settings):
    providers = settings['providers']
    require('log' not in providers, 'go-standard-log-provider-already-selected')
    providers['log'] = {'identity': {'id': 'log', 'tenant': 'examples', 'service': 'runtime-host', 'epoch': 1}}
    providers['bindings'].append({'name': 'log-greeting', 'tenant': 'examples',
        'consumerService': 'examples/my-greeting', 'providerService': 'runtime-host',
        'contract': 'latent:log/log@0.1.0', 'providerBinding': 'log-installed'})


def grant(client, node, fixture, targets, publications, result):
    from tools.c_standard_facilities_probe import require_denied_before_guest
    from tools.rust_capsule_node import call, deploy
    from tools.static_api.node import policy
    target = targets['greeting']
    row = call(client, target, 'greeting', 'greet', ['log:initializer'], 'go-log-without-grant')
    result['invocations'].append(row)
    require_denied_before_guest(row)
    rows = [row for row in node.startup_record['providers'] if row['id'] == 'log']
    require(len(rows) == 1 and rows[0]['capability'] == 'latent:log/log@0.1.0'
            and rows[0]['profile'] == 'activation-log-v1', 'go-standard-log-provider-identity')
    selected = rows[0]
    policy(client, 'provider-binding', 'log-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': selected['capability'], 'providerProfile': selected['profile'],
        'configurationDigest': selected['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': ['write']}})
    policy(client, 'policy', 'go-log-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'stdio', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']],
        'capability': selected['capability'], 'operations': ['write'],
        'resources': {'kind': 'log', 'levels': ['info', 'error']},
        'ceiling': {'operations': 64, 'inputBytes': 16384, 'outputBytes': 0, 'wallTimeMillis': 5000}}]})
    grants = [dict(row) for row in target['grants']]
    grants.append({'capability': selected['capability'], 'policy': 'go-log-allow'})
    targets['greeting'] = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
                                generation=str(target['generation']), grants=grants)
    result['goStandardLoggingGrants'] = grants


def probe(client, target, ownership, result, population):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    from tools.rust_dependency_recovery import failed
    for index, mode in enumerate(CASES):
        row = call(client, target, 'greeting', 'greet', ['log:' + mode], 'go-log-' + str(index))
        result['invocations'].append(row)
        if mode == 'panic':
            failed(row, 'guest-trap', target['budget']['memoryBytes'])
        else:
            assert_value(client, row, [{'ok': '1'}])
        require(row['processReaped'], 'go-standard-log-client-not-reaped')
        consumption = row['response']['data']['consumption']
        require(0 < int(consumption['logBytes']) <= target['budget']['logBytes']
                and int(consumption['outboundRequests']) == 0, 'go-standard-log-actual-accounting')
        result['samples'].append(sample(client, ownership, 'go-log-' + str(index), population))
        result['providerIdle'].append(provider_idle(client))
    result['goStandardLogging'] = {'status': 'passed', 'cases': list(CASES),
        'scope': 'ordinary captured fmt/log/os writes, activation-local initializer, errors, terminal trap and fresh call',
        'asyncBufferedLogging': 'not-qualified', 'retrySafety': 'unknown'}
