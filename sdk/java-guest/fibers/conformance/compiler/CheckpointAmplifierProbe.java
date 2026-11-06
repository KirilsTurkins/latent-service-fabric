package org.teavm.platform.plugin;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.teavm.backend.c.CTarget;
import org.teavm.backend.c.generate.CNameProvider;
import org.teavm.backend.c.intrinsic.IntrinsicFactory;
import org.teavm.backend.c.generators.GeneratorFactory;
import org.teavm.model.PreOptimizingClassHolderSource;
import org.teavm.model.ReferenceCache;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.vm.TeaVMBuilder;
import org.teavm.vm.TeaVMOptimizationLevel;
import org.teavm.vm.TeaVMProgressFeedback;
import org.teavm.vm.TeaVMProgressListener;
import org.teavm.vm.TeaVMPhase;

/** Local bounded diagnostic: tests the actual C frontend; no guest executes. */
public final class CheckpointAmplifierProbe {
    public static final class Fixture {
        static String value = StringAmplifier.amplify("bounded");
        public static void main(String[] args) { if (args.length != 0) value = args[0]; }
    }
    public static final class ArrayFixture {
        static String[] value = StringAmplifier.amplifyArray(new String[] { "bounded" });
        public static void main(String[] args) { if (args.length != 0) value = args; }
    }
    private static void require(boolean value, String code) {
        if (!value) throw new AssertionError(code);
    }
    private static boolean hasCause(Throwable failure, String marker) {
        for (Throwable current = failure; current != null; current = current.getCause()) {
            if (marker.equals(current.getMessage())) return true;
        }
        return false;
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 1, "mode");
        String mode = args[0];
        require(List.of("pass", "reorder", "replace", "late", "array", "declaration", "parent", "generator-reorder",
                "generator-replace", "extra-intrinsic", "extra-generator", "wrong-target", "tampered").contains(mode), "mode-name");
        CTarget target = mode.equals("wrong-target") ? new CTarget(new CNameProvider()) { }
                : new CTarget(new CNameProvider());
        target.setMinHeapSize(1024 * 1024); target.setMaxHeapSize(4 * 1024 * 1024);
        var refs = new ReferenceCache(); var builder = new TeaVMBuilder(target).setReferenceCache(refs);
        ClassLoader loader = Thread.currentThread().getContextClassLoader();
        builder.setClassLoader(loader).setResourceProvider(new ClasspathResourceProvider(loader));
        builder.setClassSource(new PreOptimizingClassHolderSource(new ClasspathClassHolderSource(
                builder.getResourceProvider(), refs, builder.getClassLoader())));
        var vm = builder.build(); vm.setOptimizationLevel(TeaVMOptimizationLevel.FULL); vm.installPlugins();
        var intrinsics = CTarget.class.getDeclaredField("intrinsicFactories"); require(intrinsics.trySetAccessible(), "field");
        @SuppressWarnings("unchecked") var factories = (List<IntrinsicFactory>) intrinsics.get(target);
        if (mode.equals("reorder")) Collections.swap(factories, 0, 1);
        if (mode.equals("replace")) factories.set(1, context -> null);
        if (mode.equals("extra-intrinsic")) target.addIntrinsic(context -> null);
        var generatorsField = CTarget.class.getDeclaredField("generatorFactories");
        require(generatorsField.trySetAccessible(), "generator-field");
        @SuppressWarnings("unchecked") var generators = (List<GeneratorFactory>) generatorsField.get(target);
        if (mode.equals("generator-reorder")) Collections.swap(generators, 0, 1);
        if (mode.equals("generator-replace")) generators.set(1, context -> null);
        if (mode.equals("extra-generator")) target.addGenerator(context -> null);
        boolean[] mutated = { false };
        if (mode.equals("declaration") || mode.equals("parent")) {
            vm.add((org.teavm.model.ClassHolder cls, org.teavm.model.ClassHolderTransformerContext context) -> {
                if (!cls.getName().equals("org.teavm.platform.plugin.StringAmplifier")) return;
                if (mode.equals("declaration")) {
                    var method = cls.getMethod(new org.teavm.model.MethodDescriptor("amplify",
                            org.teavm.model.ValueType.object("java.lang.String"),
                            org.teavm.model.ValueType.object("java.lang.String")));
                    require(method != null && !method.hasModifier(org.teavm.model.ElementModifier.FINAL), "declaration-present");
                    method.getModifiers().add(org.teavm.model.ElementModifier.FINAL);
                } else {
                    cls.getInterfaces().add("org.teavm.platform.metadata.Resource");
                }
                mutated[0] = true;
            });
        }
        var async = CTarget.class.getDeclaredField("asyncMethods"); require(async.trySetAccessible(), "async");
        boolean[] late = {false};
        vm.setProgressListener(new TeaVMProgressListener() {
            private void afterFinder() {
                if (!mode.equals("late") || late[0]) return;
                try {
                    if (async.get(target) == null) return;
                    boolean rejectedIntrinsic = false, rejectedGenerator = false;
                    try { target.addIntrinsic(context -> null); } catch (UnsupportedOperationException rejected) { rejectedIntrinsic = true; }
                    try { target.addGenerator(context -> null); } catch (UnsupportedOperationException rejected) { rejectedGenerator = true; }
                    require(rejectedIntrinsic && rejectedGenerator, "late-registration-refusal"); late[0] = true;
                } catch (IllegalAccessException failure) { throw new AssertionError(failure); }
            }
            public TeaVMProgressFeedback progressReached(int progress) { afterFinder(); return TeaVMProgressFeedback.CONTINUE; }
            public TeaVMProgressFeedback phaseStarted(TeaVMPhase phase, int count) { afterFinder(); return TeaVMProgressFeedback.CONTINUE; }
        });
        vm.setEntryPoint(mode.equals("array") ? ArrayFixture.class.getName() : Fixture.class.getName());
        var names = new ArrayList<String>(); long[] total = {0}; String[] fixtureC = {null};
        boolean failed = false;
        try {
            vm.build(name -> {
                require(names.size() < 100000, "output-count-bound"); names.add(name);
                return new ByteArrayOutputStream() {
                    private final boolean retain = name.equals("classes/org/teavm/platform/plugin/CheckpointAmplifierProbe@dFixture.c");
                    @Override public synchronized void write(int value) {
                        require(++total[0] <= 64L * 1024 * 1024, "output-byte-bound");
                        if (retain) { require(size() < 1048576, "fixture-c-bound"); super.write(value); }
                    }
                    @Override public synchronized void write(byte[] data, int offset, int length) {
                        total[0] += length; require(total[0] <= 64L * 1024 * 1024, "output-byte-bound");
                        if (retain) { require(length <= 1048576 - size(), "fixture-c-bound"); super.write(data, offset, length); }
                    }
                    @Override public void close() {
                        if (retain) { require(fixtureC[0] == null, "duplicate-fixture-c"); fixtureC[0] = toString(java.nio.charset.StandardCharsets.UTF_8); }
                    }
                };
            }, "main.c");
        } catch (IllegalStateException failure) {
            if (!hasCause(failure, "java-checkpoint-nonsuspendable-progress-741")) throw failure;
            failed = true;
        }
        boolean expected = List.of("reorder", "replace", "array", "declaration", "parent", "generator-reorder",
                "generator-replace", "extra-intrinsic", "extra-generator", "wrong-target", "tampered").contains(mode);
        require(failed == expected, "verdict-"+mode);
        if (mode.equals("declaration") || mode.equals("parent")) require(mutated[0], "mutation-applied");
        if (!expected) {
            require(vm.getProblemProvider().getSevereProblems().isEmpty(), "diagnostics");
            require(!names.isEmpty() && total[0] > 0, "generated-output");
            require(fixtureC[0] != null && java.util.regex.Pattern.compile(
                    "(?s)void\\s+\\w*Fixture__clinit_\\(\\)\\s*\\{\\s*\\w*Fixture_value\\s*=\\s*TEAVM_GET_STRING\\(\\d+\\);\\s*\\}")
                    .matcher(fixtureC[0]).find(), "identity-emitted-initializer");
            require(!mode.equals("late") || late[0], "late-observed");
            require(intrinsics.get(target) != factories, "guard-installed");
        }
        System.out.println("CHECKPOINT_AMPLIFIER_PROBE " + mode + " PASS generated=" + !expected
                + " outputFiles=" + names.size() + " outputBytes=" + total[0]);
    }
}
