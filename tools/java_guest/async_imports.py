"""Heap-held canonical imports and one activation-local readiness set.

The caller retains its Wait owner and Java argument pins until take() destroys
the actual terminal subtask. Only internal value-only runtime waits may cancel.
This generator is not selected by the existing synchronous Java profile.
"""
from __future__ import annotations

import copy

from tools.java_guest import c
from tools.java_guest.model import Graph


def cancellable(graph: Graph, function: dict) -> bool:
    interface = graph.data['interfaces'][function['interface']]
    package = graph.data['packages'][interface['package']]['name']
    return (package == 'latent:runtime@0.1.0' and interface['name'] == 'activation'
            and function['name'] in {'wait-for', 'timer-next'})


def contains_resource(graph: Graph, value, seen: frozenset[int] = frozenset()) -> bool:
    if value is None or isinstance(value, str): return False
    if value in seen: raise ValueError('recursive Java asynchronous cancellation type')
    kind = graph.types[value]['kind']
    if kind == 'resource': return True
    form, body = next(iter(kind.items()))
    if form == 'handle': return True
    if form in {'type', 'option', 'list'}: children = [body]
    elif form in {'record', 'variant'}:
        children = [member['type'] for member in body['fields' if form == 'record' else 'cases']]
    elif form == 'tuple': children = body['types']
    elif form == 'result': children = list(body.values())
    elif form in {'flags', 'enum'}: children = []
    else: raise ValueError('unsupported Java asynchronous cancellation type')
    return any(contains_resource(graph, child, seen | {value}) for child in children)


