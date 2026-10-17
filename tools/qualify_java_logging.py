"""Verify actual pinned console IR and explicitly separate host source controls."""
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
    application = project(output / 'outside-reference-project', 'logging')
    wit = output / 'reference-wit'; copy_wit_tree(application / 'wit', wit)
    for package in dependencies(wit, compiler.sdk.parent.parent / 'wit/platform'):
        target = wit / 'deps' / package.name
        if not target.exists(): copy_wit_tree(package, target)
    generated = output / 'reference-bindings'
    generate(compiler.run, wit, 'tests:logging/service@1.0.0', generated)
    source = output / 'reference-source'
    shutil.copytree(compiler.sdk / 'runtime/dev', source / 'dev')
    for name, original in (
        ('dev/latent/generated/Bindings.java', generated / 'Bindings.java'),
        ('dev/latent/app/Capsule.java', application / 'src/dev/latent/app/Capsule.java'),
        ('dev/latent/app/LoggingReferenceMain.java', compiler.sdk / 'facilities/conformance/LoggingReferenceMain.java')):
        target = source / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original.read_bytes())
    # Compile the real facade caller as well; source controls alone cannot
    # establish that a newly emitted WIT type retained its exact Java name.
    facilities.stage_logging(compiler.sdk, generated, source)
    classes = output / 'reference-classes'; classes.mkdir()
    compiler.run('logging-reference-compile', 'javac', '-proc:none', '--release', '25', '-cp', classpath,
        '-d', classes, *sorted(source.rglob('*.java')))
    result = []
    for iteration in range(3):
        for mode in (0, 1, 2, 6):
            observed = compiler.run(f'logging-reference-{iteration}-{mode}', 'java', '-Xmx128m', '-cp',
                str(classes) + os.pathsep + classpath, 'dev.latent.app.LoggingReferenceMain', mode).strip()
            if observed != f'LOGGING_REFERENCE PASS mode={mode}':
                raise ValueError('ordinary-jdk-console-reference-mismatch')
            result.append({'iteration': iteration, 'mode': mode})
    return result


def controls(compiler, output: Path) -> dict:
    output.mkdir()
    classpath, identities = locked_model_classpath(compiler)
    sdk = compiler.sdk / 'facilities'
    generated = output / 'generated'; generated.mkdir()
    bindings = generated / 'bindings'; bindings.mkdir()
    (bindings / 'probe.c').write_text('__import_module__("latent:log/log@0.1.0")', encoding='utf-8')
    (bindings / 'Bindings.java').write_text('public static final class LatentLogLog {', encoding='utf-8')
    facilities.stage_logging(compiler.sdk, bindings, generated)
    classes = output / 'classes'; classes.mkdir()
    compiler.run('logging-control-compile', 'javac', '-proc:none', '--release', '25', '-cp', classpath,
        '-d', classes, sdk / 'compiler/dev/latent/guest/facilities/compiler/LoggingPlugin.java',
        sdk / 'conformance/LoggingModelControl.java', sdk / 'conformance/LoggingSourceControl.java',
        sdk / 'conformance/log-source-control/dev/latent/generated/Bindings.java',
        generated / 'dev/latent/guest/facilities/StandardLog.java')
    result = compiler.run('logging-model-control', 'java', '-Xmx256m', '-cp', str(classes) + os.pathsep + classpath,
        'dev.latent.guest.facilities.compiler.LoggingModelControl').strip()
    expected = ('LOGGING_MODEL_CONTROL PASS pinned-streams=2;sole-console-call;singleton-and-source-owners;'
                'layout-and-repeat-negatives;application-identity')
    if result != expected: raise ValueError('actual-locked-java-console-control-failed')
    result = compiler.run('logging-source-control', 'java', '-Xmx128m', '-cp', classes, 'LoggingSourceControl').strip()
    prefix = 'LOGGING_SOURCE_CONTROL PASS checks='
    count = result.removeprefix(prefix)
    if not result.startswith(prefix) or not count.isdecimal() or not 35 <= int(count) <= 200:
        raise ValueError('java-logging-source-control-failed')
    denied = output / 'undeclared'; denied.mkdir()
    empty = denied / 'bindings'; empty.mkdir()
    (empty / 'probe.c').write_bytes(b'/* no log import */')
    (empty / 'Bindings.java').write_bytes(b'/* no log facade */')
    facilities.stage_logging(compiler.sdk, empty, denied)
    target = denied / 'classes'; target.mkdir()
    compiler.run('logging-undeclared-compile', 'javac', '-proc:none', '--release', '25', '-d', target,
        denied / 'dev/latent/guest/facilities/StandardLog.java', sdk / 'conformance/LoggingDeniedControl.java')
    result = compiler.run('logging-undeclared-control', 'java', '-Xmx128m', '-cp', target, 'LoggingDeniedControl').strip()
    if result != 'LOGGING_DENIED_CONTROL PASS explicit-failure;empty-noop;no-bindings':
        raise ValueError('undeclared-java-logging-control-failed')
    receipt = {'profile': facilities.LOG_PROFILE, 'status': 'locked-model-and-host-source-controls-passed',
        'standardConsoleClasses': 2, 'sourceChecks': int(count), 'jarDigests': identities,
        'componentExecutionPerformedByTheseControls': False, 'undeclaredCapabilityControl': 'passed-without-bindings'}
    receipt['ordinaryJdkReference'] = references(compiler, output, classpath)
    write_json(output / 'controls.json', receipt)
    return receipt
