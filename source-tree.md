# Source tree #

This chapter is a developer's map of the Panda3D source tree.

## contrib ##
Code contributed by the community. This code is usually not maintained
by the core developers but by the respective community contributors. Optional;
not built by default.

## direct ##
The **Python "show" framework** layered on top of the C++ engine. It contains
nearly all of Panda's Python code (plus a little supporting C++). This is what
sets up and initializes Panda from Python (`ShowBase`), and supplies the
mid-level authoring systems: actors, the interval (tweening) system, the task
manager, finite state machines, the DirectGui widgets, the Distributed
networking architecture, and the `directtools`/`tkpanels` editing widgets.
See **[The direct Python framework](subsystems/direct-python-framework.md)**.

## dmodels ##
Models processed by makepanda that still need conversion to `.egg` at build
time. Origin is largely the historical Disney/CMU asset set. (Present in some
checkouts/branches; not a source-code directory.)

## dtool ##
The **foundation layer** every other Panda library is built on: the
hand-rolled type system (`TypeHandle`/`TypeRegistry`), memory management, the
platform/threading primitives, the `Filename`/path utilities, and the PRC
**configuration system** (`ConfigVariable*`). It also contains `interrogatedb`,
the runtime support for the auto-generated Python bindings. (The `interrogate`
*tool itself* was moved out of this tree into the separate
`panda3d-interrogate` repo.) See **[dtool / interrogate / config](subsystems/dtool.md)**
and the **[Cross-cutting concepts](cross-cutting-concepts.md)** chapter.

## makepanda ##
Panda3D's self-contained build system (`makepanda.py` / `makepandacore.py`).
The newer CMake build lives in `CMakeLists.txt` + `cmake/`.
See **[Building Panda3D (makepanda)](building-and-makepanda.md)** for how the
build graph, OPTS tags, interrogate flow, and library integration work.

## models ##
Some free models for use in the samples. Origin is largely CMU.

## panda ##
The **low-level 3D engine**, primarily C++. This is the bulk of the engine:
the scene graph, the rendering pipeline and GSG backends, geometry/textures,
characters & animation, audio, collision/physics, the data graph and input
devices, networking, text/GUI, and the core utility/serialization libraries.
Each subdirectory under `panda/src/` is detailed below.

## pandatool ##
Standalone **command-line asset-pipeline tools**: model-format converters
(`fltegg`, `lwoegg`, `daeegg`, `objegg`, `xfileegg`, `vrmlegg`, `assimp`),
the texture palettizer (`egg-palettize`), `bam2egg`/`egg2bam`, the PStats
server, and the various egg-processing programs.
See **[pandatool (asset pipeline)](subsystems/pandatool.md)**.

## samples ##
Runnable sample programs demonstrating engine features.

----------

# panda/src directories #

The directories under `panda/src/` make up the C++ engine. They are grouped
below by subsystem; the *(→ page)* link points to the deep-dive that documents
the central classes, inheritance, entry points, and gotchas.

## Scene graph & rendering core

### pgraph ###
The heart of Panda: the scene-graph engine. Defines `PandaNode` (the base
node), `NodePath` (the handle used to navigate/manipulate the graph), and the
immutable, shared **state objects** — `RenderState`, `TransformState`,
`RenderAttrib`/`RenderEffect` — that are composed along the graph. Also defines
the `Loader`, `CullTraverser` integration, and the `SceneGraphReducer`
flatten/optimize machinery. *(→ [Scene graph](subsystems/scene-graph.md))*

### pgraphnodes ###
The concrete `PandaNode` subclasses that aren't part of the bare graph core:
the `Light` family (`DirectionalLight`, `PointLight`, `Spotlight`,
`RectangleLight`, `SphereLight`), `LODNode`, `SequenceNode`, `SelectiveChildNode`,
`CallbackNode`, `ComputeNode`, and the fog/shader-generator nodes.
*(→ [Scene graph](subsystems/scene-graph.md))*

