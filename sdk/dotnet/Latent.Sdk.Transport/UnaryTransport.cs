using System.Buffers.Binary;
using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using Google.Protobuf;
using WireControl = global::Latent.Control.V1;
using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport;

public sealed partial class BoundedClient
{
    internal async Task<Response> UnaryAsync<Response>(string method, IMessage input, CallState state, CancellationToken cancellationToken)
    {
        int size = input.CalculateSize();
        if (size > state.RequestLimit) throw state.Error(Profile.FailureCategory.Limit, "encoded request exceeds client limit");
        byte[] packet = new byte[size + 5];
        BinaryPrimitives.WriteUInt32BigEndian(packet.AsSpan(1, 4), (uint)size);
        input.WriteTo(packet.AsSpan(5));
        using var request = new HttpRequestMessage(HttpMethod.Post, new Uri(endpoint, method))
        {
            Version = HttpVersion.Version20,
            VersionPolicy = HttpVersionPolicy.RequestVersionExact,
            Content = new ByteArrayContent(packet)
        };
        request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/grpc+proto");
        request.Headers.TryAddWithoutValidation("te", "trailers");
        request.Headers.TryAddWithoutValidation("grpc-accept-encoding", "identity");
        request.Headers.TryAddWithoutValidation("grpc-timeout", Math.Max(1, (long)Math.Ceiling(state.Remaining.TotalMilliseconds)).ToString(CultureInfo.InvariantCulture) + "m");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", config.BearerToken);
        CheckDeadline(state, cancellationToken);
        state.Dispatched = true;
        using HttpResponseMessage response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
        byte[]? payload = null;
        Exception? bodyFailure = null;
        try
        {
            using Stream body = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
            payload = await ReadUnaryAsync(body, state.ResponseLimit, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception failure) when (failure is IOException or FormatException or GraphLimitException or OperationCanceledException or HttpRequestException)
        {
            bodyFailure = failure;
        }
        string[] statuses = HeaderValues(response, "grpc-status");
        if (statuses.Length == 1 && int.TryParse(statuses[0], NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out int status) &&
            status.ToString(CultureInfo.InvariantCulture) == statuses[0]) state.GrpcStatus = status;
        ReadAudit(response, state);
        if (bodyFailure is GraphLimitException) throw state.Error(Profile.FailureCategory.Limit, "encoded response exceeds client limit");
        if (bodyFailure is FormatException) throw state.Error(Profile.FailureCategory.Decode, "invalid unary response framing");
        if (bodyFailure is not null) throw bodyFailure;
        string? contentType = response.Content.Headers.ContentType?.ToString();
        string[] encodings = HeaderValues(response, "grpc-encoding");
        if (response.Version.Major != 2 || response.StatusCode != HttpStatusCode.OK ||
            contentType is not ("application/grpc" or "application/grpc+proto") || response.Content.Headers.ContentEncoding.Count != 0 ||
            statuses.Length != 1 || state.GrpcStatus is null || encodings.Length > 1 || encodings.Length == 1 && encodings[0] != "identity")
            throw state.Error(Profile.FailureCategory.Decode, "invalid bounded RPC response headers");
        if (state.GrpcStatus != 0)
        {
            Profile.ClientFailure failure = state.Failure(state.GrpcStatus == 4 ? Profile.FailureCategory.Deadline : Profile.FailureCategory.Rpc,
                "remote RPC failed; recover by the original identity");
            throw new Profile.ClientException(ReadPlatformError(response, state, failure, cancellationToken));
        }
        if (payload is null) throw state.Error(Profile.FailureCategory.Decode, "unary response message is missing");
        var message = (IMessage)Activator.CreateInstance(typeof(Response))!;
        Decode(payload, message, cancellationToken);
        return (Response)message;
    }

    private void Decode(byte[] payload, IMessage message, CancellationToken cancellationToken, int? nodeLimit = null)
    {
        var budget = new GraphBudget(config.MaxGraphBytes - 3L * payload.Length, nodeLimit ?? config.MaxGraphNodes, cancellationToken);
        budget.Spend(0);
        WireShape.Validate(payload, message.Descriptor, budget);
        using var memory = new MemoryStream(payload, writable: false);
        using CodedInputStream input = CodedInputStream.CreateWithLimits(memory, Math.Max(1, payload.Length), 16);
        message.MergeFrom(input);
    }

    private static async Task<byte[]?> ReadUnaryAsync(Stream body, int maximum, CancellationToken cancellationToken)
    {
        byte[] prefix = new byte[5];
        if (await body.ReadAsync(prefix.AsMemory(0, 1), cancellationToken).ConfigureAwait(false) == 0) return null;
        await body.ReadExactlyAsync(prefix.AsMemory(1), cancellationToken).ConfigureAwait(false);
        if (prefix[0] != 0) throw new FormatException("compression is not supported");
        uint length = BinaryPrimitives.ReadUInt32BigEndian(prefix.AsSpan(1));
        if (length > maximum) throw new GraphLimitException();
        byte[] payload = new byte[(int)length];
        await body.ReadExactlyAsync(payload, cancellationToken).ConfigureAwait(false);
        if (await body.ReadAsync(prefix.AsMemory(0, 1), cancellationToken).ConfigureAwait(false) != 0)
            throw new FormatException("extra unary response frame");
        return payload;
    }

    private static string[] HeaderValues(HttpResponseMessage response, string name) =>
        (response.Headers.TryGetValues(name, out IEnumerable<string>? initial) ? initial : [])
        .Concat(response.TrailingHeaders.TryGetValues(name, out IEnumerable<string>? trailing) ? trailing : []).ToArray();

    private void ReadAudit(HttpResponseMessage response, CallState state)
    {
        string[] statuses = HeaderValues(response, "latent-audit-status");
        string[] attempts = HeaderValues(response, "latent-audit-attempt");
        if (statuses.Length > 1 || attempts.Length > 1 || statuses.Length == 1 && (statuses[0].Length == 0 || GraphBudget.Utf8.GetByteCount(statuses[0]) > 256))
            throw state.Error(Profile.FailureCategory.Decode, "invalid audit response metadata");
        if (attempts.Length == 1)
        {
            try { state.AuditAttemptSequence = Profile.UnsignedDecimal.Parse(attempts[0]); }
            catch (Exception failure) when (failure is FormatException or OverflowException)
            {
                throw state.Error(Profile.FailureCategory.Decode, "invalid audit attempt sequence");
            }
        }
        if (statuses.Length == 0) return;
        state.AuditStatus = Redact(statuses[0]);
        Profile.AuditAckStatus? status = statuses[0] switch
        {
            "durable" => Profile.AuditAckStatus.Durable,
            "outcome-unknown" => Profile.AuditAckStatus.OutcomeUnknown,
            "audit-unavailable" => Profile.AuditAckStatus.AuditUnavailable,
            "disabled" => Profile.AuditAckStatus.Disabled,
            _ => null
        };
        if (status is not null) state.AuditAck = new(status.Value, state.AuditAttemptSequence);
    }

    private Profile.ClientFailure ReadPlatformError(HttpResponseMessage response, CallState state, Profile.ClientFailure failure, CancellationToken cancellationToken)
    {
        string[] details = HeaderValues(response, "grpc-status-details-bin");
        if (details.Length == 0) return failure;
        if (details.Length != 1 || details[0].Length > 10924) throw state.Error(Profile.FailureCategory.Decode, "invalid remote diagnostic header");
        string encoded = details[0];
        if (encoded.Length % 4 != 0) encoded = encoded.PadRight(encoded.Length + 4 - encoded.Length % 4, '=');
        byte[] payload = Convert.FromBase64String(encoded);
        if (payload.Length > 8192) throw state.Error(Profile.FailureCategory.Limit, "remote diagnostic exceeds client limit");
        var message = new WireControl.PlatformError();
        Decode(payload, message, cancellationToken, Math.Min(512, config.MaxGraphNodes));
        var detail = (Profile.PlatformError)ProfileCodec.FromWire(message, typeof(Profile.PlatformError));
        if (detail.Code.Length == 0) throw state.Error(Profile.FailureCategory.Decode, "remote diagnostic lacks a code");
        detail = detail with
        {
            Code = Redact(detail.Code), Message = Redact(detail.Message),
            DetailItems = detail.DetailItems.Select(item => item with
            {
                Kind = Redact(item.Kind),
                Fields = item.Fields.GroupBy(pair => Redact(pair.Key)).ToDictionary(group => group.Key, group => Redact(group.Last().Value))
            }).ToArray()
        };
        return failure with { PlatformError = detail };
    }

    private string Redact(string value) => value.Replace(config.BearerToken, "[redacted]", StringComparison.Ordinal);

    private static void CheckDeadline(CallState state, CancellationToken cancellationToken)
    {
        if (cancellationToken.IsCancellationRequested || state.Remaining == TimeSpan.Zero) throw state.Cancelled(cancellationToken);
    }
}
