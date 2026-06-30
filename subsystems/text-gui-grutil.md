# Text, GUI, grutil & particles

This cluster covers the engine's "2D-facing" content generators and helpers: the text rendering pipeline (`panda/src/text` + its FreeType wrapper `panda/src/pnmtext`), the C++ GUI widget layer (`panda/src/pgui`, the foundation under DirectGui), a grab-bag of graphics utilities (`panda/src/grutil`: MeshDrawer, GeoMipTerrain, MovieTexture, FrameRateMeter, LineSegs, etc.), the legacy C++ particle engine (`panda/src/particlesystem`), and the nonlinear projection/lens-distortion system (`panda/src/distort`). Almost everything here is a `PandaNode` subclass (or produces `GeomNode`s) that lives in the 2-D or 3-D scene graph and is driven by the normal cull/draw traversal. The pieces interlock: `TextNode` provides labels for `PGItem` widgets and for `FrameRateMeter`; `pgui` hooks the cull traversal to register mouse regions; `distort` wraps any camera setup at render time. They share Panda's standard machinery — `CycleData`/`PipelineCycler` for thread-safe state, `Geom`/`GeomVertexData` for geometry, and `RenderState`/`RenderAttrib` for appearance.

## text

**What it is.** The text assembly and rendering system. Given a Unicode string, a `TextFont`, and a `TextProperties` (color, alignment, shadow, wordwrap, etc.), it lays out glyphs into rows and emits `Geom` geometry that can be parented into the 2-D or 3-D scene graph. `TextNode` is the public entry point; the heavy lifting (layout, wordwrap, kerning, bidi-ish property runs, harfbuzz shaping) happens in `TextAssembler`.

**Central abstraction & inheritance.** `TextNode` (`panda/src/text/textNode.h`) multiply-inherits `public PandaNode, public TextEncoder, public TextProperties` — so a TextNode *is* both a scene-graph node and a bundle of text properties, which is why you set color/alignment directly on it. It can be used two ways (documented in the header): parent it into the graph and it renders itself like a hidden `GeomNode`, or keep it detached and call `generate()` to get a fresh ordinary node of baked geometry each time.

**Key classes and roles.**
- `TextNode` — `panda/src/text/textNode.{h,cxx}`. Owns frame/card decoration (`set_frame_*`, `set_card_*`), `max_rows`/overflow handling, and the `FlattenFlags` enum (`FF_light`/`FF_medium`/`FF_strong`/`FF_dynamic_merge`) controlling post-assembly flattening.
- `TextFont` — `panda/src/text/textFont.{h,cxx}`. Abstract base (`TypedReferenceCount`, `Namable`). Defines the `RenderMode` enum (`RM_texture`, `RM_wireframe`, `RM_polygon`, `RM_extruded`, `RM_solid`, `RM_distance_field`) and the pure-virtual `get_glyph(int character, CPT(TextGlyph) &)`.
- `DynamicTextFont` — `panda/src/text/dynamicTextFont.{h,cxx}`. `public TextFont, public FreetypeFont`; rasterizes glyphs on the fly from TTF/OTF via FreeType (guarded by `#ifdef HAVE_FREETYPE`). Packs glyphs into `DynamicTextPage` textures.
- `StaticTextFont` — `panda/src/text/staticTextFont.{h,cxx}`. Wraps a pre-built egg/bam model whose geometry already contains the glyphs (no FreeType needed).
- `DynamicTextPage` / `DynamicTextGlyph` — `panda/src/text/dynamicTextPage.{h,cxx}`, `dynamicTextGlyph.{h,cxx}`. A `DynamicTextPage` *is a* `Texture`; it allocates rectangular slots (`slot_glyph()`, `find_hole()`, `garbage_collect()`) and holds the rasterized bitmaps. This is the glyph cache.
- `TextGlyph` / `GeomTextGlyph` — `panda/src/text/textGlyph.{h,cxx}`, `geomTextGlyph.{h,cxx}`. One renderable glyph: either a textured quad (`set_quad`/`has_quad`/`get_quad`) or full geometry (`set_geom`). `GeomTextGlyph` is a `Geom` specialization (`: public Geom`) that holds a reference to a `TextGlyph` to maintain the per-glyph geom usage count, so dynamic glyphs can be recycled safely once no geoms reference them.
- `TextAssembler` — `panda/src/text/textAssembler.{h,cxx}`. Not normally used directly; `TextNode` delegates layout to it. Handles `set_wtext`/`set_wsubstr`, wordwrap, `dynamic_merge`, multiline mode, and (when built with harfbuzz) complex-script shaping.
- `TextProperties` / `TextPropertiesManager` — `panda/src/text/textProperties.{h,cxx}`, `textPropertiesManager.{h,cxx}`. The formatting bag and a registry mapping names to property sets, used by the in-line `\1name\1...\2` push/pop escape sequences inside text strings.
- `TextGraphic` — `panda/src/text/textGraphic.{h,cxx}`. Lets you embed arbitrary geometry (icons) inline in a run of text.
- `FontPool` — `panda/src/text/fontPool.{h,cxx}`. Filename → shared `TextFont` cache (analogous to `TexturePool`).
- `default_font.cxx` — the compiled-in fallback font (`cmss12`), used when no font is set so text always renders.

