# Java closed filesystem boundary

The maintained TeaVM C/WASI compiler has no filesystem provider. Ordinary
`java.io.FileInputStream`, `FileOutputStream` and `File.createTempFile` calls
must fail with a caught `UnsupportedOperationException`; an uncaught native
trap or a fabricated missing file is not the supported refusal contract.
The fresh signed programme for this port is pending.

The compiler authenticates both exact TeaVM 0.15.0 core and class-library JARs.
An SDK-owned model transformer changes only three methods on the existing
`CFileSystem` owner. `getUserDir` and `getFile` throw the standard unchecked
Unsupported exception. `isWindows` supplies the maintained WASI target's POSIX
path syntax, so ordinary `File` class initialization and argument validation do
not first enter the closed native filesystem. This value is target metadata;
it does not claim any directory or file exists.

The original `File`, input/output stream and temporary-file factory bodies
remain unchanged, including their null, prefix-length and empty-output-name
checks. All 31 other backend method bodies, the lower native refusal traps and
the separate immutable classpath/byte-array resource implementations remain
unchanged. Unknown model layouts, altered pinned JAR identities and repeated
application of the transformer fail before publishing a partial port. No
application shim, writable scratch, filesystem import or grant is added.

The exact locked compiler-model control passed two Unsupported bodies, POSIX
target metadata, preservation of 31 other backend bodies and the original
validation/resource owners, five layout mutations, repeated-port refusal and
an unrelated application owner. These are compiler-model observations, not
NativeAOT, native runtime or signed component qualification.

The normal Java workflow retains its 55-minute parent and all original commands.
The separate 20-minute scratch child consumes only its authenticated public
normal native products and four Java companion packages. Its unchanged ordinary
file open/create/temp calls must now catch Unsupported, followed by the original
explicit trap/fresh-state controls. Six additional calls preserve four null
failures, the invalid temporary prefix and the empty output-name error. All 39
outcomes, zero external effects, physical/provider retirement and clean shutdown
remain required. Profile selection supplies no filesystem authority. The manual
same-products lane may retain historical native compilation separately from the
fresh current Java components; it cannot relabel an old .NET receipt as Java.

This is the named closed-filesystem portion of [#681](https://github.com/KirilsTurkins/latent-service-fabric/issues/681).
Other filesystem APIs, concurrent facilities, pending flush, late completion and
cross-tenant runtime qualification retain their own requirements.
