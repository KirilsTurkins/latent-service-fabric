"""Ordinary filesystem refusal inputs; no scratch implementation or execution claim."""
from __future__ import annotations
import json
from pathlib import Path
from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, inventory, read_file, snapshot

LANGUAGES = ('rust', 'c', 'go', 'java', 'dotnet')
SOURCES = {'rust': 'src/lib.rs', 'c': 'src/main.c', 'go': 'src/main.go',
           'java': 'src/dev/latent/app/Capsule.java', 'dotnet': 'src/Main.cs'}
CASES = {'rust': ('open', 'create', 'temp-directory'),
         'c': ('open', 'create', 'temp'), 'go': ('open', 'create', 'temp'),
         'java': ('open', 'create', 'temp'), 'dotnet': ('open', 'create', 'temp')}

RUST = r'''
static SCRATCH_CALLS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
fn scratch_case(mode: &str) -> String {
    use std::io::ErrorKind;
    assert_eq!(SCRATCH_CALLS.fetch_add(1, std::sync::atomic::Ordering::Relaxed), 0);
    if mode == "entry" || mode == "fresh" { return "scratch|rust|entry|fresh=1".into(); }
    let result = match mode {
        "open" => std::fs::File::open("lsf-scratch-refusal").map(drop),
        "create" | "trap" => std::fs::OpenOptions::new().write(true).create_new(true)
            .open("lsf-scratch-refusal").map(drop),
        "temp-directory" => std::fs::create_dir("lsf-scratch-temporary-directory"),
        _ => panic!("scratch-mode"),
    };
    let error = match result {
        Err(error) => error,
        Ok(()) => {
            let _ = std::fs::remove_file("lsf-scratch-refusal");
            let _ = std::fs::remove_dir("lsf-scratch-temporary-directory");
            return "scratch|rust|unexpected-success".into();
        }
    };
    let label = match error.kind() {
        ErrorKind::Unsupported => "unsupported", ErrorKind::PermissionDenied => "permission-denied",
        ErrorKind::NotFound => "not-found", _ => "unclassified",
    };
    if mode == "trap" { panic!("scratch-explicit-fixture-trap"); }
    format!("scratch|rust|io-error|kind={label}|fresh=1")
}
'''

GO = r'''
var scratchCalls int
func scratchCase(mode string) string {
    scratchCalls++
    if scratchCalls != 1 { panic("scratch-state-reused") }
    if mode == "entry" || mode == "fresh" { return "scratch|go|entry|fresh=1" }
    var file *os.File
    var err error
    switch mode {
    case "open": file, err = os.Open("lsf-scratch-refusal")
    case "create", "trap": file, err = os.OpenFile("lsf-scratch-refusal", os.O_RDWR|os.O_CREATE|os.O_EXCL, 0600)
    case "temp": file, err = os.CreateTemp(".", "lsf-scratch-")
    default: panic("scratch-mode")
    }
    if err == nil {
        path := file.Name(); file.Close(); os.Remove(path)
        return "scratch|go|unexpected-success"
    }
    var pathError *os.PathError
    var errno syscall.Errno
    if !errors.As(err, &pathError) || !errors.As(err, &errno) {
        return "scratch|go|unclassified"
    }
    if errno == syscall.ENOSYS && !errors.Is(err, errors.ErrUnsupported) {
        return "scratch|go|unclassified"
    }
    if mode == "trap" { panic("scratch-explicit-fixture-trap") }
    return "scratch|go|path-error|errno="+strconv.FormatUint(uint64(errno),10)+"|fresh=1"
}
'''

