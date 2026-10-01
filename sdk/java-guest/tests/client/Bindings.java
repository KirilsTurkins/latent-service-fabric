package dev.latent.generated;

import dev.latent.guest.Option;
import dev.latent.guest.Result;
import dev.latent.guest.Unit;
import dev.latent.guest.Unsigned64;
import java.util.List;

/** Native ownership model only. This fixture is never a component/provider receipt. */
public final class Bindings {
    public enum LatentHttpStreamingMethod { Get, Head, Post, Put, Patch, Delete, Options }
    public record LatentHttpStreamingHeader(String name, String value) {}
    public record LatentHttpStreamingRequest(LatentHttpStreamingMethod method, String url,
        List<LatentHttpStreamingHeader> headers, Option<Unsigned64> bodyLength,
        Option<String> bodyMediaType, Option<String> idempotencyKey, Option<Unsigned64> timeoutMillis) {}
    public record LatentHttpStreamingHttpError(int tag) {}
    public record LatentHttpStreamingResponse(int status, List<LatentHttpStreamingHeader> headers,
        Option<String> bodyMediaType, LatentHttpStreamingBody body) {}
    public static final class LatentHttpStreamingUpload implements AutoCloseable {
        private boolean retired;
        @Override public void close() { if (!retired) { retired = true; uploadsDropped++; } }
    }
    public static final class LatentHttpStreamingBody implements AutoCloseable {
        private boolean retired;
        @Override public void close() { if (!retired) { retired = true; bodiesDropped++; } }
    }
    public static final class LatentHttpStreamingChunk implements AutoCloseable {
        private boolean retired;
        @Override public void close() { if (!retired) { retired = true; chunksDropped++; } }
    }
    public static int opens, finishes, writes, reads, trailers, uploadsDropped, bodiesDropped, chunksDropped;
    public static int status, finishError, readError;
    public static LatentHttpStreamingRequest requested;
    public static void reset() {
        opens=finishes=writes=reads=trailers=uploadsDropped=bodiesDropped=chunksDropped=0;
        finishError=readError=-1; status=200; requested=null;
    }
    public static final class LatentHttpStreaming {
        public static Result<LatentHttpStreamingUpload, LatentHttpStreamingHttpError> open(LatentHttpStreamingRequest request) {
            opens++; requested=request; return Result.ok(new LatentHttpStreamingUpload());
        }
        public static Result<Unit, LatentHttpStreamingHttpError> write(LatentHttpStreamingUpload upload, byte[] bytes) {
            if (upload.retired) throw new AssertionError("write after consumption");
            writes++; return Result.ok(Unit.VALUE);
        }
        public static Result<LatentHttpStreamingResponse, LatentHttpStreamingHttpError> finish(LatentHttpStreamingUpload upload) {
            if (upload.retired) throw new AssertionError("finish replay");
            upload.retired=true; finishes++;
            if (finishError>=0) return Result.err(new LatentHttpStreamingHttpError(finishError));
            return Result.ok(new LatentHttpStreamingResponse(status,
                List.of(new LatentHttpStreamingHeader("X-Many", "a"), new LatentHttpStreamingHeader("X-Many", "b")),
                Option.some("application/octet-stream"), new LatentHttpStreamingBody()));
        }
        public static Result<Option<LatentHttpStreamingChunk>, LatentHttpStreamingHttpError> read(LatentHttpStreamingBody body, Long maximum) {
            if (body.retired) throw new AssertionError("read after drop");
            if (maximum!=4096) throw new AssertionError("chunk bound");
            reads++;
            if (readError>=0) return Result.err(new LatentHttpStreamingHttpError(readError));
            return Result.ok(reads==1 ? Option.some(new LatentHttpStreamingChunk()) : Option.none());
        }
        public static Result<byte[], LatentHttpStreamingHttpError> chunkBytes(LatentHttpStreamingChunk chunk) {
            if (chunk.retired) throw new AssertionError("materialized dropped chunk");
            return Result.ok(new byte[]{0, (byte)255, 65, 66, 67});
        }
        public static Result<List<LatentHttpStreamingHeader>, LatentHttpStreamingHttpError> trailers(LatentHttpStreamingBody body) {
            if (body.retired) throw new AssertionError("trailers after drop");
            trailers++; return Result.ok(List.of());
        }
    }
}
