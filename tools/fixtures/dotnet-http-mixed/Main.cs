using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace ServiceWorld.wit.Exports.examples.dotnetStandardHttp;

public class ApiExportsImpl : IApiExports {
    private static int calls;
    private static readonly AsyncLocal<string?> context = new();

    public static string Run(uint which, string endpoint) {
        if (++calls != 1 || context.Value != null || SynchronizationContext.Current != null)
            throw new InvalidOperationException("activation-local client context leaked");
        return "1:" + RunAsync(which, endpoint).GetAwaiter().GetResult();
    }

    private static async Task<string> RunAsync(uint which, string endpoint) {
        string[] origins = endpoint.Split('|');
        if (origins.Length is < 2 or > 3) throw new ArgumentException("two explicitly authorized fixture origins required");
        endpoint = origins[0];
        string siblingEndpoint = origins[1];
        using var client = new HttpClient();
        switch (which) {
        case 0: return Options();
        case 1: return await Views(client, endpoint);
        case 2: return await Borrowed(client, endpoint);
        case 3: return await Pending(client, endpoint, siblingEndpoint, false);
        case 4: return await Pending(client, endpoint, siblingEndpoint, true);
        case 5: return await OwnedUpload(client, endpoint);
        case 6: return await IncompleteUpload(client, endpoint, siblingEndpoint);
        case 7: return await LengthMismatch(client, endpoint, siblingEndpoint);
        case 8: return await RequestLimit(client, endpoint);
        case 9: return await CancelBody(client, endpoint);
        case 10: return await AbortBody(client, endpoint);
        case 11: return await Accepted(endpoint, false);
        case 12: return await Accepted(endpoint, true);
        case 13: return await Late(client, endpoint);
        case 14: return await RejectedHeader(client, endpoint);
        case 15: {
            using var response = await client.GetAsync(endpoint + "/conformance/redirect");
            if ((int)response.StatusCode != 302 || response.Headers.Location == null)
                throw new InvalidOperationException("redirect status was changed");
            return "redirect:302:unfollowed";
        }
        case 16: {
            using var response = await client.GetAsync(endpoint + "/conformance/json");
            using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            if ((int)response.StatusCode != 200 || body.RootElement.GetProperty("id").GetInt32() != 7)
                throw new InvalidOperationException("fresh domain result changed");
            return "fresh:200:0";
        }
        case 17: {
            try { using var response = await client.GetAsync(endpoint + "/conformance/json"); }
            catch (HttpRequestException) { return "denied"; }
            throw new InvalidOperationException("foreign endpoint was admitted");
        }
        case 18:
        case 19: {
            using var response = await client.GetAsync(endpoint + "/conformance/body/partial", HttpCompletionOption.ResponseHeadersRead);
            await response.Content.ReadAsByteArrayAsync();
            throw new InvalidOperationException("held root terminal unexpectedly completed");
        }
        case 20: {
            string nonce = origins.Length == 3 ? origins[2] : throw new ArgumentException("tenant nonce required");
            if (nonce is not ("tenant-examples" or "tenant-foreign")) throw new ArgumentException("fixed tenant nonce required");
            using var request = new HttpRequestMessage(HttpMethod.Get, endpoint + "/conformance/echo");
            request.Headers.Add("X-Conformance", nonce);
            using var response = await client.SendAsync(request);
            using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            string actual = body.RootElement.GetProperty("customHeaderBase64").GetString()!;
            if ((int)response.StatusCode != 200 || body.RootElement.GetProperty("method").GetString() != "GET"
                    || actual != Convert.ToBase64String(Encoding.ASCII.GetBytes(nonce)))
                throw new InvalidOperationException("foreign response or client context was reused");
            return "fresh-tenant:" + nonce + ":200:0";
        }
        default: throw new ArgumentOutOfRangeException(nameof(which));
        }
    }

