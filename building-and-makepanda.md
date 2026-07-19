# Building Panda3D (makepanda) #

This chapter explains **how Panda3D is built** — the `makepanda` build system,
how it decides what ends up in which binary, how the C++→Python bindings
(interrogate) are generated, and how third-party libraries are integrated. It is
aimed at someone who needs to *change* the build: add a subsystem, wire in a new
library, or debug why a build won't link.

Panda has **two** build systems. `makepanda` (`makepanda/makepanda.py` +
`makepanda/makepandacore.py`) is the historical, self-contained one — it needs
nothing but a C++ compiler and Python, drives the whole build itself, and is
what the official wheels ship from. A newer **CMake** build lives in
`CMakeLists.txt` + `cmake/`. This chapter documents `makepanda`, because it is
still the reference for understanding how the engine is assembled — but note the
direction of travel: CMake is the intended replacement. As the maintainers put
it, "makepanda isn't caught up with some of the latest changes so if you do want
to build it, use cmake" (maxwell175), and there is an open issue (#1310) to
"Remove makepanda backend" while keeping a thin makepanda *frontend* wrapping
CMake so existing workflows don't break (Moguri). Where the two disagree, the
`CMakeLists.txt` in each `panda/src/<X>/` directory is the cleaner statement of
the same intent. The CMake build is documented in its own chapter —
**[Building Panda3D (CMake)](building-cmake.md)** — including a
makepanda-flag → CMake-variable translation table.