JAVA = r'''
    private static int scratchCalls;
    private static String scratchCase(String mode) {
        if (++scratchCalls != 1) throw new IllegalStateException("scratch-state-reused");
        if (mode.equals("entry") || mode.equals("fresh")) return "scratch|java|entry|fresh=1";
        String label;
        boolean opened = false;
        try {
            if (mode.equals("open")) {
                try (java.io.InputStream value = new java.io.FileInputStream("lsf-scratch-refusal")) { opened = true; }
            } else if (mode.equals("create") || mode.equals("trap")) {
                java.io.File path = new java.io.File("lsf-scratch-refusal");
                try (java.io.OutputStream value = new java.io.FileOutputStream(path)) { opened = true; }
                path.delete();
            } else if (mode.equals("temp")) {
                java.io.File value = java.io.File.createTempFile("lsf-scratch-", ".tmp", new java.io.File("."));
                opened = true;
                value.delete();
            } else throw new IllegalArgumentException("scratch-mode");
            return "scratch|java|unexpected-success";
        } catch (java.io.FileNotFoundException error) { label = "file-not-found";
        } catch (java.io.IOException error) { label = "io-error";
        } catch (UnsupportedOperationException error) { label = "unsupported-operation";
        } catch (SecurityException error) { label = "security-error"; }
        if (opened) return "scratch|java|unexpected-success";
        if (mode.equals("trap")) throw new IllegalStateException("scratch-explicit-fixture-trap");
        return "scratch|java|"+label+"|fresh=1";
    }
'''

DOTNET = r'''
    private static int scratchCalls;
    private static string ScratchCase(string mode)
    {
        if (++scratchCalls != 1) throw new System.InvalidOperationException("scratch-state-reused");
        if (mode is "entry" or "fresh") return "scratch|dotnet|entry|fresh=1";
        string label;
        bool opened = false;
        try {
            if (mode == "argument-null") {
                using var value = System.IO.File.OpenRead(null!); opened = true;
            } else if (mode == "argument-empty") {
                using var value = System.IO.File.OpenRead(""); opened = true;
            } else if (mode == "argument-nul") {
                using var value = System.IO.File.OpenRead("invalid\0path"); opened = true;
            } else if (mode == "argument-mode") {
                using var value = System.IO.File.Open("lsf-scratch-refusal", (System.IO.FileMode)0); opened = true;
            } else if (mode == "argument-access") {
                using var value = System.IO.File.Open("lsf-scratch-refusal", System.IO.FileMode.Open,
                    (System.IO.FileAccess)0, System.IO.FileShare.None); opened = true;
            } else if (mode == "argument-combination") {
                using var value = System.IO.File.Open("lsf-scratch-refusal", System.IO.FileMode.Create,
                    System.IO.FileAccess.Read, System.IO.FileShare.None); opened = true;
            } else if (mode == "open") {
                using var value = System.IO.File.OpenRead("lsf-scratch-refusal"); opened = true;
            } else if (mode is "create" or "trap") {
                using (var value = System.IO.File.Open("lsf-scratch-refusal", System.IO.FileMode.CreateNew,
                        System.IO.FileAccess.Write, System.IO.FileShare.None)) { opened = true; }
                System.IO.File.Delete("lsf-scratch-refusal");
            } else if (mode == "temp") {
                string path = System.IO.Path.GetTempFileName(); opened = true; System.IO.File.Delete(path);
            } else throw new System.ArgumentException("scratch-mode");
            return "scratch|dotnet|unexpected-success";
        } catch (System.ArgumentNullException) { label = "argument-null";
        } catch (System.ArgumentOutOfRangeException) { label = "argument-out-of-range";
        } catch (System.ArgumentException) { label = "argument";
        } catch (System.PlatformNotSupportedException) { label = "platform-not-supported";
        } catch (System.IO.FileNotFoundException) { label = "file-not-found";
        } catch (System.IO.DirectoryNotFoundException) { label = "directory-not-found";
        } catch (System.UnauthorizedAccessException) { label = "unauthorized-access";
        } catch (System.IO.IOException) { label = "io-error"; }
        if (opened) return "scratch|dotnet|unexpected-success";
        if (mode == "trap") throw new System.InvalidOperationException("scratch-explicit-fixture-trap");
        return "scratch|dotnet|"+label+"|fresh=1";
    }
'''