### cull ###
The cull traversal: `CullTraverser` collects the visible geometry and its
composed state into `CullableObject`s, sorts them into `CullBin`s (state-sorted,
back-to-front, fixed, etc.), and removes redundant state changes before the draw
traversal hands them to the GSG. This is where render order and depth-sorting
are decided. *(→ [Scene graph](subsystems/scene-graph.md))*

## Graphics objects & rendering backends

### gobj ###
The device-independent representation of renderable resources, *before* the GSG
turns them into GPU objects: `Geom` and `GeomPrimitive` (the drawables),
`GeomVertexData`/`GeomVertexFormat`/`GeomVertexArrayData` (the vertex-buffer
layer), `Texture`, `Shader`, `SamplerState`, `Material`, and `TextureStage`.
*(→ [Graphics objects](subsystems/graphics-objects.md))*

### gsgbase ###
The minimal base class `GraphicsStateGuardianBase` (plus `GraphicsOutputBase`),
defined here to break the cyclic dependency between `gobj`/`pgraph` (which need
to refer to "the GSG") and the full `display` GSG (which needs `gobj`/`pgraph`).
*(→ [Display & GSG backends](subsystems/display-and-gsg.md))*

### display ###
The abstract display layer: `GraphicsPipe`, `GraphicsEngine`,
`GraphicsStateGuardian`, `GraphicsOutput` and its subclasses `GraphicsWindow`
and `GraphicsBuffer`, plus `DisplayRegion`. `GraphicsEngine::render_frame()`
drives the whole per-frame App→Cull→Draw pipeline across every window/buffer.
*(→ [Display & GSG backends](subsystems/display-and-gsg.md))*

### glstuff ###
The shared, template-based OpenGL backend. `glstuff` is **not** compiled on its
own; it is a set of templated `.h`/source files (`glGraphicsStateGuardian_src.*`
etc.) that are `#include`d with different macro definitions by `glgsg` (desktop
GL), `gles2gsg`/`glesgsg` (mobile GLES), giving one source of truth for the GL
rendering logic. *(→ [Display & GSG backends](subsystems/display-and-gsg.md))*

### glgsg ###
The desktop-OpenGL instantiation of `glstuff` — it defines the macros and
compiles `glstuff` into the concrete `GLGraphicsStateGuardian`.
*(→ [Display & GSG backends](subsystems/display-and-gsg.md))*

### glesgsg / gles2gsg ###
The OpenGL ES 1.x and ES 2.x instantiations of `glstuff` for
mobile/embedded GPUs. Same pattern as `glgsg` with different macros.
*(→ [Display & GSG backends](subsystems/display-and-gsg.md))*

### dxgsg9 ###
The Direct3D 9 graphics-state-guardian. Handles all communication with the
DirectX 9 backend and manages state to minimize redundant state changes. Legacy;
desktop GL is the primary backend today.

### tinydisplay ###
A built-in **software renderer** (derived from TinyGL). It implements the GSG
interface entirely on the CPU, so Panda can render with no GPU/driver — useful
for headless rendering, CI, and as a reference GSG.
*(→ [Display & GSG backends](subsystems/display-and-gsg.md))*

### Platform display modules

These provide the OS-specific window creation and GL-context glue. Each
implements a `GraphicsPipe`/`GraphicsWindow` (and often a GL display) for one
platform:

- **cocoadisplay** — macOS native (Cocoa/NSWindow) window + GL context.
  *(→ [Display & GSG backends](subsystems/display-and-gsg.md))*
- **cocoagldisplay** — macOS Cocoa + OpenGL specifics.
- **x11display** — X11/Xlib windows on Linux/Unix (replaces the old GLUT path).
  *(→ [Display & GSG backends](subsystems/display-and-gsg.md))*