**Why makepanda exists at all.** It was written by Josh Yelon to replace the
older, powerful-but-baffling `ppremake` system with something a newcomer could
run. David Rose (drwr, Panda's original architect) summed up the trade-off:
ppremake "is designed to be extremely flexible… however, it is also
unfortunately poorly documented and quite confusing… Josh implemented the
makepanda system as part of the effort to make Panda easier to build… It's
marvelously self-contained… however, it's not as powerful." The self-contained
part is the whole point: "you can run Panda3D straight from the 'built' directory
that makepanda generates, without having to install Panda3D system-wide" (rdb),
and the source packages bundle "everything that I can legally include… even
python itself… the only thing missing is the compiler and the C runtime"
(Josh_Yelon). That philosophy is why so much (ENet, the parser-inc stubs, the
bison output) lives *in the tree*.

Throughout, citations are `makepanda.py:LINE` / `makepandacore.py:LINE` against
the tree this was derived from (the 1.11 line); line numbers drift, so grep the
named function if they don't match your checkout.

---

## The mental model: a target graph, not a directory walk

The single most important thing to internalize: **the build is a hand-wired
target graph, not a directory-driven convention.** `makepanda.py` is one long
script that calls `TargetAdd(<output>, input=<...>, opts=[...])` thousands of
times to declare "this output is built from these inputs with these options."
`makepandacore.py` holds the machinery: the package registry, the global
per-package include/lib lists, `TargetAdd` itself, and the compiler-command
builders.

The `# DIRECTORY: panda/src/<X>` lines scattered through `makepanda.py` (e.g.
`makepanda.py:4437`) are **plain comment section-markers with no parsing
significance.** What actually decides which object lands in which binary is the
explicit `TargetAdd(<binary>, input=<obj>)` wiring — nothing else. Proof: the
`nativenet` subsystem's object is routed *into* `libpanda.dll`
(`makepanda.py:4285`) while the `enet` subsystem's object — same
"one directory under `panda/src/`" convention — is routed into a *separate*
`libp3enet.dll` (`makepanda.py:4459`). The directory only influences *where the
sources are found* and which headers get published; the destination binary is
whatever name you pass to `TargetAdd`.

So there is **no tag system that magically sorts objects into binaries.** The
"tags" (OPTS) only control *compiler flags and which library's headers/libs are
on the command line*. Placement is manual wiring.

---

## `TargetAdd` — declaring an output

Signature (`makepandacore.py:3830`):

```python
def TargetAdd(target, dummy=0, opts=[], input=[], dep=[], ipath=None, winrc=None, pyabi=None):
```

The `dummy=0` positional guard forces everything after `target` to be passed by
keyword — a bare positional trips `exit("Syntax error in TargetAdd ...")`.

**The kind of output is decided purely from the target's file extension**, not
from any argument. `TargetAdd` resolves the name through
`CalcLocation` (`makepanda.py:3592-3669`), which maps the extension to an output
path (and thereby its kind), platform-branched. The extension is a *logical*
one — `.dll` does **not** mean a Windows DLL; it means "a shared library,"
spelled per platform:

| logical ext | Windows | macOS | Linux |
|---|---|---|---|
| `.obj` | `built/tmp/<fn>.obj` | `built/tmp/<fn>.o` | `built/tmp/<fn>.o` |
| `.dll` | `built/bin/<fn>.dll` | `built/lib/<fn>.dylib` | `built/lib/<fn>.so` |
| `.lib` | `built/lib/<fn>.lib` | `built/lib/<fn>.a` | `built/lib/<fn>.a` |
| `.exe` | `built/bin/<fn>.exe` | `built/bin/<fn>` | `built/bin/<fn>` |
| `.pyd` | `built/panda3d/<name><suffix>` | *(same)* | *(same)* |
| `.in` | `built/pandac/input/<fn>.in` | *(same)* | *(same)* |

The suffix classes themselves are `SUFFIX_INC` / `SUFFIX_DLL` / `SUFFIX_LIB` at
`makepandacore.py:25-27`. The original (pre-translation) extension is saved and
later dispatched by `CompileAnything` (`makepanda.py:2344`) to the right builder:
`.lib`→`CompileLib`, `.dll`/`.pyd`/`.exe`→`CompileLink`, `.in`→`CompileIgate`,
`.obj`-from-`.cxx`→`CompileCxx`, `.obj`-from-`.in`→`CompileImod`.

**`input=`** accumulates the things that go *into* the output: object files,
lower-level library targets (`.dll`/`.lib`), interrogate databases (`.in`), and
source files. Two subtleties (`makepandacore.py:3863-3907`):

- A C/C++ **source** input has its `#include` graph scanned and folded into the
  target's dependencies, so editing a header triggers the right rebuilds.
- A **`.dll`** input is deliberately *not* added as a rebuild-dependency, so that
  merely rebuilding a lower library does not force every downstream binary to
  relink.

**`TargetAdd` is cumulative.** A target is created once and keyed in a table;
repeated `TargetAdd` calls with the *same* target name push more onto its
`inputs`/`opts`/`deps`. This is exactly why `libpanda.dll` is assembled by ~70
separate `TargetAdd('libpanda.dll', input='p3<x>_composite1.obj')` lines.

**`dep=`** adds a pure "rebuild if this changed" dependency that is *not* placed
on the compiler command line — used for the generated `dtool_have_<pkg>.dat`
sentinel files.

---

## OPTS — the opt-tag "language"

`opts=[...]` is a flat list of string tokens on each target. There is **no
schema**: every compiler-command builder simply scans the list for the tokens it
recognizes and ignores the rest. makepanda's own author described the system
plainly: there is a `PACKAGES` list of third-party libraries makepanda can use,
and "that list of options [OPTS] include[s] the name[s] of the packages" — put a
package name in a target's compile OPTS to get its includes, and in its link OPTS
to get its libraries (Josh_Yelon). The categories:

### `DIR:<path>` — a source/include directory
Becomes a `-I<path>` on compiles *and* tells the build where this target's
sources live (it feeds the include-search path used to locate the `.cxx` and to
scan dependencies). Read via `GetListOption(opts, "DIR:")`.

### `BUILDING:<X>` → `-DBUILDING_X` — the export-macro switch
Emitted as a preprocessor define (`makepanda.py:1319-1321` MSVC,
`1576-1577` GCC). This is the mechanism behind Panda's per-library symbol export.
Every library has a block in `panda/src/pandabase/pandasymbols.h` shaped like:

```c
#ifdef BUILDING_ENET
  #define EXPCL_ENET EXPORT_CLASS   // __declspec(dllexport) / visibility("default")
#else
  #define EXPCL_ENET IMPORT_CLASS   // __declspec(dllimport)
#endif
```

`BUILDING_ENET` is defined **only while compiling that library's own translation
units**, so its `EXPCL_ENET`-tagged classes are *exported* (`__declspec(dllexport)`
on Windows, `__attribute__((visibility("default")))` on GCC/Clang); every other
library that includes the header sees the *import* side. The same macro block is
deliberately short-circuited under `CPPPARSER` (so interrogate doesn't choke on
the `__declspec`) and under `LINK_ALL_STATIC` (so a static build exports nothing).
Getting `BUILDING:` wrong is the classic cause of "unresolved external" /
duplicate-symbol link errors for a new module. (See
**[Cross-cutting concepts](cross-cutting-concepts.md)** for how `EXPCL_*`
decorates classes.)

### A bare package name (`ENET`, `BULLET`, `PYTHON`, `RMLUI`, `WINSOCK2`, …)
This is the tag that pulls a *package's* include dirs, libraries, and defines
onto the command line. `makepandacore.py` keeps seven global `(opt, value)`
lists — `INCDIRECTORIES`, `LIBDIRECTORIES`, `FRAMEWORKDIRECTORIES`, `LIBNAMES`,
`DEFSYMBOLS`, `COMPILEFLAGS`, `LINKFLAGS` — populated by the registrars
`IncDirectory(opt, dir)`, `LibDirectory`, `FrameworkDirectory`,
`LibName(opt, name)`, `DefSymbol(opt, sym, val)`, `CompileFlag`,
`LinkFlag(opt, flag)`. Every builder consults them with the identical idiom:

```python
if (opt == "ALWAYS") or (opt in opts):
    # add this entry to the command
```

So putting `'ENET'` in a target's OPTS adds exactly the `IncDirectory("ENET",…)`,
`LibName("ENET",…)`, and `DefSymbol("ENET",…)` entries that were registered for
that package — includes on compiles, libs on links, defines on both. The
pseudo-package **`ALWAYS`** is the wildcard that applies to *every* target (e.g.
the thirdparty `extras/include` dir).

### Special opts
- **`EXCEPTIONS`** — with it, `-fexceptions` (MSVC `/EHsc`); without it, the
  default `-fno-exceptions` (MSVC `/D_HAS_EXCEPTIONS=0`)
  (`makepanda.py:1517-1526` / `1327-1330`). Panda compiles almost everything
  *without* exceptions; a module that includes a third-party header which uses
  `throw` (RmlUi's `itlib/flat_map.hpp` is one) **must** carry `EXCEPTIONS`, or
  it won't compile.
- **`RTTI`** — opt *in* to `-frtti`; default is `-fno-rtti` on non-darwin at
  higher opt levels. Panda uses its own `TypeHandle` RTTI, not C++ `typeid`.
- **`BIGOBJ`** (MSVC `/bigobj`), auto-added to interrogate objects.
- **`NOARCH:<ARCH>`** — drop one arch on a macOS universal build.
- **`SUBSYSTEM:CONSOLE`** — MSVC link subsystem (default for exes).
- **Interrogate opts** (only `CompileIgate`/`CompileImod` read these):
  `SRCDIR:` → `-srcdir`; `IMOD:` → `-module` (the Python module name, e.g.
  `panda3d.core`); `ILIB:` → `-library` (the igate library name); `IMPORT:` →
  `-import` (module to import at runtime); `INIT:` → `-init`.

---

## What ends up in `libpanda` vs `core.pyd` vs a separate module

Three destinations, all decided by explicit wiring:

**`libpanda.dll`** — the big C++ engine shared library. Assembled
(`makepanda.py:4216-4292`) by ~70 `TargetAdd('libpanda.dll',
input='p3<subsystem>_composite1.obj')` lines that pull each core subsystem's
object *directly into one shared library*: pgraph, cull, gobj, linmath, putil,
display, char, collide, text, pgui, and so on — **plus** `nativenet` and `net`,
which are therefore **statically absorbed into libpanda** rather than being their
own DLLs. It then links the lower layers (`libpandaexpress`, `libp3dtool`,
`libp3dtoolconfig`) as inputs.

**`COMMON_PANDA_LIBS`** (`makepanda.py:3565-3568`) is the bundle
`['libpanda.dll', 'libpandaexpress.dll', 'libp3dtool.dll',
'libp3dtoolconfig.dll']` that every satellite module links against.

**`core.pyd` (= `panda3d.core`)** — the Python extension for the core engine. It
is assembled from ~35 interrogate databases: `core_module.obj` is built from many
`libp3<x>.in` inputs (`makepanda.py:4294-4336`), then `core.pyd` links all the
matching `libp3<x>_igate.obj` wrapper objects, the hand-written `_ext` objects,
`core_module.obj`, and `COMMON_PANDA_LIBS`. So `panda3d.core` is a *single*
Python module aggregating the bindings of dozens of C++ subsystems.

**A separate module** (its own `.dll` and/or `.pyd`) — everything the engine can
ship independently: `enet`, `bullet`, `rmlui`, `physics`, `egg`, `ode`, `vrpn`,
`direct`, `vision`, `skel`, … These are listed in `panda_modules`
(`makepanda.py:2968-2988`) and each has its own `libp3<x>.dll` + `<x>.pyd`. This
is also how the **display backends** (`libpandagl.dll`,
`libp3vulkandisplay.dll`) are built — as loadable `MODULE`s (note
`opts=['MODULE', …]`, which on macOS produces a `-bundle`), discovered at runtime
via the `load-display` PRC variable, not linked into anyone.

The rule of thumb: **core engine C++ → `libpanda`; its bindings → `core.pyd`;
anything optional or separately-shippable → its own `libp3<x>.dll` + `<x>.pyd`.**

`libpanda` is a deliberate **metalib** — a single library aggregating many
subsystems. It wasn't always so: drwr notes that "each module — that is, each
directory — [was] its own DLL; and it is the way it still does compile on
Unix/Linux. The only real reason that `libpanda.dll` exists now is because VC6
required it." The consolidation stuck because it buys "less code bloat due to
templates… shorter load time… less risk of name-collision." A brand-new
subsystem, by contrast, is normally given its own DLL (ODE became `libpandaode`,
Bullet `libpandabullet`, and so on).

---

## The composite (unity-build) pattern

A `p3<name>_composite1.cxx` is a **unity-build aggregator**: a tiny file that
`#include`s the individual `.cxx` translation units of a subsystem so they
compile as a single object. For example `panda/src/enet/p3enet_composite1.cxx` is
literally:

```c
#include "config_enet.cxx"
#include "enetAddress.cxx"
#include "enetEvent.cxx"
#include "enetHost.cxx"
#include "enetPeer.cxx"
```

This gives fewer object files, faster builds, and cross-translation-unit
inlining. In this tree the composite files are **checked into the source tree**
(they exist on disk under each `panda/src/<x>/`) — `makepanda` references them as
pre-existing inputs; it has no composite-generator of its own. (Larger subsystems
are split across `_composite1`, `_composite2`, … to bound per-object compile
memory.)

CMake does **not** use these checked-in files; it generates its own composites
via `CMAKE_UNITY_BUILD`. That divergence has bitten: a `.cxx` reachable only
through a checked-in composite is invisible to CMake unless someone also adds it
to that directory's `set(P3X_SOURCES …)` list. See
[Building Panda3D (CMake)](building-cmake.md).

The composite build is also a **code-quality check**: because everything is
`#include`d together, a `.cxx` that forgot to include a header it depends on still
compiles (a sibling already pulled it in). Turning composites off exposes those
latent bugs — CFSworks calls the CMake knob for it "an essential code quality
check." (He named it `COMPOSITE_SOURCE_LIMIT=0` in 2019; that variable no longer
exists in the tree — the modern equivalent is `-DCMAKE_UNITY_BUILD=OFF`.) drwr's
warning from the ppremake era still
holds: with composites off "you will find many compilation errors from header
files that aren't `#include`d where they should be."

Two supporting helpers:

- **`CopyAllHeaders('panda/src/<x>')`** copies every `*.h/*.I/*.T` from a source
  dir into `built/include/`, so all downstream compiles and interrogate find them
  under one `-Ibuilt/include`.
- **`GetDirectoryContents(dir, ["*.h", "*_composite*.cxx"])`** fnmatch-collects a
  subsystem's public headers + composites into the `IGATEFILES` list that is fed
  to interrogate.

---

## The interrogate flow — C++ → Python bindings

Interrogate is Panda's binding generator: it parses annotated C++ headers and
emits C wrapper code that exposes the classes to Python. In drwr's words, "it
won't do this… unless they are bracketed with `BEGIN_PUBLISH` / `END_PUBLISH`" (or
a `PUBLISHED:` access section), which "are defined in `dtoolbase.h` to be
`__begin_publish`/`__end_publish` when the code is compiled with interrogate, and
nothing at all when compiled with a real compiler." The runtime half (the
`Dtool_*` machinery the wrappers call — `Dtool_PyInstDef` stores the C++ `void
*_ptr_to_object` right after `PyObject_HEAD`) lives in `dtool/src/interrogatedb`.

