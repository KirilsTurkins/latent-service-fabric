package org.teavm.dependency;

import java.nio.file.Files;
import org.teavm.backend.c.CTarget;
import org.teavm.backend.c.generate.CNameProvider;
import org.teavm.interop.Unmanaged;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.ElementModifier;
import org.teavm.model.ListableClassReaderSource;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.PreOptimizingClassHolderSource;
import org.teavm.model.Program;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.EmptyInstruction;
import org.teavm.model.instructions.JumpInstruction;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.vm.TeaVMBuilder;
import org.teavm.vm.TeaVMOptimizationLevel;
import org.teavm.vm.TeaVMPhase;
import org.teavm.vm.TeaVMProgressFeedback;
import org.teavm.vm.TeaVMProgressListener;

/** Real bytecode/JCL/C-frontend control; never executes the fixture initializers. */
public final class CheckpointCompilerControl {
    private static final String REFUSAL = "java-checkpoint-nonsuspendable-progress-741";

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static final class AnalysisComplete extends RuntimeException {
        private AnalysisComplete() {
            super(null, null, false, false);
        }
    }

    private static final class ProbeTarget extends CTarget {
        boolean analyzed;

        ProbeTarget() {
            super(new CNameProvider());
            setMinHeapSize(1024 * 1024);
            setMaxHeapSize(4 * 1024 * 1024);
        }

        @Override
        public void analyzeBeforeOptimizations(ListableClassReaderSource source) {
            // Invoke the real owner after dependency completion and normal
            // JCL/C transformations. Do not substitute a synthetic call graph.
            super.analyzeBeforeOptimizations(source);
            analyzed = true;
            throw new AnalysisComplete();
        }
    }

    // Ordinary cases use the exact production CTarget. Stop at the first
    // progress callback after its finder returned, before any C output.
    private static final class StopAfterFinder implements TeaVMProgressListener {
        private final CTarget target;
        private final java.lang.reflect.Field asyncMethods;
        boolean observed;

        StopAfterFinder(CTarget target) {
            this.target = target;
            try {
                asyncMethods = CTarget.class.getDeclaredField("asyncMethods");
                require(asyncMethods.trySetAccessible(), "checkpoint-control-target-observation");
            } catch (ReflectiveOperationException failure) {
                throw new AssertionError("checkpoint-control-target-observation", failure);
            }
        }

        private void stopIfAnalyzed() {
            try {
                if (asyncMethods.get(target) != null) {
                    observed = true;
                    throw new AnalysisComplete();
                }
            } catch (IllegalAccessException failure) {
                throw new AssertionError("checkpoint-control-target-observation", failure);
            }
        }

        @Override public TeaVMProgressFeedback progressReached(int progress) {
            stopIfAnalyzed();
            return TeaVMProgressFeedback.CONTINUE;
        }

        @Override public TeaVMProgressFeedback phaseStarted(TeaVMPhase phase, int count) {
            stopIfAnalyzed();
            return TeaVMProgressFeedback.CONTINUE;
        }
    }

    public static final class Finite {
        private static final int[] VALUES = new int[256];
        private static int result;
        static {
            for (int index = 0; index < VALUES.length; ++index) VALUES[index] = index;
        }
        public static void main(String[] arguments) {
            result = VALUES[arguments.length & 255];
        }
    }

    // The fixture is analyzed by the real C frontend but is never executed:
    // it makes the exact StringInfo metadata getter reachable in an initializer.
    public static final class StringInfoAccess {
        private static String result = new org.teavm.runtime.StringInfo().getStringObject();
        public static void main(String[] arguments) {
            if (arguments.length != 0) result = arguments[0];
        }
    }

    // Direct public calls with unproven receiver or operands must refuse.
    public static final class ClassInfoEnumCountAccess {
        private static int result = new org.teavm.runtime.reflect.ClassInfo().enumConstantCount();
        public static void main(String[] arguments) { result += arguments.length; }
    }

    // The zero index still has an unproven receiver.
    public static final class ClassInfoEnumElementAccess {
        private static Object result = new org.teavm.runtime.reflect.ClassInfo().enumConstant(0);
        public static void main(String[] arguments) { if (arguments.length != 0) result = arguments[0]; }
    }

