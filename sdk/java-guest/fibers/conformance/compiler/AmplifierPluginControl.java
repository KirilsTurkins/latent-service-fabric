package org.teavm.platform.plugin;

import org.teavm.backend.c.TeaVMCHost;
import org.teavm.dependency.AbstractDependencyListener;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.ValueType;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** Test-only service-loaded compiler extension. Never installed in an SDK build. */
public final class AmplifierPluginControl implements TeaVMPlugin {
    private static String mode;
    private static int installations;
    private static int completions;
    private static int factories;
    private static int mutations;

    public static void configure(String selected) {
        require(mode == null && selected.startsWith("plugin-"), "plugin-configuration");
        mode = selected;
    }

    @Override public void install(TeaVMHost host) {
        require(mode != null && ++installations == 1, "plugin-installation");
        TeaVMCHost c = host.getExtension(TeaVMCHost.class);
        require(c != null, "plugin-c-host");
        switch (mode) {
            case "plugin-neutral":
                // A no-op plugin does not change the selected emitter profile.
                break;
            case "plugin-intrinsic":
            case "plugin-generator":
                register(c);
                break;
            case "plugin-completion-intrinsic":
            case "plugin-completion-generator":
                host.add(new AbstractDependencyListener() {
                    @Override public void complete() {
                        require(++completions == 1, "plugin-completion");
                        register(c);
                    }
                });
                break;
            case "plugin-declaration":
                host.add((ClassHolder cls, ClassHolderTransformerContext context) -> {
                    if (!cls.getName().equals("org.teavm.platform.plugin.StringAmplifier")) return;
                    var string = ValueType.object("java.lang.String");
                    var method = cls.getMethod(new MethodDescriptor("amplify", string, string));
                    require(method != null && !method.hasModifier(ElementModifier.FINAL), "plugin-method");
                    method.getModifiers().add(ElementModifier.FINAL);
                    ++mutations;
                });
                break;
            default:
                throw new AssertionError("plugin-mode");
        }
    }

    private static void register(TeaVMCHost c) {
        if (mode.endsWith("-intrinsic")) {
            c.addIntrinsic(context -> {
                ++factories;
                throw new AssertionError("unreviewed-plugin-intrinsic-invoked");
            });
        } else {
            require(mode.endsWith("-generator"), "plugin-factory-kind");
            c.addGenerator(context -> {
                ++factories;
                throw new AssertionError("unreviewed-plugin-generator-invoked");
            });
        }
    }

    public static void verify() {
        require(installations == 1, "plugin-not-discovered");
        require(factories == 0, "plugin-factory-executed-before-refusal");
        require(completions == (mode.startsWith("plugin-completion-") ? 1 : 0), "plugin-completion-observed");
        require(mutations == (mode.equals("plugin-declaration") ? 1 : 0), "plugin-mutation-observed");
    }

    private static void require(boolean value, String code) {
        if (!value) throw new AssertionError(code);
    }
}
