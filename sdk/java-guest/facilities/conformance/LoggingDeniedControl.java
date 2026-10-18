import dev.latent.guest.facilities.StandardLog;

public final class LoggingDeniedControl {
    public static void main(String[] args) throws Exception {
        StandardLog.writeOut(new byte[0], 0, 0);
        try { StandardLog.writeOut(new byte[]{65}, 0, 1); throw new AssertionError("silent-console-success"); }
        catch (java.io.IOException expected) {
            if (!expected.getMessage().equals("bounded-log-capability-not-declared")) throw new AssertionError(expected);
        }
        System.out.println("LOGGING_DENIED_CONTROL PASS explicit-failure;empty-noop;no-bindings");
    }
}
