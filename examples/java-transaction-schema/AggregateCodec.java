package dev.latent.app;

/** The synthetic application's stored bytes; version/view tokens stay opaque. */
public final class AggregateCodec {
    public static final String V1_MEDIA = "application/vnd.lsf.aggregate-v1";
    public static final String V2_MEDIA = "application/vnd.lsf.aggregate-v2";

    private AggregateCodec() {}

    public static String mediaType(boolean writeV2) {
        return writeV2 ? V2_MEDIA : V1_MEDIA;
    }

    public static Long decode(String mediaType, byte[] bytes, boolean readV2) {
        if (bytes == null) return null;
        int offset;
        if (V1_MEDIA.equals(mediaType) && bytes.length == 8) {
            offset = 0;
        } else if (readV2 && V2_MEDIA.equals(mediaType) && bytes.length == 12
                && bytes[0] == 0x41 && bytes[1] == 0x47 && bytes[2] == 2 && bytes[3] == 0) {
            offset = 4;
        } else {
            return null;
        }
        long value = 0;
        for (int i = 0; i < 8; i++) value |= (bytes[offset + i] & 255L) << (8 * i);
        return value;
    }

    public static byte[] encode(long value, boolean writeV2) {
        int offset = writeV2 ? 4 : 0;
        byte[] bytes = new byte[offset + 8];
        if (writeV2) {
            bytes[0] = 0x41;
            bytes[1] = 0x47;
            bytes[2] = 2;
        }
        for (int i = 0; i < 8; i++) bytes[offset + i] = (byte) (value >>> (8 * i));
        return bytes;
    }
}
