package dev.latent.guest.facilities.compiler;

import org.teavm.extension.spi.substitution.SubstitutionPolicy;
import org.teavm.extension.spi.substitution.SubstitutionSink;

public final class EntropySubstitution implements SubstitutionPolicy {
    @Override public void contribute(SubstitutionSink sink) {
        sink.selectClasses(name -> name.equals("java.security.ProviderException"))
            .replacePackage("java.security", "dev.latent.guest.facilities.security")
            .dontFallbackWhenNoSubstitution();
    }
}
