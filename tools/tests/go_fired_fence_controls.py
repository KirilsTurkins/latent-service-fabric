#!/usr/bin/env python3
"""Run a bounded source port of the selected Go fired-timer token probe.

The deliberately weakened probe is a negative control of the witness only; it
is not a pre-fix runtime or signed-node result.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.go_guest.fired_timer_witness import derive

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'package firedport\n\ntype lsfTimerWait struct { token [2]uint64; stopped bool; done chan struct{} }\nvar state *struct { timerWaits []*lsfTimerWait }\nvar lsfFiredFirstStopped [2]uint64\nvar observed chan struct{}\nfunc lsfFiredFenceWitness() { observed <- struct{}{} }\n'
TEST = 'package firedport\nimport ("testing"; "time")\nfunc TestOriginalStopIdentityFencesOnlyItsOwnUnsettledWait(t *testing.T) {\n target := &lsfTimerWait{token:[2]uint64{1,10},done:make(chan struct{})}\n other := &lsfTimerWait{token:[2]uint64{1,11},done:make(chan struct{})}; close(other.done)\n state=&struct{timerWaits []*lsfTimerWait}{[]*lsfTimerWait{target,other}}\n lsfFiredFirstStopped=[2]uint64{}; observed=make(chan struct{},2)\n lsfActivationTimerStopped(1,10)\n if !target.stopped || other.stopped { t.Fatal("wrong stopped record") }\n lsfActivationTimerFence(1,11)\n select { case <-observed: t.Fatal("foreign unadmitted wait falsely signaled target"); default: }\n returned:=make(chan struct{}); go func(){lsfActivationTimerFence(1,10);close(returned)}()\n select { case <-observed: case <-time.After(time.Second):t.Fatal("target probe missing") }\n select {case <-returned:t.Fatal("fence returned before original wait closed");default:}\n close(target.done)\n select {case <-returned:case <-time.After(time.Second):t.Fatal("fence did not return")}\n}\nfunc TestGenerationMustMatchTheFirstStoppedToken(t *testing.T) {\n other:=&lsfTimerWait{token:[2]uint64{2,10},done:make(chan struct{})};close(other.done)\n state=&struct{timerWaits []*lsfTimerWait}{[]*lsfTimerWait{other}}\n lsfFiredFirstStopped=[2]uint64{}; observed=make(chan struct{},2)\n lsfActivationTimerStopped(1,10)\n lsfActivationTimerFence(2,10)\n select {case <-observed:t.Fatal("generation alias falsely signaled target");default:}\n}\n'


def extract(source: str, signature: str) -> str:
    if source.count(signature) != 1:
        raise ValueError('Go-fired-fence-control-shape')
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == '{':
            depth += 1
        elif source[index] == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise ValueError('Go-fired-fence-control-unclosed')


def main() -> None:
    go = shutil.which('go')
    if go is None:
        raise ValueError('Go-fired-fence-control-pinned-go-missing')
    version = subprocess.run([go, 'version'], check=True, capture_output=True, text=True, timeout=10).stdout.split()
    if len(version) < 3 or version[2] != 'go1.27.3':
        raise ValueError('Go-fired-fence-control-unreviewed-go')
    raw = (ROOT / 'sdk/go-guest/runtime/timer_async.go.in').read_bytes()
    if len(raw) > 16384:
        raise ValueError('Go-fired-fence-control-source-bound')
    source = derive(raw).decode('utf-8')
    stop = extract(source, 'func lsfActivationTimerStopped(')
    fence = extract(source, 'func lsfActivationTimerFence(')
    selected = 'if wait.token == lsfFiredFirstStopped { lsfFiredFenceWitness() }'
    if fence.count(selected) != 1 or 'lsfFiredFirstStopped = [2]uint64{generation, id}' not in stop:
        raise ValueError('Go-fired-fence-control-token-match-missing')
    weakened = fence.replace(selected, 'lsfFiredFenceWitness()', 1)
    with tempfile.TemporaryDirectory(prefix='lsf-go-fired-fence-') as temporary:
        root = Path(temporary)
        environment = dict(os.environ, GOENV='off', GOWORK='off', GOTOOLCHAIN='local', GOPROXY='off',
                           GOSUMDB='off', GOFLAGS='', GOOS='linux', GOARCH='amd64', CGO_ENABLED='0',
                           GOCACHE=str(root / 'cache'))
        for name, selected_fence in (('weakened', weakened), ('selected', fence)):
            folder = root / name
            folder.mkdir()
            (folder / 'go.mod').write_text('module firedport\n\ngo 1.27.3\n', encoding='utf-8')
            (folder / 'port.go').write_text(PREFIX + '\n' + stop + '\n' + selected_fence + '\n', encoding='utf-8')
            (folder / 'port_test.go').write_text(TEST, encoding='utf-8')
            result = subprocess.run([go, 'test', '-count=1', '-v', './...'], cwd=folder, env=environment,
                                    capture_output=True, text=True, timeout=90)
            output = result.stdout + result.stderr
            if len(output.encode('utf-8')) > 1024 * 1024:
                raise ValueError('Go-fired-fence-control-output-bound')
            if name == 'weakened':
                if (result.returncode == 0 or 'foreign unadmitted wait falsely signaled target' not in output
                        or 'generation alias falsely signaled target' not in output):
                    raise ValueError('Go-fired-fence-weak-probe-not-rejected')
            elif result.returncode != 0 or output.count('--- PASS: Test') != 2:
                raise ValueError('Go-fired-fence-selected-probe-failed: ' + output[-1000:])
            print(name + ': ' + ('both false signals rejected' if name == 'weakened' else 'both source-port controls passed'))


if __name__ == '__main__':
    main()
