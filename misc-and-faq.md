# Miscellaneous & developer FAQ

Answers to the questions a *new engine contributor* actually asks — how to
build, where things live, how the C++/Python layer is wired, and how to debug
the engine itself. This is **not** a game-making FAQ; for that, see the
[official user manual](https://docs.panda3d.org/). Almost every answer links to
a deeper page — start with [Cross-cutting concepts](cross-cutting-concepts.md)
and the [Source tree](source-tree.md) map.

## Building & setup

### How do I build Panda3D from source?

There are two build systems in the tree, and they are not equivalent:

- **`makepanda`** (`makepanda/makepanda.py`) — the canonical, fully supported
  build. It is a hand-written Python build driver (no make/CMake), produces a
  self-contained `built/` directory, and is what the official binaries and
  wheels are made with. The simplest invocation is:

  ```sh
  python makepanda/makepanda.py --everything --installer
  ```

  `--everything` enables every third-party package it can find; `--nothing`
  disables them all (then add `--use-PKG` for the ones you want).

- **`CMakeLists.txt`** (top-level + `cmake/`) — a newer, community-driven CMake
  build. It works and is increasingly used, but is not yet the build the
  project ships releases with. Out-of-source builds are enforced
  (`CMAKE_DISABLE_IN_SOURCE_BUILD`), and the default build type is `Standard`
  (see the optimize question below).

When in doubt, use `makepanda` — it is the one the build/CI docs and the
[official "building from source" guide](https://docs.panda3d.org/1.10/python/introduction/installation-windows)
assume. See [Project health, ecosystem & deployment](project-and-ecosystem.md)
for the build/packaging footguns.

### How do I do a debug or `optimize=N` build?

With makepanda, optimization level is a single flag, `--optimize X`, where
`X` is `1`..`4` (default `3`):

| Level | Meaning |
|-------|---------|
| `1` | Full debug: assertions on, `NDEBUG` off, no inlining, `_DEBUG`. |
| `2` | Development: assertions on, some optimization. |
| `3` | **Default.** Release-ish: optimized, assertions still compiled in. |
| `4` | Production: assertions and Notify spam compiled *out*, max optimization. |

So a debugging build is `python makepanda/makepanda.py --everything --optimize 1`.
Under CMake the equivalent is the build type: `Debug`, `Standard` (the default,
≈ optimize 3) and `Release` (≈ optimize 4), set via
`-DCMAKE_BUILD_TYPE=Debug`.

> **Why "assertions compiled out" matters:** at `--optimize 4` the `nassertr` /
> `nassertv` macros expand to nothing, so a build that "works" at `-O4` may be
> silently skipping validation that fires at `-O1`. When chasing a heisenbug,
> always reproduce at `--optimize 1` first.

### How do I build with or without a subsystem (e.g. `--no-python`, no FMOD)?

makepanda exposes one `--use-PKG` / `--no-PKG` pair **per third-party package**
(run `makepanda --help` to see the live list — it is generated from the
`PkgListSet([...])` call near the top of `makepanda/makepanda.py`). Common ones:

- `--no-python` — build the C++ engine with **no** Python bindings at all.
- `--no-fmodex` / `--use-openal` — pick your audio backend (see [Audio](subsystems/audio.md)).
- `--no-bullet`, `--no-ode`, `--no-egg`, `--no-assimp`, `--no-gles2`, …

CMake uses the inverse convention: per-package `HAVE_<PKG>` options
(`cmake/macros/PackageConfig.cmake`) plus the top-level `BUILD_DTOOL`,
`BUILD_PANDA`, `BUILD_DIRECT`, `BUILD_PANDATOOL`, `BUILD_CONTRIB` toggles.

### Where do build outputs go?

makepanda writes everything into a `built/` directory at the repo root
(override with `--outputdir X`): `built/bin`, `built/lib`, `built/include`,
`built/panda3d` (the importable Python package), and `built/models`. Nothing is
written into the source tree. CMake builds into your chosen out-of-source build
directory and install prefix.

## The C++/Python binding layer

### Where is `interrogate`, the binding generator?

The **interrogate program itself was moved out** of the main repository into the
separate **[`panda3d-interrogate`](https://github.com/panda3d/panda3d-interrogate)**
repo. What remains in this tree is the *runtime* support that the generated
bindings link against: **`dtool/src/interrogatedb`** (e.g. `py_panda.h`,
`interrogate_request.h`). So if you are debugging *how a binding behaves at
runtime*, look in `interrogatedb`; if you are changing *how bindings are
generated*, that is the other repo. The conceptual model — how interrogate
scans headers and emits wrappers — is covered in
[Cross-cutting concepts §5](cross-cutting-concepts.md) and the
[dtool subsystem page](subsystems/dtool.md).

### How do I expose a new C++ method to Python?

Put the method under a **`PUBLISHED:`** access specifier in the class header
(it behaves like `public:` to C++ but additionally tells interrogate to wrap
it). Interrogate then generates the Python wrapper automatically at build time —
you do not hand-write any binding glue. See `panda/src/skel/typedSkel.h` for a
minimal example, and [Cross-cutting concepts §5](cross-cutting-concepts.md) for
how `PUBLISHED:` flows through interrogate.

### Why are there both `camelCase` and `snake_case` names (e.g. `setPos` and `set_pos`)?

Panda's C++ API is `snake_case`. Interrogate generates **both** a `snake_case`
and a legacy `camelCase` Python name for every published method, so `set_pos`
and `setPos` resolve to the same wrapper. New code should use `snake_case`;
the `camelCase` aliases exist for backward compatibility with old tutorials and
code. This is an interrogate feature, not duplicated source — details in
[Cross-cutting concepts §5](cross-cutting-concepts.md).

## Working in the code

### How do I add a new config variable?

Declare a `ConfigVariableBool` / `Int` / `Double` / `String` / `Filename` /
`Enum` object, conventionally in the owning module's `config_<module>.cxx`
(e.g. `panda/src/display/config_display.cxx`). The constructor takes the PRC
name, a default, and a doc string:

```cpp
ConfigVariableBool my_feature
  ("my-feature", false,
   PRC_DESC("Enables my experimental feature."));
```

The variable is then readable from C++ and overridable from any `.prc` file or
`--override` build flag. See the [dtool subsystem page](subsystems/dtool.md) for
the PRC system, and the [config-prc reference](reference/config-prc.md) for the
existing variables.

### How do I make a class serializable to `.bam`?

Implement the `TypedWritable` BAM protocol and register a factory:

1. `register_with_read_factory()` — registers your type with `BamReader`
   (call it once, usually from the module's `init_lib*()`).
2. `write_datagram(BamWriter *, Datagram &)` — serialize your fields (chain up
   to the base class first).
3. a static `make_from_bam(...)` factory plus `fillin(DatagramIterator &,
   BamReader *)` — deserialize.

`panda/src/pgraph/pandaNode.cxx` is a canonical, real-world example
(`PandaNode::register_with_read_factory`, `::write_datagram`, `::fillin`). The
full protocol, plus BAM versioning rules, is in
[Cross-cutting concepts §3](cross-cutting-concepts.md).

### How does Panda's type system / `DCAST` work?

Panda has a **hand-rolled RTTI** system (`TypeHandle` + `TypedObject`) instead
of relying on C++ `dynamic_cast`, because it predates reliable cross-DLL RTTI
and needs to interoperate with BAM and interrogate. `DCAST(Type, ptr)` (defined
in `panda/src/express/dcast.h`) is the safe downcast: it checks the
`TypeHandle` and returns `nullptr` (or asserts) on mismatch. Every engine class
calls `register_type(...)` in an `init_type()` method. See
[Cross-cutting concepts §1](cross-cutting-concepts.md).

### How do I add a whole new subsystem?

Copy the **`panda/src/skel`** skeleton directory. It is a deliberately minimal,
working module that demonstrates the full boilerplate a Panda subsystem needs:
`config_skel.cxx` (config + init), `typedSkel` (a `TypedObject` with RTTI,
`PUBLISHED:` methods, and `init_type`), `basicSkel`, and a `composite` source
file. Rename it, wire it into the build (`makepanda` package list / CMake), and
you have a correctly-registered subsystem to grow from.

## Debugging the engine

### How do I turn on notify/debug output for a category?

Every subsystem has a Notify *category* (e.g. `display`, `gobj`, `loader`,
`pgraph`). Set its severity with a PRC variable:

```
notify-level-display debug
notify-level-gobj spam
```

Levels are `spam`, `debug`, `info`, `warning`, `error`, `fatal`. The mechanism
lives in `dtool/src/prc/notifyCategory.*` and `notify.cxx`. There is also a
global `notify-level` fallback. At `--optimize 4`, `spam`/`debug` calls are
compiled out entirely.

### What is PStats and how do I add a timer?

**PStats** is Panda's built-in real-time performance profiler — a separate GUI
client (`pstats`) connects over a socket to your instrumented app and graphs
per-frame timings. Turn it on with `want-pstats true`. To time a region of your
own code, add a `PStatCollector` (declared in
`panda/src/pstatclient/pStatCollector.h`):

```cpp
static PStatCollector my_collector("App:My subsystem:My phase");
PStatTimer timer(my_collector);   // times the enclosing scope
```

The colon-delimited name builds the collector hierarchy shown in the GUI. See
[Core utilities](subsystems/core-utilities.md) for the surrounding profiling
infrastructure.

### Where do assertions come from (the C++ asserts that surface in Python)?

The engine validates with the `nassertr` / `nassertv` family of macros (not raw
`assert`). On failure they route through Notify, print a message with file and
line, and — depending on the `assert-abort` config var (default `false`,
declared in `dtool/src/prc/config_prc.cxx`) — either abort the process or
continue after raising. In Python, a tripped C++ assertion typically surfaces as
an `AssertionError`. Because these are compiled out at `--optimize 4`, reproduce
assertion-related bugs at a lower optimization level.

## Navigating the source

### Where does *X* live?

Start with the [Source tree](source-tree.md) chapter — it gives a one-line
description of **every** directory under `dtool/`, `panda/src/`, `direct/src/`,
and `pandatool/src/`. For the major clusters, jump straight to the matching
[subsystem deep-dive](subsystems/index.md):

| If you're touching… | Read |
|---------------------|------|
| The type system, PRC config, interrogate runtime | [dtool](subsystems/dtool.md) |
| Nodes, `NodePath`, render state, culling | [Scene graph](subsystems/scene-graph.md) |
| Geoms, vertex data, textures, shaders | [Graphics objects](subsystems/graphics-objects.md) |
| The GSG / OpenGL backend / windowing | [Display & GSG](subsystems/display-and-gsg.md) |
| Characters, joints, animation | [Characters & animation](subsystems/characters-and-animation.md) |
| The `.egg` library and loader | [Egg](subsystems/egg.md) |
| Collisions, Bullet, ODE, particles-physics | [Collision & physics](subsystems/collision-and-physics.md) |
| Tasks, events, the pipeline, math | [Core utilities](subsystems/core-utilities.md) |
| Audio backends and movie decoding | [Audio](subsystems/audio.md) |
| `ShowBase`, `Actor`, intervals, FSMs (Python) | [direct framework](subsystems/direct-python-framework.md) |
| Asset converters / palettizer / bam tools | [pandatool](subsystems/pandatool.md) |

### How is the source tree organized at the top level?

Four sibling trees, built in dependency order: **`dtool`** (foundation: type
system, config, low-level utilities — no scene graph), **`panda`** (the engine
proper, under `panda/src/`), **`direct`** (the Python-side framework layered on
top), and **`pandatool`** (offline asset-pipeline tools). `makepanda` and
`cmake` drive the build; `contrib`, `samples`, `models`, and `tests` round out
the repo. Full map in the [Source tree](source-tree.md) chapter.
