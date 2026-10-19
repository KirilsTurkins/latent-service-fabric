using System.Buffers;
using Original = System.Security.Cryptography.RandomNumberGenerator;
namespace Lsf.StandardEntropy;
// The ordinary base implementations are retained for user-derived generators.
// Calls dispatch to the user's byte-array override; they acquire no host authority.
public static class BaseMethods {
 public static void GetBytes(Original self, byte[] data, int offset, int count) {
  ArgumentNullException.ThrowIfNull(data);
  ArgumentOutOfRangeException.ThrowIfNegative(offset);
  ArgumentOutOfRangeException.ThrowIfNegative(count);
  if (data.Length - count < offset) throw new ArgumentException(SR.Argument_InvalidOffLen);
  if (count == 0) return;
  if (offset == 0 && count == data.Length) self.GetBytes(data);
  else { byte[] temp = new byte[count]; self.GetBytes(temp); Buffer.BlockCopy(temp, 0, data, offset, count); }
 }
 public static void GetBytes(Original self, Span<byte> data) {
  byte[] array = ArrayPool<byte>.Shared.Rent(data.Length);
  try { self.GetBytes(array, 0, data.Length); new ReadOnlySpan<byte>(array, 0, data.Length).CopyTo(data); }
  finally { Array.Clear(array, 0, data.Length); ArrayPool<byte>.Shared.Return(array); }
 }
 public static void GetNonZeroBytes(Original self, byte[] data) { throw new NotImplementedException(); }
 public static void GetNonZeroBytes(Original self, Span<byte> data) {
  byte[] array = ArrayPool<byte>.Shared.Rent(data.Length);
  try { self.GetNonZeroBytes(array); new ReadOnlySpan<byte>(array, 0, data.Length).CopyTo(data); }
  finally { Array.Clear(array, 0, data.Length); ArrayPool<byte>.Shared.Return(array); }
 }
}
