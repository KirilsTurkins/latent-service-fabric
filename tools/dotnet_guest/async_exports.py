"""Pinned C# marshalling for real stackful canonical async export tasks.

This bridge preserves the ordinary synchronous C# implementation interface.
It does not implement CLR task scheduling or manufacture completed host work.
"""
from __future__ import annotations

import copy
import re

PROFILE = 'dotnet-native-aot-stackful-async-exports-v1'


def block_end(text: str, start: int) -> int:
    """Canonical WIT has no comments or quoted documentation at this stage."""
    depth = 0
    for offset in range(start, len(text)):
        if text[offset] == '{':
            depth += 1
        elif text[offset] == '}':
            depth -= 1
            if depth == 0:
                return offset + 1
    raise ValueError('dotnet-async-export-unbalanced-canonical-wit')


def projection(text: str, graph: dict, world: str, project_graph):
    """Project imported implementations, retaining declared async exports.

    The caller reparses and compares the complete result against expected.
    Lexical ranges choose which implementation annotations survive; they do
    not establish contract equality.
    """
    main = re.match(r'package ([^\s;{}]+);', text)
    if main is None or any(value in text for value in ('"', '//', '/*')):
        raise ValueError('dotnet-async-export-noncanonical-wit')
    packages = graph['packages']
    selected = [item for item in graph['worlds'] if packages[item['package']]['name'] == main[1]
                and world in (item['name'], main[1].partition('@')[0] + '/' + item['name']
                              + ('@' + main[1].partition('@')[2] if '@' in main[1] else ''))]
    if len(selected) != 1:
        raise ValueError('dotnet-async-export-world-selection')
    selected = selected[0]
    expected = project_graph(graph)
    expected_world = next(item for item in expected['worlds']
                          if item['name'] == selected['name'] and item['package'] == selected['package'])
    nested = []
    for match in re.finditer(r'(?m)^\s*package ([^\s;{}]+) \{', text):
        opening = text.index('{', match.start(), match.end())
        nested.append((match[1], opening, block_end(text, opening)))

    def package_at(position):
        containing = [item for item in nested if item[1] < position < item[2]]
        return min(containing, key=lambda item: item[2] - item[1])[0] if containing else main[1]

    def ranges(kind, name, package):
        found = []
        for match in re.finditer(r'(?m)^\s*' + kind + r' %?' + re.escape(name) + r' \{', text):
            if package_at(match.start()) == package:
                opening = text.index('{', match.start(), match.end())
                found.append((opening, block_end(text, opening)))
        return found

    world_ranges = ranges('world', selected['name'], main[1])
    if len(world_ranges) != 1:
        raise ValueError('dotnet-async-export-world-source-drift')
    world_start, world_end = world_ranges[0]
    allowed, count = [], 0
    imports = {item['interface']['id'] for item in selected['imports'].values() if 'interface' in item}
    for name, item in selected['exports'].items():
        if 'function' in item:
            function = item['function']
            if function['kind'] != 'async-freestanding':
                continue
            matches = list(re.finditer(r'(?m)^\s*export %?' + re.escape(name)
                                       + r': (async\s+func)\b', text[world_start:world_end]))
            if len(matches) != 1:
                raise ValueError('dotnet-async-export-function-source-drift')
            start, end = matches[0].span(1)
            allowed.append((world_start + start, world_start + end))
            expected_world['exports'][name]['function']['kind'] = function['kind']
            count += 1
            continue
        identifier = item['interface']['id']
        interface = graph['interfaces'][identifier]
        functions = interface['functions']
        async_functions = {name: function for name, function in functions.items()
                           if function['kind'] == 'async-freestanding'
                           or isinstance(function['kind'], dict)
                           and set(function['kind']) & {'async-method', 'async-static'}}
        if not async_functions:
            continue
        if identifier in imports:
            raise ValueError('dotnet-async-export-shared-import-implementation')
        if interface['name'] is None:
            matches = list(re.finditer(r'(?m)^\s*export %?' + re.escape(name) + r': interface \{',
                                       text[world_start:world_end]))
            if len(matches) != 1:
                raise ValueError('dotnet-async-export-inline-source-drift')
            opening = world_start + text[world_start:world_end].index(
                '{', matches[0].start(), matches[0].end())
            found = [(opening, block_end(text, opening))]
        else:
            found = ranges('interface', interface['name'], packages[interface['package']]['name'])
        if len(found) != 1:
            raise ValueError('dotnet-async-export-interface-source-drift')
        allowed.extend(found)
        for function_name, function in async_functions.items():
            expected['interfaces'][identifier]['functions'][function_name]['kind'] = copy.deepcopy(function['kind'])
        count += len(async_functions)
    value = re.sub(r'\basync\s+func\b',
                   lambda match: match[0] if any(start <= match.start() < end for start, end in allowed) else 'func',
                   text)
    return value, expected, count


