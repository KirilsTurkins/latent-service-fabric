import dev.latent.generated.Bindings;
import static dev.latent.generated.Bindings.*;
import dev.latent.guest.Option;
import dev.latent.guest.client.Connection;
import dev.latent.guest.client.HttpFailure;
import java.io.IOException;
import java.net.ProtocolException;
import java.net.SocketTimeoutException;
import java.net.URL;

/** Actual Java adapter exceptions against a model port, never native qualification. */
public final class PhaseReference {
    private static int checks;
    private static void check(boolean value) {
        if (!value) throw new AssertionError("phase-reference-control");
        checks++;
    }
    private static Connection connection() throws Exception {
        return new Connection(new URL("http://fixture.invalid/"));
    }
    private interface Operation { void call() throws IOException; }
    private static IOException failure(Operation operation) throws Exception {
        try { operation.call(); throw new AssertionError("expected-closed-error"); }
        catch (IOException error) { return error; }
    }
    public static void main(String[] arguments) throws Exception {
        reset();
        if (arguments[0].equals("legacy")) {
            var old = connection(); old.setConnectTimeout(1);
            check(failure(old::connect) instanceof ProtocolException && opens == 0);
            var normal = connection(); check(normal.getResponseCode() == 200);
            reason = Option.some(new byte[]{'O', 'K'});
            check(normal.getResponseMessage() == null);
            normal.disconnect(); check(bodyDrops == 1);
            System.out.println("legacy-reference:" + checks); return;
        }
        var connect = connection(); connect.setConnectTimeout(37);
        openError = new LatentHttpPhaseTimingPhaseError(1, null, false);
        var first = failure(connect::connect);
        check(first instanceof SocketTimeoutException && connectTimeout.value() == 37L && opens == 1);
        check(failure(connect::connect) == first && opens == 1);
        for (int code : new int[]{5, 6}) {
            reset(); var selected = connection();
            openError = new LatentHttpPhaseTimingPhaseError(0, new LatentHttpStreamingHttpError(code), false);
            var error = failure(selected::connect);
            check(error instanceof HttpFailure && !(error instanceof SocketTimeoutException));
            check(((HttpFailure) error).code().equals(code == 5 ? "deadline-exceeded" : "cancelled"));
        }
        reset(); var headers = connection(); headers.setReadTimeout(73);
        finishError = new LatentHttpPhaseTimingPhaseError(2, null, true);
        var headerError = failure(headers::getResponseCode);
        check(headerError instanceof SocketTimeoutException && finishTimeout.value() == 73L);
        check(headerError.getCause() instanceof HttpFailure && ((HttpFailure) headerError.getCause()).externalCompletionUncertain());
        check(failure(headers::getResponseCode) == headerError && opens == 1 && finishes == 1 && uploadDrops == 0);
        for (int mode = 0; mode < 3; mode++) {
            reset();
            reason = mode == 0 ? Option.none() : Option.some(mode == 1 ? new byte[0] : new byte[]{(byte) 0xe9});
            var selected = connection();
            check(selected.getResponseCode() == 200 && !connectTimeout.isSome() && !finishTimeout.isSome());
            var message = selected.getResponseMessage();
            check(mode == 0 ? message == null : message.equals(mode == 1 ? "" : "\u00e9"));
            selected.disconnect(); selected.disconnect(); check(bodyDrops == 1);
        }
        reset(); var body = connection(); var input = body.getInputStream(); body.setReadTimeout(19);
        readError = new LatentHttpPhaseTimingPhaseError(2, null, false);
        var readFailure = failure(input::read);
        check(readFailure instanceof SocketTimeoutException && readFailure.getCause() == null);
        check(readTimeouts.get(0).value() == 19L && bodyDrops == 1);
        check(failure(input::read) == readFailure && reads == 1 && finishes == 1 && opens == 1);
        body.disconnect(); check(bodyDrops == 1);
        reset(); var disabled = connection();
        check(disabled.getInputStream().read() == -1 && !readTimeouts.get(0).isSome());
        disabled.disconnect(); check(bodyDrops == 1);
        reset(); reason = Option.some(new byte[513]); var oversized = connection();
        check(failure(oversized::getResponseMessage) instanceof HttpFailure && bodyDrops == 1);
        oversized.disconnect(); check(bodyDrops == 1);
        reset(); openError = new LatentHttpPhaseTimingPhaseError(3, null, false); var unsupported = connection();
        check(failure(unsupported::connect) instanceof ProtocolException && opens == 1);
        System.out.println("phase-reference:" + checks);
    }
}
