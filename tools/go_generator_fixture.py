"""Explicit owned source-generator approval in the normal signed Go campaign."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import secrets
import socket

from tools import go_capsule
from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, read_json, snapshot, write_json

CANARY = 'LSF_APPROVED_GO_GENERATOR_CANARY'
TOOL = b'''#!/usr/bin/python3
import json, os, pathlib, socket
value = json.loads(pathlib.Path("/inputs/selection.json").read_bytes())
assert not os.environ.get("LSF_APPROVED_GO_GENERATOR_CANARY")
assert not pathlib.Path("/etc/passwd").exists()
try:
    pathlib.Path(value["outsideCanary"]).read_bytes()
except OSError:
    pass
else:
    raise AssertionError("ambient host source exposed")
try:
    connection = socket.create_connection(("127.0.0.1", value["parentPort"]), timeout=.5)
except OSError:
    pass
else:
    connection.close()
    raise AssertionError("parent network exposed")
source = 'package export_examples_greeting_api\\nimport "strconv"\\n'
source += "func ApprovedGeneratedValue(text string) (uint32, string) { return "
source += str(value["value"]) + "+uint32(len([]byte(text))), " + json.dumps(value["nonce"]) + '+"|"+text }\\n'
source += 'func ApprovedGeneratedText(text string) string { value, identity := ApprovedGeneratedValue(text); '
source += 'return strconv.FormatUint(uint64(value), 10)+"|"+identity }\\n'
pathlib.Path("/outputs/approved_value.go").write_text(source)
'''


def cli(name, arguments, expected, commands):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = go_capsule.main(list(map(str, arguments)))
    commands.append({'stage': name, 'exitCode': code})
    require(code == expected, 'Go-generator-owned-CLI-outcome')
    return json.loads(stdout.getvalue() if expected == 0 else stderr.getvalue())


def install(project: Path, outside: Path):
    outside.mkdir(mode=0o700)
    inputs = outside/'inputs'; inputs.mkdir(mode=0o700)
    nonce, selected_value = secrets.token_hex(12), secrets.randbelow(1000000) + 1000
    executable, canary = outside/'generate-source', outside/'host-only-canary'
    executable.write_bytes(TOOL); executable.chmod(0o700)
    canary.write_bytes(b'owned fixture canary')
    source = project/'src/main.go'
    original = source.read_bytes()
    hook = b'func applicationPrefix(name string) string {'
    require(original.count(hook) == 1, 'Go-generator-source-hook')
    greeting = b'return wit.Ok[string, string](applicationPrefix(name) + name + "!")'
    require(original.count(greeting) == 1, 'Go-generator-original-greeting')
    source.write_bytes(original.replace(greeting, b'if strings.HasPrefix(name, "generated-go:") {\n'
        b'        return wit.Ok[string, string](ApprovedGeneratedText(strings.TrimPrefix(name, "generated-go:")))\n    }\n    ' + greeting))
    before, sdk = snapshot(project), (project/'sdk-lock.json').read_bytes()
    candidate = project/'target/generator-request.json'
    candidate.parent.mkdir(mode=0o700, exist_ok=True)
    commands = []
    with socket.socket() as peer:
        peer.settimeout(1); peer.bind(('127.0.0.1', 0)); peer.listen(2)
        port = peer.getsockname()[1]
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            connection, _ = peer.accept(); connection.close()
        selection = {'nonce': nonce, 'value': selected_value, 'outsideCanary': str(canary.resolve()), 'parentPort': port}
        raw = json.dumps(selection, sort_keys=True).encode()
        (inputs/'selection.json').write_bytes(raw)
        request = cli('request', ['generator-request', project, '--candidate', candidate, '--tool', executable,
            '--tool-version', 'owned-Go-generator-v1', '--inputs', inputs, '--timeout', '15',
            '--maximum-output-bytes', '65536'], 0, commands)
        require(request['approvalRequired'] and not request['generatorExecution']
                and request['requestDigest'] == digest(candidate.read_bytes()), 'Go-generator-request-identity')
        denial = cli('wrong-approval', ['generate', project, '--candidate', candidate,
            '--expect', 'sha256:' + '0'*64], 1, commands)
        require(denial['reason'] == 'go-generator-request-approval-mismatch' and snapshot(project) == before,
                'Go-generator-unapproved-execution')
        (inputs/'selection.json').write_bytes(raw + b' ')
        denial = cli('changed-input', ['generate', project, '--candidate', candidate,
            '--expect', request['requestDigest']], 1, commands)
        require(denial['reason'] == 'go-generator-tool-or-input-drift' and snapshot(project) == before,
                'Go-generator-changed-input-execution')
        (inputs/'selection.json').write_bytes(raw)
        previous = os.environ.get(CANARY)
        os.environ[CANARY] = 'owned-parent-only-value'
        try:
            generated = cli('approved', ['generate', project, '--candidate', candidate,
                '--expect', request['requestDigest']], 0, commands)
        finally:
            if previous is None:
                os.environ.pop(CANARY, None)
            else:
                os.environ[CANARY] = previous
        require((generated['status'], generated['cleanup'], generated['generatedFiles']) == ('succeeded', 'reaped', 1),
                'Go-generator-real-execution-and-reaping')
    selected = read_json(project/'go-generated-inputs.json')['records']
    require(len(selected) == 1 and selected[0]['requestDigest'] == request['requestDigest'],
            'Go-generator-adopted-request')
    files = snapshot(project)
    require(all(files[name] == raw for name, raw in before.items()) and (project/'sdk-lock.json').read_bytes() == sdk,
            'Go-generator-replaced-existing-source')
    output = project/'src/generated/approved_value.go'
    require(str(selected_value).encode() in output.read_bytes() and nonce.encode() in output.read_bytes(),
            'Go-generator-produced-selection')
    executable.unlink(); canary.unlink(); (inputs/'selection.json').unlink()
    cli('offline-status', ['dependencies', project], 0, commands)
    result = {'status': 'passed', 'requestDigest': request['requestDigest'],
        'generatedInputsDigest': digest((project/'go-generated-inputs.json').read_bytes()),
        'executionReceiptDigest': generated['executionReceiptDigest'],
        'generatedSourceDigest': digest(output.read_bytes()), 'toolDigest': selected[0]['toolDigest'],
        'inputsDigest': selected[0]['inputsDigest'], 'nonce': nonce, 'value': selected_value,
        'originalGeneratorAndInputs': 'unavailable-before-component-build', 'commands': commands,
        'network': 'denied', 'ambientHostCanary': 'unavailable', 'ambientEnvironmentCanary': 'unavailable',
        'cleanup': 'reaped', 'compilerExecution': False, 'runtimeExecution': 'not-yet-observed'}
    write_json(outside/'GENERATOR-COMPLETE.json', result)
    return result


def probe(client, target, ownership_probe, result, population, value):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample, selected_revision
    require(isinstance(value, dict) and set(value) == {'nonce', 'value'}
            and isinstance(value['nonce'], str) and len(value['nonce']) == 24
            and all(c in '0123456789abcdef' for c in value['nonce'])
            and type(value['value']) is int and 1000 <= value['value'] < 1001000,
            'Go-generator-probe-selection')
    selected = selected_revision(client, target)
    rows = []
    for ordinal, text in enumerate(('alpha', 'Gr\u00fc\u00dfe', 'fresh-state')):
        observed = call(client, target, 'greeting', 'greet', ['generated-go:' + text], 'Go-generator-' + str(ordinal))
        wanted = str(value['value'] + len(text.encode('utf-8'))) + '|' + value['nonce'] + '|' + text
        assert_value(client, observed, [{'ok': wanted}])
        consumption = observed['response']['data']['consumption']
        require(observed['response']['data'].get('resolvedRevision') == selected and observed['processReaped']
                and all(int(consumption[name]) == 0 for name in ('outboundRequests', 'childCalls', 'effectCount')),
                'Go-generator-signed-selected-revision')
        result['invocations'].append(observed)
        result['samples'].append(sample(client, ownership_probe, 'Go-generator-' + str(ordinal), population))
        result.setdefault('providerIdle', []).append(provider_idle(client))
        rows.append({'ordinal': ordinal, 'utf8Bytes': len(text.encode('utf-8')),
                     'selectedValue': value['value'] + len(text.encode('utf-8')), 'actualSignedTarget': True})
    result['approvedGoGenerator'] = {'status': 'passed', 'cases': rows,
        'scope': 'explicit generated request-dependent values from captured source in signed components',
        'runtimeExecution': 'signed-admitted-component', 'fullTicketQualification': False}
