package dev.latent.guest.runtime.compiler;

import org.teavm.extension.spi.substitution.SubstitutionPolicy;
import org.teavm.extension.spi.substitution.SubstitutionSink;

/** Exact missing standard members; application API references stay unchanged. */
public final class RuntimeSubstitution implements SubstitutionPolicy {
    @Override public void contribute(SubstitutionSink sink) {
        sink.selectClasses(name -> name.equals("java.lang.IllegalThreadStateException"))
            .replacePackage("java.lang", "dev.latent.guest.runtime.lang")
            .dontFallbackWhenNoSubstitution();
    }
}
