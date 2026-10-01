package dev.latent.app;

import java.util.Arrays;

/** JVM format vectors. These do not establish component or State execution. */
public final class EncodingVectors {
    private static int checked;

    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("aggregate encoding vector failed");
        checked++;
    }

    public static void main(String[] args) {
        for (long value : new long[] {0, 1, 0x0102030405060708L, Long.MAX_VALUE,
                Long.MIN_VALUE, -2, -1}) {
            byte[] v1 = AggregateCodec.encode(value, false);
            byte[] v2 = AggregateCodec.encode(value, true);
            require(v1.length == 8 && v2.length == 12);
            require(v2[0] == 0x41 && v2[1] == 0x47 && v2[2] == 2 && v2[3] == 0);
            require(Arrays.equals(v1, Arrays.copyOfRange(v2, 4, 12)));
            require(AggregateCodec.decode(AggregateCodec.V1_MEDIA, v1, false) == value);
            require(AggregateCodec.decode(AggregateCodec.V1_MEDIA, v1, true) == value);
            require(AggregateCodec.decode(AggregateCodec.V2_MEDIA, v2, true) == value);
            require(AggregateCodec.decode(AggregateCodec.V2_MEDIA, v2, false) == null);
            require(AggregateCodec.decode(AggregateCodec.V2_MEDIA, v1, true) == null);
            require(AggregateCodec.decode(AggregateCodec.V1_MEDIA, v2, true) == null);
        }
        require(Arrays.equals(AggregateCodec.encode(0x0102030405060708L, false),
                new byte[] {8, 7, 6, 5, 4, 3, 2, 1}));
        for (int index = 0; index < 4; index++) {
            byte[] bad = AggregateCodec.encode(-1, true);
            bad[index] ^= 1;
            require(AggregateCodec.decode(AggregateCodec.V2_MEDIA, bad, true) == null);
        }
        for (int length : new int[] {0, 1, 7, 9, 11, 13, 1024}) {
            require(AggregateCodec.decode(AggregateCodec.V1_MEDIA, new byte[length], true) == null);
            require(AggregateCodec.decode(AggregateCodec.V2_MEDIA, new byte[length], true) == null);
        }
        for (String media : new String[] {null, "", "application/vnd.lsf.aggregate-v1; charset=utf-8",
                "application/vnd.lsf.aggregate-v2\u0000"}) {
            require(AggregateCodec.decode(media, new byte[8], true) == null);
            require(AggregateCodec.decode(media, AggregateCodec.encode(1, true), true) == null);
        }
        require(AggregateCodec.decode(AggregateCodec.V1_MEDIA, null, false) == null);
        require(AggregateCodec.mediaType(false).equals(AggregateCodec.V1_MEDIA));
        require(AggregateCodec.mediaType(true).equals(AggregateCodec.V2_MEDIA));
        System.out.println("PASS Java aggregate encoding vectors: " + checked);
    }
}
