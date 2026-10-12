package dev.latent.guest.server.compiler;
import org.teavm.extension.spi.substitution.SubstitutionPolicy;
import org.teavm.extension.spi.substitution.SubstitutionSink;
/** Exact standard API substitution, independent of application/library identity. */
public final class ServerSubstitution implements SubstitutionPolicy {
    @Override public void contribute(SubstitutionSink sink) {
        sink.selectClasses(name -> name.startsWith("com.sun.net.httpserver."))
            .replacePackage("com.sun.net.httpserver", "dev.latent.guest.server.http")
            .dontFallbackWhenNoSubstitution();
        sink.selectClasses(name -> name.equals("java.net.InetSocketAddress")
                || name.equals("java.net.InetAddress") || name.equals("java.net.SocketAddress"))
            .replacePackage("java.net", "dev.latent.guest.server.net")
            .dontFallbackWhenNoSubstitution();
    }
}
