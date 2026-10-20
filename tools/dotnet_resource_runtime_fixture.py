"""Outside immutable streams held by ordinary default managed callbacks.

Construction and managed package capture are distinct from guest compilation
and signed qualification. No resource, logger, scheduler or context shim is
installed by the application.
"""
from __future__ import annotations
import io
import json
from pathlib import Path
import shutil
import zipfile

from tools import dotnet_dependency_authoring as authoring
from tools.application_dependencies import LOCK, verify_inputs
from tools.build_observation import build_environment
from tools.dotnet_application_dependencies import resolve
from tools.dotnet_guest.compiler import Compiler
from tools.dotnet_guest.project import create
from tools.dotnet_guest.runtime import ACTIVATION, CLOCK, WALL, RANDOM, LOG
from tools.dotnet_task_runtime_fixture import declare as declare_tasks
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot

PACKAGES=('Outside.ResourceRuntime.Library','Outside.ResourceRuntime.Data')
DATA={'text.txt':'Gr\u00fc\u00dfe\0\u96ea\n'.encode(),
      'binary.bin':bytes((0,255,128,65,13,10)),'empty.bin':b''}
DECLARATIONS=(CLOCK,WALL,RANDOM,LOG,ACTIVATION)
CHILD_SOURCE=r'''using System;
using System.IO;
using System.Text;
namespace OutsideResourceRuntime;
public static class Data {
    public static Stream Open() => typeof(Data).Assembly.GetManifestResourceStream("outside.resource.binary")
        ?? throw new Exception("outside binary resource missing");
    public static string TextHex() {
        using var input=typeof(Data).Assembly.GetManifestResourceStream("outside.resource.text")
            ?? throw new Exception("outside text resource missing");
        using var reader=new StreamReader(input,Encoding.UTF8);
        string text=reader.ReadToEnd();
        if (text!="Gr\u00fc\u00dfe\0\u96ea\n") throw new Exception("outside UTF8 resource changed");
        return Convert.ToHexString(Encoding.UTF8.GetBytes(text)).ToLowerInvariant();
    }
    public static void CheckEmpty() {
        using var empty=typeof(Data).Assembly.GetManifestResourceStream("outside.resource.empty")
            ?? throw new Exception("outside empty resource missing");
        if (empty.Length!=0 || empty.ReadByte()!=-1) throw new Exception("outside empty EOF changed");
    }
}
'''
LIBRARY_SOURCE=r'''using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
namespace OutsideResourceRuntime;
public static class Library {
    private static int calls;
    private static readonly AsyncLocal<string?> local=new();
    private static string Read(Stream input) {
        using var output=new MemoryStream(); input.CopyTo(output);
        return Convert.ToHexString(output.ToArray()).ToLowerInvariant();
    }
    private static async Task<string> Callback(string label,Stream input,Task gate) {
        if (local.Value!="parent") throw new Exception("callback context was not captured");
        local.Value=label; long before=Stopwatch.GetTimestamp();
        await gate; await Task.Delay(1);
        if (local.Value!=label || Stopwatch.GetTimestamp()<before) throw new Exception("callback context/clock changed");
        byte[] entropy=new byte[8]; RandomNumberGenerator.Fill(entropy);
        if (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()<=1L<<32) throw new Exception("wall clock width changed");
        string value=Read(input);
        Console.WriteLine("resource-dotnet:callback:"+label+":entropy=8:wall64=1"); Console.Out.Flush();
        return label+":"+value;
    }
    public static string Run(string mode) {
        if (++calls!=1 || local.Value!=null || SynchronizationContext.Current!=null)
            throw new Exception("resource callback activation state leaked");
        string text=Data.TextHex(); Data.CheckEmpty();
        using var first=Data.Open(); using var second=Data.Open();
        if (first.ReadByte()!=0 || first.ReadByte()!=255 || second.Position!=0)
            throw new Exception("independent resource positions changed");
        local.Value="parent";
        switch (mode) {
        case "parallel": {
            var gate=new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var one=Task.Run(()=>Callback("first",first,gate.Task));
            var two=Task.Run(()=>Callback("second",second,gate.Task));
            var all=Task.WhenAll(one,two);
            if (one.IsCompleted || two.IsCompleted || all.IsCompleted) throw new Exception("callback gate was fabricated complete");
            gate.SetResult(true); string[] values=all.GetAwaiter().GetResult();
            if (values.Length!=2 || values[0]!="first:80410d0a" || values[1]!="second:00ff80410d0a" || local.Value!="parent")
                throw new Exception("resource/context callback result changed");
            return "resource-dotnet|parallel="+string.Join("+",values)+"|text="+text+"|empty=0|entropy=16|wall64=1|fresh=1";
        }
        case "secure-denied":
            return Task.Run(()=> {
                try { RandomNumberGenerator.Fill(new byte[8]); }
                catch (CryptographicException) {
                    if (Read(second)!="00ff80410d0a") throw new Exception("denied callback resource changed");
                    Console.WriteLine("resource-dotnet:secure-denied"); Console.Out.Flush();
                    return "resource-dotnet|secure=cryptographic-denied|fresh=1";
                }
                throw new Exception("ungranted secure entropy succeeded");
            }).GetAwaiter().GetResult();
        case "pending": {
            var done=new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            using var timer=new Timer(_=> {
                Console.WriteLine("resource-dotnet:late-callback-must-not-run"); done.TrySetResult(Read(second));
            },null,60000,Timeout.Infinite);
            Console.WriteLine("resource-dotnet:pending:timer-created"); Console.Out.Flush();
            if (done.Task.IsCompleted) throw new Exception("pending resource timer completed early");
            return done.Task.GetAwaiter().GetResult();
        }
        case "callback-error": {
            var done=new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            using var timer=new Timer(_=> {
                Console.WriteLine("resource-dotnet:callback-error:"+Read(second)); Console.Out.Flush();
                throw new InvalidOperationException("requested resource callback trap");
            },null,1,Timeout.Infinite);
            return done.Task.GetAwaiter().GetResult();
        }
        case "trap":
            Console.WriteLine("resource-dotnet:root-trap:"+Read(second)); Console.Out.Flush();
            throw new InvalidOperationException("requested resource root trap");
        case "clear": {
            int fired=0;
            var timer=new Timer(_=> { ++fired; Console.WriteLine(Read(second)); },null,60000,Timeout.Infinite);
            timer.DisposeAsync().AsTask().GetAwaiter().GetResult();
            Task.Delay(3).GetAwaiter().GetResult();
            if (fired!=0) throw new Exception("retired resource timer callback ran");
            break;
        }
        case "fresh": break;
        default: throw new Exception("unknown resource callback mode");
        }
        string bytes=Read(second);
        if (bytes!="00ff80410d0a" || local.Value!="parent") throw new Exception("fresh resource/context changed");
        Console.WriteLine("resource-dotnet:fresh:ordinary"); Console.Out.Flush();
        return "resource-dotnet|"+mode+"="+bytes+"|text="+text+"|empty=0|fresh=1";
    }
}
'''
TEXT_HEX='4772c3bcc39f6500e99baa0a'
EXPECTED={'parallel':'resource-dotnet|parallel=first:80410d0a+second:00ff80410d0a|text='+TEXT_HEX+'|empty=0|entropy=16|wall64=1|fresh=1',
          **{mode:'resource-dotnet|'+mode+'=00ff80410d0a|text='+TEXT_HEX+'|empty=0|fresh=1' for mode in ('clear','fresh')},
          'secure-denied':'resource-dotnet|secure=cryptographic-denied|fresh=1'}