C = r'''
#include <errno.h>
#include <stdio.h>
static unsigned scratch_calls;
static bool scratch_mode(probe_string_t *name, const char *mode) {
    return name->len == strlen(mode)+8 && memcmp(name->ptr+8, mode, strlen(mode)) == 0;
}
static const char *scratch_case(probe_string_t *name) {
    lsf_require(++scratch_calls == 1);
    if (scratch_mode(name,"entry") || scratch_mode(name,"fresh")) return "scratch|c|entry|fresh=1";
    bool trapped = scratch_mode(name,"trap");
    FILE *value;
    errno = 0;
    if (scratch_mode(name,"open")) value = fopen("lsf-scratch-refusal", "rb");
    else if (scratch_mode(name,"create") || trapped) value = fopen("lsf-scratch-refusal", "wb");
    else if (scratch_mode(name,"temp")) value = tmpfile();
    else { __builtin_trap(); }
    if (value != NULL) { fclose(value); remove("lsf-scratch-refusal"); return "scratch|c|unexpected-success"; }
    int cause = errno;
    if (trapped) __builtin_trap();
    switch (cause) {
        case ENOTSUP: return "scratch|c|errno=notsup|fresh=1";
        case ENOSYS: return "scratch|c|errno=nosys|fresh=1";
        case EBADF: return "scratch|c|errno=badf|fresh=1";
        case ENOENT: return "scratch|c|errno=noent|fresh=1";
        case EACCES: return "scratch|c|errno=access|fresh=1";
        default: return "scratch|c|unclassified";
    }
}
'''


def project(language: str, directory: Path) -> tuple[Path, dict]:
    require(language in LANGUAGES, 'scratch-language')
    if language == 'rust':
        from tools.rust_capsule_project import create
    elif language == 'c':
        from tools.c_capsule_project import create
    elif language == 'go':
        from tools.go_capsule_project import create
    elif language == 'java':
        from tools.java_capsule_project import create
    else:
        from tools.dotnet_guest.project import create
    app = create(directory, 'greeting')
    before = snapshot(app)
    path = app/SOURCES[language]
    source = read_file(path).decode('utf-8')
    if language == 'rust':
        anchor = '    let name = name.trim();'
        hook = '    if let Some(mode) = name.strip_prefix("scratch:") { return Ok(scratch_case(mode)); }\n'
        source = source.replace(anchor, hook+anchor, 1)+RUST
    elif language == 'go':
        anchor = '\tname = strings.TrimSpace(name)'
        hook = '\tif strings.HasPrefix(name,"scratch:") { return wit.Ok[string,string](scratchCase(strings.TrimPrefix(name,"scratch:"))) }\n'
        source = source.replace('import (', 'import (\n"os"\n"errors"\n"syscall"\n"strconv"', 1)
        source = source.replace(anchor, hook+anchor, 1)+GO
    elif language == 'java':
        anchor = '        String trimmed = Text.trim(name);'
        hook = '        if (name.startsWith("scratch:")) return Result.ok(scratchCase(name.substring(8)));\n'
        source = source.replace(anchor, hook+anchor, 1)
        declaration = 'public final class Capsule implements Bindings.Exports {'
        require(source.count(declaration) == 1, 'scratch-original-class-shape')
        source = source.replace(declaration,
            'public final class Capsule implements Bindings.Exports {'+JAVA, 1)
    elif language == 'dotnet':
        anchor = '        string clean = Text.Trim(name);'
        hook = '        if (name.StartsWith("scratch:", System.StringComparison.Ordinal)) return Result<string,string>.Ok(ScratchCase(name.Substring(8)));\n'
        source = source.replace(anchor, hook+anchor, 1)
        declaration = 'public class ApiExportsImpl : IApiExports\n{'
        if declaration not in source:
            declaration = declaration.replace('\n', '\r\n')
        require(source.count(declaration) == 1, 'scratch-original-class-shape')
        source = source.replace(declaration, declaration+DOTNET, 1)
    else:
        anchor = '    size_t first = name->len, end = 0, offset = 0;'
        hook = '''    if (name->len >= 8 && memcmp(name->ptr, "scratch:", 8) == 0) {
        const char *outcome = scratch_case(name); probe_string_free(name);
        lsf_text_error(value, outcome); return true;
    }
'''
        source = source.replace('#include "lsf/text.h"', '#include "lsf/text.h"\n'+C, 1)
        source = source.replace(anchor, hook+anchor, 1)
    original = before[SOURCES[language]].decode('utf-8')
    require(original.count(anchor) == 1 and source.count(hook) == 1, 'scratch-original-template-shape')
    path.write_bytes(source.encode('utf-8'))
    after = snapshot(app)
    require(set(after) == set(before) and all(after[name] == data for name, data in before.items()
                if name != SOURCES[language]), 'scratch-sdk-profile-or-nonsource-change')
    return app, {'language': language, 'sourceDigest': digest(inventory(after)),
        'fixtureDigest': digest(source.encode()), 'sourcePath': SOURCES[language],
        'cases': list(CASES[language]), 'sdkProfileAndLimitsChanged': False,
        'filesystemGrantsAdded': False, 'compilerExecuted': False, 'signedQualification': 'pending'}


