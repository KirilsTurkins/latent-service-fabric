"""Ordinary Go live stack/GC/heap work under original finite request budgets."""
import json
from pathlib import Path

from tools.go_capsule_project import create
from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, inventory, read_file, snapshot

PROFILES = ('go-component-async-v1', 'go-component-activation-v5')
MODES = ('baseline', 'stack-gc', 'heap-gc')
HEAP_BYTES = 12 * 1024 * 1024
STACK_BYTES = 2 * 33 * 8192
GO = r'''
var costCalls uint32

type costMemory struct {
    HeapAlloc, HeapSys, StackInuse, StackSys, Sys uint64
    NumGC uint32
    Goroutines int
}

func costReadMemory() costMemory {
    var value runtime.MemStats
    runtime.ReadMemStats(&value)
    return costMemory{value.HeapAlloc, value.HeapSys, value.StackInuse,
        value.StackSys, value.Sys, value.NumGC, runtime.NumGoroutine()}
}

//go:noinline
func costRecursive(depth, seed int, ready chan<- struct{}, release <-chan struct{}) uint64 {
    var frame [8192]byte
    for index := range frame { frame[index] = byte(index ^ seed) }
    var value uint64
    if depth == 0 {
        runtime.GC()
        ready <- struct{}{}
        <-release
    } else {
        value = costRecursive(depth-1, seed+1, ready, release)
    }
    // Every original frame remains live through recursion, GC and suspension.
    for _, item := range frame { value += uint64(item) }
    return value
}

func costStack(before costMemory) costMemory {
    ready, release := make(chan struct{}, 2), make(chan struct{})
    done := make(chan uint64, 2)
    for _, seed := range []int{17, 29} {
        go func(value int) { done <- costRecursive(32, value, ready, release) }(seed)
    }
    <-ready
    <-ready
    live := costReadMemory()
    if live.StackInuse < before.StackInuse+2*33*8192 || live.NumGC <= before.NumGC {
        panic("cost-live-stack-or-GC-not-observed")
    }
    close(release)
    for range 2 {
        // 33 complete 8192-byte frames, each containing 32 permutations of 0..255.
        if <-done != 34467840 { panic("cost-stack-data-not-restored") }
    }
    return live
}

func costHeap(before costMemory) costMemory {
    value := make([]byte, 12*1024*1024)
    for index := 0; index < len(value); index += 4096 { value[index] = byte(index / 4096) }
    value[len(value)-1] = 42
    runtime.GC()
    live := costReadMemory()
    if live.HeapAlloc < uint64(len(value)) || live.NumGC <= before.NumGC {
        panic("cost-live-heap-or-GC-not-observed")
    }
    var checksum uint64
    for index := 0; index < len(value); index += 4096 { checksum += uint64(value[index]) }
    checksum += uint64(value[len(value)-1])
    if checksum != 391722 { panic("cost-heap-data-not-restored") }
    runtime.KeepAlive(value)
    return live
}

func costResult(mode string, before, live costMemory) wit.Result[string, string] {
    values := []string{"cost", "mode="+mode, "fresh=1", "value=42"}
    for _, pair := range []struct { key string; value uint64 }{
        {"beforeHeapAlloc", before.HeapAlloc}, {"heapAlloc", live.HeapAlloc},
        {"beforeStackInuse", before.StackInuse}, {"stackInuse", live.StackInuse},
        {"heapSys", live.HeapSys}, {"stackSys", live.StackSys}, {"sys", live.Sys},
        {"beforeNumGC", uint64(before.NumGC)}, {"numGC", uint64(live.NumGC)},
        {"goroutines", uint64(live.Goroutines)},
    } { values = append(values, pair.key+"="+strconv.FormatUint(pair.value, 10)) }
    return wit.Ok[string, string](strings.Join(values, "|"))
}

func costCase(mode string) wit.Result[string, string] {
    costCalls++
    if costCalls != 1 { panic("cost-state-reused") }
    before := costReadMemory()
    live := before
    switch mode {
    case "baseline":
    case "stack-gc": live = costStack(before)
    case "heap-gc": live = costHeap(before)
    default: panic("cost-mode")
    }
    return costResult(mode, before, live)
}
'''


def stack_reference_source():
    start = '//go:noinline\nfunc costRecursive('
    end = '\nfunc costStack('
    require(GO.count(start) == GO.count(end) == 1, 'Go-cost-exact-recursive-reference-source')
    body = GO[GO.index(start):GO.index(end)]
    return ('package main\n\nimport "runtime"\n\n' + body + '\nfunc main() {}\n').encode()


def project(directory: Path, profile: str):
    require(profile in PROFILES, 'Go-cost-explicit-existing-profile')
    app = create(directory, 'greeting', runtime_profile=profile)
    original = snapshot(app)
    source = read_file(app / 'src/main.go').decode()
    anchor = 'func Greet(name string) wit.Result[string, string] {\n'
    require(source.count(anchor) == source.count('import (\n') == 1, 'Go-cost-original-template-shape')
    source = source.replace('import (\n', 'import (\n    "runtime"\n    "strconv"\n', 1)
    source = source.replace(anchor, GO + '\n' + anchor +
        '    if strings.HasPrefix(name, "cost:") { return costCase(strings.TrimPrefix(name, "cost:")) }\n', 1)
    (app / 'src/main.go').write_bytes(source.encode())
    lock = json.loads(read_file(app / 'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(source.encode())
    (app / 'sdk-lock.json').write_bytes((json.dumps(lock, indent=2) + '\n').encode())
    actual = snapshot(app)
    require(set(actual) == set(original) and all(actual[n] == raw for n, raw in original.items()
        if n not in {'src/main.go', 'sdk-lock.json'}), 'Go-cost-original-SDK-WIT-and-request-budgets')
    return app, {'profile': profile, 'sourceDigest': digest(inventory(actual)),
        'fixtureDigest': digest(source.encode()), 'ordinarySource': True,
        'compilerExecuted': False, 'signedExecution': 'not-run', 'fullCostMatrixQualified': False,
        'logicalQueueResultNativeOwnersClaimed': False}
