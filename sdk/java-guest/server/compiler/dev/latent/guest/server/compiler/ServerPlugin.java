package dev.latent.guest.server.compiler;

import java.util.Set;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformer;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.ReferenceCache;
import org.teavm.parsing.ClassRefsRenamer;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** Keep the compiler bridge and substituted APIs on one class identity. */
public final class ServerPlugin implements TeaVMPlugin, ClassHolderTransformer {
    private static final String STANDARD = "com.sun.net.httpserver.";
    private static final String SDK = "dev.latent.guest.server.http.";
    private static final Set<String> API = Set.of("HttpServer", "HttpHandler", "HttpContext", "HttpExchange", "Headers");

    @Override public void install(TeaVMHost host) { host.add(this); }

    private static String reference(String name) {
        if (name.equals(STANDARD + "ServerSession")) return SDK + "ServerSession";
        if (name.startsWith(SDK)) {
            String suffix = name.substring(SDK.length());
            int nested = suffix.indexOf('$');
            String outer = nested < 0 ? suffix : suffix.substring(0, nested);
            if (API.contains(outer)) return STANDARD + suffix;
        }
        return name;
    }

    @Override public void transformClass(ClassHolder cls, ClassHolderTransformerContext context) {
        String name = cls.getName();
        // Only compiler-owned bridge/support code and the SDK's substituted
        // standard API bodies need normalization. Captured application classes
        // retain their ordinary source/API symbols and are never selected here.
        if (!(name.equals("dev.latent.app.Capsule") || name.equals(SDK + "ServerSession")
                || name.startsWith(STANDARD))) return;
        ClassHolder renamed = new ClassRefsRenamer(new ReferenceCache(), ServerPlugin::reference).rename(cls);
        // TeaVM 0.15 mutates the holder when its class identity is unchanged,
        // including field/method descriptors and instruction references.
        if (renamed != cls) throw new IllegalStateException("unexpected server helper alias");
    }
}
