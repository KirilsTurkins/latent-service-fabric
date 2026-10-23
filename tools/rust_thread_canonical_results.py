"""Bounded static-result and whole post-return source observations.

The owner must authenticate the captured WIT surface, complete original object
graph and compiler event. A JSON observation or matching symbol is never source
authority. This helper does not enable the normal builder or any runtime.
"""
from __future__ import annotations

from collections import deque

from tools import rust_thread_object_graph as graph


def observe_system_panic_trap(core: bytes, original_graph: dict, post_export: str,
                              realloc_export: str) -> dict:
    """Bind one original core panic_fmt and prove the remaining System closure.

    This source observation does not authenticate a host catalogue. Runtime
    consumers must recompute from their immutable original expectations; guest
    indices, symbols, hashes and this JSON never select an admitted body.
    """
    try:
        graph.require(original_graph['coreDigest'] == graph.digest(core)
                      and not original_graph['failures'] and not original_graph['unresolvedReferents']
                      and not original_graph['instructionDecodeFailures'],
                      'rust-system-panic-original-graph-not-closed')
        signatures, imports, bodies = graph.code(core)
        rows = [row for row in original_graph['matchedBindings']
                if row['kind'] == 0 and row['bodyMatched']
                and row['object'].split('/')[0].startswith('libcore-')
                and row['object'].split('/')[0].endswith('.rlib')
                and row['originalSymbol'].endswith('_4core9panicking9panic_fmt')]
        graph.require(len(rows) == 1, 'rust-system-panic-original-source-binding')
        selected = rows[0]
        function = selected['actual']
        graph.require(len(imports) <= function < len(signatures)
                      and signatures[function] == ((0x7f, 0x7f, 0x7f), ()),
                      'rust-system-panic-original-signature')
        body = bodies[function - len(imports)]
        # The authentic object body has real relocation spans. The complete
        # original graph has already checked each final referent; its object
        # hash must not be mistaken for the relocated linked body's hash.
        graph.require(len(selected['sourceBodyDigest']) == 64
                      and selected['sourceBytes'] == len(body),
                      'rust-system-panic-original-body-binding')
        _, _, exports = graph.memory_table(core)
        roots = [exports[name] for name in (post_export, realloc_export)]
        graph.require(all(kind == 0 for kind, _ in roots), 'rust-system-panic-canonical-export')
        lifecycle = {index for name, (kind, index) in exports.items()
                     if kind == 0 and name.startswith('__lsf_rust_')}
        pending = [index for _, index in roots]
        visited, operators = set(), 0
        while pending:
            index = pending.pop()
            if index in visited:
                continue
            graph.require(len(visited) < graph.MAX_NODES, 'rust-system-panic-function-bound')
            visited.add(index)
            if index == function:
                continue  # Only the installed, exact System trap stops traversal.
            graph.require(len(imports) <= index < len(signatures) and index not in lifecycle,
                          'rust-system-panic-remaining-import-or-lifecycle')
            for _, op, args in graph.bounded_instructions(
                    bodies[index - len(imports)], graph.MAX_RELOCATIONS - operators):
                operators += 1
                graph.require(op not in (17, 18, 19, 20, 21, 210),
                              'rust-system-panic-remaining-indirect-or-callback')
                if op == 16:
                    pending.append(args[0])
                    graph.require(len(pending) <= graph.MAX_RELOCATIONS,
                                  'rust-system-panic-worklist-bound')
        graph.require(function in visited, 'rust-system-panic-not-in-canonical-closure')
        return {'schemaVersion': 'latent.rust.canonical-system-panic-source.v1',
                'coreDigest': graph.digest(core), 'originalFunction': function,
                'originalSymbol': selected['originalSymbol'], 'originalObject': selected['object'],
                'originalObjectBodyDigest': 'sha256:' + selected['sourceBodyDigest'],
                'linkedOriginalBodyDigest': graph.digest(body), 'remainingClosureFunctions': len(visited),
                'remainingClosureOperators': operators, 'failureIsTrapNotCleanup': True,
                'trustedSourceCatalogueAuthenticated': False, 'systemPanicTrapInstalled': False,
                'canonicalAbiBodiesAuthenticated': False, 'actualGuestExecuted': False}
    except (IndexError, KeyError, TypeError, AttributeError) as error:
        raise ValueError('rust-system-panic-original-binding-or-shape') from error


