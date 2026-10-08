from pathlib import Path
import json
import sys

coord=Path(__file__).resolve().parent;pr=int(sys.argv[1]);assert pr in (823,828)
source=(coord/'integration-v12-verify-current-http-native.py').read_text()
if pr==823:
    source=source.replace('lf-p4-pr828-current-java-union-v12','lf-p4-current-java-bd4-union-v12')
    head='0a0dc2818946111c8657e6b681ecef1f9f3fafab';job='integration-v12-current823-developmentc844-native-v10'
    source=source.replace("receipt['passed'] and ","all(receipt['steps'][index]['exitCode']==0 for index in (0,2,3)) and ")
else:
    head='7bc6e42254ef94c2b0248ad174d1e959aefc10e2';job='integration-v12-current828-developmentc844-native-v11'
source=source.replace('6f0a8e82299aa0a1224dee293aaa8a4db7f3a7d9',head)
source=source.replace('integration-v12-http-current-java-native-v3',job)
source=source.replace('step-8.log','step-4.log')
source=source.replace('pr828-current-java-actual-runtime-native-review.json',f'pr{pr}-c844-actual-runtime-native-review.json')
exec(compile(source,'actual-c844-runtime-verifier','exec'))
