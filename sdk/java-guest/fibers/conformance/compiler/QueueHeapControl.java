package dev.latent.guest.runtime.compiler;

import java.lang.reflect.Array;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import org.teavm.asm.ClassReader;
import org.teavm.asm.ClassWriter;
import org.teavm.asm.commons.ClassRemapper;
import org.teavm.asm.commons.SimpleRemapper;
import org.teavm.asm.tree.ClassNode;
import org.teavm.model.ClassHierarchy;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.ProgramReader;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.EmptyInstruction;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClassRefsRenamer;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;

/** Executes the real pinned EventQueue on a JVM and checks the guest model replacement. */
public final class QueueHeapControl {
    private static final String QUEUE = "org.teavm.runtime.EventQueue";
    private static final String DONOR = "dev.latent.guest.runtime.EventQueueHeapDonor";
    private static final MethodDescriptor UPDATE = new MethodDescriptor("update", ValueType.INTEGER, ValueType.VOID);

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static byte[] resource(ClassLoader loader, String className) throws Exception {
        try (var stream = loader.getResourceAsStream(className.replace('.', '/') + ".class")) {
            require(stream != null, "queue-heap-class-resource");
            byte[] bytes = stream.readNBytes(1_000_001);
            require(bytes.length <= 1_000_000, "queue-heap-class-bound");
            return bytes;
        }
    }

    private static byte[] corrected(ClassLoader loader) throws Exception {
        var queue = new ClassNode();
        new ClassReader(resource(loader, QUEUE)).accept(queue, 0);
        var renamed = new ClassNode();
        var map = Map.of(DONOR.replace('.', '/'), QUEUE.replace('.', '/'),
                (DONOR + "$Node").replace('.', '/'), (QUEUE + "$Node").replace('.', '/'));
        new ClassReader(resource(loader, DONOR)).accept(
                new ClassRemapper(renamed, new SimpleRemapper(map)), 0);
        var replacements = renamed.methods.stream()
                .filter(method -> method.name.equals("update") && method.desc.equals("(I)V")).toList();
        require(replacements.size() == 1, "queue-heap-donor-method");
        int matches = 0;
        for (int index = 0; index < queue.methods.size(); ++index) {
            var method = queue.methods.get(index);
            if (method.name.equals("update") && method.desc.equals("(I)V")) {
                queue.methods.set(index, replacements.get(0));
                ++matches;
            }
        }
        require(matches == 1, "queue-heap-original-method");
        var writer = new ClassWriter(0);
        queue.accept(writer);
        return writer.toByteArray();
    }

    /** The nested Node/Event identities must come from the same actual queue copy. */
    private static final class QueueLoader extends ClassLoader {
        private final byte[] outer;
        QueueLoader(ClassLoader parent, byte[] outer) { super(parent); this.outer = outer; }

