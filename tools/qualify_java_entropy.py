"""Verify the pinned SecureRandom model and separate host source controls."""
from pathlib import Path
import os
import shutil

from tools.java_guest import facilities
from tools.qualify_java_fibers import locked_model_classpath
from tools.rust_capsule_project import write_json


def references(compiler, output: Path, classpath: str) -> list[dict]:
    from tools.build_java_guest_capsules import project
    from tools.java_guest.bindings import generate
    from tools.stage_runtime_wit import copy_wit_tree, dependencies
    application = project(output / 'outside-reference-project', 'random')
    wit = output / 'reference-wit'
    copy_wit_tree(application / 'wit', wit)
    for package in dependencies(wit, compiler.sdk.parent.parent / 'wit/platform'):
        target = wit / 'deps' / package.name
        if not target.exists(): copy_wit_tree(package, target)
    generated = output / 'reference-bindings'
    generate(compiler.run, wit, 'tests:random/service@1.0.0', generated)
    source = output / 'reference-source'
    shutil.copytree(compiler.sdk / 'runtime/dev', source / 'dev')
    for name, original in (
        ('dev/latent/generated/Bindings.java', generated / 'Bindings.java'),
        ('dev/latent/app/Capsule.java', application / 'src/dev/latent/app/Capsule.java'),
        ('dev/latent/app/EntropyReferenceMain.java', compiler.sdk / 'facilities/conformance/EntropyReferenceMain.java')):
        target = source / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original.read_bytes())
    classes = output / 'reference-classes'; classes.mkdir()
    compiler.run('entropy-reference-compile', 'javac', '-proc:none', '--release', '25', '-cp', classpath,
                 '-d', classes, *sorted(source.rglob('*.java')))
    result = []
    for iteration in range(3):
        for mode in (3, 4, 6):
            observed = compiler.run(f'entropy-reference-{iteration}-{mode}', 'java', '-Xmx128m', '-cp',
                str(classes) + os.pathsep + classpath, 'dev.latent.app.EntropyReferenceMain', mode).strip()
            expected = 42 if mode == 6 else 32
            if observed != f'ENTROPY_REFERENCE PASS mode={mode} result={expected}':
                raise ValueError('ordinary-jdk-entropy-reference-mismatch')
            result.append({'iteration': iteration, 'mode': mode, 'result': expected})
    return result


def controls(compiler, output: Path) -> dict:
    output.mkdir()
    classpath, identities = locked_model_classpath(compiler)
    sdk = compiler.sdk / 'facilities'
    model = output / 'model'; model.mkdir()
    generated = output / 'generated'; generated.mkdir()
    bindings = generated / 'bindings'; bindings.mkdir()
    # These are explicitly host-only controls. The component still compiles
    # against its real independently generated bindings and normal host broker.
    (bindings / 'probe.c').write_text('__import_module__("latent:random/random@0.1.0")', encoding='utf-8')
    (bindings / 'Bindings.java').write_text('public static final class LatentRandomRandom {', encoding='utf-8')
    facilities.stage(compiler.sdk, bindings, generated)
    sources = [*sorted((sdk / 'dev').rglob('*.java')), *sorted((sdk / 'compiler/dev').rglob('*.java')),
        generated / 'dev/latent/guest/facilities/Entropy.java',
        sdk / 'conformance/source-control/dev/latent/generated/Bindings.java',
        sdk / 'conformance/EntropyModelControl.java', sdk / 'conformance/EntropySourceControl.java']
    compiler.run('entropy-control-compile', 'javac', '-proc:none', '--release', '25',
                 '-cp', classpath, '-d', model, *sources)
    observed = compiler.run('entropy-model-control', 'java', '-Xmx256m', '-cp', str(model) + os.pathsep + classpath,
        'dev.latent.guest.facilities.compiler.EntropyModelControl').strip()
    expected = ('ENTROPY_MODEL_CONTROL PASS methods=13;original-fallback-negative;reference-closure;owners;'
                'layout-and-repeat-negatives;unseen-caller')
    if observed != expected:
        raise ValueError('actual-locked-java-entropy-model-control-failed')
    observed = compiler.run('entropy-source-control', 'java', '-Xmx128m', '-cp', model, 'EntropySourceControl').strip()
    prefix = 'ENTROPY_SOURCE_CONTROL PASS checks='
    checks = observed.removeprefix(prefix)
    if not observed.startswith(prefix) or not checks.isdecimal() or not 200 <= int(checks) <= 1000:
        raise ValueError('java-entropy-source-control-failed')
    denied = output / 'undeclared'; denied.mkdir()
    empty = denied / 'bindings'; empty.mkdir()
    (empty / 'probe.c').write_bytes(b'/* no random import */')
    (empty / 'Bindings.java').write_bytes(b'/* no random facade */')
    facilities.stage(compiler.sdk, empty, denied)
    denied_classes = denied / 'classes'; denied_classes.mkdir()
    compiler.run('entropy-undeclared-compile', 'javac', '-proc:none', '--release', '25', '-d', denied_classes,
        sdk / 'dev/latent/guest/facilities/EntropyRandom.java', denied / 'dev/latent/guest/facilities/Entropy.java',
        sdk / 'conformance/EntropyDeniedControl.java')
    observed = compiler.run('entropy-undeclared-control', 'java', '-Xmx128m', '-cp', denied_classes,
                            'EntropyDeniedControl').strip()
    if observed != 'ENTROPY_DENIED_CONTROL PASS explicit-failure;empty-noop;unchanged-output;no-bindings':
        raise ValueError('undeclared-java-entropy-control-failed')
    result = {'profile':facilities.PROFILE, 'status':'locked-model-and-host-source-controls-passed',
        'standardMethodBodies':13, 'sourceChecks':int(checks), 'jarDigests':identities,
        'componentExecutionPerformedByTheseControls':False, 'sourceProvider':'explicit-host-only-deterministic-control'}
    result['ordinaryJdkReference'] = references(compiler, output, classpath)
    result['undeclaredCapabilityControl'] = 'passed-without-generated-random-bindings'
    write_json(output / 'controls.json', result)
    return result
