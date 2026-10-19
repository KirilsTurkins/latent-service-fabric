"""Captured outside NuGet code using ordinary RandomNumberGenerator APIs."""
from pathlib import Path
import io
import shutil
import zipfile

from tools import dotnet_dependency_authoring as authoring
from tools.application_dependencies import LOCK
from tools.build_observation import build_environment
from tools.build_snapshot import canonical, digest
from tools.dotnet_application_dependencies import resolve
from tools.dotnet_guest.compiler import Compiler
from tools.dotnet_guest.entropy_grants import declare
from tools.dotnet_guest.project import create
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import snapshot

PACKAGE = 'Outside.Standard.Entropy'
CASES = ('empty', 'one', 'wide', 'instance', 'offset', 'integer', 'invalid', 'initializer', 'nonzero', 'choices', 'hex', 'subclass', 'budget')
LIBRARY_SOURCE = r'''using System;
using System.Security.Cryptography;
namespace OutsideEntropy;
public static class Library {
    public static string Request = "";
    private static int calls;
    public static string Run(string mode) {
        if (++calls != 1) throw new Exception("entropy request state leaked");
        Request = mode;
        int count = 0;
        switch (mode) {
        case "empty": RandomNumberGenerator.Fill(Span<byte>.Empty); break;
        case "one": count = RandomNumberGenerator.GetBytes(1).Length; break;
        case "wide": count = RandomNumberGenerator.GetBytes(257).Length; break;
        case "instance":
            using (var random = RandomNumberGenerator.Create()) {
                byte[] value = new byte[32]; random.GetBytes(value); count = value.Length;
            }
            break;
        case "offset":
            byte[] guarded = new byte[35]; Array.Fill(guarded, (byte)0x5a);
            using (var random = RandomNumberGenerator.Create()) random.GetBytes(guarded, 1, 33);
            if (guarded[0] != 0x5a || guarded[34] != 0x5a) throw new Exception("entropy buffer overrun");
            count = 33; break;
        case "integer":
            for (int index = 0; index < 33; ++index) {
                int value = RandomNumberGenerator.GetInt32(-37, 91);
                if (value < -37 || value >= 91) throw new Exception("ordinary integer range changed");
            }
            count = 33; break;
        case "invalid":
            try { RandomNumberGenerator.GetInt32(4, 4); throw new Exception("invalid range accepted"); }
            catch (ArgumentException) { }
            try { RandomNumberGenerator.GetBytes(-1); throw new Exception("invalid length accepted"); }
            catch (ArgumentOutOfRangeException) { }
            count = 2; break;
        case "initializer":
            if (Initializer.Request != mode || Initializer.Length != 16)
                throw new Exception("request-sensitive entropy initializer was frozen");
            count = 16; break;
        case "nonzero":
            byte[] nonzero = new byte[257];
            using (var random = RandomNumberGenerator.Create()) random.GetNonZeroBytes(nonzero.AsSpan());
            foreach (byte value in nonzero) if (value == 0) throw new Exception("zero byte acknowledged");
            count = nonzero.Length; break;
        case "choices":
            char[] choices = new[] { 'a', 'b', 'c' };
            char[] items = RandomNumberGenerator.GetItems<char>(choices, 33);
            foreach (char value in items) if (value < 'a' || value > 'c') throw new Exception("invalid choice");
            Span<char> destination = stackalloc char[17];
            RandomNumberGenerator.GetItems<char>(choices, destination);
            foreach (char value in destination) if (value < 'a' || value > 'c') throw new Exception("invalid span choice");
            string generated = RandomNumberGenerator.GetString(choices, 9);
            foreach (char value in generated) if (value < 'a' || value > 'c') throw new Exception("invalid string choice");
            int[] shuffled = new[] { 1, 2, 3, 4 };
            RandomNumberGenerator.Shuffle<int>(shuffled);
            Array.Sort(shuffled);
            for (int index = 0; index < 4; ++index) if (shuffled[index] != index + 1) throw new Exception("shuffle changed items");
            count = items.Length + destination.Length + generated.Length; break;
        case "hex":
            string hex = RandomNumberGenerator.GetHexString(33, lowercase: true);
            foreach (char value in hex) if (!((value >= '0' && value <= '9') || (value >= 'a' && value <= 'f')))
                throw new Exception("invalid hexadecimal string");
            Span<char> hexSpan = stackalloc char[17];
            RandomNumberGenerator.GetHexString(hexSpan);
            foreach (char value in hexSpan) if (!((value >= '0' && value <= '9') || (value >= 'A' && value <= 'F')))
                throw new Exception("invalid hexadecimal span");
            count = hex.Length + hexSpan.Length; break;
        case "subclass":
            var derived = new DerivedGenerator();
            byte[] custom = new byte[35]; Array.Fill(custom, (byte)0x5a);
            derived.GetBytes(custom, 1, 33);
            if (custom[0] != 0x5a || custom[34] != 0x5a) throw new Exception("base generator overrun");
            Span<byte> customSpan = stackalloc byte[33]; derived.GetBytes(customSpan);
            foreach (byte value in customSpan) if (value != 0x6b) throw new Exception("base span did not dispatch");
            derived.Dispose(); if (!derived.Disposed) throw new Exception("base Dispose did not dispatch");
            count = 33; break;
        case "budget":
            try {
                // More than the unchanged 65,536-byte provider aggregate.
                for (int index = 0; index < 17; ++index) RandomNumberGenerator.GetBytes(4096);
                throw new Exception("bounded random source acknowledged excess bytes");
            }
            catch (CryptographicException) { return "ordinary-entropy:budget|denied=cryptographic|fresh=1"; }
        case "denied":
            try { RandomNumberGenerator.GetBytes(1); throw new Exception("denied source acknowledged entropy"); }
            catch (CryptographicException) { return "ordinary-entropy:denied|denied=cryptographic|fresh=1"; }
        case "trap":
            RandomNumberGenerator.GetBytes(32); throw new InvalidOperationException("requested entropy trap");
        case "fuel":
            RandomNumberGenerator.GetBytes(32); while (true) calls++;
        default: throw new Exception("unknown finite entropy case");
        }
        return "ordinary-entropy:" + mode + "|count=" + count + "|fresh=1";
    }
}
public sealed class DerivedGenerator : RandomNumberGenerator {
    public bool Disposed;
    public override void GetBytes(byte[] value) { Array.Fill(value, (byte)0x6b); }
    protected override void Dispose(bool disposing) { Disposed = disposing; }
}
public static class Initializer {
    public static readonly string Request;
    public static readonly int Length;
    static Initializer() {
        Request = Library.Request;
        Length = RandomNumberGenerator.GetBytes(16).Length;
    }
}
'''
COUNTS = dict(zip(CASES[:-1], (0, 1, 257, 32, 33, 33, 2, 16, 257, 59, 50, 33)))


