using System;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Flurl.Http;
using Refit;

namespace ServiceWorld.wit.Exports.examples.dotnetStandardHttp;

public interface IDomainApi {
    [Get("")]
    Task<ApiResponse<JsonElement>> Get(CancellationToken cancellationToken);
}

[JsonSerializable(typeof(JsonElement))]
internal partial class DomainJson : JsonSerializerContext { }

public class ApiExportsImpl : IApiExports {
    private static int calls;

    public static string Run(uint which, string endpoint) {
        string prefix = (++calls) + ":";
        try {
            using var cancellation = new CancellationTokenSource();
            if (which == 8 || which == 9) cancellation.CancelAfter(100);
            if (which == 16 || which == 17) cancellation.Cancel();
            if (which == 2) return prefix + PrivateFirst.Worker.Get(endpoint, cancellation.Token).GetAwaiter().GetResult();
            if (which == 3) return prefix + PrivateSecond.Worker.Get(endpoint, cancellation.Token).GetAwaiter().GetResult();
            if (which == 19) return prefix + Extension(endpoint, cancellation.Token).GetAwaiter().GetResult();
            if (which == 1 || which == 5 || which == 7 || which == 9 || which == 17) {
                var settings = new RefitSettings {
                    ContentSerializer = new SystemTextJsonContentSerializer(DomainJson.Default.Options)
                };
                using var refitClient = RestService.CreateHttpClient(endpoint, settings);
                var api = RestService.ForGenerated<IDomainApi>(refitClient, settings);
                using var response = api.Get(cancellation.Token).GetAwaiter().GetResult();
                if (response.Error is not null) {
                    using var error = JsonDocument.Parse(response.Error.Content ?? throw new InvalidDataException("missing actual error body"));
                    return prefix + Parse((int)response.StatusCode, error.RootElement);
                }
                return prefix + Parse((int)response.StatusCode, response.Content);
            }
            using var client = new FlurlClient();
            var request = client.Request(endpoint).AllowAnyHttpStatus();
            if (which == 10) request.WithHeader("Authorization", "must-not-leave-guest");
            using var result = which == 12 || which == 14
                ? request.SendAsync(HttpMethod.Post, new ByteArrayContent([0, 1, 2, 3]),
                    cancellationToken: cancellation.Token, completionOption: HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult()
                : request.GetAsync(cancellationToken: cancellation.Token,
                    completionOption: HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult();
            if (which == 18) {
                using var partial = result.GetStreamAsync().GetAwaiter().GetResult();
                byte[] first = new byte[4];
                return prefix + "early:" + partial.Read(first);
            }
            using var document = JsonDocument.Parse(result.GetStringAsync().GetAwaiter().GetResult());
            if (which == 12) {
                if (document.RootElement.GetProperty("method").GetString() != "POST"
                        || document.RootElement.GetProperty("bodyBase64").GetString() != "AAECAw==")
                    throw new InvalidDataException("actual mutation bytes changed");
                return prefix + "200:echo:AAECAw==";
            }
            return prefix + Parse(result.StatusCode, document.RootElement);
        } catch (FlurlHttpTimeoutException) {
            return prefix + "cancelled";
        } catch (FlurlHttpException error) {
            return prefix + (error.InnerException is OperationCanceledException ? "cancelled" : "transport-error");
        } catch (OperationCanceledException) {
            return prefix + "cancelled";
        } catch (HttpRequestException) {
            return prefix + "transport-error";
        } catch (IOException) {
            return prefix + "transport-error";
        } catch (JsonException) {
            return prefix + "invalid-json";
        }
    }

    private static string Parse(int status, JsonElement body) {
        if (status >= 400) {
            if (body.GetProperty("status").GetInt32() != status) throw new InvalidDataException("actual HTTP error status changed");
            return status + ":error:" + body.GetProperty("message").GetString();
        }
        var items = body.GetProperty("items");
        if (items.GetArrayLength() != 2) throw new InvalidDataException("actual domain item count changed");
        return status + ":domain:" + body.GetProperty("id").GetInt32() + ":"
            + body.GetProperty("name").GetString() + ":" + items[0].GetString() + "|"
            + items[1].GetString() + ":" + body.GetProperty("empty").GetString();
    }

    private sealed class GuestExtension : DelegatingHandler {
        public int Calls;
        public GuestExtension() : base(new HttpClientHandler()) { }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) {
            if (++Calls != 1) throw new InvalidOperationException("unexpected extension replay");
            return base.SendAsync(request, token);
        }
    }

    private static async Task<string> Extension(string endpoint, CancellationToken token) {
        using var handler = new GuestExtension();
        using var client = new HttpClient(handler);
        using var response = await client.GetAsync(endpoint, HttpCompletionOption.ResponseHeadersRead, token);
        using var stream = await response.Content.ReadAsStreamAsync(token);
        using var document = await JsonDocument.ParseAsync(stream, cancellationToken: token);
        if (handler.Calls != 1) throw new InvalidOperationException("extension not entered");
        return Parse((int)response.StatusCode, document.RootElement);
    }
}
