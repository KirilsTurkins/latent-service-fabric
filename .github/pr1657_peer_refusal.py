from pathlib import Path
import json,re,runpy,sys
sys.path.insert(0,str(Path.cwd()))
from tools import rust_thread_http_combined_node as controller
original_environment=controller.build_environment
controller.build_environment=lambda directory: {**original_environment(directory), 'LSF_JAVA_HTTP_REFUSAL_DIAGNOSTIC':'1'}
original_invoke=controller.invoke
def invoke(client,node,target,peer,probe,output,digest):
    try:
        return original_invoke(client,node,target,peer,probe,output,digest)
    finally:
        node.drain()
        lines=[line.decode('ascii') for line in bytes(node.buffers[1]).splitlines()
               if re.fullmatch(rb'LSF-JAVA-HTTP-REFUSAL-V1 (?:typed-http-conversion|pool-active-dial) (?:resource-exhausted|admission-rejected) (?:busy|capacity|unclassified)',line)]
        (output/'closed-http-refusal.json').write_text(json.dumps({'diagnosticOnly':True,'records':lines[:16],'rawErrorRetained':False})+'\n')
controller.invoke=invoke
runpy.run_path('.github/pr1657_peer_observation.py')
