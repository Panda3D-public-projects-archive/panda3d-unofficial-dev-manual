# dtool / interrogate / config

`dtool` is Panda3D's foundation layer: the small, dependency-free library that *everything* else in the engine sits on top of. It provides the run-time type system (`TypeHandle`/`TypeRegistry`/`TypedObject`), memory management (`MemoryHook`, deleted chains, pluggable allocators), platform/compiler abstraction (mutex impls, atomics, alignment and branch-hint macros), portable filesystem access (`Filename`, `DSearchPath`, `ExecutionEnvironment`), the PRC configuration system (`ConfigVariable*`, `ConfigPage`, `ConfigPageManager`), and the run-time half of the C++→Python binding machinery (`interrogatedb` + `py_panda`). It is built as a handful of small shared libraries (`libp3dtoolbase`, `libp3dtoolutil`, `libp3dtool`, `libp3interrogatedb`/`libp3prc`) that are linked by `libpanda` and below. Note that the *binding generator itself* (`interrogate` and its `cppparser`) no longer lives in this tree — it was extracted into a standalone repository (see the `interrogatedb` section); only the generated-data runtime stays here.

Repo layout under the cluster (all paths relative to the panda3d repo root):

```
dtool/src/dtoolbase     # type system, memory, atomics, mutexes, platform macros, STL allocators
dtool/src/dtoolutil     # Filename, DSearchPath, ExecutionEnvironment, PandaSystem, streams, DSO loading
dtool/src/prc           # PRC config system + Notify logging + encrypt/native-data helpers
dtool/src/dconfig       # ConfigureFn/ConfigureDef static-init macros
dtool/src/interrogatedb # runtime data structures for C++→Python bindings (py_panda, interrogate_request)
dtool/src/prckeys       # makePrcKey / signPrcFile: PRC trust-level signing tools
dtool/src/parser-inc    # ~195 fake system headers fed to the interrogate parser
```

---

## dtoolbase

**What it is.** The lowest layer of Panda3D — pure platform and language primitives with essentially no dependencies (it does not even depend on `dtoolutil`). It defines the run-time type identification (RTTI) system that the entire engine uses for dynamic casting, factory creation, and Python binding dispatch; the memory-allocation wrapper that lets Panda swap allocators and track usage; cross-platform mutex/atomic/alignment primitives; and a large set of compile-time macros (`INLINE`, `PUBLISHED`, `EXPCL_*`, `LIKELY`/`UNLIKELY`, `ALIGN_16BYTE`, `NODEFAULT`). Almost every `.h` file elsewhere in Panda begins by including `dtoolbase.h`.

**Central abstraction — the type system.** Three classes form the RTTI core:

- `TypeHandle` (`dtool/src/dtoolbase/typeHandle.h`) — a `final` value type wrapping a single `int _index` into the registry. Comparison and hashing are integer-cheap. `none()` is index 0, `invalid()` is `-1`. The default constructor deliberately does nothing because a `TypeHandle` is frequently a `static` member and "must do nothing, because we can't guarantee ordering of static initializers" (comment at `typeHandle.h:95`). It also carries per-type memory accounting (`inc_memory_usage`/`dec_memory_usage` over `MemoryClass`) and, in Python builds, the link to a `PyTypeObject` (`get_python_type`, `wrap_python`).
- `TypeRegistry` (`dtool/src/dtoolbase/typeRegistry.h`) — the single global table (`TypeRegistry::ptr()`), guarded by a `static MutexImpl _lock`. It maps names↔handles, records derivations (`record_derivation`), answers inheritance queries (`is_derived_from`, `get_parent_towards`, `get_parent_class`), and supports `register_dynamic_type` for Python-defined subclasses. Inheritance answers are lazily recomputed: `_derivations_fresh` / `rebuild_derivations()`. The nodes themselves live in `TypeRegistryNode` (not shown in the header list but referenced throughout).
- `TypedObject` (`dtool/src/dtoolbase/typedObject.h`) — the abstract base (`: public MemoryBase`) for any class wanting *virtual* type identification. It declares the pure virtuals `get_type()` and `force_init_type()`, and supplies `is_of_type()` / `is_exact_type()` / `as_typed_object()`. Interrogate-generated code calls `as_typed_object()` rather than a raw cast so that multiply-inheriting classes can disambiguate.

