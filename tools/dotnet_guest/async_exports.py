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
METHOD = re.compile(r'(?ms)^(?P<indent>[ \t]*)public static (?P<signature>(?:async Task |unsafe uint )[^\n{}]+)\n'
                    r'(?P=indent)\{\n(?P<body>.*?)^(?P=indent)\}')
WRAPPER = re.compile(r'(?ms)^(?P<indent>[ \t]*)public static unsafe int (?P<name>wasmExport[A-Za-z0-9_]+)'
                     r'\((?P<params>[^\n]*)\) \{\n(?P<body>.*?)^(?P=indent)\}')


def bridge_class(text: str) -> tuple[str, int]:
    """Keep upstream argument/result marshalling, changing only task lifetime."""
    calls = set()
    count = 0

    def entry(match):
        nonlocal count
        body = match['body']
        invocation = re.search(r'(?m)^\s*var task = ([A-Za-z_][A-Za-z0-9_]*Async\([^\n]*\));\n', body)
        if invocation is None:
            raise ValueError('dotnet-async-export-pinned-entry-drift')
        expected = ('                if (task.IsCompletedSuccessfully)\n'
                    '                {\n                    return (int)CallbackCode.Exit;\n                }\n\n'
                    '                // TODO: Defer dropping borrowed resources until a result is returned.\n'
                    '                ContextTask* contextTaskPtr = AsyncSupport.ContextGet();\n\n'
                    '                return (int)CallbackCode.Wait | (int)(contextTaskPtr->WaitableSetHandle << 4);\n')
        # Compare normalized indentation as classes for interface/resource
        # exports can nest. Extra work between invocation and exit is rejected.
        normalize = lambda value: '\n'.join(line.strip() for line in value.splitlines()).strip()
        if normalize(body[invocation.end():]) != normalize(expected):
            raise ValueError('dotnet-async-export-pinned-entry-drift')
        call = invocation[1]
        calls.add(call.partition('(')[0])
        count += 1
        return (match['indent'] + 'public static unsafe int ' + match['name'] + '(' + match['params'] + ') {\n'
                + body[:invocation.start()] + match['indent'] + '    ' + call + ';\n'
                + match['indent'] + '    return 0;\n' + match['indent'] + '}')

    result = WRAPPER.sub(entry, text)
    if not count or result.count('EntryPoint = "[async-lift]') != count:
        raise ValueError('dotnet-async-export-entry-count-drift')
    helpers, callbacks = set(), 0

    def method(match):
        nonlocal callbacks
        signature, body = match['signature'], match['body']
        helper = re.fullmatch(r'async Task ([A-Za-z_][A-Za-z0-9_]*Async)\(([^\n]*)\)', signature)
        if helper and helper[1] in calls:
            helpers.add(helper[1])
            # With --with-wit-results the pinned generator emits a direct
            # result call. Its result-less export emits exactly one await.
            body = re.sub(r'(?m)^(\s*)await ([A-Za-z0-9_:.]+\.[A-Za-z0-9_]+\([^\n]*\));$',
                          r'\1\2;', body)
            if re.search(r'\bawait\b', body):
                raise ValueError('dotnet-async-export-pinned-helper-drift')
            signature = 'unsafe void ' + helper[1] + '(' + helper[2] + ')'
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
    if helpers != calls or callbacks != count or any(token in result for token in
            ('AsyncSupport.', 'CallbackCode.', 'ContextTask', 'async Task')):
        raise ValueError('dotnet-async-export-unaccounted-generated-task-support')
    return result, count


def bridge(synchronous: str, asynchronous: str) -> tuple[str, int]:
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
        adapted, amount = bridge_class(match[0])
        original = baseline[match['name']]
        replacements.append((original.start(), original.end(), adapted))
        count += amount
    result = synchronous
    for start, end, adapted in reversed(sorted(replacements)):
        result = result[:start] + adapted + result[end:]
    if result.count('EntryPoint = "[async-lift]') != count:
        raise ValueError('dotnet-async-export-final-entry-count-drift')
    return result, count
