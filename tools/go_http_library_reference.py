"""Bounded native reference of the unchanged captured Go clients, never guest proof."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time

from tools.application_dependencies import prepare
from tools.application_dependency_store import directory_files
from tools.build_observation import build_environment
from tools.build_process import run_bounded
from tools.go_application_dependencies import configure
from tools.guest_dependency_inputs import capture_source
from tools.phase2_operator_process import require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import digest, read_file

SOURCE = r'''package main

import (
    "encoding/json"
    "io"
    "net/http"
    "net/http/httptest"
    "os"
    "sync/atomic"
    app @application@
)

func main() {
    if len(os.Args) != 2 && len(os.Args) != 3 { panic("reference client required") }
    var which uint32
    switch os.Args[1] { case "sling": which = 0; case "requests": which = 100; default: panic("unknown reference client") }
    scenario, body, declared := "truncated", "short", 32
    if len(os.Args) == 3 {
        if os.Args[2] != "malformed-json" { panic("unknown reference response") }
        scenario, body, declared = "malformed-json", `{"id":`, 6
    }
    var calls atomic.Uint32
    var invalid atomic.Bool
    server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        calls.Add(1)
        if r.Method != "GET" || r.URL.Path != "/conformance/body/"+scenario { invalid.Store(true) }
        if scenario == "malformed-json" { w.Header().Set("Content-Length", "6")
        } else { w.Header().Set("Content-Length", "32") }
        w.Header().Set("Content-Type", "application/json")
        w.Header().Set("Connection", "close")
        io.WriteString(w, body)
    }))
    result := app.Run(which, server.URL+"/conformance/body/"+scenario)
    server.Close()
    json.NewEncoder(os.Stdout).Encode(struct {
        Client string `json:"client"`
        Result string `json:"result"`
        Requests uint32 `json:"requests"`
        InvalidRequest bool `json:"invalidRequest"`
        BodyBytes int `json:"bodyBytes"`
        DeclaredBytes int `json:"declaredBytes"`
    }{os.Args[1], result, calls.Load(), invalid.Load(), len(body), declared})
}
'''


def client_outcome(expected: str, row: dict, *, body_bytes: int = 5, declared_bytes: int = 32) -> str:
    require(isinstance(row, dict) and set(row) == {'client', 'result', 'requests', 'invalidRequest', 'bodyBytes', 'declaredBytes'}
        and row['client'] == expected and type(row['result']) is str and row['result'] in {'invalid-json', 'transport-error'}
        and type(row['requests']) is int and row['requests'] == 1 and row['invalidRequest'] is False
        and type(row['bodyBytes']) is int and row['bodyBytes'] == body_bytes
        and type(row['declaredBytes']) is int and row['declaredBytes'] == declared_bytes,
        'go-http-native-reference-client-result')
    return row['result']


def outcomes(record: dict) -> dict[str, str]:
    require(isinstance(record, dict) and record.get('schemaVersion') == 'latent.go.http-client.native-reference.v1'
        and record.get('status') == 'passed' and record.get('guestExecution') is False,
        'go-http-native-reference-required')
    rows = record.get('clients')
    require(isinstance(rows, list) and len(rows) == 2, 'go-http-native-reference-client-count')
    return {name: client_outcome(name, row) for name, row in zip(('sling', 'requests'), rows, strict=True)}


def malformed_outcomes(record: dict) -> dict[str, str]:
    outcomes(record)
    rows = record.get('malformedJsonClients')
    require(isinstance(rows, list) and len(rows) == 2, 'go-http-native-reference-malformed-client-count')
    return {name: client_outcome(name, row, body_bytes=6, declared_bytes=6)
            for name, row in zip(('sling', 'requests'), rows, strict=True)}


def observe(app: Path, go: Path, output: Path, *, deadline: float, include_malformed: bool = False) -> dict:
    record = {'schemaVersion': 'latent.go.http-client.native-reference.v1', 'status': 'in-progress',
              'guestExecution': False, 'scope': 'truncated-body-original-client-reference', 'stage': 'capture', 'clients': []}
    deadline = min(deadline, time.monotonic()+120)
    source_before = read_file(app/'src/main.go')
    original_go = file_identity(go)
    try:
        require(sys.platform == 'linux', 'go-http-native-reference-linux-only')
        observed = capture_source(app, 'go')
        with tempfile.TemporaryDirectory(prefix='lsf-go-http-native-reference-') as temporary:
            root = Path(temporary)
            work = root/'project'; work.mkdir()
            for name, data in observed.files.items():
                path = work/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            closure = prepare(observed.dependency_root, work, root, 'go')
            require(closure is not None, 'go-http-native-reference-captured-closure-required')
            selected = configure(closure, work)
            for name, data in directory_files(Path(selected['downloadCache'])).items():
                path = root/'modules/cache/download'/name
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            environment = build_environment(root)
            environment.update(GOTOOLCHAIN='local', GOWORK='off', GOENV='off', CGO_ENABLED='0',
                GOOS='linux', GOARCH='amd64', GOCACHE=str(root/'cache'), GOMODCACHE=str(root/'modules'),
                GOPROXY='off', GOSUMDB='off', GONOPROXY='none', GONOSUMDB='none', GOPRIVATE='', GOFLAGS='-mod=readonly')
            def command(arguments, maximum):
                remaining = min(maximum, deadline-time.monotonic())
                require(remaining > 0, 'go-http-native-reference-original-deadline')
                return run_bounded(arguments, work, environment, remaining, 65536)
            version = command([str(go), 'version'], 10).stdout.decode().split()
            pins = json.loads(read_file(app/'vendor/lsf/sdk/go-guest/toolchain.lock.json'))
            require(len(version) == 4 and version[2] == pins['go']['version'] and version[3] == 'linux/amd64',
                    'go-http-native-reference-pinned-toolchain')
            source = SOURCE.replace('@application@', json.dumps(selected['module']+'/src')).encode()
            harness = root/'main.go'; harness.write_bytes(source)
            binary = root/'reference'
            record['stage'] = 'native-build'
            command([str(go), 'build', '-mod=readonly', '-trimpath', '-o', str(binary), str(harness)], 100)
            record.update(sourceDigest=digest(source_before), harnessDigest=digest(source),
                          dependencyIdentity=closure.identity, nativeGo=original_go,
                          nativeBinary=file_identity(binary, 64*1024**2))
            for name in ('sling', 'requests'):
                record['stage'] = name+'-truncated'
                row = json.loads(command([str(binary), name], 10).stdout)
                record['clients'].append(row)
                write_json(output.with_name(output.stem+'-'+name+'.json'), row)
                client_outcome(name, row)
            if include_malformed:
                record['malformedJsonClients'] = []
                for name in ('sling', 'requests'):
                    record['stage'] = name+'-malformed-json'
                    row = json.loads(command([str(binary), name, 'malformed-json'], 10).stdout)
                    record['malformedJsonClients'].append(row)
                    write_json(output.with_name(output.stem+'-malformed-json-'+name+'.json'), row)
                    client_outcome(name, row, body_bytes=6, declared_bytes=6)
            closure.check_unchanged(); observed.check_unchanged()
        require(read_file(app/'src/main.go') == source_before and file_identity(go) == original_go,
                'go-http-native-reference-original-input-changed')
        outcomes({**record, 'status': 'passed'})
        if include_malformed:
            malformed_outcomes({**record, 'status': 'passed'})
        record.update(status='passed', stage='complete')
        return record
    except BaseException:
        record['status'] = 'failed'
        raise
    finally:
        write_json(output, record)
