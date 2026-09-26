using System.Text;

namespace Lsf.Guest;

/// <summary>The tutorial contract uses Unicode White_Space, as Rust str::trim.</summary>
public static class Text
{
    public static bool Whitespace(char c) => c is >= '\x09' and <= '\x0d'
        or '\x20' or '\x85' or '\u00a0' or '\u1680'
        or >= '\u2000' and <= '\u200a' or '\u2028' or '\u2029'
        or '\u202f' or '\u205f' or '\u3000';
    public static string Trim(string value)
    {
        int begin = 0, end = value.Length;
        while (begin < end && Whitespace(value[begin])) ++begin;
        while (end > begin && Whitespace(value[end - 1])) --end;
        return value[begin..end];
    }
    public static int Utf8Length(string value) => Encoding.UTF8.GetByteCount(value);
}
