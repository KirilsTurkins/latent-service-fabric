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
from tools.go_guest.fired_timer_witness import derive, derive_activation_bridge

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'package firedport\n\nimport "unsafe"\nvar lsfReturnedToken [2]uint64\nvar lsfReturnedFenceSeen bool\nfunc lsfReturnedSetFenceChannel(unsafe.Pointer) {}\ntype lsfTimerWait struct { token [2]uint64; stopped bool; done chan struct{} }\nvar state *struct { timerWaits []*lsfTimerWait }\nvar lsfFiredFirstStopped [2]uint64\nvar observed chan struct{}\nfunc lsfFiredFenceWitness() { observed <- struct{}{} }\n'
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



# This source port models scheduler admission and the canonical subtask edges.
# It runs the exact selected Go helpers; the real provider/park is witnessed
# only by the separately selected signed owner.
RETURNED_PREFIX = r'''package returnedport
import ("runtime"; "unsafe")
type lsfTimerWait struct { token [2]uint64; subtask uint32; result unsafe.Pointer; stopped, started bool; done chan struct{} }
var state *struct { timerWaits []*lsfTimerWait }
var lsfFiredFirstStopped, lsfReturnedToken, selected [2]uint64
var lsfReturnedFenceSeen, lsfReturnedCancel, cancelSelected bool
var heldProbes int
var events chan string
var release chan struct{}
var marked unsafe.Pointer
func lsfReturnedTickerSelected(g, id uint64) bool { return selected == [2]uint64{g,id} }
func lsfReturnedCancelSelected(g, id uint64) bool { return cancelSelected && selected == [2]uint64{g,id} }
func lsfReturnedObserve() {
    if cancelSelected && lsfReturnedFenceSeen { heldProbes++; events <- "held"; if heldProbes == 3 { panic("simulated root cancellation") }; return }
    if lsfReturnedFenceSeen { events <- "after-drop" } else { events <- "event"; close(release) }
}
func lsfFiredFenceWitness() { events <- "fence" }
func lsfReturnedSetFenceChannel(p unsafe.Pointer) { marked=p; if p == nil { events <- "unmark" } else { events <- "mark" } }
func waitableJoin(_, _ uint32) { events <- "unjoin" }
func subtaskDrop(_ uint32) { events <- "drop" }
func lsfRemoveTimerWait(_ *lsfTimerWait) { state.timerWaits=nil }
func lsfCompleteTimerWait(wait *lsfTimerWait) { close(wait.done) }
'''
RETURNED_TEST = r'''package returnedport
import ("testing"; "time"; "unsafe")
func reset() *lsfTimerWait {
    value:=new([16]byte); wait:=&lsfTimerWait{token:[2]uint64{7,10},subtask:42,result:unsafe.Pointer(value),started:true,done:make(chan struct{})}
    state=&struct{timerWaits []*lsfTimerWait}{[]*lsfTimerWait{wait}}
    lsfFiredFirstStopped=[2]uint64{};lsfReturnedToken=[2]uint64{};lsfReturnedFenceSeen=false;lsfReturnedCancel=false;cancelSelected=false;heldProbes=0
    selected=wait.token;events=make(chan string,16);release=make(chan struct{});marked=nil
    return wait
}
func TestReturnedEventWaitsForSameTokenFenceBeforeDrop(t *testing.T) {
    wait:=reset(); finished:=make(chan struct{})
    go func(){ <-release;lsfActivationTimerStopped(7,10);lsfActivationTimerFence(7,10);events<-"public";close(finished) }()
    if !lsfHandleTimerEvent(42) { t.Fatal("matched event not handled") }
    select { case <-finished: case <-time.After(time.Second): t.Fatal("public Stop did not complete") }
    for _, want:=range []string{"event","fence","mark","unjoin","drop","after-drop","unmark","public"} {
        select {case got:= <-events: if got!=want {t.Fatalf("got %s, want %s",got,want)};default:t.Fatalf("missing %s",want)}
    }
    if marked!=nil || len(state.timerWaits)!=0 || !wait.stopped {t.Fatal("owner bookkeeping")}
}
func TestReturnedEventDoesNotAcceptAnErrorOrAnotherToken(t *testing.T) {
    wait:=reset();*(*byte)(wait.result)=1;lsfReturnedBeforeDrop(wait)
    if lsfReturnedToken != [2]uint64{} { t.Fatal("error result admitted") }
    *(*byte)(wait.result)=0;selected=[2]uint64{8,10};lsfReturnedBeforeDrop(wait)
    if lsfReturnedToken != [2]uint64{} {t.Fatal("foreign token admitted")}
    select {case got:= <-events:t.Fatalf("unexpected probe %s",got);default:}
}
func TestReturnedFenceRejectsAnotherGeneration(t *testing.T) {
    reset();foreign:=&lsfTimerWait{token:[2]uint64{8,10},done:make(chan struct{})};close(foreign.done)
    state.timerWaits=[]*lsfTimerWait{foreign};lsfReturnedToken=[2]uint64{7,10}
    lsfActivationTimerFence(8,10)
    if lsfReturnedFenceSeen || marked!=nil {t.Fatal("foreign generation marked as matched fence")}
}
func TestCancellationHoldsTheOriginalEventBeforeSubtaskDrop(t *testing.T) {
    wait:=reset();cancelSelected=true;finished:=make(chan struct{})
    go func(){ <-release;lsfActivationTimerStopped(7,10);lsfActivationTimerFence(7,10);events<-"public";close(finished) }()
    defer func(){
        if recover()==nil || heldProbes!=3 { t.Fatal("simulated cancellation did not stop the held event") }
        for len(events)>0 { event:= <-events; if event=="unjoin" || event=="drop" || event=="public" { t.Fatalf("early %s",event) } }
        if len(state.timerWaits)!=1 || state.timerWaits[0]!=wait {t.Fatal("original wait was removed")}
        close(wait.done)
        select {case <-finished:case <-time.After(time.Second):t.Fatal("test waiter did not finish")}
    }()
    lsfHandleTimerEvent(42)
    t.Fatal("held event unexpectedly returned")
}
'''


