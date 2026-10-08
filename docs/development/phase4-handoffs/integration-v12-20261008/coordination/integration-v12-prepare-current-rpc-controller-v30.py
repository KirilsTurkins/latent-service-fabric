from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
head='1b7a8073f9ec7b354a4dd00a365deb1c4094e3aa'
steps=json.loads((coord/'integration-v12-current828-rpc-native-steps-v23.json').read_bytes())
base=(coord/'integration-v12-current823-java-bridge-native-controller-v21.py').read_text(encoding='utf8')
lines=base.splitlines(keepends=True)
replaced=[]
for line in lines:
    if line.startswith('assert mode == "native" and steps == '):
        replaced.append('assert mode == "native" and head == '+repr(head)+' and steps == '+repr(steps)+'\n')
    elif line.startswith("env['PATH'] =") or line.startswith("env['JAVA_HOME'] ="):
        continue
    else:
        replaced.append(line)
text=''.join(replaced)
compile(text,'current-rpc-v30','exec')
out=coord/'integration-v12-current828-rpc-native-controller-v30.py'
out.write_text(text,encoding='utf8',newline='\n')
proof=dict(head=head, originalStepsByteIdenticalToV23=True, originalBoundsPreserved=True,
    controllerSha256=hashlib.sha256(out.read_bytes()).hexdigest(), actualNativeExecuted=False,
    diagnosticControl255AndCLI162RemainSeparateRequiredChecks=True,
    sourceReceiptSha256='70082840aea65dc413d13df8f3430ddbbd10cf62879c91bbb325f3a42f25c317')
(coord/'integration-v12-union-review/current-rpc-controller-preflight-v30.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