def select_wit_result(wit: dict, world: str, public_export: str) -> dict:
    """Bind the finite layout to one real parsed WIT world/public function."""
    try:
        graph.require(0 < len(wit['worlds']) <= 128 and len(wit['interfaces']) <= 4096
                      and len(wit['packages']) <= 256 and len(wit['types']) <= 4096,
                      'rust-result-wit-graph-bound')
        def world_name(row):
            package = row.get('package')
            if package is None:
                return row['name']
            graph.require(type(package) is int and 0 <= package < len(wit['packages']),
                          'rust-result-wit-world-package-index')
            base, at, version = wit['packages'][package]['name'].partition('@')
            return base + '/' + row['name'] + at + version

        selected = [row for row in wit['worlds'] if row['name'] == world or world_name(row) == world]
        graph.require(len(selected) == 1 and len(selected[0]['exports']) == 1,
                      'rust-result-single-wit-world-export')
        reference = next(iter(selected[0]['exports'].values()))
        graph.require(set(reference) == {'interface'}, 'rust-result-wit-interface-only')
        index = reference['interface']['id']
        graph.require(type(index) is int and 0 <= index < len(wit['interfaces']),
                      'rust-result-wit-interface-index')
        interface = wit['interfaces'][index]
        package = interface['package']
        graph.require(type(package) is int and 0 <= package < len(wit['packages'])
                      and len(interface['functions']) == 1, 'rust-result-single-wit-public-function')
        function = next(iter(interface['functions'].values()))
        base, at, version = wit['packages'][package]['name'].partition('@')
        name = base + '/' + interface['name'] + at + version + '#' + function['name']
        graph.require(name == public_export and function['kind'] == 'freestanding',
                      'rust-result-wit-public-binding')

        def resolve(value, seen):
            if isinstance(value, str):
                return value
            graph.require(type(value) is int and 0 <= value < len(wit['types'])
                          and value not in seen and len(seen) < 32,
                          'rust-result-wit-type-index-cycle-or-depth')
            kind = wit['types'][value]['kind']
            if set(kind) == {'type'}:
                return resolve(kind['type'], seen | {value})
            graph.require(set(kind) == {'result'} and set(kind['result']) == {'ok', 'err'},
                          'rust-result-wit-layout-not-qualified')
            return {'result': {arm: resolve(kind['result'][arm], seen | {value})
                               for arm in ('ok', 'err')}}

        result = resolve(function['result'], set())
        graph.require(result == {'result': {'ok': 'string', 'err': 'string'}},
                      'rust-result-wit-layout-not-qualified')
        return result
    except (IndexError, KeyError, TypeError, AttributeError, StopIteration) as error:
        raise ValueError('rust-result-wit-original-shape') from error