    public static final class ClassInfoEnumNegativeAccess {
        private static Object result = new org.teavm.runtime.reflect.ClassInfo().enumConstant(-1);
        public static void main(String[] arguments) { if (arguments.length != 0) result = arguments[0]; }
    }

    public static final class ClassInfoEnumHighAccess {
        private static Object result = new org.teavm.runtime.reflect.ClassInfo().enumConstant(Integer.MAX_VALUE);
        public static void main(String[] arguments) { if (arguments.length != 0) result = arguments[0]; }
    }

    public static final class ClassInfoSuperinterfaceAccess {
        private static Object result = new org.teavm.runtime.reflect.ClassInfo().superinterface(-1);
        public static void main(String[] arguments) { if (arguments.length != 0) result = arguments[0]; }
    }

    public static final class ClassInfoArrayLengthAccess {
        private static int result = new org.teavm.runtime.reflect.ClassInfo().arrayLength(new Object());
        public static void main(String[] arguments) { result += arguments.length; }
    }

    public static final class ClassInfoManagedCountAccess {
        private static volatile int result;
        public static void main(String[] arguments) {
            result = new org.teavm.runtime.reflect.ClassInfo().enumConstantCount();
        }
    }

    public static final class ClassInfoManagedClassObjectAccess {
        private static volatile Object result;
        public static void main(String[] arguments) {
            result = new org.teavm.runtime.reflect.ClassInfo().classObject();
        }
    }

    public static final class OrdinaryClassAccess {
        private static volatile Object result;
        public static void main(String[] arguments) {
            Object value = arguments.length == 0 ? new Object() : arguments;
            result = value.getClass().getName();
        }
    }

    public static final class InitializerPolling {
        private static volatile boolean ready;
        static {
            while (!ready) {
                // No checkpoint call and no finite induction argument.
            }
        }
        public static void main(String[] arguments) {
            ready = arguments.length != 0;
        }
    }

    public static final class UnmanagedPolling {
        private static volatile boolean ready;
        @Unmanaged
        private static void poll() {
            while (!ready) {
                // A loop-free caller does not make its unmanaged callee finite.
            }
        }
        public static void main(String[] arguments) {
            poll();
        }
    }

    public static final class ManagedPolling {
        private static volatile boolean ready;
        public static void main(String[] arguments) {
            while (!ready) {
                // This checks exclusion, not managed runtime fairness.
            }
        }
    }

