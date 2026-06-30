# Display & GSG backends

This cluster is the layer that turns a culled scene graph into pixels on a screen (or an offscreen texture). It defines the platform-independent rendering abstractions — `GraphicsEngine` (frame orchestration), `GraphicsOutput`/`GraphicsWindow`/`GraphicsBuffer` (render targets), `GraphicsPipe` (a factory that knows how to talk to a windowing system), `DisplayRegion` (a viewport+camera), and `GraphicsStateGuardian` (GSG, the thing that issues GPU commands) — and then provides concrete backends: a shared template-based OpenGL/OpenGL-ES implementation (`glstuff` instantiated by `glgsg`/`glesgsg`/`gles2gsg`), an EGL surface layer, a pure-software rasterizer (`tinydisplay`), and the per-OS window modules (`cocoadisplay`, `x11display`, `windisplay`). The key architectural idea is a strict separation between *windowing* (OS-specific, in the platform modules) and *drawing* (API-specific, in the GSG backends), bridged by small "GL-on-platform" glue modules (`wgldisplay`, `glxdisplay`, `cocoagldisplay`, `egldisplay`) that live outside this cluster but subclass its base classes. A second core idea is the App/Cull/Draw threaded pipeline: `GraphicsEngine::render_frame()` cycles the data pipeline and dispatches cull and draw work to (optionally) separate threads.

The render path, end to end: `GraphicsEngine::render_frame()` (panda/src/display/graphicsEngine.cxx:713) opens pending windows, cycles the pipeline, then calls `WindowRenderer::do_frame()` (graphicsEngine.cxx:2680) for app and each render thread. `do_frame` runs three stages in order: `cull_to_bins()` (walks each active `DisplayRegion`'s scene into a `CullResult` of `CullableObject`s, sorted into `CullBin`s), `draw_bins()` (graphicsEngine.cxx:1643 — for each window calls `begin_frame`/`clear`/`do_draw` per region/`end_frame`, then optionally flips), and `process_events()` (OS window event pump). `do_draw()` (graphicsEngine.cxx:2043) sets up the scene on the GSG and replays the cull bins, issuing `set_state_and_transform` + `draw_*` calls into the GSG. Flipping (buffer swap) is separated so it can be synchronized across all windows (`do_flip_frame`).

**Cross-cutting — the layering and the threading model.** Five layers cooperate: (1) `GraphicsEngine` orchestrates and owns all outputs; (2) `GraphicsOutput`/`GraphicsWindow`/`GraphicsBuffer` are render targets; (3) `GraphicsPipe` is the per-OS factory (`GraphicsPipeSelection` picks/loads one); (4) `GraphicsStateGuardian` (base in `gsgbase`, real work in `glstuff`/`tinydisplay`/`egl`) issues GPU commands and caches GPU resources via per-resource `*Context` objects; (5) `DisplayRegion` is a viewport+camera within an output, and many regions can share one output. The App/Cull/Draw split is encoded by `GraphicsThreadingModel` (parsed from the `threading-model` config string, e.g. `Cull/Draw`): each window's *window*, *cull*, and *draw* tasks are assigned to a named `WindowRenderer`, and `RenderThread`s execute the cull/draw stages off the app thread against earlier stages of the `Pipeline` (Panda's triple-buffered, copy-on-write data pipeline in `panda/src/pipeline`). The *window* task (all OS API calls) almost always stays in app because windowing systems (notably X11 and Cocoa/AppKit) require all their calls on one thread. Cull is deduplicated per camera per thread (graphicsEngine.cxx:1543) so two regions sharing a camera cull once. The whole design — non-certified-window retry, capability queries deferred to the draw thread, GSG resource contexts — exists because GPU state can only be queried/created once a context is current on the draw thread.

## display

**What it is.** The heart of the cluster: the platform- and API-independent rendering abstractions plus the engine that drives them. Everything else in the cluster (and every GL/DX/software backend) subclasses types defined here. It owns the App/Cull/Draw threading model, the window/buffer lifecycle, render-to-texture plumbing, stereo, screenshots, and input event collection from windows.