def generate(graph: Graph) -> str:
    selected = [function for function in graph.imports if function.get('asyncLowered')]
    if not selected:
        raise ValueError('Java pending-call bridge requires actual asynchronous C imports')
    sync = copy.copy(graph)
    sync.imports = [function for function in graph.imports if not function.get('asyncLowered')]
    output = [c.generate(sync), '''
__attribute__((import_module("$root"), import_name("[async-lower][subtask-cancel]")))
extern uint32_t lsf_subtask_cancel_async(uint32_t handle);

typedef struct lsf_async_call lsf_async_call;
struct lsf_async_call {
    lsf_async_call *next;
    uint32_t operation;
    probe_subtask_status_t status;
    bool joined;
    bool has_subtask;
    union {''']
    for function in selected:
        output.append('struct {')
        for index, parameter in enumerate(function['cParams'][:len(function['params'])]):
            output.append(parameter['type'] + ' arg' + str(index) + ';')
        if function.get('result') is not None:
            output.append(function['cParams'][-1]['type'] + ' result;')
        if not function['params'] and function.get('result') is None:
            output.append('uint8_t unused;')
        output.append('} op' + str(function['operation']) + ';')
    output.append('''} data;
};
static lsf_async_call *lsf_async_calls;
static uint32_t lsf_async_count;
static probe_waitable_set_t lsf_async_set;
static bool lsf_async_set_exists;

static lsf_async_call *lsf_async_checked(void *address) {
    for (lsf_async_call *call = lsf_async_calls; call; call = call->next)
        if (call == address) return call;
    __builtin_trap();
}

static void lsf_async_event(probe_event_t *event) {
    if (event->event == PROBE_EVENT_NONE) return;
    lsf_require(event->event == PROBE_EVENT_SUBTASK && event->code <= PROBE_SUBTASK_RETURNED_CANCELLED);
    for (lsf_async_call *call = lsf_async_calls; call; call = call->next) {
        if (PROBE_SUBTASK_HANDLE(call->status) == event->waitable) {
            lsf_require(PROBE_SUBTASK_STATE(call->status) < PROBE_SUBTASK_RETURNED);
            call->status = (event->waitable << 4) | event->code;
            return;
        }
    }
    __builtin_trap();
}

void *lsf_java_async_begin(int32_t operation, void *bytes, int32_t length) {
    lsf_require(length >= 0 && (uint32_t)length <= LSF_MAX_BYTES && lsf_async_count < 64);
    lsf_async_call *call = lsf_allocate(1, sizeof(*call));
    memset(call, 0, sizeof(*call));
    call->operation = (uint32_t)operation;
    lsf_wire input = {bytes, (size_t)length, 0, (size_t)length};
    switch (operation) {''')
    codec = c.Codec(graph)
    for function in selected:
        prefix = 'call->data.op' + str(function['operation'])
        arguments = []
        output.append('case ' + str(function['operation']) + ': {')
        for index, (parameter, native) in enumerate(zip(function['params'], function['cParams'])):
            member = prefix + '.arg' + str(index)
            output.extend(codec.emit(parameter['type'], member, 'read', '&input'))
            arguments.append(('&' if native['pointer'] else '') + member)
        output.append('lsf_finish(&input);')
        if function.get('result') is not None: arguments.append('&' + prefix + '.result')
        output.append('call->status = ' + function['symbol'] + '(' + ', '.join(arguments) + '); break; }')
    output.append('''default: __builtin_trap();
    }
    lsf_require(PROBE_SUBTASK_STATE(call->status) <= PROBE_SUBTASK_RETURNED);
    call->next = lsf_async_calls; lsf_async_calls = call; lsf_async_count++;
    if (PROBE_SUBTASK_STATE(call->status) != PROBE_SUBTASK_RETURNED) {
        call->has_subtask = true;
        if (!lsf_async_set_exists) {
            lsf_async_set = probe_waitable_set_new(); lsf_async_set_exists = true;
        }
        probe_waitable_join(PROBE_SUBTASK_HANDLE(call->status), lsf_async_set);
        call->joined = true;
    }
    return call;
}

int32_t lsf_java_async_state(void *address) {
    return (int32_t)PROBE_SUBTASK_STATE(lsf_async_checked(address)->status);
}

void lsf_java_async_poll(void) {
    if (!lsf_async_set_exists) return;
    probe_event_t event = {0};
    probe_waitable_set_poll(lsf_async_set, &event); lsf_async_event(&event);
}

void lsf_java_async_wait(void) {
    lsf_require(lsf_async_set_exists && lsf_async_count != 0);
    bool pending = false;
    for (lsf_async_call *call = lsf_async_calls; call; call = call->next)
        if (call->joined && PROBE_SUBTASK_STATE(call->status) < PROBE_SUBTASK_RETURNED) pending = true;
    lsf_require(pending);
    probe_event_t event = {0};
    probe_waitable_set_wait(lsf_async_set, &event); lsf_async_event(&event);
}

int32_t lsf_java_async_cancel_root_wait(void *address) {
    lsf_async_call *call = lsf_async_checked(address);
    switch (call->operation) {''')
    for function in selected:
        if cancellable(graph, function):
            # These runtime signatures contain only value records/options;
            # no transferred resource may be hidden by a cancellation result.
            if (any(contains_resource(graph, parameter['type']) for parameter in function['params'])
                    or contains_resource(graph, function.get('result'))):
                raise ValueError('internal Java wait cancellation cannot transfer resources')
            output.append('case ' + str(function['operation']) + ': break;')
    output.append('''default: __builtin_trap();
    }
    if (call->joined) {
        probe_waitable_join(PROBE_SUBTASK_HANDLE(call->status), 0); call->joined = false;
    }
    if (PROBE_SUBTASK_STATE(call->status) < PROBE_SUBTASK_RETURNED) {
        uint32_t observed = lsf_subtask_cancel_async(PROBE_SUBTASK_HANDLE(call->status));
        if (observed != UINT32_MAX) {
            lsf_require(observed >= PROBE_SUBTASK_RETURNED && observed <= PROBE_SUBTASK_RETURNED_CANCELLED);
            call->status = (PROBE_SUBTASK_HANDLE(call->status) << 4) | observed;
        }
    }
    if (PROBE_SUBTASK_STATE(call->status) < PROBE_SUBTASK_RETURNED) {
        probe_waitable_join(PROBE_SUBTASK_HANDLE(call->status), lsf_async_set);
        call->joined = true;
    }
    return (int32_t)PROBE_SUBTASK_STATE(call->status);
}

void *lsf_java_async_take(void *address, int32_t cancelled_root_wait) {
    lsf_async_call *call = lsf_async_checked(address);
    probe_subtask_state_t state = PROBE_SUBTASK_STATE(call->status);
    lsf_require(state == PROBE_SUBTASK_RETURNED
        || (cancelled_root_wait && state >= PROBE_SUBTASK_STARTED_CANCELLED && state <= PROBE_SUBTASK_RETURNED_CANCELLED));
    if (cancelled_root_wait) {
        switch (call->operation) {''')
    for function in selected:
        if cancellable(graph, function): output.append('case ' + str(function['operation']) + ': break;')
    output.append('''default: __builtin_trap();
        }
    }
    if (call->joined) probe_waitable_join(PROBE_SUBTASK_HANDLE(call->status), 0);
    if (call->has_subtask) probe_subtask_drop(PROBE_SUBTASK_HANDLE(call->status));
    lsf_wire output = {0};
    switch (call->operation) {''')
    for function in selected:
        prefix = 'call->data.op' + str(function['operation'])
        output.append('case ' + str(function['operation']) + ': {')
        for index, parameter in enumerate(function['params']):
            output.extend(codec.emit(parameter['type'], prefix + '.arg' + str(index), 'free', 'NULL'))
        if function.get('result') is not None:
            output.append('if (state == PROBE_SUBTASK_RETURNED) {')
            output.extend(codec.emit(function['result'], prefix + '.result', 'write', '&output'))
            output.extend(codec.emit(function['result'], prefix + '.result', 'free', 'NULL'))
            output.append('}')
        output.append('break; }')
    output.append('''default: __builtin_trap();
    }
    lsf_async_call **link = &lsf_async_calls;
    while (*link != call) { lsf_require(*link != NULL); link = &(*link)->next; }
    *link = call->next; lsf_async_count--; lsf_release(call, sizeof(*call));
    if (lsf_async_count == 0 && lsf_async_set_exists) {
        probe_waitable_set_drop(lsf_async_set); lsf_async_set_exists = false;
    }
    if (state != PROBE_SUBTASK_RETURNED) return NULL;
    return lsf_result(&output);
}
''')
    return '\n'.join(output)