The *tool* itself was **split out of the tree** in 2024 into a separate
`panda3d-interrogate` project, installed as a binary rather than built in-tree.
rdb's rationale (issue #1074): "Most users of Panda3D don't need interrogate. It
just takes up space… [but] it is useful to have an easy way to get interrogate for
being able to cross-compile." makepanda now `pip install`s it into a temp dir; you
override the binary with the `$INTERROGATE` / `$INTERROGATE_MODULE` env vars. See
**[dtool / interrogate / config](subsystems/dtool.md)** and
**[Cross-cutting concepts](cross-cutting-concepts.md)** for the runtime side.

For a module `enet`, the chain is four targets (`makepanda.py:4466-4477`):

1. **Produce the `.in` database** — `TargetAdd('libp3enet.in', input=IGATEFILES,
   opts=[…,'IMOD:panda3d.enet','ILIB:libp3enet','SRCDIR:panda/src/enet'])`.
   Dispatches to `CompileIgate` (`makepanda.py:1659`), which runs the
   `interrogate` binary with `-srcdir`, the stub preprocessor defines
   (`-DCPPPARSER -D__cplusplus=…`), `-S built/include/parser-inc` (see below),
   each package's real include dirs as **`-S`** (system-include: parsed but not
   wrapped), the `DEFSYMBOLS` as `-D`, and `-module`/`-library` from `IMOD:`/
   `ILIB:`. It emits the `.in` database *and* a `libp3enet_igate.cxx` wrapper.