**Key classes and roles.**
- `GraphicsEngine` (`graphicsEngine.h`/`.cxx`, `: public ReferenceCount`) — the singleton-ish frame driver. `render_frame()`, `make_output()` (the master window/buffer factory), `open_windows()`, `flip_frame()`. Internally holds a `WindowRenderer` for "app" plus one `RenderThread` (which *is* a `WindowRenderer` + `Thread`) per named draw/cull thread; threads are slaves driven by `_cv_start`/`_cv_done` condition variables and a `ThreadState` enum. Read the giant comment block at graphicsEngine.h:200-320 — it is the canonical explanation of how window/cull/draw tasks are distributed across threads.
- `GraphicsOutput` (`graphicsOutput.h`, `: public GraphicsOutputBase, public DrawableRegion`) — abstract base for anything you can render into. Manages a list of `DisplayRegion`s, the bound `GraphicsStateGuardian`, render-textures (`add_render_texture` with a `RenderTextureMode`: `RTM_bind_or_copy`, `RTM_copy_texture`, `RTM_copy_ram`, `RTM_triggered_copy_*`, `RTM_bind_layered` — graphicsOutput.h:78), `begin_frame`/`end_frame`/`begin_flip`/`end_flip`, and clear settings (inherited from `DrawableRegion`). The `_sort` value controls inter-output draw order (host window is 0; offscreen buffers feeding it must sort lower/negative).
- `GraphicsWindow` (`graphicsWindow.h`, `: public GraphicsOutput`) — adds `WindowProperties`, an input-device list (`GraphicsWindowInputDevice`), and the `process_events()`/`set_properties_now()` window-thread API. Platform window classes subclass this.
- `GraphicsBuffer` (`graphicsBuffer.h`, `: public GraphicsOutput`) — abstract offscreen render target (a real FBO subclass lives in the GL backend); `ParasiteBuffer` (`parasiteBuffer.h`) is the fallback that renders into a corner of a host window when true offscreen buffers are unavailable.
- `GraphicsPipe` (`graphicsPipe.h`, `: public TypedReferenceCount`) — abstract factory bound to one windowing system. Defines `BufferCreationFlags` (the `BF_*` bitmask: `BF_refuse_parasite`, `BF_require_window`, `BF_can_bind_color`, `BF_size_power_2`, …) and the protected `make_output(... int retry, bool &precertify)` that platform pipes override. `GraphicsPipeSelection` (`graphicsPipeSelection.h`) is the registry: `make_pipe()`/`make_module_pipe()`/`load_aux_modules()` dynamically load and rank pipe modules (e.g. it tries `pandagl` before `p3tinydisplay`).
- `GraphicsStateGuardian` (`graphicsStateGuardian.h`, `: public GraphicsStateGuardianBase`) — the display-level GSG base that fills in most of the double-dispatch protocol declared in `gsgbase`. Holds capability flags, the `PreparedGraphicsObjects` resource cache, the current `RenderState`/`TransformState`, and `is_valid()`/`needs_reset()`/`reset()`. Concrete backends (`GLGraphicsStateGuardian`, `TinyGraphicsStateGuardian`, `eglGraphicsStateGuardian`) subclass this.
- `DisplayRegion` (`displayRegion.h`, `: public TypedReferenceCount, public DrawableRegion`) — a rectangular sub-region of an output bound to a camera/lens; `do_cull()` (displayRegion.h:210) is the per-region cull entry point. `StereoDisplayRegion` (`stereoDisplayRegion.h`) wraps a left/right pair. `DisplayRegionCullCallbackData`/`DisplayRegionDrawCallbackData` let user code hook cull/draw.
- `FrameBufferProperties` (`frameBufferProperties.h`) — the requested framebuffer format (color/depth/stencil bits, multisample, sRGB, aux buffers); `subsumes()`/`get_quality()` drive backend format selection.
- `StandardMunger` (`standardMunger.h`) — the default `GeomMunger` subclass that reformats vertex data to what the GSG wants (color scaling via vertex color, etc.); GL/Tiny provide their own mungers that subclass it.
- Support types: `GraphicsThreadingModel` (parses the `threading-model` string into cull/draw thread names), `WindowProperties`, `NativeWindowHandle`/`WindowHandle` (embed Panda in a foreign window), `CallbackGraphicsWindow` (drive Panda from your own GL context), `DisplayInformation`/`DisplaySearchParameters` (enumerate modes/monitors), `ScreenshotRequest`, `SubprocessWindow` (macOS plugin-era out-of-process rendering).

**Central abstraction & inheritance.** `GraphicsOutputBase` (gsgbase) → `GraphicsOutput` → {`GraphicsWindow` → platform windows, `GraphicsBuffer` → backend FBO buffers, `ParasiteBuffer`, `CallbackGraphicsWindow`}. The GSG chain is `GraphicsStateGuardianBase` (gsgbase) → `GraphicsStateGuardian` (display) → backend GSGs.

**How it plugs in.** Upstream it consumes the scene graph (`pgraph`: `PandaNode`, `Camera`, `Lens`, `RenderState`, `CullResult`, `CullBin`, `GeomMunger`) and the `Pipeline`/`PipelineCycler` machinery (`pipeline`) for thread-safe data. Downstream it is the *only* thing that touches a GSG backend. Application code (e.g. `ShowBase`) creates a `GraphicsEngine`, asks `GraphicsPipeSelection` for a pipe, calls `engine->make_output(...)`, attaches a `Camera` to a `DisplayRegion`, and calls `render_frame()` each frame.

**Where to start.** To touch the frame loop or threading: `graphicsEngine.cxx` (`render_frame`, `WindowRenderer::do_frame`, `cull_to_bins`, `draw_bins`, `do_draw`, `do_flip_frame`). To touch window/buffer creation and RTT: `make_output()` (graphicsEngine.cxx:265) and `graphicsOutput.cxx`. To add a capability flag the engine must respect: `graphicsPipe.h` `BufferCreationFlags` and `make_output`'s flag handling.

