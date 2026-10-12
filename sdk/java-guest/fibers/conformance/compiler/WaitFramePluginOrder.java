package org.teavm.vm;

import java.util.List;
import java.util.Set;

/** Exercise the locked compiler's actual ordering reader without loading or
 * initializing developer code, or replacing its plugin-order implementation. */
public final class WaitFramePluginOrder {
    private WaitFramePluginOrder() { }

    public static List<String> ordered() {
        return TeaVMPluginReader.orderPlugins(WaitFramePluginOrder.class.getClassLoader(), Set.of(
            "dev.latent.guest.runtime.compiler.RuntimePlugin",
            "org.teavm.platform.plugin.PlatformPlugin"));
    }
}
