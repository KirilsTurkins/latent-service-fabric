The maintained TeaVM 0.15 C backend saves Java locals across `setjmp` and
`longjmp` using `teavm_spill_N`. A declaration such as
`volatile TeaVM_Array* teavm_spill_1` qualifies the pointee, leaving the saved
pointer indeterminate after a nonlocal jump. The SDK changes that declaration
to `TeaVM_Array* volatile teavm_spill_1`. Ordinary object references receive
the equivalent `void* volatile` declaration. Scalar saves, application source,
object layout, exception routing and compiler optimization remain unchanged.

The compiler selects `teavm-0.15-wasm-sjlj-reference-spills-v2`. The historical
`teavm-0.15-wasm-sjlj-pointer-spills-v1` helper remains available with its original
reviewed grammar. V2 additionally accepts the exact `volatile TeaVM_Array*`
declaration emitted for the pinned backend's eight primitive/object array
categories. Unknown types, altered declaration grammar and repeated adaptation
are rejected. All generated class declarations are validated before any class
or platform file changes, and the receipt binds every original and derived file.

The checked-in `sdk/java-guest/tests/probes/CSpillDeclarations.java` exercises
the actual pinned `BufferedCodeWriter.printType(VariableType)` emitter. The
reviewed `teavm-core-0.15.0.jar` digest is
`501ca5eae7a835cd6278c822685f32800fa0818e3f42204afc9b558408c943df`.
Compile that probe with `-proc:none` and the verified JAR on the classpath to
observe all emitted declarations. This compiler metadata control establishes
the reviewed grammar; it does not qualify guest scheduling, lifecycle or the
complete Java runtime profile.
