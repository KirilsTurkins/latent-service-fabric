from pathlib import Path
import json

coord=Path(__file__).resolve().parent
source=(coord/'integration-v12-verify-current-http-native.py').read_text()
source=source.replace("lf-p4-pr828-current-java-union-v12","lf-p4-current-public-effect-union-v12")
source=source.replace('6f0a8e82299aa0a1224dee293aaa8a4db7f3a7d9','27d32ea9780784cab5cb1a14aee8b2fb4a46cb03')
source=source.replace('integration-v12-http-current-java-native-v3','integration-v12-current-public-effect-native-v4')
source=source.replace('step-8.log','step-4.log')
source=source.replace('pr828-current-java-actual-runtime-native-review.json','pr823-current-effect-actual-runtime-native-review.json')
assert 'http-current-java-native-v3' not in source
exec(compile(source,'current-effect-native-verifier','exec'))
