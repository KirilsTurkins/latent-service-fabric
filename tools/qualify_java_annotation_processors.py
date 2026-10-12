#!/usr/bin/env python3
"""Exact-approved local processor, generated component and signed-node control.

Host JVM source checks and real guest execution remain separately identified.
This creates only isolated synthetic fixture trust and publishes no runtime.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time
if __package__ in {None, ""}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.java_capsule_project import create
from tools.java_dependency_authoring import edit,review
from tools.java_dependency_resolution import resolve
from tools.java_capsule_build import build
from tools.build_snapshot import digest
from tools.application_dependency_store import DependencyError
from tools.build_observation import build_environment
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT,fresh
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_scenario import configure_node,connect,stop
from tools.phase2_operator_process import read_json,write_json,stopped_record,require
from tools.rust_capsule_node import RecordingClient,deploy,call,assert_value
from tools.java_server_node import IDLE_OWNERS
from tools.guest_runtime_grants import configure as runtime_config,grant

CORE_OWNERS=IDLE_OWNERS-{'http-exchanges','http-buffer-reservations'}
def observe_idle(client,evidence,name):
    deadline=min(client.deadline,time.monotonic()+5)
    for _attempt in range(100):
        value=client.call('node','get','operator-workflow-test')['data']['inventory']
        topology=value['topology']
        require(topology['available'] and topology['complete'],'processor-ownership-unavailable')
        entries={row['name']:row for row in topology['entries']}
        require(CORE_OWNERS<=entries.keys(),'processor-core-ownership-missing')
        cells=value['cellCapacity']
        require(cells and all(row['observationAvailable'] for row in cells),'processor-cell-observation-unavailable')
        idle=(all(entries[key]['activeCount']=='0' for key in CORE_OWNERS)
            and all(int(row['activeCount'])==0 for row in topology['entries'] if row['ownership']=='activation-scoped')
            and all(int(row['activeCount'])==0 and int(row['configuredCount'])==0 for row in topology['entries'] if row['ownership']=='service-resident')
            and all(row['active']==0 and row['quarantined']==0 and row['available']==row['total'] for row in cells)
            and all(int(count)==0 for count in value['quotas']['usage'].values()))
        if idle:
            write_json(evidence/(name+'.json'),value)
            return value
        require(time.monotonic()<deadline,'processor-retirement-deadline')
        time.sleep(.025)
    raise RuntimeError('processor-retirement-observation-bound')

def fixture(root,commands,gradle,peer_port,sentinel):
    source=root/'processor-source/outside/processor';source.mkdir(parents=True)
    (source/'Generate.java').write_text('''package outside.processor;
    import java.lang.annotation.*;
    @Retention(RetentionPolicy.SOURCE) @Target(ElementType.TYPE)
    public @interface Generate {}
    ''')
    (source/'Helper.java').write_text('''package outside.processor;
    public final class Helper { public static String text() { return "Captured "; } }
    ''')
    (source/'ChosenProcessor.java').write_text('''package outside.processor;
    import javax.annotation.processing.*;
    import javax.lang.model.*;
    import javax.lang.model.element.*;
    import java.util.Set;
    @SupportedAnnotationTypes("outside.processor.Generate")
    @SupportedSourceVersion(SourceVersion.RELEASE_25)
    public final class ChosenProcessor extends AbstractProcessor {
     private boolean emitted;
     public boolean process(Set<? extends TypeElement> types, RoundEnvironment round) {
      if (!emitted && !types.isEmpty()) {
       emitted=true;
       if (System.getenv("JAVA_HOME") != null) throw new AssertionError("ambient parent environment survived");
       try { java.nio.file.Files.readString(java.nio.file.Path.of(/*PARENT_INPUT*/));
        throw new AssertionError("ambient input readable"); } catch (java.io.IOException denied) { }
       try { java.nio.file.Files.writeString(java.nio.file.Path.of(System.getProperty("user.dir"), "dev/latent/app/Capsule.java"), "changed");
        throw new AssertionError("original source writable"); } catch (java.io.IOException denied) { }
       try (var connection=new java.net.Socket()) {
        connection.connect(new java.net.InetSocketAddress("127.0.0.1", /*PEER*/), 1000);
        throw new AssertionError("parent network reachable");
       } catch (java.io.IOException denied) { }
       try (var out=processingEnv.getFiler().createSourceFile("outside.generated.Message").openWriter()) {
        out.write("package outside.generated; public final class Message { public static String greet(String name) { return ");
        out.write((char)34); out.write(Helper.text()); out.write((char)34); out.write("+name; } }");
       } catch (Exception error) { throw new RuntimeException(error); }
      }
      return true;
     }
    }
    '''.replace('/*PEER*/',str(peer_port)).replace('/*PARENT_INPUT*/',json.dumps(str(sentinel))))
    classes=root/'processor-classes';classes.mkdir()
    commands.run('processor-source-compile','javac','--release','25','-proc:none','-d',classes,*sorted(source.glob('*.java')))
    helper=root/'unlisted-helper.jar';processor=root/'unlisted-processor.jar'
    commands.run('processor-helper-jar','jar','--create','--file',helper,'-C',classes,'outside/processor/Helper.class')
    commands.run('processor-main-jar','jar','--create','--file',processor,'-C',classes,'outside/processor/Generate.class','-C',classes,'outside/processor/ChosenProcessor.class')
    app=create(root/'application','greeting','my-greeting')
    p=app/'src/dev/latent/app/Capsule.java'
    p.write_text(p.read_text().replace('public final class Capsule','@outside.processor.Generate\npublic final class Capsule').replace('"Hello, " + trimmed + "!"','outside.generated.Message.greet(trimmed)'))
    edit(app,'add-local',local_id='developer-private-helper/7',jar=helper,processor_input=True)
    edit(app,'add-local',local_id='developer-private-processor/13',jar=processor,dependencies=('developer-private-helper/7',),
     processor_classes=('outside.processor.ChosenProcessor',))
    candidate=root/'candidate.json'
    resolve(app,candidate,gradle=gradle)
    review(app,candidate,digest(candidate.read_bytes()))
    return app

def node_control(root,native,native_identity):
    record=read_json(root/'signed/release-set.json')['releases'][0]
    evidence=root/'node';evidence.mkdir()
    with owned_cancellation() as cancellation,tempfile.TemporaryDirectory(prefix='java-processors-node-') as temporary:
     work=Path(temporary)
     for name in ('client','node'): (work/name).mkdir()
     client=RecordingClient(native/'latent',work/'client',cancellation,time.monotonic()+180,evidence=evidence/'controls')
     config=configure_node(work/'node',root/'signed','examples');settings=read_json(config)
     settings['engine']={'javaGuest':True};settings['providers']={'formatVersion':1,'bindings':[]}
     original_audit=dict(settings['audit']);runtime_config(settings,('greeting',),language='java');settings['audit']=original_audit
     settings['execution']['maximumWallTimeMillis']=120000
     settings['budgetProfile']={'mode':'phase3','maximumOutboundRequests':8,'maximumBlobReadBytes':65536,'maximumBlobWriteBytes':65536}
     settings['capabilityPolicies']={'formatVersion':1,'maximumControlJobs':2,'store':{'maximumRecords':64,'maximumOutcomes':128,'maximumCatalogBytes':4194304,'maximumReadOwners':64,'maximumPageRecords':16}}
     config.write_bytes(json.dumps(settings,separators=(',',':')).encode())
     node=connect(client,native/'latentd',work/'node',config,'examples',1)
     try:
      observe_idle(client,evidence,'before-publication')
      package=root/'signed/my-greeting'
      unsigned=client.call('release','publish-package',package/'package','--operation-id','unsigned-denied','--expected-generation','0',codes=(4,))
      require(unsigned['error']['code']=='permission-denied','processor-unsigned-package-admitted')
      published=client.call('release','publish-package',package/'package','--evidence',package/'evidence/index.json','--operation-id','publish','--expected-generation','0')
      publication=published['data']['operation']['publication']['id']
      targets={'greeting':deploy(client,package/'deployment.json',publication)};result={}
      grant(client,node,root/'signed',targets,{'greeting':publication},result,language='java')
      calls=[]
      for ordinal,(arguments,expected,code) in enumerate([(['Ada'],[{'ok':'Captured Ada'}],0),([''],[{'err':'Please enter a name.'}],3),(['Bob'],[{'ok':'Captured Bob'}],0)]):
       observed=call(client,targets['greeting'],'greeting','greet',arguments,'processor-call-'+str(ordinal))
       assert_value(client,observed,expected,code)
       calls.append(observed)
       observe_idle(client,evidence,'after-'+str(ordinal))
      stop(client,node);shutdown=stopped_record(node)
      require(shutdown['record']['clean'] and shutdown['reaped'],'processor-node-shutdown-unconfirmed')
      write_json(evidence/'processor-qualified.json',{'status':'passed','scope':'actual signed contained generated-source greeting only',
        'nativeTuple':native_identity,'unsignedDenied':unsigned,'runtimeGrantDenied':result['runtimeGrantDenied'],
        'calls':calls,'shutdown':shutdown,'componentDigest':record['componentDigest']})
      print(json.dumps({'stage':'signed-node','status':'passed','calls':len(calls),'cleanShutdown':True}),flush=True)
     finally:
      node.close()

def ownership_negatives(root,commands):
    """Run the actual parse-only owner against source identities, not filenames."""
    control=root/'source-owner/dev/latent/compiler/SourceOwnership.java'
    control.parent.mkdir(parents=True)
    shutil.copyfile(ROOT/'sdk/java-guest/processors/SourceOwnership.java',control)
    cases={
        'original-class-collision':('outside/App.java','package outside; class App {}',
            'generated-source-owner-collision'),
        'original-nested-class-collision':('outside/Other.java','package outside; class App$Nested {}',
            'generated-source-owner-collision'),
        'platform-package':('java/Owned.java','package java; class Owned {}',
            'generated-source-overrides-platform'),
        'escaped-platform-package':('java/Owned.java',r'package \u006aava; class Owned {}',
            'generated-source-overrides-platform'),
        'generated-package-path':('wrong/Owned.java','package outside; class Owned {}',
            'generated-source-package-path-mismatch'),
        'invalid-generated-source':('outside/Owned.java','package outside; class Owned {',
            'generated-source-parse-failed'),
    }
    observations=[]
    for name,(relative,text,reason) in cases.items():
        directory=fresh(root/('ownership-'+name))
        original=directory/'original/outside'
        original.mkdir(parents=True)
        (original/'App.java').write_text('package outside; class App { static class Nested {} }',encoding='utf-8')
        generated=directory/'generated'
        target=generated/relative
        target.parent.mkdir(parents=True)
        target.write_text(text,encoding='utf-8')
        manifest=directory/'inputs.tsv'
        manifest.write_text('original\toutside/App.java\ngenerated\t'+relative+'\n',encoding='utf-8')
        try:
            commands.run('ownership-'+name,'java','-Xmx256m','--source','25',control,original.parent,generated,manifest)
        except ValueError:
            require(commands.records[-1]['exitCode']==1,'processor-source-owner-negative-incomplete')
            ordinal=len(commands.records)-1
            stderr=root/'logs'/f'{ordinal:02d}-ownership-{name}.stderr.txt'
            expected='java-annotation-processor-'+reason
            require(stderr.read_text(encoding='utf-8').strip()==expected,
                    'processor-source-owner-negative-wrong-reason')
            observations.append({'case':name,'reason':expected,'exitCode':1})
        else:
            raise RuntimeError('processor-source-owner-accepted-'+name)
    write_json(root/'source-ownership-negatives.json',{'status':'passed','cases':observations,
        'scope':'actual pinned Javac parse-only source ownership, not guest execution'})

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('output','native-directory','native-tuple','wasi-sdk','read-only-cache'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--gradle',default='gradle')
    args=parser.parse_args(argv)
    require(args.output.absolute()!=ROOT and ROOT not in args.output.absolute().parents,'processor-fixture-must-be-outside-runtime')
    native=args.native_directory
    products={name:native/name for name in ('latent','latentd','capsule_contracts','package','capsule_authoring')}
    native_identity=ordinary_tuple(args.native_tuple,products)
    root=fresh(args.output)
    selected=fresh(root/'native-products')
    for name,binary in products.items():
        shutil.copyfile(binary,selected/name)
        (selected/name).chmod(0o700)
    require(ordinary_tuple(args.native_tuple,{name:selected/name for name in products})==native_identity,
            'processor-native-capture-changed')
    native=selected
    products={name:selected/name for name in products}
    environment=build_environment(root)
    if 'JAVA_HOME' in os.environ: environment['JAVA_HOME']=os.environ['JAVA_HOME']
    commands=Commands(ROOT,root,environment,deadline_seconds=1800,command_seconds=60)
    stage='source-fixture'
    peer=None
    try:
        peer=socket.socket()
        peer.bind(('127.0.0.1',0))
        peer.listen(1)
        peer.settimeout(.05)
        peer_port=peer.getsockname()[1]
        sentinel=root/'parent-only-sentinel.txt'
        sentinel.write_text('synthetic owned nonsecret control',encoding='utf-8')
        app=fixture(root,commands,args.gradle,peer_port,sentinel)
        stage='actual-source-ownership-negatives'
        ownership_negatives(root,commands)
        parameters=dict(gradle=args.gradle,timeout=900,read_only_cache=args.read_only_cache)
        inputs=(products['capsule_contracts'],products['package'],'https://github.com/KirilsTurkins/latent-service-fabric',args.wasi_sdk)
        stage='unapproved-denial'
        try: build(app,root/'unapproved',*inputs,**parameters)
        except DependencyError as error:
            require(str(error)=='java-annotation-processors-require-exact-executable-approval','processor-unapproved-control-wrong-failure')
        else: raise RuntimeError('unapproved-processor-executed')
        approval=read_json(root/'unapproved/executable-input-approval-request.json')
        stage='approved-contained-build'
        approved=build(app,root/'approved',*inputs,**parameters,executable_approval=approval['identity'])
        require((approved/'java-annotation-processors.json').is_file(),'processor-profile-missing')
        try:
            connection,_address=peer.accept()
        except TimeoutError:
            write_json(root/'containment.json',{'status':'passed','parentLoopbackPeerAccepted':0,
                'parentEnvironmentDenied':True,'ambientInputDenied':True,'originalSourceWriteDenied':True,
                'scope':'actual declared processor checks, not hostile multitenant isolation'})
        else:
            connection.close()
            raise RuntimeError('processor-reached-parent-loopback-peer')
        peer.close()
        stage='isolated-fixture-signing'
        commands.run('sign-fixture',products['capsule_authoring'],'demo-sign',root/'signed',approved)
        stage='signed-node'
        node_control(root,native,native_identity)
        require(ordinary_tuple(args.native_tuple,products)==native_identity,'processor-native-products-changed')
        require(time.monotonic()<commands.deadline,'processor-qualification-deadline')
        write_json(root/'qualification.json',{'status':'passed','scope':'exact-approved-contained-processor-and-real-signed-greeting',
            'nativeTuple':native_identity,'commands':commands.records,'component':file_identity(approved/'component.wasm'),
            'processorProfile':file_identity(approved/'java-annotation-processors.json'),
            'guestReceipt':file_identity(root/'node/processor-qualified.json')})
        print(json.dumps({'status':'passed','receipt':str(root/'qualification.json')}))
    except BaseException as error:
        write_json(root/'FAILED.json',{'status':'failed','stage':stage,'commands':commands.records,
            'reason':str(error) if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__})
        raise
    finally:
        if peer is not None:
            peer.close()
    return 0

if __name__=='__main__':
    raise SystemExit(main())