The canonical boilerplate (the exact pattern you must replicate when adding a class — see the long comment block at the top of `typedObject.h`) is `static get_class_type()` / `static init_type()` / `virtual get_type()` / `virtual force_init_type()` plus a `static TypeHandle _type_handle;` member defined in the `.cxx`. The `register_type(...)` helper family (`dtool/src/dtoolbase/register_type.h`, up to 4 parents) hides the `TypeRegistry::register_type` + `record_derivation` calls; `register_type.h` also pre-registers `TypeHandle`s for builtin types (`int_type_handle`, `float_type_handle`, `string_type_handle`, the `pvector`/`pmap`/`pset` containers, etc.) via `init_system_type_handles()`, and provides the `get_type_handle(type)` / `do_init_type(type)` macros used inside templates.

**Memory management.**
- `MemoryHook` (`dtool/src/dtoolbase/memoryHook.h`, `.cxx`) — virtual wrapper around whichever malloc Panda was built with. The `PANDA_MALLOC_*` / `PANDA_FREE_*` macros vector through it (except in production builds). Selectable backends are chosen by `USE_MEMORY_*` macros in `dtoolbase.h` (`mimalloc`, `dlmalloc`, `ptmalloc2`, or plain system malloc; sources `dlmalloc_src.cxx`, `ptmalloc2_smp_src.cxx`). It tracks `_total_heap_single_size`/`_total_heap_array_size`/etc. as `patomic<size_t>` and can fire `overflow_heap_size()` past a threshold. `MemoryHook::alloc_fail()` is the central out-of-memory hook.
- `MemoryBase` (`memoryBase.h`) — marker base whose `operator new`/`delete` route through the hook; `TypedObject` derives from it.
- `DeletedChain<T>` / `DeletedBufferChain` (`deletedChain.h`, `deletedBufferChain.h`) — an intrusive free-list allocator. The `ALLOC_DELETED_CHAIN(Type)` macro stamps a class with `operator new`/`delete` that recycle freed same-sized blocks instead of returning them to the heap, which is a large win for the many short-lived nodes Panda churns through (RenderState, TransformState, etc.). It is gated by `USE_DELETED_CHAIN`; when `DO_MEMORY_USAGE` is defined instead, the macro expands to per-`TypeHandle` accounting so leaks can be attributed by type. Caveat baked into the source: the chain "won't work in the presence of polymorphism…unless you instantiate a DeletedChain for *every* kind of derived class," and if the compiler fails to unify the static chain pointer you can leak — hence the `ALLOC_DELETED_CHAIN_DECL`/`_DEF` variant (`deletedChain.h:98-123`).
- `NeverFreeMemory` (`neverFreeMemory.h`) — bump allocator for objects that live for the whole process (e.g. `ConfigVariableCore`).