CLASS = re.compile(r'(?ms)^(?P<indent>[ \t]*)public static class (?P<name>[A-Za-z_][A-Za-z0-9_]*)'
                   r'(?: \{|\n(?P=indent)\{)\n.*?^(?P=indent)\}')
METHOD = re.compile(r'(?ms)^(?P<indent>[ \t]*)public static (?P<signature>(?:async Task |unsafe uint )[^{}]+?)\n'
                    r'(?P=indent)\{\n(?P<body>.*?)^(?P=indent)\}')
WRAPPER = re.compile(r'(?ms)^(?P<indent>[ \t]*)public static unsafe int (?P<name>wasmExport[A-Za-z0-9_]+)'
                     r'\((?P<params>[^\n]*)\) \{\n(?P<body>.*?)^(?P=indent)\}')


def task_call(body: str) -> tuple[int, int, str]:
    """Read one generated invocation, including multiline record arguments.

    Only the balanced call expression is consumed. Statements/comments or
    literals inside this generated argument projection are not accepted;
    the original pinned completion tail is checked separately by the caller.
    """
    start = re.search(r'(?m)^\s*var task = ([A-Za-z_][A-Za-z0-9_]*Async)\(',body)
    if start is None:
        raise ValueError('dotnet-async-export-pinned-entry-drift')
    depth = 1
    for offset in range(start.end(),len(body)):
        token = body[offset]
        if token in ';{}\'"/':
            raise ValueError('dotnet-async-export-pinned-entry-drift')
        if token == '(':
            depth += 1
        elif token == ')':
            depth -= 1
            if depth == 0:
                if body[offset+1:offset+3] != ';\n':
                    raise ValueError('dotnet-async-export-pinned-entry-drift')
                return start.start(),offset+3,body[start.start(1):offset+1]
    raise ValueError('dotnet-async-export-pinned-entry-drift')


