package dev.latent.guest.client.compiler;

import org.teavm.model.ClassHolder;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.text.ListingBuilder;
import org.teavm.parsing.ClasspathClassHolderSource;

/** Actual pinned compiler class model; this is not component execution. */
public final class HttpModel {
    private static void require(boolean value, String code) {
        if (!value) throw new AssertionError(code);
    }
    private static void bridge(ClassHolder cls, String name, String helper, ValueType... signature) {
        var method = cls.getMethod(new MethodDescriptor(name, signature));
        require(method != null && method.getProgram() != null, "missing-concrete-standard-member:" + name);
        int calls = 0;
        for (var block : method.getProgram().getBasicBlocks()) {
            for (var instruction : block) {
                if (instruction instanceof InvokeInstruction invoke) {
                    require(invoke.getMethod().getClassName().equals("dev.latent.guest.client.StandardMembers")
                        && invoke.getMethod().getName().equals(helper), "wrong-standard-member-owner:" + name);
                    require(invoke.getArguments().size() == signature.length, "wrong-instance-arguments:" + name);
                    calls++;
                }
            }
        }
        require(calls == 1, "duplicate-standard-operation:" + name);
    }
    public static void main(String[] arguments) {
        var source = new ClasspathClassHolderSource(new ReferenceCache());
        var plugin = new HttpPlugin();
        var url = source.get("java.net.URL");
        var connection = source.get("java.net.URLConnection");
        var http = source.get("java.net.HttpURLConnection");
        require(url != null && connection != null && http != null, "missing-maintained-standard-classes");
        require(http.getMethod(new MethodDescriptor("setFixedLengthStreamingMode", ValueType.LONG, ValueType.VOID)) == null,
            "unexpected-upstream-long-member");
        plugin.transformClass(url, null);
        plugin.transformClass(connection, null);
        plugin.transformClass(http, null);
        bridge(connection, "getContentLengthLong", "contentLength", ValueType.LONG);
        bridge(connection, "getHeaderFieldLong", "headerLong", ValueType.object("java.lang.String"), ValueType.LONG, ValueType.LONG);
        bridge(http, "setFixedLengthStreamingMode", "fixedLength", ValueType.LONG, ValueType.VOID);
        require(http.getMethod(new MethodDescriptor("usingProxy", ValueType.BOOLEAN)).getModifiers()
            .contains(ElementModifier.ABSTRACT), "missing-standard-proxy-declaration");
        String listing = new ListingBuilder().buildListing(url.getMethod(
            new MethodDescriptor("setupStreamHandler", ValueType.VOID)).getProgram(), "");
        require(listing.contains("dev.latent.guest.client.StreamHandler")
            && !listing.contains("XHRStreamHandler"), "default-handler-was-not-bound");
        // Neither dependency coordinates nor a class outside the SDK is selected.
        var external = source.get("dev.latent.guest.client.compiler.OutsideHttpCalls");
        require(external != null, "missing-outside-bytecode-control");
        String before = new ListingBuilder().buildListing(external.getMethod(
            new MethodDescriptor("read", ValueType.object("java.net.HttpURLConnection"), ValueType.LONG)).getProgram(), "");
        plugin.transformClass(external, null);
        String after = new ListingBuilder().buildListing(external.getMethod(
            new MethodDescriptor("read", ValueType.object("java.net.HttpURLConnection"), ValueType.LONG)).getProgram(), "");
        require(before.equals(after) && before.contains("getContentLengthLong"), "dependency-bytecode-was-rewritten");
        try { plugin.transformClass(new ClassHolder("java.net.URL"), null); throw new AssertionError("shape-drift-accepted"); }
        catch (IllegalStateException expected) { }
        System.out.println("PINNED_HTTP_CLASS_MODEL=passed; COMPONENT_QUALIFICATION=pending");
    }
}
