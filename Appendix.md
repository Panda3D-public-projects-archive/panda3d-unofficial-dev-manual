# Appendix

Reference material for the rest of the manual: a glossary of the internal terms
every Panda3D engine developer must know, a table of the most useful PRC config
variables for development and debugging, and a curated set of external
resources. Definitions are deliberately short and link to the page that covers
each concept in depth.

## Glossary

**GSG (GraphicsStateGuardian)**
: The abstraction over a single rendering API context (OpenGL, GLES, etc.).
  The GSG translates Panda's `RenderState`/`Geom` into actual API calls and
  owns all per-context resources. See
  [Display & GSG](subsystems/display-and-gsg.md).

**BAM / `.bam`**
: Panda's native **B**inary **A**rchive format — a serialized graph of
  `TypedWritable` objects (models, textures, whole scene graphs) written by
  `BamWriter` and read by `BamReader`. The on-disk format is versioned
  (major.minor; constants in `panda/src/putil/bam.h`). See
  [Cross-cutting concepts §3](cross-cutting-concepts.md).

**PandaNode**
: The base class of every node in the scene graph. It holds children,
  a transform, a `RenderState`, and bounds, but is itself drawable-agnostic
  (geometry lives in `GeomNode`, a subclass). See
  [Scene graph](subsystems/scene-graph.md).

**NodePath**
: A lightweight, copyable *handle* identifying a specific path from a root down
  to a `PandaNode`. Because the same node can appear under multiple parents
  (instancing), most operations (`set_pos`, `reparent_to`, …) are methods on a
  `NodePath`, not the node. See [Scene graph](subsystems/scene-graph.md).

**RenderState / TransformState**
: Immutable, reference-counted, globally-deduplicated objects describing *how*
  (state) and *where* (transform) to render. Because they are immutable and
  interned, identical states share one object, which is what the
  `state-cache` / `transform-cache` config vars manage. See
  [Scene graph](subsystems/scene-graph.md).

**RenderAttrib / RenderEffect**
: A `RenderState` is a set of `RenderAttrib`s — one per renderable property
  (`ColorAttrib`, `TextureAttrib`, `DepthTestAttrib`, …). A `RenderEffect` is a
  per-node effect computed at cull time (e.g. `BillboardEffect`,
  `CompassEffect`) rather than a composable render property. See
  [Scene graph](subsystems/scene-graph.md).

**CullBin**
: A bucket that collects cullable objects and defines their draw order within a
  frame (opaque, transparent, fixed, etc.). Bins are how Panda controls render
  ordering. See [Scene graph](subsystems/scene-graph.md) and the
  [render-order reference](reference/render-order.md).

**GeomVertexData**
: The container of actual vertex data (positions, normals, texcoords, …) laid
  out per a `GeomVertexFormat`. A `Geom` references one `GeomVertexData` plus
  `GeomPrimitive`s that index into it. See
  [Graphics objects](subsystems/graphics-objects.md).

**`PT()` / `CPT()` (PointerTo / ConstPointerTo)**
: Panda's intrusive smart pointers. `PT(Texture)` is `PointerTo<Texture>`;
  `CPT(...)` is the const variant. They increment/decrement the object's own
  `ReferenceCount` so heap objects are freed when the last pointer drops. See
  [Cross-cutting concepts §2](cross-cutting-concepts.md).

**TypeHandle / TypedObject**
: Panda's hand-rolled RTTI. `TypedObject` is the base that knows its own
  `TypeHandle`; `TypeHandle` is a registered, comparable type token used for
  safe downcasts (`DCAST`), BAM factories, and interrogate — instead of C++
  `dynamic_cast`. See [Cross-cutting concepts §1](cross-cutting-concepts.md).

**TypedWritable**
: The base class for any object that can be serialized to BAM. It declares the
  `write_datagram` / `fillin` / read-factory protocol. See
  [Cross-cutting concepts §3](cross-cutting-concepts.md).

**ReferenceCount**
: The mix-in base that gives an object an atomic reference count so it can be
  managed by `PointerTo`. See [Cross-cutting concepts §2](cross-cutting-concepts.md).