def static_return_area(body: bytes) -> tuple[int, int]:
    """Conservatively prove every reachable normal exit returns one i32.const.

    Structured branch edges are followed, including branches to the function
    label. Tail calls and a function-label branch are refused. Immediate
    constants cannot be bypassed by any structured branch into a return node.
    Trapping paths have no normal result. No dynamic values are guessed.
    """
    ops = graph.bounded_instructions(body)
    graph.require(ops, 'rust-result-empty-body')
    parents, ends, alternatives, stack = [], {}, {}, [-1]
    for index, (_, op, _) in enumerate(ops):
        parents.append(stack[-1])
        if op in (2, 3, 4):
            graph.require(len(stack) < graph.MAX_NODES, 'rust-result-control-depth-bound')
            stack.append(index)
        elif op == 5:
            graph.require(stack[-1] >= 0 and ops[stack[-1]][1] == 4
                          and stack[-1] not in alternatives, 'rust-result-else-shape')
            alternatives[stack[-1]] = index
        elif op == 11:
            graph.require(stack, 'rust-result-end-shape')
            opener = stack.pop()
            ends[opener] = index
            graph.require(stack or index == len(ops) - 1, 'rust-result-trailing-function-operators')
        graph.require(op not in (18, 19), 'rust-result-tail-call-not-qualified')
    graph.require(not stack and -1 in ends, 'rust-result-unclosed-control')

    branch_steps = 0

    def branch(index, depth):
        nonlocal branch_steps
        label = parents[index]
        for _ in range(depth):
            branch_steps += 1
            graph.require(branch_steps <= graph.MAX_RELOCATIONS, 'rust-result-branch-work-bound')
            graph.require(label != -1, 'rust-result-branch-depth')
            label = parents[label]
        graph.require(label != -1, 'rust-result-function-label-branch-not-qualified')
        return label + 1 if ops[label][1] == 3 else ends[label] + 1

    queue, scheduled, exits, edges = deque([0]), {0}, [], 0
    while queue:
        index = queue.popleft()
        graph.require(0 <= index < len(ops), 'rust-result-control-edge-bound')
        _, op, args = ops[index]
        if op == 0:  # unreachable: no successful exit.
            targets = ()
        elif op == 15 or index == ends[-1]:
            graph.require(index > 0 and ops[index - 1][1] == 65,
                          'rust-result-dynamic-or-unqualified-return')
            exits.append(ops[index - 1][2][0])
            targets = ()
        elif op == 12:
            targets = (branch(index, args[0]),)
        elif op == 13:
            targets = (index + 1, branch(index, args[0]))
        elif op == 14:
            targets = tuple(branch(index, depth) for depth in args)
        elif op == 4:
            targets = (index + 1, alternatives.get(index, ends[index]) + 1)
        elif op == 5:
            targets = (ends[parents[index]] + 1,)
        else:
            targets = (index + 1,)
        edges += len(targets)
        graph.require(edges <= graph.MAX_RELOCATIONS, 'rust-result-control-edge-bound')
        # Avoid duplicate queued nodes consuming unbounded worklist storage.
        for target in targets:
            if target not in scheduled:
                scheduled.add(target)
                queue.append(target)
        graph.require(len(queue) <= graph.MAX_RELOCATIONS, 'rust-result-worklist-bound')
    graph.require(exits and len(set(exits)) == 1, 'rust-result-missing-or-distinct-static-return')
    return exits[0], len(exits)


def _post_deallocator(body: bytes) -> int:
    # Original result<string,string> has the same string payload for both tags.
    # Empty strings must retain their dangling sentinel; no free occurs for0.
    reader = graph.Reader(body)
    graph.require(reader.number() == 1 and reader.number() == 1 and reader.byte() == 0x7f,
                  'rust-result-post-local-shape')
    ops = graph.bounded_instructions(body)
    expected = [(2, [-64]), (32, [0]), (40, [2, 8]), (34, [1]), (69, []),
                (13, [0]), (32, [0]), (40, [2, 4]), (32, [1]), (65, [1]),
                (16, None), (11, []), (11, [])]
    graph.require(len(ops) == len(expected), 'rust-result-post-whole-body')
    for (_, op, args), (wanted_op, wanted_args) in zip(ops, expected):
        graph.require(op == wanted_op and (wanted_args is None or args == wanted_args),
                      'rust-result-post-whole-body')
    return ops[10][2][0]


def observe_canonical_result(core: bytes, public_export: str, post_export: str,
                             original_graph: dict, wit_result: dict) -> dict:
    """Observe one selected original WIT result<string,string> binding.

    The semantic WIT type comes from the owning captured contracts derivation,
    not a regex over arbitrary source. Its authority remains a separate gate.
    Unsupported layouts refuse rather than generalizing this finite proof.
    """
    graph.require(isinstance(core, bytes) and len(core) <= graph.MAX_CORE_BYTES
                  and isinstance(original_graph, dict), 'rust-result-input-bound-or-shape')
    graph.require(all(isinstance(name, str) and 0 < len(name) <= 768
                      for name in (public_export, post_export)), 'rust-result-export-name-bound')
    try:
        return _observe(core, public_export, post_export, original_graph, wit_result)
    except (IndexError, KeyError, TypeError) as error:
        raise ValueError('rust-result-original-binding-or-shape') from error


