package dev.latent.guest.runtime.compiler;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.teavm.backend.c.CTarget;
import org.teavm.backend.c.generate.CNameProvider;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.*;
import org.teavm.platform.metadata.StringResource;
import org.teavm.classlib.impl.unicode.CLDRHelper;
import org.teavm.vm.*;

/** Actual frontend controls. No component or guest is executed. */
public final class WorkerCompilerControl {
    public static final class Descending {
        static int value;
        static { for (int i = 12; i > -4; --i) value += i; }
        public static void main(String[] args) { if (args.length > 0) value = args.length; }
    }
    public static final class InclusiveDescending {
        static int value;
        static { for (int i = Integer.MIN_VALUE + 3; i >= Integer.MIN_VALUE + 1; --i) value += i; }
        public static void main(String[] args) { if (args.length > 0) value = args.length; }
    }
    public static final class ZeroDescending {
        static int value;
        static { for (int i = 12; i > 0; --i) value += i; }
        public static void main(String[] args) { if (args.length > 0) value = args.length; }
    }
    public static final class WrappingDescending {
        static int value;
        static { for (int i = Integer.MIN_VALUE + 3; i >= Integer.MIN_VALUE; --i) value += i; }
        public static void main(String[] args) { if (args.length > 0) value = args.length; }
    }
    public static final class DynamicDescending {
        static int value;
        static int lower = Integer.MIN_VALUE;
        static { for (int i = 12; i >= lower; --i) value += i; }
        public static void main(String[] args) { if (args.length > 0) value = args.length; }
    }
    public static final class StalledDescending {
        static int value;
        static { for (int i = 12; i > 0; i += 0) value += i; }
        public static void main(String[] args) { if (args.length > 0) value = args.length; }
    }
    public static final class Counter { public int remaining = 12; }
    public static final class FieldDescending {
        static Counter value = drain(new Counter());
        static Counter drain(Counter state) { while (state.remaining > 0) --state.remaining; return state; }
        public static void main(String[] args) { if (args.length > 0) value.remaining = args.length; }
    }
    public static final class FieldAlias {
        static Counter value = drain(new Counter(), new Counter());
        static Counter drain(Counter state, Counter other) { while (state.remaining > 0) --other.remaining; return state; }
        public static void main(String[] args) { if (args.length > 0) value.remaining = args.length; }
    }
    public static final class FieldCall {
        static Counter value = drain(new Counter());
        static void reset(Counter state) { state.remaining = 12; }
        static Counter drain(Counter state) { while (state.remaining > 0) { --state.remaining; reset(state); } return state; }
        public static void main(String[] args) { if (args.length > 0) value.remaining = args.length; }
    }
    public static final class FieldBypass {
        static Counter value = drain(new Counter());
        static Counter drain(Counter state) {
            while (state.remaining > 0) { if (state.remaining == 12) continue; --state.remaining; }
            return state;
        }
        public static void main(String[] args) { if (args.length > 0) value.remaining = args.length; }
    }
    public static final class ResourceRead {
        static StringResource resource;
        static String value = resource.getValue();
        public static void main(String[] args) { if (args.length > 0) value = args[0]; }
    }
    public static final class LocaleRead {
        static String value = CLDRHelper.getDefaultLocale().getValue();
        public static void main(String[] args) { if (args.length > 0) value = args[0]; }
    }
    public static final class MathTables {
        static java.math.BigDecimal value = java.math.BigDecimal.ONE;
        public static void main(String[] args) { if (args.length > 0) value = java.math.BigDecimal.TEN; }
    }

    private static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static boolean refused(Throwable failure) {
        for (Throwable e = failure; e != null; e = e.getCause()) {
            if (List.of("java-checkpoint-nonsuspendable-progress-741", "java-checkpoint-unresolved-741",
                    "unexpected-maintained-math-initialization").contains(e.getMessage())) return true;
        }
        return false;
    }

