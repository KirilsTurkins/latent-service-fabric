"""Stage an owned standard entropy port against the exact declared WIT import."""
from pathlib import Path

PROFILE = 'lsf.java.bounded-entropy.v1'


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
