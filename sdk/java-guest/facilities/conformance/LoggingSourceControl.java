import dev.latent.generated.Bindings;
import dev.latent.guest.facilities.StandardLog;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

public final class LoggingSourceControl {
    private static int checks;
    private static void require(boolean value) { checks++; if (!value) throw new AssertionError("check-" + checks); }
    private static void rejected(byte[] bytes, int offset, int length, String code) throws Exception {
        int before = Bindings.calls;
        try { StandardLog.writeOut(bytes, offset, length); throw new AssertionError("accepted"); }
        catch (IOException expected) { require(expected.getMessage().equals(code)); }
        require(Bindings.calls == before);
    }
    public static void main(String[] args) throws Exception {
        for (String text : new String[]{"plain", "caf\u00e9", "\u041f\u0440\u0438\u0432\u0435\u0442", "\ud83c\udf0d", "quote\"\n\\"}) {
            byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
            StandardLog.writeOut(bytes, 0, bytes.length);
            require(Bindings.message.equals(text) && Bindings.level == Bindings.LatentLogLogLevel.Info);
            StandardLog.writeErr(bytes, 0, bytes.length);
            require(Bindings.message.equals(text) && Bindings.level == Bindings.LatentLogLogLevel.Error);
        }
        int before = Bindings.calls;
        StandardLog.writeOut(new byte[0], 0, 0); require(Bindings.calls == before);
        rejected(new byte[4097], 0, 4097, "bounded-log-write-too-large");
        for (byte[] bytes : new byte[][]{{(byte)0xc0,(byte)0x80}, {(byte)0x80}, {(byte)0xe0,(byte)0x80,(byte)0x80},
                {(byte)0xed,(byte)0xa0,(byte)0x80}, {(byte)0xf4,(byte)0x90,(byte)0x80,(byte)0x80}, {(byte)0xff}})
            rejected(bytes, 0, bytes.length, "bounded-log-invalid-utf8");
        rejected(new byte[]{(byte)0xc2}, 0, 1, "bounded-log-incomplete-utf8-write");
        try { StandardLog.writeOut(null, 0, 0); throw new AssertionError(); } catch (NullPointerException expected) { checks++; }
        for (int[] range : new int[][]{{-1,0},{0,-1},{2,0},{1,1},{0,Integer.MAX_VALUE}}) {
            try { StandardLog.writeOut(new byte[1], range[0], range[1]); throw new AssertionError(); }
            catch (IndexOutOfBoundsException expected) { checks++; }
        }
        String[] codes = {"bounded-log-budget-exhausted", "bounded-log-invalid-field", "bounded-log-unavailable"};
        for (int error = 0; error < 3; error++) {
            Bindings.error = error;
            try { StandardLog.writeOut(new byte[]{65}, 0, 1); throw new AssertionError(); }
            catch (IOException expected) { require(expected.getMessage().equals(codes[error])); }
        }
        Bindings.error = -1; Bindings.accepted = false;
        try { StandardLog.writeOut(new byte[]{65}, 0, 1); throw new AssertionError(); }
        catch (IOException expected) { require(expected.getMessage().equals("bounded-log-record-dropped")); }
        var stream = new java.io.PrintStream(new java.io.OutputStream() {
            public void write(int value) throws IOException { StandardLog.writeOut(new byte[]{(byte)value}, 0, 1); }
            public void write(byte[] bytes, int offset, int length) throws IOException { StandardLog.writeOut(bytes, offset, length); }
        }, false, StandardCharsets.UTF_8);
        stream.print("fault"); require(stream.checkError());
        before = Bindings.calls; stream.flush(); require(Bindings.calls == before);
        System.out.println("LOGGING_SOURCE_CONTROL PASS checks=" + checks);
    }
}