def returned_controls(go: str, root: Path, environment: dict, derived: str) -> None:
    names = ('lsfActivationTimerStopped', 'lsfActivationTimerFence', 'lsfReturnedBeforeDrop',
             'lsfReturnedAfterDrop', 'lsfHandleTimerEvent')
    bodies = {name: extract(derived, 'func ' + name + '(') for name in names}
    selected = 'if wait.token == lsfReturnedToken {'
    if bodies['lsfActivationTimerFence'].count(selected) != 1:
        raise ValueError('Go-returned-fence-token-match-missing')
    for name, fence in (('weakened-returned', bodies['lsfActivationTimerFence'].replace(selected, 'if true {', 1)),
                        ('selected-returned', bodies['lsfActivationTimerFence'])):
        folder = root / name
        folder.mkdir()
        (folder / 'go.mod').write_text('module returnedport\n\ngo 1.27.3\n', encoding='utf-8')
        source = RETURNED_PREFIX + '\n' + '\n'.join(fence if key == 'lsfActivationTimerFence' else bodies[key] for key in names)
        (folder / 'port.go').write_text(source, encoding='utf-8')
        (folder / 'port_test.go').write_text(RETURNED_TEST, encoding='utf-8')
        result = subprocess.run([go, 'test', '-count=1', '-v', './...'], cwd=folder, env=environment,
                                capture_output=True, text=True, timeout=90)
        output = result.stdout + result.stderr
        if len(output.encode('utf-8')) > 1024 * 1024:
            raise ValueError('Go-returned-fence-control-output-bound')
        if name == 'weakened-returned':
            if result.returncode == 0 or 'foreign generation marked as matched fence' not in output:
                raise ValueError('Go-returned-fence-weak-probe-not-rejected')
        elif result.returncode != 0 or output.count('--- PASS: Test') != 4:
            raise ValueError('Go-returned-fence-selected-probe-failed: ' + output[-1500:])
        print(name + ': ' + ('foreign generation rejected' if name.startswith('weakened') else 'four source-port controls passed'))



