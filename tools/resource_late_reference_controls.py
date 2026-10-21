"""Reference-language controls for the exact ordinary late-facility sources.

These framework-only builds supplement signed guest qualification. They do not
compile an SDK, adapter, native host or guest component.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import dotnet_resource_runtime_fixture as managed
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.resource_late_facilities import EXPECTED
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json


def execute(language, output):
    require(language in EXPECTED, 'resource-late-reference-language')
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'resource-late-reference-independent-output')
    output = fresh(output)
    record = {'schemaVersion': 'latent.resource-late-reference.v1', 'language': language,
        'signedGuestQualification': False, 'sourceIdentities': {}, 'commands': [], 'cases': []}
    environment = build_environment(output)

    def source(name, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(read_file(ROOT/name))
        record['sourceIdentities'][name] = file_identity(target)

    def run(label, args, timeout=120):
        completed = run_bounded_result([str(arg) for arg in args], cwd=output,
            env=environment, timeout_seconds=timeout, max_output_bytes=1024**2)
        require(len(completed.stdout) <= 1024**2 and len(completed.stderr) <= 1024**2,
            'resource-late-reference-bounded-public-output')
        for suffix, raw in (('stdout', completed.stdout), ('stderr', completed.stderr)):
            (output/(label+'.'+suffix)).write_bytes(raw)
        record['commands'].append({'label': label, 'exitCode': completed.returncode,
            'stdout': file_identity(output/(label+'.stdout')),
            'stderr': file_identity(output/(label+'.stderr'))})
        require(completed.returncode == 0, 'resource-late-reference-command:'+label)
        return completed

    if language == 'java':
        home = Path(os.environ['JAVA_HOME'])
        extension = '.exe' if os.name == 'nt' else ''
        javac, java = (home/'bin'/(name+extension) for name in ('javac', 'java'))
        run('runtime-version', [java, '-version'])
        version = run('compiler-version', [javac, '--version']).stdout.decode().strip()
        require(version.startswith('javac 25.'), 'resource-late-reference-java25')
        source('tools/fixtures/java-resource-late/Library.java', output/'Library.java')
        source('examples/java-resource-runtime/child/Data.java', output/'Data.java')
        (output/'Main.java').write_text('public final class Main { public static void main(String[] args) {'
            ' System.err.print(outside.resourceruntime.Library.run(args[0])); } }\n', encoding='utf8')
        classes = output/'classes'; classes.mkdir()
        run('compile', [javac, '--release', '25', '-proc:none', '-encoding', 'UTF-8',
            '-d', classes, output/'Library.java', output/'Data.java', output/'Main.java'])
        resources = classes/'outside/resourceruntimedata'; resources.mkdir(exist_ok=True)
        for name, raw in (('utf8.txt', managed.DATA['text.txt']),
                ('binary.bin', managed.DATA['binary.bin']), ('empty.bin', b'')):
            (resources/name).write_bytes(raw)
        invocation = [java, '-cp', classes, 'Main']
    else:
        # A framework-only project with no PackageReference or inherited repo
        # build targets. The same exact Library/Data bodies are compiled.
        source('tools/fixtures/dotnet-resource-late/Library.cs', output/'Library.cs')
        (output/'Data.cs').write_text(managed.CHILD_SOURCE, encoding='utf8')
        (output/'Main.cs').write_text('System.Console.Error.Write('
            'OutsideResourceRuntime.Library.Run(args[0]));\n', encoding='utf8')
        for name, raw in managed.DATA.items():
            (output/name).write_bytes(raw)
        resources = ''.join('<EmbeddedResource Include="'+name+'" LogicalName="outside.resource.'+logical+'" />'
            for name, logical in (('text.txt', 'text'), ('binary.bin', 'binary'), ('empty.bin', 'empty')))
        (output/'Reference.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk">'
            '<PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType>'
            '<Nullable>enable</Nullable><EnableDefaultEmbeddedResourceItems>false</EnableDefaultEmbeddedResourceItems>'
            '<ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>'
            '<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets>'
            '</PropertyGroup><ItemGroup>'+resources+'</ItemGroup></Project>\n', encoding='utf8')
        dotnet = shutil.which('dotnet'); require(dotnet is not None, 'resource-late-reference-dotnet')
        version = run('sdk-version', [dotnet, '--version']).stdout.decode().strip()
        require(version.startswith('10.0.'), 'resource-late-reference-dotnet10')
        run('compile', [dotnet, 'build', output/'Reference.csproj', '-c', 'Release', '--nologo'])
        invocation = [dotnet, output/'bin/Release/net10.0/Reference.dll']

    for mode, marker in (('late', b'L'), ('fresh', b'F')):
        completed = run(mode, [*invocation, mode], 30)
        require(completed.stdout == marker
            and completed.stderr.decode('utf8') == EXPECTED[language][mode],
            'resource-late-reference-exact-result-and-one-completion-record')
        record['cases'].append({'mode': mode, 'result': EXPECTED[language][mode],
            'stdout': completed.stdout.decode('ascii'), 'separateProcess': True})
    record['status'] = 'passed'
    write_json(output/'reference.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=sorted(EXPECTED), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(execute(args.language, args.output)['status'])
