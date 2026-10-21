"""One normal C build, five finite observations; no seventeen-case qualification."""
from __future__ import annotations
import argparse,json,os,sys,tempfile,time
from pathlib import Path
if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import c_capsule_build as compiler,c_thread_minimal_fixture as fixture
from tools import c_thread_runtime_node as original,host_codec_native_products as native
from tools.diagnose_c_thread_prefix import observe
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require,stopped_record
from tools.phase2_operator_scenario import connect,stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_c_thread_runtime import materials,native_evidence,build_evidence
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient,configure,delete_all,deploy,sample
from tools.rust_capsule_project import ROOT,fresh,inventory,read_json,snapshot,write_json
from tools.sdk_provider_scenario import start_provider
HELPERS=('tools/c_thread_minimal_fixture.py','tools/diagnose_c_thread_minimal.py',
 'tools/diagnose_c_thread_prefix.py','tools/c_thread_prefix_inputs.py',
 '.github/workflows/c-thread-minimal-diagnostic.yml')
def source_inputs():return {**materials(),**{n:file_identity(ROOT/n)for n in HELPERS}}

def run(prepared,output):
 require(sys.platform=='linux' and sys.version_info>=(3,13)and os.geteuid()!=0,'c-minimal-unprivileged-linux-python313')
 output=output.absolute()
 require(output!=ROOT and output not in ROOT.parents and ROOT not in output.parents,'c-minimal-output-outside-checkout')
 output=fresh(output);before=source_inputs();origin,source,tools=native_evidence(native,prepared)
 started=time.monotonic();stage='normal-diagnostic-application';commands=None
 record={'schemaVersion':'latent.c.thread-minimal.diagnostic.v1','status':'incomplete','qualification':False,
  'diagnosticOnly':True,'full17ProgrammeQualified':False,'nativeProductsRebuilt':False,
  'guestComponentsCompiled':0,'materials':before,'nativeOrigin':origin,'nativeSource':source,'outcomes':[]}
 try:
  app=fixture.prepare(output/'application');captured=inventory(snapshot(app))
  stage='one-normal-captured-c-build'
  artifact=compiler.build(app,output/'build',tools['capsule_contracts'],tools['package'],
   'https://github.com/KirilsTurkins/latent-service-fabric')
  record.update(guestComponentsCompiled=1,build=build_evidence(artifact,captured))
  commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=600,command_seconds=90)
  stage='normal-signing'
  signed=output/'signed';commands.run('normal-sign-diagnostic-component',tools['capsule_authoring'],'demo-sign',signed,artifact)
  stage='five-diagnostic-observations'
  with owned_cancellation()as cancellation,tempfile.TemporaryDirectory(prefix='lsf-c-minimal-')as temp,original.owned_cleanup(record)as cleanup:
   work=Path(temp)
   for name in('client','node','peer'):(work/name).mkdir(mode=0o700)
   client=RecordingClient(tools['latent'],work/'client',cancellation,min(commands.deadline,time.monotonic()+240),evidence=output/'controls')
   peer,port=start_provider(client,work/'peer',maximum_seconds=240);cleanup.callback(peer.close)
   config,settings=configure(work/'node',signed,port,language='c');original.configure(settings,read_json(artifact/'capsule.json'))
   config.write_bytes((json.dumps(settings,sort_keys=True,separators=(',',':'))+'\n').encode());record['configuration']=settings
   node=connect(client,tools['latentd'],work/'node',config,'examples',0);cleanup.callback(node.close)
   record['startup']=node.startup_record;probe=Probe(node,file_identity(tools['latentd']));release=signed/original.SERVICE
   published=client.call('release','publish-package',release/'package','--evidence',release/'evidence/index.json',
    '--operation-id','c-minimal-publish','--expected-generation','0')
   require(published['outcomeKnown']is True and published['data']['release']['digest']==record['build']['component']['sha256'],
    'c-minimal-exact-normal-component-publication')
   publication=published['data']['operation']['publication']['id'];target=deploy(client,release/'deployment.json',publication)
   grants=original.install(client,node,target)
   target=deploy(client,release/'deployment.json',publication,generation=str(target['generation']),grants=grants)
   for mode in fixture.MODES:
    record['outcomes'].append(observe(client,node,probe,target,output,mode))
    write_json(output/('progress-'+mode+'.json'),record)
   delete_all(client,[target['name']]);record['afterDelete']=sample(client,probe,'c-minimal-after-delete',0)
   stop(client,node);record['nodeShutdown']=stopped_record(node);record['peerShutdown']=stop_observation_peer(peer)
   require(record['nodeShutdown']['reaped']is True and record['nodeShutdown']['record']['clean']is True,'c-minimal-clean-reaped-node')
   cancellation.check()
  stage='source-build-product-and-bounds-fence'
  require(source_inputs()==before and native_evidence(native,prepared)==(origin,source,tools)
   and inventory(snapshot(app))==captured and build_evidence(artifact,captured)==record['build']
   and len(record['outcomes'])==5 and client.calls<=384 and time.monotonic()-started<=1100
   and time.monotonic()<commands.deadline,'c-minimal-unchanged-source-and-original-bounds')
  record['rootPrefixControlPassed']=(record['outcomes'][0]['exitCode']==3 and record['outcomes'][0]['decoded']==[{'err':'application-error'}])
  require(record['rootPrefixControlPassed'],'c-minimal-root-prefix-control')
  record.update(status='observed',commands=commands.records)
  write_json(output/'diagnostic.json',record);return record
 except BaseException as error:
  record.update(status='failed',stage=stage,errorCategory=type(error).__name__,commands=commands.records if commands is not None else [])
  try:write_json(output/'FAILED.json',record)
  except BaseException:pass
  raise
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prepared',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
 args=parser.parse_args();value=run(args.prepared,args.output);print(json.dumps({'status':value['status'],'qualification':False,'attempts':len(value['outcomes'])}))