    @SuppressWarnings("unchecked")
    private static Object metadata(CTarget target) throws Exception {
        var field = CTarget.class.getDeclaredField("generatorFactories"); require(field.trySetAccessible(), "generators");
        var factories = (List<Object>) field.get(target);
        var first = factories.get(0); var capture = first.getClass().getDeclaredFields();
        require(capture.length == 1 && capture[0].trySetAccessible(), "metadata-capture");
        Object result = capture[0].get(first);
        require(result.getClass().getName().equals("org.teavm.platform.plugin.MetadataCIntrinsic"), "metadata-type");
        return result;
    }

    @SuppressWarnings("unchecked")
    private static void removeLocale(Object metadata) throws Exception {
        var field = metadata.getClass().getDeclaredField("generatorMap"); require(field.trySetAccessible(), "metadata-map");
        var map = (Map<MethodReference, Object>) field.get(metadata);
        var target = new MethodReference("org.teavm.classlib.impl.unicode.CLDRHelper", "getDefaultLocale$$create",
                ValueType.object("org.teavm.platform.metadata.StringResource"));
        require(map.remove(target) != null, "locale-generator-present");
    }

    public static void main(String[] args) throws Exception {
        require(args.length == 1, "mode"); String mode = args[0];
        boolean positive = List.of("worker-descending", "worker-descending-inclusive", "worker-descending-zero",
                "worker-field", "worker-resource", "worker-locale", "worker-math").contains(mode);
        boolean known = positive || List.of("worker-descending-overflow", "worker-descending-dynamic",
                "worker-descending-stalled", "worker-field-alias", "worker-field-call", "worker-field-bypass",
                "worker-field-volatile", "worker-resource-declaration", "worker-resource-parent",
                "worker-locale-declaration", "worker-locale-provider", "worker-locale-late-provider",
                "worker-math-mutated").contains(mode);
        require(known, "known-mode");
        var target = new CTarget(new CNameProvider()); target.setObfuscated(false);
        target.setMinHeapSize(1024 * 1024); target.setMaxHeapSize(4 * 1024 * 1024);
        var refs = new ReferenceCache(); var loader = Thread.currentThread().getContextClassLoader();
        var builder = new TeaVMBuilder(target).setReferenceCache(refs).setClassLoader(loader)
                .setResourceProvider(new ClasspathResourceProvider(loader));
        builder.setClassSource(new PreOptimizingClassHolderSource(new ClasspathClassHolderSource(
                builder.getResourceProvider(), refs, loader)));
        var vm = builder.build(); vm.setOptimizationLevel(TeaVMOptimizationLevel.FULL); vm.installPlugins();
        boolean[] changed = { false };
        vm.add((ClassHolder cls, ClassHolderTransformerContext context) -> {
            if (mode.equals("worker-field-volatile") && cls.getName().equals(Counter.class.getName())) {
                cls.getField("remaining").getModifiers().add(ElementModifier.VOLATILE); changed[0] = true;
            }
            if (mode.equals("worker-resource-declaration") && cls.getName().equals(StringResource.class.getName())) {
                cls.getMethod(new MethodDescriptor("getValue", ValueType.object("java.lang.String")))
                        .getModifiers().add(ElementModifier.FINAL); changed[0] = true;
            }
            if (mode.equals("worker-resource-parent") && cls.getName().equals("org.teavm.platform.metadata.Resource")) {
                cls.getInterfaces().add("java.io.Serializable"); changed[0] = true;
            }
            if (mode.equals("worker-locale-declaration") && cls.getName().equals(CLDRHelper.class.getName())) {
                cls.getMethod(new MethodDescriptor("getDefaultLocale$$create", ValueType.object(StringResource.class.getName())))
                        .getModifiers().add(ElementModifier.FINAL); changed[0] = true;
            }
            if (mode.startsWith("worker-math") && cls.getName().equals("java.math.Multiplication")) {
                if (mode.equals("worker-math-mutated")) {
                    var program = cls.getMethod(new MethodDescriptor("<clinit>", ValueType.VOID)).getProgram();
                    outer: for (var block : program.getBasicBlocks()) for (var instruction : block) {
                        if (instruction instanceof IntegerConstantInstruction constant && constant.getConstant() == 18) {
                            constant.setConstant(19); changed[0] = true; break outer;
                        }
                    }
                }
                BoundedMathInitialization.transform(cls);
            }
        });
        Object metadata = mode.contains("provider") ? metadata(target) : null;
        if (mode.equals("worker-locale-provider")) { removeLocale(metadata); changed[0] = true; }
        if (mode.equals("worker-locale-late-provider")) {
            var async = CTarget.class.getDeclaredField("asyncMethods"); require(async.trySetAccessible(), "async");
            vm.setProgressListener(new TeaVMProgressListener() {
                private void after() {
                    try { if (!changed[0] && async.get(target) != null) { removeLocale(metadata); changed[0] = true; } }
                    catch (Exception failure) { throw new AssertionError(failure); }
                }
                public TeaVMProgressFeedback progressReached(int n) { after(); return TeaVMProgressFeedback.CONTINUE; }
                public TeaVMProgressFeedback phaseStarted(TeaVMPhase phase, int n) { after(); return TeaVMProgressFeedback.CONTINUE; }
            });
        }
        Class<?> fixture;
        switch (mode) {
            case "worker-descending": fixture = Descending.class; break;
            case "worker-descending-inclusive": fixture = InclusiveDescending.class; break;
            case "worker-descending-zero": fixture = ZeroDescending.class; break;
            case "worker-descending-overflow": fixture = WrappingDescending.class; break;
            case "worker-descending-dynamic": fixture = DynamicDescending.class; break;
            case "worker-descending-stalled": fixture = StalledDescending.class; break;
            case "worker-field-alias": fixture = FieldAlias.class; break;
            case "worker-field-call": fixture = FieldCall.class; break;
            case "worker-field-bypass": fixture = FieldBypass.class; break;
            default: fixture = mode.startsWith("worker-resource") ? ResourceRead.class
                    : mode.startsWith("worker-locale") ? LocaleRead.class
                    : mode.startsWith("worker-math") ? MathTables.class : FieldDescending.class;
        }
        vm.setEntryPoint(fixture.getName());
        var captures = new java.util.HashMap<String, String>(); long[] counts = { 0, 0 };
        boolean failed = false;
        try {
            vm.build(name -> {
                require(++counts[0] < 100000, "output-count");
                return new ByteArrayOutputStream() {
                    public synchronized void write(int value) { require(++counts[1] <= 64L * 1024 * 1024, "output-size"); super.write(value); }
                    public synchronized void write(byte[] b, int off, int n) { counts[1] += n; require(counts[1] <= 64L * 1024 * 1024, "output-size"); super.write(b, off, n); }
                    public void close() {
                        if (name.contains("WorkerCompilerControl") || name.endsWith("CLDRHelper.c") || name.endsWith("Multiplication.c"))
                            captures.put(name, toString(java.nio.charset.StandardCharsets.UTF_8));
                    }
                };
            }, "main.c");
        } catch (IllegalStateException failure) { if (!refused(failure)) throw failure; failed = true; }
        require(failed != positive, "verdict-" + mode);
        if (!positive) require(counts[0] == 0 && counts[1] == 0, "refusal-before-output");
        if (mode.endsWith("declaration") || mode.endsWith("parent") || mode.contains("provider")
                || mode.endsWith("volatile") || mode.endsWith("mutated")) require(changed[0], "mutation-observed");
        if (positive) {
            require(vm.getProblemProvider().getSevereProblems().isEmpty() && counts[0] > 0 && counts[1] > 0, "generated");
            String generated = String.join("\n", captures.values());
            if (mode.equals("worker-resource") || mode.equals("worker-locale")) {
                require(generated.contains("teavm_dereferenceNullable") && generated.contains("TEAVM_FIELD"), "bounded-resource-read");
            }
            if (mode.equals("worker-locale")) require(generated.matches("(?s).*getDefaultLocale__create\\(\\) \\{\\s*return resource_[A-Za-z0-9_]+;\\s*}.*"), "constant-locale-generator");
            if (mode.equals("worker-math")) require(generated.contains("multiplyPAP") && !generated.contains("karatsuba"), "bounded-math-initializer");
        }
        System.out.println("CHECKPOINT_AMPLIFIER_PROBE " + mode + " PASS generated=" + positive
                + " outputFiles=" + counts[0] + " outputBytes=" + counts[1]);
    }
}
