// Use the pinned SDK's own NuGet content-hash algorithm. Signed package hashes
// exclude the repository signature; a raw ZIP SHA-512 is a different identity.
using NuGet.Packaging;
if (args.Length != 1) throw new ArgumentException("one package archive required");
var info = new FileInfo(args[0]);
if (!info.Exists || info.Length < 1 || info.Length > 512L * 1024 * 1024)
    throw new ArgumentException("bounded package archive required");
using var package = new PackageArchiveReader(info.FullName);
var signature = await package.GetPrimarySignatureAsync(CancellationToken.None);
if (signature != null)
    await package.ValidateIntegrityAsync(signature.SignatureContent, CancellationToken.None);
Console.WriteLine(package.GetContentHash(CancellationToken.None));