    private static string Options() {
        using var handler = new HttpClientHandler();
        int refused = 0;
        void Unsupported(Action action) {
            try { action(); }
            catch (PlatformNotSupportedException) { refused++; return; }
            throw new InvalidOperationException("unsupported setting accepted");
        }
        if (handler.SupportsAutomaticDecompression || handler.SupportsProxy || handler.SupportsRedirectConfiguration)
            throw new InvalidOperationException("unqualified setting advertised");
        Unsupported(() => { handler.UseCookies = false; });
        Unsupported(() => { handler.CookieContainer = new CookieContainer(); });
        Unsupported(() => { handler.AutomaticDecompression = DecompressionMethods.None; });
        Unsupported(() => { handler.UseProxy = false; });
        Unsupported(() => { handler.Proxy = null; });
        Unsupported(() => { handler.DefaultProxyCredentials = null; });
        Unsupported(() => { handler.PreAuthenticate = false; });
        Unsupported(() => { handler.UseDefaultCredentials = false; });
        Unsupported(() => { handler.Credentials = null; });
        Unsupported(() => { handler.AllowAutoRedirect = false; });
        Unsupported(() => { handler.MaxAutomaticRedirections = 1; });
        Unsupported(() => { handler.MaxConnectionsPerServer = 1; });
        Unsupported(() => { handler.MaxResponseHeadersLength = 1; });
        Unsupported(() => { handler.CheckCertificateRevocationList = false; });
        Unsupported(() => { handler.ServerCertificateCustomValidationCallback = null; });
        bool nullChecked = false;
        try { handler.CookieContainer = null!; }
        catch (ArgumentNullException) { nullChecked = true; }
        if (!nullChecked || refused != 15) throw new InvalidOperationException("option validation changed");
        return "options:15:validation:3";
    }

    private static async Task<string> Views(HttpClient client, string endpoint) {
        using var response = await client.GetAsync(endpoint + "/conformance/json", HttpCompletionOption.ResponseHeadersRead);
        var first = await response.Content.ReadAsStreamAsync();
        var second = await response.Content.ReadAsStreamAsync();
        if (!ReferenceEquals(first, second)) throw new InvalidOperationException("body view was duplicated");
        using var bytes = new MemoryStream();
        await first.CopyToAsync(bytes);
        if (first.ReadByte() != -1) throw new InvalidOperationException("consumed body was replayed");
        first.Dispose(); first.Dispose();
        bool closed = false;
        try { first.ReadByte(); } catch (ObjectDisposedException) { closed = true; }
        if (!closed || bytes.Length != 57) throw new InvalidOperationException("body close changed");
        return "views:57:same:eof:closed";
    }

    private static async Task<string> Borrowed(HttpClient client, string endpoint) {
        using var response = await client.GetAsync(endpoint + "/conformance/json", HttpCompletionOption.ResponseHeadersRead);
        using var sink = new TrackedStream(Array.Empty<byte>(), writable: true);
        await response.Content.CopyToAsync(sink);
        if (sink.Disposals != 0 || sink.Length != 57) throw new InvalidOperationException("borrowed output was disposed");
        sink.WriteByte(42);
        return "borrowed:57:open";
    }

    private static async Task<string> Pending(HttpClient client, string endpoint, string siblingEndpoint, bool buffered) {
        context.Value = "parent";
        using var threadLocal = new ThreadLocal<string>(() => "thread:" + Thread.CurrentThread.ManagedThreadId);
        int parentThread = Thread.CurrentThread.ManagedThreadId, childThread = 0, childAfter = 0;
        threadLocal.Value = "parent:" + parentThread;
        var entered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var pending = Task.Run(async () => {
            if (context.Value != "parent") throw new InvalidOperationException("accepted context was not captured");
            childThread = Thread.CurrentThread.ManagedThreadId;
            if (threadLocal.Value != (childThread == parentThread ? "parent:" + parentThread : "thread:" + childThread))
                throw new InvalidOperationException("thread-local initialization changed");
            threadLocal.Value = "child:" + childThread;
            context.Value = "child";
            var sending = client.GetAsync(endpoint + "/conformance/body/partial",
                buffered ? HttpCompletionOption.ResponseContentRead : HttpCompletionOption.ResponseHeadersRead);
            entered.SetResult(true);
            using var response = await sending;
            byte[] bytes = await response.Content.ReadAsByteArrayAsync();
            if (context.Value != "child" || bytes.Length != 4109)
                throw new InvalidOperationException("pending context or body changed");
            childAfter = Thread.CurrentThread.ManagedThreadId;
            string expected = childAfter == childThread ? "child:" + childThread
                : childAfter == parentThread ? "parent:" + parentThread : "thread:" + childAfter;
            if (threadLocal.Value != expected) throw new InvalidOperationException("thread-local continuation changed");
            return bytes.Length;
        });
        await entered.Task;
        if (pending.IsCompleted) throw new InvalidOperationException("accepted HTTP task was not incomplete");
        using var sibling = await client.GetAsync(siblingEndpoint + "/conformance/json");
        using var body = JsonDocument.Parse(await sibling.Content.ReadAsStringAsync());
        if (body.RootElement.GetProperty("id").GetInt32() != 7 || pending.IsCompleted || context.Value != "parent")
            throw new InvalidOperationException("sibling did not progress during the held body");
        int parentAfter = Thread.CurrentThread.ManagedThreadId;
        string expectedParent = parentAfter == childThread ? "child:" + childThread
            : parentAfter == parentThread ? "parent:" + parentThread : "thread:" + parentAfter;
        if (threadLocal.Value != expectedParent) throw new InvalidOperationException("thread-local caller state changed");
        using var marker = await client.PostAsync(siblingEndpoint + "/conformance/echo",
            new StringContent(buffered ? "managed-sibling-content" : "managed-sibling-headers"));
        await marker.Content.ReadAsByteArrayAsync();
        int count = await pending;
        return (buffered ? "content" : "headers") + ":4109:pending:context:isolated:thread-local:"
            + parentThread + ":" + childThread + ":" + childAfter + ":" + parentAfter;
    }

