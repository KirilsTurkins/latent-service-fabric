package org.teavm.backend.c.generate;

import java.lang.reflect.Proxy;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.teavm.ast.RegularMethodNode;
import org.teavm.backend.lowlevel.analyze.LowLevelInliningFilterFactory;
import org.teavm.backend.lowlevel.generate.NameProvider;
import org.teavm.model.AnnotationHolder;
import org.teavm.model.ClassHolder;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.ValueType;
import org.teavm.model.lowlevel.Characteristics;

/** Real original/patched compiler policy and C-header emission, not guest execution. */
public final class MethodGranularityControl {
    private static final RuntimeException HEADER_COMPLETE = new RuntimeException("method-header-complete");
    private static final String PREFIX = "__attribute__((noinline)) ";

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static MethodReference method(Map<String, ClassHolder> classes, String name, boolean unmanaged) {
        var cls = new ClassHolder(name);
        if (unmanaged) cls.getAnnotations().add(new AnnotationHolder("org.teavm.interop.Unmanaged"));
        var reference = new MethodReference(name, "call", ValueType.VOID);
        cls.addMethod(new MethodHolder(reference.getDescriptor()));
        classes.put(name, cls);
        return reference;
    }

    private static void filter(boolean corrected) {
        var classes = new HashMap<String, ClassHolder>();
        var methods = List.of(method(classes, "control.First", false),
                method(classes, "different.Second", false), method(classes, "control.Raw", true));
        var characteristics = new Characteristics(classes::get);
        require(characteristics.isManaged(methods.get(0)) && characteristics.isManaged(methods.get(1))
                && !characteristics.isManaged(methods.get(2)), "method-control-real-characteristics");
        var factory = new LowLevelInliningFilterFactory(characteristics);
        int checked = 0;
        for (int caller = 0; caller < methods.size(); caller++) {
            var selected = factory.createFilter(methods.get(caller));
            for (int callee = 0; callee < methods.size(); callee++) {
                boolean expected = !corrected && caller < 2 && callee < 2;
                require(selected.apply(methods.get(callee)) == expected, "method-control-inlining-boundary");
                checked++;
            }
        }
        require(checked == 9, "method-control-filter-count");
    }

    private static void headers(boolean corrected) {
        NameProvider names = (NameProvider) Proxy.newProxyInstance(NameProvider.class.getClassLoader(),
                new Class<?>[] {NameProvider.class}, (proxy, method, args) -> {
                    if (method.getName().equals("forMethod") && args.length == 1
                            && args[0] instanceof MethodReference) return "lsf_control_symbol";
                    throw new AssertionError("method-control-unexpected-name-query");
                });
        var context = new GenerationContext(null, null, null, null, names, null, null, null, null,
                null, List.of(), List.of(), method -> false, null, null, false, false, false, false,
                Set.of(), Set.of(), null);
        int checked = 0;
        for (String owner : List.of("control.First", "different.Second")) {
            var reference = new MethodReference(owner, "value", ValueType.INTEGER, ValueType.INTEGER);
            for (boolean isStatic : new boolean[] {false, true}) {
                var originalSignature = new HeaderWriter(false);
                CodeGenerator.generateMethodSignature(originalSignature, names, reference, isStatic, true);
                var actual = new HeaderWriter(true);
                var classContext = new ClassGenerationContext(context, null, new HeaderWriter(false), null, owner);
                var generator = new CodeGenerator(classContext, actual, null);
                var node = new RegularMethodNode(reference);
                if (isStatic) node.getModifiers().add(ElementModifier.STATIC);
                boolean stopped = false;
                try {
                    generator.generateMethod(node);
                } catch (RuntimeException failure) {
                    if (failure != HEADER_COMPLETE) throw failure;
                    stopped = true;
                }
                require(stopped && actual.complete, "method-control-header-not-reached");
                require(actual.text.toString().equals((corrected ? PREFIX : "") + originalSignature.text),
                        "method-control-actual-header");
                require(!actual.text.toString().contains("optnone"), "method-control-unexpected-optnone");
                checked++;
            }
        }
        require(checked == 4, "method-control-header-count");
    }

    private static final class HeaderWriter extends CodeWriter {
        final StringBuilder text = new StringBuilder();
        final boolean stop;
        boolean complete;

        HeaderWriter(boolean stop) { this.stop = stop; }
        @Override public CodeWriter fragment() { return new HeaderWriter(false); }
        @Override protected void newLine() { text.append('\n'); }
        @Override protected void append(String value) {
            if (stop && value.equals(" {")) {
                complete = true;
                throw HEADER_COMPLETE;
            }
            text.append(value);
        }
        @Override protected void indentBy(int amount) { }
        @Override public void flush() { }
        @Override public void source(String fileName, int lineNumber) { }
        @Override public void nosource() { }
    }

    public static void main(String[] args) {
        if (args.length != 1 || !(args[0].equals("original") || args[0].equals("corrected")))
            throw new IllegalArgumentException("method-control-mode");
        boolean corrected = args[0].equals("corrected");
        filter(corrected);
        headers(corrected);
        System.out.println("{\"schemaVersion\":\"latent.java.method-granularity-control.v1\",\"mode\":\""
                + args[0] + "\",\"passed\":true,\"filters\":9,\"headers\":4}");
    }
}