PROPERTIES=('<PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Library</OutputType>'
    '<Nullable>enable</Nullable><UseSharedCompilation>false</UseSharedCompilation>'
    '<ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>'
    '<ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets></PropertyGroup>')


def project(directory:Path,outside:Path):
    require(directory.parent.resolve(strict=True)==outside.parent.resolve(strict=True)
        and ROOT not in outside.parents and outside.parent.resolve(strict=True)!=ROOT,
        'resource-dotnet-independent-originals')
    app=create(directory,'greeting');before=snapshot(app)
    declare_tasks(app)
    world=read_file(app/'wit/world.wit');require(world.count(b'world service {')==1 and LOG.encode() not in world,
                                              'resource-dotnet-original-runtime-world')
    world=world.replace(b'world service {',b'world service {\n    import '+LOG.encode()+b';',1)
    (app/'wit/world.wit').write_bytes(world)
    for name,raw in snapshot(ROOT/'wit/platform/log').items():
        target=app/'wit/deps/log'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    source=before['src/Main.cs'];marker=b'    public static Result<string, string> Greet(string name)\n    {'
    require(source.count(marker)==1,'resource-dotnet-original-forwarder')
    source=source.replace(marker,marker+b'\n        if (name.StartsWith("resource-runtime:", System.StringComparison.Ordinal)) return Result<string, string>.Ok(OutsideResourceRuntime.Library.Run(name.Substring(17)));',1)
    (app/'src/Main.cs').write_bytes(source)
    descriptor=json.loads(read_file(app/'capsule-project.json'));descriptor['limits']['logBytes']=16384
    (app/'capsule-project.json').write_bytes((json.dumps(descriptor,indent=2)+'\n').encode())
    sdk=json.loads(before['sdk-lock.json']);sdk['template'].update(sourceDigest=digest(source),witDigest=digest(world))
    (app/'sdk-lock.json').write_bytes((json.dumps(sdk,indent=2)+'\n').encode())
    outside.mkdir(mode=0o700);library=outside/'library';child=library/'child';child.mkdir(parents=True)
    (child/'Resource.cs').write_bytes(CHILD_SOURCE.encode())
    for name,raw in DATA.items():(child/name).write_bytes(raw)
    resources=''.join('<EmbeddedResource Include="'+path+'" LogicalName="outside.resource.'+name+'" />'
        for path,name in (('text.txt','text'),('binary.bin','binary'),('empty.bin','empty')))
    (child/'Child.csproj').write_bytes(('<Project Sdk="Microsoft.NET.Sdk">'+PROPERTIES+
        '<PropertyGroup><AssemblyName>'+PACKAGES[1]+'</AssemblyName></PropertyGroup><ItemGroup>'+resources+'</ItemGroup></Project>').encode())
    (library/'Library.cs').write_bytes(LIBRARY_SOURCE.encode())
    (library/'Library.csproj').write_bytes(('<Project Sdk="Microsoft.NET.Sdk">'+PROPERTIES+
        '<PropertyGroup><AssemblyName>'+PACKAGES[0]+'</AssemblyName></PropertyGroup><ItemGroup>'+ 
        '<Compile Remove="child/**" /><ProjectReference Include="child/Child.csproj" /></ItemGroup></Project>').encode())
    (library/'nuget.config').write_bytes(b'<configuration><packageSources><clear /></packageSources></configuration>')
    (library/'global.json').write_bytes(read_file(app/'global.json'))
    return app,{'originals':json.loads(inventory(snapshot(library))),'sdkLock':digest(read_file(app/'sdk-lock.json')),
        'declarations':list(DECLARATIONS),'applicationSchedulerOrContextShim':False,
        'nativeThreadsQualified':False,'threadLocalQualified':False,'asyncFlushQueuePresent':False,
        'guestCompiled':False,'signedExecution':'pending'}