**How it plugs in.** `TextNode` is a `PandaNode`, so it participates directly in cull/draw. The output geometry uses standard `Geom`/`RenderState`; for `RM_texture` fonts the glyph quads share the `DynamicTextPage` textures. Downstream consumers: `pgui` (`PGButton`/`PGEntry` labels), `grutil`'s `FrameRateMeter` and `SceneGraphAnalyzerMeter` (both subclass `TextNode`), and DirectGui/OnscreenText in `direct/`.

**Where to start.** To change layout/wordwrap/shaping, read `TextAssembler::assemble_text` and `assemble_paragraph` in `textAssembler.cxx` (the harfbuzz path is at `#if defined(HAVE_HARFBUZZ) && defined(HAVE_FREETYPE)` around line 1482). To change frame/card geometry or the public API, start in `textNode.cxx` (`do_rebuild`, `do_measure`, `generate`). For glyph caching/atlas behavior, `dynamicTextFont.cxx` (`make_glyph`, `slot_glyph`) and `dynamicTextPage.cxx`.

**Gotchas / rationale (community).**
- Rebuilding a TextNode every frame is a classic perf trap: the docs page [Too Many Text Updates](https://docs.panda3d.org/1.10/python/optimization/performance-issues/too-many-text-updates) recommends not regenerating geometry each frame and exploiting the cached glyph pages. Forum threads on animating per-glyph geometry confirm you must reach into the generated `Geom`s rather than re-assemble ([t/31288](https://discourse.panda3d.org/t/31288), [t/29882](https://discourse.panda3d.org/t/29882)).
- Signed-distance-field text (`RM_distance_field`) gives crisp text at any scale and was added across `pnmtext`/`text`; see commit [f4f7df99](https://github.com/panda3d/panda3d/commit/f4f7df9949a04a27332d5b0c3839908a0423342e) ("Add signed-distance-field text rendering to DynamicTextFont and egg-mkfont") and forum [t/24063](https://discourse.panda3d.org/t/24063). For crispness at large sizes you typically raise the font's `point_size`/`pixels_per_unit` rather than scale the node ([t/28009](https://discourse.panda3d.org/t/28009)).
- `set_glyph_scale` interacts subtly with mixed-size runs ([t/4680](https://discourse.panda3d.org/t/4680)).

**Config (`config_text.cxx`).** `text_flatten`, `text_dynamic_merge`, `text_kerning`, `text_use_harfbuzz`, `text_anisotropic_degree`, `text_texture_margin`, `text_poly_margin`, `text_page_size` (atlas page dimensions), `text_small_caps`/`text_small_caps_scale`, `text_default_font`, `text_tab_width`, the in-line escape keys (`text_push_properties_key`, `text_pop_properties_key`, `text_soft_hyphen_key`, `text_soft_break_key`, `text_embed_graphic_key`), `text_hyphen_ratio`, `text_max_never_break`, `text_default_underscore_height`, and the texture sampler defaults `text_minfilter`/`text_magfilter`/`text_wrap_mode`/`text_quality_level`/`text_render_mode`.

## pnmtext

**What it is.** The thin, shared FreeType-2 wrapper. It abstracts loading a font face, setting size/scaling, and rasterizing glyphs — the common substrate used by *both* `text/DynamicTextFont` (glyphs → scene-graph geometry) and `PNMTextMaker` (glyphs → pixels in a `PNMImage`). Keeping this layer separate is why DynamicTextFont can inherit it without dragging in scene-graph code.

**Central abstraction & inheritance.** `FreetypeFont` (`panda/src/pnmtext/freetypeFont.h`) inherits `Namable` and wraps a `FreetypeFace`. It exposes point size, pixels-per-unit, pixel size, scale factor, native antialias, and a `WindingOrder` enum (for outline/polygon extraction). `DynamicTextFont` and `PNMTextMaker` are its two concrete derivations.

**Key classes and roles.**
- `FreetypeFont` — `freetypeFont.{h,cxx}`. `load_font()` (from filename or in-memory buffer), size/scale management, glyph slot acquisition, and the bitmap/outline extraction used to build glyphs. The whole module is gated on FreeType being present.
- `FreetypeFace` — `freetypeFace.{h,cxx}`. A reference-counted, mutex-guarded wrapper around the raw `FT_Face` so a single decoded face can be *shared between copied font instances*. Holds the static `FT_Library` and `acquire_face()/release_face()` to safely set the active char size/DPI. The `Mutex _lock` matters: FreeType faces are not reentrant.
- `PNMTextMaker` — `pnmTextMaker.{h,cxx}`. `public FreetypeFont`; renders strings straight into a `PNMImage` with its own `Alignment` enum (`A_left`/`A_right`/`A_center`), fg/interior colors, and an interior-fill flag. Used for offline/CPU text (e.g. baking labels into textures).
- `PNMTextGlyph` — `pnmTextGlyph.{h,cxx}`. A single rasterized glyph as a pixel buffer, with `place()` to blit it into a target image.

**How it plugs in.** Purely a service layer — it has no scene-graph dependencies and depends on `pnmimage` plus the system FreeType (and optionally harfbuzz). `text/DynamicTextFont` consumes its glyph bitmaps to fill `DynamicTextPage` atlases; `PNMTextMaker` is used by tooling and anyone rendering text to images.

**Where to start.** `freetypeFont.cxx` (`load_font`, `get_glyph`/`render_glyph`, and the SDF/outline paths). For face sharing and thread-safety, `freetypeFace.cxx` (`acquire_face`/`release_face`, `initialize_ft_library`).

**Gotchas / rationale.** The `FreetypeFace` mutex exists precisely because FreeType's `FT_Face` carries mutable per-call state (active size). The pnmtext/text split is the seam through which SDF rendering was added (commit [f4f7df99](https://github.com/panda3d/panda3d/commit/f4f7df9949a04a27332d5b0c3839908a0423342e) touches `freetypeFont.{I,cxx}`).

**Config (`config_pnmtext.cxx`).** `text_point_size`, `text_pixels_per_unit`, `text_scale_factor`, `text_native_antialias` — the defaults inherited by every `FreetypeFont`.

## pgui

**What it is.** The C++ GUI widget framework — the foundation that Python's DirectGui sits on. It provides mouse-interactive 2-D widgets (buttons, text entries, sliders, scroll frames, wait bars) as `PandaNode` subclasses. Each widget owns a `PGMouseWatcherRegion` (a screen rectangle) and a set of "state" subgraphs; the current state's subgraph is what gets rendered. Interaction is wired through `MouseWatcher` events.

**Central abstraction & inheritance.** `PGItem` (`panda/src/pgui/pgItem.h`) `: public PandaNode` is the base of every widget. It defines the full interaction protocol as virtuals — `enter_region`/`exit_region`/`within_region`/`without_region`, `focus_in`/`focus_out`, `press`/`release`/`keystroke`/`candidate`/`move` — plus `activate_region()` and a `cull_callback()`. The class must be parented beneath a `PGTop` for any of this to fire.

**Key classes and roles.**
- `PGItem` — `pgItem.{h,cxx}`. Base widget: holds the `PGMouseWatcherRegion`, the state subgraphs, frame style, optional sound, and a `PGItemNotify` callback hook. Guarded by a `LightReMutex` for thread-safety.
- `PGTop` — `pgTop.{h,cxx}`. The required root of any GUI subgraph under render2d. Its `cull_callback()` swaps in a `PGCullTraverser` and clears/repopulates the `MouseWatcher` region set every cull, forcing depth-first, left-to-right 2-D draw order. Holds the `MouseWatcher` and a `PGMouseWatcherGroup`.
- `PGCullTraverser` — `pgCullTraverser.{h,cxx}`. A `CullTraverser` specialization that carries the owning `PGTop` and a running `_sort_index` so each `PGItem` it visits can register its region with the correct sort.
- `PGButton` — `pgButton.{h,cxx}`. `: public PGItem`; `State` enum `S_ready`/`S_depressed`/`S_rollover`/`S_inactive`, `setup(label, bevel)` or per-state NodePaths, click-button binding, and emits `"<prefix>-<button>"` events. `PGButtonNotify` is its callback interface.
- `PGEntry` — `pgEntry.{h,cxx}`. Text input field; embeds a `TextNode` for display and tracks cursor/selection.
- `PGSliderBar` — `pgSliderBar.{h,cxx}`. Slider/scrollbar; `PGSliderBarNotify` callback.
- `PGScrollFrame` / `PGVirtualFrame` — `pgScrollFrame.{h,cxx}`, `pgVirtualFrame.{h,cxx}`. Clipped/scrollable containers (the virtual frame applies a `ScissorEffect` to its canvas parent so children are clipped to the frame).
- `PGWaitBar` — `pgWaitBar.{h,cxx}`. Progress bar.
- `PGFrameStyle` — `pgFrameStyle.{h,cxx}`. Renders the card/border look (flat, bevel, groove, ridge, etc.) behind a widget.
- `PGMouseWatcherRegion` / `PGMouseWatcherParameter` / `PGMouseWatcherGroup` / `PGMouseWatcherBackground` — bridge classes that turn raw `MouseWatcher` callbacks into `PGItem` method calls and per-event parameters.

**How it plugs in.** This is the crux: a `PGItem`'s region is *not* statically registered. During cull, `PGTop::cull_callback()` (pgTop.cxx:86) installs a `PGCullTraverser`, then each `PGItem::cull_callback()` (pgItem.cxx:197) checks `trav->is_exact_type(PGCullTraverser::get_class_type())` (line 230) and, if its `activate_region()` succeeds, calls `pg_trav->_top->add_region(region)` (line 276). So mouse regions are rebuilt from the visible widgets every frame, using the *current* transform — which is what makes scrolling, hiding, and re-parenting "just work." `PGEntry` depends on `text`; widgets emit Panda events consumed by Python via DirectGui.

**Where to start.** To understand event flow, read `pgItem.cxx` (`cull_callback`, `activate_region`, `press`/`release`) and `pgTop.cxx` (`cull_callback`). For a concrete widget, `pgButton.cxx` (`press`/`release`/`click`, `set_active`). To debug "my widget isn't clickable," the answer is almost always the `PGTop` parenting + region-registration path above.

**Gotchas / rationale (community).**
- DirectGui is explicitly described as layered on PGui, which "detects the mouse position by creating a MouseWatcherRegion for each clickable region" ([t/10868](https://discourse.panda3d.org/t/10868)). DirectGUI dispatches via `PGItem::within_region`/events ([github #1603](https://github.com/panda3d/panda3d/issues/1603)).
- To find/debug regions visually: `base.mouseWatcherNode.showRegions(render2d, 'gui-popup', 0)` reveals every clickable rectangle ([t/2239](https://discourse.panda3d.org/t/2239)); `MouseWatcher::get_over_region()` returns the region under the mouse ([t/26615](https://discourse.panda3d.org/t/26615)).
- Maintainer note: issue [#1603 "Make PGui nice"](https://github.com/panda3d/panda3d/issues/1603) tracks API ergonomics and confirms "there are actually lots of comments in the code that are pretty good, so just reading the source works."

**Config (`config_pgui.cxx`).** `scroll_initial_delay` and `scroll_continued_delay` — auto-repeat timing for held scroll buttons.

## grutil

**What it is.** "Graphics utilities" — an unrelated collection of helper classes that don't fit elsewhere but build on the scene graph and `Geom` system. Highlights: `MeshDrawer` (recycle one Geom to draw masses of dynamic triangles/billboards/particles), `GeoMipTerrain` (heightfield → LOD terrain), `ShaderTerrainMesh` (GPU tessellated terrain, the modern alternative), `MovieTexture` (video-backed Texture), `FrameRateMeter`/`SceneGraphAnalyzerMeter` (on-screen diagnostics), `LineSegs`/`CardMaker`/`FisheyeMaker` (geometry generators), `RigidBodyCombiner` (batch many moving rigid nodes), plus `PfmVizzer`, `HeightfieldTesselator`, `MultitexReducer`, and `PipeOcclusionCullTraverser`.

**Key classes and roles.**
- `MeshDrawer` — `meshDrawer.{h,cxx}`. `: public TypedObject`. Owns one recycled `Geom` with vertex/normal/uv/color channels; `begin(camera, render)` / `tri()` / `particle()` / `blended_particle()` / `end()` let you stream triangles each frame within a fixed `set_budget()` triangle cap. `MeshDrawer2D` (`meshDrawer2D.{h,cxx}`) is the screen-space variant.
- `GeoMipTerrain` — `geoMipTerrain.{h,cxx}`. `: public TypedObject`. Implements Geometrical MipMapping (de Boer's paper, cited in the header) over a `PNMImage` heightfield, producing a hierarchy of `GeomNode` blocks. `set_focal_point`, `set_bruteforce`, `set_auto_flatten` (`AFM_off`/`light`/`medium`/`strong`), `update()` (rebuilds only blocks whose LOD changed), `get_elevation`, `get_normal`, `calc_ambient_occlusion`.
- `ShaderTerrainMesh` — `shaderTerrainMesh.{h,cxx}`. GPU-side tessellated terrain (the recommended modern path; uses a hardware tessellation shader rather than CPU rebuilds).
- `MovieTexture` — `movieTexture.{h,cxx}`. `: public Texture`. Streams frames from a `MovieVideo`/`MovieVideoCursor`; `play`/`stop`/`set_time`/`set_loop`/`set_play_rate`/`synchronize_to(AudioSound*)`. Uses a `PipelineCycler` and a `cull_callback()` so frame fetch happens at cull time. `HTMLVideoTexture` (`htmlVideoTexture.{h,cxx}`) is the Emscripten/web variant.
- `FrameRateMeter` — `frameRateMeter.{h,cxx}`. `: public TextNode`. Self-updating FPS readout; `setup_window()` makes its own corner `DisplayRegion`. `SceneGraphAnalyzerMeter` (`sceneGraphAnalyzerMeter.{h,cxx}`) is the analogous node/vertex/state-count readout.
- `LineSegs` — `lineSegs.{h,cxx}`. `: public Namable`. `move_to`/`draw_to`/`set_color`/`set_thickness` then `create()` → a `GeomNode` of line primitives. A visualization/editing tool, not a perf path.
- `CardMaker` — `cardMaker.{h,cxx}`. Generates textured quads/cards (used everywhere for UI and fullscreen effects).
- `RigidBodyCombiner` — `rigidBodyCombiner.{h,cxx}`. `: public PandaNode`. Flattens many independently-moving children into as few `Geom`s as possible via `NodeVertexTransform`; call `collect()` once at setup, then move children freely. Header warns: RenderEffects like Billboards are unsupported below it, and `collect()` is expensive.
- `FisheyeMaker` (`fisheyeMaker.{h,cxx}`), `HeightfieldTesselator`, `PfmVizzer`, `MultitexReducer`, `PipeOcclusionCullTraverser` — specialized geometry/visualization/optimization tools.

**How it plugs in.** No single theme — each class is a leaf helper. `MeshDrawer`/`LineSegs`/`CardMaker` produce `Geom`/`GeomNode`; `GeoMipTerrain`/`ShaderTerrainMesh` produce terrain subgraphs; `MovieTexture` plugs into the `Texture`/material system and is sampled like any texture; `FrameRateMeter` builds on `text`. `MeshDrawer` is also a common rendering backend for the particle system.

**Where to start.** `meshDrawer.cxx` (`begin`/`end` rebuild loop, `GeomVertexRewriter` usage) for dynamic batching; `geoMipTerrain.cxx` (`update`, `generate`, block LOD selection) for terrain; `movieTexture.cxx` (`cull_callback`, `do_update_frames` at line 662) for video.

**Gotchas / rationale (community).**
- `MeshDrawer` must be re-issued *every frame* — it recycles one Geom, so "drawing a billboard once" is meaningless ([t/6321](https://discourse.panda3d.org/t/6321)). It's fast but oriented toward "easily putting non-modelled geometry on screen," and notably provides no per-face normals for triangles ([t/26278](https://discourse.panda3d.org/t/26278)).
- `GeoMipTerrain.update()` only rebuilds blocks whose LOD actually changed; in bruteforce mode it should cost ~nothing if the camera barely moved ([t/5899](https://discourse.panda3d.org/t/5899)), and it returns `False` when nothing changed ([t/11259](https://discourse.panda3d.org/t/11259)). With a large positional offset on the terrain, LOD selection can misbehave unless near/far/focal-point are set consistently ([t/11259](https://discourse.panda3d.org/t/11259)). You can clamp quality near the focal point with a minimum LOD level ([docs: Geometrical MipMapping](https://docs.panda3d.org/1.10/python/programming/terrain/geometrical-mipmapping)).

**Config (`config_grutil.cxx`).** `frame_rate_meter_milliseconds`, `frame_rate_meter_update_interval`, `frame_rate_meter_text_pattern`, `frame_rate_meter_ms_text_pattern`, `frame_rate_meter_layer_sort`, `frame_rate_meter_scale`, `frame_rate_meter_side_margins`; the matching `scene_graph_analyzer_meter_*` set; `movies_sync_pages` (multi-page movie texture sync); `pfm_vis_max_vertices`/`pfm_vis_max_indices` (PfmVizzer limits); `ae_undershift_factor_16`/`ae_undershift_factor_32` (ambient-occlusion shift).

## particlesystem

**What it is.** Panda's classic C++ particle engine. A `ParticleSystem` owns a pool of particles and is driven by three pluggable strategy objects: an **emitter** (where/which direction particles are born), a **factory** (what kind of particle and its initial attributes), and a **renderer** (how living particles become geometry). A global `ParticleSystemManager` ticks and renders all registered systems. Note: this is the lower-level engine — Python's `direct.particles` (ParticleEffect, `.ptf` files, the Particle Panel) wraps it.

**Central abstraction & inheritance.** `ParticleSystem` (`panda/src/particlesystem/particleSystem.h`) `: public Physical` (from `panda/src/physics`), so particles are physically integrated. The four extension points are all abstract bases: `BaseParticle`, `BaseParticleEmitter`, `BaseParticleFactory`, `BaseParticleRenderer`.

**Key classes and roles.**
- `ParticleSystem` — `particleSystem.{h,cxx}`. Core loop and config: `set_pool_size`, `set_birth_rate`/`set_litter_size`/`set_litter_spread`, `set_emitter`/`set_factory`/`set_renderer`, spawn-on-death and template support, `set_floor_z`, local-velocity flag, `update(dt)` (particleSystem.cxx:457), `birth_particle()`/`kill_particle()`. Defaults wired in the constructor: `SphereSurfaceEmitter`, `PointParticleRenderer`, `PointParticleFactory` (particleSystem.cxx:73–78).
- `ParticleSystemManager` — `particleSystemManager.{h,cxx}`. Registry + update coordinator; `attach_particlesystem`, `do_particles(dt)` ticks every system (optionally every Nth frame via `set_frame_stepping`). Has a `PStatCollector`.
- `BaseParticle` — `baseParticle.{h,cxx}`. `: public PhysicsObject`. Abstract particle with age/lifespan/alive/index and parameterized age/velocity; pure-virtual `init`/`die`/`update`/`make_copy`. Concrete types: `PointParticle`, `OrientedParticle`, `ZSpinParticle`.
- `BaseParticleEmitter` — `baseParticleEmitter.{h,cxx}`. `: public ReferenceCount`. `emissionType` enum (`ET_EXPLICIT`/`ET_RADIATE`/`ET_CUSTOM`), amplitude/spread, offset force, `generate(pos, vel)`. Concrete emitters: `BoxEmitter`, `SphereVolumeEmitter`, `SphereSurfaceEmitter`, `DiscEmitter`, `LineEmitter`, `PointEmitter`, `RectangleEmitter`, `RingEmitter`, `TangentRingEmitter`, `ArcEmitter` (collected in `emitters.h`).
- `BaseParticleFactory` — `baseParticleFactory.{h,cxx}`. `populate_particle()` stamps lifespan/mass/etc. onto a new particle. Concrete: `PointParticleFactory`, `OrientedParticleFactory`, `ZSpinParticleFactory` (`particlefactories.h`).
- `BaseParticleRenderer` — `baseParticleRenderer.{h,cxx}`. `: public ReferenceCount`. Owns the output `GeomNode`/`NodePath`; `ParticleRendererAlphaMode` (`PR_ALPHA_NONE`/`OUT`/`IN`/`IN_OUT`/`USER`) and blend method enums; `birth_particle`/`kill_particle` hooks. Concrete: `PointParticleRenderer`, `SpriteParticleRenderer`, `LineParticleRenderer`, `GeomParticleRenderer`, `SparkleParticleRenderer` (`particles.h`).
- `ColorInterpolationManager` — `colorInterpolationManager.{h,cxx}`. Animates particle color over normalized lifetime via interpolation segments.

**How it plugs in.** Each frame `ParticleSystemManager::do_particles(dt)` calls `ParticleSystem::update(dt)`, which: ages/integrates particles (via the `Physical`/physics layer), spawns new ones through `birth_particle()` (calls `_factory->populate_particle` then `_emitter->generate`), kills dead ones, and notifies the renderer (`_renderer->birth_particle`/`kill_particle`). The renderer's `GeomNode` lives under a render-parent NodePath in the scene graph. The system depends on `physics`, `pgraph`, and (for sprites) `gobj`/texture; it can integrate with `grutil`'s `MeshDrawer` for batched output.

**Where to start.** `particleSystem.cxx` (`update` at line 457, `birth_particle` at 135, `kill_particle` at 290) is the heartbeat. To add a new shape, copy an emitter (e.g. `boxEmitter.cxx`) and implement `assign_initial_position`/`assign_initial_velocity`. To add a new look, subclass `BaseParticleRenderer` (study `spriteParticleRenderer.cxx`, the most-used one).

**Gotchas / rationale (community).**
- Renderer choice is the main performance lever. A `SpriteParticleRenderer` particle is a camera-facing textured quad computed in 2-D — fast for many particles — while `GeomParticleRenderer` instances a full 3-D model per particle (heavier) ([docs: Particle Renderers](https://docs.panda3d.org/1.10/python/programming/particle-effects/renderers); [docs: Particle Panel](https://docs.panda3d.org/1.10/python/programming/particle-effects/using-the-particle-panel)).
- Sprites *always* face the camera by definition; if you need oriented sprites you must use geom particles instead ([t/1443](https://discourse.panda3d.org/t/1443)).
- You can drive the renderers without the full physics system if you only want their geometry output ([t/25973](https://discourse.panda3d.org/t/25973)).

**Config (`config_particlesystem.cxx`).** No published `ConfigVariable`s; the file only registers type handles / module init. Tuning is done per-system through the setters above (and via `.ptf` files in the Python layer).

## distort

**What it is.** The nonlinear projection / lens-distortion module (built into the `pandafx` library, `EXPCL_PANDAFX`). It lets you render scenes through non-perspective lenses (fisheye, cylindrical, spherical) even though the GPU only does linear projection, and to pre-distort imagery for curved screens or off-axis projectors. The orchestrator is `NonlinearImager`; the workhorse is `ProjectionScreen` (CPU projective texturing); the lens math lives in a family of `Lens` subclasses.

**Central abstraction & inheritance.** The nonlinear lenses all derive from `Lens` (defined in `gobj`): `FisheyeLens`, `CylindricalLens`, `OSphereLens` (orthographic sphere), `PSphereLens` (perspective sphere) — each `: public Lens` (e.g. `fisheyeLens.h`, `cylindricalLens.h:33`, `oSphereLens.h:30`, `pSphereLens.h:33`) and overriding the projection primitives `do_extrude`, `do_extrude_vec`, `do_project`, and the fov↔film/focal-length conversions.

**Key classes and roles.**
- `NonlinearImager` — `nonlinearImager.{h,cxx}`. The director. Its header lays out the three camera roles precisely: **source cameras** (normal perspective cameras under `render` that capture the world, set per screen via `set_source_camera`), **projectors** (the lens associated with each `ProjectionScreen`), and **viewers** (the possibly-nonlinear cameras that observe the screens and write to a `DisplayRegion`). It wires these together, creating render-to-texture buffers per source camera and an `AsyncTask`/callback to recompute as things move.
- `ProjectionScreen` — `projectionScreen.{h,cxx}`. `: public PandaNode`. Recomputes UVs (in the CPU) on its child geometry so that a texture appears projected from a given `LensNode` projector — works for *any* lens, linear or nonlinear. `generate_screen()` builds screen geometry; `set_projector()` chooses the lens; supports an undistortion LUT (`set_undist_lut`, a `PfmFile`). Has a `cull_callback()` to refresh UVs when the relative transform changes. Note the header's caveat: this is pure CPU UV computation, *not* hardware projective texturing (use `NodePath::project_texture()` for that).
- `FisheyeLens` — `fisheyeLens.{h,cxx}`. Spherical distortion up to 360° FOV.
- `CylindricalLens` — `cylindricalLens.{h,cxx}`. Cylindrical projection (panoramas).
- `OSphereLens` / `PSphereLens` — `oSphereLens.{h,cxx}`, `pSphereLens.{h,cxx}`. Orthographic and perspective spherical lenses.

**How it plugs in.** `NonlinearImager` sits *outside* the normal scene graph as a controller over `GraphicsEngine`/`GraphicsOutput`/`Camera`/`DisplayRegion`. It renders each source camera into an offscreen buffer, applies those buffers as textures onto `ProjectionScreen` geometry (whose UVs encode the lens), then renders the screens through the viewer's lens into the final DisplayRegion. The `Lens` subclasses are usable on their own (assign a `FisheyeLens` to any `Camera`) but full nonlinear *rasterization* of an arbitrary scene needs the imager-plus-screen pipeline. `FisheyeMaker` in `grutil` complements this by generating fisheye/cube screen geometry.

**Where to start.** `nonlinearImager.cxx` (`add_screen`, `set_source_camera`, `add_viewer`, and the recompute task) to understand the multi-camera dance; `projectionScreen.cxx` (`recompute`, `make_screen`, `generate_screen`) for the UV math; an individual lens `.cxx` (`fisheyeLens.cxx` `do_project`/`do_extrude`) to add or fix a lens type.

**Gotchas / rationale (community).** The three camera roles (source / projector / viewer) are the chronic source of confusion; the header's "dark room with projection screens" analogy is the best mental model. Community examples for making a camera fisheye via `NonlinearImager` (`from panda3d.fx import *`) are in [t/26635](https://discourse.panda3d.org/t/26635); a worked curved-screen / large-FOV projection setup is discussed in [t/29298](https://discourse.panda3d.org/t/29298).

**Config (`config_distort.cxx`).** `project_invert_uvs` — flips the V coordinate when computing projected UVs (compensates for renderers/textures with inverted vertical UV origin).

## Where to start (this cluster)

- **Text pipeline:** `panda/src/text/textNode.cxx` (public API + assembly entry) → `panda/src/text/textAssembler.cxx` (layout/wordwrap/harfbuzz) → `panda/src/text/dynamicTextFont.cxx` + `panda/src/pnmtext/freetypeFont.cxx` (rasterization & glyph atlas).
- **GUI:** `panda/src/pgui/pgItem.cxx` (`cull_callback`/`activate_region`) together with `panda/src/pgui/pgTop.cxx` (`cull_callback`) — this pair *is* how widgets become clickable. Then `panda/src/pgui/pgButton.cxx` for a concrete widget.
- **grutil helpers:** pick the file by feature — `meshDrawer.cxx` (dynamic batching), `geoMipTerrain.cxx` (CPU terrain) or `shaderTerrainMesh.cxx` (GPU terrain), `movieTexture.cxx` (video), `frameRateMeter.cxx` (diagnostics).
- **Particles:** `panda/src/particlesystem/particleSystem.cxx` (`update`/`birth_particle`/`kill_particle`) plus the `Base*Emitter`/`Base*Factory`/`Base*Renderer` headers to see the three plug-in points; `spriteParticleRenderer.cxx` is the canonical renderer to study.
- **Distort:** `panda/src/distort/nonlinearImager.cxx` for the camera orchestration, `panda/src/distort/projectionScreen.cxx` for the UV recompute, and any `*Lens.cxx` for the projection math.

## Known shortcomings & footguns

The constructive sections above cover how this cluster *works*. This section collects the community-mined ways it *breaks* — long-standing GUI and text limitations that repeatedly bite users. These are sourced from forum/issue history and maintainer commentary; severity/status tags reflect the catalogue's assessment, not a re-verification here.

### DirectGUI is a poor, dated GUI system
**Severity: major · Status: still-open (maintainer-acknowledged; no successor)**

DirectGui (Python) sits on the C++ `pgui` widget layer described above (see the [pgui](#pgui) section), and the foundation is solid, but the user-facing API is widely regarded as awkward and outdated.

> "There are a couple of problems with DirectGUI: Its API is unintuitive; It is
> written in Python, so not available to C++ users; The defaults are bad.
> Inevitably, every GUI-heavy application ends up writing their own wrapper around
> DirectGUI." — rdb *(maintainer)*, [#1603](https://github.com/panda3d/panda3d/issues/1603)

(The same issue, [#1603 "Make PGui nice"](https://github.com/panda3d/panda3d/issues/1603), is referenced in the `pgui` gotchas above as the tracker for API ergonomics.)

### No HTML/CSS or visual-designer GUI; every alternative died
**Severity: major · Status: still-open**

There is no supported HTML/CSS-style layout engine or visual GUI designer. The history is a graveyard of attempts — CEGUI, libRocket (on the never-merged `panda3d_2_0` branch), awesomium/Berkelium, LUI, Rocket — none of which landed as a supported, documented system. In practice you build UIs with DirectGui (and its `pgui` foundation) or roll your own.

### DirectGUI is mouse-only (no gamepad/keyboard navigation)
**Severity: major · Status: still-open**

DirectGui has no built-in focus traversal: there is no out-of-the-box way to move focus between widgets via keyboard or gamepad. This follows from the `pgui` model — mouse regions are rebuilt from visible widgets each cull (see the [pgui](#pgui) section), but there is no equivalent navigation graph — so console-style or accessible UIs require a custom input layer ([#1351](https://github.com/panda3d/panda3d/issues/1351)).

### CJK/Unicode text needs a HarfBuzz build + a font with the glyphs
**Severity: minor · Status: mitigated (HarfBuzz builds)**

Complex scripts (Arabic, Indic, CJK, etc.) require a HarfBuzz-enabled build *and* a font that actually contains the glyphs. The shaping path is the `#if defined(HAVE_HARFBUZZ) && defined(HAVE_FREETYPE)` branch in `TextAssembler` (see the [text](#text) section, "Where to start"). Even with HarfBuzz, the compiled-in default font (`cmss12`) lacks most non-Latin glyphs, so missing characters silently render as blanks or boxes — you must supply a glyph-bearing `DynamicTextFont`.