2. **`libp3enet_igate.obj`** — auto-created for any `.in` target
   (`makepandacore.py:3932-3937`); a plain `CompileCxx` of the generated wrapper.
3. **`enet_module.obj`** — `TargetAdd('enet_module.obj', input='libp3enet.in',
   opts=[…,'IMOD:panda3d.enet','ILIB:enet','IMPORT:panda3d.core'])`. An `.obj`
   whose input is a `.in` dispatches to `CompileImod` (`makepanda.py:1741`),
   which runs `interrogate_module` to emit the module init code, then compiles
   it.
4. **`enet.pyd`** — links `enet_module.obj` + `libp3enet_igate.obj` +
   `libp3enet.dll` + `COMMON_PANDA_LIBS` into the Python extension.

`GetInterrogate()` / `GetInterrogateModule()` (`makepandacore.py:614`/`632`)
resolve the tool from `$INTERROGATE` / `$INTERROGATE_MODULE` first, then from
`PATH` (via `shutil.which`), then a pip-installed copy. **This resolution order
matters** — see the interrogate gotcha below.

### parser-inc — why interrogate can parse third-party headers
Interrogate is a **pure C++ parser** (it embeds `libp3cppParser`) and, as drwr
repeatedly warns, "doesn't know anything about the nonstandard symbols that system
library writers like to put in their system header files" — Windows'
`__declspec`, GCC intrinsics, heavy template machinery. There are two standard
fixes, and Panda uses both:

1. **Shadow the offending header** with a stub in `dtool/src/parser-inc/`. drwr:
   "we shadow the third-party header files with a dummy header file in
   `dtool/src/parser-inc`… The idea is to just stub-declare each of the required
   typenames… read by interrogate, but not by the actual compiler." Often the
   stub only needs the class *names* (`class Foo;`) — "the typedefs don't
   necessarily have to be accurate; they usually just have to name the new type."
2. **`#ifdef CPPPARSER`** in your own code to hide a declaration from interrogate
   entirely (interrogate defines `CPPPARSER`; a real compile does not), or
   `DefSymbol` a `-D` to define an offending keyword away.

The stubs are copied to `built/include/parser-inc` and injected into *every*
interrogate run via `-S built/include/parser-inc` (`makepanda.py:1713`). The `-S`
(vs `-I`) distinction is central: `-S` headers are *parsed for context but their
contents are not wrapped into Python*. So a new module that includes an
unparseable third-party header interrogates fine as long as only its **own**
`PUBLISHED:` declarations are `-I`-visible and the third-party stuff is `-S`.

> **Critical, and repeatedly tripped over:** the `parser-inc` directory must
> **never** be on the *real* compiler's include path. rdb: "You are adding the
> parser-inc directory to your include path. Don't do that. They are meant for our
> interrogate parser only." The stubs are intentionally incomplete (some are
> empty); a real compile that picks them up fails in baffling ways.

One more interrogate subtlety when binding a module that takes or returns Panda
types: a forward declaration in `parser-inc` is *not* enough. rdb: "interrogate
really does need to know the full definition of the Panda3D types so that it will
understand how to convert them." Give it the real Panda headers (as `-S`), and
prefer marking your own API `PUBLISHED:` (or listing it in an `.N` file) over the
`-promiscuous` flag, which drags in unwanted dependencies.

---

## Vendored vs external libraries

Panda integrates third-party code two ways, and a new integration should follow
whichever the library warrants.

### Vendored — the code ships in-tree (ENet is the model)
`panda/src/enet/vendor/` contains a pinned copy of the ENet C library. The build
(`makepanda.py:4440-4478`):

- points includes at the in-tree copy: `IncDirectory("ENET",
  "panda/src/enet/vendor/include")`;
- sets platform capability macros directly rather than via a configure test:
  `DefSymbol("ENET", "HAS_GETADDRINFO")`, `HAS_POLL`, etc. on the relevant
  platforms;
- compiles each vendor `.c` file into a `p3enet_vendor_<name>.obj` and links them
  straight into `libp3enet.dll`.

There is no discovery step — the library is simply present. `'ENET'` is still a
registered *package* so it can be toggled with `--no-enet` and so its
`IncDirectory`/`DefSymbol` entries gate on the `ENET` opt. Vendoring is the right
choice for a small, rarely-changing C library you want to guarantee is present
and version-locked (ENet is ~1 MB of C). Record the upstream commit in a
`PROVENANCE.md` next to the vendor tree.