def typescript_project(directory: Path, outside: Path, case: str) -> tuple[Path, dict]:
    """Actual normal npm capture; only the owning compiler may prove refusal."""
    import os
    import shutil
    from tools.typescript_guest.project import create
    from tools import typescript_dependency_authoring as authoring
    from tools.application_dependencies import verify_inputs
    from tools.npm_lock_authoring import create_lock
    from tools.typescript_application_dependencies import resolve
    from tools.rust_capsule_project import ROOT
    operations = {'open': "const file=openSync('lsf-scratch-refusal','r');closeSync(file);",
        'create': "const file=openSync('lsf-scratch-refusal','wx');closeSync(file);unlinkSync('lsf-scratch-refusal');",
        'temp': "const path=mkdtempSync('lsf-scratch-');rmdirSync(path);"}
    require(case in operations, 'scratch-typescript-case')
    require(directory.parent.resolve(strict=True) == outside.parent.resolve(strict=True)
            and ROOT not in outside.parents and outside.parent.resolve(strict=True) != ROOT,
            'scratch-typescript-owned-outside-source')
    app = create(directory, 'greeting')
    sdk = read_file(app/'sdk-lock.json')
    path = app/'src/main.ts';source = read_file(path)
    anchor = b'  greet(name) {'
    require(source.count(anchor) == 1, 'scratch-typescript-template-shape')
    path.write_bytes(b"import {probeScratch} from 'outside-scratch-api';\n"+source.replace(anchor,
        anchor+b"\n    if(name.startsWith('scratch:')) return probeScratch(name);", 1))
    outside.mkdir(mode=0o700)
    package = {'name': 'outside-scratch-api', 'version': '1.0.0', 'type': 'module', 'license': 'Apache-2.0',
        'exports': {'types': './index.d.ts', 'import': './index.mjs'}}
    (outside/'package.json').write_bytes((json.dumps(package, indent=2)+'\n').encode())
    library = ("import {openSync,closeSync,unlinkSync,mkdtempSync,rmdirSync} from 'node:fs';\n"
        +"export function probeScratch(name){"+operations[case]+"return 'scratch|typescript|unexpected-success';}\n").encode()
    (outside/'index.mjs').write_bytes(library)
    (outside/'index.d.ts').write_bytes(b'export function probeScratch(name: string): string;\n')
    authoring.edit(app, 'add', identity='outside-scratch-api', local=outside)
    node = Path(shutil.which('node') or 'missing-node')
    npm = node.parent/'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve()
    native = create_lock(app, node=node, npm=npm)
    candidate = app/'target/scratch.candidate.json';candidate.parent.mkdir(exist_ok=True)
    resolve(app, candidate, node=node, npm=npm)
    authoring.review(app, candidate, digest(read_file(candidate)))
    accepted = verify_inputs(app, 'typescript')
    require(accepted is not None and accepted.lock['selection']['runtimeProfile'] == 'spidermonkey-public-sync-v1',
            'scratch-typescript-original-profile')
    require(not outside.is_symlink() and outside.resolve(strict=True).parent == app.parent.resolve(strict=True),
            'scratch-typescript-removal-scope')
    shutil.rmtree(outside)
    require(read_file(app/'sdk-lock.json') == sdk and verify_inputs(app, 'typescript').lock == accepted.lock,
            'scratch-typescript-sdk-or-offline-closure-change')
    return app, {'language': 'typescript', 'case': case, 'libraryDigest': digest(library),
        'sourceDigest': digest(inventory(authoring.source_files(app))), 'nativeLock': native,
        'acceptedLockDigest': digest(read_file(app/'latent.dependencies.lock.json')),
        'originalOutsideSourceRemoved': True, 'filesystemGrantsAdded': False,
        'compilerRefusal': 'pending', 'runtimeNodeFilesystemClaimed': False}