    private static async Task<string> OwnedUpload(HttpClient client, string endpoint) {
        var source = new TrackedStream(new byte[4096]);
        using (var request = new HttpRequestMessage(HttpMethod.Post, endpoint + "/conformance/echo")) {
            request.Content = new StreamContent(source);
            using var response = await client.SendAsync(request);
            using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            if (body.RootElement.GetProperty("bodyBase64").GetBytesFromBase64().Length != 4096 || source.Disposals != 0)
                throw new InvalidOperationException("owned request content changed");
        }
        if (source.Disposals != 1) throw new InvalidOperationException("owned request stream not disposed once");
        return "stream-content:4096:owned:1";
    }

    private static async Task<string> IncompleteUpload(HttpClient client, string endpoint, string siblingEndpoint) {
        var gate = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var content = new GatedContent(gate.Task, 4096, 4096);
        var sending = client.PostAsync(endpoint + "/conformance/hold/upload", content);
        await content.Entered.Task;
        if (sending.IsCompleted) throw new InvalidOperationException("producer was not pending");
        using var sibling = await client.GetAsync(siblingEndpoint + "/conformance/json");
        await sibling.Content.ReadAsByteArrayAsync();
        if (sending.IsCompleted || content.Finished) throw new InvalidOperationException("unfinished upload was completed");
        gate.SetResult(true);
        using var response = await sending;
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        if (body.RootElement.GetProperty("bodyBytes").GetInt32() != 4096 || !content.Finished)
            throw new InvalidOperationException("incomplete producer bytes changed");
        return "producer:4096:pending:sibling:finished";
    }

    private static async Task<string> LengthMismatch(HttpClient client, string endpoint, string siblingEndpoint) {
        var gate = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var content = new GatedContent(gate.Task, 8, 4);
        var sending = client.PostAsync(endpoint + "/conformance/echo", content);
        await content.Entered.Task;
        using var sibling = await client.GetAsync(siblingEndpoint + "/conformance/json");
        await sibling.Content.ReadAsByteArrayAsync();
        if (sending.IsCompleted || content.Finished) throw new InvalidOperationException("mismatch was not pending before dispatch");
        gate.SetResult(true);
        try { using var response = await sending; }
        catch (HttpRequestException) { return "length-mismatch:transport-error"; }
        throw new InvalidOperationException("short declared upload succeeded");
    }

    private static async Task<string> RequestLimit(HttpClient client, string endpoint) {
        using var content = new ByteArrayContent(new byte[4097]);
        try { using var response = await client.PostAsync(endpoint + "/conformance/echo", content); }
        catch (HttpRequestException) { return "request-limit:transport-error"; }
        throw new InvalidOperationException("request limit was ignored");
    }

    private static async Task<string> CancelBody(HttpClient client, string endpoint) {
        using var cancellation = new CancellationTokenSource();
        using var response = await client.GetAsync(endpoint + "/conformance/body/partial", HttpCompletionOption.ResponseHeadersRead, cancellation.Token);
        using var stream = await response.Content.ReadAsStreamAsync(cancellation.Token);
        byte[] bytes = new byte[5];
        await stream.ReadExactlyAsync(bytes, cancellation.Token);
        if (Encoding.ASCII.GetString(bytes) != "first") throw new InvalidOperationException("partial prefix changed");
        using var sibling = await client.GetAsync(endpoint + "/conformance/json");
        await sibling.Content.ReadAsByteArrayAsync();
        cancellation.CancelAfter(100);
        try { await stream.ReadAsync(bytes, cancellation.Token); }
        catch (OperationCanceledException error) {
            if (error.CancellationToken != cancellation.Token) throw new InvalidOperationException("body cancel token changed");
            return "body-cancel:5:token:sibling";
        }
        throw new InvalidOperationException("body cancellation was ignored");
    }

