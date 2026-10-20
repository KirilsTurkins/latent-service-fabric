package dev.latent.generated;

import dev.latent.guest.Option;
import dev.latent.guest.Result;
import dev.latent.guest.Unsigned64;
import java.util.ArrayList;
import java.util.List;

/** Host-JDK model of typed results; never a transport or component implementation. */
public final class Bindings {
    public enum LatentHttpStreamingMethod { Get, Head, Post, Put, Delete, Options }
    public record LatentHttpStreamingHeader(String name, String value) {}
    public record LatentHttpStreamingRequest(LatentHttpStreamingMethod method, String url,
        List<LatentHttpStreamingHeader> headers, Option<Unsigned64> bodyLength,
        Option<String> bodyMediaType, Option<String> idempotencyKey, Option<Unsigned64> timeout) {}
    public record LatentHttpStreamingHttpError(int tag) {}
    public record LatentHttpPhaseTimingPhaseError(int tag,
        LatentHttpStreamingHttpError httpValue, boolean readTimeoutValue) {}
    public static final class LatentHttpStreamingUpload implements AutoCloseable {
        public void close() { uploadDrops++; }
    }
    public static final class LatentHttpStreamingBody implements AutoCloseable {
        public void close() { bodyDrops++; }
    }
    public static final class LatentHttpStreamingChunk implements AutoCloseable {
        public void close() { chunkDrops++; }
    }
    public record LatentHttpPhaseTimingResponse(int status, Option<byte[]> reasonPhrase,
        List<LatentHttpStreamingHeader> headers, Option<String> bodyMediaType,
        LatentHttpStreamingBody body) {}
    public static int opens, finishes, reads, uploadDrops, bodyDrops, chunkDrops;
    public static Option<Long> connectTimeout, finishTimeout;
    public static final List<Option<Long>> readTimeouts = new ArrayList<>();
    public static LatentHttpPhaseTimingPhaseError openError, finishError, readError;
    public static Option<byte[]> reason = Option.none();
    public static void reset() {
        opens = finishes = reads = uploadDrops = bodyDrops = chunkDrops = 0;
        openError = finishError = readError = null;
        connectTimeout = finishTimeout = null;
        reason = Option.none(); readTimeouts.clear();
    }
    public static final class LatentHttpPhaseTiming {
        public static Result<LatentHttpStreamingUpload, LatentHttpPhaseTimingPhaseError> open(
                LatentHttpStreamingRequest request, Option<Long> timeout) {
            opens++; connectTimeout = timeout;
            return openError == null ? Result.ok(new LatentHttpStreamingUpload()) : Result.err(openError);
        }
        public static Result<Object, LatentHttpStreamingHttpError> write(LatentHttpStreamingUpload upload, byte[] bytes) {
            return Result.ok(new Object());
        }
        public static Result<LatentHttpPhaseTimingResponse, LatentHttpPhaseTimingPhaseError> finish(
                LatentHttpStreamingUpload upload, Option<Long> timeout) {
            finishes++; finishTimeout = timeout;
            return finishError == null ? Result.ok(new LatentHttpPhaseTimingResponse(200, reason,
                List.of(), Option.none(), new LatentHttpStreamingBody())) : Result.err(finishError);
        }
        public static Result<Option<LatentHttpStreamingChunk>, LatentHttpPhaseTimingPhaseError> read(
                LatentHttpStreamingBody body, Long maximum, Option<Long> timeout) {
            reads++; readTimeouts.add(timeout);
            return readError == null ? Result.ok(Option.none()) : Result.err(readError);
        }
        public static Result<byte[], LatentHttpStreamingHttpError> chunkBytes(LatentHttpStreamingChunk chunk) {
            return Result.ok(new byte[]{1});
        }
        public static Result<List<LatentHttpStreamingHeader>, LatentHttpStreamingHttpError> trailers(LatentHttpStreamingBody body) {
            return Result.ok(List.of());
        }
    }
    public static final class LatentHttpStreaming {
        public static Result<LatentHttpStreamingUpload, LatentHttpStreamingHttpError> open(LatentHttpStreamingRequest request) {
            opens++; return Result.ok(new LatentHttpStreamingUpload());
        }
        public static Result<Object, LatentHttpStreamingHttpError> write(LatentHttpStreamingUpload upload, byte[] bytes) {
            return LatentHttpPhaseTiming.write(upload, bytes);
        }
        public static Result<LatentHttpPhaseTimingResponse, LatentHttpStreamingHttpError> finish(LatentHttpStreamingUpload upload) {
            finishes++; return Result.ok(new LatentHttpPhaseTimingResponse(200, reason,
                List.of(), Option.none(), new LatentHttpStreamingBody()));
        }
        public static Result<Option<LatentHttpStreamingChunk>, LatentHttpStreamingHttpError> read(LatentHttpStreamingBody body, Long maximum) {
            reads++; return Result.ok(Option.none());
        }
        public static Result<byte[], LatentHttpStreamingHttpError> chunkBytes(LatentHttpStreamingChunk chunk) {
            return LatentHttpPhaseTiming.chunkBytes(chunk);
        }
        public static Result<List<LatentHttpStreamingHeader>, LatentHttpStreamingHttpError> trailers(LatentHttpStreamingBody body) {
            return LatentHttpPhaseTiming.trailers(body);
        }
    }
}
