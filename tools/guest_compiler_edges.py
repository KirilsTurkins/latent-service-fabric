"""Bounded compiler call-edge observations, never whole-program API approval.

The LLVM/MIR/Go printers are pinned owner inputs. Unknown instructions, incomplete
blocks and indirect calls prevent a negative edge proof. Public observations
contain identities and counts; private compiler IR is not a report payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from tools.dev_workflow.common import digest, encode, require, sha

SCHEMA = 'lsf.guest.compiler-edge.v1'
MAX_BYTES = 4 * 1024 * 1024
MAX_LINE_BYTES = 256 * 1024
MAX_LINES = 65536
MAX_BLOCKS = 4096
MAX_OPERATIONS = 65536
KINDS = ('c-llvm', 'rust-mir', 'go-ssa')
ROOT_EDGES = {
    'c-llvm': (b'if (0) { /* lsf-api-root-edge */', b'if (1) { /* lsf-api-root-edge */'),
    'rust-mir': (b'if false { // lsf-api-root-edge', b'if true { // lsf-api-root-edge'),
    'go-ssa': (b'if false { // lsf-api-root-edge', b'if true { // lsf-api-root-edge'),
}
IDENTIFIER = re.compile(r'[A-Za-z_.$][A-Za-z0-9_.$:/<>,-]{0,191}\Z')
LLVM_PURE = frozenset(('alloca load store getelementptr bitcast addrspacecast trunc zext sext '
    'fptrunc fpext fptoui fptosi uitofp sitofp ptrtoint inttoptr icmp fcmp phi select freeze '
    'add sub mul udiv sdiv urem srem shl lshr ashr and or xor fadd fsub fmul fdiv frem fneg '
    'extractvalue insertvalue extractelement insertelement shufflevector fence atomicrmw cmpxchg').split())
GO_PURE = frozenset(('Arg ArgIntReg ArgFloatReg InitMem SP SB Const8 Const16 Const32 Const64 MakeResult I64Const '
    'ConstBool ConstNil ConstString Copy Phi Select0 Select1 SelectN Add32 Add64 Sub32 Sub64 '
    'Mul32 Mul64 Eq32 Eq64 Neq32 Neq64 Less32 Less64 Leq32 Leq64 Not OffPtr PtrIndex '
    'WasmI64Const WasmI32Const WasmI64Add WasmI64Sub WasmI64Mul WasmI64Eq WasmI64Eqz '
    'WasmI64Ne WasmI64LtS WasmI64LtU WasmI64LeS WasmI64LeU WasmI64And WasmI64Or '
    'WasmI64Xor WasmI64Shl WasmI64ShrS WasmI64ShrU WasmI32WrapI64 WasmI64ExtendI32S '
    'WasmI64ExtendI32U WasmI64Load WasmI32Load WasmI64Store WasmI32Store').split())
# Go2aae1000 cmd/compile/internal/ssa/_gen/genericOps.go: MakeResult builds
# result components with final memory operand. It is not a call; individual
# operand-producing instructions still need their own explicitly known shapes.
# The same pinned WasmOps.go names I64Const/LoweredStaticCall; _gen/main.go
# writes opInfo.name verbatim and generates Op.String() from it, without Wasm.


@dataclass
class Block:
    calls: list[str] = field(default_factory=list)
    successors: list[str] = field(default_factory=list)
    terminal: bool = False
    unknown: bool = False


class Graph:
    def __init__(self):
        self.blocks: dict[str, Block] = {}
        self.entry: str | None = None
        self.complete = True
        self.operations = 0

    def block(self, name):
        require(name not in self.blocks and len(self.blocks) < MAX_BLOCKS, 'compiler-edge-block-bound-or-duplicate')
        self.blocks[name] = Block()
        if self.entry is None:
            self.entry = name
        return self.blocks[name]

    def step(self, block):
        self.operations += 1
        require(self.operations <= MAX_OPERATIONS, 'compiler-edge-operation-bound')
        if block.terminal:
            self.complete = False

    def observation(self, target):
        require(self.entry is not None, 'compiler-edge-no-entry')
        if any(not block.terminal or any(edge not in self.blocks for edge in block.successors)
               for block in self.blocks.values()):
            self.complete = False
        seen, todo, count, unknown = set(), [self.entry], 0, False
        while todo:
            name = todo.pop()
            if name in seen or name not in self.blocks:
                continue
            seen.add(name)
            block = self.blocks[name]
            count += block.calls.count(target)
            unknown |= block.unknown
            todo.extend(block.successors)
        complete = self.complete and not unknown
        return {'state': ('observed-direct-edge' if count else 'edge-not-observed') if complete else 'unknown',
                'completeSelectedBody': self.complete and not unknown,
                'directEdges': count, 'blocks': len(self.blocks), 'reachableBlocks': len(seen),
                'operations': self.operations}


def lines(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'compiler-edge-byte-bound')
    rows = raw.split(b'\n', MAX_LINES)
    require(len(rows) <= MAX_LINES and all(len(row) <= MAX_LINE_BYTES for row in rows),
            'compiler-edge-line-bound')
    require(b'\0' not in raw, 'compiler-edge-nul')
    return raw.decode('utf-8').splitlines()


def identifier(value):
    require(type(value) is str and IDENTIFIER.fullmatch(value) is not None,
            'compiler-edge-identifier')
    return value


def llvm(raw, root):
    graph, block, active, ended = Graph(), None, False, False
    for row in lines(raw):
        # A quoted identifier/assembly/string outside the selected body may be
        # private. Do not resolve it by substring or interpret it as a call.
        match = re.match(r'^define\b.*?@([A-Za-z_.$][A-Za-z0-9_.$-]*)\(', row)
        if match:
            if active:
                graph.complete = False
            if match[1] == root:
                require(not ended, 'compiler-edge-duplicate-root')
                active = True
                graph.complete &= row.rstrip().endswith('{')
            continue
        if not active:
            continue
        text = row.strip()
        if text == '}':
            active, ended = False, True
            continue
        if not text or text.startswith(';'):
            continue
        label = re.match(r'^([A-Za-z_.$0-9][A-Za-z0-9_.$-]*):(?:\s*;.*)?$', text)
        if label:
            block = graph.block(label[1])
            continue
        if block is None:
            block = graph.block('entry')
        graph.step(block)
        statement = re.sub(r'^%[^=]+ = ', '', text)
        opcode = statement.split(None, 1)[0]
        if opcode in ('tail', 'musttail', 'notail'):
            statement = statement.split(None, 1)[1]
            opcode = statement.split(None, 1)[0]
        if opcode == 'call':
            call = re.match(r'^call\b[^@%"\n]*@([A-Za-z_.$][A-Za-z0-9_.$-]*)\(', statement)
            if call:
                block.calls.append(call[1])
            else:
                block.unknown = True
        elif opcode == 'br':
            edges = re.findall(r'\blabel %([A-Za-z_.$0-9][A-Za-z0-9_.$-]*)', statement)
            if len(edges) not in (1, 2):
                block.unknown = True
            block.successors.extend(edges)
            block.terminal = True
        elif opcode in ('ret', 'unreachable'):
            block.terminal = True
        elif opcode not in LLVM_PURE:
            # Includes invoke/callbr/switch/asm and unfamiliar future opcodes.
            block.unknown = True
    graph.complete &= ended and not active
    return graph


def mir(raw, root):
    graph, block, active, depth, ended = Graph(), None, False, 0, False
    for row in lines(raw):
        header = re.match(r'^fn ([^ (]+)\(', row)
        if header:
            if active:
                graph.complete = False
            if header[1] == root:
                require(not ended, 'compiler-edge-duplicate-root')
                active, depth = True, 1
                graph.complete &= row.rstrip().endswith('{')
            continue
        if not active:
            continue
        text = row.strip()
        if text == '}' and depth == 1:
            active, ended = False, True
            continue
        label = re.fullmatch(r'(bb[0-9]+): \{', text)
        if label and depth == 1:
            block = graph.block(label[1]); depth += 1
            continue
        if text == '}':
            depth -= 1
            if depth == 1:
                block = None
            continue
        if block is None:
            # Declarations/debug scopes are not executable MIR blocks. Unknown
            # brace geometry refuses a complete negative rather than guessing.
            if text.endswith('{'):
                depth += 1
            continue
        if not text or text.startswith('//'):
            continue
        graph.step(block)
        call = re.fullmatch(r'_[0-9]+(?:\.[0-9]+)? = ([A-Za-z][A-Za-z0-9_:.$<>,-]*)\(.*\) -> \[(.*)\];', text)
        if call:
            block.calls.append(call[1])
            block.successors.extend(re.findall(r'\bbb[0-9]+\b', call[2]))
            block.terminal = True
        elif re.fullmatch(r'goto -> bb[0-9]+;', text):
            block.successors.append(text[8:-1]); block.terminal = True
        elif re.fullmatch(r'switchInt\([^\n]*\) -> \[[^\n]*\];', text):
            block.successors.extend(re.findall(r'\bbb[0-9]+\b', text)); block.terminal = True
        elif text in ('return;', 'unreachable;', 'resume;', 'abort;'):
            block.terminal = True
        elif '->' in text or re.match(r'^(drop|assert|yield|falseEdge|falseUnwind|asm)\b', text):
            block.unknown = True
        elif not re.fullmatch(r'_[0-9]+(?:\.[0-9]+)? = [^;]+;', text) and not re.fullmatch(
                r'(?:StorageLive|StorageDead|Deinit)\([^;]+\);|nop;', text):
            block.unknown = True
    graph.complete &= ended and not active
    return graph


def go_ssa(raw, root):
    rows = lines(raw)
    require(rows[0].startswith(root + ' func('), 'compiler-edge-Go-function-header')
    graph, block = Graph(), None
    for row in rows[1:]:
        text = row.strip()
        if not text or text.startswith('name '):
            continue
        label = re.fullmatch(r'(b[0-9]+):(?: <- (?:b[0-9]+ ?)+)?', text)
        if label:
            block = graph.block(label[1]); continue
        if block is None:
            graph.complete = False; continue
        graph.step(block)
        value = re.match(r'^\([?+\-0-9]+\) v[0-9]+ = ([A-Za-z0-9_]+)\b(.*)$', text)
        if value:
            opcode, tail = value.groups()
            if 'Call' in opcode:
                target = re.search(r'\{([A-Za-z_.$][A-Za-z0-9_.$:/<>,-]*)\}', tail)
                if opcode in ('StaticCall', 'StaticLECall', 'WasmLoweredStaticCall', 'LoweredStaticCall') and target:
                    block.calls.append(target[1])
                else:
                    block.unknown = True
            if any(atom in opcode for atom in ('Closure', 'InterCall', 'Panic', 'Defer', 'TailCall')):
                block.unknown = True
            if 'Call' not in opcode and opcode not in GO_PURE:
                block.unknown = True
        elif re.match(r'^(Plain|If|Ret|Exit|Defer|First)\b', text):
            kind = text.split(None, 1)[0]
            edges = text.split('->', 1)[1] if '->' in text else ''
            block.successors.extend(re.findall(r'\bb[0-9]+\b', edges))
            if kind not in ('Plain', 'If', 'Ret', 'Exit'):
                block.unknown = True
            elif len(block.successors) != {'Plain': 1, 'If': 2, 'Ret': 0, 'Exit': 0}[kind]:
                block.unknown = True
            block.terminal = True
        else:
            # Architecture-specific block kinds, DEAD rows and dependency-cycle
            # output need explicit pinned support before a negative is valid.
            block.unknown = True
    return graph


def observe(kind, raw, root, target, bindings):
    require(kind in KINDS, 'compiler-edge-kind')
    identifier(root); identifier(target)
    required = {'sourceDigest', 'componentDigest', 'compilerDigest', 'recipeDigest', 'graphDigest'}
    require(type(bindings) is dict and set(bindings) == required, 'compiler-edge-binding-shape')
    for value in bindings.values():
        sha(value)
    graph = {'c-llvm': llvm, 'rust-mir': mir, 'go-ssa': go_ssa}[kind](raw, root)
    result = {'schemaVersion': SCHEMA, 'compilerFormat': kind, **bindings,
        'rawDigest': digest(raw), 'rawBytes': len(raw),
        'rootIdentity': digest(root.encode()), 'targetIdentity': digest(target.encode()),
        **graph.observation(target), 'scope': 'exact-selected-compiler-call-edge',
        'apiSupport': 'unknown', 'runtimeExecution': 'not-observed', 'authority': 'none'}
    result['identity'] = digest(encode(result))
    return validate(result)


def validate(value, *, bindings=None):
    require(type(value) is dict and set(value) == {'schemaVersion', 'compilerFormat',
        'sourceDigest', 'componentDigest', 'compilerDigest', 'recipeDigest', 'graphDigest',
        'rawDigest', 'rawBytes', 'rootIdentity', 'targetIdentity', 'state', 'completeSelectedBody',
        'directEdges', 'blocks', 'reachableBlocks', 'operations', 'scope', 'apiSupport',
        'runtimeExecution', 'authority', 'identity'}, 'compiler-edge-report-shape')
    require(value['schemaVersion'] == SCHEMA and value['compilerFormat'] in KINDS
        and value['scope'] == 'exact-selected-compiler-call-edge'
        and (value['apiSupport'], value['runtimeExecution'], value['authority']) ==
            ('unknown', 'not-observed', 'none'), 'compiler-edge-report-scope')
    for key in ('sourceDigest', 'componentDigest', 'compilerDigest', 'recipeDigest', 'graphDigest',
                'rawDigest', 'rootIdentity', 'targetIdentity', 'identity'):
        sha(value[key])
    for key, low, high in (('rawBytes', 1, MAX_BYTES), ('blocks', 1, MAX_BLOCKS),
                          ('reachableBlocks', 1, value['blocks']), ('operations', 0, MAX_OPERATIONS),
                          ('directEdges', 0, value['operations'])):
        require(type(value[key]) is int and low <= value[key] <= high, 'compiler-edge-report-count')
    require(type(value['completeSelectedBody']) is bool, 'compiler-edge-report-completeness')
    expected = ('observed-direct-edge' if value['directEdges'] else 'edge-not-observed') \
        if value['completeSelectedBody'] else 'unknown'
    require(value['state'] == expected and len(encode(value)) <= 65536
        and value['identity'] == digest(encode({key: item for key, item in value.items() if key != 'identity'})),
        'compiler-edge-report-identity-or-state')
    if bindings is not None:
        require(type(bindings) is dict and set(bindings) == {'sourceDigest', 'componentDigest',
            'compilerDigest', 'recipeDigest', 'graphDigest'} and all(value[key] == item for key, item in bindings.items()),
            'compiler-edge-report-stale-binding')
    return value


def controlled_pair(negative, positive, original_inputs, selected_inputs, root_path):
    """Qualification-owner proof for the fixed one-root-edge fixture only.

    The caller supplies actual captured input bytes, not booleans asserting
    that a library stayed unchanged. This never runs or edits an application.
    """
    from tools.rust_capsule_project import inventory
    negative, positive = validate(negative), validate(positive)
    kind = negative['compilerFormat']
    require(positive['compilerFormat'] == kind and negative['state'] == 'edge-not-observed'
        and positive['state'] == 'observed-direct-edge', 'compiler-edge-pair-actual-states')
    require(all(negative[key] == positive[key] for key in
        ('compilerDigest', 'recipeDigest', 'graphDigest', 'rootIdentity', 'targetIdentity'))
        and negative['componentDigest'] != positive['componentDigest']
        and negative['rawDigest'] != positive['rawDigest'], 'compiler-edge-pair-exact-input-context')
    require(type(original_inputs) is dict and type(selected_inputs) is dict
        and set(original_inputs) == set(selected_inputs) and len(original_inputs) <= 32768
        and root_path in original_inputs and type(root_path) is str
        and all(type(raw) is bytes for raw in (*original_inputs.values(), *selected_inputs.values())),
        'compiler-edge-pair-captured-inputs')
    before, after = original_inputs[root_path], selected_inputs[root_path]
    old, new = ROOT_EDGES[kind]
    require(len(before) <= MAX_BYTES and before.count(old) == 1 and after == before.replace(old, new, 1)
        and all(original_inputs[name] == selected_inputs[name] for name in original_inputs if name != root_path),
        'compiler-edge-pair-only-fixed-root-edge')
    require(negative['sourceDigest'] == digest(inventory(original_inputs))
        and positive['sourceDigest'] == digest(inventory(selected_inputs)), 'compiler-edge-pair-source-inventories')
    result = {'schemaVersion': 'lsf.guest.compiler-edge-pair.v1', 'compilerFormat': kind,
        'negativeObservation': negative['identity'], 'positiveObservation': positive['identity'],
        'sourceBefore': negative['sourceDigest'], 'sourceAfter': positive['sourceDigest'],
        'graphDigest': negative['graphDigest'], 'compilerDigest': negative['compilerDigest'],
        'recipeDigest': negative['recipeDigest'], 'rootIdentity': negative['rootIdentity'],
        'targetIdentity': negative['targetIdentity'], 'scope': 'one-controlled-compiler-call-edge',
        'libraryInputsUnchanged': True, 'apiSupport': 'unknown', 'runtimeExecution': 'not-observed',
        'authority': 'none'}
    result['identity'] = digest(encode(result))
    return result
