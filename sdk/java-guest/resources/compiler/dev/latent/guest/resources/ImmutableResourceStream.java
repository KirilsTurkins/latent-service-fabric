package dev.latent.guest.resources;

/** Resource-only correction for the locked TeaVM 0.15.0 bulk-read methods. */
final class ImmutableResourceStream extends java.io.ByteArrayInputStream {
    ImmutableResourceStream(byte[] bytes) {
        super(bytes);
    }

    @Override public synchronized byte[] readAllBytes() {
        byte[] result = java.util.Arrays.copyOfRange(buf, pos, count);
        pos = count;
        return result;
    }

    @Override public byte[] readNBytes(int length) {
        if (length < 0) throw new IllegalArgumentException("negative resource read length");
        int end = pos + Math.min(length, count - pos);
        byte[] result = java.util.Arrays.copyOfRange(buf, pos, end);
        pos = end;
        return result;
    }
}