def bridge_class(text: str, drain_call: str | None = None, *, managed: bool = False) -> tuple[str, int]:
    """Keep upstream argument/result marshalling, changing only task lifetime."""
    if type(managed) is not bool or (managed and drain_call is None):
        raise ValueError('dotnet-managed-root-bridge-selection')
    calls = {}
    count = 0

    def entry(match):
        nonlocal count
        previous = text[:match.start()].rstrip().splitlines()[-1]
        if 'EntryPoint = "[async-lift]' not in previous:
            return match[0]
        body = match['body']
        invocation_start, invocation_end, call = task_call(body)
        expected = ('                if (task.IsCompletedSuccessfully)\n'
                    '                {\n                    return (int)CallbackCode.Exit;\n                }\n\n'
                    '                // TODO: Defer dropping borrowed resources until a result is returned.\n'
                    '                ContextTask* contextTaskPtr = AsyncSupport.ContextGet();\n\n'
                    '                return (int)CallbackCode.Wait | (int)(contextTaskPtr->WaitableSetHandle << 4);\n')
        # Compare normalized indentation as classes for interface/resource
        # exports can nest. Extra work between invocation and exit is rejected.
        normalize = lambda value: '\n'.join(line.strip() for line in value.splitlines()).strip()
        if normalize(body[invocation_end:]) != normalize(expected):
            raise ValueError('dotnet-async-export-pinned-entry-drift')
        parameters = match['params']
        parsed = [] if not parameters else parameters.split(', ')
        if any(re.fullmatch(r'(?:int|long|float|double|nint) p[0-9]+',value) is None for value in parsed):
            raise ValueError('dotnet-async-export-pinned-core-parameters-drift')
        arguments = [value.partition(' ')[2] for value in parsed]
        helper = call.partition('(')[0]
        if helper in calls or len(arguments) != len(set(arguments)):
            raise ValueError('dotnet-async-export-duplicate-generated-helper')
        calls[helper] = (parameters,body[:invocation_start])
        count += 1
        return (match['indent'] + 'public static unsafe int ' + match['name'] + '(' + match['params'] + ') {\n'
                + (match['indent'] + '    global::LsfManagedWorkRoot.Initialize();\n' if managed else '')
                + match['indent'] + '    ' + helper + '(' + ', '.join(arguments) + ');\n'
                + match['indent'] + '    return 0;\n' + match['indent'] + '}')

    result = WRAPPER.sub(entry, text)
    if not count or result.count('EntryPoint = "[async-lift]') != count:
        raise ValueError('dotnet-async-export-entry-count-drift')
    helpers, callbacks = set(), 0

    def method(match):
        nonlocal callbacks
        signature, body = match['signature'], match['body']
        helper = re.fullmatch(r'async Task ([A-Za-z_][A-Za-z0-9_]*Async)\(([\s\S]*)\)', signature)
        if helper and helper[1] in calls:
            helpers.add(helper[1])
            # With --with-wit-results the pinned generator emits a direct
            # result call. Its result-less export emits exactly one await.
            body = re.sub(r'(?m)^(\s*)await ([A-Za-z0-9_:.]+\.[A-Za-z0-9_]+\([^\n]*\));$',
                          r'\1\2;', body)
            if re.search(r'\bawait\b', body):
                raise ValueError('dotnet-async-export-pinned-helper-drift')
            if drain_call is not None:
                returns = list(re.finditer(r'(?m)^(\s*)([A-Za-z_][A-Za-z0-9_]*TaskReturn\([^\n]*\));$', body))
                if len(returns) != 1:
                    raise ValueError('dotnet-retirement-task-return-shape')
                start = returns[0].start()
                sequence = ((returns[0][1]+'global::LsfManagedWorkRoot.Join();\n') if managed else '')
                sequence += returns[0][1]+drain_call+';\n'
                if managed:
                    sequence += returns[0][1]+'global::LsfManagedWorkRoot.Finish();\n'
                body = body[:start]+sequence+body[start:]
            # The pinned generator uses lifted record expressions as formal
            # parameter names. Keep its original raw core parameter list and
            # original argument lifting together instead of inventing a C#
            # type mapping or changing the authoritative implementation API.
            parameters, preamble = calls[helper[1]]
            signature = 'unsafe void ' + helper[1] + '(' + parameters + ')'
            body = preamble + body
        elif re.fullmatch(r'unsafe uint [A-Za-z_][A-Za-z0-9_]*Callback\(int eventRaw, uint waitable, uint code\)', signature):
            expected = ('EventWaitable e = new EventWaitable((EventCode)eventRaw, waitable, code);\n\n'
                        'return (uint)AsyncSupport.Callback(e);')
            normalize = lambda value: '\n'.join(line.strip() for line in value.splitlines()).strip()
            if normalize(body) != normalize(expected):
                raise ValueError('dotnet-async-export-pinned-callback-drift')
            callbacks += 1
            body = (match['indent'] + '    throw new global::System.InvalidOperationException('
                    '"stackful canonical export received a callback");\n')
        return match['indent'] + 'public static ' + signature + '\n' + match['indent'] + '{\n' + body + match['indent'] + '}'

    result = METHOD.sub(method, result)
    if helpers != set(calls) or callbacks != count or any(token in result for token in
            ('AsyncSupport.', 'CallbackCode.', 'ContextTask', 'async Task')):
        raise ValueError('dotnet-async-export-unaccounted-generated-task-support')
    return result, count


def bridge(synchronous: str, asynchronous: str, drain_call: str | None = None, *, managed: bool = False) -> tuple[str, int]:
    """Replace only complete export interop classes in baseline bindings."""
    baseline = {}
    for match in CLASS.finditer(synchronous):
        if match['name'] in baseline:
            raise ValueError('dotnet-async-export-ambiguous-interop-class')
        baseline[match['name']] = match
    replacements, count = [], 0
    for match in CLASS.finditer(asynchronous):
        if 'EntryPoint = "[async-lift]' not in match[0]:
            continue
        if match['name'] not in baseline:
            raise ValueError('dotnet-async-export-missing-baseline-class')
        adapted, amount = bridge_class(match[0], drain_call, managed=managed)
        original = baseline[match['name']]
        replacements.append((original.start(), original.end(), adapted))
        count += amount
    result = synchronous
    for start, end, adapted in reversed(sorted(replacements)):
        result = result[:start] + adapted + result[end:]
    result = memory_support(result, asynchronous)
    if result.count('EntryPoint = "[async-lift]') != count:
        raise ValueError('dotnet-async-export-final-entry-count-drift')
    return result, count


