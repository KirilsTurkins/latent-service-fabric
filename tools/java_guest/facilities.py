"""Stage an owned standard entropy port against the exact declared WIT import."""
from pathlib import Path

PROFILE = 'lsf.java.bounded-entropy.v1'
LOG_PROFILE = 'lsf.java.bounded-standard-logging.v1'


def stage(sdk: Path, bindings: Path, output: Path) -> dict:
    bridge = (bindings / 'probe.c').read_text(encoding='utf-8')
    declared = '__import_module__("latent:random/random@0.1.0")' in bridge
    source = (bindings / 'Bindings.java').read_text(encoding='utf-8')
    if declared and source.count('public static final class LatentRandomRandom {') != 1:
        raise ValueError('canonical-java-random-facade-type-drift')
    body = '''var result = dev.latent.generated.Bindings.LatentRandomRandom.bytes((long)target.length);
        if (result.isError()) {
            int tag = result.error().tag();
            if (tag == 0) throw new java.security.ProviderException("bounded-entropy-invalid-length");
            if (tag == 1) throw new java.security.ProviderException("bounded-entropy-budget-exhausted");
            throw new java.security.ProviderException("bounded-entropy-unavailable");
        }
        byte[] captured = result.value();
        try {
            if (captured.length != target.length) throw new java.security.ProviderException("bounded-entropy-invalid-provider-output");
            System.arraycopy(captured, 0, target, 0, target.length);
        } finally { java.util.Arrays.fill(captured, (byte)0); }''' if declared else (
        'throw new java.security.ProviderException("bounded-entropy-capability-not-declared");')
    template = (sdk / 'facilities/templates/Entropy.java.in').read_text(encoding='utf-8')
    if template.count('ENTROPY_BODY') != 1:
        raise ValueError('invalid-owned-java-entropy-template')
    target = output / 'dev/latent/guest/facilities/Entropy.java'
    if target.exists():
        raise ValueError('java-entropy-source-collision')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace('ENTROPY_BODY', body), encoding='utf-8')
    return {'profile': PROFILE, 'entropyDeclared': declared, 'maximumCallBytes': 4096,
            'implicitGrant': False, 'deterministicFallback': False}


def stage_logging(sdk: Path, bindings: Path, output: Path) -> dict:
    bridge = (bindings / 'probe.c').read_text(encoding='utf-8')
    declared = '__import_module__("latent:log/log@0.1.0")' in bridge
    source = (bindings / 'Bindings.java').read_text(encoding='utf-8')
    if declared and source.count('public static final class LatentLogLog {') != 1:
        raise ValueError('canonical-java-log-facade-type-drift')
    body = '''var level = error ? dev.latent.generated.Bindings.LatentLogLogLevel.Error
            : dev.latent.generated.Bindings.LatentLogLogLevel.Info;
        var result = dev.latent.generated.Bindings.LatentLogLog.write(level, message, java.util.List.of());
        if (result.isError()) {
            int tag = result.error().tag();
            if (tag == 0) throw new IOException("bounded-log-budget-exhausted");
            if (tag == 1) throw new IOException("bounded-log-invalid-field");
            throw new IOException("bounded-log-unavailable");
        }
        if (!result.value()) throw new IOException("bounded-log-record-dropped");''' if declared else (
        'throw new IOException("bounded-log-capability-not-declared");')
    template = (sdk / 'facilities/templates/StandardLog.java.in').read_text(encoding='utf-8')
    if template.count('LOG_BODY') != 1:
        raise ValueError('invalid-owned-java-log-template')
    target = output / 'dev/latent/guest/facilities/StandardLog.java'
    if target.exists(): raise ValueError('java-log-source-collision')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace('LOG_BODY', body), encoding='utf-8')
    return {'profile': LOG_PROFILE, 'logDeclared': declared, 'maximumWriteBytes': 4096,
            'implicitGrant': False, 'failurePolicy': 'IOException-to-PrintStream-checkError',
            'pendingBuffers': 0, 'backgroundWorkers': 0, 'flushGuaranteesRemoteDelivery': False}