**Scene graph vs. data graph**
: The **scene graph** (`PandaNode` tree) describes what to render. The **data
  graph** is a separate graph of `DataNode`s that pumps input data (mouse,
  keyboard, trackers) each frame via the same traversal machinery. See
  [Devices & networking](subsystems/devices-and-networking.md).

**PRC**
: **P**anda **R**untime **C**onfiguration — the `.prc` text files (and
  environment overrides) that set `ConfigVariable*` values at runtime. See
  [dtool](subsystems/dtool.md) and the
  [config-prc reference](reference/config-prc.md).

**interrogate**
: The build-time tool that scans C++ headers and auto-generates the Python
  bindings. The *generator* now lives in the separate
  [`panda3d-interrogate`](https://github.com/panda3d/panda3d-interrogate) repo;
  the runtime support stays in `dtool/src/interrogatedb`. See
  [Cross-cutting concepts §5](cross-cutting-concepts.md).

**`PUBLISHED:`**
: A custom access specifier (alongside `public:`/`private:`) that marks a
  member as *both* public to C++ *and* to be wrapped for Python by interrogate.
  See [Cross-cutting concepts §5](cross-cutting-concepts.md) and the
  [misc & FAQ](misc-and-faq.md).

**Pipeline cycler / CycleData / COW**
: The mechanism that lets the App, Cull, and Draw stages run on different
  threads safely. Mutable per-stage object data lives in a `CycleData` block
  managed by a `PipelineCycler`; readers/writers get a copy-on-write view per
  pipeline stage. See [Cross-cutting concepts §4](cross-cutting-concepts.md).

**AsyncTask**
: A unit of work scheduled by the `AsyncTaskManager` (the C++ side of the task
  system that Python's `taskMgr` wraps). Tasks run once per frame or on a
  schedule. See [Core utilities](subsystems/core-utilities.md) and the
  [direct framework](subsystems/direct-python-framework.md).

**Messenger**
: The Python-side global event bus (`base.messenger`) for publish/subscribe
  events; it sits on top of the C++ `EventQueue`/`EventHandler`. See the
  [direct framework](subsystems/direct-python-framework.md).

**ShowBase**
: The Python class that wires up a running application — the window, the default
  `render`/`render2d` graphs, camera, task manager, and messenger. It is the
  entry point most Panda apps start from. See the
  [direct framework](subsystems/direct-python-framework.md).

**Actor**
: The Python class wrapping an animated character: it loads a model plus its
  animations and exposes playback (`loop`, `play`, control via joints). The C++
  machinery beneath it is the `char`/`chan` subsystem. See
  [Characters & animation](subsystems/characters-and-animation.md).

**Interval**
: A time-parameterized animation primitive (e.g. `LerpPosInterval`) that can be
  sequenced/parallelized to script motion over time. See the
  [direct framework](subsystems/direct-python-framework.md).

**egg format**
: Panda's human-readable text interchange format for models/animations, parsed
  by the `egg` library and converted to a scene graph by `egg2pg`; the
  `pandatool` converters import/export it. See [Egg](subsystems/egg.md) and the
  [egg-syntax reference](reference/egg-syntax.md).

**Multifile / VFS**
: A **Multifile** is Panda's archive container (`.mf`); the **Virtual File
  System** (`VirtualFileSystem`) mounts multifiles and directories into one
  searchable namespace so `load_model("foo")` works whether `foo` is on disk or
  inside an archive. See [Core utilities](subsystems/core-utilities.md).

**DCAST**
: The safe, RTTI-checked downcast macro, `DCAST(Type, ptr)` (defined in
  `panda/src/express/dcast.h`). It returns `nullptr` (or asserts) on a type
  mismatch instead of giving you a bad pointer. See
  [Cross-cutting concepts §1](cross-cutting-concepts.md).

## Key configuration variables

The PRC variables a developer reaches for most. Names and defaults below were
checked against the `config_*.cxx` declarations in the source tree; for the full
catalog and PRC file syntax see the
[config-prc reference](reference/config-prc.md). Set these in a `.prc` file, in
`PRC_PATH`, or via `load_prc_file_data()`.

| Variable | Default | What it does | Declared in / see |
|----------|---------|--------------|-------------------|
| `notify-level-<category>` | `info` (inherited) | Per-subsystem log verbosity: `spam`/`debug`/`info`/`warning`/`error`/`fatal`. `notify-level-<cat>` for one category, `notify-level` for the global default. | `dtool/src/prc/notifyCategory.cxx` |
| `assert-abort` | `false` | On the first failed `nassert*`, abort with a core dump / stack trace instead of continuing. | `dtool/src/prc/config_prc.cxx` |
| `want-pstats` | `false` | Auto-connect to the PStats profiler server at startup. | read at call sites (e.g. `ShowBase.py`); see [Core utilities](subsystems/core-utilities.md) |
| `pstats-host` / `pstats-port` | `localhost` / `5185` | Where the PStats client connects. | `panda/src/pstatclient/config_pstatclient.cxx` |
| `threading-model` | `""` (single-threaded) | Render pipeline threading, e.g. `"Cull/Draw"` to run cull and draw on separate threads. | `panda/src/display/config_display.cxx`; see [Cross-cutting concepts §4](cross-cutting-concepts.md) |
| `support-threads` | `true` | Master switch: if false, Panda refuses to spawn threads even when compiled with thread support. | `panda/src/pipeline/config_pipeline.cxx` |
| `sync-video` | `true` | Sync presentation to the display refresh (vsync). Set `false` to let frame rate run unbounded for benchmarking. | `panda/src/display/config_display.cxx` |
| `load-display` | `*` | Which graphics pipe (display module) to load, e.g. `pandagl`. `*` tries each in `aux-display`. | `panda/src/display/graphicsPipeSelection.cxx`; see [Display & GSG](subsystems/display-and-gsg.md) |
| `aux-display` | (list) | The candidate display modules to try when `load-display` is `*`. | `panda/src/display/graphicsPipeSelection.cxx` |
| `win-size` | `800 600` | Default new-window size (width height). | `panda/src/display/config_display.cxx` |
| `fullscreen` | `false` | Open windows fullscreen by default. | `panda/src/display/config_display.cxx` |
| `framebuffer-multisample` | `false` | Request a multisample-capable framebuffer. | `panda/src/display/config_display.cxx` |
| `multisamples` | `0` | Number of MSAA samples to request (`1` = max available). | `panda/src/display/config_display.cxx` |
| `gl-version` | `""` (any) | Request a specific OpenGL context version; empty means no constraint. | `panda/src/glstuff/glmisc_src.cxx` |
| `gl-debug` | `false` | Enable the GL debug-message callback (more diagnostics via `notify-level-glgsg`, slight cost). | `panda/src/glstuff/glmisc_src.cxx` |
| `basic-shaders-only` | `false` | Disable shader features beyond ~SM3 that are historically unreliable on some drivers. | `panda/src/gobj/config_gobj.cxx` |
| `audio-library-name` | `null` | Which audio backend to load, e.g. `p3openal_audio` or `p3fmod_audio`; `null` disables audio. | `panda/src/audio/config_audio.cxx`; see [Audio](subsystems/audio.md) |
| `model-path` | (empty search path) | Directories searched by `load_model()` and friends. | `panda/src/putil/config_putil.cxx`; see [Core utilities](subsystems/core-utilities.md) |
| `default-model-extension` | `""` | Extension assumed when a model filename has none (e.g. `.egg` or `.bam`). | `panda/src/pgraph/config_pgraph.cxx` |
| `transform-cache` | `true` | Cache deduplicated `TransformState` objects (and inverses). | `panda/src/pgraph/config_pgraph.cxx`; see [Scene graph](subsystems/scene-graph.md) |
| `state-cache` | `true` | Cache deduplicated `RenderState` objects. | `panda/src/pgraph/config_pgraph.cxx` |
| `garbage-collect-states` | `true` | Defer freeing unused `RenderState`/`TransformState` to end-of-frame instead of immediately. | `panda/src/pgraph/config_pgraph.cxx` |
| `text-flatten` | `true` | Flatten generated text geometry rather than keeping a deep node hierarchy. | `panda/src/text/config_text.cxx`; see [Text, GUI & grutil](subsystems/text-gui-grutil.md) |
| `show-frame-rate-meter` | `false` | Display the on-screen frame-rate meter. | `panda/src/framework/config_framework.cxx` |
| `vfs-mount` | (list) | Mount a directory/multifile into the VFS: `vfs-mount <file> <mount-point> [options]`. | `panda/src/express/virtualFileSystem.cxx`; see [Core utilities](subsystems/core-utilities.md) |
| `vfs-case-sensitive` | `true` (debug) / `false` (release) | Whether VFS path lookups are case-sensitive (helps catch case bugs in dev). | `panda/src/express/virtualFileSystem.cxx` |

## External resources

Current, authoritative links. The official, *user-facing* documentation
complements this developer manual: when this manual says "how the engine does
X", the official docs say "how to use X".

- **Official documentation** — <https://docs.panda3d.org> — The official manual
  and tutorials. Versioned; pick the version matching your checkout.
- **API reference** — <https://docs.panda3d.org/1.10/python/reference/index> —
  The full, interrogate-generated class/method reference (Python and C++). The
  single most useful lookup when reading the engine.
- **Main GitHub repository** — <https://github.com/panda3d/panda3d> — The engine
  source (this manual's `dtool` / `panda` / `direct` / `pandatool` trees),
  issues, and pull requests. Where to file bugs and submit patches.
- **`panda3d-interrogate`** — <https://github.com/panda3d/panda3d-interrogate> —
  The standalone binding generator, split out of the main repo. Where to look if
  you are changing *how* the Python bindings are produced (the runtime support
  stays in `dtool/src/interrogatedb`).
- **`panda3d-gltf`** — <https://github.com/panda3d/panda3d-gltf> — The
  separately-maintained glTF importer / runtime loader, distributed as its own
  package rather than in the engine tree.
- **Building from source (official guide)** —
  <https://docs.panda3d.org/1.10/python/introduction/installation-windows> —
  The platform build instructions that match `makepanda`; cross-reference with
  this manual's [misc & FAQ](misc-and-faq.md) build section.
- **Discourse forum** — <https://discourse.panda3d.org> — The long-form
  community forum; ~20 years of archived design discussion, much of it cited
  throughout this manual's subsystem pages.
- **Discord** — <https://discord.gg/UyepkAv> (linked from the website) — Real-time
  community chat, including a developers channel; the fastest way to reach
  maintainers about engine internals.
- **Contributing guide** — <https://github.com/panda3d/panda3d/blob/master/CONTRIBUTING.md>
  and the [coding-style reference](reference/coding-style.md) — Conventions for
  patches: coding style, commit hygiene, and the CLA.

## Maintainer notes

### 2026 - the decade update

It's been 10 years and 27 days since I last updated this manual. Lately I've been
working intensely with Panda's source code, so I decided to revamp it with the help of LLMs.

The original content was a best-effort collection from the source code, the forums, and IRC.
Today's update isn't all that different in spirit, except that now we have LLMs to help with
gathering and referencing the material.

Over the years I got a few pings that this manual was a step in the right direction but too
unfinished. I hope these new efforts close the gap to something genuinely usable, and that you
find the material helpful. As always, all of this content is CC0, public domain, so you can use
it however you like.

Please don't hesitate to submit corrections, critiques, or any other comments.

Best,
Tom

### 2014 - extracted from now deleted old/....odt

```
Hi, I'm frainfreeze.
This manual was made so I don't forget all the useful info other Panda3D developers told me.
I hope it will scale and eventually become big enough to be called official and to actually help someone. 
I want to excuse for my poor English.
Huge, tera, extra , super 'thank you' to Panda community especially rdb who actively maintains Panda and of course others behind the scenes.

Preface
Book is organized in tree structure that follows panda 1.9 source tree.
It's bad, messy, confusing.
It also contains doc strings and comments from scripts.
Manual is built from several parts.
1. 	Source structured. It follows structure of panda source and notes are sorted in same way, 	under each item in tree.
2.	File formats, specifications and similar
3. 	Miscellaneous and F.A.Q.
4.	Appendix (Can contain code snippets or even whole scripts)


Note:
Maunal may be from 2014 but contents are much older. Some parts date from 2002 and loots of information might be deprecated. However most of Part 1 should be up to date at moment of writing.
```

----

Ok, bye now!