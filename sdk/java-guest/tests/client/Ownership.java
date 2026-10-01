package dev.latent.guest.client;

import dev.latent.generated.Bindings;
import java.io.IOException;
import java.net.HttpRetryException;
import java.net.URL;
import java.util.Arrays;

/** Exercises actual SDK Java state/ownership code against a native model boundary. */
public final class Ownership {
    private static void require(boolean condition) { if (!condition) throw new AssertionError(); }
    private static Connection fresh() throws Exception {
        Bindings.reset();
        return new Connection(new URL("http://fixture.test/data?q=raw%2F#fragment"));
    }
    public static void main(String[] args) throws Exception {
        int cases=0;
        var connection=fresh();
        require(connection.getResponseCode()==200);
        require(Bindings.requested.url().equals("http://fixture.test/data?q=raw%2F"));
        require(connection.getHeaderField("x-many").equals("b"));
        require(connection.getHeaderFields().get("X-Many").equals(java.util.List.of("a","b")));
        var body=connection.getInputStream();
        byte[] bytes=new byte[5];
        require(body.read(bytes,0,2)==2 && body.read(bytes,2,3)==3);
        require(Arrays.equals(bytes,new byte[]{0,(byte)255,65,66,67}));
        require(body.read()==-1 && body.read()==-1 && Bindings.trailers==1 && Bindings.chunksDropped==1);
        body.close(); body.close(); connection.disconnect();
        require(Bindings.bodiesDropped==1 && Bindings.opens==1 && Bindings.finishes==1); cases++;

        connection=fresh(); Bindings.status=500;
        require(connection.getErrorStream()==null && connection.getResponseCode()==500);
        try { connection.getInputStream(); throw new AssertionError(); } catch(IOException expected) {}
        require(Arrays.equals(connection.getErrorStream().readAllBytes(),new byte[]{0,(byte)255,65,66,67}));
        connection.disconnect(); require(Bindings.bodiesDropped==1); cases++;

        connection=fresh(); Bindings.finishError=12;
        IOException original=null;
        try { connection.getResponseCode(); throw new AssertionError(); }
        catch(HttpFailure expected) { require(expected.externalCompletionUncertain()); original=expected; }
        try { connection.getResponseCode(); throw new AssertionError(); }
        catch(IOException expected) { require(expected==original); }
        connection.disconnect(); require(Bindings.opens==1 && Bindings.finishes==1 && Bindings.uploadsDropped==0); cases++;

        connection=fresh(); Bindings.readError=14;
        body=connection.getInputStream();
        try { body.read(); throw new AssertionError(); }
        catch(HttpFailure expected) { require(expected.code().equals("unexpected-eof")); }
        require(Bindings.bodiesDropped==1 && Bindings.trailers==0); connection.disconnect(); cases++;

        connection=fresh(); connection.setDoOutput(true); connection.setFixedLengthStreamingMode(2L);
        var output=connection.getOutputStream(); output.write(1);
        try { output.close(); throw new AssertionError(); } catch(IOException expected) {}
        require(Bindings.uploadsDropped==1 && Bindings.finishes==0 && Bindings.requested.method()==Bindings.LatentHttpStreamingMethod.Post);
        try { connection.getResponseCode(); throw new AssertionError(); } catch(IOException expected) {}
        require(Bindings.opens==1); connection.disconnect(); cases++;

        connection=fresh(); connection.setDoOutput(true); connection.setFixedLengthStreamingMode(1);
        output=connection.getOutputStream();
        try { output.write(new byte[]{1,2}); throw new AssertionError(); } catch(HttpFailure expected) {}
        require(Bindings.writes==0 && Bindings.uploadsDropped==1); connection.disconnect(); cases++;

        connection=fresh(); connection.setConnectTimeout(1);
        try { connection.getResponseCode(); throw new AssertionError(); } catch(IOException expected) {}
        require(Bindings.opens==0); connection.disconnect(); cases++;

        connection=fresh(); Bindings.status=302;
        try { connection.getResponseCode(); throw new AssertionError(); } catch(HttpRetryException expected) {}
        require(Bindings.opens==1 && Bindings.finishes==1 && Bindings.bodiesDropped==1); connection.disconnect(); cases++;

        connection=fresh(); connection.setInstanceFollowRedirects(false); Bindings.status=302;
        require(connection.getResponseCode()==302 && Bindings.opens==1);
        connection.disconnect(); cases++;

        Bindings.reset();
        try { new StreamHandler().openConnection(new URL("https://fixture.test/")); throw new AssertionError(); }
        catch(IOException expected) { require(expected.getMessage().equals("java-https-standard-type-not-qualified")); }
        require(Bindings.opens==0); cases++;
        System.out.println("NATIVE_MODEL_CONTROLS="+cases+"; COMPONENT_QUALIFICATION=pending");
    }
}
