using System;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Threading;

namespace ServiceWorld.wit.Exports.examples.dotnetStandardHttp;

public class ApiExportsImpl : IApiExports {
    private static int calls;

    private enum Phase {
        Entry, RequestReady, SendBegun, HeadersReady, StreamReady, BodyCopied, JsonParsed, ResultReady
    }

    public static string Run(uint which, string endpoint) {
        if (which == 100) return "fixture-prefix-v1:entry-export";
        Phase stopAfter = which switch {
            101 => Phase.RequestReady,
            102 => Phase.HeadersReady,
            103 => Phase.StreamReady,
            104 => Phase.BodyCopied,
            _ => Phase.Entry
        };
        if (stopAfter != Phase.Entry) which = 0;
        Phase phase = Phase.Entry;
        try {
            return RunCore(which, endpoint, ref phase, stopAfter);
        } catch (Exception error) {
            string location = phase switch {
                Phase.RequestReady => "request-ready",
                Phase.SendBegun => "send-begun",
                Phase.HeadersReady => "headers-ready",
                Phase.StreamReady => "stream-ready",
                Phase.BodyCopied => "body-copied",
                Phase.JsonParsed => "json-parsed",
                Phase.ResultReady => "result-ready",
                _ => "entry"
            };
            string family = error switch {
                PlatformNotSupportedException => "platform-not-supported",
                ObjectDisposedException => "disposed",
                InvalidOperationException => "invalid-operation",
                NotSupportedException => "not-supported",
                ArgumentException => "argument",
                OutOfMemoryException => "out-of-memory",
                OperationCanceledException => "cancelled",
                HttpRequestException => "http",
                JsonException => "json",
                IOException => "io",
                _ => "other"
            };
            return "managed-failure-v1:" + location + ":" + family;
        }
    }

    private static string RunCore(uint which, string endpoint, ref Phase phase, Phase stopAfter) {
        string prefix = (++calls) + ":";
        using var client = new HttpClient();
        using var request = new HttpRequestMessage(which == 1 ? HttpMethod.Post : HttpMethod.Get, endpoint);
        using var cancellation = new CancellationTokenSource();
        if (which == 1) {
            request.Content = new ByteArrayContent([0, 1, 2, 3]);
            request.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/octet-stream");
        }
        if (which == 3) request.Headers.TryAddWithoutValidation("Authorization", "must-not-leave-guest");
        if (which == 4) cancellation.CancelAfter(100);
        phase = Phase.RequestReady;
        if (stopAfter == Phase.RequestReady) return "fixture-prefix-v1:request-ready-plus-cleanup";
        try {
            phase = Phase.SendBegun;
            using var response = client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead,
                cancellation.Token).GetAwaiter().GetResult();
            phase = Phase.HeadersReady;
            if (stopAfter == Phase.HeadersReady) return "fixture-prefix-v1:headers-ready-plus-cleanup";
            using var stream = response.Content.ReadAsStreamAsync(cancellation.Token).GetAwaiter().GetResult();
            phase = Phase.StreamReady;
            if (stopAfter == Phase.StreamReady) return "fixture-prefix-v1:stream-ready-plus-cleanup";
            if (which == 2 || which == 5) {
                byte[] first = new byte[4];
                int count = stream.Read(first);
                if (which == 2) return prefix + "early:" + count;
                cancellation.CancelAfter(100);
                while (stream.ReadAsync(first.AsMemory(), cancellation.Token).GetAwaiter().GetResult() != 0) { }
                return prefix + "unexpected-body-completion";
            }
            using var body = new MemoryStream();
            stream.CopyTo(body);
            phase = Phase.BodyCopied;
            if (stopAfter == Phase.BodyCopied) return "fixture-prefix-v1:body-copied-plus-cleanup";
            using var document = JsonDocument.Parse(body.ToArray());
            phase = Phase.JsonParsed;
            var value = document.RootElement;
            string parsed;
            if (which == 1) {
                if (value.GetProperty("method").GetString() != "POST"
                        || !value.GetProperty("contentLengthPresent").GetBoolean()
                        || !value.GetProperty("contentTypePresent").GetBoolean()
                        || value.GetProperty("customHeaderBase64").ValueKind != JsonValueKind.Null)
                    throw new InvalidDataException("unexpected echo metadata");
                parsed = "echo:" + value.GetProperty("bodyBase64").GetString();
            } else if (!response.IsSuccessStatusCode) {
                if (value.GetProperty("status").GetInt32() != (int)response.StatusCode)
                    throw new InvalidDataException("unexpected error status");
                parsed = "error:" + value.GetProperty("message").GetString();
            } else {
                var items = value.GetProperty("items");
                if (items.GetArrayLength() != 2) throw new InvalidDataException("unexpected item count");
                parsed = "domain:" + value.GetProperty("id").GetInt32() + ":"
                    + value.GetProperty("name").GetString() + ":" + items[0].GetString() + "|"
                    + items[1].GetString() + ":" + value.GetProperty("empty").GetString();
            }
            string result = prefix + (int)response.StatusCode + ":" + parsed;
            phase = Phase.ResultReady;
            return result;
        } catch (OperationCanceledException) {
            return prefix + "cancelled";
        } catch (HttpRequestException) {
            return prefix + "transport-error";
        } catch (JsonException) {
            return prefix + "invalid-json";
        } catch (IOException) {
            return prefix + "transport-error";
        }
    }
}
