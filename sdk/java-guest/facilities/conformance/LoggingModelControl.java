package dev.latent.guest.facilities.compiler;

import java.util.List;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

public final class LoggingModelControl {
    private static void require(boolean value, String code) {
        if (!value) throw new AssertionError(code);
    }
    public static void main(String[] args) {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(
            LoggingModelControl.class.getClassLoader()), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        var context = new ClassHolderTransformerContext() {
            public ClassHierarchy getHierarchy() { return new ClassHierarchy(source); }
            public org.teavm.diagnostics.Diagnostics getDiagnostics() { throw new AssertionError("diagnostics"); }
            public org.teavm.cache.IncrementalDependencyRegistration getIncrementalCache() { throw new AssertionError("cache"); }
            public boolean isObfuscated() { return false; }
            public boolean isStrict() { return true; }
            public String getEntryPoint() { return "unused"; }
            public void submit(ClassHolder cls) { throw new AssertionError("submit"); }
        };
        var signature = new MethodDescriptor("write", ValueType.arrayOf(ValueType.BYTE),
            ValueType.INTEGER, ValueType.INTEGER, ValueType.VOID);
        var plugin = new LoggingPlugin();
        for (String suffix : List.of("StdoutOutputStream", "StderrOutputStream")) {
            var original = source.get("org.teavm.classlib.impl.console." + suffix);
            require(original != null, "actual-pinned-console-class");
            var originalProgram = original.getMethod(signature).getProgram();
            var cls = ModelUtils.copyClass(original);
            plugin.transformClass(cls, context);
            int redirected = 0;
            for (var block : cls.getMethod(signature).getProgram().getBasicBlocks()) for (var instruction : block) {
                if (instruction instanceof InvokeInstruction call) {
                    require(call.getMethod().getClassName().equals("dev.latent.guest.facilities.StandardLog"), "owned-target");
                    require(call.getMethod().getName().equals(suffix.startsWith("Stdout") ? "writeOut" : "writeErr"), "stream-level");
                    redirected++;
                }
            }
            require(redirected == 1 && cls.getMethods().size() == original.getMethods().size(), "sole-body-operation");
            require(original.getMethod(signature).getProgram() == originalProgram, "original-owner");
            for (var method : original.getMethods()) if (!method.getDescriptor().equals(signature))
                require(cls.getMethod(method.getDescriptor()).getProgram() != null, "singleton-initializers-retained");
            for (int mutation = 0; mutation < 3; mutation++) {
                var broken = ModelUtils.copyClass(original);
                if (mutation == 0) broken.setParent("java.lang.Object");
                if (mutation == 1) broken.removeMethod(broken.getMethod(signature));
                if (mutation == 2) broken.getField("INSTANCE").setType(ValueType.INTEGER);
                try { plugin.transformClass(broken, context); throw new AssertionError("layout-drift"); }
                catch (IllegalStateException expected) { }
            }
            try { plugin.transformClass(cls, context); throw new AssertionError("repeated-port"); }
            catch (IllegalStateException expected) { }
        }
        var app = new ClassHolder("outside.owner.StdoutOutputStream");
        plugin.transformClass(app, context);
        require(app.getMethods().isEmpty(), "application-identity");
        System.out.println("LOGGING_MODEL_CONTROL PASS pinned-streams=2;sole-console-call;singleton-and-source-owners;layout-and-repeat-negatives;application-identity");
    }
}