**Gotchas / rationale (community).** "App/Cull/Draw" is *the* mental model; the canonical explanation is the maintainer's forum post "Can you describe the Rendering Pipeline please?" (https://discourse.panda3d.org/t/340) — App is your code, Cull walks the frustum into a flat list, Draw issues GL calls; with `threading-model Cull/Draw` these run on separate threads of a triple-buffered data pipeline (docs: https://docs.panda3d.org/1.10/python/programming/rendering-process/multithreaded-render-pipeline). Note that enabling threading does *not* automatically parallelize physics/app logic and can expose latency-sensitive bugs (e.g. transform updates lagging a frame, gh issue 250). Offscreen buffers silently fall back to **parasite buffers** (rendered into a corner of the host window) when true FBOs/pbuffers aren't available — a classic "my screenshot has garbage in it" footgun (https://discourse.panda3d.org/t/4114); use `BF_refuse_parasite` and check `gl-support-fbo`. On a headless box `make_output` can fail entirely if no GSG/window can be created (https://discourse.panda3d.org/t/25604) — that's why `tinydisplay` exists as a software fallback.

**Config vars (config_display.cxx).** `threading-model` (default empty = single-threaded), `auto-flip`, `sync-flip`, `yield-timeslice`, `allow-nonpipeline-threads`, `view-frustum-cull`, `prefer-parasite-buffer`/`force-parasite-buffer`/`prefer-texture-buffer`/`prefer-single-buffer`, `support-render-texture`, `support-stencil`, `allow-incomplete-render`, `win-size`/`win-origin`/`fullscreen`/`undecorated`/`win-fixed-size`/`cursor-hidden`/`icon-filename`, `red-blue-stereo`/`side-by-side-stereo`/`swap-eyes`, `screenshot-filename`/`screenshot-extension`.

## gsgbase

**What it is.** A deliberately tiny package holding only the *abstract* base of the GSG (and of graphics output) so that the scene-graph library (`pgraph`) can reference a GSG by pointer and perform double-dispatch (a `Geom` asks the GSG to draw it) **without** creating a circular build dependency between `pgraph` and `display`. It contains no rendering logic — just pure-virtual prototypes and type registration.

**Key classes and roles.**
- `GraphicsStateGuardianBase` (`graphicsStateGuardianBase.h`/`.cxx`, `: public TypedWritableReferenceCount`) — the master interface every backend must implement. It declares the capability queries (`get_max_texture_dimension`, `get_supported_geom_rendering`, `get_supports_texture_srgb`, `get_supports_multisample`, …), the resource `prepare_*`/`release_*`/`update_*` methods for textures, samplers, geoms, shaders, vertex/index/shader buffers, the per-attribute draw protocol (`set_state_and_transform`, `begin_draw_primitives`, `draw_triangles`/`draw_tristrips`/`draw_lines`/`draw_points`, `end_draw_primitives`), decal support, and `dispatch_compute`. Inheriting from `TypedWritableReferenceCount` is intentional so a GSG can be passed as an event parameter (see the class comment).
- `GraphicsOutputBase` (`graphicsOutputBase.h`, `: public TypedWritableReferenceCount`) — minimal base for `GraphicsOutput`, again to break a dependency cycle (so e.g. `Texture` can reference the output it was rendered from).

**Inheritance.** This is the root: `GraphicsStateGuardianBase` → `GraphicsStateGuardian` (display) → all concrete GSGs. `GraphicsOutputBase` → `GraphicsOutput` (display).

**How it plugs in.** `pgraph` (specifically `CullableObject`, `Geom`, `GeomPrimitive`) calls back into the GSG through these virtuals — this is the "double dispatch" the header mentions. The actual implementations live two layers down. Because gsgbase has almost no dependencies, it sits very low in the build order.

**Where to start.** If you are adding a new rendering capability that the scene graph must be able to ask about or invoke (e.g. a new primitive type or a new resource kind), you add the pure-virtual here first, then implement it in `GraphicsStateGuardian` (display) and each backend. `graphicsStateGuardianBase.h` is essentially the contract spec for the whole cluster.

**Config vars (config_gsgbase.cxx).** Minimal — no config vars at all; the `ConfigureFn(config_gsgbase)` block just calls `GraphicsOutputBase::init_type()` and `GraphicsStateGuardianBase::init_type()`. The meaningful GSG config lives in `display` and `glstuff`.

## glstuff

**What it is.** The single, shared OpenGL/OpenGL-ES backend implementation, written *once* as a set of `_src.h`/`_src.cxx`/`_src.I` files that are textually included and compiled **three times** with different preprocessor macros — producing the desktop-GL classes (prefix `GL`), the OpenGL-ES 1 classes (`GLES`), and the OpenGL-ES 2 classes (`GLES2`). This is how Panda maintains one GL codebase that targets desktop, mobile, and embedded GL without duplicating ~30k lines. The files are **not** include-guarded; they are meant to be included multiple times.

**The macro trick.** Each "instantiating" module (`glgsg`, `glesgsg`, `gles2gsg`) defines a small macro vocabulary and then `#include "glstuff_src.h"`. From `glgsg/glgsg.h`:
```
#define GLP(name) gl ## name            // GL function-name prefix
#define GLPf(name) gl ## name ## f       // float-suffix variant (d if STDFLOAT_DOUBLE)
#define CLP(name) GL ## name             // CLASS prefix -> GLGraphicsStateGuardian
#define GLCAT glgsg_cat                  // notify category
#define EXPCL_GL EXPCL_PANDA_GLGSG       // DLL export macro
```
`glesgsg.h` redefines `CLP(name)` to `GLES##name` and defines `OPENGLES`/`OPENGLES_1`/`SUPPORT_FIXED_FUNCTION`; `gles2gsg.h` uses `GLES2##name` and `OPENGLES_2`. So `CLP(GraphicsStateGuardian)` expands to `GLGraphicsStateGuardian`, `GLESGraphicsStateGuardian`, or `GLES2GraphicsStateGuardian` depending on which TU pulls it in. `glstuff_undef_src.h` exists to tear the macros back down. `glpure.cxx` provides "pure" (non-extension) GL stubs.

**Key classes (all written as `CLP(...)`).**
- `CLP(GraphicsStateGuardian)` (`glGraphicsStateGuardian_src.h`/`.cxx`, `: public GraphicsStateGuardian`) — the workhorse. Implements `reset()` (queries GL version/extensions and wires up function pointers), `begin_frame`/`end_frame`, `set_state_and_transform`, the `do_issue_*` per-attribute state appliers (`do_issue_texture`, `do_issue_shader`, `do_issue_blending`, `do_issue_depth_test`, …), `begin_draw_primitives`/`draw_triangles`/etc., FBO management, and all the `prepare_*` resource creators. ~10k lines; this is where most GL bugs are fixed.
- `CLP(GeomMunger)` (`glGeomMunger_src.h`, subclass of `StandardMunger`) — formats vertex arrays for GL (interleaving, column types).
- Resource contexts, each a `TypedObject`/`*Context` subclass that caches a GL object handle alongside the Panda resource: `CLP(TextureContext)` (`glTextureContext_src.h`), `CLP(SamplerContext)`, `CLP(VertexBufferContext)`/`CLP(IndexBufferContext)`/`CLP(BufferContext)` (VBO/IBO/SSBO+UBO), `CLP(GeomContext)`, `CLP(ShaderContext)` (GLSL) and `CLP(CgShaderContext)` (legacy Cg), `CLP(OcclusionQueryContext)`.
- `CLP(GraphicsBuffer)` (`glGraphicsBuffer_src.h`, `: public GraphicsBuffer`) — the real FBO-backed offscreen buffer (the thing `GraphicsBuffer` in `display` is the abstract base of).
- `CLP(ImmediateModeSender)` (`glImmediateModeSender_src.h`) — fallback glBegin/glVertex path for ancient GL.
- `glmisc_src.cxx` — registers all the `gl-*` config vars and global GL helpers.

**How it plugs in.** glstuff itself builds no library; the instantiating modules do. The GSG is created by a *GL-on-platform* module: `wglGraphicsStateGuardian` (wgl, Windows), `glxGraphicsStateGuardian` (glx, X11), `CocoaGLGraphicsStateGuardian` (cocoagl, macOS), and `eglGraphicsStateGuardian` (egl) all subclass `CLP(GraphicsStateGuardian)` (i.e. `GLGraphicsStateGuardian`) and just add context/surface creation. Those modules pair the GSG with a platform `GraphicsWindow` (see windisplay/x11display/cocoadisplay below).

**Where to start.** Almost every "rendering looks wrong / a state isn't applied / extension X unused" bug is in `glGraphicsStateGuardian_src.cxx` — search for the relevant `do_issue_*` or `draw_*`. A new texture format goes in `glTextureContext_src.cxx` + `reset()`'s format tables. A new shader feature goes in `glShaderContext_src.cxx`. Remember any edit here is compiled into all three GL variants, so guard ES-incompatible code with `#ifndef OPENGLES` / `#ifdef OPENGLES_2`.

**Gotchas.** Because the source is shared, a desktop-only GL call must be `#ifdef`-guarded or it will break the GLES builds. The "non-certified window / retry" dance in `GraphicsEngine::make_output` exists largely because GL capabilities can only be queried from the draw thread after a context exists (see the comment at graphicsEngine.cxx:274). State leaks into/out of foreign GL contexts were fixed by adding explicit state resets after callbacks (https://discourse.panda3d.org/t/24149).

**Config vars (glmisc_src.cxx, prefix `gl-`).** `gl-version`, `gl-forward-compatible`, `gl-support-fbo`, `gl-support-dsa`, `gl-debug`/`gl-debug-synchronous`/`gl-debug-abort-level`/`gl-check-errors`/`gl-max-errors`, `gl-finish`, `gl-cheap-textures`, `gl-ignore-mipmaps`/`gl-force-mipmaps`/`gl-ignore-filters`/`gl-ignore-clamp`, `gl-support-clamp-to-border`, `gl-color-mask`, `gl-support-occlusion-query`, `gl-min-buffer-usage-hint`, `gl-force-depth-stencil`, `gl-force-fbo-color`, `gl-debug-object-labels`.

## glgsg

**What it is.** The thin instantiation module that compiles `glstuff` against the **real desktop OpenGL** library. It contains almost no code of its own: `glgsg.h` sets the `GLP`/`CLP`/`GLPf` macros, includes the system `<GL/gl.h>` (or `<OpenGL/gl.h>` on macOS) plus Panda's bundled `panda_glext.h`, then includes `glstuff_src.h`; `glgsg.cxx` includes `glstuff_src.cxx`. The net effect is to emit the concrete `GLGraphicsStateGuardian`, `GLGeomMunger`, `GLTextureContext`, `GLGraphicsBuffer`, etc., into the `pandagl`-side library.

**Key classes.** `GLGraphicsStateGuardian`, `GLGeomMunger`, and all the `GL*Context`/`GLGraphicsBuffer` classes — but they are *defined* in glstuff via `CLP()`; glgsg merely fixes the prefix to `GL`. `glgsg.h` also sets `EXPECT_GL_VERSION_*` macros from the configured `MIN_GL_VERSION_*` so glstuff can `#ifdef` out runtime checks for guaranteed-present features.

**Inheritance.** `GraphicsStateGuardianBase` → `GraphicsStateGuardian` → `GLGraphicsStateGuardian` (this module) → `wglGraphicsStateGuardian`/`glxGraphicsStateGuardian`/`CocoaGLGraphicsStateGuardian`/`eglGraphicsStateGuardian` (the platform GL modules).

**How it plugs in.** Sits between glstuff (the implementation) and the platform GL windowing modules (`wgldisplay`, `glxdisplay`, `cocoagldisplay`, `egldisplay`), which subclass `GLGraphicsStateGuardian` and add context creation/`gl*MakeCurrent`/swap. The sibling modules `glesgsg` and `gles2gsg` are the *same* glstuff source compiled for GLES1 and GLES2 respectively.

**Where to start.** You rarely edit glgsg itself — it's macros + includes. Edit it only to change which GL headers are pulled in, the `__glext_h_` suppression (it deliberately blocks the system glext.h to use Panda's `panda_glext.h`), or the version-expectation logic. For actual GL behavior, go to `glstuff`.

**Config vars (config_glgsg.cxx).** Registers the `glgsg_cat` notify category and the `pandagl` GL pipe/GSG types; the functional GL config lives in `glstuff`/`glmisc_src.cxx`.

## cocoadisplay

**What it is.** The macOS/Cocoa windowing layer — and *only* the windowing layer. It manages `NSWindow`/`NSView`/event handling/display-mode switching/`CVDisplayLink` vsync, but is **GL-agnostic**: the actual OpenGL context is created by the separate `cocoagldisplay` module (`CocoaGLGraphicsPipe`/`CocoaGLGraphicsWindow`/`CocoaGLGraphicsStateGuardian`), which subclasses the classes here. This split lets the same Cocoa windowing code serve both the GL backend and the software `tinydisplay` backend (via `tinyCocoa*`). Written in Objective-C++ (`.mm`).

**Key classes and roles.**
- `CocoaGraphicsPipe` (`cocoaGraphicsPipe.h`/`.mm`, `: public GraphicsPipe`) — abstract macOS pipe; enumerates displays via ApplicationServices/CoreVideo. It does **not** implement `make_output` (it has no GL); `CocoaGLGraphicsPipe` does.
- `CocoaGraphicsWindow` (`cocoaGraphicsWindow.h`/`.mm`, `: public GraphicsWindow`) — abstract macOS window: owns the `CocoaPandaWindow`/`CocoaPandaView`, translates Cocoa keyboard/mouse/touch events into Panda input, handles fullscreen and display reconfiguration, and the `CVDisplayLink` used to pace flips.
- Objective-C helper classes: `CocoaPandaApp`/`CocoaPandaAppDelegate` (NSApplication bring-up so a windowless Python process still gets an event loop), `CocoaPandaWindow` (NSWindow subclass), `CocoaPandaWindowDelegate`, `CocoaPandaView` (the NSView that hosts the GL/CA layer and receives events).

**Inheritance.** `GraphicsPipe` → `CocoaGraphicsPipe` → `CocoaGLGraphicsPipe` (in cocoagldisplay). `GraphicsWindow` → `CocoaGraphicsWindow` → `CocoaGLGraphicsWindow`.

**How it plugs in.** Selected by `GraphicsPipeSelection` on macOS; the GL glue (`cocoagldisplay`) provides the `make_output` that builds a `CocoaGLGraphicsWindow` + `CocoaGLGraphicsStateGuardian`. Because all AppKit calls must happen on the main thread, the window task runs in app (mirroring the X11 constraint).

**Where to start.** Window decoration/fullscreen/Retina/event bugs on macOS: `cocoaGraphicsWindow.mm`. App/menu/dock bring-up: `cocoaPandaApp.mm`/`cocoaPandaAppDelegate.mm`. The autorelease-pool wrapping of each frame is in `WindowRenderer::do_frame` (graphicsEngine.cxx:2683, `objc_autoreleasePoolPush`).

**Gotchas (community).** Apple Silicon and recent macOS broke a lot of GL assumptions (deprecated OpenGL, software-renderer-only contexts) — users fall back to `tinydisplay` when only the Apple software renderer is available (https://discourse.panda3d.org/t/30412, https://discourse.panda3d.org/t/30304).

**Config vars (config_cocoadisplay.mm).** `cocoa-invert-wheel-x`, `dpi-aware`.

## x11display

**What it is.** The X11/Linux windowing layer, again GL-agnostic: it creates X windows and pumps X events, with optional XRandR (multi-monitor/mode-switching), XInput2 (raw input), Xcursor, and XF86DGA (relative mouse) support. The GL context is layered on top by `glxdisplay` (GLX) or `egldisplay` (EGL); the software backend uses `tinyXGraphicsPipe`. The headers carefully wrap X11's macro-heavy headers via `pre_x11_include.h`/`post_x11_include.h` to avoid macro collisions with Panda symbols.

**Key classes and roles.**
- `x11GraphicsPipe` (`x11GraphicsPipe.h`/`.cxx`, `: public GraphicsPipe`) — opens the `Display*`, caches X atoms, queries XRandR modes, manages an X error handler. Abstract w.r.t. GL; `glxGraphicsPipe`/`eglGraphicsPipe` subclass it and add `make_output`.
- `x11GraphicsWindow` (`x11GraphicsWindow.h`/`.cxx`, `: public GraphicsWindow`) — creates the `Window`, sets WM properties, processes the X event queue (`process_events`), implements pointer warp/grab, fullscreen via XRandR, and clipboard. All X calls funnel through the window/app thread.
- `get_x11.h` / `pre_x11_include.h` / `post_x11_include.h` (these shims actually live in `panda/src/display/`, and x11display pulls them in via `#include "get_x11.h"`) — the include-hygiene shims for X11's `#define`s (e.g. `Bool`, `None`, `KeyPress`); `get_x11.h` wraps the `<X11/*.h>` includes between the pre/post headers.

**Inheritance.** `GraphicsPipe` → `x11GraphicsPipe` → {`glxGraphicsPipe`, `eglGraphicsPipe` (egldisplay `typedef`s `x11GraphicsPipe` as its `BaseGraphicsPipe` when X is present)}. `GraphicsWindow` → `x11GraphicsWindow` → `glxGraphicsWindow`/`eglGraphicsWindow`.

**How it plugs in.** Default Linux desktop path. `egldisplay` literally builds on x11display (`typedef x11GraphicsPipe BaseGraphicsPipe;` in eglGraphicsPipe.h) so EGL-on-X reuses the same X window management.

**Where to start.** Input/keyboard/mouse/fullscreen/multi-monitor bugs: `x11GraphicsWindow.cxx`. Display enumeration / XRandR / DPI: `x11GraphicsPipe.cxx`. If a build breaks from an X macro leaking into Panda code, look at the `pre/post_x11_include.h` shims.

**Gotchas (community).** Xlib is not thread-safe unless `XInitThreads` is called first — hence the `x-init-threads` config var and the architectural rule that **all X calls run in one thread** (the app thread); the GraphicsEngine comment notes "the design of X-Windows is such that all X calls must be issued in the same thread." Threading behavior genuinely differs between Linux and Windows here (https://discourse.panda3d.org/t/9855). Fullscreen focus loss on minimal WMs is a known X quirk (https://discourse.panda3d.org/t/27801). Headless servers need a virtual X server (Xvfb / `nvidia` headless) or you get no pipe at all (https://discourse.panda3d.org/t/24508).

**Config vars (config_x11display.cxx).** `display` (the X display string), `x-error-abort`, `x-init-threads`, `x-support-xcursor`, `x-support-xinput2`, `x-support-xf86dga`, `x-support-xrandr`, `x-wheel-up-button`/`x-wheel-down-button`/`x-wheel-left-button` (mouse-wheel button mapping).

## windisplay

**What it is.** The Win32 windowing layer plus shared Windows infrastructure. `WinGraphicsPipe`/`WinGraphicsWindow` are the abstract bases for both the OpenGL path (`wglGraphicsPipe`/`wglGraphicsWindow` in `wgldisplay`) and the legacy DirectX9 path (`wdxGraphicsPipe` in `dxgsg9`). It owns `HWND` creation, the Win32 message loop, DPI awareness, IME, and DirectX device/video-memory detection.

**Key classes and roles.**
- `WinGraphicsPipe` (`winGraphicsPipe.h`/`.cxx`, `: public GraphicsPipe`) — base Windows pipe; resolves DPI-awareness entry points from `user32.dll` and loads `psapi.dll`/`PowrProf.dll`, runs DirectX detection to pick a device (`winDetectDx.h`, `winDetectDx9.cxx`), reports display info. Abstract w.r.t. the rendering API.
- `WinGraphicsWindow` (`winGraphicsWindow.h`/`.cxx`, `: public GraphicsWindow`) — registers the window class, creates the `HWND`, runs the `WndProc`, translates Win32 messages to Panda input (incl. raw input, IME, touch), handles fullscreen mode switching and DPI scaling. Nested `WinWindowHandle : public WindowHandle` supports embedding/parenting.
- `winDetectDx.h` + `winDetectDx9.cxx` — enumerate adapters and video memory so the engine can choose a GPU and size buffers (gated by `do-vidmemsize-check`/`request-dxdisplay-information`).

**Inheritance.** `GraphicsPipe` → `WinGraphicsPipe` → {`wglGraphicsPipe` (GL), `wdxGraphicsPipe9` (DX9)}. `GraphicsWindow` → `WinGraphicsWindow` → `wglGraphicsWindow`/`wdxGraphicsWindow9`.

**How it plugs in.** Default Windows path; `wgldisplay` subclasses these and pairs them with `wglGraphicsStateGuardian` (a `GLGraphicsStateGuardian` subclass from glstuff). The DX9 backend (`dxgsg9`) reuses the same window base but its own GSG.

**Where to start.** Window creation, message handling, fullscreen, DPI, IME, clipboard: `winGraphicsWindow.cxx`. GPU/adapter selection and video-memory checks: `winDetectDx9.cxx` and `winGraphicsPipe.cxx`. The message loop can be disabled (`disable-message-loop`) when embedding Panda in a host app that owns the loop.

**Config vars (config_windisplay.cxx).** `do-vidmemsize-check`, `auto-cpu-data`, `ime-hide`, `request-dxdisplay-information`, `dpi-aware`, `dpi-window-resize`, `paste-emit-keystrokes`, `disable-message-loop`.

## egldisplay

**What it is.** The EGL surface/context layer used to bring up OpenGL-ES (or, in some configs, desktop GL) on Linux/Android and headless devices. EGL is the API that creates GL contexts and drawing surfaces independently of a particular window system, so this module is parametrized: when built with X support it `typedef`s `x11GraphicsPipe` as its base (`BaseGraphicsPipe`) and reuses X window management; when built `EGL_NO_X11`, it uses the plain `GraphicsPipe` base for true windowless rendering. It also selects which GL variant to drive (`gles2gsg`, `glesgsg`, or `glgsg`) via the same `Base*` typedef indirection.

**Key classes and roles.**
- `eglGraphicsPipe` (`eglGraphicsPipe.h`/`.cxx`, `: public BaseGraphicsPipe`) — wraps `EGLDisplay`/`eglInitialize`/config selection; provides `get_interface_name()`, the static `pipe_constructor()` registered with `GraphicsPipeSelection`, and `make_output()` dispatching to one of the four surface types below.
- `eglGraphicsWindow` (`eglGraphicsWindow.h`/`.cxx`) — on-screen window surface (`eglCreateWindowSurface`), reusing the X window when X is present.
- `eglGraphicsBuffer` (`eglGraphicsBuffer.h`/`.cxx`) — pbuffer / FBO offscreen surface.
- `eglGraphicsPixmap` (`eglGraphicsPixmap.h`/`.cxx`) — pixmap surface (render into an X/native pixmap).
- `eglGraphicsStateGuardian` (`eglGraphicsStateGuardian.h`/`.cxx`, `: public BaseGraphicsStateGuardian` which is a `GL*GraphicsStateGuardian` from glstuff) — owns the `EGLContext`, implements `gl_flush`/`make_current`/`reset`/`choose_pixel_format` against EGL while inheriting all drawing from the glstuff GSG.

**Inheritance.** `eglGraphicsStateGuardian` extends whichever glstuff GSG was selected (`GLES2GraphicsStateGuardian` by default) — so the drawing code is shared with desktop GL; only context/surface management is EGL-specific. `eglGraphicsPipe` extends `x11GraphicsPipe` (X build) or `GraphicsPipe` (headless build).

**How it plugs in.** Registered as a pipe type; chosen on platforms/configs where GLES/EGL is the target (Android, Raspberry Pi, headless GPU rendering). It bridges the platform window (x11 or none) to the glstuff GL-ES backend.

**Where to start.** Context/surface creation and config selection: `eglGraphicsStateGuardian.cxx` (`choose_pixel_format`, `reset`) and `eglGraphicsPipe.cxx` (`make_output`). Headless rendering bugs: build with `EGL_NO_X11` and look at the buffer/pixmap surface classes.

**Config vars (config_egldisplay.cxx).** Mainly registers the pipe/GSG types and the `egldisplay` notify category; functional GL config is inherited from `glstuff` (`gl-*`).

## tinydisplay

**What it is.** A complete CPU software rasterizer — no GPU, no driver, no GL — derived originally from TinyGL. It implements its own z-buffered triangle/line rasterization, perspective-correct texturing, fixed-function lighting/fog, and pixel store with optional sRGB and dithering, all in portable C/C++. It exists as the universal fallback (headless CI, broken/absent GPU drivers, deterministic reference rendering) and ships its own platform window glue for every OS plus an SDL and an offscreen pipe.

**Key classes and roles.**
- `TinyGraphicsStateGuardian` (`tinyGraphicsStateGuardian.h`/`.cxx`, `: public GraphicsStateGuardian`) — implements the GSG protocol in software: `begin_draw_primitives`, `draw_triangles`/etc. feed the `ZBuffer` rasterizer; holds the current `ZBuffer` framebuffer and an `_aux_frame_buffer`. State changes set up the C rasterizer's globals.
- `ZBuffer` (`zbuffer.h`/`zbuffer.cxx`) — the core framebuffer struct (`PIXEL`-typed color + z planes), with `ZB_open`/`ZB_close`/`ZB_resize`/`ZB_clear`/`ZB_copyFrameBuffer`. Triangle fill goes through function-pointer dispatch (`ZB_fillTriangleFunc`, `ZB_storePixelFunc`, `ZB_lookupTextureFunc`).
- Rasterizer internals: `ztriangle*.cxx`/`ztriangle_code_*.h` (the triangle inner loops, generated from `ztriangle.py` into specialized variants for flat/smooth/textured/etc.), `zline.cxx`, `clip.cxx` (frustum clipping), `vertex.cxx`, `td_texture.cxx` (texture sampling/mipmaps), `td_light.cxx` (per-vertex lighting), `specbuf.cxx` (specular), `zdither.cxx`, `store_pixel.cxx`/`store_pixel_code.h`/`store_pixel_table.h` (blend/store with sRGB; tables generated by `store_pixel.py`), `srgb_tables.*`.
- `TinyGeomMunger` (`tinyGeomMunger.h`) and `TinyTextureContext` (`tinyTextureContext.h`) — the software munger and texture-context.
- `TinyGraphicsBuffer` (`tinyGraphicsBuffer.h`, `: public GraphicsBuffer`) — software offscreen target wrapping a `ZBuffer`.
- Platform glue (each a pipe+window pair subclassing the matching platform base): `tinyWinGraphicsPipe`, `tinyXGraphicsPipe`, `tinyCocoaGraphicsPipe`, `tinySDLGraphicsPipe`, `tinyOffscreenGraphicsPipe` — these create an OS window/buffer and blit the `ZBuffer` into it each frame.

**Inheritance.** `GraphicsStateGuardian` → `TinyGraphicsStateGuardian`. `GraphicsPipe`/platform pipes → `tinyXGraphicsPipe`/`tinyWinGraphicsPipe`/`tinyCocoaGraphicsPipe`/`tinySDLGraphicsPipe`/`tinyOffscreenGraphicsPipe`. `GraphicsBuffer` → `TinyGraphicsBuffer`.

**How it plugs in.** Registered with `GraphicsPipeSelection` as the `p3tinydisplay` pipe; selected explicitly (`load-display p3tinydisplay`) or as a fallback when no GPU pipe can be created. It receives the exact same culled `CullableObject` stream as the GL backend, so a scene renders identically (modulo software limits) without any app changes.

**Where to start.** Wrong pixels/blending/sRGB: `store_pixel.cxx` (and regenerate via `store_pixel.py`). Triangle artifacts/perf: `ztriangle_*.cxx` + `ztriangle.py` (do not hand-edit the generated `_code_` headers — edit the generator). Texturing: `td_texture.cxx`. Framebuffer/clear/resize: `zbuffer.cxx`. GSG-level state mapping: `tinyGraphicsStateGuardian.cxx`.

**Gotchas (community).** It is the documented escape hatch when a GPU/driver is unavailable — e.g. Apple-Silicon software-renderer-only situations and headless clusters fall back to tinydisplay (https://discourse.panda3d.org/t/30412). It's slow and feature-limited (no real shaders), so it is for correctness/availability, not performance.

**Config vars (config_tinydisplay.cxx).** `td-ignore-mipmaps`, `td-ignore-clamp`, `td-perspective-textures`.

## Known shortcomings & footguns

The constructive description above explains how the display cluster and the GSG turn a scene into pixels. This section catalogues where that pipeline breaks in practice — community-mined "footguns" about the shader generator, the GL/Cg legacy, blending and depth, the single-backend reality, and the platform-display backends (macOS, Wayland, Web). These are community-sourced opinion and history; severity/status tags reflect the state at the time they were reported. Pure scene-graph/node/state pitfalls (color attribs, `flattenStrong`, stale bounds, immutable `RenderState`, Geom batching) live on the scene-graph page; this page keeps the ones that bottom out in the GSG/GPU pipeline.

### The shader generator is perpetually incomplete
**Severity: major · Status: mitigated (gaps closed over years; superseded in 1.11)**

The auto-shader (`setShaderAuto`) was meant to transparently replace the fixed-function pipeline (the `do_issue_*` state appliers in `glGraphicsStateGuardian_src.cxx`) but for a decade emitted `Shader Generator does not support X yet` for fog, TexMatrix, TexGen, ColorScale, cube maps, perspective points, GLES, etc. — and because the errors don't halt rendering, the effect just silently drops.

> "the shader generator doesn't yet support all the features of the rendering
> pipeline." — Josh_Yelon *(maintainer)*, [t/3519](https://discourse.panda3d.org/t/3519)

### The auto-shader silently diverges from the fixed-function pipeline it emulates
**Severity: major · Status: mostly fixed-in-1.10.x**

Enabling `setShaderAuto` was supposed to look identical to FFP but diverged on texture-combine modes, color-scale, runtime `TextureStage::set_color()`, vertex alpha, etc. — some cases asserting/crashing. rdb repeatedly called these oversights. (Issues #177, #178, #189, #331, #401, #417–419.)

> re: ShaderGenerator ignoring `TextureStage::set_color()` changes — "This was an
> oversight, and should be easy to fix." — rdb *(maintainer)*,
> [#177](https://github.com/panda3d/panda3d/issues/177)

### `gl-version 3 2` / core profile / Apple Silicon silently break lighting, fog, transparency
**Severity: blocker (on affected configs) · Status: by-design / mitigated-in-1.11**

Modern GL core profiles delete fixed-function. There, the shader generator won't run and the minimal "default shader" can't do materials, fog, lighting, or transparency. On macOS you're forced into core profile for usable GLSL (see [macOS OpenGL is frozen at 4.1](#macos-opengl-deprecation-frozen-at-41-no-computessbos-no-metal) below); on Apple Silicon the shader generator didn't work at all (≡ `setShaderOff`) — one reason the cocoadisplay/tinydisplay fallback (above) exists. The `gl-version` config var lives in `glmisc_src.cxx`.

> "the shader generator does not work on ARM macs... it means the set_shader_auto
> call is in this case equivalent to set_shader_off." — rdb *(maintainer)*,
> [t/30412](https://discourse.panda3d.org/t/30412)

### Cg was the default shader language — then NVIDIA deprecated it
**Severity: major · Status: mitigated-in-1.11 (in-house compiler, "not as good")**

Panda's shaders, samples, and the shader generator were all Cg (the `CLP(CgShaderContext)` path noted in glstuff above), which NVIDIA deprecated in 2012 (no ARM/GLES/modern-mac support). 1.11 replaces the Cg Toolkit with an in-house compiler the docs describe as a "best-effort attempt... not as good as the Cg Toolkit."

### `setShaderAuto` is a silent, large performance cliff
**Severity: minor · Status: by-design**

Turning it on silently switches all lighting from per-vertex to per-pixel and regenerates shaders on state changes — frequently a ~10× framerate drop (e.g. 700→70 fps) — and can't be combined with hardware instancing.

### Auto-shader caching is tangled with RenderState identity (internal design debt)
**Severity: major (internal) · Status: known wart**

The generated shader is cached on the `RenderState` object, so any state change regenerates a shader; sharing shaders cheaply across states would require pulling the shader cache out of `RenderState` entirely (a hash-of-attribs scheme drwr describes but no one has implemented). This is the GSG-side reason the perf cliff above bites so hard.

### Transparency sorting, decals & depth offset

Order-dependent transparency (no OIT), the `DecalEffect`/`DepthOffset` vs.
transparency-sort conflict, and the unitless `setDepthOffset` / wasted depth
precision are sorting/state concerns that live with the cull bins and
`RenderState` — see **Transparency is order-dependent**,
**`DecalEffect`/`DepthOffset` conflict**, and **Z-fighting / `setDepthOffset`**
in the [scene-graph page's footguns](scene-graph.md#known-shortcomings-footguns).
They surface at draw time in the GSG (`do_issue_blending` in the GL GSG), but the
root cause is the back-to-front sort within a cull bin, not the backend.

### sRGB / gamma is off-by-default — recurring "too dark/washed-out" trap
**Severity: major · Status: by-design (correct behavior is opt-in)**

For backward compat, lighting/blending default to (physically wrong) gamma space. Correct results require flagging every texture's sRGB color space + enabling `framebuffer-srgb` (the sRGB framebuffer support flows through `FrameBufferProperties` and `get_supports_texture_srgb` in the GSG above), and it's easy to get half-right (normal maps wrongly tagged sRGB, GUI too bright, MSAA+sRGB banding).

> "blending and lighting are done in gamma-corrected sRGB space, which generates
> incorrect / unrealistic results." — rdb *(maintainer)*, [t/28863](https://discourse.panda3d.org/t/28863)

### No built-in PBR or production deferred shading
**Severity: major · Status: mitigated (3rd-party `simplepbr`; not core)**

PBR comes from third-party `simplepbr`; deferred shading exists only as the "Fireflies" sample, which "breaks as soon as you rotate the camera." The standard shader generator doesn't use materials for PBR.

> "we have firefly example but it breaks as soon as your rotate the camera, the
> lights are not spherical but cones, no shadows." — treeform,
> [t/7970](https://discourse.panda3d.org/t/7970)

### Single rendering backend: OpenGL only; DirectX stuck at D3D9; Vulkan perpetual WIP
**Severity: major · Status: still-open**

The only production backend is the shared `glstuff` OpenGL GSG (above). The DirectX backend (`dxgsg9`) is DX9 (no modern features/RTX); the Vulkan backend has been "WIP" for years and is "not ready for prime time." This single-backend reality is the root cause of several platform footguns below.

> "There is a Vulkan backend that is, last I've heard, not ready for prime time.
> But most people use OpenGL without issue." — Schwarzbaer, Discord

### macOS OpenGL deprecation: frozen at 4.1, no compute/SSBOs, no Metal
**Severity: blocker (modern-GPU features) · Status: still-open**

Apple froze OpenGL at 4.1 and deprecated it; because Panda has only the GL backend on Mac (see the single-backend entry above, and the cocoadisplay/cocoagldisplay split earlier on this page), compute shaders, image load/store, and SSBOs are unavailable. Maintainers declined a Metal backend, betting on the unfinished Vulkan + MoltenVK path ([#339](https://github.com/panda3d/panda3d/issues/339), closed with no Mac modern-GPU path).

> "I think it might be a better use of our time if we finish the Vulkan
> implementation and then use MoltenVK on macOS/iOS... I'm closing this until plans
> change." — rdb *(maintainer)*, [#339](https://github.com/panda3d/panda3d/issues/339)

### macOS HiDPI/Retina unsupported for years
**Severity: major · Status: partially-fixed (`display_zoom` in 1.10.8+)**

"Panda3D never supported HiDPI on macOS"; on Retina/Catalina the view was blurry or rendered into a quarter of the window (a `cocoaGraphicsWindow.mm` / `dpi-aware` concern — see the cocoadisplay section above). The fix was to *force-disable* HiDPI; the general issue ([#426](https://github.com/panda3d/panda3d/issues/426)) sat for years and the eventual short-term fix just exposes a `display_zoom` factor for apps to handle themselves.

### No native Wayland backend (X11/XWayland only)
**Severity: major · Status: mitigated-in-1.11 (XInput2 fallback), no native backend**

There is no Wayland display backend — Linux runs through `x11display` (above) under XWayland. Relative/FPS mouse (XF86DGA, the `x-support-xf86dga` path) doesn't work under Wayland, breaking mouselook. A native backend ([#1579](https://github.com/panda3d/panda3d/issues/1579)) is unimplemented as distros default to Wayland.

### Web/WASM is an unmerged experimental branch (from-source emscripten build)
**Severity: major · Status: still-open**

The post-plugin replacement is a WebGL/emscripten port (driving the GLES backend in `glstuff`) on an experimental branch, not part of releases; using it means building Python + Panda from source with emscripten and no supported workflow.

### Where to start (this cluster)

- **Understand a frame first.** Read `panda/src/display/graphicsEngine.cxx`: `render_frame()` (713), `WindowRenderer::do_frame()` (2680), `cull_to_bins()` (1475), `draw_bins()` (1643), `do_draw()` (2043), and the long threading comment in `graphicsEngine.h` (200-320). Pair it with the forum post https://discourse.panda3d.org/t/340.
- **Understand the abstraction contract.** `panda/src/gsgbase/graphicsStateGuardianBase.h` (what every backend must implement) and `panda/src/display/graphicsStateGuardian.h` (the shared base implementation), then `graphicsOutput.h`/`graphicsWindow.h`/`graphicsPipe.h`/`displayRegion.h`/`frameBufferProperties.h`.
- **Window/buffer creation.** `GraphicsEngine::make_output()` (graphicsEngine.cxx:265) and `GraphicsPipe::BufferCreationFlags` in `graphicsPipe.h`; then a concrete pipe's `make_output` (e.g. `eglGraphicsPipe.cxx`).
- **GL behavior.** `panda/src/glstuff/glGraphicsStateGuardian_src.cxx` is where ~all GL bugs live; `glgsg/glgsg.h` shows the macro instantiation. Remember edits compile into GL, GLES1, and GLES2 — guard with `#ifdef OPENGLES`.
- **Per-OS windowing.** `x11display/x11GraphicsWindow.cxx`, `windisplay/winGraphicsWindow.cxx`, `cocoadisplay/cocoaGraphicsWindow.mm` — and remember the concrete GL pipe lives in the sibling `*gldisplay`/`wgldisplay`/`glxdisplay`/`cocoagldisplay`/`egldisplay` module, not in the windowing module.
- **Software / headless reference.** `tinydisplay/tinyGraphicsStateGuardian.cxx` + `zbuffer.cxx` + `ztriangle_*.cxx`.
