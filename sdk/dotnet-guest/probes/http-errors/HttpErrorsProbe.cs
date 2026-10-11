using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;

// Execute the actual captured WASI BCL in two isolated host load contexts.
// This verifies its conversion/exception boundary, not a guest scheduler or
// default-client component. No native WASI import is called by this probe.
if (args.Length != 3 || File.Exists(args[2]))
    throw new InvalidDataException("http-error-probe-arguments");
string Digest(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
if (Digest(args[0]) != "3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587")
    throw new InvalidDataException("http-error-probe-original-preimage");
var originalContext = new AssemblyLoadContext("original-wasi-bcl", isCollectible: true);
var derivedContext = new AssemblyLoadContext("derived-wasi-bcl", isCollectible: true);
var original = originalContext.LoadFromAssemblyPath(Path.GetFullPath(args[0]));
var derived = derivedContext.LoadFromAssemblyPath(Path.GetFullPath(args[1]));
var cases = 0;
void Equal(object? expected, object? actual)
{
    cases++;
    if (!Equals(expected, actual))
        throw new InvalidDataException("http-error-probe-mismatch");
}
string ConvertError(Assembly assembly, byte tag, object? payload)
{
    var interop = assembly.GetType("System.Net.Http.WasiHttpInterop", throwOnError: true)!;
    var converter = interop.GetMethod("ErrorCodeToString", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)!;
    var errorType = converter.GetParameters().Single().ParameterType;
    var error = Activator.CreateInstance(errorType, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
        binder: null, args: [tag, payload], culture: null)!;
    return (string)converter.Invoke(null, [error])!;
}
for (byte tag = 0; tag < 38; tag++)
    Equal(ConvertError(original, tag, null), ConvertError(derived, tag, null));
Equal(ConvertError(original, 255, "latent-http-uncertain"), ConvertError(derived, 255, "latent-http-uncertain"));
string[] markers = [
    "latent-http-request-too-large", "latent-http-response-too-large",
    "latent-http-deadline-exceeded", "latent-http-cancelled", "latent-http-budget-exhausted",
    "latent-http-tls-failed", "latent-http-connection-failed", "latent-http-unavailable",
    "latent-http-uncertain", "latent-http-invalid-state",
];
foreach (var marker in markers)
{
    Equal("INTERNAL_ERROR", ConvertError(original, 38, marker));
    var message = ConvertError(derived, 38, marker);
    Equal("INTERNAL_ERROR:" + marker, message);
    var exceptionType = derived.GetType("System.Net.Http.HttpRequestException", throwOnError: true)!;
    var exception = (Exception)Activator.CreateInstance(exceptionType, [message])!;
    Equal(message, exception.Message);
}
object?[] hiddenPayloads = [null, "", "private-credential", "latent-http-uncertain\nprivate-credential",
    "prefix-latent-http-uncertain", "latent-http-uncertain-suffix", "LATENT-HTTP-UNCERTAIN",
    new string('x', 8192), 42, new object()];
foreach (var payload in hiddenPayloads)
    Equal("INTERNAL_ERROR", ConvertError(derived, 38, payload));
var result = new {
    scope = "captured-wasi-bcl-conversion-and-exception",
    assertions = cases,
    originalDigest = "sha256:" + Digest(args[0]),
    derivedDigest = "sha256:" + Digest(args[1]),
    allNonInternalVariantsUnchanged = true,
    boundedCategoriesPreserved = true,
    arbitraryPayloadDisclosure = false,
    defaultClientComponentQualified = false,
};
using (var output = new FileStream(args[2], FileMode.CreateNew, FileAccess.Write, FileShare.None))
    JsonSerializer.Serialize(output, result);
Console.WriteLine(JsonSerializer.Serialize(result));
originalContext.Unload();
derivedContext.Unload();
