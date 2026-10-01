package dev.latent.guest.runtime.compiler;

import java.util.Set;
import org.teavm.extension.spi.substitution.SubstitutionPolicy;
import org.teavm.extension.spi.substitution.SubstitutionSink;

/** Exact missing standard members; application API references stay unchanged. */
public final class RuntimeSubstitution implements SubstitutionPolicy {
    static final String STANDARD = "java.util.concurrent.";
    static final String SDK = "dev.latent.guest.runtime.concurrent.";
    static final Set<String> API = Set.of("AbstractExecutorService", "ExecutorService", "Executors",
        "ThreadFactory", "Future", "Future$State", "FutureTask", "RunnableFuture",
        "RejectedExecutionException", "TimeoutException", "TimeUnit");

    @Override public void contribute(SubstitutionSink sink) {
        sink.selectClasses(name -> name.equals("java.lang.IllegalThreadStateException"))
            .replacePackage("java.lang", "dev.latent.guest.runtime.lang")
            .dontFallbackWhenNoSubstitution();
        sink.selectClasses(name -> name.startsWith(STANDARD) && API.contains(name.substring(STANDARD.length())))
            .replacePackage("java.util.concurrent", "dev.latent.guest.runtime.concurrent")
            .dontFallbackWhenNoSubstitution();
    }
}
