"""Ordinary Go work which remains live at a real standalone-node stop."""
import json
from pathlib import Path

from tools.go_capsule_project import create
from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, inventory, read_file, snapshot

PROFILE = 'go-component-activation-v5'
GO = '''
func nodeStopTimer(duration time.Duration) {
    timer := time.NewTimer(duration)
    defer timer.Stop()
    <-timer.C
}

var nodeStopInitialized = func() uint32 {
    value := make(chan uint32)
    go func() { nodeStopTimer(time.Millisecond); value <- 42 }()
    return <-value
}()
var nodeStopCalls uint32

func nodeStopCase(mode string) wit.Result[string, string] {
    nodeStopCalls++
    if nodeStopCalls != 1 || nodeStopInitialized != 42 { panic("node-stop-state-reused") }
    switch mode {
    case "fresh":
        return wit.Ok[string, string]("node-stop|fresh=1|value=42")
    case "pending":
        var work sync.WaitGroup
        work.Add(2)
        for range 2 { go func() { defer work.Done(); nodeStopTimer(time.Hour) }() }
        work.Wait()
        panic("node-stop-pending-work-returned")
    case "drain":
        go func() { nodeStopTimer(time.Hour) }()
        return wit.Ok[string, string]("node-stop|root-returned-with-accepted-work")
    default:
        panic("node-stop-mode")
    }
}
'''


def project(directory: Path):
    app = create(directory, 'greeting', runtime_profile=PROFILE)
    before = snapshot(app)
    original = read_file(app / 'src/main.go').decode()
    anchor = 'func Greet(name string) wit.Result[string, string] {\n'
    hook = '    if strings.HasPrefix(name, "node-stop:") { return nodeStopCase(strings.TrimPrefix(name, "node-stop:")) }\n'
    require(original.count(anchor) == 1 and original.count('import (\n') == 1,
            'Go-node-stop-original-template-shape')
    source = original.replace('import (\n', 'import (\n    "sync"\n    "time"\n', 1)
    source = source.replace(anchor, GO + '\n' + anchor + hook, 1)
    (app / 'src/main.go').write_bytes(source.encode())
    # This fixture owns its declared source identity; no captured SDK input changes.
    lock = json.loads(read_file(app / 'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(source.encode())
    (app / 'sdk-lock.json').write_bytes((json.dumps(lock, indent=2) + '\n').encode())
    after = snapshot(app)
    require(set(before) == set(after) and all(after[name] == raw for name, raw in before.items()
            if name not in {'src/main.go', 'sdk-lock.json'}), 'Go-node-stop-nonsource-change')
    require(after['capsule-project.json'] == before['capsule-project.json'], 'Go-node-stop-original-budgets')
    return app, {'profile': PROFILE, 'sourceDigest': digest(inventory(after)),
                 'fixtureDigest': digest(source.encode()), 'ordinaryGoroutinesTimersWaitGroup': True,
                 'originalTemplateCasesRetained': True, 'compilerExecuted': False,
                 'signedQualification': 'pending'}