def expected(mode):
    if mode in {'budget', 'denied'}:
        return 'ordinary-entropy:' + mode + '|denied=cryptographic|fresh=1'
    return 'ordinary-entropy:' + mode + '|count=' + str(COUNTS[mode]) + '|fresh=1'


def prepare(output: Path, outside: Path, tools: Path):
    project = create(output, 'greeting')
    declare(project)
    outside.mkdir(mode=0o700)
    library, evidence, feed = (outside / name for name in ('library', 'evidence', 'feed'))
    for directory in (library, evidence, feed): directory.mkdir()
    (library / 'Library.cs').write_text(LIBRARY_SOURCE, encoding='utf-8', newline='\n')
    (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<TargetFramework>net10.0</TargetFramework><OutputType>Library</OutputType>'
        '<AssemblyName>' + PACKAGE + '</AssemblyName><Nullable>enable</Nullable>'
        '<UseSharedCompilation>false</UseSharedCompilation><ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>'
        '<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets></PropertyGroup></Project>',
        encoding='utf-8', newline='\n')
    (library / 'nuget.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    (library / 'global.json').write_bytes((project / 'global.json').read_bytes())
    originals = {name: digest(data) for name, data in snapshot(library).items()}
    commands = Commands(library, evidence, build_environment(outside))
    compiler = Compiler(tools, commands, project / 'vendor/lsf', offline=True, captured=True)
    compiler.run('outside-entropy-library', compiler.dotnet, 'build', library / 'Library.csproj', '-c', 'Release',
        '-p:RestoreConfigFile=' + str(library / 'nuget.config'), '-p:NuGetAudit=false', '-nodeReuse:false',
        '-p:UseSharedCompilation=false', '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
    compiler.check_unchanged()
    assembly = (library / 'bin/Release/net10.0' / (PACKAGE + '.dll')).read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PACKAGE + '.nuspec', '<?xml version="1.0"?><package><metadata><id>' + PACKAGE
            + '</id><version>1.0.0</version><authors>SDK qualification</authors>'
            '<description>Outside ordinary secure entropy library</description></metadata></package>')
        archive.writestr('lib/net10.0/' + PACKAGE + '.dll', assembly)
    package = buffer.getvalue()
    (feed / (PACKAGE.lower() + '.1.0.0.nupkg')).write_bytes(package)
    path = project / 'src/Main.cs'
    before = path.read_text(encoding='utf-8')
    marker = '    public static Result<string, string> Greet(string name)\n    {'
    require(before.count(marker) == 1, 'dotnet-entropy-greeting-preimage')
    path.write_text(before.replace(marker, marker + '\n        if (name.StartsWith("entropy:", '
        'System.StringComparison.Ordinal))\n            return Result<string, string>.Ok('
        'OutsideEntropy.Library.Run(name.Substring(8)));'), encoding='utf-8', newline='\n')
    authoring.edit(project, 'add', identity=PACKAGE, version='1.0.0')
    candidate = project / 'target/entropy-candidate.json'; candidate.parent.mkdir(exist_ok=True)
    lock = resolve(project, candidate, dotnet=compiler.dotnet, tools=tools,
        policy={'sources': [{'name': 'outside', 'path': str(feed), 'patterns': [PACKAGE]}]})
    require(authoring.review(project, candidate, digest(candidate.read_bytes()))['status'] == 'reviewed'
            and authoring.status(project)['status'] == 'verified', 'dotnet-entropy-exact-native-review')
    require(PACKAGE.lower() in {row['metadata']['package'] for row in lock['artifacts']}
            and all(row['role'] != 'build-tool' for row in lock['artifacts']), 'dotnet-entropy-pure-capture')
    for directory in (library, feed):
        require(directory.resolve(strict=True).parent == outside.resolve(strict=True), 'dotnet-entropy-owned-cleanup')
        shutil.rmtree(directory)
    return project, {'schemaVersion': 'latent.dotnet.entropy.fixture.v1', 'originalFiles': originals,
        'assemblyDigest': digest(assembly), 'packageDigest': digest(package),
        'dependencyLock': digest((project / LOCK).read_bytes()),
        'originalLibraryAndFeedRemoved': not library.exists() and not feed.exists(),
        'applicationEntropyReplacement': False, 'cases': list(CASES),
        'ordinaryCalls': ['RandomNumberGenerator.GetBytes', 'RandomNumberGenerator.Fill',
                          'RandomNumberGenerator.Create', 'RandomNumberGenerator.GetInt32']}
