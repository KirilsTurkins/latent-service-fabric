package org.teavm.dependency;

import java.lang.reflect.Proxy;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.teavm.cache.IncrementalDependencyRegistration;
import org.teavm.model.ClassHierarchy;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassReaderSource;
import org.teavm.model.InvokeDynamicInstruction;
import org.teavm.model.MethodReference;
import org.teavm.model.emit.ValueEmitter;

/** Private collector for the actual locked emitter. Never part of a component. */
public final class LambdaEmitterControlContext extends DependencyAgent {
    public final Map<String, ClassHolder> generated = new LinkedHashMap<>();
    private final ClassReaderSource source;
    private final ClassHierarchy hierarchy;
    private final IncrementalDependencyRegistration cache;

    public LambdaEmitterControlContext(ClassReaderSource original) {
        super(null);
        source = name -> generated.containsKey(name) ? generated.get(name) : original.get(name);
        hierarchy = new ClassHierarchy(source);
        cache = (IncrementalDependencyRegistration)Proxy.newProxyInstance(
            IncrementalDependencyRegistration.class.getClassLoader(),
            new Class<?>[]{IncrementalDependencyRegistration.class}, (proxy, method, arguments) -> {
                if (!method.getName().equals("addDependencies") || !generated.containsKey(arguments[0]))
                    throw new AssertionError("unexpected-emitter-cache-operation");
                return null;
            });
    }
    @Override public ClassReaderSource getClassSource() { return source; }
    @Override public ClassHierarchy getClassHierarchy() { return hierarchy; }
    @Override public IncrementalDependencyRegistration getIncrementalCache() { return cache; }
    @Override public void submitClass(ClassHolder cls) {
        if (generated.putIfAbsent(cls.getName(), cls) != null)
            throw new AssertionError("duplicate-emitted-callback-identity");
    }
    public DynamicCallSite site(MethodReference caller, InvokeDynamicInstruction instruction,
                                List<ValueEmitter> captures) {
        return new DynamicCallSite(caller, instruction.getMethod(), null, captures,
            instruction.getBootstrapMethod(), instruction.getBootstrapArguments(), this, instruction.getLocation());
    }
}