def package(identity,assembly,*,child):
    dependency='' if child else '<dependencies><group targetFramework="net10.0"><dependency id="'+PACKAGES[1]+'" version="[1.0.0]" /></group></dependencies>'
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(identity+'.nuspec','<?xml version="1.0"?><package><metadata><id>'+identity+
            '</id><version>1.0.0</version><authors>SDK qualification</authors><description>Outside resource callbacks</description>'+dependency+'</metadata></package>')
        archive.writestr('lib/net10.0/'+identity+'.dll',assembly)
    return buffer.getvalue()


def source_files(directory:Path):
    return {name:raw for name,raw in snapshot(directory).items()
            if not any(part in {'bin','obj'} for part in Path(name).parts)}


def unchanged_library(directory:Path,original:bytes):
    require(inventory(source_files(directory))==original,'resource-dotnet-original-library-source-changed')


def capture(app:Path,outside:Path,tools:Path):
    library=outside/'library';feed=outside/'feed';evidence=outside/'evidence';feed.mkdir();evidence.mkdir()
    original=inventory(source_files(library));sdk=read_file(app/'sdk-lock.json')
    commands=Commands(library,evidence,build_environment(outside))
    compiler=Compiler(tools,commands,app/'vendor/lsf',offline=True,captured=True)
    compiler.run('outside-resource-callback-library',compiler.dotnet,'build',library/'Library.csproj','-c','Release',
        '-p:RestoreConfigFile='+str(library/'nuget.config'),'-p:NuGetAudit=false','-nodeReuse:false',
        '-p:UseSharedCompilation=false','-p:ImportDirectoryBuildProps=false','-p:ImportDirectoryBuildTargets=false')
    compiler.check_unchanged();unchanged_library(library,original);identities={}
    for identity,directory,is_child in ((PACKAGES[0],library,False),(PACKAGES[1],library/'child',True)):
        assembly=read_file(directory/'bin/Release/net10.0'/(identity+'.dll'),4*1024*1024)
        raw=package(identity,assembly,child=is_child);(feed/(identity.lower()+'.1.0.0.nupkg')).write_bytes(raw)
        identities[identity]={'assembly':digest(assembly),'package':digest(raw)}
    authoring.edit(app,'add',identity=PACKAGES[0],version='1.0.0')
    candidate=app/'target/resource-runtime-candidate.json';candidate.parent.mkdir(exist_ok=True)
    lock=resolve(app,candidate,dotnet=compiler.dotnet,tools=tools,
        policy={'sources':[{'name':'outside','path':str(feed),'patterns':list(PACKAGES)}]})
    rows={r['metadata']['package']:r for r in lock['artifacts'] if r['metadata'].get('package') in {p.lower() for p in PACKAGES}}
    require(set(rows)=={p.lower() for p in PACKAGES} and rows[PACKAGES[1].lower()]['id'] in rows[PACKAGES[0].lower()]['dependencies']
        and all(row['role']!='build-tool' for row in lock['artifacts']), 'resource-dotnet-exact-pure-transitive-capture')
    authoring.review(app,candidate,digest(read_file(candidate)))
    verified=verify_inputs(app,'dotnet');require(verified is not None and read_file(app/'sdk-lock.json')==sdk,
                                               'resource-dotnet-exact-reviewed-sdk')
    unchanged_library(library,original)
    root=outside.resolve(strict=True)
    for directory in (library,feed):
        require(not directory.is_symlink() and directory.resolve(strict=True).parent==root,'resource-dotnet-owned-originals')
        shutil.rmtree(directory)
    require(verify_inputs(app,'dotnet').identity==verified.identity,'resource-dotnet-offline-captured-closure')
    return {'acceptedLock':digest(read_file(app/LOCK)),'originalSource':digest(original), 'packages':identities,
        'originalLibraryAndFeedRemoved':True,'applicationSchedulerOrContextShim':False,
        'guestCompiled':False,'signedExecution':'pending'}