    public static final class RecursiveInitializer {
        private static int result = recurse(0);
        private static int recurse(int value) {
            return recurse(value + 1);
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class FiniteUnmanaged {
        private static int result;
        @Unmanaged
        private static int sum(int limit) {
            int total = 0;
            for (int index = 0; index < limit; ++index) total += index;
            return total;
        }
        public static void main(String[] arguments) {
            result = sum(arguments.length);
        }
    }

    public static final class NestedCounted {
        private static int result;
        static {
            for (int outer = 0; outer < 4; ++outer) {
                for (int inner = 0; inner < 3; ++inner) result += outer + inner;
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class ChangingBound {
        private static volatile int limit = 3;
        private static int result;
        static {
            // The signed induction rank decreases even when the bound changes.
            for (int index = 0; index < limit; ++index) {
                limit = (index & 1) + 4;
                result = index;
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class WrappingCounted {
        private static volatile int limit = Integer.MAX_VALUE;
        private static int result;
        static {
            // A non-strict test admits MAX_VALUE and lets the increment wrap.
            for (int index = Integer.MAX_VALUE; index <= limit; ++index) result = index;
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class ResetCounted {
        private static volatile int limit = 4;
        private static int result;
        static {
            for (int index = 0; index < limit; ++index) {
                result = index;
                index = 0;
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class ExceptionalRetry {
        private static volatile int divisor;
        private static int result;
        static {
            for (int index = 0; index < 3;) {
                try {
                    result = 1 / divisor;
                    ++index;
                } catch (ArithmeticException retry) {
                    // The exceptional backedge bypasses the induction update.
                }
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    @Unmanaged
    public static final class UnmanagedClassPolling {
        private static volatile boolean ready;
        private static void poll() {
            while (!ready) { }
        }
        public static void main(String[] arguments) {
            poll();
        }
    }

    public static final class TransitiveInitializer {
        private static volatile boolean ready;
        private static int result = first();
        private static int first() {
            return second();
        }
        private static int second() {
            while (!ready) { }
            return 1;
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class NearMaxCounted {
        private static int result;
        static {
            for (int index = Integer.MAX_VALUE - 2; index < Integer.MAX_VALUE; ++index) result = index;
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class NestedPolling {
        private static volatile boolean ready;
        private static int result;
        static {
            for (int index = 0; index < 3; ++index) {
                while (!ready) { }
                result = index;
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class MutualRecursion {
        private static int result = first(0);
        private static int first(int value) {
            return second(value + 1);
        }
        private static int second(int value) {
            return first(value + 1);
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class VirtualInitializer {
        private interface Supplier {
            int get();
        }
        private static final class PollingSupplier implements Supplier {
            private static volatile boolean ready;
            public int get() {
                while (!ready) { }
                return 1;
            }
        }
        private static int read(Supplier supplier) {
            return supplier.get();
        }
        private static int result = read(new PollingSupplier());
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    private static void loop(MethodHolder method) {
        Program program = new Program();
        for (int index = 0; index <= method.parameterCount(); ++index) program.createVariable();
        var block = program.createBasicBlock();
        var jump = new JumpInstruction();
        jump.setTarget(block);
        block.add(jump);
        method.setProgram(program);
    }

    private static boolean mutate(ClassHolder cls, String mutation) {
        if (mutation.equals("runtime-initializer") && cls.getName().equals("org.teavm.runtime.Allocator")) {
            var descriptor = new MethodDescriptor("<clinit>", ValueType.VOID);
            require(cls.getMethod(descriptor) == null, "checkpoint-control-original-initializer-absent");
            var method = new MethodHolder(descriptor);
            method.getModifiers().add(ElementModifier.STATIC);
            loop(method);
            cls.addMethod(method);
            return true;
        }
        if (mutation.equals("class-object-helper") && cls.getName().equals("java.lang.Class")) {
            var method = cls.getMethod(new MethodDescriptor("createClass",
                    ValueType.object("org.teavm.runtime.reflect.ClassInfo"), ValueType.object("java.lang.Class")));
            require(method != null, "checkpoint-control-class-object-helper-present");
            loop(method);
            return true;
        }
        if (mutation.equals("string-copy-body") && cls.getName().equals("java.lang.String")) {
            var method = cls.getMethod(new MethodDescriptor("<init>", ValueType.arrayOf(ValueType.CHARACTER),
                    ValueType.VOID));
            require(method != null && method.getProgram() != null, "checkpoint-control-string-copy-body-present");
            method.getProgram().basicBlockAt(0).getFirstInstruction().insertPrevious(new EmptyInstruction());
            return true;
        }
        if (mutation.equals("class-info-declaration") && cls.getName().equals("org.teavm.runtime.reflect.ClassInfo")) {
            var method = cls.getMethod(new MethodDescriptor("enumConstantCount", ValueType.INTEGER));
            require(method != null && !method.hasModifier(ElementModifier.FINAL),
                    "checkpoint-control-class-info-original-declaration");
            method.getModifiers().add(ElementModifier.FINAL);
            return true;
        }
        if (mutation.equals("class-info-layout") && cls.getName().equals("org.teavm.runtime.RuntimeClass")) {
            var field = new org.teavm.model.FieldHolder("changedEnumCountLayout");
            field.setType(ValueType.INTEGER);
            cls.addField(field);
            return true;
        }
        if (mutation.equals("string-info-declaration") && cls.getName().equals("org.teavm.runtime.StringInfo")) {
            var method = cls.getMethod(new MethodDescriptor("getStringObject", ValueType.object("java.lang.String")));
            require(method != null && !method.hasModifier(ElementModifier.FINAL),
                    "checkpoint-control-string-info-original-declaration");
            method.getModifiers().add(ElementModifier.FINAL);
            return true;
        }
        if (mutation.equals("string-info-parent") && cls.getName().equals("org.teavm.runtime.reflect.ReflectionInfo")) {
            var field = new org.teavm.model.FieldHolder("changedLayout");
            field.setType(ValueType.INTEGER);
            cls.addField(field);
            return true;
        }
        return false;
    }

    private static void checkCompilerArchive(boolean corrected) throws Exception {
        Class<?> finderType = org.teavm.model.util.AsyncMethodFinder.class;
        java.lang.reflect.Method verifier;
        try {
            verifier = finderType.getDeclaredMethod("pinnedStringInfoArchive", java.nio.file.Path.class);
        } catch (NoSuchMethodException missing) {
            require(!corrected, "checkpoint-control-archive-verifier-missing");
            return;
        }
        require(corrected && verifier.trySetAccessible(), "checkpoint-control-archive-verifier-unexpected");
        var finder = new org.teavm.model.util.AsyncMethodFinder(null, null);
        java.nio.file.Path original = java.nio.file.Path.of(CTarget.class.getProtectionDomain()
                .getCodeSource().getLocation().toURI()).toRealPath();
        require(Files.size(original) <= 67108864 && Boolean.TRUE.equals(verifier.invoke(finder, original)),
                "checkpoint-control-original-compiler-archive");
        for (String selected : new String[] {
                "org/teavm/backend/c/intrinsic/reflection/StringInfoIntrinsic.class",
                "org/teavm/backend/c/intrinsic/reflection/ClassInfoIntrinsic.class",
                "org/teavm/backend/c/core.h",
                "org/teavm/model/util/TypeInferer.class" }) {
            java.nio.file.Path altered = Files.createTempFile("checkpoint-compiler-archive-", ".jar");
            try {
                int count = 0, changed = 0;
                long total = 0;
                try (var input = new java.util.zip.ZipFile(original.toFile());
                        var output = new java.util.zip.ZipOutputStream(Files.newOutputStream(altered))) {
                    var entries = input.entries();
                    while (entries.hasMoreElements()) {
                        var entry = entries.nextElement();
                        long size = entry.getSize();
                        require(++count <= 32768 && size >= 0 && size <= 16777216,
                                "checkpoint-control-compiler-archive-entry-bound");
                        total = Math.addExact(total, size);
                        require(total <= 134217728, "checkpoint-control-compiler-archive-total-bound");
                        byte[] bytes;
                        try (var stream = input.getInputStream(entry)) {
                            bytes = stream.readNBytes((int) size + 1);
                        }
                        require(bytes.length == size, "checkpoint-control-compiler-archive-entry-size");
                        if (entry.getName().equals(selected)) {
                            require(bytes.length > 0, "checkpoint-control-compiler-archive-entry-empty");
                            bytes[bytes.length - 1] ^= 1;
                            ++changed;
                        }
                        output.putNextEntry(new java.util.zip.ZipEntry(entry.getName()));
                        output.write(bytes);
                        output.closeEntry();
                    }
                }
                require(changed == 1 && Boolean.FALSE.equals(verifier.invoke(finder, altered)),
                        "checkpoint-control-altered-compiler-archive-refused");
            } finally {
                Files.deleteIfExists(altered);
            }
        }
    }

    private static void checkClassInfoOperandFence(boolean corrected) throws Exception {
        var finder = org.teavm.model.util.AsyncMethodFinder.class;
        java.lang.reflect.Method fence;
        try {
            fence = finder.getDeclaredMethod("progressUnprovenClassInfoOperands",
                    org.teavm.model.MethodReference.class);
        } catch (NoSuchMethodException missing) {
            require(!corrected, "checkpoint-control-class-info-fence-missing");
            return;
        }
        require(corrected && fence.trySetAccessible(), "checkpoint-control-class-info-fence-access");
        for (String name : new String[] {
                "modifiers",
                "primitiveKind",
                "superinterfaceCount",
                "itemType",
                "declaringClass",
                "enclosingClass",
                "parent",
                "name",
                "simpleName",
                "superinterface",
                "arrayLength",
                "isSuperTypeOf",
                "reflection",
                "classObject",
                "enumConstantCount",
                "enumConstant",
                "arrayType",
                "newArrayInstance",
                "getItem",
                "putItem",
                "initialize" }) {
            var method = new org.teavm.model.MethodReference(
                    "org.teavm.runtime.reflect.ClassInfo", name, ValueType.VOID);
            require(Boolean.TRUE.equals(fence.invoke(null, method)), "checkpoint-control-class-info-fence-scope");
        }
        var otherOwner = new org.teavm.model.MethodReference("example.Unrelated", "enumConstant", ValueType.VOID);
        var otherName = new org.teavm.model.MethodReference(
                "org.teavm.runtime.reflect.ClassInfo", "unrelated", ValueType.VOID);
        require(Boolean.FALSE.equals(fence.invoke(null, otherOwner)), "checkpoint-control-class-info-fence-owner");
        require(Boolean.FALSE.equals(fence.invoke(null, otherName)), "checkpoint-control-class-info-fence-name");
    }

    private static void checkClassInfoHeader(boolean corrected) throws Exception {
        java.lang.reflect.Method verifier;
        try {
            verifier = org.teavm.model.util.AsyncMethodFinder.class.getDeclaredMethod(
                    "pinnedClassInfoResource", ClassLoader.class);
        } catch (NoSuchMethodException missing) {
            require(!corrected, "checkpoint-control-class-info-resource-verifier-missing");
            return;
        }
        require(corrected && verifier.trySetAccessible(), "checkpoint-control-class-info-resource-verifier");
        final String resource = "org/teavm/backend/c/core.h";
        ClassLoader original = CTarget.class.getClassLoader();
        require(Boolean.TRUE.equals(verifier.invoke(null, original)), "checkpoint-control-class-info-header-original");
        byte[] altered;
        try (var input = original.getResourceAsStream(resource)) {
            require(input != null, "checkpoint-control-class-info-header-present");
            altered = input.readNBytes(9451);
        }
        require(altered.length == 9450, "checkpoint-control-class-info-header-size");
        altered[17] ^= 1;
        ClassLoader shadow = new ClassLoader(original) {
            @Override public java.io.InputStream getResourceAsStream(String name) {
                return name.equals(resource) ? new java.io.ByteArrayInputStream(altered)
                        : super.getResourceAsStream(name);
            }
        };
        ClassLoader missing = new ClassLoader(original) {
            @Override public java.io.InputStream getResourceAsStream(String name) {
                return name.equals(resource) ? null : super.getResourceAsStream(name);
            }
        };
        require(Boolean.FALSE.equals(verifier.invoke(null, shadow))
                        && Boolean.FALSE.equals(verifier.invoke(null, missing)),
                "checkpoint-control-class-info-shadow-header-refused");
    }

    private static void check(String entry, boolean corrected, boolean unsafe, String mutation) {
        check(entry, corrected, unsafe, mutation, false);
    }

    private static void check(String entry, boolean corrected, boolean unsafe, String mutation,
            boolean alternateTarget) {
        compileWithTarget(entry, corrected, unsafe, mutation,
                alternateTarget ? new ProbeTarget() : new CTarget(new CNameProvider()));
    }

    private static org.teavm.vm.TeaVM compileWithTarget(String entry, boolean corrected, boolean unsafe,
            String mutation, CTarget target) {
        target.setMinHeapSize(1024 * 1024);
        target.setMaxHeapSize(4 * 1024 * 1024);
        var stop = new StopAfterFinder(target);
        var references = new ReferenceCache();
        var builder = new TeaVMBuilder(target).setReferenceCache(references);
        // The split-loader control supplies the same explicit application loader
        // boundary as the production in-process Gradle build strategy.
        var loader = Thread.currentThread().getContextClassLoader();
        builder.setClassLoader(loader).setResourceProvider(new ClasspathResourceProvider(loader));
        // Match TeaVMTool's maintained non-incremental input preparation.
        builder.setClassSource(new PreOptimizingClassHolderSource(new ClasspathClassHolderSource(
                builder.getResourceProvider(), references, builder.getClassLoader())));
        var vm = builder.build();
        vm.setProgressListener(stop);
        vm.setOptimizationLevel(TeaVMOptimizationLevel.FULL);
        vm.installPlugins();
        boolean[] changed = { false };
        vm.add((ClassHolder cls, ClassHolderTransformerContext context) -> {
            changed[0] |= mutate(cls, mutation);
        });
        vm.setEntryPoint(entry);
        boolean refused = false;
        try {
            vm.build(name -> {
                throw new AssertionError("checkpoint-control-must-not-generate-code");
            }, "unused.c");
            throw new AssertionError("checkpoint-control-must-reach-owning-finder");
        } catch (AnalysisComplete completed) {
            require(stop.observed || target instanceof ProbeTarget && ((ProbeTarget) target).analyzed,
                    "checkpoint-control-real-c-analysis-completed");
        } catch (IllegalStateException failure) {
            if (!(corrected && unsafe && REFUSAL.equals(failure.getMessage()))) {
                throw new AssertionError("checkpoint-control-unexpected-compiler-refusal", failure);
            }
            refused = true;
        }
        require(mutation.isEmpty() || changed[0], "checkpoint-control-mutation-was-applied");
        require(vm.getProblemProvider().getSevereProblems().isEmpty(),
                "checkpoint-control-no-hidden-compiler-errors");
        require(refused == (corrected && unsafe), "checkpoint-control-progress-verdict");
        return vm;
    }

    private static void checkCompilerCacheIsolation(boolean corrected) throws Exception {
        var target = new CTarget(new CNameProvider());
        var first = compileWithTarget(StringInfoAccess.class.getName(), corrected, false, "", target);
        java.util.Map<Object, Boolean> cache = null;
        if (corrected) {
            var field = org.teavm.model.util.AsyncMethodFinder.class.getDeclaredField("progressStringInfoArchives");
            require(field.trySetAccessible(), "checkpoint-control-compiler-cache-access");
            Object raw = field.get(null);
            require(raw instanceof java.util.WeakHashMap, "checkpoint-control-compiler-cache-type");
            @SuppressWarnings("unchecked")
            var typedCache = (java.util.Map<Object, Boolean>) raw;
            cache = typedCache;
            synchronized (cache) {
                require(Boolean.TRUE.equals(cache.get(first)) && !cache.containsKey(target),
                        "checkpoint-control-first-vm-cache");
                // A failed receipt for the first compiler must not affect another
                // compiler even if it is given the very same CTarget object.
                cache.put(first, Boolean.FALSE);
            }
        }
        var methods = CTarget.class.getDeclaredField("asyncMethods");
        require(methods.trySetAccessible() && methods.get(target) != null,
                "checkpoint-control-reused-target-observation");
        methods.set(target, null);
        var second = compileWithTarget(StringInfoAccess.class.getName(), corrected, false, "", target);
        require(first != second, "checkpoint-control-distinct-compiler-instances");
        if (corrected) {
            synchronized (cache) {
                require(Boolean.FALSE.equals(cache.get(first)) && Boolean.TRUE.equals(cache.get(second))
                                && !cache.containsKey(target),
                        "checkpoint-control-compiler-cache-isolation");
            }
        }
    }

    public static void checkClasslibIdentity(String mode) {
        require(mode.equals("original") || mode.equals("corrected"), "checkpoint-classlib-control-mode");
        // A changed archive retains all class bytes but is not the locked proof
        // source. Only the corrected finder must refuse its finite initializer.
        check(Finite.class.getName(), mode.equals("corrected"), true, "");
    }

    public static void main(String[] arguments) {
        require(arguments.length == 1 && (arguments[0].equals("original")
                || arguments[0].equals("corrected")), "checkpoint-compiler-control-mode");
        boolean corrected = arguments[0].equals("corrected");
        try {
            checkClassInfoOperandFence(corrected);
        } catch (Exception failure) {
            throw new AssertionError("checkpoint-control-class-info-fence", failure);
        }
        check(ClassInfoEnumCountAccess.class.getName(), corrected, true, "");
        check(ClassInfoEnumElementAccess.class.getName(), corrected, true, "");
        check(ClassInfoEnumNegativeAccess.class.getName(), corrected, true, "");
        check(ClassInfoEnumHighAccess.class.getName(), corrected, true, "");
        check(ClassInfoSuperinterfaceAccess.class.getName(), corrected, true, "");
        check(ClassInfoArrayLengthAccess.class.getName(), corrected, true, "");
        check(ClassInfoManagedCountAccess.class.getName(), corrected, true, "");
        check(ClassInfoManagedClassObjectAccess.class.getName(), corrected, true, "");
        System.err.println("CHECKPOINT_CLASSINFO_DIRECT_CONTROL PASS " + arguments[0]);
        checkCompatibility(corrected);
        check(InitializerPolling.class.getName(), corrected, true, "");
        check(UnmanagedPolling.class.getName(), corrected, true, "");
        check(ManagedPolling.class.getName(), corrected, false, "");
        check(RecursiveInitializer.class.getName(), corrected, true, "");
        for (String mutation : new String[] { "runtime-initializer", "class-object-helper", "string-copy-body" }) {
            check(Finite.class.getName(), corrected, true, mutation);
        }
        check(FiniteUnmanaged.class.getName(), corrected, false, "");
        check(NestedCounted.class.getName(), corrected, false, "");
        check(ChangingBound.class.getName(), corrected, false, "");
        check(WrappingCounted.class.getName(), corrected, true, "");
        check(ResetCounted.class.getName(), corrected, true, "");
        check(ExceptionalRetry.class.getName(), corrected, true, "");
        check(UnmanagedClassPolling.class.getName(), corrected, true, "");
        check(TransitiveInitializer.class.getName(), corrected, true, "");
        check(NearMaxCounted.class.getName(), corrected, false, "");
        check(NestedPolling.class.getName(), corrected, true, "");
        check(MutualRecursion.class.getName(), corrected, true, "");
        check(VirtualInitializer.class.getName(), corrected, true, "");
        check(StringInfoAccess.class.getName(), corrected, false, "");
        for (String mutation : new String[] { "string-info-declaration", "string-info-parent" }) {
            check(StringInfoAccess.class.getName(), corrected, true, mutation);
        }
        check(StringInfoAccess.class.getName(), corrected, true, "", true);
        for (String mutation : new String[] { "class-info-declaration", "string-info-parent", "class-info-layout" }) {
            check(ClassInfoEnumCountAccess.class.getName(), corrected, true, mutation);
        }
        check(ClassInfoEnumCountAccess.class.getName(), corrected, true, "", true);
        try {
            checkClassInfoHeader(corrected);
            checkCompilerArchive(corrected);
            checkCompilerCacheIsolation(corrected);
        } catch (Exception failure) {
            throw new AssertionError("checkpoint-control-compiler-archive", failure);
        }
        System.out.println("CHECKPOINT_COMPILER_CONTROL PASS " + arguments[0]
                + ";finite;ordinary-class-reflection;initializer;unmanaged;managed;recursion;runtime-initializer;class-object-helper;string-copy-body;finite-unmanaged;nested-counted;changing-bound;wrapping-counted;reset-counted;exceptional-retry;unmanaged-class;transitive-initializer;near-max-counted;nested-polling;mutual-recursion;virtual-initializer;string-info-getter;string-info-declaration;string-info-parent;string-info-target;class-info-enum-count-refused;class-info-enum-element-refused;class-info-enum-negative-refused;class-info-enum-high-refused;class-info-superinterface-refused;class-info-array-length-refused;class-info-managed-count-refused;class-info-managed-class-object-refused;class-info-declaration-refused;class-info-parent-refused;class-info-layout-refused;class-info-target-refused;class-info-fence-scope;class-info-header-shadow;compiler-archive-control;compiler-cache-isolation");
    }
    private static void checkCompatibility(boolean corrected) {
        AssertionError first = null;
        try {
            check(Finite.class.getName(), corrected, false, "");
            System.err.println("CHECKPOINT_COMPATIBILITY finite PASS");
        } catch (AssertionError failure) {
            System.err.println("CHECKPOINT_COMPATIBILITY finite FAIL");
            first = failure;
        }
        try {
            check(OrdinaryClassAccess.class.getName(), corrected, false, "");
            System.err.println("CHECKPOINT_COMPATIBILITY class-reflection PASS");
        } catch (AssertionError failure) {
            System.err.println("CHECKPOINT_COMPATIBILITY class-reflection FAIL");
            if (first == null) {
                first = failure;
            } else {
                first.addSuppressed(failure);
            }
        }
        if (first != null) {
            throw first;
        }
    }
}