PARK_PREFIX = r'''package parkport
import "unsafe"
type lsfUnitResult struct {tag, failure byte}
type hchan struct {id int}
type channelRef struct {value *hchan}
func (p *channelRef) get() *hchan {return p.value}
type sudog struct {waitlink *sudog; c channelRef}
type g struct {lsfOwner [2]uint64; lsfParked bool; waitreason int; waiting *sudog}
const waitReasonChanReceive=1
var lsfReturnedFenceChannel unsafe.Pointer
var parks, observations int
var deny bool
func lsfPark(_, _ int64, result unsafe.Pointer) {parks++;if deny {(*lsfUnitResult)(result).tag=1}}
func lsfReturnedParkObserve(_ unsafe.Pointer) {observations++}
func lsfFail(s string) {panic(s)}
'''
PARK_TEST = r'''package parkport
import ("testing";"unsafe")
func reset() (*g,*hchan) {parks=0;observations=0;deny=false;channel:=&hchan{10};lsfReturnedFenceChannel=unsafe.Pointer(channel);return &g{lsfOwner:[2]uint64{7,1},waitreason:waitReasonChanReceive,waiting:&sudog{c:channelRef{channel}}},channel}
func TestMatchingFenceChannelReportsAfterOriginalPark(t *testing.T) {
 gp,_:=reset();lsfTaskPark(gp)
 if parks!=1 || observations!=1 || !gp.lsfParked {t.Fatal("matching fence did not report after accepted park")}
}
func TestForeignOrNonReceiveParksNeverReportFence(t *testing.T) {
 for _,mode:=range []string{"foreign","multiple","reason","nil","unowned"} {
  gp,_:=reset();switch mode {case "foreign":gp.waiting.c.value=&hchan{10};case "multiple":gp.waiting.waitlink=&sudog{};case "reason":gp.waitreason=2;case "nil":gp.waiting=nil;case "unowned":gp.lsfOwner=[2]uint64{}}
  lsfTaskPark(gp);if observations!=0 {t.Fatalf("%s park falsely reported matching channel",mode)}
 }
}
func TestRefusedParkCannotReportFence(t *testing.T) {
 gp,_:=reset();deny=true;defer func(){if recover()==nil || observations!=0 {t.Fatal("refused park reported")}}();lsfTaskPark(gp)
}
'''


def returned_park_controls(go: str, root: Path, environment: dict) -> None:
    original = (ROOT / 'sdk/go-guest/runtime/activation_bridge.go.in').read_bytes()
    park = extract(derive_activation_bridge(original).decode('utf-8'), 'func lsfTaskPark(')
    selected = 'unsafe.Pointer(gp.waiting.c.get()) == lsfReturnedFenceChannel'
    if park.count(selected) != 1:
        raise ValueError('Go-returned-park-channel-match-missing')
    for name, body in (('weakened-park', park.replace(selected, 'true', 1)), ('selected-park', park)):
        folder = root / name
        folder.mkdir()
        (folder / 'go.mod').write_text('module parkport\n\ngo 1.27.3\n', encoding='utf-8')
        (folder / 'port.go').write_text(PARK_PREFIX + '\n' + body + '\n', encoding='utf-8')
        (folder / 'port_test.go').write_text(PARK_TEST, encoding='utf-8')
        result = subprocess.run([go, 'test', '-count=1', '-v', './...'], cwd=folder, env=environment,
                                capture_output=True, text=True, timeout=90)
        output = result.stdout + result.stderr
        if len(output.encode('utf-8')) > 1024 * 1024:
            raise ValueError('Go-returned-park-control-output-bound')
        if name == 'weakened-park':
            if result.returncode == 0 or 'foreign park falsely reported matching channel' not in output:
                raise ValueError('Go-returned-park-weak-probe-not-rejected')
        elif result.returncode != 0 or output.count('--- PASS: Test') != 3:
            raise ValueError('Go-returned-park-selected-probe-failed: ' + output[-1500:])
        print(name + ': ' + ('foreign channel rejected' if name.startswith('weakened') else 'three source-port controls passed'))


def cancellation_gate_controls(root: Path) -> None:
    rustc = shutil.which('rustc')
    if rustc is None:
        raise ValueError('Go-returned-cancel-gate-pinned-rust-missing')
    version = subprocess.run([rustc, '--version'], check=True, capture_output=True, text=True, timeout=10).stdout.split()
    if len(version) < 2 or version[1] != '1.97.1':
        raise ValueError('Go-returned-cancel-gate-unreviewed-rust')
    source = ROOT / 'crates/latent-wasmtime/src/development_go_timer_cancel.rs'
    binary = root / 'returned-cancel-gate'
    build = subprocess.run([rustc, '--edition=2021', '--test', str(source), '-o', str(binary)],
                           capture_output=True, text=True, timeout=90)
    if build.returncode != 0 or len((build.stdout + build.stderr).encode()) > 1024 * 1024:
        raise ValueError('Go-returned-cancel-gate-build-failed: ' + build.stderr[-1500:])
    result = subprocess.run([str(binary), '--test-threads=1'], capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    if (result.returncode != 0 or len(output.encode()) > 1024 * 1024
            or 'test result: ok. 3 passed; 0 failed; 0 ignored;' not in output):
        raise ValueError('Go-returned-cancel-gate-controls-failed: ' + output[-1500:])
    print('returned-cancel: three exact Rust gate controls passed')


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
        returned_controls(go, root, environment, source)
        returned_park_controls(go, root, environment)
        cancellation_gate_controls(root)


if __name__ == '__main__':
    main()