- **glxdisplay** — GLX (OpenGL-on-X11) context creation.
- **windisplay** — Win32 native window creation (`WinGraphicsWindow`).
  *(→ [Display & GSG backends](subsystems/display-and-gsg.md))*
- **wgldisplay** — Windows WGL (OpenGL-on-Win32) context creation.
- **egldisplay** — EGL context creation (used with GLES on Linux/mobile/headless).
  *(→ [Display & GSG backends](subsystems/display-and-gsg.md))*
- **webgldisplay** — WebGL display backend for Emscripten/browser builds.
- **android / androiddisplay** — Android platform abstraction and display backend.
- **iphone / iphonedisplay** — iOS platform abstraction and display backend (legacy).

## Geometry, models & images

### egg ###
The "egg library": in-memory classes (`EggData`, `EggGroup`, `EggPrimitive`,
`EggVertex`, …) that read, write, and manipulate `.egg` files. It knows nothing
about the scene graph — it lives in its own world. *(→ [Egg library & loader](subsystems/egg.md))*

### egg2pg ###
The "egg loader": converts the `EggData` structure produced by the `egg`
library into a renderable `PandaNode` scene graph (`EggLoader`,
`CharacterMaker`, `AnimBundleMaker`). After conversion the in-memory egg data
is discarded unless you keep it yourself. *(→ [Egg library & loader](subsystems/egg.md))*

### pnmimage ###
Reads and writes image files and provides the `PNMImage` class — an in-memory
image that is laid out (almost) uniformly regardless of channel count/bit depth,
which is what lets utilities like `PNMPainter` work on any image type. Also
`PfmFile` (portable float-map images). *(→ [Egg library & loader](subsystems/egg.md))*

### pnmimagetypes ###
The concrete file-format readers/writers plugged into `pnmimage`: PNG, JPEG,
TIFF, BMP, TGA, SGI, EXR, PFM, etc. Many are gated by `HAVE_*` build flags.
*(→ [Egg library & loader](subsystems/egg.md))*

### collada ###
COLLADA (`.dae`) support classes (when built). The primary `.dae`→scene-graph
path goes through `pandatool`'s `daeegg` converter.

## Characters & animation

### char ###
The renderable character layer: `Character` (a `PandaNode`) and its
`CharacterJoint`/`CharacterSlider` skeleton, plus the `JointVertexTransform`/
`CharacterVertexSlider` that bind geometry to joints for skinning and morphs.
*(→ [Characters & animation](subsystems/characters-and-animation.md))*

### chan ###
The engine-agnostic **animation-channel** library: the `PartBundle`/`MovingPart`
(animatable) hierarchy and the parallel `AnimBundle`/`AnimChannel` (keyframe
data) hierarchy, the binding machinery that connects them, and `AnimControl`
playback. A support library for `char` and anything whose values change over
time. *(→ [Characters & animation](subsystems/characters-and-animation.md))*

### parametrics ###
Parametric curves and surfaces: the `ParametricCurve` family (Hermite/NURBS
motion paths) and the separate, newer NURBS evaluator that renders curves and
surfaces as geometry via `RopeNode`/`SheetNode`.
*(→ [Characters & animation](subsystems/characters-and-animation.md))*

## Collision & physics

### collide ###
The native collision system: `CollisionSolid` shapes, `CollisionNode`s in the
graph, the `CollisionTraverser` that detects hits and packages them as
`CollisionEntry`s, and the `CollisionHandler` family that responds. Detection +
dispatch only — no force integration. *(→ [Collision & physics](subsystems/collision-and-physics.md))*

### physics ###
Panda's original lightweight native physics: **point masses with forces** and
an Euler integrator (`PhysicsManager`, `Physical`, `PhysicsObject`,
`LinearForce`/`AngularForce`). The engine behind particle systems; no rigid
bodies or constraints. *(→ [Collision & physics](subsystems/collision-and-physics.md))*