def _observe(core, public_export, post_export, original_graph, wit_result):
    graph.require(wit_result == {'result': {'ok': 'string', 'err': 'string'}},
                  'rust-result-wit-layout-not-qualified')
    graph.require(original_graph.get('coreDigest') == graph.digest(core)
                  and not original_graph.get('failures', [1])
                  and not original_graph.get('unresolvedReferents', [1])
                  and not original_graph.get('instructionDecodeFailures', [1]),
                  'rust-result-original-graph-not-closed')
    signatures, imports, bodies = graph.code(core)
    memory, _, exports = graph.memory_table(core)
    graph.require(memory is not None, 'rust-result-original-memory')
    layout = graph.original_linker_layout(core, exports, len(memory))
    bindings = original_graph.get('matchedBindings', [])
    graph.require(len(bindings) <= graph.MAX_NODES, 'rust-result-original-binding-bound')
    public, post = exports.get(public_export), exports.get(post_export)
    graph.require(public is not None and post is not None and public[0] == post[0] == 0
                  and len(imports) <= public[1] < len(signatures)
                  and len(imports) <= post[1] < len(signatures)
                  and public[1] != post[1], 'rust-result-original-public-binding')
    graph.require(signatures[public[1]][1] == (0x7f,)
                  and signatures[post[1]] == ((0x7f,), ()), 'rust-result-flat-signatures')
    area, exits = static_return_area(bodies[public[1] - len(imports)])
    graph.require(0 < area and area % 4 == 0 and area + 12 <= layout['stackLow'],
                  'rust-result-static-area-original-memory-range')
    private_ranges = []
    for row in bindings:
        if row['kind'] == 1 and row['bodyMatched']:
            begin, size = row['actual'], row['sourceBytes']
            graph.require(0 <= begin <= begin + size <= len(memory),
                          'rust-result-private-data-range')
            graph.require(size == 0 or area + 12 <= begin or begin + size <= area,
                          'rust-result-static-area-private-data-alias')
            private_ranges.append((begin, size))
    graph.require(private_ranges, 'rust-result-missing-original-private-data')
    deallocator = _post_deallocator(bodies[post[1] - len(imports)])
    delegators = [row for row in original_graph.get('compilerDelegators', [])
                  if row['function'] == deallocator]
    graph.require(len(delegators) == 1, 'rust-result-post-original-deallocator-binding')
    delegate = delegators[0]['delegate']
    # Symbol is a locator into the authenticated original std source graph.
    # The exact compiler forwarder and full original target/reference closure,
    # rather than this spelling alone, establish the deallocation body binding.
    graph.require(delegators[0]['originalSymbol'].endswith('14___rust_dealloc')
                  and isinstance(delegate, int) and 0 <= deallocator < len(signatures)
                  and signatures[deallocator] == ((0x7f, 0x7f, 0x7f), ())
                  and any(row['kind'] == 0 and row['actual'] == delegate
                          and row['bodyMatched'] for row in bindings),
                  'rust-result-post-original-deallocator-binding')
    return {'schemaVersion': 'latent.rust.canonical-result-source.v1',
            'coreDigest': graph.digest(core), 'publicFunction': public[1],
            'postFunction': post[1], 'staticResultArea': area, 'resultAreaBytes': 12,
            'resultTagOffset': 0, 'resultPointerOffset': 4, 'resultLengthOffset': 8,
            'reachableNormalExits': exits, 'privateDataRangesChecked': len(private_ranges),
            'originalHeapLow': layout['stackHigh'], 'postDeallocator': deallocator,
            'postOriginalAllocatorBody': delegate, 'wholePostShapeChecked': True,
            'trustedWitLayoutAuthenticated': False, 'trustedSourceCatalogueAuthenticated': False,
            'dynamicResultGuardInstalled': False, 'canonicalResultAreaAuthenticated': False,
            'privateExecutorGraphAuthenticated': False, 'actualGuestExecuted': False}