    private static async Task<string> AbortBody(HttpClient client, string endpoint) {
        using var response = await client.GetAsync(endpoint + "/conformance/body/partial", HttpCompletionOption.ResponseHeadersRead);
        var stream = await response.Content.ReadAsStreamAsync();
        byte[] bytes = new byte[5];
        await stream.ReadExactlyAsync(bytes);
        if (Encoding.ASCII.GetString(bytes) != "first") throw new InvalidOperationException("early prefix changed");
        response.Dispose();
        try { await stream.ReadAsync(bytes); }
        catch (ObjectDisposedException) { return "response-dispose:5:closed"; }
        throw new InvalidOperationException("disposed response body remained readable");
    }

    private static async Task<string> Accepted(string endpoint, bool trap) {
        var entered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        _ = Task.Run(async () => {
            context.Value = "accepted-child";
            using var childClient = new HttpClient();
            using var response = await childClient.GetAsync(endpoint + "/conformance/body/partial", HttpCompletionOption.ResponseHeadersRead);
            entered.SetResult(true);
            await response.Content.ReadAsByteArrayAsync();
        });
        await entered.Task;
        if (trap) throw new InvalidOperationException("owned accepted HTTP root trap");
        return "root-return:accepted";
    }

    private static async Task<string> Late(HttpClient client, string endpoint) {
        var ready = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var logical = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        var work = Task.Run(async () => {
            using var response = await client.GetAsync(endpoint + "/conformance/body/partial", HttpCompletionOption.ResponseHeadersRead);
            ready.SetResult(true);
            byte[] bytes = await response.Content.ReadAsByteArrayAsync();
            bool overwritten = logical.TrySetResult(bytes.Length);
            return (bytes.Length, overwritten);
        });
        await ready.Task;
        if (work.IsCompleted || !logical.TrySetCanceled()) throw new InvalidOperationException("logical cancel did not precede completion");
        try { await logical.Task; throw new InvalidOperationException("cancelled result became successful"); }
        catch (OperationCanceledException) { }
        using var marker = await client.PostAsync(endpoint + "/conformance/echo", new StringContent("managed-task-cancelled"));
        await marker.Content.ReadAsByteArrayAsync();
        if (work.IsCompleted) throw new InvalidOperationException("held work finished before marker");
        var completed = await work;
        if (completed.Item1 != 4109 || completed.overwritten || !logical.Task.IsCanceled)
            throw new InvalidOperationException("late completion overwrote cancellation");
        return "late:cancelled:4109:not-overwritten";
    }

    private static async Task<string> RejectedHeader(HttpClient client, string endpoint) {
        using var request = new HttpRequestMessage(HttpMethod.Get, endpoint + "/conformance/json");
        request.Headers.TryAddWithoutValidation("Cookie", "must-not-leave-guest");
        try { using var response = await client.SendAsync(request); }
        catch (HttpRequestException) { return "reserved-header:transport-error"; }
        throw new InvalidOperationException("reserved header was admitted");
    }

    private sealed class TrackedStream : MemoryStream {
        public int Disposals;
        public TrackedStream(byte[] value, bool writable = false) : base() {
            if (!writable) { Write(value); Position = 0; }
        }
        protected override void Dispose(bool disposing) { if (disposing) Disposals++; base.Dispose(disposing); }
    }

    private sealed class GatedContent : HttpContent {
        private readonly Task gate;
        private readonly int declared, actual;
        public readonly TaskCompletionSource<bool> Entered = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public bool Finished;
        public GatedContent(Task gate, int declared, int actual) {
            this.gate = gate; this.declared = declared; this.actual = actual;
        }
        protected override bool TryComputeLength(out long length) { length = declared; return true; }
        protected override async Task SerializeToStreamAsync(Stream stream, TransportContext? context) {
            int first = Math.Min(actual, 4);
            await stream.WriteAsync(new byte[first]);
            Entered.SetResult(true);
            await gate;
            if (actual > first) await stream.WriteAsync(new byte[actual - first]);
            Finished = true;
        }
    }
}
