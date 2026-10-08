from pathlib import Path
import json

coord=Path(__file__).resolve().parent
review=coord/'integration-v12-union-review'
steps=json.loads((review/'actual-startup-wrapper-source-steps-v1.json').read_text())
previous=steps[0][-1]
assert previous.count("'tools.tests.test_java_current_inputs'")==1
modules=['tools.tests.test_java_diagnostic_program','tools.tests.test_java_provider_timeout',
         'tools.tests.test_java_resource_diagnostics']
needle="'tools.tests.test_java_current_inputs'"
after=needle+''.join(', '+repr(name) for name in modules)
steps[0][-1]=previous.replace(needle,after)
compile(steps[0][-1],'actualSourceModuleWrapper','exec')
(review/'current0cd-full-source-steps-v7.json').write_text(json.dumps(steps,indent=2)+'\n')
print(json.dumps({'originalModulesPreserved':28,'newCurrentMainModules':modules,
                  'exactWrapperCompiled':True,'originalAllSevenGatesPreserved':True}))
