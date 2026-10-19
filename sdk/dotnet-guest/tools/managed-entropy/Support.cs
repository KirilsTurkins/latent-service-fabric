using System.Runtime.InteropServices;
using System.Security.Cryptography;
namespace Lsf.StandardEntropy;
internal static unsafe class Interop {
 [DllImport("System.Native", EntryPoint="SystemNative_GetCryptographicallySecureRandomBytes")]
 private static extern int SecureBytes(byte* buffer, int count);
 internal static void GetCryptographicallySecureRandomBytes(byte* buffer, int count) {
  if (SecureBytes(buffer, count) != 0) throw new CryptographicException();
 }
}
internal static class SR {
 internal const string Argument_InvalidRandomRange = "The specified range is invalid.";
 internal const string Arg_EmptySpan = "The span must contain at least one element.";
 internal const string Argument_InvalidOffLen = "Offset and length were out of bounds for the array.";
}