def retirement_call(directory) -> str | None:
    matches = []
    for path in directory.glob('*.IOwnerImports.cs'):
        text = path.read_text(encoding='utf-8')
        namespace = re.search(r'(?m)^namespace ([A-Za-z_][A-Za-z0-9_.]*\.wit\.Imports\.latent\.dotnetRetirement);$', text)
        if namespace is None:
            continue
        if (text.count('public static unsafe void Drain()') != 1 or
                'OwnerImportsInterop.DrainWasmInterop.wasmImportDrain();' not in text):
            raise ValueError('dotnet-retirement-generated-csharp-shape')
        interop = path.with_name(path.name.replace('IOwnerImports.cs', 'OwnerImportsInterop.cs')).read_text(encoding='utf-8')
        if ('DllImportAttribute("latent:dotnet-retirement/owner@0.1.0", EntryPoint = "drain")' not in interop
                or interop.count('public static extern void wasmImportDrain();') != 1):
            raise ValueError('dotnet-retirement-generated-import-shape')
        matches.append('global::'+namespace[1]+'.IOwnerImports.Drain()')
    if len(matches) > 1:
        raise ValueError('dotnet-retirement-ambiguous-generated-import')
    return matches[0] if matches else None


def managed_root_support(directory) -> str | None:
    """Use genuine pinned bindings and normal static UnsafeAccessor metadata.

    The three targets are added to the selected runtime CoreLib's actual Task
    type. No extra facade, reflection lookup or application IL rewrite is used.
    """
    matches = []
    identity = 'latent:dotnet-managed-work/owner@0.1.0'
    for path in directory.glob('*.IOwnerImports.cs'):
        text = path.read_text(encoding='utf-8')
        namespace = re.search(r'(?m)^namespace ([A-Za-z_][A-Za-z0-9_.]*\.wit\.Imports\.latent\.dotnetManagedWork);$', text)
        if namespace is None:
            continue
        signatures = ('public static unsafe Result<(ulong, ulong), uint> Reserve(uint kind, ulong parentGeneration, ulong parentId)',
            'public static unsafe Result<None, uint> Settle(ulong generation, ulong id)',
            'public static unsafe Result<None, uint> Close()', 'public static unsafe void Context(ulong generation, ulong id)')
        interop = path.with_name(path.name.replace('IOwnerImports.cs', 'OwnerImportsInterop.cs')).read_text(encoding='utf-8')
        entries = re.findall(r'DllImportAttribute\("'+re.escape(identity)+r'", EntryPoint = "([a-z]+)"\)', interop)
        if any(text.count(signature) != 1 for signature in signatures) or entries != ['reserve', 'settle', 'close', 'context']:
            raise ValueError('dotnet-managed-root-generated-binding-shape')
        matches.append('global::'+namespace[1]+'.IOwnerImports')
    if len(matches) > 1:
        raise ValueError('dotnet-managed-root-ambiguous-generated-binding')
    if not matches:
        return None
    owner = matches[0]
    return '''// Compiler-owned selected bridge; generated WIT import functions remain unchanged.
#nullable enable
internal static class LsfManagedWorkRoot
{
    [global::System.Runtime.CompilerServices.UnsafeAccessor(global::System.Runtime.CompilerServices.UnsafeAccessorKind.StaticMethod, Name = "LsfInstallAcceptedWork")]
    private static extern void Install(global::System.Threading.Tasks.Task? type,
        global::System.Func<int, ulong, ulong, (ulong, ulong)> reserve,
        global::System.Action<ulong, ulong> settle, global::System.Action close,
        global::System.Action<ulong, ulong> context);

    [global::System.Runtime.CompilerServices.UnsafeAccessor(global::System.Runtime.CompilerServices.UnsafeAccessorKind.StaticMethod, Name = "LsfJoinAcceptedWork")]
    private static extern void JoinCore(global::System.Threading.Tasks.Task? type);

    [global::System.Runtime.CompilerServices.UnsafeAccessor(global::System.Runtime.CompilerServices.UnsafeAccessorKind.StaticMethod, Name = "LsfFinishAcceptedWork")]
    private static extern void FinishCore(global::System.Threading.Tasks.Task? type);

    private static (ulong, ulong) Reserve(int kind, ulong generation, ulong id)
    {
        var result = OWNER.Reserve(checked((uint)kind), generation, id);
        if (!result.IsOk) throw new global::System.InvalidOperationException("managed-work-admission-refused");
        return result.AsOk;
    }
    private static void Settle(ulong generation, ulong id)
    {
        var result = OWNER.Settle(generation, id);
        if (!result.IsOk) throw new global::System.InvalidOperationException("managed-work-settlement-refused");
    }
    private static void Close()
    {
        var result = OWNER.Close();
        if (!result.IsOk) throw new global::System.InvalidOperationException("managed-work-closing-refused");
    }
    internal static void Initialize() => Install(null, Reserve, Settle, Close, OWNER.Context);
    internal static void Join() => JoinCore(null);
    internal static void Finish() => FinishCore(null);
}
'''.replace('OWNER', owner)