**Never edit vendored headers to make them build — shadow them instead.**
Josh_Yelon's rule: "when making a thirdparty package, we try very hard not to
edit the header files… if you edit the header files, then every time you update…
you have to re-edit… instead, we put `#define`s into the panda side… or put a
dummy header into parser-inc." (This is why the ENet integration adds `HAS_*`
`DefSymbol`s from the *makepanda* side rather than patching ENet's `unix.c`.)

### External — discovered at configure time (Bullet, FreeType, RmlUi)
These are found by `SmartPkgEnable(pkg, pkgconfig, libs, incs, …)`
(`makepandacore.py:1775`), e.g.
`SmartPkgEnable("FREETYPE", "freetype2", ("freetype"), …)`. Resolution order:
the bundled thirdparty dir → macOS framework → **pkg-config** → a manual
system-library search; if nothing is found the package auto-disables. Custom
locations come from `--<pkg>-incdir` / `--<pkg>-libdir`, which every registered
package gets for free (`makepanda.py:282-289`). The library is then linked via
the `LibName(pkg, …)` entries discovery populated. External is right for large,
system-provided, or fast-moving libraries.

The **`thirdparty/` archive** holds prebuilt copies of the optional libraries
(jpeg, zlib, FreeType, …) for platforms without a good system package manager;
you don't strictly need it ("you'll build a more limited version" without it —
drwr). It is regenerated by rdb's separate `panda3d-thirdparty` CMake project,
which **statically links everything by default**. Two consequences of static
thirdparty linking worth knowing: (1) Linux distro builders skip the archive and
use distro `-dev` packages instead, because statically bundling a different
version "probably violates packaging policies"; (2) to keep a statically-absorbed
library's symbols from leaking out of a Panda module and colliding, both build
systems pass `-Wl,--exclude-libs` (renderbear: "fairly safe to set
`-Wl,--exclude-libs,ALL` when compiling any module/plug-in, such as
`libpandagl.so`").

Two macOS linking wrinkles worth knowing when you integrate an external lib whose
own code (or Panda's glue to it) touches the Python C-API from inside a *shared
library* rather than only a `.pyd`:
- Framework Python exposes **no link library**, so the Python symbols must be
  allowed to stay unresolved and bind at load time:
  `LibName("<PKG>", "-undefined dynamic_lookup")`.
- If the library's install name is `@rpath/...`, consumers need an rpath:
  `LibName("<PKG>", "-Wl,-rpath,@loader_path/../lib")`, and the `.dylib` must be
  copied into `built/lib` so that rpath resolves.

---

## Package registration — how `--use-X` and `PkgSkip("X")` work

The master package list is set once by `PkgListSet([...])` (`makepanda.py:80-106`)
— ~70 names, `"ENET"`/`"BULLET"`/`"RMLUI"`/`"PYTHON"` among them. Being in that
list is *all* it takes to get, for free:

- the `--use-<pkg>` / `--no-<pkg>` flags (matched generically in `parseopts`,
  `makepanda.py:275-281`) and their auto-generated help text;
- the `--<pkg>-incdir` / `--<pkg>-libdir` custom-location flags;
- the `PkgSkip("<PKG>")` gate that every part of the build tests.

To fully wire a subsystem into the build you then, all guarded by
`if not PkgSkip("<PKG>"):`

1. `panda_modules.append('<x>')` — registers the Python module shim;
2. `CopyAllHeaders('panda/src/<x>')` — publishes its headers to `built/include`;
3. the `TargetAdd` block that compiles the composite into `libp3<x>.dll` and runs
   the interrogate chain to produce `<x>.pyd`;
4. if the module exports classes to other C++ code, a `BUILDING_<X>` /
   `EXPCL_<X>` block in `pandasymbols.h`.

Disabling the package (or its dependency not being found) cleanly removes all of
the above, because they share the one `PkgSkip` guard.

---

## Build gotchas (hard-won)

These are the failure modes that cost real time. Most produce a build that stops
in seconds during configuration, or a link/interrogate error that looks
mysterious until you know the mechanism above.

**Stale `built/` short-circuits.** `rm -rf built` (or `--clean`) after almost any
configuration change is the single most repeated piece of maintainer advice —
after changing `STDFLOAT_DOUBLE`, the Python version, a package's enablement, or a
version bump. If a build aborts during configuration it can leave a `built/` tree
with a written dependency cache but no compiled libraries; the next run then
decides "nothing to do" and exits in 0 seconds. Cached `dtool_have_<pkg>.dat`
files remember a *failed* discovery, so a wrong `--<pkg>-incdir` can persist as
"not found" until you wipe. A specific known trap (rdb): "makepanda doesn't
automatically copy over the parser-inc tree when a file in it has changed," and a
Ctrl-C'd build can leave `built/include/parser-inc` corrupt — `rm -rf
built/include/parser-inc` (or the whole `built/`) fixes the resulting interrogate
errors.

**Don't put `built/bin` on your `PATH`** (especially cross-compiling). rdb: doing
so "makes the installer use the copy of interrogate that is in there, which will
not work because it is compiled for a different architecture." For a
cross-compile you need a *host* interrogate — which is exactly why interrogate is
now a pip-installable host tool.

**Interrogate binary mismatch.** `GetInterrogate()` prefers an `interrogate` on
`PATH` before any in-tree/pip copy. If the wrong one is first on `PATH`, its
generated wrapper code can `#include` a runtime header that *redefines* the
structs already in your tree's `py_panda.h` (symptoms: `redefinition of
'Dtool_PyInstDef'`, `unknown type name 'EXPCL_PYPANDA'`). Fix by installing the
*matching* interrogate and pinning `$INTERROGATE` / `$INTERROGATE_MODULE` to it,
then wiping `built/` (old runs leave poisoned `_igate.cxx`).

**Interrogate parse errors on a new module.** Two common causes: (1) a `.cxx`
body that transitively includes an unparseable third-party header ended up in
`IGATEFILES` — interrogate only needs the **headers** carrying `PUBLISHED:`
declarations, so list those and drop the `.cxx`. (2) An inline `.I` file listed
*separately* in `IGATEFILES` is parsed standalone, before its class is declared
(`error: unknown type 'Foo'`) — don't list it; the `.h` already `#include`s it at
the bottom.

**`throw` under `-fno-exceptions`** (`cannot use 'throw' with exceptions
disabled`) — the module includes a third-party header that uses exceptions; add
`EXCEPTIONS` to *both* the composite and the igate/module OPTS.

**Undefined `_Py*` symbols when linking a `libp3<x>.dll`** (not a `.pyd`) — the
shared library contains Python-C-API code but framework Python offers no link
lib; add `-undefined dynamic_lookup` for that package (see the macOS wrinkles
above).

**pkg-config resolving to the wrong prefix.** `SmartPkgEnable` uses pkg-config
for some packages (freetype, harfbuzz), and pkg-config may return an *incomplete*
install (e.g. a MacPorts `/opt/local` when you meant Homebrew). Pass explicit
`--<pkg>-incdir`/`--<pkg>-libdir`. Note freetype's include level: makepanda's
`incs` check adds the `freetype2` subdir itself, so `--freetype-incdir` must be
the directory *above* `freetype2`.

**PYTHONPATH shadowing.** A `pip install panda3d*` wheel on `sys.path` will
shadow your `built/` engine at import time. Run against a fresh build with
`PYTHONPATH=<tree>/built` and install companion packages with `--no-deps` so they
don't drag in a stock `panda3d` wheel.

**Python ABI must match.** The engine, the interpreter you run it with, and any
native extension you build against it (e.g. RenderPipeline's `native_.so`) must
all be the *same* Python. A mismatch segfaults at import. `ldd`/`otool -L` the
`.so` to confirm which Python it links.

---

## Running the built engine

The build outputs everything under `built/`. To use it without installing:

```sh
export PYTHONPATH=<tree>/built
# macOS: let bundled dylibs (libMoltenVK, librmlui, …) resolve:
export DYLD_FALLBACK_LIBRARY_PATH=<tree>/built/lib
# Linux equivalent:
export LD_LIBRARY_PATH=<tree>/built/lib
python -c "import panda3d.core as p; print(p.PandaSystem.getVersionString())"
```

`built/bin` holds the tools and interrogate; `built/lib` the shared libraries;
`built/panda3d` the Python extension modules (`core.pyd`, `bullet.pyd`, …);
`built/include` the published headers; `built/pandac/input` the interrogate `.in`
databases.

---

## The Vulkan / shaderpipeline backend

Panda has an in-development **Vulkan** rendering backend
(`panda/src/vulkandisplay`) fed by a **shaderpipeline** that compiles GLSL to
SPIR-V (`panda/src/shaderpipeline`). It is opt-in and its build has extra
dependencies. This section captures the platform recipes; the backend itself is
documented in the display/GSG material.

The shaderpipeline uses three Khronos libraries, and it helps to know what each
does when a build fails to find one: **glslang** compiles GLSL (and, with a
patched front-end, Cg) to SPIR-V; **SPIRV-Cross** cross-compiles SPIR-V *back*
to the GLSL/GLSL-ES/HLSL/MSL each backend needs; **SPIRV-Tools** provides the
optimizer, including the "HLSL legalizer" that fixes SPIR-V glslang emits for
HLSL. They are statically linked, which is why `libpanda` (carrying glslang) is
large and each GSG module (carrying SPIRV-Cross) adds ~1 MB. glslang and
SPIRV-Cross are consumed as external packages — supply them via
`--glslang-*`/`--spirv-cross-*`/`--spirv-tools-*` incdir/libdir if they're not on
the default search path.

### macOS (MoltenVK → Metal)
There is no native Vulkan on macOS; the backend runs on **MoltenVK**, an ICD that
translates Vulkan to Metal. A working configuration:

```sh
export VULKAN_SDK=/opt/homebrew        # or a real LunarG SDK
python makepanda/makepanda.py --nothing \
  --use-python --use-direct --use-egg \
  --use-gl --use-vulkan --use-cocoa \
  --use-freetype --use-harfbuzz --use-zlib --use-png --use-jpeg \
  --glslang-incdir=/opt/homebrew/opt/glslang/include \
  --glslang-libdir=/opt/homebrew/opt/glslang/lib \
  --spirv-cross-incdir=/opt/homebrew/opt/spirv-cross/include \
  --spirv-cross-libdir=/opt/homebrew/opt/spirv-cross/lib \
  --spirv-tools-incdir=/opt/homebrew/opt/spirv-tools/include \
  --spirv-tools-libdir=/opt/homebrew/opt/spirv-tools/lib \
  --threads=$(sysctl -n hw.ncpu)
```

At runtime, point the Vulkan loader at MoltenVK and let the bundled dylibs
resolve:

```sh
export VK_ICD_FILENAMES=/opt/homebrew/opt/molten-vk/etc/vulkan/icd.d/MoltenVK_icd.json
export DYLD_FALLBACK_LIBRARY_PATH=<tree>/built/lib
```

macOS-specific caveats:
- A Homebrew `libMoltenVK.dylib` is a **symlink** into the Cellar; a build step
  that copies it into `built/lib` must `os.path.realpath()` the source first, or
  the copied symlink dangles and `install_name_tool` fails.
- The backend selects `VulkanGraphicsPipe` as the default pipe **only if the game
  loads `p3vulkandisplay`** (`load-display p3vulkandisplay` in the PRC); otherwise
  only GL registers and you silently run on GL.
- Offscreen rendering and bound-RTT readback are unreliable on this path (known
  teardown asserts); it is not a headless-verification-friendly backend.

### Linux (native Vulkan — the better place to debug)
On Linux you get a **real** Vulkan driver and full **validation layers** (which
barely attach under MoltenVK), which makes Linux the right place to bisect
"our-shaderpipeline bug" vs "MoltenVK-only bug." Translate the macOS command by
swapping `--use-cocoa` for `--use-x11` and dropping the MoltenVK bits; if the
distro `-dev` packages are on the default search path you can usually drop the
`--glslang-*`/`--spirv-*` dir flags entirely.

```sh
sudo apt install -y vulkan-tools libvulkan-dev vulkan-validationlayers-dev \
     spirv-tools glslang-dev glslang-tools spirv-headers \
     libspirv-cross-c-shared-dev mesa-vulkan-drivers        # driver for your GPU
python makepanda/makepanda.py --nothing \
  --use-python --use-direct --use-egg \
  --use-gl --use-vulkan --use-x11 \
  --use-freetype --use-harfbuzz --use-zlib --use-png --use-jpeg \
  --threads=$(nproc)
```

Runtime: the Linux Vulkan loader auto-finds the system ICD (do **not** set
`VK_ICD_FILENAMES` unless forcing a specific driver such as Mesa `lavapipe`, the
CPU software fallback for headless CI). Turn on validation and it will often flag
the descriptor/UBO/struct-packing issues automatically:

```sh
export VK_INSTANCE_LAYERS=VK_LAYER_KHRONOS_validation
export VK_LOADER_DEBUG=warn
export LD_LIBRARY_PATH=<tree>/built/lib
```

A good first correctness gate that needs **no GPU** is the shaderpipeline test
suite, which exercises the GLSL→SPIR-V passes directly:

```sh
PYTHONPATH=<tree>/built python -m pytest tests/shaderpipeline tests/gobj/test_shader.py -q
```

If a packing test fails here, the bug is in the SPIR-V passes, not the driver.
For frame-level inspection, `renderdoc` captures every pass and lets you read UBO
contents — the classic culprit is a `std140` `vec3[]` array-stride mismatch (the
12-vs-16-byte trap) reaching the IBL/lighting shaders.
