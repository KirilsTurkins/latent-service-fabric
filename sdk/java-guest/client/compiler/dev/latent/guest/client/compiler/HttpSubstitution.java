package dev.latent.guest.client.compiler;

import java.util.Set;
import org.teavm.extension.spi.substitution.SubstitutionPolicy;
import org.teavm.extension.spi.substitution.SubstitutionSink;

/** Shared standard types used by ordinary default URL connection factories. */
public final class HttpSubstitution implements SubstitutionPolicy {
    static final String STANDARD = "java.net.";
    static final String SDK = "dev.latent.guest.client.net.";
    static final Set<String> API = Set.of("Proxy", "Proxy$Type", "SocketAddress", "InetSocketAddress");

    @Override public void contribute(SubstitutionSink sink) {
        sink.selectClasses(name -> name.startsWith(STANDARD) && API.contains(name.substring(STANDARD.length())))
            .replacePackage("java.net", "dev.latent.guest.client.net")
            .dontFallbackWhenNoSubstitution();
        sink.selectClasses(name -> name.equals("javax.net.ssl.HttpsURLConnection"))
            .replacePackage("javax.net.ssl", "dev.latent.guest.client.ssl")
            .dontFallbackWhenNoSubstitution();
    }
}
