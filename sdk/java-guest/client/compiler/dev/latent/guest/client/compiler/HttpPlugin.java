package dev.latent.guest.client.compiler;

import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformer;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.ReferenceCache;
import org.teavm.parsing.ClassRefsRenamer;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** Source-bound replacement of the maintained URL's default browser handler. */
public final class HttpPlugin implements TeaVMPlugin, ClassHolderTransformer {
    private static final String ORIGINAL = "java.net.impl.XHRStreamHandler";
    private static final String REPLACEMENT = "dev.latent.guest.client.StreamHandler";
    @Override public void install(TeaVMHost host) { host.add(this); }
    @Override public void transformClass(ClassHolder cls, ClassHolderTransformerContext context) {
        if (!cls.getName().equals("java.net.URL")) return;
        int[] references = {0};
        ClassHolder renamed = new ClassRefsRenamer(new ReferenceCache(), name -> {
            if (!name.equals(ORIGINAL)) return name;
            references[0]++;
            return REPLACEMENT;
        }).rename(cls);
        if (renamed != cls || references[0] == 0) {
            throw new IllegalStateException("pinned URL default handler shape changed");
        }
    }
}
