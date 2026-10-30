"""Ordinary captured C# API-callee differential; compilation stays in its owner.

The API is queried in the ORIGINAL selected CoreLib. No method metadata,
delegate construction or source annotation certifies execution or API safety.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools import application_dependencies
from tools import compiler_compatibility_fixture as original
from tools.dev_workflow.common import digest, require
from tools.dotnet_guest.project import create, validate
from tools.rust_capsule_project import canonical, inventory, read_file, snapshot

ROOT_SOURCE = 'src/Main.cs'
OLD = b'if (false) { // lsf-api-root-edge'
NEW = b'if (true) { // lsf-api-root-edge'
MAIN = b'''using System;
using System.Runtime.CompilerServices;
using Lsf.Guest;
using ServiceWorld;
using OutsideDiagnostics;
namespace ServiceWorld.wit.Exports.examples.greeting;
public class ApiExportsImpl : IApiExports
{
    private static int calls;
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int CompatibilityRoot()
    {
        if (false) { // lsf-api-root-edge
            return Library.Probe();
        }
        return 42;
    }
    public static Result<string,string> Greet(string mode)
    {
        if (++calls != 1) throw new InvalidOperationException("api-state-not-fresh");
        if (mode != "probe") throw new ArgumentException("api-mode");
        if (CompatibilityRoot() != 42) throw new InvalidOperationException("api-answer");
        return Result<string,string>.Ok("api|answer=42|fresh=1");
    }
}
'''
LIBRARY = b'''using OutsideDiagnosticsData;
namespace OutsideDiagnostics;
public static class Library
{
    public static int Probe() => Core.Probe();
}
'''
CHILD = b'''using System;
using System.IO;
namespace OutsideDiagnosticsData;
public static class Core
{
    // An original ldftn in the captured initializer makes the ACTUAL API
    // addressable. A volatile delegate field avoids a source-level wrapper
    // absence claim; completed ILC graphs must still prove both variants.
    private static volatile Func<string> selected = Path.GetTempFileName;
    public static int Probe()
    {
        try
        {
            _ = selected();
            throw new InvalidOperationException("api-unexpected-filesystem-success");
        }
        catch (PlatformNotSupportedException) { return 42; }
    }
}
'''


def prepare(directory: Path):
    app = create(directory, 'greeting')
    (app / ROOT_SOURCE).write_bytes(MAIN)
    lock = json.loads(read_file(app / 'sdk-lock.json'))
    lock['template'].update(name='api-callee-retention', sourceDigest=digest(MAIN))
    (app / 'sdk-lock.json').write_bytes(canonical(lock) + b'\n')
    validate(snapshot(app))
    return {'projectPath': app, 'rootSource': ROOT_SOURCE,
        'apiKey': 'dotnet.System.IO.Path.GetTempFileName',
        'expectedScope': 'one-controlled-api-callee-retention-differential'}


def capture(app: Path, outside: Path, tools: Path, *, deadline: float):
    return original.dotnet_capture(app, outside, tools, deadline=deadline,
        sources={'Core.cs': CHILD, 'Library.cs': LIBRARY})


def counterfactual(app: Path):
    files = snapshot(app)
    require(files.get(ROOT_SOURCE) == MAIN and MAIN.count(OLD) == 1, 'api-fixed-counterfactual-root')
    captured = application_dependencies.verify_inputs(app, 'dotnet')
    require(captured is not None, 'api-original-captured-transitive-library')
    (app / ROOT_SOURCE).write_bytes(MAIN.replace(OLD, NEW, 1))
    after = snapshot(app)
    require(set(files) == set(after)
        and all(files[name] == after[name] for name in files if name != ROOT_SOURCE)
        and application_dependencies.verify_inputs(app, 'dotnet').identity == captured.identity,
        'api-counterfactual-identical-library-closure')
    return {'sourceBefore': digest(inventory(files)), 'sourceAfter': digest(inventory(after)),
        'capturedInputIdentity': captured.identity, 'rootSource': ROOT_SOURCE,
        'libraryInputsUnchanged': True, 'apiGlobalElimination': 'unknown'}
