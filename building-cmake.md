# Building Panda3D (CMake) #

This chapter documents Panda's **CMake** build: the macro vocabulary that
replaces `makepanda`'s `TargetAdd`, how component libraries are merged into
metalibs, how interrogate is driven, and what actually differs between the two
build systems. It is aimed at the same reader as the
[makepanda chapter](building-and-makepanda.md) — someone who needs to *change*
the build — and assumes you have read that chapter's conceptual material
(composites, interrogate, metalibs, packages), because this chapter describes
the same engine assembled by different machinery and does not repeat the
concepts.

**Which build system should you use?** For new work on the engine, CMake. rdb,
closing issue #1729 (2025-03-03), states the policy directly:

> "If you are comfortable with using CMake, I would encourage building with
> CMake. We are in the process of phasing out the makepanda script with CMake."

Maxwell175 has been blunter about the practical consequence
(2022-12-18): "makepanda isn't caught up with some of the latest changes so if
you do want to build it, use cmake". But note what is *not* yet true: official
release artifacts are still makepanda-built. rdb, 2026-03-26: "we don't build
the public builds with CMake yet." And `makepanda`'s replacement-by-wrapper
(PR #859, Moguri) has been open since 2020-01-25. So: **CMake is the
recommended developer build; makepanda is still the release build.** Expect to
need both.

Citations are `path:LINE` against upstream `master` at `121191775e`
(2026-07-03). Line numbers drift — grep the named macro if they don't match.

---

## Quick start

The invocation from `cmake/README.md`, which is also the form every maintainer
uses in the archives:

```sh
mkdir build && cd build
cmake ..
cmake --build . --config Standard --parallel 4
[sudo] cmake --build . --config Standard --target install
```

Two notes on this, because both trip people up:

- **`--config Standard` is ignored by single-config generators** (Ninja,
  Makefiles). There, set `-DCMAKE_BUILD_TYPE=Standard` at configure time
  instead. It is only meaningful for Xcode and Visual Studio.
- **`-A x64` is required on Windows** for a 64-bit build, and only on the
  *first* `cmake` invocation: `cmake -A x64 ..`. `-G Ninja` is "highly
  recommended on Linux" per the README.

> **A note on style.** The archives contain no use of the modern
> `cmake -B build -S .` / `cmake --install build` spelling — upstream's README
> and every maintainer use the legacy `mkdir build && cd build` form shown
> above. The modern form works fine; it simply isn't what you'll see in any
> existing Panda discussion, so this chapter documents the attested form.

**Build configurations** are Panda-specific. `Standard` is the default and has
no stock CMake equivalent — rdb explains why (forum topic 28054, 2021-09-30):

> "`--optimize 4` would correspond to Release. `--optimize 1` and `2` would
> correspond to Debug. `--optimize 3` is a bit of a weird one, it is technically
> Release mode in that it has a lot of optimizations but we do include a lot of
> assertion checks and other debugging information. In our CMake scripts we
> created a new mode for this called 'Standard'."

| Configuration | Meaning | makepanda equivalent |
|---|---|---|
| `Standard` | **Default.** Optimized, assertions retained. The SDK build. | `--optimize 3` |
| `Release` | Distribution for end users. | `--optimize 4` |
| `MinSizeRel` | Like Release, optimized for size. | — |
| `RelWithDebInfo` | Like Release, with debug symbols. | — |
| `Debug` | Unoptimized, optional debugging features on. | `--optimize 1`/`2` |
| `Coverage` | Like Debug, with coverage profiling. Clang/GCC only. | — |

The deliberate design point: `Standard` **does not define `NDEBUG`**, and that
is load-bearing for ABI compatibility with `Release`. rdb, PR #717 (2019-10-05):
"the reason why `Standard` shouldn't have `NDEBUG` is because `NDEBUG` removes a
lot of things that people really do expect… Panda will often simply crash if you
pass an out-of-bounds value." CFSworks found `PandaNode` was 8 bytes smaller
under `NDEBUG` — an ABI break between the SDK you compile against and the
Release wheel you ship on. There are still no automated tests guarding this.

---

## Translating makepanda flags to CMake

This table does not exist upstream, and its absence is the single most common
source of confusion in the archives. Moguri asked for it in 2020-01-24 ("Are
there any migration docs? Like what cmake flags to use to replace makepanda
flags?"); it was never written. The same question recurs from users through
2026 — `--no-eigen`, `--no-openexr` and friends simply do not exist under CMake.

| makepanda | CMake |
|---|---|
| `--use-X` / `--no-X` | `-DHAVE_X=ON` / `-DHAVE_X=OFF` |
| `--optimize 1` … `4` | `-DCMAKE_BUILD_TYPE=Debug` … `Release` (see table above) |
| `--everything` | *(default — all found libraries are enabled)* |
| `--nothing` | *(no equivalent; disable individually)* |
| `--distributor X` | `-DPANDA_DISTRIBUTOR=X` |
| `--threads N` | `--parallel N` on the build step, or `-jN` |
| `--outputdir X` | *(the build directory itself)* |
| `--static` | `-DBUILD_SHARED_LIBS=OFF` |
| `--python-incdir` / `--libdir` | `-DPython_ROOT_DIR=…` (see `FindPython` hints) |
| `--<pkg>-incdir` / `--<pkg>-libdir` | `-D<Pkg>_ROOT=…`, or the module's own `<PKG>_INCLUDE_DIR` / `_LIBRARY` cache vars |
| `--thirdparty X` | `-DTHIRDPARTY_DIRECTORY=X` |
| `--installer` | *(no equivalent — CPack/installers were never ported)* |
| `--wheel` | *(no equivalent — see "Wheels" below)* |
| `--version X` | *(read from `setup.cfg`)* |
| `--clean` | delete the build directory |

The naming conventions, per `cmake/README.md`: `HAVE_<LIBRARY>` for third-party
libraries, `BUILD_<SUBPACKAGE>` for Panda's own trees, and "other configuration
settings use their historical names (same names as in-source)" — so
`PANDA_DISTRIBUTOR`, `LINMATH_ALIGN`, `STDFLOAT_DOUBLE` are spelled exactly as
in the C++.

> **Doc bug, worth knowing so it doesn't mislead you:** the README's own example
> under `HAVE_<LIBRARY>` reads `# Example: USE_JPEG`. The variable is
> `HAVE_JPEG`; there is no `USE_JPEG`.

Because there is no `--nothing`, a minimal build is built by subtraction. A real
example (pmp-p, 2023-10-22), reducing to software rendering only:

```sh
cmake -DHAVE_AUDIO=NO -DHAVE_EGL=NO -DHAVE_GL=NO -DHAVE_GLX=NO -DHAVE_X11=NO \
      -DHAVE_GLES1=NO -DHAVE_GLES2=NO -DHAVE_TINYDISPLAY=1 -DBUILD_SHARED_LIBS=NO ..
```

and a C++-only build with no Python at all (Forest, 2025-08-24):

```sh
cmake .. -DCMAKE_INSTALL_PREFIX=~/apps/panda3d \
         -DHAVE_PYTHON=OFF -DHAVE_EIGEN=OFF -DHAVE_TINYDISPLAY=OFF
```

That last one has a motive worth stating: with `HAVE_PYTHON=ON`, `install`
writes the Python package into your **global** `site-packages`
(`PYTHON_ARCH_INSTALL_DIR`, `dtool/Package.cmake:337-341`), which repeatedly
surprises people building Panda purely as a C++ library.

---

## The mental model: declarative targets, deferred wiring

Where makepanda is one long script issuing `TargetAdd` calls in execution order,
CMake is a set of per-directory `CMakeLists.txt` files that *declare* targets and
properties, with the actual commands assembled later from those properties. The
practical consequences:

- **Ordering still matters, but for a different reason.** `add_metalib` fatals
  if a named component target does not yet exist
  (`cmake/macros/BuildMetalib.cmake:234-237`, "Component library targets must be
  created BEFORE add_metalib"). That is why `panda/CMakeLists.txt` adds every
  `src/*` subdirectory before the `metalibs/*` ones, and why the root
  `CMakeLists.txt:116-134` orders `dtool` → `panda` → `direct` → `pandatool` →
  `contrib`. Each tree hard-errors if its predecessor wasn't built
  (`panda/CMakeLists.txt:1-3` and siblings).
- **Interrogate is deferred.** `target_interrogate` does not run interrogate; it
  records properties on the target, and the command is materialized later by
  `add_python_module`. See below.
- **Flags come from target properties, not a global options list.** makepanda's
  `OPTS=['ZLIB','PNG']` becomes `target_link_libraries(tgt PKG::ZLIB PKG::PNG)`,
  and the include dirs / defines / link flags ride along as usage requirements.

rdb notes the lineage (2020-02-02): "CMake was modelled more after the old
ppremake build system (which was removed some time ago) than after the makepanda
system." That explains the per-directory structure — it is closer to what the
tree looked like before makepanda flattened it.

---

## The macro vocabulary

The root `CMakeLists.txt:96-103` includes the macro set, self-documenting:

```cmake
include(AddBisonTarget)   # add_bison_target
include(AddFlexTarget)    # add_flex_target
include(BuildMetalib)     # add_component_library AND add_metalib
include(CompositeSources) # composite_sources
include(Python)           # add_python_target AND install_python_package
include(Interrogate)      # target_interrogate AND add_python_module
include(RunPzip)          # run_pzip
include(Versioning)       # hooks add_library to apply VERSION/SOVERSION
```

Mapped against the makepanda concepts from the previous chapter:

| makepanda | CMake | Defined at |
|---|---|---|
| `TargetAdd('libp3x_composite1.obj', …)` | `add_component_library()` | `cmake/macros/BuildMetalib.cmake:30` |
| `TargetAdd('libpanda.dll', input=…)` ×70 | `add_metalib()` | `cmake/macros/BuildMetalib.cmake:145` |
| `OPTS=['ZLIB','BUILDING:X']` | `PKG::ZLIB` + `SYMBOL` argument | `PackageConfig.cmake:177`, `BuildMetalib.cmake:99-111` |
| `PkgSkip("X")` / `--use-X` | `package_option()` → `option(HAVE_X)` | `cmake/macros/PackageConfig.cmake:70` |
| `CompileIgate` | `target_interrogate()` + `interrogate_sources()` | `Interrogate.cmake:56`, `:134` |
| `CompileImod` | `add_python_module()` | `cmake/macros/Interrogate.cmake:292` |
| checked-in `_composite1.cxx` | `composite_sources()` + `CMAKE_UNITY_BUILD` | `cmake/macros/CompositeSources.cmake:37` |
| `built/` | `PANDA_OUTPUT_DIR` | `dtool/CompilerFlags.cmake:76-88` |
| makepanda's `dtool_config.h` writer | `configure_file(dtool_config.h.in …)` | `dtool/LocalSetup.cmake:186-212` |

`cmake/macros/README.md` warns these are **unsafe outside Panda3D** — they
depend on Panda's variables and layout. `cmake/modules/` (the `Find*.cmake`
files) is the generic, reusable half; `cmake/scripts/` are run via `cmake -P`
and must never be `include()`d.

---

## Component libraries and metalibs

This is the CMake answer to "what ends up in `libpanda`", and the mechanism is
genuinely different from makepanda's — worth understanding before you debug a
link failure.

**The knob is `BUILD_METALIBS` (`dtool/Config.cmake:43-47`, default ON.)**

**With `BUILD_METALIBS=ON`:** `add_component_library(p3putil …)` creates an
**OBJECT library** (`BuildMetalib.cmake:87`) — a bag of `.o` files with no link
step at all. Its `install(TARGETS)` is guarded by `if(NOT BUILD_METALIBS)`, so
nothing is installed for it; only its headers are. Then
`add_metalib(panda … COMPONENTS ${PANDA_LINK_TARGETS})`
(`panda/metalibs/panda/CMakeLists.txt:24`) merges them, and the merge is one
line — `BuildMetalib.cmake:330`:

```cmake
list(APPEND sources "$<TARGET_OBJECTS:${component}>")
```

Everything around it is property hoisting: the metalib copies each component's
`INTERFACE_COMPILE_DEFINITIONS` (`:268-279`), `INTERFACE_INCLUDE_DIRECTORIES`
(`:283-297`), `INTERFACE_LINK_LIBRARIES` (`:301-317`) and `LINK_OPTIONS`
(`:321-327`) up onto itself — filtering out references to sibling components,
since those are being absorbed rather than linked. That link-libraries hoist is
how `PKG::ZLIB` and friends bubble from a component up to the metalib's link
line, and the `LINK_OPTIONS` hoist is how a component's `--exclude-libs`
survives.

**With `BUILD_METALIBS=OFF`:** each component becomes a real library, the
per-directory `install(TARGETS)` blocks activate, and the metalib degenerates to
a stub that simply links them (`:332-334`). As `Config.cmake:43-47` puts it,
"turning this off will still result in the 'metalibs' being built, but they will
instead be many smaller stub libraries." Note CFSworks's warning (2019-04-18)
that toggling `BUILD_METALIBS` in an existing build directory "will cause it to
yell loudly" — reconfigure from clean.

**The generated init function.** `add_metalib` synthesizes an `init_<name>.cxx`
from `cmake/templates/metalib_init.cxx.in` (`BuildMetalib.cmake:338-349`) that
chains every component's init:

```c++
#include "config_putil.h"     // one per component, from its INIT_HEADER
// ... one #include per component ...
EXPORT_CLASS void init_libpanda() {
  init_libputil();            // one per component, from its INIT_FUNCTION
  // ... one call per component ...
}
```

Those come from properties `add_component_library` stamped on each target
(`:94-97`): `IS_COMPONENT`, `INIT_FUNCTION`, `INIT_HEADER`. The defaults are
derived by stripping the `p3` prefix (`:42-43`), so `p3putil` implies
`init_libputil()` declared in `config_putil.h`. Pass `NOINIT` or
`INIT func [header]` to override.

**The export-symbol trick.** `SYMBOL BUILDING_PANDA_PUTIL` becomes
`DEFINE_SYMBOL`, but since CMake ignores `DEFINE_SYMBOL` for OBJECT libraries it
is *also* appended to `COMPILE_DEFINITIONS` (`:104`) and propagated to sibling
components through a guarded generator expression (`:108-109`):

```
$<$<BOOL:$<TARGET_PROPERTY:IS_COMPONENT>>:${symbol}>
```

So components inside the same metalib see `BUILDING_…` (and therefore use
`EXPORT_CLASS`), while outside consumers do not (and use `IMPORT_CLASS`). If
symbols are visible or invisible when you didn't expect it, this genex plus the
tree-wide `-fvisibility=hidden` (`dtool/CompilerFlags.cmake:248-253`) is where
to look.

**The rule that catches everyone**, stated at `BuildMetalib.cmake:26-28`:
*component libraries may only be linked by other components in the same
metalib.* From outside, link the metalib. Linking a component directly gets you
either duplicate symbols or missing ones.

The 12 metalibs: `p3dtool`, `pandaexpress`, `panda` (~27 components),
`pandaegg`, `pandadx9`, `pandagl`, `pandagles`, `pandagles2`, `pandaphysics`,
`p3headlessgl`, `p3direct`, and `p3tinydisplay`. Note `p3prc` is deliberately
*not* a component — `dtool/src/prc/CMakeLists.txt:93` uses plain `add_library`.

---

## Packages — `HAVE_*`, `PKG::`, and the interrogate-hiding genex

Every third-party dependency is declared in **`dtool/Package.cmake`** as a
`find_package` / `package_option` / `package_status` triple:

```cmake
find_package(ZLIB QUIET)                                  # Package.cmake:481
package_option(ZLIB
  "Enables support for compression of Panda assets."
  IMPORTED_AS ZLIB::ZLIB)                                 # :483-485
package_status(ZLIB "zlib")                               # :487
```

`package_option` (`cmake/macros/PackageConfig.cmake:70`) does three things worth
knowing:

1. **`:148` — `option("HAVE_${name}" …)`.** This is the single source of every
   `HAVE_*` cache variable in the build. The default is `${<pkg>_FOUND}`, i.e.
   **every found library is enabled by default** — the CMake analogue of
   `--everything`, not of `--nothing`. Forcing `HAVE_X=ON` when the package
   wasn't found is a hard `SEND_ERROR`: `"NOT FOUND: X. Disable HAVE_X to
   continue."`
2. **`:177` — `add_library(PKG::${name} INTERFACE IMPORTED GLOBAL)`,
   unconditionally.** This is why per-directory files can write
   `target_link_libraries(p3express PKG::ZLIB PKG::OPENSSL)` with no `if()`
   guard: when the package is disabled, `PKG::ZLIB` is simply an empty interface
   library. It is the structural replacement for makepanda's `PkgSkip` guards.
3. **`:186-189`, `:198-199`, `:228` — the interrogate-hiding generator
   expression.** Package include directories and imported targets are wrapped in
   a genex that evaluates to *nothing* for a consumer whose `IS_INTERROGATE`
   property is set. This deliberately hides real third-party headers from
   interrogate so it uses the stubs in `dtool/src/parser-inc` instead — the same
   `-S`/`parser-inc` mechanism described in the makepanda chapter, achieved
   structurally rather than by hand-built command lines.

**Critical packages don't auto-disable.** `Python` and `OpenSSL` are declared
`DEFAULT ON` regardless of whether they were found. rdb's reasoning (issue
#1072, 2020-12-20):

> "The majority of people who are compiling Panda3D want to do so with Python
> and OpenSSL support, and doing otherwise is likely to be a mistake. So we mark
> those packages as critical, and they need to be disabled explicitly in order
> not to build with them. This is intended to fix the recurring support issue we
> have with makepanda, where people don't bother looking at the build output and
> then complain that 'Panda3D doesn't work'."

He also notes the confusing consequence, which is still present: these show `+`
in the configure summary *because they are enabled*, not because they were
found. "Maybe this is confusing. Perhaps we should show them with a '!'."

**`THIRDPARTY_DIRECTORY`** auto-detects `${PROJECT_SOURCE_DIR}/thirdparty`
(`Package.cmake:42-57`) and maps makepanda's platform subdirectory names
(`darwin-libs-a`, `win-libs-vc14-x64`, `linux-libs-x64`, …) at `:1-40`, then sets
`<Package>_ROOT` for 25 packages (`:87-150`, requiring policy `CMP0074`, hence
**CMake ≥ 3.12**). It is entirely optional, and rdb is emphatic that it is
usually the wrong tool (2023-11-18): "the whole `THIRDPARTY_DIRECTORY` system is
optional and you don't want to use it" — on a system with real packages, let
`find_package` do its job. It is also a false-positive hazard: Moguri hit CMake
concluding he had a thirdparty dir "simply because 'thirdparty' existed. However,
I had emscripten libs, not Linux ones."

**The config header.** There is one that matters: `dtool/dtool_config.h.in` →
`dtool_config.h`, generated at `dtool/LocalSetup.cmake:186-212`, with ~82
`#cmakedefine` lines. Multi-config generators get one *per configuration*
(`:190-201`), driven by the `per_config_option` registry. Everything before that
in `LocalSetup.cmake` is autoconf-style probing (`WORDS_BIGENDIAN`,
`SIMPLE_STRUCT_POINTERS`, `PHAVE_*_H`, `HAVE_SSE2`, …).

> **If you see `dtool_config.h: No such file`:** your target is not
> transitively linking `p3dtoolbase`. That target's PUBLIC include directories
> (`dtool/src/dtoolbase/CMakeLists.txt:78-80`) are what put the generated header
> on everyone's include path.

Note the `config_<dir>.h` files are **ordinary checked-in sources**, not
generated — only `dtool_config.h`, `pandaVersion.h`, `prc_parameters.h`,
`panda.prc` and the metalib init pair are `configure_file` products.

---

## Interrogate under CMake

Three functions in `cmake/macros/Interrogate.cmake`, and the split between them
is the main conceptual difference from makepanda.

**`target_interrogate(target [ALL] [sources…] [EXTENSIONS ext…])` (`:56`) does
not run interrogate.** It only records, on the target, which sources should
later be scanned — `IGATE_SOURCES`, `IGATE_EXTENSIONS`, `TARGET_SRCDIR`,
`TARGET_BINDIR`. Sources marked `WRAP_EXCLUDE` are skipped (`:89-90`), which is
exactly what `composite_sources` sets on the originals so that the *composites*
get scanned instead.

**`interrogate_sources(…)` (`:134`) builds the actual command** (`:254-276`):

```
interrogate -oc <workdir>/<target>_igate.cxx -od <workdir>/<target>.in
            -srcdir <TARGET_SRCDIR> -library <target>
            ${INTERROGATE_OPTIONS} ${IGATE_FLAGS} ${language_flags} ${define_flags}
            -S ${PROJECT_SOURCE_DIR}/dtool/src/interrogatedb
            -S ${PROJECT_SOURCE_DIR}/dtool/src/parser-inc
            -S ${PYTHON_INCLUDE_DIRS}
            ${include_flags} ${scan_sources}
```

Two implementation details you will meet while debugging:

- **The fake-target hack (`:202-210`).** Custom commands aren't targets and so
  can't carry properties, so the macro creates a dummy
  `add_custom_target(${target}_igate_internal)` with `IS_INTERROGATE 1`, mirrors
  the real target's include directories onto it, and then reads them back
  *through* it — which is what makes the `PKG::` genexes collapse to empty and
  the `parser-inc` stubs win. The source comment ends: "I hate it, but such is
  CMake."
- **`-I` flags are tab-separated** (`:210`) rather than space-separated, to work
  around a CMake escaping bug.
- `.N` files are globbed per scanned source and added to `DEPENDS` (`:174-179`),
  so editing an interrogate directive file correctly re-triggers. makepanda does
  not track this as precisely.
- Paths are deliberately relativized against `TARGET_SRCDIR` (`:168`) to keep
  command lines short enough for Windows.

**`add_python_module(module …)` (`:292`)** ties it together: it calls
`interrogate_sources` per component, then runs `interrogate_module` over the
collected `.in` files (`:365-376`), then `add_python_target`. Note `:387-390` —
the module *scans* many components but *links* only what `LINK` names, which is
why `panda3d.core` interrogates ~30 components and links just `panda`
(`panda/CMakeLists.txt:110`).

### Interrogate is an external project

This is a significant divergence from makepanda and a common surprise.
`dtool/Config.cmake:246-317`: if `BUILD_INTERROGATE` is ON (the default when
bindings are wanted), CMake `ExternalProject_Add`s
`https://github.com/panda3d/interrogate.git` at a **pinned commit**, builds it,
and uses that. If OFF, it `find_program`s, honouring `INTERROGATE_EXECUTABLE` /
`INTERROGATE_MODULE_EXECUTABLE`.

rdb's announcement (2024-08-10) covers the rationale and the one real gotcha:

> "Heads up: most of interrogate is now deleted, CMake pulls it in using
> `ExternalProject_Add` (if `BUILD_INTERROGATE` is set, the default) or expects
> it to be present on the system already. Makepanda will always install it into
> a temporary directory using pip. Generally you don't need to change anything,
> **unless you build Panda without an internet connection.**"

So an offline or air-gapped build must set `BUILD_INTERROGATE=OFF` and supply
`INTERROGATE_EXECUTABLE`. Note also that `panda3d-interrogate` itself **can only
be built with CMake** — makepanda cannot build it at all.

---

## Composite (unity) builds

The makepanda chapter describes checked-in `_composite1.cxx` files. **CMake does
not use them.** It generates composites itself, or rather delegates to CMake's
native unity-build support.

> **Correction worth flagging if you've read older material:** the knob is
> **not** `COMPOSITE_SOURCE_LIMIT`. That string does not appear anywhere in the
> tree. CFSworks's widely-quoted 2019 advice to set `-DCOMPOSITE_SOURCE_LIMIT=0`
> for better error messages referred to the hand-rolled implementation that
> predates CMake 3.16; the modern equivalent is `-DCMAKE_UNITY_BUILD=OFF`.

The live cache variables (`cmake/macros/CompositeSources.cmake:18-33`):

| Variable | Default | Meaning |
|---|---|---|
| `CMAKE_UNITY_BUILD` | **ON** — "Panda defaults this to on" | Master switch. Turn OFF for clearer errors and better parallelism. |
| `CMAKE_UNITY_BUILD_BATCH_SIZE` | **30** | Files per composite. Higher is faster but more memory-hungry. |
| `COMPOSITE_SOURCE_EXTENSIONS` | `.cxx;.mm;.c` | Only these are composited. |
| `COMPOSITE_SOURCE_EXCLUSIONS` | *(empty)* | Target names to skip; "mainly desirable for CI builds". |

`composite_sources(target sources_var)` (`:37`) has two code paths. On **CMake
≥ 3.16 it does almost nothing** (`:38-52`) — it marks non-`.cxx` sources
`SKIP_UNITY_BUILD_INCLUSION` and returns, leaving the work to
`CMAKE_UNITY_BUILD`. The elaborate hand-rolled batching at `:54-166` is the
legacy path for older CMake. Since the tree now requires 3.16 anyway
(root `CMakeLists.txt:1`, and 3.16 on Apple), the native path is what you
actually get.

Per-file opt-out is `set_source_files_properties(x.cxx PROPERTIES
SKIP_UNITY_BUILD_INCLUSION YES)` — see `dtool/src/dtoolbase/CMakeLists.txt:72`.

The code-quality argument from the makepanda chapter still applies, and CI
exercises both settings (`.github/workflows/ci.yml:182`). Kam's practical note
(2020-02-11): "`CMAKE_UNITY_BUILD=OFF` helps with the messages, and builds much
faster in parallel." CFSworks tuned the other direction: "I can build Panda in
about 5 minutes by tuning [the batch size] and using `make -j17`."

---

## Output layout — the CMake build dir *is* `built/`

`dtool/CompilerFlags.cmake:73-106` deliberately mimics makepanda's layout. The
first line is the surprising one:

```cmake
# Set up the output directory structure, mimicking that of makepanda
set(CMAKE_BINARY_DIR "${CMAKE_BINARY_DIR}/cmake")
```

That pushes *intermediate* artifacts into `<build>/cmake/{dtool,panda,…}`, while
`PANDA_OUTPUT_DIR` (`:76-84`) stays at the top of the build dir. The result is
that a CMake build directory is a drop-in replacement for `built/`:

| Path | Contents |
|---|---|
| `<build>/bin` | tools |
| `<build>/lib` | shared libraries |
| `<build>/panda3d/` | the importable extension modules |
| `<build>/direct/`, `<build>/pandac/` | the Python packages |
| `<build>/etc/panda3d/20_panda.prc` | generated config |
| `<build>/models` | models |
| `<build>/panda3d.dist-info/` | `METADATA` + `entry_points.txt` |

so the same runtime incantation works:

```sh
export PYTHONPATH=<build>
export DYLD_FALLBACK_LIBRARY_PATH=<build>/lib   # macOS
export LD_LIBRARY_PATH=<build>/lib              # Linux
python -c "import panda3d.core as p; print(p.PandaSystem.getVersionString())"
```

**Multi-config generators insert a per-config level**: everything gains a
`<build>/<Config>/` prefix, which is why CI adds both `$PWD/<config>/bin` and
`$PWD/bin` to `PATH`.

That `panda3d.dist-info/METADATA` exists so the *build tree itself* looks like an
installed distribution to `importlib.metadata` — which is what makes the
`build_apps` / `bdist_apps` setuptools entry points resolvable from an
uninstalled build.

---

## Install, export, and consuming Panda from CMake

There is no central install script; each directory installs its own targets and
headers, tagged with an **install component** (`Core`/`CoreDevel`,
`Python`, `Direct`/`DirectDevel`, `Tools`, `OpenGL`, `Bullet`, …) and an
**export set**. `export_targets(set [NAMESPACE ns] [COMPONENT comp])`
(`PackageConfig.cmake:446`) emits `Panda3D<Set>Targets.cmake` into
`${CMAKE_INSTALL_LIBDIR}/cmake/Panda3D`.

Downstream, `cmake/install/Panda3DConfig.cmake` gives you:

```cmake
find_package(Panda3D COMPONENTS Core Direct Framework OpenGL Tools)
target_link_libraries(mygame Panda3D::Core::panda Panda3D::Framework::p3framework)
```

Its header comment (`:13-118`) is the authoritative list of components and
imported target names — worth reading, because there is no other documentation
of it. Because the root `CMakeLists.txt:190-192` calls `export(PACKAGE Panda3D)`,
this works against an **uninstalled build directory** too; disambiguate between
several with `set(Panda3D_DIR …)`.

rdb's own recommendation for embedding Panda in a C++ project (2026-03-26) is
`ExternalProject_Add`: "putting a reference to a particular commit of panda3d
repo in there which would be built automatically by CMake when building my
project… It's kinda like a git submodule except not via git but via cmake."
`FetchContent` + `add_subdirectory` also works. He acknowledges the doc gap
frankly: "It's fair criticism — I suppose we don't put a lot of thought into
compact C++ bundles because it's admittedly not really the main audience for
Panda3D."

### Wheels

**There is no CMake wheel target, and no `pip install .`** — the tree has no
`setup.py` and no `pyproject.toml`. (`setup.cfg` exists solely to carry
`version =`, which the root `CMakeLists.txt:46` parses.)

Wheels are built by `makepanda/makewheel.py`, which is build-system-agnostic and
consumes the *output directory*. Point it at your CMake build:

```sh
python makepanda/makewheel.py --outputdir=<build>
```

It finds the platform tag by parsing `PYTHON_PLATFORM_TAG` out of
`CMakeCache.txt` when makepanda's `tmp/platform.dat` is absent
(`makewheel.py:647-664`). rdb, 2023-11-18: "makewheel should work with cmake -
let me know if you run into trouble, **I've never tested this**." Issue #1663
(open since 2024-06) tracks the remaining breakage; the interrogate `.in`
databases are not placed where `makewheel` expects them, which breaks
`types-panda3d` stub generation, and loadable plugins can land in the wrong
directory.

The intended future, per rdb (2024-08-10), is the pipeline already used for
`panda3d-interrogate`: **cibuildwheel + scikit-build-core**, with dependencies
pulled in via `ExternalProject_Add`, "so the whole build process can be
encapsulated inside Python's build system." That is aspiration, not shipped.

---

## Worked example: wiring a new subsystem into the CMake build

The Vulkan backend is a good model because it was makepanda-only until recently,
so the diff that added it is exactly the set of changes a new subsystem needs.
(This is `tkfoss-panda3d` commits `49b815694b` and `1531ebc249`; the backend
itself is covered in the makepanda chapter.)

**1. Declare the package** — `dtool/Package.cmake`:

```cmake
find_package(Vulkan QUIET)
package_option(Vulkan
  "Enable the experimental Vulkan rendering backend."
  IMPORTED_AS Vulkan::Vulkan)
package_status(Vulkan "Vulkan")
```

That one triple buys `HAVE_VULKAN`, the `PKG::VULKAN` interface target, the
configure-summary line, and the "NOT FOUND … disable to continue" error.

**2. Write the per-directory `CMakeLists.txt`** — the canonical shape:

```cmake
if(NOT HAVE_VULKAN)
  return()
endif()

set(P3VULKANDISPLAY_HEADERS  config_vulkandisplay.h …)
set(P3VULKANDISPLAY_SOURCES  config_vulkandisplay.cxx …)

composite_sources(p3vulkandisplay P3VULKANDISPLAY_SOURCES)

set(CMAKE_INSTALL_DEFAULT_COMPONENT_NAME "Vulkan")
add_metalib(p3vulkandisplay ${MODULE_TYPE}
  ${P3VULKANDISPLAY_HEADERS} ${P3VULKANDISPLAY_SOURCES}
  COMPONENTS ${VULKANDISPLAY_LINK_TARGETS})
unset(CMAKE_INSTALL_DEFAULT_COMPONENT_NAME)

set_target_properties(p3vulkandisplay PROPERTIES DEFINE_SYMBOL BUILDING_VULKANDISPLAY)
target_link_libraries(p3vulkandisplay panda PKG::VULKAN)

install(TARGETS p3vulkandisplay
  EXPORT Vulkan COMPONENT Vulkan
  DESTINATION ${MODULE_DESTINATION}
  ARCHIVE COMPONENT VulkanDevel)
export_targets(Vulkan NAMESPACE "Panda3D::Vulkan::" COMPONENT VulkanDevel)
```

Three idioms in there are worth naming explicitly:

- **`${MODULE_TYPE}`** (set at `dtool/LocalSetup.cmake:143-153` to `MODULE` in a
  shared build, `STATIC` in a static one) falls through `add_metalib`'s keyword
  parser into the source list and lands as the first argument of `add_library` —
  which is how a *loadable* display module is spelled. `pandagl` does the same.
- **`if(NOT HAVE_<PKG>) return() endif()`** at the top is the CMake equivalent of
  makepanda's `if not PkgSkip("X"):` block.
- **`CMAKE_INSTALL_DEFAULT_COMPONENT_NAME`** is set/unset around `add_metalib`
  purely so the internal `install(FILES init_header)` at
  `BuildMetalib.cmake:348` lands in the right install component.

**3. Register the directory** in `panda/CMakeLists.txt`, before the metalibs:

```cmake
# Also creates a (loadable-module) metalib.
add_subdirectory(src/vulkandisplay)
```

**4. Expect the link step to be where the trouble is.** The first attempt
compiled all 15 sources and failed to link on `undefined vtable for
SpirVConvertBoolToIntPass`. The cause was *not* a visibility problem, which was
the initial hypothesis — it was that `spirVConvertBoolToIntPass.cxx` existed in
the tree and was compiled by makepanda (it is `#include`d by
`p3shaderpipeline_composite2.cxx`) but was **missing from CMake's explicit
`P3SHADERPIPELINE_SOURCES` list**, so the class was silently absent from
`libpanda`.

That failure mode generalizes, and it is the single most important CMake-specific
gotcha in this chapter:

> **The two build systems' source lists are maintained independently and drift.**
> makepanda discovers sources through checked-in composite files; CMake uses
> hand-written `set(P3X_SOURCES …)` lists. A file added to one and not the other
> compiles under one build system and vanishes under the other, with the symptom
> appearing only at link time in the *first downstream consumer* — potentially
> long after the file was added.

---

## Gotchas

**`CMAKE_BUILD_TYPE` and multi-config generators.** Long-running trap. With
Visual Studio or Xcode, `CMAKE_BUILD_TYPE` is meaningless and `--config`
governs; MSVC defaults to `Debug` when nothing is specified, which silently
gives you `_DEBUG` instead of `NDEBUG`. Several users have settled on
`RelWithDebInfo` "to prevent the dodgy macro flags."

**Library naming differs from makepanda on Windows** — CMake historically built
libraries without the `lib` prefix. If a downstream build script hardcodes
makepanda names, set `CMAKE_SHARED_LIBRARY_PREFIX=lib`.

**Different DLL decomposition.** CMake produces `p3prc.dll` as its own library
rather than folding it into `p3dtoolconfig.dll` as makepanda does, and builds
`p3txafile.dll` rather than linking it into `egg-palettize.exe`. Not a bug —
but it means the two builds' output file lists are not interchangeable.

**`dtool_config.h` contents differ.** `HAVE_STB_IMAGE` is missing from the
CMake-generated header (issue #1700, open); `HAVE_RTTI` has had similar trouble.
If a `#ifdef` behaves differently between the two builds, diff the two generated
`dtool_config.h` files before assuming anything subtler.

**Source layout is stricter.** rdb (2023-02-12): "makepanda doesn't mind that
but CMake doesn't like it" about sources spread across directories. Vendored
third-party trees with their own `CMakeLists.txt` also conflict — Maxwell175 on
Recast/Detour: "I can't just `add_subdirectory` on it since the panda3d cmake
functions start fighting with their CMake files."

**`INTERROGATE_C_INTERFACE` is dead.** The option exists but, as maxrdz found
(2024-01-23), "that option is actually not linked to any process in the CMake
configuration."

**Options that should imply others, don't.** `-DWANT_NATIVE_NET=NO` currently
fails in `pstatclient` on a missing `connectionManager.h`; you must also set
`DO_PSTATS=NO` (issue #1598).

**CMake minimum version has ratcheted** — ≥3.12 for `THIRDPARTY_DIRECTORY`
(policy `CMP0074`), then 3.13, now **3.16** (needed for `enable_language(OBJCXX)`
on Apple).

**In-source builds are refused outright** — `CMAKE_DISABLE_IN_SOURCE_BUILD` and
`CMAKE_DISABLE_SOURCE_CHANGES` are set before `project()`
(root `CMakeLists.txt:1-3`).

**`-rdynamic` is deliberately stripped** (`CompilerFlags.cmake:180-186`) so that
a missing `ENABLE_EXPORTS` surfaces as a real link error instead of silently
working on some platforms.

---

## Platform notes

### macOS
- **Use Apple's clang, not Homebrew's.** rdb (issue #1692): "We do all our
  builds with Apple's clang. I suggest instead installing the XCode Command-Line
  Tools, and uninstalling clang from Homebrew." Homebrew clang produces
  `ld: unknown options: --exclude-libs` because `CMAKE_CXX_COMPILER_ID` comes out
  as `AppleClang` and misses a guard in `dtool/src/prc/CMakeLists.txt`. More
  generally, `-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew` is the lever for
  Homebrew contamination.
- `CMAKE_OSX_DEPLOYMENT_TARGET` defaults to **10.13** (root `CMakeLists.txt:30`).
- **Avoid `-DCMAKE_SYSTEM_NAME=Darwin`** — it triggers a cross-compile path that
  fails early with `No rule to make target 'host_pzip-NOTFOUND'`.
- Universal builds are rough: `-DCMAKE_OSX_ARCHITECTURES="x86_64;arm64"` has
  segfaulted clang where `makepanda --universal` worked.
- **Watch the Python.** CMake's `FindPython` will happily pick a different
  interpreter than the framework Python you run with, and a mismatched extension
  segfaults in `_PyObject_Malloc` at import. Pin it with `-DPython_ROOT_DIR=…`
  (or `-DWANT_PYTHON_VERSION=3.13`) and verify with
  `otool -L <module>.so | grep -i python`.

### Linux
- `-G Ninja` is the recommended generator.
- **manylinux wheel builds need a patch** that may not be upstreamed. The
  failure is `NOT FOUND: PYTHON. Disable HAVE_PYTHON to continue.` in a
  manylinux container; the fix found by germanunkol (2024-12) was to use
  `Development.Module` rather than `Development` in `find_package(Python …)` and
  `Python::Module` in place of `PKG::PYTHON`. Treat as an open workaround —
  check whether your tree already has it before re-deriving it.

### Windows
- `-A x64` on the first configure, always.
- **CMake is how you get a real Visual Studio solution.** rdb (2019-10-08):
  "makepanda.sln isn't an actual VS solution, just something that invokes
  makepanda under the hood… if you want a working VS solution, you should try
  building Panda from the CMake branch." This fixes IntelliSense.
- `HAVE_DX9` is not always autodetected; check the `DIRECT3D9_*` cache variables.
- `FindOpenAL` on the Windows thirdparty tree returns a path with `AL` already
  appended, which breaks every OpenAL include.
- Newer CMake expects `*_ROOT` variables uppercase.

---

## Where to look when it breaks

| Symptom | Look at |
|---|---|
| `dtool_config.h: No such file` | target isn't transitively linking `p3dtoolbase` (`dtool/src/dtoolbase/CMakeLists.txt:78-80`) |
| Duplicate or missing symbols across components | you linked a component instead of its metalib, or added it to two metalibs (`BuildMetalib.cmake:299-317`) |
| `undefined vtable for <class>` | source present in the makepanda composite but absent from CMake's `set(P3X_SOURCES …)` |
| Symbols unexpectedly (in)visible | `-fvisibility=hidden` (`CompilerFlags.cmake:248-253`) + the `IS_COMPONENT` genex (`BuildMetalib.cmake:108-109`) |
| Interrogate chokes on a third-party header | working as designed (`PackageConfig.cmake:186-189`) — add a stub to `dtool/src/parser-inc`, don't un-hide the real include dir |
| `NOT FOUND: X. Disable HAVE_X to continue.` | you forced `HAVE_X=ON` and `find_package` failed |
| Third-party symbols leaking out of a module | the `--exclude-libs` pattern; note `BuildMetalib.cmake:321-327` propagates it to the metalib |
| Configure succeeds, no network | `BUILD_INTERROGATE=OFF` + `INTERROGATE_EXECUTABLE` |
| `Component library targets must be created BEFORE add_metalib` | `add_subdirectory` ordering in `panda/CMakeLists.txt` |
</content>
</invoke>
