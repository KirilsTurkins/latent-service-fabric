"""Actual v5 timer capture selection and fail-closed signed evidence controls."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_go_activation as activation
from tools import qualify_go_synchronization as reference


NATIVE17 = [0, 1, 2, 3, 5, 6, 18, 19, 20, 9, 11, 12, 13, 14, 15, 16, 17]


# These host-only controls compile the actual sweep, retirement and idle-drain
# functions from the runtime template. The stubs force weak conversion to park;
# they do not claim a signed component, real GC pause, or host timer execution.
SLOT_INTERLEAVING_TEST = r'''package timerowner

import (
    "testing"
    "unsafe"
)

var lsfTimerSlots []lsfTimerSlot
var conversion func(unsafe.Pointer) unsafe.Pointer
var retired, fenced [][2]uint64
var stopHook func(*timer)
var fenceHook func([2]uint64)

type timer struct {
    isChan bool
    lsfToken [2]uint64
    lsfSlot uint32
    stops int
}
func (t *timer) stop() bool { t.stops++; if stopHook != nil { stopHook(t) }; return true }
func lsfFail(message string) { panic(message) }
func KeepAlive(*timer) {}

func internal_weak_runtime_makeStrongFromWeak(p unsafe.Pointer) unsafe.Pointer { return conversion(p) }
func lsfStopTimerSlot(index uint32, token [2]uint64) {
    if token[1] == 0 { return }
    if lsfTimerSlots[index-1].token != token { panic("stale timer slot") }
    retired = append(retired, token)
    lsfTimerSlots[index-1] = lsfTimerSlot{}
}
func lsfActivationTimerFence(generation, id uint64) {
    if id != 0 {
        token := [2]uint64{generation, id}
        fenced = append(fenced, token)
        if fenceHook != nil { fenceHook(token) }
    }
}

func TestReusedSlotDuringWeakConversion(t *testing.T) {
    for _, mode := range []string{"reuse", "reuse-then-grow", "reuse-grow-reuse"} {
        t.Run(mode, func(t *testing.T) {
            old, next, last := [2]uint64{7, 1}, [2]uint64{7, 2}, [2]uint64{7, 4}
            lsfTimerSlots = make([]lsfTimerSlot, 1, 1)
            lsfTimerSlots[0].token = old
            retired, fenced = nil, nil
            parked, resume, done := make(chan struct{}), make(chan struct{}), make(chan interface{}, 1)
            conversion = func(unsafe.Pointer) unsafe.Pointer { close(parked); <-resume; return nil }
            go func() { defer func() { done <- recover() }(); lsfSweepCollectedTimers() }()
            <-parked
            // Another goroutine retires the original before publishing a new owner.
            lsfStopTimerSlot(1, old)
            lsfActivationTimerFence(old[0], old[1])
            lsfTimerSlots[0].token = next
            if mode != "reuse" {
                lsfTimerSlots = append(lsfTimerSlots, lsfTimerSlot{token:[2]uint64{7, 3}})
            }
            expected := next
            if mode == "reuse-grow-reuse" {
                lsfStopTimerSlot(1, next)
                lsfActivationTimerFence(next[0], next[1])
                lsfTimerSlots[0].token, expected = last, last
            }
            retired, fenced = nil, nil
            close(resume)
            if p := <-done; p != nil { t.Errorf("unexpected stale-owner trap: %v", p) }
            if lsfTimerSlots[0].token != expected || len(retired) != 0 || len(fenced) != 0 {
                t.Errorf("owner=%v retired=%v fenced=%v", lsfTimerSlots[0].token, retired, fenced)
            }
        })
    }
}

func TestCollectedUnchangedOwnerIsRetiredAndFenced(t *testing.T) {
    old := [2]uint64{7, 1}
    lsfTimerSlots = []lsfTimerSlot{{token:old}}
    retired, fenced = nil, nil
    conversion = func(unsafe.Pointer) unsafe.Pointer { return nil }
    lsfSweepCollectedTimers()
    if len(retired)!=1 || retired[0]!=old || len(fenced)!=1 || fenced[0]!=old { t.Fatal(retired, fenced) }
}

func TestReachableOwnerIsUntouched(t *testing.T) {
    old := [2]uint64{7, 1}
    lsfTimerSlots = []lsfTimerSlot{{token:old}}
    retired, fenced = nil, nil
    strong := new(byte)
    conversion = func(unsafe.Pointer) unsafe.Pointer { return unsafe.Pointer(strong) }
    lsfSweepCollectedTimers()
    if lsfTimerSlots[0].token != old || len(retired)!=0 || len(fenced)!=0 { t.Fatal(lsfTimerSlots, retired, fenced) }
}

func TestIdleDrainRechecksWeakConversionAfterRetirementAndReuse(t *testing.T) {
    for _, mode := range []string{"nil-reuse", "nil-reuse-grow", "nil-reuse-grow-reuse",
        "strong-stop-replace", "strong-reset-same", "strong-reset-grow", "strong-reset-relocate"} {
        t.Run(mode, func(t *testing.T) {
            oldToken, newToken := [2]uint64{7, 1}, [2]uint64{7, 2}
            old := &timer{isChan:true, lsfToken:oldToken, lsfSlot:1}
            lsfTimerSlots = []lsfTimerSlot{{token:oldToken, weak:unsafe.Pointer(old)}}
            lsfTimerSlots = append(make([]lsfTimerSlot, 0, 1), lsfTimerSlots...)
            retired, fenced, stopHook = nil, nil, nil
            parked, resume, done := make(chan struct{}), make(chan struct{}), make(chan interface{}, 1)
            calls := 0
            observed := map[[2]uint64]int{}
            conversion = func(p unsafe.Pointer) unsafe.Pointer {
                calls++
                if calls == 1 { return p } // The preceding sweep sees a live timer.
                if calls == 2 {
                    close(parked); <-resume
                    if mode[:3] == "nil" { return nil }
                    return p
                }
                current := (*timer)(p)
                observed[current.lsfToken]++
                return p
            }
            go func() { defer func() { done <- recover() }(); lsfStopIdleChannelTimers() }()
            <-parked
            // The original owner is retired before another owner reuses it.
            lsfRetireTimer(old)
            lsfActivationTimerFence(oldToken[0], oldToken[1])
            replacement := &timer{isChan:true, lsfToken:newToken, lsfSlot:1}
            if mode == "strong-reset-same" || mode == "strong-reset-grow" || mode == "strong-reset-relocate" {
                replacement = old
                replacement.lsfToken, replacement.lsfSlot = newToken, 1
            }
            lsfTimerSlots[0] = lsfTimerSlot{token:newToken, weak:unsafe.Pointer(replacement)}
            survivors := map[[2]uint64]*timer{newToken:replacement}
            if mode == "nil-reuse-grow" || mode == "nil-reuse-grow-reuse" || mode == "strong-reset-grow" {
                otherToken := [2]uint64{7, 3}
                other := &timer{isChan:true, lsfToken:otherToken, lsfSlot:2}
                lsfTimerSlots = append(lsfTimerSlots, lsfTimerSlot{token:otherToken, weak:unsafe.Pointer(other)})
                survivors[otherToken] = other
            }
            if mode == "nil-reuse-grow-reuse" {
                lsfRetireTimer(replacement)
                lastToken := [2]uint64{7, 4}
                replacement = &timer{isChan:true, lsfToken:lastToken, lsfSlot:1}
                lsfTimerSlots[0] = lsfTimerSlot{token:lastToken, weak:unsafe.Pointer(replacement)}
                delete(survivors, newToken)
                survivors[lastToken] = replacement
            }
            if mode == "strong-reset-relocate" {
                otherToken := [2]uint64{7, 3}
                other := &timer{isChan:true, lsfToken:otherToken, lsfSlot:1}
                lsfTimerSlots[0] = lsfTimerSlot{token:otherToken, weak:unsafe.Pointer(other)}
                replacement.lsfSlot = 2
                lsfTimerSlots = append(lsfTimerSlots, lsfTimerSlot{token:newToken, weak:unsafe.Pointer(replacement)})
                survivors[otherToken] = other
            }
            retired, fenced = nil, nil
            close(resume)
            if p := <-done; p != nil { t.Errorf("unexpected drain failure: %v", p) }
            for token, selected := range survivors {
                if observed[token] == 0 || selected.stops != 1 {
                    t.Errorf("replacement %v was not re-observed then stopped: conversions=%v stops=%d", token, observed, selected.stops)
                }
            }
            if mode == "strong-stop-replace" && old.stops != 0 { t.Errorf("stopped old timer after its owner retired") }
            for _, slot := range lsfTimerSlots {
                if slot.token[1] != 0 { t.Errorf("owner remained after drain: %v", slot.token) }
            }
            if len(retired) != len(survivors) || len(fenced) != len(survivors) {
                t.Errorf("retired=%v fenced=%v survivors=%v", retired, fenced, survivors)
            }
        })
    }
}

func TestIdleDrainNormalCollectedReachableAndCallbackCases(t *testing.T) {
    for _, kind := range []string{"collected", "reachable", "callback"} {
        t.Run(kind, func(t *testing.T) {
            token := [2]uint64{9, 1}
            current := &timer{isChan:kind!="callback", lsfToken:token, lsfSlot:1}
            lsfTimerSlots = []lsfTimerSlot{{token:token, weak:unsafe.Pointer(current)}}
            retired, fenced, stopHook = nil, nil, nil
            calls := 0
            conversion = func(p unsafe.Pointer) unsafe.Pointer {
                calls++
                if kind == "collected" && calls > 1 { return nil }
                return p
            }
            var failure interface{}
            func() { defer func(){ failure = recover() }(); lsfStopIdleChannelTimers() }()
            if kind == "callback" {
                if failure != "LSF callback timer remains during result seal" || current.stops != 0 || lsfTimerSlots[0].token != token {
                    t.Fatalf("callback failure=%v timer=%+v slots=%v", failure, current, lsfTimerSlots)
                }
                return
            }
            wantStops := 0
            if kind == "reachable" { wantStops = 1 }
            if failure != nil || current.stops != wantStops || len(retired)!=1 || retired[0]!=token || len(fenced)!=1 || fenced[0]!=token {
                t.Fatalf("failure=%v stops=%d retired=%v fenced=%v", failure, current.stops, retired, fenced)
            }
        })
    }
}

func TestIdleDrainRevisitsEarlierSlotReusedDuringLaterFence(t *testing.T) {
    first, second, replacement := [2]uint64{10, 1}, [2]uint64{10, 2}, [2]uint64{10, 3}
    a := &timer{isChan:true, lsfToken:first, lsfSlot:1}
    b := &timer{isChan:true, lsfToken:second, lsfSlot:2}
    c := &timer{isChan:true, lsfToken:replacement, lsfSlot:1}
    lsfTimerSlots = []lsfTimerSlot{{token:first, weak:unsafe.Pointer(a)}, {token:second, weak:unsafe.Pointer(b)}}
    retired, fenced, stopHook = nil, nil, nil
    conversion = func(p unsafe.Pointer) unsafe.Pointer { return p }
    fenceHook = func(token [2]uint64) {
        if token == second { lsfTimerSlots[0] = lsfTimerSlot{token:replacement, weak:unsafe.Pointer(c)} }
    }
    defer func(){ fenceHook = nil }()
    lsfStopIdleChannelTimers()
    if a.stops != 1 || b.stops != 1 || c.stops != 1 || len(retired) != 3 || len(fenced) != 3 || lsfTimerSlots[0].token[1] != 0 {
        t.Fatalf("stops=%d,%d,%d retired=%v fenced=%v slot=%v", a.stops, b.stops, c.stops, retired, fenced, lsfTimerSlots[0].token)
    }
}

func TestIdleDrainFailsClosedOnUnexpectedStopIdentityChange(t *testing.T) {
    old, next := [2]uint64{11, 1}, [2]uint64{11, 2}
    current := &timer{isChan:true, lsfToken:old, lsfSlot:1}
    lsfTimerSlots = []lsfTimerSlot{{token:old, weak:unsafe.Pointer(current)}}
    retired, fenced = nil, nil
    conversion = func(p unsafe.Pointer) unsafe.Pointer { return p }
    stopHook = func(t *timer) {
        lsfStopTimerSlot(1, old)
        t.lsfToken = next
        lsfTimerSlots[0] = lsfTimerSlot{token:next, weak:unsafe.Pointer(t)}
        retired = nil
    }
    var failure interface{}
    func() { defer func(){ failure = recover() }(); lsfStopIdleChannelTimers() }()
    stopHook = nil
    if failure != "LSF idle timer identity changed during stop" || lsfTimerSlots[0].token != next || len(retired)!=0 || len(fenced)!=0 {
        t.Fatalf("failure=%v slot=%v retired=%v fenced=%v", failure, lsfTimerSlots[0].token, retired, fenced)
    }
}

func TestIdleDrainFailsClosedOnEndlessSlotChurn(t *testing.T) {
    token := [2]uint64{13, 1}
    current := &timer{isChan:true, lsfToken:token, lsfSlot:1}
    lsfTimerSlots = []lsfTimerSlot{{token:token, weak:unsafe.Pointer(current)}}
    retired, fenced, stopHook = nil, nil, nil
    calls := 0
    conversion = func(p unsafe.Pointer) unsafe.Pointer {
        calls++
        if calls == 1 { return p }
        old := current.lsfToken
        lsfStopTimerSlot(1, old)
        lsfActivationTimerFence(old[0], old[1])
        current.lsfToken = [2]uint64{old[0], old[1]+1}
        lsfTimerSlots[0] = lsfTimerSlot{token:current.lsfToken, weak:p}
        return nil
    }
    var failure interface{}
    func() { defer func(){ failure = recover() }(); lsfStopIdleChannelTimers() }()
    if failure != "LSF idle timer drain did not settle" || calls != 8194 || lsfTimerSlots[0].token != current.lsfToken || current.stops != 0 {
        t.Fatalf("failure=%v calls=%d slot=%v current=%+v", failure, calls, lsfTimerSlots[0].token, current)
    }
}
'''

# The actual publisher is compiled unchanged. Only the installer's allocation
# is replaced with an equivalent make plus an optional test pause, modeling the
# GC-assist suspension allowed at allocation rather than claiming a real pause.
SLOT_INSTALL_TEST = r'''package timerowner

import (
    "testing"
    "unsafe"
)

var lsfTimerSlots []lsfTimerSlot
var lsfTimerCallbacks uint32
var allocationHook func(int, [2]uint64)
type timer struct { isChan bool; lsfToken [2]uint64; lsfSlot uint32 }
func lsfFail(message string) { panic(message) }
func internal_weak_runtime_registerWeakPointer(p unsafe.Pointer) unsafe.Pointer { return p }
func controlledTimerSlots(size int, token [2]uint64) []lsfTimerSlot {
    if allocationHook != nil { allocationHook(size, token) }
    return make([]lsfTimerSlot, size)
}
func assertInstalled(t *testing.T, selected *timer, token [2]uint64) {
    t.Helper()
    if selected.lsfToken != token || selected.lsfSlot == 0 || int(selected.lsfSlot) > len(lsfTimerSlots) {
        t.Fatalf("timer identity=%+v slots=%v", selected, lsfTimerSlots)
    }
    slot := lsfTimerSlots[selected.lsfSlot-1]
    if slot.token != token || slot.weak != unsafe.Pointer(selected) || slot.callback == selected.isChan {
        t.Fatalf("selected slot=%+v timer=%+v", slot, selected)
    }
}

func TestInstallRetriesWhenAnotherOwnerPublishesDuringAllocation(t *testing.T) {
    lsfTimerSlots, lsfTimerCallbacks = nil, 0
    first, second := &timer{isChan:true}, &timer{isChan:false}
    firstToken, secondToken := [2]uint64{1,1}, [2]uint64{1,2}
    parked, resume, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
    paused := false
    allocationHook = func(_ int, token [2]uint64) {
        if token == firstToken && !paused { paused = true; close(parked); <-resume }
    }
    defer func(){ allocationHook = nil }()
    go func(){ lsfInstallTimer(first, firstToken); close(done) }()
    <-parked
    lsfInstallTimer(second, secondToken)
    assertInstalled(t, second, secondToken)
    close(resume); <-done
    assertInstalled(t, first, firstToken)
    assertInstalled(t, second, secondToken)
    if len(lsfTimerSlots)!=2 || first.lsfSlot==second.lsfSlot || lsfTimerCallbacks!=1 {
        t.Fatalf("slots=%v first=%+v second=%+v callbacks=%d", lsfTimerSlots, first, second, lsfTimerCallbacks)
    }
}

func TestInstallReusesSlotFreedDuringAllocation(t *testing.T) {
    previous, next := [2]uint64{2,1}, [2]uint64{2,2}
    existing, selected := &timer{isChan:true}, &timer{isChan:true}
    lsfTimerSlots = []lsfTimerSlot{{token:previous, weak:unsafe.Pointer(existing)}}
    lsfTimerCallbacks = 0
    parked, resume, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
    allocationHook = func(_ int, token [2]uint64) {
        if token == next { close(parked); <-resume }
    }
    defer func(){ allocationHook = nil }()
    go func(){ lsfInstallTimer(selected, next); close(done) }()
    <-parked
    // Model the existing owner's confirmed retirement before the slot is free.
    lsfTimerSlots[0] = lsfTimerSlot{}
    close(resume); <-done
    assertInstalled(t, selected, next)
    if len(lsfTimerSlots)!=1 || selected.lsfSlot!=1 { t.Fatalf("unexpected growth: %v", lsfTimerSlots) }
}

func TestInstallRetriesAfterSeveralConcurrentGrowths(t *testing.T) {
    lsfTimerSlots, lsfTimerCallbacks = nil, 0
    a, b, c := &timer{isChan:true}, &timer{isChan:false}, &timer{isChan:false}
    one, two, three := [2]uint64{3,1}, [2]uint64{3,2}, [2]uint64{3,3}
    parked, resume, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
    paused := false
    allocationHook = func(_ int, token [2]uint64) {
        if token == one && !paused { paused = true; close(parked); <-resume }
    }
    defer func(){ allocationHook = nil }()
    go func(){ lsfInstallTimer(a, one); close(done) }()
    <-parked
    lsfInstallTimer(b, two)
    lsfInstallTimer(c, three)
    close(resume); <-done
    assertInstalled(t, a, one); assertInstalled(t, b, two); assertInstalled(t, c, three)
    if len(lsfTimerSlots)!=3 || a.lsfSlot==b.lsfSlot || a.lsfSlot==c.lsfSlot || b.lsfSlot==c.lsfSlot || lsfTimerCallbacks!=2 {
        t.Fatalf("slots=%v callbacks=%d", lsfTimerSlots, lsfTimerCallbacks)
    }
}

func TestInstallFailsClosedIfInventoryExceedsHostBound(t *testing.T) {
    lsfTimerSlots, lsfTimerCallbacks, allocationHook = make([]lsfTimerSlot, 8192), 0, nil
    for i := range lsfTimerSlots { lsfTimerSlots[i].token = [2]uint64{4, uint64(i+1)} }
    selected := &timer{isChan:true}
    var failure interface{}
    func(){ defer func(){ failure = recover() }(); lsfInstallTimer(selected, [2]uint64{4,8193}) }()
    if failure != "LSF timer inventory capacity exhausted" || selected.lsfSlot!=0 ||
        len(lsfTimerSlots)!=8192 || lsfTimerSlots[0].token != [2]uint64{4,1} || lsfTimerSlots[8191].token != [2]uint64{4,8192} {
        t.Fatalf("failure=%v timer=%+v", failure, selected)
    }
}
'''

# The dispatcher functions are copied from the runtime template. The two
# injected hooks only pause allocation or channel receive at the indicated
# boundary; host readiness and physical retirement are controlled stubs.
READINESS_PUBLICATION_TEST = r'''package timerwait

import (
    "runtime"
    "testing"
    "unsafe"
)

type unit struct{}
type stateType struct { timerWaits []*lsfTimerWait; waitableSet uint32 }
var state *stateType
const (STATUS_STARTING uint32 = 0; STATUS_STARTED uint32 = 1; STATUS_RETURNED uint32 = 2)
type allocator struct{}
func (allocator) Allocate(_ *runtime.Pinner, _, _ int) unsafe.Pointer { return unsafe.Pointer(new([16]byte)) }
var witRuntime allocator
var selected [2]uint64
var status uint32
var hostStarts int
var physicalPending bool
var lastStarted *lsfTimerWait
var appendHook, receiveHook func()
var nextHook func(int)
var nextCalls int
func lsfNextTimer() (uint64, uint64) {
    nextCalls++
    if nextHook != nil { nextHook(nextCalls) }
    return selected[0], selected[1]
}
func lsfTimerNext(_, _ int64, _ unsafe.Pointer) uint32 {
    hostStarts++
    lastStarted = state.timerWaits[len(state.timerWaits)-1]
    physicalPending = status == STATUS_STARTING || status == STATUS_STARTED
    if physicalPending { return 42<<4 | status }
    return status
}
func waitableSetNew() uint32 { return 7 }
func waitableJoin(_, _ uint32) {}
func subtaskDrop(_ uint32) { physicalPending = false }
func controlledWaitAppend(old []*lsfTimerWait, wait *lsfTimerWait) []*lsfTimerWait {
    if appendHook != nil { appendHook() }
    return append(old, wait)
}
func controlledFenceReceive(wait *lsfTimerWait) {
    if receiveHook != nil { receiveHook() }
    (<-wait.done)
}
func reset() {
    state = &stateType{}
    selected = [2]uint64{1,1}
    status, hostStarts, physicalPending, lastStarted = STATUS_STARTED, 0, false, nil
    appendHook, receiveHook = nil, nil
    nextHook, nextCalls = nil, 0
}
func cancelled(wait *lsfTimerWait) {
    *(*byte)(wait.result) = 1
    *(*byte)(unsafe.Add(wait.result, 8)) = 3
}

func TestStopWhilePublicationAllocatesDoesNotStartAStaleSubtask(t *testing.T) {
    reset()
    parked, resume, done := make(chan struct{}), make(chan struct{}), make(chan bool, 1)
    appendHook = func(){ close(parked); <-resume }
    go func(){ done <- lsfStartTimerWait() }()
    <-parked
    pendingBeforePublication := physicalPending
    lsfActivationTimerStopped(1,1)
    selected = [2]uint64{} // The original host timer has been stopped.
    lsfActivationTimerFence(1,1)
    close(resume)
    refreshed := <-done
    if pendingBeforePublication || hostStarts != 0 || !refreshed || len(state.timerWaits)!=0 {
        t.Fatalf("pending=%v starts=%d refresh=%v inventory=%d", pendingBeforePublication, hostStarts, refreshed, len(state.timerWaits))
    }
}

func TestChangedSelectionIsRetriedBeforeHostAdmission(t *testing.T) {
    reset()
    parked, resume, done := make(chan struct{}), make(chan struct{}), make(chan bool, 1)
    appendHook = func(){ close(parked); <-resume }
    go func(){ done <- lsfStartTimerWait() }()
    <-parked
    selected = [2]uint64{1,2}
    close(resume)
    refreshed := <-done
    if hostStarts!=0 || !refreshed || len(state.timerWaits)!=0 { t.Fatalf("starts=%d refresh=%v inventory=%v", hostStarts, refreshed, state.timerWaits) }
}

func TestStopAfterPublicationWaitsForUnstartedRecordRetirement(t *testing.T) {
    reset()
    parked, resume, started, fenced := make(chan struct{}), make(chan struct{}), make(chan bool,1), make(chan struct{})
    nextHook = func(call int) { if call==2 { close(parked); <-resume } }
    go func(){ started <- lsfStartTimerWait() }()
    <-parked
    if len(state.timerWaits)!=1 || hostStarts!=0 { t.Fatal("unstarted publication not visible") }
    lsfActivationTimerStopped(1,1)
    selected = [2]uint64{}
    go func(){ lsfActivationTimerFence(1,1); close(fenced) }()
    runtime.Gosched()
    select { case <-fenced: t.Fatal("fence returned before the unstarted record retired"); default: }
    close(resume)
    if refreshed := <-started; !refreshed { t.Fatal("stale selection did not request refresh") }
    <-fenced
    if hostStarts!=0 || physicalPending || len(state.timerWaits)!=0 { t.Fatal("stopped unstarted record leaked") }
}

func TestStoppedPendingWaitFencesUntilPhysicalSubtaskDrop(t *testing.T) {
    reset()
    if lsfStartTimerWait() || !physicalPending || len(state.timerWaits)!=1 { t.Fatal("pending setup") }
    wait := state.timerWaits[0]
    lsfActivationTimerStopped(1,1)
    cancelled(wait)
    fenced := make(chan struct{})
    go func(){ lsfActivationTimerFence(1,1); close(fenced) }()
    runtime.Gosched()
    select { case <-fenced: t.Fatal("fence returned while subtask remained pending"); default: }
    if !lsfHandleTimerEvent(42) { t.Fatal("pending event not handled") }
    <-fenced
    if physicalPending || len(state.timerWaits)!=0 { t.Fatalf("pending=%v waits=%v", physicalPending, state.timerWaits) }
}

func TestCompletionBeforeFenceReceiveRemainsVisible(t *testing.T) {
    reset()
    lsfStartTimerWait()
    wait := state.timerWaits[0]
    lsfActivationTimerStopped(1,1)
    cancelled(wait)
    parked, resume, fenced := make(chan struct{}), make(chan struct{}), make(chan struct{})
    receiveHook = func(){ close(parked); <-resume }
    go func(){ lsfActivationTimerFence(1,1); close(fenced) }()
    <-parked
    if !lsfHandleTimerEvent(42) { t.Fatal("pending event not handled") }
    close(resume)
    <-fenced
    if physicalPending || len(state.timerWaits)!=0 { t.Fatalf("pending=%v waits=%v", physicalPending, state.timerWaits) }
}

func TestImmediateCompletionRemovesAndClosesWait(t *testing.T) {
    reset()
    status = STATUS_RETURNED
    if !lsfStartTimerWait() || hostStarts!=1 || physicalPending || len(state.timerWaits)!=0 { t.Fatal("synchronous result not retired") }
    select { case <-lastStarted.done: default: t.Fatal("synchronous completion not visible to fence") }
}

func TestUnstartedWaitCannotConsumeAnotherSubtaskEvent(t *testing.T) {
    reset()
    wait := &lsfTimerWait{token:[2]uint64{1,1}, done:make(chan unit)}
    state.timerWaits = []*lsfTimerWait{wait}
    if lsfHandleTimerEvent(0) || len(state.timerWaits)!=1 || state.timerWaits[0]!=wait {
        t.Fatal("unstarted timer wait consumed an unrelated event")
    }
}

func TestUnstoppedReadinessFailureStillTraps(t *testing.T) {
    reset()
    lsfStartTimerWait()
    wait := state.timerWaits[0]
    *(*byte)(wait.result) = 1
    *(*byte)(unsafe.Add(wait.result,8)) = 6
    var failure interface{}
    func(){ defer func(){ failure=recover() }(); lsfHandleTimerEvent(42) }()
    if failure != "LSF timer readiness failed or root deadline won" { t.Fatalf("failure=%v", failure) }
}
'''


class SourceOnlyCompiler:
    def __init__(self, *_args, **_kwargs):
        self.materials = []

    def compile(self, _source, _wit, _world, output, **_kwargs):
        (output / 'runtime-overlay').mkdir(parents=True)
        (output / 'runtime-overlay/overlay.json').write_bytes(b'{"Replace":{}}')
        component = output / 'component.wasm'
        component.write_bytes(b'unit-test-input-only-no-native-execution')
        return component, {}


def rows():
    return [{'case': case, 'iteration': iteration, 'mode': mode, 'outcome': outcome}
            for case, iteration, mode, outcome in reference.MANAGED_TIMER_ROWS]


def output(values, filtered=50):
    records = '\n'.join('GO_MANAGED_TIMER_CASE ' + json.dumps(row) for row in values)
    return (f'test {reference.MANAGED_TIMER_CASE} ... ok\n{records}\n'
            f'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; {filtered} filtered out; finished in 6.00s\n').encode()


def compile_record(folder):
    source = (reference.ROOT / 'sdk/go-guest/runtime/timers-conformance/main.go').read_bytes()
    (folder / 'src').mkdir()
    (folder / 'src/main.go').write_bytes(source)
    (folder / 'build').mkdir()
    component = b'unit-test-source-control-only'
    (folder / 'build/component.wasm').write_bytes(component)
    return {'profile': 'go-component-activation-v5', 'fixture': 'timers',
            'sourceDigest': 'sha256:' + reference.digest(source), 'sourceUnchanged': True,
            'ordinarySource': True, 'signedExecution': 'not-run',
            'componentDigest': 'sha256:' + reference.digest(component),
            'bindingDigest': 'sha256:' + 'a' * 64, 'tools': [], 'transformations': [],
            'nativeReference': {'modes': NATIVE17, 'output': 42, 'freshProcessPerMode': True,
                                'sourceDigest': 'sha256:' + reference.digest(source)}}


class GoManagedTimers(unittest.TestCase):
    @unittest.skipUnless(shutil.which('go'), 'controlled host interleaving requires Go')
    def test_timer_readiness_is_published_before_host_start_and_fenced_until_drop(self):
        source = (reference.ROOT / 'sdk/go-guest/runtime/timer_async.go.in').read_text()
        start = source.index('type lsfTimerWait struct {')
        declaration = source[start:source.index('\n}', start) + 2]
        functions = []
        for name in ('lsfActivationTimerStopped', 'lsfActivationTimerFence', 'lsfCompleteTimerWait',
                     'lsfRemoveTimerWait', 'lsfHandleTimerEvent', 'lsfStartTimerWait'):
            start = source.index('func ' + name + '(')
            functions.append(source[start:source.index('\n}', start) + 2])
        receive, allocation = '(<-wait.done)', 'append(state.timerWaits, wait)'
        self.assertEqual(functions[1].count(receive), 1)
        self.assertEqual(functions[-1].count(allocation), 1)
        functions[1] = functions[1].replace(receive, 'controlledFenceReceive(wait)')
        functions[-1] = functions[-1].replace(allocation, 'controlledWaitAppend(state.timerWaits, wait)')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'wait.go').write_text('package timerwait\n\nimport ("runtime"; "unsafe")\n\n' +
                                          declaration + '\n\n' + '\n\n'.join(functions) + '\n')
            (root / 'wait_test.go').write_text(READINESS_PUBLICATION_TEST)
            env = dict(os.environ, GO111MODULE='off', GOENV='off', GOFLAGS='', GOWORK='off',
                       GOTOOLCHAIN='local', GOMAXPROCS='1', GOOS='', GOARCH='', CGO_ENABLED='0')
            env.pop('GOROOT', None)
            result = subprocess.run([shutil.which('go'), 'test', '-count=1', '-timeout=45s', '-v', '.'],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('go'), 'controlled host interleaving requires Go')
    def test_timer_installation_rechecks_inventory_after_allocation_parking(self):
        source = (reference.ROOT / 'sdk/go-guest/runtime/timer_bridge.go.in').read_text()
        declaration = next(line for line in source.splitlines() if line.startswith('type lsfTimerSlot struct '))
        functions = []
        for signature in ('func lsfInstallTimer(', '//go:nosplit\nfunc lsfPublishTimer('):
            start = source.index(signature)
            end = source.index('\n}', start) + 2
            functions.append(source[start:end])
        allocation = 'make([]lsfTimerSlot, capacity)'
        self.assertEqual(functions[0].count(allocation), 1)
        functions[0] = functions[0].replace(allocation, 'controlledTimerSlots(capacity, token)')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'timer.go').write_text('package timerowner\n\nimport "unsafe"\n\n' +
                                           declaration + '\n\n' + '\n\n'.join(functions) + '\n')
            (root / 'timer_test.go').write_text(SLOT_INSTALL_TEST)
            env = dict(os.environ, GO111MODULE='off', GOENV='off', GOFLAGS='', GOWORK='off',
                       GOTOOLCHAIN='local', GOMAXPROCS='1', GOOS='', GOARCH='', CGO_ENABLED='0')
            env.pop('GOROOT', None)
            result = subprocess.run([shutil.which('go'), 'test', '-count=1', '-timeout=45s', '-v', '.'],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('go'), 'controlled host interleaving requires Go')
    def test_collected_timer_sweep_retains_original_identity_across_gc_parking(self):
        source = (reference.ROOT / 'sdk/go-guest/runtime/timer_bridge.go.in').read_text()
        declaration = next(line for line in source.splitlines() if line.startswith('type lsfTimerSlot struct '))
        functions = []
        for name in ('lsfSweepCollectedTimers', 'lsfRetireTimer', 'lsfStopIdleChannelTimers'):
            start = source.index('func ' + name + '(')
            end = source.index('\n}', start) + 2
            functions.append(source[start:end])
        constants = '\n'.join(line for line in source.splitlines() if line.startswith('const lsfTimerDrainPassLimit '))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'timer.go').write_text('package timerowner\n\nimport "unsafe"\n\n' +
                                           declaration + '\n' + constants + '\n\n' + '\n\n'.join(functions) + '\n')
            (root / 'timer_test.go').write_text(SLOT_INTERLEAVING_TEST)
            env = dict(os.environ, GO111MODULE='off', GOENV='off', GOFLAGS='', GOWORK='off',
                       GOTOOLCHAIN='local', GOMAXPROCS='1', GOOS='', GOARCH='', CGO_ENABLED='0')
            env.pop('GOROOT', None)
            result = subprocess.run([shutil.which('go'), 'test', '-count=1', '-timeout=45s', '-v', '.'],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_v5_timer_compile_records_native_reference_on_the_same_unmodified_timer_source(self):
        source = (reference.ROOT / 'sdk/go-guest/runtime/timers-conformance/main.go').read_bytes()
        native = {'modes': NATIVE17, 'output': 42, 'freshProcessPerMode': True,
                  'sourceDigest': 'sha256:' + reference.digest(source)}
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(activation, 'Compiler', SourceOnlyCompiler), \
                patch.object(activation, 'stage'), \
                patch.object(activation, 'fixture_reference', return_value=native) as observe:
            folder = Path(temporary) / 'capture'
            record = activation.compile_fixture(folder, runtime_profile='go-component-activation-v5', fixture='timers')
            self.assertIn('nativeReference', record)
            self.assertEqual(record['nativeReference'], native)
            observe.assert_called_once()
            self.assertEqual(observe.call_args.args[-2:], (source, 'timers'))
            self.assertEqual((folder / 'src/main.go').read_bytes(), source)
            self.assertTrue(record['sourceUnchanged'])
            self.assertEqual(record['signedExecution'], 'not-run')

    def test_legacy_v3_reference_capture_remains_selected_and_not_relabelled(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(activation, 'Compiler', SourceOnlyCompiler), \
                patch.object(activation, 'stage'), \
                patch.object(activation, 'fixture_reference', return_value={'modes': NATIVE17}) as observe:
            record = activation.compile_fixture(Path(temporary) / 'legacy',
                                                 runtime_profile='go-component-activation-v3', fixture='timers')
            observe.assert_called_once()
            self.assertEqual(record['profile'], 'go-component-activation-v3')
            self.assertEqual(record['nativeReference']['modes'], NATIVE17)

    def test_exact_v5_timer_source_profile_and_all_seventeen_native_modes_are_required(self):
        self.assertEqual(reference.TIMER_NATIVE_MODES, NATIVE17)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            record = compile_record(folder)
            path = folder / 'GO-ACTIVATION-COMPILE.json'
            path.write_bytes(json.dumps(record).encode())
            actual = reference.compile_identity(folder, reference.ROOT, 'go-component-activation-v5', 'timers')
            self.assertEqual(actual['sourceDigest'], record['sourceDigest'])
            for key, value in [('profile', 'go-component-activation-v3'), ('fixture', 'managed-idle'),
                               ('sourceUnchanged', False), ('signedExecution', 'passed')]:
                changed = copy.deepcopy(record)
                changed[key] = value
                path.write_bytes(json.dumps(changed).encode())
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'source-or-profile'):
                    reference.compile_identity(folder, reference.ROOT, 'go-component-activation-v5', 'timers')
            for key, value in [('modes', [0, 1, 2]), ('modes', NATIVE17[:-1]),
                               ('freshProcessPerMode', False), ('output', 0), ('sourceDigest', 'sha256:' + 'b' * 64)]:
                changed = copy.deepcopy(record)
                changed['nativeReference'][key] = value
                path.write_bytes(json.dumps(changed).encode())
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'native-reference'):
                    reference.compile_identity(folder, reference.ROOT, 'go-component-activation-v5', 'timers')

    def test_unknown_or_v3_profile_cannot_substitute_for_the_closed_managed_timer_campaign(self):
        fixture = Path('owned-timer-capture')
        self.assertEqual(reference.campaign('managed-timers', fixture, None),
                         {'case': reference.MANAGED_TIMER_CASE, 'fixture': 'timers',
                          'variable': 'LSF_GO_MANAGED_TIMER_FIXTURE', 'inputs': [(fixture, 'go-component-activation-v5')]})
        with self.assertRaisesRegex(ValueError, 'unreviewed-campaign-or-negative'):
            reference.campaign('managed-timers', fixture, Path('legacy-v3'))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            record = compile_record(folder)
            (folder / 'GO-ACTIVATION-COMPILE.json').write_bytes(json.dumps(record).encode())
            with self.assertRaisesRegex(ValueError, 'unreviewed-source-profile'):
                reference.compile_identity(folder, reference.ROOT, 'go-component-activation-v3', 'timers')

    def test_all_forty_three_original_outcomes_cover_stop_reset_overlap_gc_and_retirement(self):
        values = rows()
        self.assertEqual(len(values), 43)
        self.assertEqual(reference.managed_timer_observations(output(values), 50), values)
        expected = {0, 1, 2, 3, 4, 5, 6, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20}
        for iteration in (0, 1):
            self.assertEqual({r['mode'] for r in values if r['case'] == 'ordinary' and r['iteration'] == iteration}, expected)
        self.assertEqual([(r['case'], r['outcome']) for r in values[36:]],
                         [('timer-capacity', 'guest-trap'), ('fresh-after-timer-capacity', 'success'),
                          ('callback-failure', 'guest-trap'), ('fresh-after-callback-failure', 'success'),
                          ('cancel-original-root', 'cancelled'), ('deadline-original-root', 'deadline-exceeded'),
                          ('fresh-after-cancel-deadline', 'success')])

    def test_missing_duplicate_reordered_and_fake_elapsed_or_capacity_success_are_rejected(self):
        wrong = rows()
        wrong[-2]['outcome'] = 'success'
        capacity = rows()
        capacity[36]['outcome'] = 'success'
        for values in [rows()[:-1], rows() + rows()[:1], list(reversed(rows())), wrong, capacity]:
            with self.subTest(last=values[-1]), self.assertRaisesRegex(ValueError, 'missing-or-extra|invocation-contract'):
                reference.managed_timer_observations(output(values), 50)

    def test_private_unknown_boolean_and_unbounded_iteration_fields_fail_closed(self):
        for key, value in [('private', 'not-exported'), ('iteration', True), ('mode', False),
                           ('iteration', 2**64), ('outcome', 'invented'), ('case', 'unknown')]:
            values = rows()
            values[0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'private-or-unknown|invocation-contract'):
                reference.managed_timer_observations(output(values), 50)

    def test_wrapper_success_other_target_or_ignored_cases_cannot_qualify_managed_timers(self):
        raw = output(rows())
        for old, new in [(reference.MANAGED_TIMER_CASE.encode(), reference.CASE.encode()),
                         (b'0 ignored', b'1 ignored'), (b'50 filtered', b'49 filtered'),
                         (b'1 passed', b'2 passed'), (b'GO_MANAGED_TIMER_CASE', b'GO_SYNCHRONIZATION_CASE')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                reference.managed_timer_observations(raw.replace(old, new), 50)
        with self.assertRaisesRegex(ValueError, 'output-bound'):
            reference.managed_timer_observations(b'x' * (2 * 1024 * 1024 + 1), 50)


if __name__ == '__main__':
    unittest.main()
