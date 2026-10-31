"""Isolate verified executor callbacks from the ordinary function table.

This is a source transform, not source/provenance authentication. Its owning
compiler must derive Targets/Sites from the complete authenticated object graph,
original constructor/Arc path and callback receiver ownership before enablement.
The output never certifies that remaining contract or enables a runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter

from tools import rust_thread_object_graph as graph


@dataclass(frozen=True)
class Target:
    slot: int
    function: int


@dataclass(frozen=True)
class Site:
    function: int
    offset: int
    slot: int
    source_fallback: bool = False


def derive_plan(core: bytes, observation: dict, *, std_library: str,
                executor_library: str) -> tuple[tuple[Target, ...], tuple[Site, ...], dict]:
    """Derive indices/sites from complete original bodies, never final names.

    These original symbol suffixes locate roles inside the owner-authenticated
    selected source libraries. All their bytes/references must already match.
    The owning compiler still has to bind that source catalogue/event and prove
    the original constructor/Arc/worker transfer before allowing execution.
    """
    graph.require(observation.get('coreDigest') == graph.digest(core)
                  and not observation.get('failures', [1])
                  and not observation.get('unresolvedReferents', [1])
                  and not observation.get('instructionDecodeFailures', [1])
                  and not observation.get('tableMutations', [1])
                  and all(row['callerBodyMatched'] for row in
                          observation.get('incomingPrivateReferences', [{'callerBodyMatched': False}])),
                  'rust-callback-original-observation-not-closed')
    bindings = observation.get('matchedBindings', [])
    graph.require(0 < len(bindings) <= graph.MAX_NODES, 'rust-callback-original-binding-bound')

    def role(library, suffix):
        rows = [row for row in bindings if row['kind'] == 0 and row['bodyMatched']
                and row['object'].startswith(library + '/')
                and row['originalSymbol'].split('.llvm.', 1)[0].endswith(suffix)]
        graph.require(len(rows) == 1, 'rust-callback-original-role-binding')
        return rows[0]

    roles = {
        'pool-progress': role(executor_library, '_9PoolState8progress'),
        'pool-release': role(executor_library, '_9PoolState7release'),
        'builder-create': role(executor_library, '_17ThreadPoolBuilder6create'),
        'root-progress': role(std_library, 'runtime13executor_root12progress_all'),
        'worker-release': role(std_library, 'runtime13executor_root14worker_release'),
        'worker-tls': role(std_library, 'runtime13executor_root18worker_tls_drained'),
        'worker-frames': role(std_library, 'runtime13executor_root20worker_frames_exited'),
        'reaper': role(std_library, 'runtime4reap'),
        'entered': role(std_library, 'runtime7entered'),
        'prepare': role(std_library, '__lsf_rust_pool_prepare'),
        'commit': role(std_library, '__lsf_rust_pool_commit'),
        'request': role(std_library, '__lsf_rust_pool_request'),
    }
    worker = [row for row in bindings if row['kind'] == 0 and row['bodyMatched']
              and row['object'].startswith(executor_library + '/')
              and '9PoolState17ensure_generation' in row['originalSymbol']
              and 'FnOnce' in row['originalSymbol'] and 'call_once6vtable' in row['originalSymbol']]
    graph.require(len(worker) == 1, 'rust-callback-original-worker-closure-binding')
    roles['worker-closure'] = worker[0]
    signatures, imports, bodies = graph.code(core)
    _, table, _ = graph.memory_table(core)
    types = graph.types(core)
    ops, operators = {}, 0
    for name, row in roles.items():
        index = row['actual']
        graph.require(len(imports) <= index < len(signatures), 'rust-callback-original-role-index')
        ops[name] = graph.bounded_instructions(bodies[index - len(imports)],
                                             graph.MAX_RELOCATIONS - operators)
        operators += len(ops[name])
    target_names = ('pool-progress', 'pool-release', 'worker-release', 'worker-frames', 'worker-tls')
    targets_by_name = {}
    for name in target_names:
        function = roles[name]['actual']
        slots = [slot for slot, value in table.items() if value == function]
        graph.require(len(slots) == 1, 'rust-callback-original-role-table-binding')
        targets_by_name[name] = Target(slots[0], function)

    def calls(name, expected):
        found = [(index, row) for index, row in enumerate(ops[name]) if row[1] == 17]
        graph.require(len(found) == len(expected), 'rust-callback-original-owner-indirect-count')
        for (_, (_, _, args)), signature in zip(found, expected):
            graph.require(0 <= args[0] < len(types) and args[1] == 0
                          and types[args[0]] == signature, 'rust-callback-original-owner-signature')
        return found

    progress = ((0x7f,), (0x7f,))
    release, notified = ((0x7f,), ()), ((0x7f, 0x7f), ())
    root = calls('root-progress', (progress, progress, release))
    # The actual selected enum branch explicitly distinguishes Captured1 from
    # genuine Source. Both progress branches preserve identical receiver/index
    # locals. The later shared release retains its Source fallback.
    first = root[0][0]
    branch = ops['root-progress'][first - 6:first]
    graph.require(len(branch) == 6 and [row[1] for row in branch] == [32, 65, 71, 13, 32, 32]
                  and branch[1][2] == [1] and branch[3][2] == [0]
                  and [(op, args) for _, op, args in branch[-2:]] ==
                      [(op, args) for _, op, args in ops['root-progress'][root[1][0] - 2:root[1][0]]],
                  'rust-callback-original-captured-source-branch')
    owners = [
        ('root-progress', root[0], 'pool-progress', False),
        ('root-progress', root[2], 'pool-release', True),
        ('worker-release', calls('worker-release', (release,))[0], 'pool-release', False),
        ('reaper', calls('reaper', (notified, release))[0], 'worker-frames', False),
        ('reaper', calls('reaper', (notified, release))[1], 'worker-release', False),
        ('entered', calls('entered', (notified,))[0], 'worker-tls', False),
    ]
    sites = tuple(Site(roles[name]['actual'], row[0], targets_by_name[target].slot, fallback)
                  for name, (_, row), target, fallback in owners)
    # Bind the constructor's real callback constants to these very table slots.
    # This remains a partial Arc observation until original allocation/refcount
    # and worker transfer predicates are receipt-bound by the owner.
    commit = [(index, row) for index, row in enumerate(ops['builder-create'])
              if row[1] == 16 and row[2] == [roles['commit']['actual']]]
    prepare = [index for index, row in enumerate(ops['builder-create'])
               if row[1] == 16 and row[2] == [roles['prepare']['actual']]]
    graph.require(len(commit) == len(prepare) == 1 and prepare[0] < commit[0][0],
                  'rust-callback-original-constructor-registration-order')
    index = commit[0][0]
    graph.require([(op, args) for _, op, args in ops['builder-create'][index - 2:index]] ==
                  [(65, [targets_by_name['pool-progress'].slot]),
                   (65, [targets_by_name['pool-release'].slot])],
                  'rust-callback-original-constructor-targets')
    arc = _arc_paths(ops, roles, observation, targets_by_name, prepare[0], index)
    return tuple(targets_by_name[name] for name in target_names), sites, {
        'schemaVersion': 'latent.rust.callback-role-source.v1', 'coreDigest': graph.digest(core),
        'roles': roles, 'capturedSourceBranchChecked': True,
        'constructorCallbackTargetsChecked': True, 'trustedSourceCatalogueAuthenticated': False,
        'originalArcMechanism': arc,
        'originalArcPathsAuthenticated': False, 'privateExecutorGraphAuthenticated': False,
        'actualGuestExecuted': False}


def _arc_paths(ops, roles, observation, targets, prepare_index, commit_index):
    """Bind real allocation/header/strong increment and worker raw-Arc transfer.

    Every containing body and its entire relocated destructor/allocator closure
    already matched its original compiler object. These checks identify the
    concrete original values; no copied pool model or serial is an Arc proof.
    """
    constructor = ops['builder-create']
    prefix = [(op, args) for _, op, args in constructor[commit_index - 6:commit_index]]
    graph.require(len(prefix) == 6 and prefix[0][0] == prefix[1][0] == 32
                  and prefix[2:] == [(65, [8]), (106, []),
                                    (65, [targets['pool-progress'].slot]),
                                    (65, [targets['pool-release'].slot])],
                  'rust-callback-original-arc-payload-commit')
    allocation_local = prefix[1][1][0]
    allocators = [row for row in observation['compilerDelegators']
                  if row['originalSymbol'].endswith('12___rust_alloc')]
    graph.require(len(allocators) == 1 and allocators[0]['delegate'] is not None,
                  'rust-callback-original-arc-allocator-binding')
    allocated = [(index, row) for index, row in enumerate(constructor)
                 if row[1] == 16 and row[2] == [allocators[0]['function']]]
    graph.require(len(allocated) == 1 and prepare_index < allocated[0][0] < commit_index,
                  'rust-callback-original-arc-prepaid-allocation-order')
    allocated = allocated[0][0]
    graph.require([(op, args) for _, op, args in constructor[allocated - 2:allocated]] ==
                  [(65, [96]), (65, [8])]
                  and constructor[allocated + 1][1:] == (34, [allocation_local]),
                  'rust-callback-original-arc-allocation-layout')

    def contains(rows, expected):
        actual = [(op, args) for _, op, args in rows]
        return any(actual[index:index + len(expected)] == expected
                   for index in range(len(actual) - len(expected) + 1))

    graph.require(contains(constructor[allocated:commit_index], [
        (32, [allocation_local]), (66, [4294967297]), (55, [3, 0])]),
        'rust-callback-original-arc-strong-weak-header')

    def increment(rows, base, overflow_depth):
        found = []
        for index in range(1, len(rows) - 5):
            window = [(op, args) for _, op, args in rows[index:index + 6]]
            if ([op for op, _ in window] == [32, 40, 34, 65, 106, 54]
                    and window[0][1] == [base] and window[1][1] == [2, 0]
                    and window[3:] == [(65, [1]), (106, []), (54, [2, 0])]):
                counter = window[2][1][0]
                graph.require(not found, 'rust-callback-original-arc-single-increment')
                graph.require(rows[index - 1][1] in (32, 34) and rows[index - 1][2] == [base]
                              and contains(rows[index + 6:], [
                                  (32, [counter]), (65, [-1]), (76, []), (13, [overflow_depth])]),
                              'rust-callback-original-arc-increment-overflow')
                found.append(rows[index][0])
        graph.require(len(found) == 1, 'rust-callback-original-arc-single-increment')
        return found[0]

    root_clone = increment(constructor[allocated:commit_index], allocation_local, 2)
    worker = ops['worker-closure']
    requests = [(index, row) for index, row in enumerate(worker)
                if row[1] == 16 and row[2] == [roles['request']['actual']]]
    graph.require(len(requests) == 1, 'rust-callback-original-worker-transfer-request')
    index, request = requests[0]
    transfer = [(op, args) for _, op, args in worker[index - 11:index]]
    graph.require(len(transfer) == 11 and [op for op, _ in transfer] ==
                  [65, 32, 32, 66, 32, 65, 106, 34, 32, 65, 106]
                  and transfer[0][1] == [2] and transfer[3][1] == [0]
                  and transfer[5][1] == [8], 'rust-callback-original-worker-raw-arc-transfer')
    worker_base = transfer[4][1][0]
    worker_clone = increment(worker[:index], worker_base, 0)
    graph.require(contains(worker[:index], [
        (32, [worker_base]), (41, [3, 24]), (33, transfer[1][1])]),
        'rust-callback-original-worker-same-pool-registration')
    return {'allocationFunction': allocators[0]['function'],
            'originalAllocatorBody': allocators[0]['delegate'], 'allocationBytes': 96,
            'allocationAlignment': 8, 'strongWeakHeaderValue': 4294967297,
            'retainedPayloadOffset': 8, 'rootRetainedStrongIncrementOffset': root_clone,
            'workerRetainedStrongIncrementOffset': worker_clone,
            'workerRawArcTransferOffset': request[0], 'wholeOriginalBodiesAndReferentsMatched': True,
            'compilerEventAndSourceCatalogueAuthenticated': False}


def unsigned(value: int) -> bytes:
    graph.require(0 <= value <= 0xffffffff, 'rust-callback-u32-bound')
    result = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        result.append(byte | (128 if value else 0))
        if not value:
            return bytes(result)


def signed(value: int) -> bytes:
    graph.require(-(1 << 31) <= value < 1 << 31, 'rust-callback-i32-bound')
    result = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        done = value == 0 and not byte & 64 or value == -1 and byte & 64
        result.append(byte | (0 if done else 128))
        if done:
            return bytes(result)


def section(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + unsigned(len(content)) + content


def _append_vector(original: bytes, additions: list[bytes]) -> bytes:
    reader = graph.Reader(original)
    count = reader.number()
    return unsigned(count + len(additions)) + original[reader.p:] + b''.join(additions)


def _function_type(signature) -> bytes:
    params, results = signature
    return b'\x60' + unsigned(len(params)) + bytes(params) + unsigned(len(results)) + bytes(results)


def _helper(target: Target, target_type: int, signature, fallback: bool) -> bytes:
    params, results = signature
    graph.require(all(value == 0x7f for value in params) and 1 <= len(params) <= 2
                  and results in ((), (0x7f,)), 'rust-callback-target-signature')
    # Preserve each original receiver argument exactly. Only the callback index
    # is compared/consumed; a private callback cannot be reached via table0.
    args = b''.join(b'\x20' + unsigned(index) for index in range(len(params)))
    body = (b'\0\x20' + unsigned(len(params)) + b'\x41' + signed(target.slot) +
            b'\x46\x04' + (bytes(results) if results else b'\x40') + args +
            b'\x10' + unsigned(target.function) + b'\x05')
    if fallback:
        body += args + b'\x20' + unsigned(len(params)) + b'\x11' + unsigned(target_type) + b'\0'
    else:
        body += b'\0'  # Typed unreachable; no callback or context operation.
    return body + b'\x0b\x0b'


def _table_limits(parts):
    definitions = [raw for kind, raw in parts if kind == 4]
    graph.require(len(definitions) == 1, 'rust-callback-original-one-table')
    reader = graph.Reader(definitions[0])
    graph.require(reader.number() == 1 and reader.byte() == 0x70,
                  'rust-callback-original-funcref-table')
    flags, minimum = reader.number(), reader.number()
    maximum = reader.number() if flags == 1 else minimum
    graph.require(flags in (0, 1) and 0 < minimum <= maximum <= 65536,
                  'rust-callback-original-table-bound')
    reader.done()
    return minimum, maximum


def _elements(raw: bytes, targets: dict[int, Target], traps: dict[int, int], minimum: int):
    reader = graph.Reader(raw)
    count = reader.number()
    result, seen = bytearray(unsigned(count)), Counter()
    occupied = set()
    for _ in range(count):
        flags = reader.number()
        graph.require(flags in (0, 2), 'rust-callback-closed-active-elements')
        result.extend(unsigned(flags))
        if flags == 2:
            graph.require(reader.number() == 0, 'rust-callback-element-table')
            result.extend(b'\0')
        graph.require(reader.byte() == 0x41, 'rust-callback-element-offset')
        offset = reader.number(True)
        graph.require(offset >= 0 and reader.byte() == 0x0b, 'rust-callback-element-offset')
        result.extend(b'\x41' + signed(offset) + b'\x0b')
        if flags == 2:
            graph.require(reader.byte() == 0, 'rust-callback-element-funcref')
            result.extend(b'\0')
        size = reader.number()
        graph.require(offset + size <= minimum, 'rust-callback-element-original-bound')
        result.extend(unsigned(size))
        for slot in range(offset, offset + size):
            function = reader.number()
            graph.require(slot not in occupied, 'rust-callback-overlapping-elements')
            occupied.add(slot)
            if function in traps:
                graph.require(slot in targets and targets[slot].function == function,
                              'rust-callback-unexpected-private-table-alias')
                seen[slot] += 1
                function = traps[function]
            elif slot in targets:
                raise ValueError('rust-callback-target-original-slot-mismatch')
            result.extend(unsigned(function))
    reader.done()
    graph.require(set(seen) == set(targets) and all(value == 1 for value in seen.values()),
                  'rust-callback-target-element-closure')
    return bytes(result)



def _audit(derived: bytes, protected: set[int], helpers: dict[int, int],
           original_functions: int, sites: tuple[Site, ...]):
    signatures, imports, bodies = graph.code(derived)
    _, initialized, exports = graph.memory_table(derived)
    graph.require(not protected.intersection(initialized.values()) and
                  all(kind != 0 or function not in protected for kind, function in exports.values()),
                  'rust-callback-derived-public-target-leak')
    helper_calls, target_calls = Counter(), Counter()
    first_helper = min(helpers)
    expected_owners = Counter((site.function, first_helper + index) for index, site in enumerate(sites))
    for function, body in enumerate(bodies, len(imports)):
        for _, op, arguments in graph.instructions(body):
            if op in (16, 18, 210) and arguments[0] in protected:
                graph.require(op == 16 and helpers.get(function) == arguments[0],
                              'rust-callback-derived-private-target-bypass')
                target_calls[function] += 1
            if op in (16, 18, 210) and arguments[0] in helpers:
                graph.require(op == 16 and function < original_functions,
                              'rust-callback-derived-helper-entry-bypass')
                helper_calls[(function, arguments[0])] += 1
    graph.require(helper_calls == expected_owners and set(target_calls) == set(helpers)
                  and all(count == 1 for count in target_calls.values()),
                  'rust-callback-derived-owner-dispatch-closure')


def seal_callback_paths(core: bytes, expected_digest: str, targets: tuple[Target, ...],
                        sites: tuple[Site, ...]) -> tuple[bytes, dict]:
    """Apply an independently source-authenticated plan without creating authority.

    All existing imports/functions/data/table bounds remain. Private targets are
    absent from the public table, exports, original direct/ref.func paths and
    unknown call_ref forms. Only exact original owner-site offsets are changed.
    Original table indices survive in the registry and are checked by helpers.
    """
    graph.require(isinstance(core, bytes) and len(core) <= graph.MAX_CORE_BYTES
                  and graph.digest(core) == expected_digest, 'rust-callback-original-preimage')
    graph.require(0 < len(targets) <= 8 and 0 < len(sites) <= 16,
                  'rust-callback-plan-bound')
    slots = {target.slot: target for target in targets}
    functions = {target.function for target in targets}
    graph.require(len(slots) == len(targets) == len(functions), 'rust-callback-duplicate-target')
    selected = {(site.function, site.offset): site for site in sites}
    graph.require(len(selected) == len(sites) and {site.slot for site in sites} == set(slots),
                  'rust-callback-site-closure')
    signatures, imports, bodies = graph.code(core)
    parts = graph.sections(core)
    type_pool = graph.types(core)
    function_count = len(signatures)
    graph.require(function_count + len(targets) + len(sites) <= 65534
                  and len(type_pool) + len(sites) <= 65534,
                  'rust-callback-function-or-type-bound')
    minimum, maximum = _table_limits(parts)
    _, initialized, exports = graph.memory_table(core)
    graph.require(all(0 <= index < function_count for index in initialized.values()),
                  'rust-callback-original-element-function-bound')
    graph.require(all(kind != 0 or 0 <= index < function_count for kind, index in exports.values()),
                  'rust-callback-original-export-function-bound')
    for target in targets:
        graph.require(0 <= target.slot < minimum and len(imports) <= target.function < function_count
                      and initialized.get(target.slot) == target.function,
                      'rust-callback-original-target')
    graph.require(all(kind != 0 or index not in functions for kind, index in exports.values()),
                  'rust-callback-private-export-bypass')
    # Fail closed for imported tables/memories/globals. The selected original
    # core owns its table and numeric globals; cross-module aliases are absent.
    for tag, raw in parts:
        if tag == 2:
            reader = graph.Reader(raw)
            for _ in range(reader.number()):
                reader.name(); reader.name()
                graph.require(reader.byte() == 0, 'rust-callback-nonfunction-import')
                reader.number()
            reader.done()
        elif tag == 6:
            reader = graph.Reader(raw)
            for _ in range(reader.number()):
                graph.require(reader.byte() == 0x7f and reader.byte() in (0, 1)
                              and reader.byte() == 0x41, 'rust-callback-numeric-global')
                reader.number(True)
                graph.require(reader.byte() == 0x0b, 'rust-callback-global-initializer')
            reader.done()
    trap_indices = {target.function: function_count + index for index, target in enumerate(targets)}
    added_types, added_functions, added_bodies = [], [], []
    for target in targets:
        signature = signatures[target.function]
        graph.require(signature in type_pool, 'rust-callback-target-type')
        added_functions.append(unsigned(type_pool.index(signature)))
        added_bodies.append(b'\0\0\x0b')  # No locals; unreachable; end.
    replacements = {}
    for index, site in enumerate(sites):
        target = slots[site.slot]
        signature = signatures[target.function]
        helper_type = (signature[0] + (0x7f,), signature[1])
        type_index = len(type_pool) + len(added_types)
        added_types.append(_function_type(helper_type))
        added_functions.append(unsigned(type_index))
        added_bodies.append(_helper(target, type_pool.index(signature), signature, site.source_fallback))
        replacements[(site.function, site.offset)] = (function_count + len(targets) + index, signature)
    found, changed, operators = set(), [], 0
    for function, body in enumerate(bodies, len(imports)):
        ops = graph.bounded_instructions(body, graph.MAX_RELOCATIONS - operators)
        operators += len(ops)
        graph.require(operators <= graph.MAX_RELOCATIONS, 'rust-callback-operator-bound')
        edits = []
        for index, (offset, op, arguments) in enumerate(ops):
            if op in (16, 18, 210):
                graph.require(arguments[0] < function_count and arguments[0] not in functions,
                              'rust-callback-private-direct-or-ref-bypass')
            if op in (17, 19):
                graph.require(arguments[0] < len(type_pool) and arguments[1] == 0,
                              'rust-callback-original-indirect-type-or-table')
            graph.require(op != 38 and not (op == 252 and arguments[0] in (12, 14, 15, 17)),
                          'rust-callback-mutable-table')
            key = (function, offset)
            if key in replacements:
                helper, signature = replacements[key]
                graph.require(op == 17 and arguments[1] == 0
                              and type_pool[arguments[0]] == signature,
                              'rust-callback-original-owner-site')
                end = ops[index + 1][0] if index + 1 < len(ops) else len(body)
                edits.append((offset, end, b'\x10' + unsigned(helper)))
                found.add(key)
        start, output = 0, bytearray()
        for begin, end, value in edits:
            output.extend(body[start:begin]); output.extend(value); start = end
        output.extend(body[start:])
        changed.append(bytes(output))
    graph.require(found == set(replacements), 'rust-callback-missing-owner-site')
    output, seen = bytearray(b'\0asm\1\0\0\0'), Counter()
    for tag, raw in parts:
        seen[tag] += 1
        if tag in (1, 3, 9, 10):
            graph.require(seen[tag] == 1, 'rust-callback-duplicate-required-section')
        if tag == 1:
            raw = _append_vector(raw, added_types)
        elif tag == 3:
            raw = _append_vector(raw, added_functions)
        elif tag == 9:
            raw = _elements(raw, slots, trap_indices, minimum)
        elif tag == 10:
            all_bodies = changed + added_bodies
            raw = unsigned(len(all_bodies)) + b''.join(unsigned(len(body)) + body for body in all_bodies)
        output.extend(section(tag, raw))
    graph.require(all(seen[tag] == 1 for tag in (1, 3, 9, 10))
                  and len(output) <= graph.MAX_CORE_BYTES, 'rust-callback-output-bound-or-sections')
    derived = bytes(output)
    helper_targets = {function_count + len(targets) + index: slots[site.slot].function
                      for index, site in enumerate(sites)}
    _audit(derived, functions, helper_targets, function_count, sites)
    return derived, {
        'schemaVersion': 'latent.rust.private-callback-paths-source.v1',
        'originalDigest': expected_digest, 'derivedDigest': graph.digest(derived),
        'ordinaryTableMinimum': minimum, 'ordinaryTableMaximum': maximum,
        'privateTargetsRemoved': len(targets), 'authenticatedOwnerSitesRewritten': len(sites),
        'privateTargetsHaveOnlyCheckedDispatchCallers': True,
        'ordinaryTableContainsPrivateTargets': False,
        'addedTrapFunctions': len(targets), 'addedDispatchFunctions': len(sites),
        'debugMappingQualified': False, 'trustedSourceCatalogueAuthenticated': False,
        'originalArcReceiverProvenanceAuthenticated': False,
        'privateExecutorGraphAuthenticated': False, 'actualGuestExecuted': False,
    }