### bullet ###
The wrapper around the **Bullet** rigid-body/soft-body engine. `BulletWorld`
owns a `btDiscreteDynamicsWorld`; Panda node subclasses (e.g.
`BulletRigidBodyNode`) wrap Bullet collision objects and live in the scene
graph, with transforms synced both ways each step. The recommended physics
engine for new projects. *(→ [Collision & physics](subsystems/collision-and-physics.md))*

### ode ###
The wrapper around the **Open Dynamics Engine**. Unlike Bullet, the ODE classes
are plain `TypedObject`s holding raw ODE handles — *not* scene-graph nodes — so
you sync transforms to your `NodePath`s yourself. Functional but the
less-polished option. *(→ [Collision & physics](subsystems/collision-and-physics.md))*

### physx ###
Legacy NVIDIA PhysX wrapper (largely historical/unbuilt on modern checkouts).

## Core utilities, serialization & threading

### putil ###
"Panda utilities": the core object-management machinery — most importantly the
**BAM serialization system** (`BamReader`/`BamWriter`/`TypedWritable`/the
`Factory`), plus the global `ClockObject`, bit masks, the button registry, and
the copy-on-write base classes. *(→ [Core utilities](subsystems/core-utilities.md))*

### express ###
The lowest-level support library (depended on by everything): the byte-level
`Datagram` serialization primitives, the reference-counting/smart-pointer
machinery (`ReferenceCount`, `PointerTo`, weak pointers), `Filename`, the
**virtual file system**, and stream compression/encryption/hashing.
*(→ [Core utilities](subsystems/core-utilities.md))*

### pipeline ###
Panda's threading abstraction (`Thread`, `Mutex`, condition variables, with
true-thread / "simple" cooperative / dummy back-ends) **and** the copy-on-write
**pipeline cycler** that lets the app thread mutate state while Cull/Draw read a
stable snapshot. *(→ [Core utilities](subsystems/core-utilities.md))* and the
**[Cross-cutting concepts](cross-cutting-concepts.md)** chapter.

