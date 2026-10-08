from pathlib import Path
import sys

coord=Path(__file__).resolve().parent
pr=int(sys.argv[1]);assert pr in (823,828)
source=(coord/'integration-v12-verify-current-http-native.py').read_text()
if pr==823:
    source=source.replace('lf-p4-pr828-current-java-union-v12','lf-p4-current-java-bd4-union-v12')
    head='eafeb0f3046ddd5756258a37940a1d6cfd69f04a'
else:head='237fb3edc4ee39d17e361d69e88b43be2d5ea4f8'
source=source.replace('6f0a8e82299aa0a1224dee293aaa8a4db7f3a7d9',head)
source=source.replace('integration-v12-http-current-java-native-v3',f'integration-v12-current{pr}-development0cd-native-v8')
source=source.replace('step-8.log','step-3.log')
source=source.replace('pr828-current-java-actual-runtime-native-review.json',f'pr{pr}-current0cd-actual-runtime-native-review.json')
exec(compile(source,'current-main-native-verifier','exec'))
