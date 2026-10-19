package dev.latent.guest.client;

import dev.latent.generated.Bindings;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.ProtocolException;
import java.net.URL;
import java.util.Arrays;

/** Installed-JDK reference and actual SDK source; never a component/provider receipt. */
public final class ResponseMessages {
    private static void require(boolean condition) { if (!condition) throw new AssertionError(); }
    private static Connection fresh() throws Exception {
        Bindings.reset();
        return new Connection(new URL("http://fixture.test/message"));
    }
    public static void main(String[] args) throws Exception {
        int cases=0;
        var reference=new HttpURLConnection(new URL("http://must-not-contact.invalid/")) {
            @Override public int getResponseCode() { return 207; }
            @Override public void connect() { throw new AssertionError("reference made a network call"); }
            @Override public void disconnect() { }
            @Override public boolean usingProxy() { return false; }
        };
        require(reference.getResponseCode()==207 && reference.getResponseMessage()==null);
        var connection=fresh(); Bindings.status=207;
        require(connection.getResponseMessage()==reference.getResponseMessage());
        require(connection.getResponseMessage()==null && connection.getResponseCode()==207);
        require(Bindings.opens==1 && Bindings.finishes==1 && Bindings.reads==0
            && Bindings.trailers==0 && Bindings.bodiesDropped==0);
        connection.disconnect(); require(Bindings.bodiesDropped==1); cases++;

        connection=fresh(); Bindings.status=404;
        require(connection.getResponseMessage()==null && connection.getResponseCode()==404);
        try { connection.getInputStream(); throw new AssertionError(); }
        catch(FileNotFoundException expected) { }
        require(connection.getResponseMessage()==null);
        var body=connection.getErrorStream();
        require(body!=null && Arrays.equals(body.readAllBytes(),new byte[]{0,(byte)255,65,66,67}));
        body.close(); connection.disconnect();
        require(Bindings.opens==1 && Bindings.finishes==1 && Bindings.bodiesDropped==1); cases++;

        connection=fresh(); Bindings.finishError=12;
        IOException original=null;
        try { connection.getResponseMessage(); throw new AssertionError(); }
        catch(HttpFailure expected) { require(expected.externalCompletionUncertain()); original=expected; }
        try { connection.getResponseMessage(); throw new AssertionError(); }
        catch(IOException expected) { require(expected==original); }
        try { connection.getResponseCode(); throw new AssertionError(); }
        catch(IOException expected) { require(expected==original); }
        connection.disconnect();
        require(Bindings.opens==1 && Bindings.finishes==1 && Bindings.reads==0
            && Bindings.uploadsDropped==0 && Bindings.bodiesDropped==0); cases++;

        connection=fresh(); connection.setConnectTimeout(1);
        try { connection.getResponseMessage(); throw new AssertionError(); }
        catch(ProtocolException expected) { require(expected.getMessage().contains("connect/read timeout")); }
        require(Bindings.opens==0 && Bindings.finishes==0); connection.disconnect(); cases++;

        connection=fresh(); connection.setReadTimeout(1);
        try { connection.getResponseMessage(); throw new AssertionError(); }
        catch(ProtocolException expected) { require(expected.getMessage().contains("connect/read timeout")); }
        require(Bindings.opens==0 && Bindings.finishes==0); connection.disconnect(); cases++;

        connection=fresh(); connection.disconnect();
        try { connection.getResponseMessage(); throw new AssertionError(); }
        catch(IOException expected) { require(expected.getMessage().equals("http-connection-closed")); }
        require(Bindings.opens==0 && Bindings.finishes==0 && Bindings.reads==0); cases++;
        System.out.println("RESPONSE_MESSAGE_MODEL_CONTROLS="+cases+"; COMPONENT_QUALIFICATION=pending");
    }
}
