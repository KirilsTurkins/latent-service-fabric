"""Bounded public-input and metadata controls; no SDK, native or guest execution."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import dotnet_resource_originals as original, dotnet_resource_recomposition as metadata
from tools.build_observation import finish_observation
from tools.dotnet_guest import internal_io
from tools.rust_capsule_project import ROOT, digest, inventory, snapshot

PARAMETERS={'compiler':'native-aot-llvm','bindings':'wit-bindgen-csharp','language':'csharp',
 'target':'wasi-wasm','runtime':'native-aot','locked':True,'ambientWasi':False}


class DotnetResourceTenants(unittest.TestCase):
 def producer(self,kind):
  row=original.SPECS[kind]
  return {'id':row['artifact'],'name':row['name'],'size_in_bytes':row['bytes'],'digest':row['digest'],
   'expired':False,'workflow_run':{'id':row['run'],'head_sha':row['head'],
    'repository_id':1337591365,'head_repository_id':1337591365}}

 def fixture(self,root,source=b'{}',recipe=b'{}'):
  root.mkdir();component=b'own-unit-component';identity={'sha256':digest(component),'bytes':len(component)}
  observed=finish_observation(repository='https://github.com/example/fixture',revision='fixture',inventory=source,
   component=component,materials=[{'name':'package-inputs',**original.PACKAGE_INPUTS},
    {'name':'toolchain-config','digest':digest(b'unit-toolchain'),'size':14},
    {'name':'wasm-tools','digest':digest(b'unit-pinned-codec'),'size':17},
    *[{'name':name,'digest':digest(('unit-'+name).encode()),'size':len('unit-'+name)}
      for name in ('dotnet','wit-bindgen','closed-runtime','compiler-inputs','dependency-lock','contracts-tool','packager')]],
   started=1,finished=1,elapsed=0,reproducible=False)
  observed['buildType']='https://latent.dev/build/dotnet-capsule/v1';observed['parameters']=PARAMETERS
  obs=json.dumps(observed).encode()
  marker={'componentDigest':identity['sha256'],'observationDigest':digest(obs),'sourceDigest':digest(source)}
  rows={'component.wasm':component,'build-observation.json':obs,'source-inputs.json':source,
   'recipe-inputs.json':recipe,'BUILD-COMPLETE.json':json.dumps(marker).encode(),'compatibility-report.json':b'{}'}
  expected={name:{'sha256':digest(raw),'bytes':len(raw)} for name,raw in rows.items()}
  for name,raw in rows.items():(root/name).write_bytes(raw)
  return expected,identity

 def controls(self,expected,component):
  stack=ExitStack();stack.enter_context(patch.object(original,'RECORDS',expected))
  stack.enter_context(patch.object(original,'COMPONENT',component));stack.enter_context(patch.object(metadata,'COMPONENT',component))
  return stack

 def test_original_archive_identity_is_closed_for_both_distinct_producers(self):
  for kind in original.SPECS:
   value=self.producer(kind);self.assertFalse(original.validate_metadata(kind,value)['wholeArchiveDigestVerified'])
   for field in ('id','name','size_in_bytes','digest','expired','head_sha','run','repo'):
    changed=copy.deepcopy(value)
    if field=='head_sha':changed['workflow_run']['head_sha']='0'*40
    elif field=='run':changed['workflow_run']['id']=0
    elif field=='repo':changed['workflow_run']['repository_id']=0
    elif field=='expired':changed[field]=True
    else:changed[field]='foreign'
    with self.subTest(kind=kind,field=field),self.assertRaisesRegex(RuntimeError,'fixed-original-artifact'):
     original.validate_metadata(kind,changed)

 def test_all_six_original_document_preimages_are_mandatory(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)/'original';expected,component=self.fixture(root)
   with self.controls(expected,component):
    original.validate_records(root)
    for name in expected:
     raw=(root/name).read_bytes();(root/name).write_bytes(raw+b'changed')
     with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'original-document-preimage'):
      original.validate_records(root)
     (root/name).write_bytes(raw)

 def test_rehashed_foreign_component_and_package_material_still_fail_the_binding(self):
  for mode in ('component','package'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as t:
    root=Path(t)/'original';expected,component=self.fixture(root)
    observed=json.loads((root/'build-observation.json').read_bytes())
    if mode=='component':observed['componentDigest']='sha256:'+'0'*64
    else:next(row for row in observed['materials'] if row['name']=='package-inputs')['size']+=1
    raw=json.dumps(observed).encode();(root/'build-observation.json').write_bytes(raw)
    expected['build-observation.json']={'sha256':digest(raw),'bytes':len(raw)}
    marker=json.loads((root/'BUILD-COMPLETE.json').read_bytes());marker['observationDigest']=digest(raw)
    raw=json.dumps(marker).encode();(root/'BUILD-COMPLETE.json').write_bytes(raw)
    expected['BUILD-COMPLETE.json']={'sha256':digest(raw),'bytes':len(raw)}
    with self.controls(expected,component),self.assertRaisesRegex(RuntimeError,'original-build-bindings'):
     original.validate_records(root)

 def test_original_public_project_and_seed_bytes_are_complete_and_source_bound(self):
  from tools.dotnet_guest.project import create
  from tools.dotnet_standard_console_fixture import declare
  for mode in ('valid','missing-wit','foreign-wit','foreign-project','foreign-seed'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as t:
    base=Path(t);project=create(base/'prototype','greeting');declare(project)
    files={n:raw for n,raw in snapshot(project).items() if n.startswith('wit/') or n=='capsule-project.json'}
    files['vendor/lsf/Cargo.toml']=(ROOT/'Cargo.toml').read_bytes()
    seeds={n:(ROOT/n).read_bytes() for n in original.SEEDS}
    source=json.loads(inventory(files));recipe=json.loads(inventory(seeds))
    if mode=='missing-wit':source.pop('wit/world.wit')
    elif mode=='foreign-wit':source['wit/world.wit']['digest']='sha256:'+'0'*64
    elif mode=='foreign-project':source['capsule-project.json']['size']+=1
    elif mode=='foreign-seed':recipe[original.SEEDS[0]]['digest']='sha256:'+'0'*64
    expected,component=self.fixture(base/'original',json.dumps(source).encode(),json.dumps(recipe).encode())
    fetched=[]
    def fetch(name):
     fetched.append(name);return files['vendor/lsf/Cargo.toml'] if name=='Cargo.toml' else seeds[name]
    with self.controls(expected,component):
     if mode=='valid':
      actual,actual_seeds=original.original_public_files(base/'original',base/'public',fetch)
      self.assertEqual(actual,files);self.assertEqual(actual_seeds,seeds)
      self.assertEqual(fetched,['Cargo.toml',*original.SEEDS])
     else:
      with self.assertRaisesRegex(RuntimeError,'original-public-|original-recipe-'):
       original.original_public_files(base/'original',base/'public',fetch)

 def test_public_source_fetch_refuses_unselected_paths_before_network(self):
  with patch.object(original.urllib.request,'urlopen') as fetch:
   for name in ('../Cargo.toml','src/private.cs','sdk/dotnet-guest/runtime/other.wit'):
    with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'source-allowlist'):
     original.public_git_file(name)
  fetch.assert_not_called()

 def test_component_recovery_requires_exact_adapter_entropy_materials_and_three_children(self):
  header=b'\0asm\x0d\0\x01\0'
  def section(kind,raw):return bytes([kind])+internal_io.encoded_integer(len(raw))+raw
  adapter=header;entropy=header+section(0,b'\x01e');application=header+section(0,b'\x01a'+b'x'*(2*1024**2))
  raw=header+b''.join(section(4,v) for v in (application,adapter,entropy))
  component={'sha256':digest(raw),'bytes':len(raw)}
  a={'digest':digest(adapter),'size':len(adapter)};e={'digest':digest(entropy),'size':len(entropy)}
  observed={'materials':[{'name':'closed-logging-runtime',**a},{'name':'noncrypto-entropy',**e}]}
  with patch.object(metadata,'COMPONENT',component),patch.object(metadata,'ADAPTER',a),patch.object(metadata,'ENTROPY',e):
   result=metadata.recover_components(raw,observed);self.assertEqual(result['application'],application)
   changed=copy.deepcopy(observed);changed['materials'][1]['size']+=1
   with self.assertRaisesRegex(RuntimeError,'original-material'):metadata.recover_components(raw,changed)
   with self.assertRaisesRegex(RuntimeError,'original-component'):metadata.recover_components(raw+b'changed',observed)

 def test_real_command_runner_creates_owned_parent_before_codec_selection(self):
  from tools import qualify_dotnet_resource_tenants as campaign
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);binary=root/'never-executed';binary.write_bytes(b'owned-source-control')
   with patch.object(campaign.sys,'platform','linux'),patch.object(campaign.sys,'version_info',(3,13)), \
    patch.object(campaign,'native_products',return_value=({'latent':binary},{})), \
    patch.object(campaign.subprocess,'check_output',return_value=b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n'), \
    patch.object(campaign.originals,'acquire',return_value=(root/'original',{})), \
    patch.object(campaign.shutil,'which',return_value=None), \
    self.assertRaisesRegex(RuntimeError,'dotnet-resource-pinned-codec-required'):
    campaign.run(root/'native',{},root/'output')
   self.assertTrue((root/'output/commands/logs').is_dir())
   failure=json.loads((root/'output/FAILED.json').read_bytes())
   self.assertEqual(failure['guard'],'dotnet-resource-pinned-codec-required')
   self.assertEqual(binary.read_bytes(),b'owned-source-control')

 def test_new_observation_refuses_missing_derivation_witnesses_before_mutation(self):
  for flag in ('nativeAotCompilation','allCoreModulesByteIdentical','publicGraphEquivalent','actualProductionComposition','selectedComponent'):
   with self.subTest(flag=flag),tempfile.TemporaryDirectory() as t:
    root=Path(t);artifact=root/'artifact';expected,component=self.fixture(artifact)
    selected=root/'selected.wasm';selected.write_bytes(b'new-metadata')
    proof={'nativeAotCompilation':False,'allCoreModulesByteIdentical':True,'publicGraphEquivalent':True,
     'actualProductionComposition':True,'originalComponent':component,
     'selectedComponent':{'sha256':digest(selected.read_bytes()),'bytes':selected.stat().st_size}}
    proof.pop(flag);before={n:(artifact/n).read_bytes() for n in expected}
    with self.controls(expected,component),self.assertRaisesRegex(RuntimeError,'metadata-derivation-proof'):
     metadata.publish_build(artifact,selected,proof,root/'evidence',None,'a'*40)
    self.assertFalse((root/'evidence').exists());self.assertEqual(before,{n:(artifact/n).read_bytes() for n in expected})

 def test_new_metadata_observation_preserves_old_records_and_carries_explicit_ancestry_assets(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);artifact=root/'artifact';expected,component=self.fixture(artifact)
   (artifact/'capsule.json').write_bytes(json.dumps({'component':{'digest':component['sha256']}}).encode())
   (artifact/'deployment.json').write_bytes(json.dumps({'spec':{'release':component['sha256']}}).encode())
   (artifact/'package-source.json').write_bytes(json.dumps({'layers':[{'source':'component.wasm','path':'component.wasm','role':'component','mediaType':'application/wasm'},
    {'source':'capsule.json','path':'capsule.json','role':'capsule-manifest','mediaType':'application/json'},
    {'source':'compatibility-report.json','path':'compatibility-report.json','role':'asset','mediaType':'application/json'}]}).encode())
   selected=root/'selected.wasm';selected.write_bytes(b'unit-selected-metadata')
   proof={'nativeAotCompilation':False,'allCoreModulesByteIdentical':True,'publicGraphEquivalent':True,
    'actualProductionComposition':True,'originalComponent':component,
    'selectedComponent':{'sha256':digest(selected.read_bytes()),'bytes':selected.stat().st_size}}
   before={n:(artifact/n).read_bytes() for n in expected}
   with self.controls(expected,component):
    marker=metadata.publish_build(artifact,selected,proof,root/'evidence',None,'a'*40)
   self.assertFalse(marker['nativeAotCompilation'])
   new=json.loads((artifact/'build-observation.json').read_bytes());self.assertEqual(new['parameters'],PARAMETERS)
   for name in ('BUILD-COMPLETE.json','build-observation.json','source-inputs.json','recipe-inputs.json','compatibility-report.json'):
    self.assertEqual((root/'evidence'/('original-'+name)).read_bytes(),before[name])
   self.assertEqual((artifact/'dotnet-inherited-aot-observation.json').read_bytes(),before['build-observation.json'])
   self.assertEqual((artifact/'dotnet-metadata-derivation.json').read_bytes(),(root/'evidence/derivation.json').read_bytes())
   self.assertEqual(next(r for r in new['materials'] if r['name']=='metadata-only-no-native-aot-compilation')['digest'],
    digest((root/'evidence/derivation.json').read_bytes()))
   self.assertFalse(json.loads((artifact/'dotnet-metadata-derivation.json').read_bytes())['nativeAotCompilation'])


if __name__=='__main__':unittest.main()