**Platform / concurrency.** `mutexImpl.h` typedefs `MutexImpl` to one of `MutexPosixImpl`, `MutexWin32Impl`, `MutexSpinlockImpl`, or `MutexDummyImpl` (no-op for single-threaded builds) based on `selectThreadImpl.h`. `patomic.h`/`.cxx`/`.I` provides `patomic<T>` (Panda's `std::atomic` shim, with a non-atomic fallback when threads are disabled). `dtool_platform.h` carries OS/arch detection; `dtoolbase.h` carries compiler-feature macros (`LIKELY`/`UNLIKELY` → `__builtin_expect`; `NODEFAULT` → `__builtin_unreachable`/`__assume`; `ASSUME_ALIGNED`, `RETURNS_ALIGNED`, `ALIGN_16BYTE`, `MEMORY_HOOK_ALIGNMENT` = 8/16/32 by config). The STL-allocator-aware containers `pvector`/`pmap`/`pset`/`plist`/`pdeque` (`pvector.h` etc., built on `pallocator.h`) route container memory through the hook too.

**How it plugs in.** Universally. Any subsystem that needs dynamic typing inherits `TypedObject`; any class wanting fast alloc uses `ALLOC_DELETED_CHAIN`; threading code in `panda/src/pipeline` builds its `Mutex`/`ConditionVar` on these impls. There is no inbound dependency from dtoolbase on anything above it.

**Where to start.** To touch the type system, read `typeRegistry.cxx` and `typedObject.h`'s doc block. To touch allocation, read `memoryHook.cxx` and `deletedChain.I`. To add a platform/compiler macro, edit `dtoolbase.h`. To understand the static-init contract, read `register_type.h`.

**Gotchas / maintainer notes.** Static-initialization order is the perennial hazard here. `TypeHandle`'s do-nothing default ctor exists precisely so a type registered by one translation unit's static init isn't clobbered by another's. The community has hit this directly: *"`init_memory_hook()` not (necessarily) called before static initialization"* — issue [panda3d#539](https://github.com/panda3d/panda3d/issues/539) proposes making `MemoryHook`'s constructor `constexpr` (which the current header does: `constexpr MemoryHook() = default`) so the global hook is constant-initialized before any other static runs. A related real-world breakage when building without Python: commit `6e8cb98861` (*"dtoolbase: fix compile errors with --no-python"*) touched `dtoolbase.h` and `typeHandle.cxx`. Config var: none registered directly in `dtoolbase` (it has no PRC dependency); memory behavior is selected at *compile* time via the `USE_MEMORY_*` defines.

---

## dtoolutil

**What it is.** Portable filesystem and process-environment utilities layered on `dtoolbase`. This is where Panda's path abstraction (`Filename`), search-path resolution (`DSearchPath`), process/environment introspection (`ExecutionEnvironment`), build-feature querying (`PandaSystem`), text encoding, and the custom `std::streambuf` family live. It is the bridge between the OS and the higher-level virtual file system.

**Central abstraction — `Filename`** (`dtool/src/dtoolutil/filename.h`, `.cxx` ~90 KB, `.I`, plus the Python extension `filename_ext.cxx` and the macOS helper `filename_assist.mm`). A `Filename` stores a path in Panda's *internal* convention — always forward-slash, Unix-like — and knows how to translate to/from the local OS convention (`from_os_specific()`, `to_os_specific()`). It parses components (`get_dirname`, `get_basename`, `get_basename_wo_extension`, `get_extension`, `get_fullpath`), normalizes (`make_absolute`, `make_canonical`, `standardize`), and carries a `Type`/`Flags` bitfield distinguishing text vs binary vs DSO vs executable files (this affects newline translation and platform extension fix-ups). **Critical design point, stated in the header:** the I/O methods on `Filename` (`exists()`, `open_read()`, `open_write()`, `unlink()`, …) "directly interface with the operating system and are **not** aware of Panda's virtual file system. To interact with the VFS, use the methods on `VirtualFileSystem` instead" (`filename.h:40-43`). `Filename` is the seam: code that wants real-disk access calls `Filename`; code that wants mounted/multifile/ramdisk assets goes through `panda/src/express/virtualFileSystem`.

**Other key classes.**
- `DSearchPath` (`dSearchPath.h`, `.cxx`) — an ordered list of directories; `find_file(Filename)` returns the first hit, `find_all_files()` returns a `DSearchPath::Results`. This underlies model/texture/PRC lookup everywhere.
- `ExecutionEnvironment` (`executionEnvironment.h`, `.cxx`) — singleton exposing `get_environment_variable`/`set_environment_variable`, `expand_string` (`$VAR` substitution used in PRC values), `get_binary_name`, `get_dtool_name`, `get_cwd`, and the args vector. It is the source of the `MAIN_DIR` and other vars the config loader expands.
- `PandaSystem` (`pandaSystem.h`, `.cxx`) — singleton reporting build configuration: `get_version_string()`, `has_system("audio")`, `is_threading_supported()`, etc. This is the runtime feature-detection API.
- The stream family: `PandaFileStream`/`IFileStream`/`OFileStream` over `PandaFileStreamBuf` (`pandaFileStream.h`, `pandaFileStreamBuf.h`/`.cxx` ~23 KB) gives `Filename`-aware, newline-translating, optionally-64-bit file I/O; `LineStream`/`LineStreamBuf` (`lineStream.h`) is an `ostream` that buffers whole lines for the logging system; `pfstream`/`pfstreamBuf` runs a subprocess and exposes its stdio as a stream.
- Support: `GlobPattern` (`globPattern.h`) wildcard matching (`*`, `?`, `[...]`), `load_dso.h`/`.cxx` (`dlopen`/`LoadLibrary` wrapper), `string_utils.h`, `TextEncoder`/`StringDecoder`/`unicodeLatinMap` (encoding), `panda_getopt*` (portable getopt), `small_vector.h`, `preprocess_argv` (Windows wide-arg handling).

**How it plugs in.** `Filename` and `DSearchPath` are the asset-loading vocabulary of the whole engine — loaders, the model cache, the texture pool, and PRC discovery all speak them. `ExecutionEnvironment` feeds `ConfigPageManager` (PRC dir resolution and `$VAR` expansion). `PandaSystem` is queried by Python startup and tools. The streams back both logging (`Notify` → `LineStream`) and on-disk reads.

**Where to start.** For path/IO bugs, `filename.cxx` (and `filename_ext.cxx` for the Python `os.PathLike` glue). For search/resolution, `dSearchPath.cxx`. For "why won't my env var expand", `executionEnvironment.cxx::expand_string`. For newline/encoding surprises, `pandaFileStreamBuf.cxx` and `textEncoder.cxx`.

**Gotchas / community notes.** The number-one footgun is forgetting the VFS/real-FS split above. The community guidance is consistently *"Use `Filename` objects — then you can do `path.to_os_specific()`"* ([Discord](https://discord.com/channels/524691714909274162/533048345791299634/990104391128350770)) and to always store forward-slashed paths so code is Windows-portable — a recurring PR review comment, e.g. [panda3d#612](https://github.com/panda3d/panda3d/pull/612) ("changed to use forward-slashed paths instead of `os.path.join`, so it can work on Windows"). Code that resolves a `Filename` against the VFS and then hands it to a raw OS API is a known bug pattern; see [panda3d#1781](https://github.com/panda3d/panda3d/pull/1781) which had to teach Windows icon/cursor loading to go through the VFS rather than `Filename` directly. **Config vars:** `config_dtoolutil.cxx` is intentionally minimal — it only calls `Filename::init_type()` / `PandaSystem::init_type()` from `init_libdtoolutil()` and registers no PRC variables (text-encoding defaults etc. live in higher layers). The companion `config_dtoolutil.N` is an *interrogate* directive file (`forcetype std::ifstream`, etc.) telling the binding generator how to treat std stream types.

---

## prc

**What it is.** The PRC ("Panda Runtime Config", historically "Panda Resource Configuration") system — Panda's answer to ini/registry/env config. It decouples engine tuning from code: `*.prc` text files (and programmatic pages) declare `name value` lines that drive behavior at runtime, discoverable on a search path and reloadable. This directory also houses the `Notify` logging framework (because log categories are themselves config-driven), plus a few numeric/stream helpers (`nativeNumericData`, `encryptStream`, `bigEndian`/`littleEndian`).

**The data model (four layers).**
- `ConfigDeclaration` (`configDeclaration.h`, `.cxx`) — one `name value` line from one page. It lazily parses its value into words and caches typed views (`get_string_word`, `get_bool_word`, `get_int_word`, `get_int64_word`, `get_double_word`, with `get_num_words`).
- `ConfigPage` (`configPage.h`, `.cxx`) — an ordered set of declarations representing a single `.prc` file or a programmatic page. Carries a sort order, a trust level (set by signature verification), and a signature. Two special pages exist: the *default* page (compiled-in defaults) and the *local* page (runtime overrides via `make_local_value`).
- `ConfigVariableCore` (`configVariableCore.h`, `.cxx`) — the *shared, never-destructed* internal record for a given variable name. It aggregates declarations from *all* pages, partitions them into trusted/untrusted/unique lists, holds the default value, value type, description, flags (trust level/closed/dynamic), and a `_local_value`. Created via `make()`; allocated from `NeverFreeMemory`. The comment is explicit: "Once created, these objects are never destructed" (`configVariableCore.h:31-34`).
- `ConfigPageManager` (`configPageManager.h`, `.cxx` ~25 KB) — the singleton (`get_global_ptr()`) that discovers and orders pages. `load_implicit_pages()` scans the PRC search path; pages are kept in sorted order (`sort_pages`), and `mark_unsorted()`/`_global_modified` drive cache invalidation so that a newly loaded or edited page is reflected by already-constructed `ConfigVariable`s.

**The public typed wrappers** are thin and cheap to construct anywhere (including as `static` globals):
- `ConfigFlags` (`configFlags.h`) — shared enum scope: `ValueType` (`VT_bool`, `VT_int`, `VT_double`, `VT_string`, `VT_filename`, `VT_enum`, `VT_search_path`, `VT_int64`, `VT_color`, `VT_list`) and `VariableFlags` (the bottom 12 bits are a *trust level*, plus `F_open`/`F_closed`/`F_dynamic`/`F_dconfig`). It also owns the global modification counter used for value-cache validation.
- `ConfigVariableBase` → `ConfigVariable` (`configVariable.h`) → the concrete `ConfigVariableBool`/`ConfigVariableInt`/`ConfigVariableInt64`/`ConfigVariableDouble`/`ConfigVariableString`/`ConfigVariableFilename`/`ConfigVariableEnum<T>`/`ConfigVariableList`/`ConfigVariableSearchPath` (the full set of `configVariable*.h` files in this directory). Each wraps a `ConfigVariableCore*` and does type-specific coercion. (`VT_color` exists in the `ValueType` enum but has no dedicated class in this directory; color vars are handled higher up.) `ConfigVariableManager` (`configVariableManager.h`) is the registry of all known cores (for tools that list variables).

**Declaring a config variable** (the pattern you copy): construct a file-static typed variable with name, default, and a `PRC_DESC(...)` description. Example from this very directory (`config_prc.cxx:25`):

```cpp
ALIGN_16BYTE ConfigVariableBool assert_abort
("assert-abort", false,
 PRC_DESC("Set this true to trigger a core dump and/or stack trace when the first assertion fails"));
```

**How discovery works** (`configPageManager.cxx`). On first need it scans, in order, the dirs named by the compiled-in `PRC_DIR_ENVVARS`/`PRC_PATH_ENVVARS`/`PRC_PATH2_ENVVARS` environment variables (typically `PRC_DIR`, `PRC_PATH`), then `DEFAULT_PRC_DIR` if the path was otherwise empty, matching files against `PRC_PATTERNS` (e.g. `*.prc`), `PRC_ENCRYPTED_PATTERNS`, and `PRC_EXECUTABLE_PATTERNS`. A `<auto>` prefix on `PRC_DIR` triggers `scan_auto_prc_dir()`, which walks up from the executable to find a config tree. `MAIN_DIR` is published into `ExecutionEnvironment` so `.prc` values can reference it. The trust level on a page is `0` unless it was signed (see `prckeys`); untrusted pages cannot raise the value of "closed"/trusted variables.

**Notify (logging).** `Notify`/`NotifyCategory`/`NotifySeverity`/`NotifyCategoryProxy` (`notifyCategory.h`, `notifySeverity.h`, `pnotify.h`) live here because each category's severity is itself a config variable (`notify-level-<category>`). `NotifyCategoryDef(prc, "")` in `config_prc.cxx` shows the registration. `androidLogStream`/`emscriptenLogStream` route Notify to platform log sinks.

**How it plugs in.** Every subsystem that wants a tunable declares a `ConfigVariable*` at file scope; reading it is a near-free cached lookup. The scene graph, the GSG, audio, collision, etc. all gate features on PRC vars. `Notify` is the engine-wide logging spine. Python's `loadPrcFileData()` / `ConfigVariableBool` proxies (via `configVariable_ext.cxx`) expose all of this to script.

**Where to start.** To change discovery/ordering, `configPageManager.cxx` (`load_implicit_pages`, `sort_pages`, `scan_auto_prc_dir`). To change value parsing/coercion, `configDeclaration.cxx` and the relevant `configVariableXxx.cxx`. To add a new value type, mirror an existing `configVariableInt.*` triple and add a `VT_*` in `configFlags.h`. To debug "my var has the wrong value", dump `ConfigVariableCore::write()` which lists every contributing declaration and its page/trust.

**Gotchas / maintainer notes.** Static-init order bites PRC just as hard as dtoolbase. The fix commit `0ae9a55bdb` (*"fix static-init order issue"*) moved initialization logic out of `config_prc.cxx`/`.h` and into `configPageManager.cxx` (`config_initialized()`), because a `ConfigVariable` constructed during another library's static init could otherwise touch a not-yet-constructed `ConfigPageManager`. Practical user-facing footguns the community hits repeatedly: a custom `Config.prc` being silently ignored or overridden because page **sort order / trust** put another page on top ([discourse t/4383 "[solved] prc being ignored"](https://discourse.panda3d.org/t/4383)), and the fact that *many* options (window/graphics) are only read once at startup so setting them after `ShowBase` does nothing (same thread; [t/6763](https://discourse.panda3d.org/t/6763)). **Config vars defined here:** `assert-abort` (`config_prc.cxx`). Most engine vars are defined in their own subsystems' `config_*.cxx`, not here.

---

## interrogatedb

**What it is.** The *runtime* support library for Panda's C++→Python (and historically C++→Scheme/other) bindings. It does **not** generate bindings — it holds the data structures and the Python-C-API glue that the generated wrapper code and the loaded `.in` databases plug into at static-init time. Two concerns live here: (1) the C registration interface (`interrogate_request.h`) by which each compiled module hands its metadata to the global interrogate database, and (2) `py_panda` — the layer that makes a Panda C++ object look like a Python object.

**Key files.**
- `interrogate_request.h` — a deliberately C-only (`extern "C"`) interface so it can be called from any module's static init. `interrogate_request_module(InterrogateModuleDef *)` registers a library's metadata; `interrogate_request_database(const char *)` loads a `.in` database file. `InterrogateModuleDef` (`interrogate_request.h:52`) carries `file_identifier`, `library_name`, `library_hash_name`, `module_name`, `database_filename`, the `unique_names` table (`InterrogateUniqueNameDef`), and the function-pointer table `fptrs`/`num_fptrs` with `first_index`/`next_index` offsets that tie generated wrappers back to database entries.
- `py_panda.h` / `py_panda.I` — the heart of the Python runtime. `Dtool_PyInstDef` is the common header struct embedded in *every* wrapped Panda instance: it stores `_My_Type` (pointer to the type's `Dtool_PyTypedObject`), `_ptr_to_object` (the C++ pointer), a `_signature` (`PY_PANDA_SIGNATURE` = `0xbeaf`, used by `DtoolInstance_Check` to recognize a Panda object in O(1)), and the `_memory_rules`/`_is_const` flags governing ownership and const-correctness. `Dtool_PyTypedObject` extends `PyTypeObject` with the bridging `TypeHandle _type` plus the upcast/downcast/coerce function slots (`UpcastFunction`, `WrapFunction`, `CoerceFunction`, `ModuleClassInitFunction`). This is what lets a Python reference to a `NodePath` correctly upcast/downcast across multiple inheritance and respect refcount ownership.
- `py_compat.h` — the Python 2/3 (and across-3.x) compatibility shims; it is the file that `#include`s `Python.h`.

**How it plugs in.** At process start, each generated module (`libpandaexpress`, `libpanda`, …) runs static initializers that call `interrogate_request_module`; the wrappers register their `Dtool_PyTypedObject`s and link them to `TypeRegistry` entries via `TypeHandle`/`TypeRegistry::record_python_type` (declared back in `dtoolbase`). Thereafter, when Python code touches a Panda object, `py_panda` uses the type system to wrap/unwrap pointers. So `interrogatedb` is the meeting point of the dtoolbase type system and CPython.

**Relationship to the `interrogate` tool (important).** The binding *generator* — the `interrogate` executable and the `cppparser` C++-AST parser it uses — **used to live in `dtool/src/interrogate` and `dtool/src/cppparser`, but was deleted from this repository** and now lives in a standalone project. The removal is commit `8d2407d553` ("Delete cppparser and interrogate from tree — These tools now live in https://github.com/panda3d/interrogate/, see also #1074"). That is why you will not find an `interrogate.cxx` anywhere under `dtool/src` in a current checkout; only the runtime (`interrogatedb`) and the parser stubs (`parser-inc`) remain. The build pipeline is: `interrogate` (external tool) parses the headers (using `parser-inc` fakes) → emits per-module `.in` databases and `*_igate.cxx` wrapper sources → those are compiled and, at runtime, register themselves through `interrogate_request.h` and wrap objects via `py_panda.h`.

**Where to start.** To understand object wrapping/ownership bugs, read `py_panda.h`/`py_panda.I` (`Dtool_PyInstDef`, the `_memory_rules` handling, `DtoolInstance_*` macros). To understand module registration, read `interrogate_request.h`. To actually change *how bindings are generated*, you must work in the separate [panda3d/interrogate](https://github.com/panda3d/interrogate/) repo, not here.

**Gotchas / maintainer notes.** The community is candid that this is the least-documented corner of Panda: *"interrogate is a poorly-documented system (it's not even documented well internally, unlike most of the rest of Panda)"* — and that downcasting through it is deliberately limited: *"We don't have an interface for you to do an on-demand downcast like that … it would be dangerous"* ([discourse t/8851](https://discourse.panda3d.org/t/8851), [t/1335](https://discourse.panda3d.org/t/1335)). There has been active work to shrink the runtime tables: PR [panda3d#439](https://github.com/panda3d/panda3d/pull/439) ("Remove Python type tables from interrogatedb") is a step toward issue [#387](https://github.com/panda3d/panda3d/issues/387). Static-init ordering between `MemoryHook`, `TypeRegistry`, and the interrogate registration is a known sharp edge ([#539](https://github.com/panda3d/panda3d/issues/539)). For "is pybind11 better?" discussions and the rationale for keeping the bespoke generator (performance), see [#1210](https://github.com/panda3d/panda3d/issues/1210).

---

## parser-inc

**What it is.** A directory of roughly 195 *fake* header files that stand in for real system and third-party headers when the `interrogate`/`cppparser` tool parses Panda's source. They are **never compiled** — only parsed. The header of each file says so explicitly (from `dtool/src/parser-inc/vector`): "This file, and all the other files in this directory, aren't intended to be compiled — they're just parsed by CPPParser (and interrogate) in lieu of the actual system headers, to generate the interrogate database."

**Why it exists.** Interrogate's bundled C++ parser is not a full compiler and must not choke on the wildly compiler- and platform-specific contents of real STL/system headers (`<vector>`, `<map>`, `<atomic>`, `<memory>`, libc headers, and third-party SDK headers like `Cg/`, `btBulletDynamicsCommon.h`, `avcodec.h`, `Eigen/`). Each stub provides just the minimal declarations interrogate needs to resolve types and member signatures. For example, `parser-inc/vector` declares a bare `template<class T, class Allocator> class vector` with only the public typedefs (`value_type`, `iterator`, `size_type`, …) and no implementation; `parser-inc/cstdint` simply re-includes `<stdint.h>`; many entries (e.g. third-party SDK headers) are essentially empty so the include resolves to nothing. This both keeps parsing portable across build machines and keeps STL/external internals *out* of the generated Python bindings.

**How it plugs in.** Only the binding-generation build step uses this directory: `interrogate` is invoked with this directory on its include path *ahead of* the real system include paths, so `#include <vector>` resolves to the stub. The contents are coupled to whatever interrogate needs to see — when a class newly exposes, say, a `std::unordered_map` member to Python, the corresponding stub here may need a matching declaration. The `forcetype`/`forbidden` directives in the various `config_*.N` files (e.g. `dtoolutil/config_dtoolutil.N` forcing `std::ifstream` etc.) work alongside these stubs to steer the generator.

**Where to start.** If interrogate fails to parse a header or generates a wrapper for a type that should be opaque, look here first: either a stub is missing a member/typedef interrogate now needs, or a real header is leaking in because no stub shadows it. Add or extend the matching stub (copy the style of `parser-inc/vector`).

**Gotchas / maintainer notes.** These stubs are intentionally *incomplete*; do not treat them as documentation of real STL semantics. They drift relative to the actual standard library, so a build that suddenly fails interrogation after a compiler/STL upgrade often needs a stub update rather than a code change. Because the generator itself now lives in the external [interrogate repo](https://github.com/panda3d/interrogate/), this directory is the remaining in-tree coupling point between Panda's headers and that tool. No config variables.

---

## prckeys

**What it is.** The small toolset that implements PRC **trust** — RSA signing and verification of `.prc` config pages, so that a deployment can mark certain pages (and the "closed"/trusted variables they set) as authoritative and reject tampered or third-party config. It is the security half of the `prc` directory's `trust_level` concept.

**Key files.**
- `makePrcKey.cxx` — a command-line tool that generates RSA key pairs (using OpenSSL: `<openssl/rsa.h>`, `pem.h`, `rand.h`) and emits a C header of *public* keys that gets compiled into the engine (`PRC_PUBLIC_KEYS_INCLUDE`). It uses `prcKeyRegistry.h` (which lives in `dtool/src/prc/`, not here), `Filename`, `panda_getopt`, and `preprocess_argv` from the lower layers. Each generated key gets a number and optional pass phrase.
- `signPrcFile_src.cxx` — the signature-verification logic compiled into the engine. When `ConfigPageManager` loads a page that carries a signature, this code (together with `PrcKeyRegistry`, `dtool/src/prc/prcKeyRegistry.h`, which `configPageManager.cxx` includes) checks it against the compiled-in public keys and, on success, assigns the page a positive `trust_level` (recall `ConfigPage::get_trust_level()` and the `F_trust_level_mask` bits in `configFlags.h`). Untrusted pages get trust level 0 and cannot override "closed" variables.

**How it plugs in.** Build-time you run `makePrcKey` to bake public keys into the engine; deploy-time you sign sensitive `.prc` files with the matching private key; run-time `ConfigPageManager` → `signPrcFile`-derived code validates them. The whole feature is OpenSSL-gated (it compiles only when SSL support is available).

**Where to start.** To change the trust model or signature format, read `signPrcFile_src.cxx` and trace `get_trust_level()` usage in `configPage.cxx`/`configPageManager.cxx`. To change key generation/CLI, read `makePrcKey.cxx`.

**Gotchas / maintainer notes.** Trust is opt-in and only meaningful if (a) you actually compiled in public keys and (b) the variables you care about are declared "closed" so untrusted pages can't lower them. For most open-source/desktop users this subsystem is dormant (all pages trust level 0). No PRC config variables of its own; behavior is driven entirely by compiled-in keys and per-page signatures.

---

## dconfig

**What it is.** A single header (`dtool/src/dconfig/dconfig.h`) of preprocessor macros that implement Panda's per-library **static-initialization hook** — the mechanism by which every Panda library runs a block of code (chiefly `init_type()` calls and `ConfigVariable` setup) exactly once when it is loaded. It is the connective tissue that wires the type system and config system into module load.

**What it provides.** Three macro families, each in a legacy (`Configure*`) and a current `DTool`-prefixed form (the prefix exists because a bare `Configure` symbol collided with DirectX 9 headers — see the comment at `dconfig.h:24-27`):
- `DToolConfigureDecl(name, expcl, exptp)` — placed in the `config_*.h`; currently expands to nothing (a vestige kept for source compatibility).
- `DToolConfigureDef(name)` — placed in the `config_*.cxx`; defines a tiny `StaticInitializer_<name>` class and a file-static instance of it, so its constructor runs at static-init time.
- `DToolConfigureFn(name)` — defines the body of that constructor; this is where a library puts its `Foo::init_type(); Bar::init_type(); …` calls.

So the idiom (referenced in `typedObject.h`'s example) is: each subsystem has a `config_<pkg>.cxx` containing `ConfigureFn(config_<pkg>) { ClassA::init_type(); ClassB::init_type(); … }`, guaranteeing every `TypeHandle` is registered before use.

**How it plugs in.** Used by essentially every `config_*.cxx` across the whole engine (panda, pandatool, direct). It depends only on `dtoolbase.h` and `notifyCategoryProxy.h`. It is the entry point that turns "library loaded" into "types registered + config initialized."

**Where to start.** Read `dconfig.h` top-to-bottom (it is ~65 lines). To see it in practice, read any `config_*.cxx` `ConfigureFn` block (e.g. `dtool/src/prc/config_prc.cxx`).

**Gotchas / maintainer notes.** The header itself flags the long-term plan: *"These macros may eventually be phased out in favor of a simpler interface that does not require static init"* (`dconfig.h:21-22`), precisely because static-init order is fragile (see the dtoolbase/prc notes above and issue [#539](https://github.com/panda3d/panda3d/issues/539)). Until then, the rule is: do real initialization work in the `ConfigureFn` body, and never assume two libraries' `ConfigureFn`s run in a particular order. No config variables; this directory *enables* the config system rather than configuring anything.

---

## Where to start (this cluster)

A new contributor should read in this order:

1. **`dtool/src/dtoolbase/typedObject.h`** and **`typeHandle.h`** — the doc comments here are the single best explanation of Panda's RTTI/static-init contract; almost every class you'll ever touch follows this pattern. Then skim **`register_type.h`** for the helper macros.
2. **`dtool/src/dtoolbase/dtoolbase.h`** — the master macro/platform header; understand `INLINE`, `PUBLISHED`, `EXPCL_*`, the `USE_MEMORY_*` selection, and `MEMORY_HOOK_ALIGNMENT`. Pair with **`memoryHook.h`** and **`deletedChain.h`** to understand allocation.
3. **`dtool/src/dtoolutil/filename.h`** — internalize the forward-slash internal convention and the *VFS vs real-FS* split (the most common source of cross-platform bugs).
4. **`dtool/src/prc/configFlags.h` → `configVariable.h` → `configVariableCore.h` → `configPageManager.h`** — read in that order to see a config var go from a one-line file-static declaration down to page discovery; `config_prc.cxx` is a 28-line worked example.
5. **`dtool/src/dconfig/dconfig.h`** — short, and explains how all the above gets initialized at module load.
6. **`dtool/src/interrogatedb/py_panda.h`** — only when you need to understand C++↔Python object wrapping; remember the *generator* itself is now the external [panda3d/interrogate](https://github.com/panda3d/interrogate/) repo, with `parser-inc` as the remaining in-tree coupling.

Two cross-cutting hazards to keep in mind everywhere in this cluster: **static-initialization order** (handles, the memory hook, and the config page manager must all tolerate being touched in any order — the recurring class of bug behind commits `0ae9a55bdb`, `6e8cb98861` and issue #539) and the **VFS/real-filesystem boundary** that `Filename` deliberately does not cross.