def memory_support(synchronous: str, asynchronous: str) -> str:
    """Retain the pinned pure helper needed by asynchronous list lowering.

    The generator can require this class only in the async projection. Its
    general async task runtime is deliberately excluded from the selection.
    Insert the original helper beside its matching return-area class, inside
    the original namespace; never copy the surrounding async support graph.
    """
    expected = ('public static class MemoryHelper\n{\n'
                'public static unsafe void* AlignStackPtr(void* stackAddress, uint alignment)\n{\n'
                'return (void*)(((nint)stackAddress) + ((int)alignment - 1) & -(int)alignment);\n}\n}')
    normalize = lambda value: '\n'.join(line.strip() for line in value.splitlines()).strip()
    selected = [match for match in CLASS.finditer(asynchronous) if match['name'] == 'MemoryHelper']
    if not selected:
        return synchronous
    if len(selected) != 1 or normalize(selected[0][0]) != expected:
        raise ValueError('dotnet-async-export-pinned-memory-helper-drift')
    existing = [match for match in CLASS.finditer(synchronous) if match['name'] == 'MemoryHelper']
    if existing:
        if len(existing) != 1 or normalize(existing[0][0]) != expected:
            raise ValueError('dotnet-async-export-pinned-memory-helper-drift')
        return synchronous
    anchors = [match for match in CLASS.finditer(synchronous) if match['name'] == 'InteropReturnArea']
    original = [match for match in CLASS.finditer(asynchronous) if match['name'] == 'InteropReturnArea']
    if (len(anchors) != 1 or len(original) != 1
            or anchors[0]['indent'] != selected[0]['indent']
            or original[0]['indent'] != selected[0]['indent']
            or original[0].end() > selected[0].start()
            or asynchronous[original[0].end():selected[0].start()].strip()):
        raise ValueError('dotnet-async-export-memory-helper-placement-drift')
    offset = anchors[0].end()
    return synchronous[:offset] + '\n\n' + selected[0][0] + synchronous[offset:]


# This test-only adapter is pinned to the complete retained NORMAL helper,
# including its actual int TaskReturn ABI. Ordinary bridge() never calls it.
JOIN_CAUSE_NORMAL_SHA256 = '6cad4650339b330d39ceeca74af9dde080cfbc751fdbbda26ab2323349a63e8d'
JOIN_CAUSE_FILE = 'ServiceWorld.wit.Exports.examples.greeting.ApiExportsInterop.cs'
JOIN_CAUSE_NORMAL = '            global::LsfManagedWorkRoot.Join();'
JOIN_CAUSE_SELECTED = '''            try
            {
                global::LsfManagedWorkRoot.Join();
            }
            catch (global::System.InvalidOperationException failure) when (
                failure.GetType() == typeof(global::System.InvalidOperationException) &&
                failure.Message == "managed-work-unproven-quiescence")
            {
                ProbeTaskReturn(unchecked((int)0x4A430001u));
                return;
            }
            catch (global::System.AggregateException failure) when (
                failure.InnerExceptions.Count == 1 &&
                global::System.Object.ReferenceEquals(failure.InnerExceptions[0],
                    global::OutsideRootDrain.Library.OriginalFault))
            {
                ProbeTaskReturn(unchecked((int)0x4A430002u));
                return;
            }
            catch (global::System.Exception)
            {
                ProbeTaskReturn(unchecked((int)0x4A430003u));
                return;
            }'''


def diagnostic_join_cause(name: str, text: str) -> tuple[str, dict]:
    """Explicit auxiliary source, never a drain or original-trap qualification."""
    import hashlib
    if name != JOIN_CAUSE_FILE or hashlib.sha256(text.encode('utf-8')).hexdigest() != JOIN_CAUSE_NORMAL_SHA256:
        raise ValueError('dotnet-join-cause-unreviewed-normal-helper')
    if text.count(JOIN_CAUSE_NORMAL) != 1:
        raise ValueError('dotnet-join-cause-join-shape')
    selected = text.replace(JOIN_CAUSE_NORMAL, JOIN_CAUSE_SELECTED)
    if selected.replace(JOIN_CAUSE_SELECTED, JOIN_CAUSE_NORMAL) != text:
        raise ValueError('dotnet-join-cause-normal-inverse')
    return selected, {'profile': 'dotnet-ac7-join-cause-auxiliary-v1', 'source': name,
        'normalSha256': JOIN_CAUSE_NORMAL_SHA256,
        'selectedSha256': hashlib.sha256(selected.encode('utf-8')).hexdigest(),
        'taskReturnOperand': 'int', 'diagnosticWords': [0x4A430001, 0x4A430002, 0x4A430003],
        'physicalRetirementQualified': False, 'originalTrapQualified': False}