### event ###
Two systems: the name-based **event** bus (`throw_event`, `EventQueue`,
`EventHandler` — `base.messenger`'s C++ side) and the **task** scheduler
(`AsyncTask`, `AsyncTaskManager`, `AsyncTaskChain`, `AsyncFuture` — `taskMgr`'s
C++ side). *(→ [Core utilities](subsystems/core-utilities.md))*

### linmath ###
The linear-algebra library: 2/3/4-vectors and points, 3×3/4×4 matrices,
quaternions, and coordinate-system handling, implemented for both `float` and
`double` via a header-reinclude-with-macros trick rather than C++ templates.
*(→ [Core utilities](subsystems/core-utilities.md))*

### mathutil ###
Geometric algorithms on top of `linmath`: the **bounding-volume** family used
for culling and collision broad-phase, `Plane`/`Frustum`/`Parabola`, polygon
triangulation, Perlin noise, a Mersenne-Twister RNG, and the FFT animation
compressor. *(→ [Core utilities](subsystems/core-utilities.md))*

### pandabase ###
A tiny foundational header layer (`pandabase.h` and friends) providing the
common includes/macros shared across the `panda` tree.

## Data graph, input devices & networking

### device ###
Input-device support: the `InputDevice` abstraction (gamepads, joysticks,
3D trackers, steering wheels), the per-platform device managers
(`InputDeviceManager` + Linux evdev / Windows raw-input/XInput / macOS IOKit
back-ends), and the `ClientBase` family for external device servers.
*(→ [Devices & networking](subsystems/devices-and-networking.md))*

### dgraph ###
The **data graph**: a second graph (distinct from the scene graph) of
`DataNode`s wired input-to-output, traversed once per frame by
`DataGraphTraverser` to flow raw input data (mouse, keyboard, trackers) through
transformers toward the scene. *(→ [Devices & networking](subsystems/devices-and-networking.md))*

### tform ###
Data-graph transformer nodes: `Trackball`, `DriveInterface`, `MouseWatcher`,
`ButtonThrower`, `Transform2SG` — they convert raw device data (from `dgraph`)
into something useful (camera motion, GUI region hits, thrown events).
*(→ [Devices & networking](subsystems/devices-and-networking.md))*

### net ###
The high-level networking layer built on a connection abstraction:
`ConnectionManager`, `Connection`, `ConnectionReader`/`ConnectionWriter`,
`ConnectionListener`, and `NetDatagram` (message-oriented TCP/UDP).
*(→ [Devices & networking](subsystems/devices-and-networking.md))*

### nativenet ###
The low-level socket layer beneath `net`: the `Socket_IP` family
(`Socket_TCP`, `Socket_UDP_Incoming`/`Outgoing`, `Socket_TCP_Listen`) plus the
`select()`/`poll()` wrappers. *(→ [Devices & networking](subsystems/devices-and-networking.md))*

### downloader ###
Asynchronous HTTP and file transfer: `HTTPClient`/`HTTPChannel`, the
`VirtualFileMountHTTP` (mount a URL into the VFS), the multifile patcher/
extractor/decompressor, and `URLSpec`. Used by the runtime model downloader
and the SSL-backed networking. *(→ [Devices & networking](subsystems/devices-and-networking.md))*

### downloadertools ###
Small command-line utilities built on `downloader` (e.g. `pdecrypt`/`pencrypt`,
multifile helpers).

### vrpn ###
The client glue for the **VRPN** library (Virtual-Reality Peripheral Network):
`VrpnClient` + `Vrpn{Tracker,Button,Analog,Dial}Device` for reading networked
VR trackers/buttons into the data graph. *(→ [Devices & networking](subsystems/devices-and-networking.md))*

## Text, GUI & rendering utilities

### text ###
Renderable text: `TextNode`, dynamic FreeType fonts (`DynamicTextFont` +
`DynamicTextPage` glyph atlas), static egg fonts (`StaticTextFont`), the
`TextAssembler` line-layout engine, and optional HarfBuzz shaping.
*(→ [Text, GUI, grutil & particles](subsystems/text-gui-grutil.md))*

### pnmtext ###
The lower-level FreeType wrapper (`FreetypeFont`/`FreetypeFace`,
`PNMTextMaker`) that rasterizes glyphs into `PNMImage`s — shared by `text` and
by font tools. *(→ [Text, GUI, grutil & particles](subsystems/text-gui-grutil.md))*

### pgui ###
The **C++ GUI widget layer** that DirectGui sits on: `PGItem` (the base
interactive node), `PGButton`, `PGEntry`, `PGSliderBar`, `PGScrollFrame`,
`PGVirtualFrame`, and the `PGTop`/`PGMouseWatcher*` plumbing.
*(→ [Text, GUI, grutil & particles](subsystems/text-gui-grutil.md))*

### grutil ###
"Graphics utilities": assorted renderable helpers — `MeshDrawer`/`MeshDrawer2D`,
`GeoMipTerrain`, `ShaderTerrainMesh`, `MovieTexture` (video-on-a-texture),
`CardMaker`, `LineSegs`, `FrameRateMeter`, `RigidBodyCombiner`, `FisheyeMaker`.
*(→ [Text, GUI, grutil & particles](subsystems/text-gui-grutil.md))*

### particlesystem ###
The C++ particle engine (built on `physics`): `ParticleSystem` plus the
emitter/factory/renderer families that control how particles spawn, behave, and
draw. (The Python wrapper is in `direct/src/particles`.)
*(→ [Text, GUI, grutil & particles](subsystems/text-gui-grutil.md))*

### distort ###
Non-linear projection / lens-distortion effects: `FisheyeLens`,
`CylindricalLens`, `OSphereLens`/`PSphereLens`, `NonlinearImager`, and
`ProjectionScreen` (for dome/multi-projector rendering).
*(→ [Text, GUI, grutil & particles](subsystems/text-gui-grutil.md))*

## Media decoding

### movies ###
The codec-abstraction / raw-media-streaming layer: `MovieAudio`/
`MovieAudioCursor` and `MovieVideo`/`MovieVideoCursor` turn files into decoded
PCM samples and video frames. In-tree decoders cover WAV/Vorbis/Opus/FLAC; the
audio backends and `MovieTexture` consume the cursors. *(→ [Audio](subsystems/audio.md))*

### ffmpeg ###
The optional FFmpeg-backed `movies` decoder. It registers itself as the
catch-all (`*`) audio/video type, which is why formats the in-tree decoders
don't handle (MP3/AAC/MP4/…) still play. *(→ [Audio](subsystems/audio.md))*

## Audio

### audio ###
The backend-agnostic audio abstraction: `AudioManager` (factory + mixer/3D
listener) and `AudioSound` (a playable handle), the always-available `Null*`
fallback, the runtime backend-selection loader, and `FilterProperties` (DSP
chain description). *(→ [Audio](subsystems/audio.md))*

### audiotraits ###
The two concrete audio backends, each a separately-loadable library:
**OpenAL** (the default, open-source) and **FMOD** (proprietary). Selected at
runtime by the `audio-library-name` config var. *(→ [Audio](subsystems/audio.md))*

## Frameworks & instrumentation

### framework ###
`PandaFramework`/`WindowFramework`: a minimal C++ harness for opening a window
and displaying geometry without the Python `direct` layer. Handy for C++-only
demos and as the base of the `pandatool` viewers.

### pstatclient ###
The **PStats** client instrumentation: the `PStatClient`, `PStatCollector`, and
`PStatTimer` macros sprinkled through the engine that report per-frame timing to
the external PStats server (`pandatool/src/pstatserver`). The first place to
look when adding performance counters.

### recorder ###
The session recorder: `RecorderController` + recorder classes
(`MouseRecorder`, …) that capture input/event streams to a file for
deterministic playback and regression testing.

### vision ###
Computer-vision/AR support: webcam capture (`WebcamVideo`) and AR-marker
tracking (ARToolKit/OpenCV-backed), exposed as `MovieVideo` sources.

## Support, scaffolding & misc

### configfiles ###
Default `.prc` configuration files and housekeeping files shipped with Panda.

### dconfig / doc ###
`doc/` holds developer documentation notes that don't fit a single package
(surfaced in the [File formats & reference](reference/index.md) part of this manual).

### gsgbase / pandabase ###
Tiny dependency-breaking base layers (see above under their subsystem groups).

### skel ###
A minimal **skeleton package** — a copy-paste template showing the canonical
file layout (`config_*.cxx`, a class with `.h`/`.cxx`/`.I`, `CMakeLists.txt`)
for adding a brand-new C++ subsystem.

### testbed ###
Small C++ test programs that link against `framework`.

----------

# dtool/src directories #

See **[dtool / interrogate / config](subsystems/dtool.md)** for the full deep-dive.

- **dtoolbase** — the absolute base: `TypeHandle`/`TypeRegistry` (the RTTI
  system), `MemoryHook`/allocators, atomics and the platform/threading macros.
- **dtoolutil** — `Filename`, `DSearchPath`, `ExecutionEnvironment`,
  `PandaSystem`, the buffered file streams and Unicode/text encoders.
- **prc** — the PRC **configuration system**: `ConfigVariable*`,
  `ConfigDeclaration`/`ConfigPage`/`ConfigPageManager`, and PRC signing keys.
- **dconfig** — the older `DConfig`/`DToolConfigure` configuration macros that
  predate (and bridge to) `prc`.
- **interrogatedb** — the **runtime** support for the generated Python bindings
  (`Dtool_PyTypedObject`, the `interrogate_request` query API). The
  binding-*generator* tool now lives in the separate `panda3d-interrogate` repo.
- **prckeys** — the PRC signing-key tooling (`make-prc-key`).
- **parser-inc** — stub headers fed to the interrogate parser so it can parse
  system headers it shouldn't actually expand.

----------

# direct/src directories #

See **[The direct Python framework](subsystems/direct-python-framework.md)** for the deep-dive.

- **showbase** — `ShowBase` (the app bootstrap), `DirectObject`, the global
  `messenger`/`taskMgr`, `Loader`, `Audio3DManager`.
- **actor** — `Actor`, the Python wrapper over the C++ `Character`.
- **interval** — the tweening system: `LerpInterval`, `Sequence`/`Parallel`,
  `MetaInterval` (Python over the C++ `CInterval` family).
- **task** — the Python `Task`/`taskMgr` surface over the C++ `AsyncTask` system.
- **fsm** — `FSM` and the legacy `ClassicFSM` finite-state-machine helpers.
- **gui** — **DirectGui**: `DirectFrame`/`DirectButton`/… built on the C++ `pgui`.
- **distributed** — the **Distributed** networking architecture (the Disney
  "DC" object-replication system); `dcparser`/`dcparse` are the C++ `.dc`-file parser.
- **stdpy** — drop-in replacements for parts of the Python stdlib
  (`threading`, `file`) that cooperate with Panda's VFS/threads.
- **directnotify** — the `directNotify` category-based logging system.
- **controls** — character-controller walkers (`GravityWalker`,
  `NonPhysicsWalker`, …) and `InputState`.
- **directtools / directdevices / leveleditor / motiontrail / filter /
  showutil / tkpanels / tkwidgets / wxwidgets** — in-engine editing widgets,
  device wrappers, the (legacy) level editor, post-process filters, and the
  Tk/wx GUI bindings used by the tools.
- **cluster** — multi-machine display clustering (sync rendering across PCs).
- **deadrec** — dead-reckoning smoothing for networked/distributed objects.
- **dist / directscripts / extensions_native** — packaging (`build_apps`/
  deployment), helper scripts, and native Python extension hooks.

----------

# pandatool/src directories #

See **[pandatool (asset pipeline)](subsystems/pandatool.md)** for the deep-dive.

- **pandatoolbase / progbase / eggbase / imagebase** — the framework base
  classes shared by every tool (`ProgramBase`, `EggToSomething`, …).
- **egg-palettize / palettizer** — the texture-atlas ("palette") packer driven
  by `.txa` scripts.
- **converter / ptloader** — the converter base and the runtime model-loader
  plugin that loads non-egg formats at load time.
- **bam** — `bam2egg`/`egg2bam` and BAM inspection tools.
- **Format → egg converters**: **fltegg/fltprogs** (MultiGen FLT),
  **lwoegg/lwoprogs** (LightWave), **daeegg/daeprogs** (COLLADA),
  **objegg/objprogs** (Wavefront OBJ), **xfileegg/xfileprogs** (DirectX `.x`),
  **vrmlegg/vrmlprogs** (VRML), **dxfegg/dxfprogs** (DXF), **assimp**
  (everything Assimp supports: glTF, FBX, …).
- **Egg programs**: **eggprogs / eggcharbase / egg-mkfont / egg-optchar /
  egg-qtess** — egg manipulation, font generation, character optimization,
  tessellation.
- **PStats server**: **pstatserver** plus the platform viewers **gtk-stats /
  win-stats / mac-stats / text-stats**.
- **Image / misc**: **imageprogs / pfmprogs / miscprogs** and **deploy-stub**
  (the executable stub used by `build_apps` deployment).

----------

> For the foundational patterns that recur across all of these subsystems —
> the type system, reference counting, BAM serialization, the threaded
> pipeline cycler, and interrogate bindings — see the
> **[Cross-cutting concepts](cross-cutting-concepts.md)** chapter.
