"""Disposable source-explicit recomposition; preserve the original failed event."""
from pathlib import Path
import hashlib, json, os, subprocess, zipfile
from tools import rust_original_delta as delta, rust_combined_diagnostic_envelope as envelope
from tools.dotnet_guest.internal_io import core_modules, integer, encoded_integer
from tools import rust_wasi_http_profile as profile

out=Path(os.environ['RUNNER_TEMP'])/'pr1657-cooperative'; out.mkdir(exist_ok=True)
archive=Path(os.environ['RUNNER_TEMP'])/'pump-tested.zip'
assert archive.stat().st_size==2152256
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='9d0775052063fd0f66f3d1373b44850f516d4e30fae48219ed0e2d37ba9bc621'
with zipfile.ZipFile(archive) as z:
    assert len(z.infolist())==21 and z.testzip() is None
    info=json.loads(z.read('tested-tree.json'))
    assert info['sha']=='407134dd76c12361dda2562175f7c9d71186ba1c'
    assert info['base']=='480f9f15ed0e01e7283e862c1cb79312c298320b'
    assert len(info['files'])==12
    for name in info['files']:
        assert Path(name).read_bytes()==z.read('source/'+name), name
    runtime=z.read('runtime.wasm')
    assert runtime==(out/'runtime.wasm').read_bytes(), 'fresh adapter compile differs from tested source'
raw=Path('target/wasm32-unknown-unknown/release/examples/rust_wasi_http_runtime.wasm').read_bytes()
core_proof=profile.verify_compiled_core(raw,core_modules(runtime))
def graph(path):
    return json.loads(subprocess.check_output(['wasm-tools','component','wit',str(path),'--json']))
reference=graph('sdk/wasi-http-runtime/wit')
adapter_graph=graph(out/'runtime.wasm')
adapter_proof=profile.validate_adapter(reference,adapter_graph)
catalog=Path('crates/latent-component-threading/src/rust_catalogue')
base=(catalog/'combined-final-component.wasm').read_bytes()
assert len(base)==1281820 and hashlib.sha256(base).hexdigest()=='8916f44f9044242b05fe4a438f47082ff7073cfcbf08585b01312c347e338c90'
main=base[318214:318214+920667]
assert len(main)==920667 and base.count(main)==1
position=8;parts=[];children=[];ranges=[]
while position<len(base):
    start=position; kind=base[position]; size,position=integer(base,position+1); end=position+size
    assert end<=len(base)
    payload=base[position:end]
    if kind==4:
        children.append(payload); ranges.append((start,end))
        if len(children)==1:
            assert hashlib.sha256(payload).hexdigest()=='f4c4cc8fab0434c69cc0304f486741114562c3120ebbd86dac0b3403a4da3434'
            parts.append(b'\4'+encoded_integer(len(runtime))+runtime)
            position=end
            continue
    parts.append(base[start:end]); position=end
assert len(children)==3 and position==len(base)
result=base[:8]+b''.join(parts)
assert result.count(main)==1 and len(result)<2*1024*1024
# Every original outer section except runtime child 0 is byte-exact, including
# both application/root components, import declarations, instances and aliases.
start,end=ranges[0]
assert result==base[:start]+b'\4'+encoded_integer(len(runtime))+runtime+base[end:]
final=out/'recomposed.wasm';final.write_bytes(result)
subprocess.run(['wasm-tools','validate','--features','all',str(final)],check=True)
final_graph=graph(final)
old_graph_path=out/'original.wasm';old_graph_path.write_bytes(base)
old_graph=graph(old_graph_path)
assert set(profile.names(old_graph,'imports'))==set(profile.names(final_graph,'imports'))
assert set(profile.names(old_graph,'exports'))==set(profile.names(final_graph,'exports'))
for direction in ('imports','exports'):
    before=profile.names(old_graph,direction);after=profile.names(final_graph,direction)
    for name in before:
        assert before[name]['functions'].keys()==after[name]['functions'].keys()
        for key in before[name]['functions']:
            assert profile.shape(old_graph,before[name]['functions'][key])==profile.shape(final_graph,after[name]['functions'][key])
original=(catalog/'combined-original-core.wasm').read_bytes()
proof=delta.encode(original,result)
wrapped=envelope.frame(result,proof)
main_start=result.index(main); main_end=main_start+len(main)
files={'combined-final-component.wasm':result,'combined-final-prefix.bin':result[:main_start],
       'combined-final-suffix.bin':result[main_end:],'combined-original-delta.bin':proof}
for name,payload in files.items():
    (out/name).write_bytes(payload)
    (catalog/name).write_bytes(payload)
identity=lambda data:{'bytes':len(data),'sha256':'sha256:'+hashlib.sha256(data).hexdigest()}
record={'schemaVersion':'latent.rust.http.callback-recomposition-diagnostic.v1',
    'sourceCommit':subprocess.check_output(['git','rev-parse','HEAD']).decode().strip(),
    'originalApplicationCompilerEventUnchanged':True,'originalCompilerOutcome':'failed',
    'originalGraph':identity(base),'originalAdapter':identity(children[0]),'newAdapter':identity(runtime),
    'newGraph':identity(result),'originalApplication':identity(original),'main':identity(main),
    'mainOffset':main_start,'delta':identity(proof),'wrapped':identity(wrapped),
    'originalOtherTopLevelSectionsExact':True,'originalApplicationAndRootComponentsExact':True,
    'adapterCoreProof':core_proof,'adapterGraphProof':adapter_proof,
    'applicationRecompiled':False,'adapterRecompiled':True,'normalRustBuilderRouteOpened':False,
    'notFinalHeadQualification':True}
(out/'recomposition.json').write_text(json.dumps(record,indent=2)+'\n')
p=Path('tools/rust_thread_http_combined_package.py');s=p.read_text()
old="WRAPPED = {'bytes': 1629518, 'sha256': 'sha256:5634429a97b4a3f0cf8afca2877dbbddbc98f5e4fd7bf59ae6f7f50e780c2e17'}"
assert s.count(old)==1;s=s.replace(old,'WRAPPED = '+repr(identity(wrapped)))
old="    base = read_file(artifact / 'combined-component.wasm', 2 * 1024 * 1024)\n"
assert s.count(old)==1
s=s.replace(old,"    require(digest(read_file(artifact / 'combined-component.wasm', 2 * 1024 * 1024)) == 'sha256:' + PINS['combined-component.wasm'][1], 'rust-http-thread-original-composition-retained')\n    base = read_file(catalogue / 'combined-final-component.wasm', 2 * 1024 * 1024)\n")
s=s.replace("'applicationRecompiled': False,", "'applicationRecompiled': False, 'adapterRecompiledForCallbackDiagnostic': True,")
p.write_text(s)
(out/'diagnostic-source.patch').write_bytes(subprocess.check_output(['git','diff','--binary']))
print(json.dumps(record,indent=2))
