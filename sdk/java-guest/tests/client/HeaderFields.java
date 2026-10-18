package dev.latent.guest.client;

import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentHttpStreamingHeader;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;

/** Actual SDK metadata and ownership controls against a host model, never a provider receipt. */
public final class HeaderFields {
    private static void require(boolean condition) { if (!condition) throw new AssertionError(); }
    private static Connection response(List<LatentHttpStreamingHeader> headers) throws Exception {
        Bindings.reset();
        Bindings.responseHeaders=headers;
        return new Connection(new URL("http://fixture.test/"));
    }
    private static void retire(Connection connection) {
        connection.disconnect(); connection.disconnect();
        require(Bindings.opens==1 && Bindings.finishes==1 && Bindings.bodiesDropped==1
            && Bindings.uploadsDropped==0 && Bindings.reads==0 && Bindings.trailers==0);
    }
    public static void main(String[] args) throws Exception {
        int cases=0;
        var connection=response(List.of(new LatentHttpStreamingHeader("X-Many","a"),
            new LatentHttpStreamingHeader("x-many","b")));
        require(connection.getHeaderField("X-MANY").equals("b"));
        require(connection.getHeaderFields().get("X-Many").equals(List.of("a","b")));
        require(!connection.getHeaderFields().containsKey("x-many"));
        retire(connection); cases++;

        connection=response(List.of(new LatentHttpStreamingHeader("X-Many","a"),
            new LatentHttpStreamingHeader("Other","value"), new LatentHttpStreamingHeader("x-many","b"),
            new LatentHttpStreamingHeader("X-Many","c")));
        var fields=connection.getHeaderFields();
        require(fields.get("X-Many").equals(List.of("a","b","c")));
        require(new ArrayList<>(fields.keySet()).equals(List.of("X-Many","Other","Content-Type")));
        require(connection.getHeaderField("x-many").equals("c") && connection.getHeaderField("absent")==null);
        try { fields.put("injected",List.of("value")); throw new AssertionError(); }
        catch(UnsupportedOperationException expected) { }
        try { fields.get("X-Many").add("injected"); throw new AssertionError(); }
        catch(UnsupportedOperationException expected) { }
        require(connection.getHeaderField("X-MANY").equals("c"));
        retire(connection); cases++;

        connection=response(List.of(new LatentHttpStreamingHeader("content-type","text/plain"),
            new LatentHttpStreamingHeader("Content-Type","application/json"),
            new LatentHttpStreamingHeader("X-Count","7"), new LatentHttpStreamingHeader("x-count","9"),
            new LatentHttpStreamingHeader("X-Count","11")));
        require(connection.getHeaderField("CONTENT-TYPE").equals("application/json"));
        require(connection.getHeaderFields().get("content-type").equals(List.of("text/plain","application/json")));
        require(!connection.getHeaderFields().containsKey("Content-Type"));
        require(StandardMembers.headerLong(connection,"X-COUNT",-1)==11);
        retire(connection); cases++;

        var original=new ArrayList<>(List.of(new LatentHttpStreamingHeader("X-Many","a"),
            new LatentHttpStreamingHeader("x-many","b")));
        connection=response(original);
        fields=connection.getHeaderFields();
        original.clear(); original.add(new LatentHttpStreamingHeader("X-Many","changed"));
        Bindings.responseHeaders=List.of(new LatentHttpStreamingHeader("X-Many","replacement"));
        require(fields.get("X-Many").equals(List.of("a","b")));
        require(connection.getHeaderField("x-many").equals("b") && connection.getResponseCode()==200);
        retire(connection); cases++;
        System.out.println("HEADER_MODEL_CONTROLS="+cases+"; COMPONENT_QUALIFICATION=pending");
    }
}