        @Override protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
            synchronized (getClassLoadingLock(name)) {
                Class<?> cls = findLoadedClass(name);
                if (cls == null && (name.equals(QUEUE) || name.startsWith(QUEUE + "$"))) {
                    try {
                        byte[] bytes = name.equals(QUEUE) ? outer : resource(getParent(), name);
                        cls = defineClass(name, bytes, 0, bytes.length);
                    } catch (Exception error) { throw new ClassNotFoundException(name, error); }
                }
                if (cls == null) cls = super.loadClass(name, false);
                if (resolve) resolveClass(cls);
                return cls;
            }
        }
    }

    private static List<Long> execute(Class<?> queue, long[] heap, int cancelledId, boolean repeat)
            throws Exception {
        for (int index = 1; index < heap.length; ++index)
            require(heap[(index - 1) / 2] <= heap[index], "queue-heap-invalid-fixture");
        ClassLoader loader = queue.getClassLoader();
        Class<?> event = Class.forName(QUEUE + "$Event", false, loader);
        Class<?> node = Class.forName(QUEUE + "$Node", false, loader);
        var constructor = node.getDeclaredConstructor(int.class, event, long.class);
        require(constructor.trySetAccessible(), "queue-heap-node-access");
        Object data = Array.newInstance(node, Math.max(16, heap.length));
        List<Long> observed = new ArrayList<>();
        for (int index = 0; index < heap.length; ++index) {
            final long deadline = heap[index];
            Object callback = Proxy.newProxyInstance(loader, new Class<?>[] { event }, (proxy, method, args) -> {
                if (method.getName().equals("run")) { observed.add(deadline); return null; }
                throw new AssertionError("queue-heap-unexpected-proxy-call");
            });
            Array.set(data, index, constructor.newInstance(index + 1, callback, deadline));
        }
        var entries = queue.getDeclaredField("data");
        var size = queue.getDeclaredField("size");
        require(entries.trySetAccessible() && size.trySetAccessible(), "queue-heap-state-access");
        entries.set(null, data);
        size.setInt(null, heap.length);
        var kill = queue.getDeclaredMethod("kill", int.class);
        kill.invoke(null, cancelledId);
        if (repeat) kill.invoke(null, cancelledId);
        var pump = queue.getDeclaredMethod("processSingle");
        for (int index = 0; size.getInt(null) > 0; ++index) {
            require(index < heap.length, "queue-heap-drain-bound");
            pump.invoke(null);
        }
        return observed;
    }

    private static List<Long> expected(long[] heap, int cancelledId) {
        List<Long> values = new ArrayList<>();
        for (int index = 0; index < heap.length; ++index)
            if (index + 1 != cancelledId) values.add(heap[index]);
        values.sort(Long::compareTo);
        return values;
    }

    private static void check(Class<?> queue, long[] heap, int cancelledId, boolean repeat) throws Exception {
        List<Long> observed = execute(queue, heap, cancelledId, repeat);
        require(observed.equals(expected(heap, cancelledId)), "queue-heap-order");
    }

    private static ClassHolderTransformerContext context(org.teavm.model.ClassReaderSource source) {
        return new ClassHolderTransformerContext() {
            public ClassHierarchy getHierarchy() { return new ClassHierarchy(source); }
            public org.teavm.diagnostics.Diagnostics getDiagnostics() { throw new AssertionError("diagnostics"); }
            public org.teavm.cache.IncrementalDependencyRegistration getIncrementalCache() {
                throw new AssertionError("cache");
            }
            public boolean isObfuscated() { return false; }
            public boolean isStrict() { return true; }
            public String getEntryPoint() { return "unused"; }
            public void submit(ClassHolder model) { throw new AssertionError("submit"); }
        };
    }

    private static void rejectDonor(ClassHolder queue, org.teavm.model.ClassReaderSource source) {
        try {
            EventQueueHeapMethods.transform(ModelUtils.copyClass(queue), context(source));
            throw new AssertionError("queue-heap-shadow-donor-accepted");
        } catch (IllegalStateException expected) {
            require("unexpected-maintained-event-queue-donor".equals(expected.getMessage()),
                    "queue-heap-shadow-donor-rejected-at-donor-boundary");
        }
    }

    private static void model(ClassLoader loader) throws Exception {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(loader),
                new ReferenceCache(), loader);
        ClassHolder original = source.get(QUEUE);
        require(original != null, "queue-heap-actual-model");
        ClassHolderTransformerContext context = context(source);
        var altered = ModelUtils.copyClass(original);
        altered.getMethod(UPDATE).getProgram().basicBlockAt(0).getFirstInstruction()
                .insertPrevious(new EmptyInstruction());
        try {
            EventQueueHeapMethods.transform(altered, context);
            throw new AssertionError("queue-heap-altered-preimage-accepted");
        } catch (IllegalStateException expected) { }

        var fixed = ModelUtils.copyClass(original);
        EventQueueHeapMethods.transform(fixed, context);
        try {
            EventQueueHeapMethods.transform(fixed, context);
            throw new AssertionError("queue-heap-repeat-accepted");
        } catch (IllegalStateException expected) { }

        var renamed = new ClassRefsRenamer(new ReferenceCache(), name -> {
            if (name.equals(DONOR)) return QUEUE;
            if (name.equals(DONOR + "$Node")) return QUEUE + "$Node";
            return name;
        }).rename(ModelUtils.copyClass(source.get(DONOR)));
        var same = EventQueueHeapMethods.class.getDeclaredMethod("same", ProgramReader.class, ProgramReader.class);
        require(same.trySetAccessible() && Boolean.TRUE.equals(same.invoke(null,
                fixed.getMethod(UPDATE).getProgram(), renamed.getMethod(UPDATE).getProgram())),
                "queue-heap-actual-model-uses-donor");

        var badBody = ModelUtils.copyClass(source.get(DONOR));
        badBody.getMethod(UPDATE).getProgram().basicBlockAt(0).getFirstInstruction()
                .insertPrevious(new EmptyInstruction());
        rejectDonor(original, name -> name.equals(DONOR) ? badBody : source.get(name));

        var badLayout = ModelUtils.copyClass(source.get(DONOR));
        badLayout.getField("data").setType(ValueType.arrayOf(ValueType.object("java.lang.Object")));
        rejectDonor(original, name -> name.equals(DONOR) ? badLayout : source.get(name));

        var badNode = ModelUtils.copyClass(source.get(DONOR + "$Node"));
        badNode.getField("time").setType(ValueType.INTEGER);
        rejectDonor(original, name -> name.equals(DONOR + "$Node") ? badNode : source.get(name));
    }

    public static void main(String[] args) throws Exception {
        ClassLoader parent = QueueHeapControl.class.getClassLoader();
        model(parent);
        byte[] originalBytes = resource(parent, QUEUE);
        Class<?> original = Class.forName(QUEUE, true, new QueueLoader(parent, originalBytes));
        long[] up = { 1, 4, 2, 5, 6, 7, 3 };
        require(execute(original, up, 4, false).equals(List.of(1L, 2L, 4L, 3L, 6L, 7L)),
                "queue-heap-original-upward-regression");

        Class<?> fixed = Class.forName(QUEUE, true, new QueueLoader(parent, corrected(parent)));
        check(fixed, up, 4, false);
        check(fixed, new long[] { 1, 2, 3, 4, 5, 6, 7 }, 2, false);
        check(fixed, new long[] { 1, 2, 1, 2, 2, 1, 1 }, 4, false);
        check(fixed, new long[] { 1, 2, 3, 4, 5, 6, 7 }, 1, false);
        check(fixed, new long[] { 1, 2, 3 }, 1, false);
        check(fixed, new long[] { Long.MIN_VALUE, -1, 0, 0 }, 2, false);
        check(fixed, new long[] { 1, 2, 3, 4, 5, 6, 7 }, 7, false);
        check(fixed, new long[] { 1 }, 1, true);
        check(fixed, new long[] { }, 999, true);
        check(fixed, new long[] { 1, 2, 3 }, 999, true);
        System.out.println("QUEUE_HEAP_CONTROL PASS actual-original-regression;actual-corrected-order;"
                + "up;down;ties;root;single-child;signed-min;last;singleton;empty;missing;repeat;model;preimage-negative;repeat-negative;donor-body-negative;donor-layout-negative;donor-node-negative");
    }
}
