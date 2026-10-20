package dev.latent.guest.resources;

import java.lang.reflect.InvocationTargetException;
import java.util.Arrays;

/** Direct host control against the pinned TeaVM superclass, not guest proof. */
public final class ImmutableResourceStreamControl {
    private static final byte[] DATA = {0, (byte) 255, (byte) 128, 65};

    private static Object open(String owner, byte[] bytes) throws Exception {
        var constructor = Class.forName(owner).getDeclaredConstructor(byte[].class);
        constructor.setAccessible(true);
        return constructor.newInstance((Object) bytes);
    }

    private static Object call(Object stream, String method, Class<?>[] parameters, Object... arguments)
            throws Exception {
        var selected = stream.getClass().getMethod(method, parameters);
        selected.setAccessible(true);
        return selected.invoke(stream, arguments);
    }

    private static int read(Object stream) throws Exception {
        return (int) call(stream, "read", new Class<?>[]{});
    }

    private static byte[] all(Object stream) throws Exception {
        return (byte[]) call(stream, "readAllBytes", new Class<?>[]{});
    }

    private static byte[] some(Object stream, int length) throws Exception {
        return (byte[]) call(stream, "readNBytes", new Class<?>[]{int.class}, length);
    }

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    public static void main(String[] args) throws Exception {
        String owner = args[0];
        String selected = args[1];
        Object first = open(owner, DATA.clone());
        switch (selected) {
            case "all":
                require(read(first) == 0 && Arrays.equals(all(first), new byte[]{(byte) 255, (byte) 128, 65}),
                    "exact-remaining-bytes");
                require(read(first) == -1 && all(first).length == 0
                    && (int) call(first, "available", new Class<?>[]{}) == 0, "bulk-read-eof-position");
                break;
            case "bounded":
                require(Arrays.equals(some(first, 2), new byte[]{0, (byte) 255}) && read(first) == 128,
                    "bounded-read-following-position");
                require(Arrays.equals(some(first, 8), new byte[]{65}) && read(first) == -1,
                    "bounded-read-short-eof");
                break;
            case "zero":
                require(some(first, 0).length == 0 && read(first) == 0, "zero-read-position");
                break;
            case "negative":
                try {
                    some(first, -1);
                    throw new AssertionError("negative-length-accepted");
                } catch (InvocationTargetException expected) {
                    require(expected.getCause() instanceof IllegalArgumentException, "negative-length-type");
                }
                require(read(first) == 0, "invalid-read-preserves-position");
                break;
            case "maximum":
                require(read(first) == 0
                    && Arrays.equals(some(first, Integer.MAX_VALUE), new byte[]{(byte) 255, (byte) 128, 65})
                    && read(first) == -1, "maximum-length-no-overflow");
                break;
            case "mark-close":
                require(read(first) == 0, "first-byte");
                call(first, "mark", new Class<?>[]{int.class}, 0);
                require(Arrays.equals(some(first, 2), new byte[]{(byte) 255, (byte) 128}), "marked-bulk");
                call(first, "reset", new Class<?>[]{});
                require(read(first) == 255, "reset-position");
                call(first, "close", new Class<?>[]{});
                require(Arrays.equals(all(first), new byte[]{(byte) 128, 65}) && read(first) == -1,
                    "close-remains-noop");
                break;
            case "independent":
                Object second = open(owner, DATA.clone());
                byte[] copied = some(first, 1);
                copied[0] = 42;
                require(read(first) == 255 && read(second) == 0, "independent-stream-and-array-owners");
                break;
            case "empty":
                Object empty = open(owner, new byte[0]);
                require(all(empty).length == 0 && some(empty, Integer.MAX_VALUE).length == 0
                    && read(empty) == -1, "empty-eof");
                break;
            default:
                throw new AssertionError("unknown-control");
        }
        System.out.println("RESOURCE_STREAM_CONTROL PASS " + selected);
    }
}
