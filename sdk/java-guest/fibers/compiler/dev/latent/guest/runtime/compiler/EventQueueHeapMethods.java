package dev.latent.guest.runtime.compiler;

import java.io.OutputStream;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.HexFormat;
import org.teavm.cache.InMemorySymbolTable;
import org.teavm.cache.ClassIO;
import org.teavm.cache.ProgramIO;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassReader;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.PreOptimizingClassHolderSource;
import org.teavm.model.ProgramReader;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.util.ModelUtils;
import org.teavm.model.util.ProgramUtils;
import org.teavm.parsing.ClassRefsRenamer;
import org.teavm.parsing.resource.ResourceBytecodeClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;

/** One source-authenticated correction to the pinned runtime's heap repair. */
final class EventQueueHeapMethods {
    private static final String QUEUE = "org.teavm.runtime.EventQueue";
    private static final String DONOR = "dev.latent.guest.runtime.EventQueueHeapDonor";
    private static final MethodDescriptor UPDATE =
            new MethodDescriptor("update", ValueType.INTEGER, ValueType.VOID);
    private static final MethodDescriptor REMOVE =
            new MethodDescriptor("remove", ValueType.INTEGER, ValueType.VOID);
    private static final MethodDescriptor NODE_INIT = new MethodDescriptor("<init>", ValueType.INTEGER,
            ValueType.object(QUEUE + "$Event"), ValueType.LONG, ValueType.VOID);
    private static final MethodDescriptor KILL =
            new MethodDescriptor("kill", ValueType.INTEGER, ValueType.VOID);
    private static final MethodDescriptor OFFER = new MethodDescriptor("offer",
            ValueType.object(QUEUE + "$Event"), ValueType.LONG, ValueType.INTEGER);
    private static final MethodDescriptor PUMP = new MethodDescriptor("processSingle", ValueType.LONG);

    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("unexpected-maintained-event-queue-heap");
    }

    // Fixed site numbers and bit masks only; no application names or code are reported.
    private static void requireAt(boolean value, int site) {
        if (!value) throw new IllegalStateException("unexpected-maintained-event-queue-heap-site-" + site);
    }

    private static void authenticate(ClassLoader loader, String name, int length, String digest) throws Exception {
        try (InputStream input = loader.getResourceAsStream(name)) {
            require(input != null);
            byte[] bytes = input.readNBytes(length + 1);
            require(bytes.length == length);
            require(MessageDigest.isEqual(MessageDigest.getInstance("SHA-256").digest(bytes),
                    HexFormat.of().parseHex(digest)));
        }
    }

    private static ResourceBytecodeClassHolderSource source(ClassLoader loader) {
        return new ResourceBytecodeClassHolderSource(new ClasspathResourceProvider(loader), new ReferenceCache());
    }

    private static boolean bounded(ProgramReader program) {
        if (program == null || program.basicBlockCount() > 256 || program.variableCount() > 4096) return false;
        long instructions = 0, phis = 0, handlers = 0;
        for (var block : program.getBasicBlocks()) {
            instructions += block.instructionCount();
            phis += block.readPhis().size();
            handlers += block.readTryCatchBlocks().size();
            if (instructions > 16384 || phis > 4096 || handlers > 4096) return false;
        }
        return true;
    }

    private static boolean same(ProgramReader first, ProgramReader second) throws Exception {
        if (!bounded(first) || !bounded(second)) return false;
        // Shared symbol tables ensure a changed operand cannot acquire the same
        // independent numeric ID. Stream instead of buffering program bodies.
        var io = new ProgramIO(new ReferenceCache(), new InMemorySymbolTable(),
                new InMemorySymbolTable(), new InMemorySymbolTable());
        var left = MessageDigest.getInstance("SHA-256");
        var right = MessageDigest.getInstance("SHA-256");
        try (var a = new java.security.DigestOutputStream(OutputStream.nullOutputStream(), left);
             var b = new java.security.DigestOutputStream(OutputStream.nullOutputStream(), right)) {
            io.write(first, a);
            io.write(second, b);
        }
        return MessageDigest.isEqual(left.digest(), right.digest());
    }

    private static boolean sameClass(ClassReader expected, ClassReader actual) throws Exception {
        if (expected == null || actual == null || !expected.getName().equals(actual.getName())
                || expected.getFields().size() > 16 || expected.getMethods().size() > 16
                || expected.getFields().size() != actual.getFields().size()
                || expected.getMethods().size() != actual.getMethods().size()) return false;
        for (var method : expected.getMethods()) {
            var other = actual.getMethod(method.getDescriptor());
            if (other == null) return false;
            var a = method.getProgram();
            var b = other.getProgram();
            if (a == null || b == null) { if (a != b) return false; }
            else if (!same(a, b)) return false;
        }
        var a = ModelUtils.copyClass(expected);
        var b = ModelUtils.copyClass(actual);
        for (var method : a.getMethods()) method.setProgram(null);
        for (var method : b.getMethods()) method.setProgram(null);
        var io = new ClassIO(new ReferenceCache(), new InMemorySymbolTable(),
                new InMemorySymbolTable(), new InMemorySymbolTable());
        var left = MessageDigest.getInstance("SHA-256");
        var right = MessageDigest.getInstance("SHA-256");
        try (var outA = new java.security.DigestOutputStream(OutputStream.nullOutputStream(), left);
             var outB = new java.security.DigestOutputStream(OutputStream.nullOutputStream(), right)) {
            io.writeClass(outA, a);
            io.writeClass(outB, b);
        }
        return MessageDigest.isEqual(left.digest(), right.digest());
    }

    private static void trustedDonorResource(ClassLoader loader, String name) throws Exception {
        Class<?> trusted = Class.forName(name, false, loader);
        Class<?> plugin = EventQueueHeapMethods.class;
        require(trusted.getClassLoader() == loader && plugin.getClassLoader() == loader);
        var ownCode = plugin.getProtectionDomain().getCodeSource();
        var donorCode = trusted.getProtectionDomain().getCodeSource();
        require(ownCode != null && donorCode != null
                && ownCode.getLocation().getProtocol().equals("file")
                && donorCode.getLocation().getProtocol().equals("file"));
        var root = java.nio.file.Path.of(ownCode.getLocation().toURI()).toRealPath();
        require(root.equals(java.nio.file.Path.of(donorCode.getLocation().toURI()).toRealPath()));
        String entry = name.replace('.', '/') + ".class";
        var resource = loader.getResource(entry);
        require(resource != null);
        if (java.nio.file.Files.isDirectory(root)) {
            require(resource.getProtocol().equals("file")
                    && java.nio.file.Path.of(resource.toURI()).toRealPath().equals(root.resolve(entry).toRealPath()));
        } else {
            require(resource.getProtocol().equals("jar"));
            var connection = resource.openConnection();
            require(connection instanceof java.net.JarURLConnection);
            var jar = (java.net.JarURLConnection) connection;
            require(entry.equals(jar.getEntryName()) && jar.getJarFileURL().getProtocol().equals("file")
                    && java.nio.file.Path.of(jar.getJarFileURL().toURI()).toRealPath().equals(root));
        }
        try (var input = resource.openStream()) {
            byte[] bytes = input.readNBytes(1048577);
            require(bytes.length >= 4 && bytes.length <= 1048576
                    && bytes[0] == (byte) 0xca && bytes[1] == (byte) 0xfe
                    && bytes[2] == (byte) 0xba && bytes[3] == (byte) 0xbe);
        }
    }

    private static boolean matches(ClassHolder expected, ClassHolder actual) throws Exception {
        if (expected == null) return false;
        for (MethodDescriptor descriptor : new MethodDescriptor[] { OFFER, KILL, REMOVE, UPDATE, PUMP }) {
            var baseline = expected.getMethod(descriptor);
            var candidate = actual.getMethod(descriptor);
            if (baseline == null || candidate == null || !same(baseline.getProgram(), candidate.getProgram()))
                return false;
        }
        return true;
    }

    // Evaluated only after a preimage has already been refused. Bits identify
    // the five fixed queue methods in their existing comparison order.
    private static int queueMismatch(ClassHolder expected, ClassHolder actual) throws Exception {
        if (expected == null) return 32;
        int mask = 0, index = 0;
        for (MethodDescriptor descriptor : new MethodDescriptor[] { OFFER, KILL, REMOVE, UPDATE, PUMP }) {
            var baseline = expected.getMethod(descriptor);
            var candidate = actual.getMethod(descriptor);
            if (baseline == null || candidate == null || !same(baseline.getProgram(), candidate.getProgram()))
                mask |= 1 << index;
            index++;
        }
        return mask;
    }

    private static int nodeMismatch(ClassReader expected, ClassReader actual) throws Exception {
        if (expected == null || actual == null) return 64;
        int mask = 0;
        if (!"java.lang.Object".equals(actual.getParent())) mask |= 1;
        if (actual.getFields().size() != 3 || actual.getMethods().size() != 1) mask |= 2;
        var id = actual.getField("id");
        var event = actual.getField("event");
        var time = actual.getField("time");
        if (id == null || !id.hasModifier(ElementModifier.FINAL) || !id.getType().equals(ValueType.INTEGER)) mask |= 4;
        if (event == null || !event.hasModifier(ElementModifier.FINAL)
                || !event.getType().equals(ValueType.object(QUEUE + "$Event"))) mask |= 8;
        if (time == null || !time.hasModifier(ElementModifier.FINAL) || !time.getType().equals(ValueType.LONG)) mask |= 16;
        var a = expected.getMethod(NODE_INIT);
        var b = actual.getMethod(NODE_INIT);
        if (a == null || b == null || !same(a.getProgram(), b.getProgram())) mask |= 32;
        return mask;
    }

    private static boolean matchesNode(ClassReader expected, ClassReader actual) throws Exception {
        if (expected == null || actual == null || !actual.getParent().equals("java.lang.Object")
                || actual.getFields().size() != 3 || actual.getMethods().size() != 1) return false;
        var id = actual.getField("id");
        var event = actual.getField("event");
        var time = actual.getField("time");
        if (id == null || !id.hasModifier(ElementModifier.FINAL) || !id.getType().equals(ValueType.INTEGER)
                || event == null || !event.hasModifier(ElementModifier.FINAL)
                || !event.getType().equals(ValueType.object(QUEUE + "$Event"))
                || time == null || !time.hasModifier(ElementModifier.FINAL)
                || !time.getType().equals(ValueType.LONG)
                || expected.getMethod(NODE_INIT) == null || actual.getMethod(NODE_INIT) == null) return false;
        return same(expected.getMethod(NODE_INIT).getProgram(), actual.getMethod(NODE_INIT).getProgram());
    }

    static void transform(ClassHolder cls, ClassHolderTransformerContext context) {
        if (!cls.getName().equals(QUEUE)) return;
        requireAt(context != null && cls.getParent().equals("java.lang.Object") && cls.getFields().size() == 4, 1);
        var data = cls.getField("data");
        var size = cls.getField("size");
        var update = cls.getMethod(UPDATE);
        requireAt(data != null && data.hasModifier(ElementModifier.STATIC)
                && data.getType().equals(ValueType.arrayOf(ValueType.object(QUEUE + "$Node")))
                && size != null && size.hasModifier(ElementModifier.STATIC)
                && size.getType().equals(ValueType.INTEGER)
                && update != null && update.hasModifier(ElementModifier.STATIC)
                && update.getProgram() != null, 2);
        int site = 3, rawMask = -1, optimizedMask = -1;
        try {
            ClassLoader loader = EventQueueHeapMethods.class.getClassLoader();
            require(loader != null);
            site = 4;
            authenticate(loader, "org/teavm/runtime/EventQueue.class", 3962,
                    "326bcaaef5f35c6615e815d3b3f55e215968c49b94d7d57fed84d9c013d6ac12");
            site = 5;
            authenticate(loader, "org/teavm/runtime/EventQueue$Node.class", 674,
                    "5c07775c45fa2e281936b948057f6ab4265e409c1e6b4d1c43af966e749838d2");
            site = 6;
            ClassHolder raw = source(loader).get(QUEUE);
            ClassHolder optimized = new PreOptimizingClassHolderSource(source(loader)).get(QUEUE);
            // Only the two deterministic representations of the locked body
            // are admitted. Unknown transforms and a repeated repair refuse.
            site = 7;
            if (!(matches(raw, cls) || matches(optimized, cls))) {
                rawMask = queueMismatch(raw, cls);
                optimizedMask = queueMismatch(optimized, cls);
                throw new IllegalStateException();
            }
            site = 8;
            ClassReader node = context.getHierarchy().getClassSource().get(QUEUE + "$Node");
            ClassHolder rawNode = source(loader).get(QUEUE + "$Node");
            ClassHolder optimizedNode = new PreOptimizingClassHolderSource(source(loader)).get(QUEUE + "$Node");
            site = 9;
            if (!(matchesNode(rawNode, node) || matchesNode(optimizedNode, node))) {
                rawMask = nodeMismatch(rawNode, node);
                optimizedMask = nodeMismatch(optimizedNode, node);
                throw new IllegalStateException();
            }
        } catch (Exception failure) {
            // Do not include exception text, class names or application identifiers.
            throw new IllegalStateException("unexpected-maintained-event-queue-heap-site-" + site
                    + "-raw-" + rawMask + "-optimized-" + optimizedMask);
        }

        var donor = context.getHierarchy().getClassSource().get(DONOR);
        var donorNode = context.getHierarchy().getClassSource().get(DONOR + "$Node");
        try {
            ClassLoader loader = EventQueueHeapMethods.class.getClassLoader();
            trustedDonorResource(loader, DONOR);
            trustedDonorResource(loader, DONOR + "$Node");
            ClassHolder rawDonor = source(loader).get(DONOR);
            ClassHolder rawNode = source(loader).get(DONOR + "$Node");
            ClassHolder optimizedDonor = new PreOptimizingClassHolderSource(source(loader)).get(DONOR);
            ClassHolder optimizedNode = new PreOptimizingClassHolderSource(source(loader)).get(DONOR + "$Node");
            require(rawDonor != null && rawDonor.getFields().size() == 2
                    && rawDonor.getMethods().size() == 2 && rawDonor.getField("data") != null
                    && rawDonor.getField("data").hasModifier(ElementModifier.STATIC)
                    && rawDonor.getField("data").getType().equals(ValueType.arrayOf(ValueType.object(DONOR + "$Node")))
                    && rawDonor.getField("size") != null
                    && rawDonor.getField("size").hasModifier(ElementModifier.STATIC)
                    && rawDonor.getField("size").getType().equals(ValueType.INTEGER)
                    && rawDonor.getMethod(UPDATE) != null && rawDonor.getMethod(UPDATE).hasModifier(ElementModifier.STATIC)
                    && rawNode != null && rawNode.getFields().size() == 1 && rawNode.getMethods().size() == 1
                    && rawNode.getField("time") != null && rawNode.getField("time").hasModifier(ElementModifier.FINAL)
                    && rawNode.getField("time").getType().equals(ValueType.LONG));
            // The active hierarchy may not shadow or alter either compiler-owned
            // donor. Both metadata and all method bodies must match the trusted
            // class-loader's captured raw or deterministically preoptimized input.
            require((sameClass(rawDonor, donor) || sameClass(optimizedDonor, donor))
                    && (sameClass(rawNode, donorNode) || sameClass(optimizedNode, donorNode)));
        } catch (Exception failure) {
            throw new IllegalStateException("unexpected-maintained-event-queue-donor", failure);
        }
        var renamed = new ClassRefsRenamer(new ReferenceCache(), name -> {
            if (name.equals(DONOR)) return QUEUE;
            if (name.equals(DONOR + "$Node")) return QUEUE + "$Node";
            return name;
        }).rename(ModelUtils.copyClass(donor));
        var fixed = renamed.getMethod(UPDATE);
        require(fixed != null && fixed.hasModifier(ElementModifier.STATIC) && fixed.getProgram() != null);
        update.setProgram(ProgramUtils.copy(fixed.getProgram()));
    }
}
