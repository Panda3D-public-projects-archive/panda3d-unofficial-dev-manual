# Scene graph (pgraph)

This cluster is the beating heart of Panda3D: the scene-graph data structure (`PandaNode` and its many subclasses), the immutable, reference-counted, slot-indexed state system (`RenderState`/`RenderAttrib`, `TransformState`, `RenderEffect`/`RenderEffects`), the high-level navigation/editing API (`NodePath`), and the per-frame **cull traversal** that walks the graph, accumulates net state/transform, view-frustum-culls, and emits drawable `Geom`s into sorted output queues (`CullBin`s). `panda/src/pgraph` holds the core machinery; `panda/src/pgraphnodes` holds higher-level semantic nodes (lights, LOD, sequence/switch, callback, compute); `panda/src/cull` holds the concrete `CullBin` sorting implementations and the two `CullHandler`s that consume cull results. The two hardest ideas for new contributors live here: (1) **state composition** — how attribs override and merge as you descend the tree — and (2) the **copy-on-write `PipelineCycler`** that lets the cull thread read a stable snapshot of the graph while the app thread mutates it.

## pgraph

**What it is.** The core scene-graph engine. It defines the universal node base class `PandaNode`, the path/handle abstraction `NodePath`, the immutable state objects (`RenderState`, `TransformState`, `RenderAttrib`, `RenderEffect`, `RenderEffects`), the cull-traversal framework (`CullTraverser`, `CullTraverserData`, `CullResult`, `CullableObject`, `CullHandler`), the renderable leaf `GeomNode`, the `Camera`/`LensNode` that drives a view, and a large family of concrete `RenderAttrib` subclasses (`TextureAttrib`, `ColorAttrib`, `TransparencyAttrib`, `CullBinAttrib`, `ClipPlaneAttrib`, `DepthOffsetAttrib`, etc.) and `RenderEffect` subclasses (`BillboardEffect`, `CompassEffect`, `DecalEffect`). This is also where the **bin registry** (`CullBinManager`) and the slot registry (`RenderAttribRegistry`) live.

**Central abstraction & inheritance.**
- `PandaNode` (`panda/src/pgraph/pandaNode.h`) — base of *every* scene-graph node. Inherits `TypedWritableReferenceCount` (bam-serializable + ref-counted) and `Namable`. It owns parent/child link lists (`Up`/`Down`, stored copy-on-write via `COWPT`), a `TransformState`, a `RenderState`, a `RenderEffects`, draw/collide masks, bounds, and tags — *all* wrapped in a `PipelineCycler<CData>` (line 701) so they can be cycled across pipeline stages. Note `is_renderable()` is `final` and gated by a `set_renderable()` flag; the cull traversal calls `add_for_draw()` (overridden by `GeomNode`) for renderable nodes.
- `RenderState` (`renderState.h`) — inherits `NodeCachedReferenceCount`. An immutable, interned *set* of `RenderAttrib`s. You never construct one; you call `RenderState::make(...)` or compose existing ones. Internally a `SimpleHashMap` of `(slot -> Attribute{attrib, override})` plus a precomputed hash; states are uniquified globally so pointer-equality == value-equality.
- `RenderAttrib` (`renderAttrib.h`) — inherits `TypedWritableReferenceCount`. Base of one renderable property (texture, color, depth-test...). Each subclass returns a unique integer **slot** from `get_slot()` (pure virtual, line 87). Attribs are interned in a static set keyed by `compare_to_impl`; identical attribs share one pointer. Key virtuals to override when adding a new attrib: `compose_impl`, `invert_compose_impl`, `compare_to_impl`, `get_hash_impl`, and the bam I/O.
- `TransformState` (`transformState.h`) — `final`, inherits `NodeCachedReferenceCount`. Immutable transform (componentwise pos/hpr/scale/shear *or* a raw matrix), interned and reference-counted exactly like `RenderState`.
- `RenderEffect` (`renderEffect.h`) — inherits `TypedWritableReferenceCount`. The crucial doc difference from `RenderAttrib` (renderEffect.h:31-46): a `RenderAttrib` *propagates down to the leaves* regardless of which node it sits on, whereas a `RenderEffect` is *applied immediately at the node where it is encountered* during cull (billboarding, compass, decal). `RenderEffects` is the per-node container of effects.
- `CullTraverser` (`cullTraverser.h`) — `TypedReferenceCount`. Performs the depth-first walk. `CullTraverserData` (`cullTraverserData.h`) is the per-node accumulator (net transform, accumulated `RenderState`, view frustum, `CullPlanes`, instance list, draw mask).
- `GeomNode` (`geomNode.h`) — the renderable leaf. Holds a copy-on-write list of `(Geom, RenderState)` entries; its `add_for_draw()` (geomNode.cxx) composes the accumulated state with each Geom's state and hands a `CullableObject` to the `CullHandler`.
- `Camera` (`camera.h`) inherits `LensNode`; carries the `camera_mask` (DrawMask), `initial_state`, `lod_center`/`lod_scale`, `cull_center`, and tag-state map that the traversal reads.

**The state/attrib system (the part newcomers find hardest).** A `RenderState` is "a collection of `RenderAttribs`, like `TextureAttrib`, `ColorAttrib`... The `RenderState` and `RenderAttrib` objects are const, so when you want to change one, you make a new one" (community, Discord: https://discord.com/channels/524691714909274162/533048345791299634/800606173916692482). Each attrib *type* owns a fixed **slot** assigned at startup by `RenderAttribRegistry::register_slot` (`renderAttribRegistry.h:52`). A `RenderState` is therefore a sparse array indexed by slot, and a `SlotMask` (`BitMask32`, renderAttribRegistry.h:46) records which slots are filled — making `compose()`/`compare_to()` fast bitwise/array operations rather than map merges. **Composition** (`RenderState::compose`) walks slots: a child's attrib for a slot replaces the parent's, unless the parent set a higher `override`. This is how "set a texture high in the tree, override it lower down" works. The slot scheme came from the 2008 `dev_slots_2008` branch (commit `26754b86`, "merge dev_slots_2008: slot-based RenderState implementation") and the later move to `SimpleHashMap` + `garbage_collect()` (commit `229cf67a`) was groundwork for threaded pipelining.

> **Gotcha — only 32 attrib slots.** `_max_slots = 32` (`renderAttribRegistry.h:50`) and the mask is a `BitMask32`. Panda already ships ~30 built-in attribs, so registering many custom attribs can exhaust the slots: GitHub issue #500 "Running out of attrib slots" (https://github.com/panda3d/panda3d/issues/500). If you add a built-in attrib you are consuming a global slot. The header comment itself flags that the next step is a 64-bit mask.

**The copy-on-write / PipelineCycler pattern (the other hard part).** Every mutable field of a `PandaNode` lives inside `PandaNode::CData`, owned by `PipelineCycler<CData> _cycler` (pandaNode.h:701). Readers use `CDReader`/`CDStageReader`; writers use `CDWriter` (typedefs at pandaNode.h:702-706). With threaded pipelining enabled, the cull thread reads one pipeline stage while the app thread writes another, and writes are copy-on-write so the cull thread never sees a half-mutated node. The child/parent lists and the Geom list are themselves `COWPT`/`CopyOnWriteObj`, copied lazily only on first write (pandaNode.h:683-687). **This pattern is real and fragile**: the threaded `PipelineCycler` "has not been reliably thread-safe" and is the subject of the in-progress epoch-based-reclamation rewrite, PR #1853 "Implement EBR to solve scenegraph threading" (https://github.com/panda3d/panda3d/pull/1853), whose stack traces show contention right at `PipelineCyclerTrueImpl::write_stage`. If you touch `CData` layout or locking, that PR is required reading.

**How it plugs into the rest of the engine.** `display`/`GraphicsEngine` sets up a `SceneSetup` and calls `CullTraverser::traverse(root)` once per `DisplayRegion` per frame; the traverser reads the active `Camera`'s lens, mask and initial state. `CullTraverser::do_traverse` (cullTraverser.cxx:178) inspects each node's `fancy_bits` (the `FancyBits` enum, pandaNode.h:319: `FB_transform`, `FB_state`, `FB_effects`, `FB_cull_callback`, `FB_renderable`, `FB_decal`, ...) to skip uninteresting nodes cheaply; for interesting ones it calls `data.apply_transform_and_state(this)` (which composes the node's transform/state/effects into the accumulator, and runs `RenderEffect::cull_callback`), then `node->cull_callback()` for nodes that override it (LOD/Switch/Sequence/Callback), then `node->add_for_draw()` for renderables, then recurses into children via `traverse_down`. The downstream `CullHandler` (either `DrawCullHandler` for immediate draw or `BinCullHandler` for sorted draw) receives `CullableObject`s and stuffs them into `CullResult`/`CullBin`s. `NodePath` is the app-facing wrapper that everything else (loader, actor, GUI, collision) uses to manipulate the graph.

**Where to start reading (entry points).**
- To understand a frame: `cullTraverser.cxx` `traverse()` → `do_traverse()` (lines 178-241) → `cullTraverserData.cxx` `apply_transform_and_state()`/`apply_transform()` (line 96) → `geomNode.cxx` `add_for_draw()`.
- To understand state: `renderState.cxx` `make()`, `compose()`, `do_compose`; `renderAttrib.cxx` interning; `renderAttribRegistry.cxx`.
- To add a new render attribute: copy an existing small one (e.g. `colorWriteAttrib.h/.cxx/.I`), implement `make()`, `compose_impl`, `compare_to_impl`, `get_hash_impl`, bam I/O, register the slot in `config_pgraph.cxx`, and add it to `CMakeLists.txt`.
- To debug threading/CoW: `pandaNode.h` `CData` + `_cycler`, and PR #1853.

**Relevant config variables (`config_pgraph.cxx`).**
- `state-cache` / `transform-cache` (bool) — enable the global compose/compare caches for `RenderState`/`TransformState`.
- `garbage-collect-states` (bool, default true) + `garbage-collect-states-rate` (double) — how interned states are reclaimed.
- `uniquify-states` / `uniquify-transforms` / `uniquify-attribs` (bool) — force global de-duplication so pointer equality implies value equality (and enables fast `compare_sort`).
- `paranoid-compose`, `paranoid-const`, `auto-break-cycles`, `detect-graph-cycles`, `unambiguous-graph` — debugging/validation aids for the graph and the compose caches.
- `fake-view-frustum-cull` (bool) — render frustum-culled geometry in red wireframe instead of dropping it (see `do_fake_cull`, cullTraverser.cxx:271).
- `depth-offset-decals` (bool) — implement `DecalEffect` via `DepthOffsetAttrib` rather than the legacy two-pass decal.
- `m-dual`, `m-dual-opaque`, `m-dual-transparent`, `m-dual-flash` — control `M_dual` transparency (binary-alpha opaque pass + sorted blended pass).
- `flatten-geoms`, `premunge-data`, `preserve-geom-nodes` — flatten/optimization behavior.

> **Gotcha — flatten doesn't cross ModelNodes.** `flatten_strong()` stops at `ModelNode`s; call `clear_model_nodes()` first (community: https://discourse.panda3d.org/t/11911). And flattening only pays off with many nodes (https://discourse.panda3d.org/t/27492). Note `flatten_strong()` was later changed to also `unify()` geoms (commit `5c623893`).

## pgraphnodes

**What it is.** The library of *specialized* `PandaNode` subclasses that add semantic behavior on top of the bare node: the light family, level-of-detail and animation-selection nodes, user-callback and GPU-compute nodes, and the fixed-function `ShaderGenerator`. Anything that needs a `cull_callback` to make per-frame decisions (which child to show, what distance bucket we're in) tends to live here rather than in `pgraph`.

**Key classes & roles.**
- `LightNode` (`lightNode.h`) — multiply-inherits `Light` (the abstract light interface, in `panda/src/pgraph/light.h`) and `PandaNode`. Base for lights that *don't* need a lens. `AmbientLight` (`ambientLight.h`) derives from it.
- `LightLensNode` (`lightLensNode.h`) — multiply-inherits `Light` and **`Camera`** (lightLensNode.h:33), because shadow-casting lights need a lens/view to render a shadow map. Holds shadow-buffer state (`set_shadow_caster`, `_shadow_map`, `_sbuffers`). `DirectionalLight`, `PointLight`, `Spotlight`, and `RectangleLight` derive from this directly (`SphereLight` derives from `PointLight`, so transitively from `LightLensNode`). (Spotlight needs a lens, which is why it inherits the lens path rather than plain `LightNode` — see lightNode.h:23-25.)
- `LODNode` (`lodNode.h`) — `PandaNode` whose `cull_callback` (lodNode.cxx) measures the distance from the LOD center (the camera's `lod_center`, scaled by `lod_scale`) and shows exactly one child whose `[in, out)` switch range contains that distance. `add_switch(in, out)` with `in > out` ("in" = far switch-in, "out" = near switch-out; see lodNode.h:49-53). `FadeLODNode` (`fadeLodNode.h`) cross-fades between two levels over `lod-fade-time`. Community confirms both "render exactly one of their children, according to the distance of that node from the camera" (https://discourse.panda3d.org/t/1133).
- `SelectiveChildNode` (`selectiveChildNode.h`) — "now vestigial" base (selectiveChildNode.h:26) for nodes that show one child; `SequenceNode` and `SwitchNode` and historically `LODNode` relate to it.
- `SequenceNode` (`sequenceNode.h`) — cycles through children over time like a flipbook (an `AnimInterface`); `SwitchNode` (`switchNode.h`) shows a single explicitly-selected child. Both override `has_single_child_visibility()`/`get_visible_child()`.
- `CallbackNode` (`callbackNode.h`) — lets app code register `CallbackObject`s fired at cull/draw time (e.g. `set_cull_callback`, `set_draw_callback`); the hook for custom rendering without subclassing.
- `ComputeNode` (`computeNode.h`) — dispatches GPU compute shaders during the draw pass (`add_dispatch(x,y,z)`).
- `UvScrollNode` (`uvScrollNode.h`) — animates a texture matrix over time.
- `ShaderGenerator` (`shaderGenerator.h`, ~80 KB `.cxx`) — the fixed-function-to-GLSL auto-shader: given a `RenderState` it synthesizes a shader implementing that state. This is the single largest and most-edited file in the cluster and the place to look when "auto-shader" output is wrong.
- `SceneGraphAnalyzer` (`sceneGraphAnalyzer.h`) — a diagnostic that walks a subgraph counting nodes/verts/geoms; useful for understanding flatten payoff.

**Central abstraction & inheritance.** Everything here is `PandaNode` (directly or via `Camera`/`LensNode`). The recurring pattern is *override `cull_callback(CullTraverser*, CullTraverserData&)`* to make a per-frame decision and prune/select children, returning `false` to stop the traversal descending. Lights additionally implement the `Light` mixin so they can be attached to a `LightAttrib` (in `pgraph`) and consumed by the GSG.

**How it plugs in.** These nodes are added to the graph like any other and are visited by the same `CullTraverser`. Their `cull_callback` flag sets `FB_cull_callback` so `do_traverse` (cullTraverser.cxx:205) calls them. Lights are referenced by `LightAttrib`/`LightRampAttrib` (in `pgraph`) which the cull traversal accumulates into the `RenderState`; `LightLensNode`s additionally hand a shadow buffer to the `GraphicsEngine`. `ShaderGenerator` is invoked by the GSG (`display`) when `ShaderAttrib::make_auto()` is in effect.

**Where to start reading.** `lodNode.cxx::cull_callback` is the canonical example of a decision node (and the most-asked-about: see the LOD forum threads). For lights, read `lightLensNode.cxx` (shadow setup) and `directionalLight.cxx`/`pointLight.cxx`. To add a new decision node, subclass `PandaNode`, override `cull_callback` + `has_single_child_visibility`/`get_visible_child`, and register it in `config_pgraphnodes.cxx` (`init_type` + `register_with_read_factory`).

> **Gotcha — LOD prunes geometry, not collisions.** Because `LODNode` only selects which child to *render*, collision solids parented under non-visible LOD levels can still be active/processed; users repeatedly hit this (https://discourse.panda3d.org/t/9308, https://discourse.panda3d.org/t/9957). The node is doing exactly what it's designed to: cull-time visual selection, nothing more.

**Relevant config variables (`config_pgraphnodes.cxx`).**
- `default-lod-type` (`pop`|`fade`) — what `LODNode::make_default_lod()` produces.
- `support-fade-lod` (bool, default true) — turn off to make `FadeLODNode` behave like a plain `LODNode` (handy for measuring fade cost).
- `lod-fade-time` (double, 0.5) — default cross-fade duration.
- `lod-fade-bin-name` (default `fixed`), `lod-fade-bin-draw-order`, `lod-fade-state-override` (1000) — how the fading half-level is drawn/overridden.
- `verify-lods` (bool, NDEBUG-only) — assert each LOD child's geometry fits inside its switch radius.
- `parallax-mapping-samples` (int, 3) and `parallax-mapping-scale` (double, 0.1) — feed the `ShaderGenerator`.

## cull

**What it is.** The output stage of the cull pipeline. `pgraph` produces a stream of `CullableObject`s during traversal; this directory provides (a) the concrete `CullBin` subclasses that *group and sort* those objects per draw strategy, and (b) the two `CullHandler` implementations that decide whether to draw immediately or accumulate into bins. It is deliberately split out from `pgraph` so the abstract `CullBinManager` (in `pgraph`) can register bin *constructors* by type without `pgraph` depending on the concrete sorters — the factory wiring happens in `config_cull.cxx::init_libcull()`.

**Key classes & roles.**
- `CullBin` (abstract base, declared in `panda/src/pgraph/cullBin.h`) — "a collection of Geoms and their associated state, for a particular scene" (cullBin.h:32). Pure virtuals `add_object()` and `draw()`; helper `make_result_graph()`. Concrete subclasses live here in `cull`:
  - `CullBinUnsorted` (`cullBinUnsorted.h`) — keeps objects in traversal order; cheapest.
  - `CullBinStateSorted` (`cullBinStateSorted.h`) — sorts to group identical state together (minimize GSG state changes), and front-to-back within a state to exploit hierarchical-Z early-out (cullBinStateSorted.h:26-34). This is the default for the `opaque` bin.
  - `CullBinBackToFront` (`cullBinBackToFront.h`) — sorts by distance, far-to-near; required for correct alpha blending. Default for the `transparent` bin.
  - `CullBinFrontToBack` (`cullBinFrontToBack.h`) — near-to-far.
  - `CullBinFixed` (`cullBinFixed.h`) — honors an explicit per-object draw order; used for `background` and `fixed` bins and for FadeLOD's fading half.
- `BinCullHandler` (`binCullHandler.h`) — `CullHandler` that routes each recorded `CullableObject` into the right `CullBin` of a `CullResult` (deferred, sorted draw). This is the normal path.
- `DrawCullHandler` (`drawCullHandler.h`) — `CullHandler` that draws each object the instant it's recorded, with no binning/sorting. Used when you don't want the cost/latency of bins.

**Central abstraction & inheritance.** `CullBin : TypedReferenceCount, CullBinEnums`; each concrete bin is `EXPCL_PANDA_CULL`. `BinType` (`BT_unsorted`, `BT_state_sorted`, `BT_back_to_front`, `BT_front_to_back`, `BT_fixed`) is defined in `cullBinEnums.h` (in `pgraph`); the `CullBinManager` maps a registered bin *name+sort* to a `BinType`, and at draw time `CullResult::make_new_bin` asks the manager to instantiate the right concrete class via the constructor registered in `init_libcull()`.

**How it plugs in.** Per frame: `GraphicsEngine` makes a `CullResult` for the `DisplayRegion`, wraps it in a `BinCullHandler`, and runs the `CullTraverser`. Each `GeomNode::add_for_draw` builds a `CullableObject` and calls `CullHandler::record_object` (geomNode.cxx). `CullResult::add_object` (cullResult.cxx:108) reads the object's `CullBinAttrib` (via `RenderState::get_bin_index()`), creates the bin lazily, and calls `bin->add_object`. Transparency handling also happens here: `CullResult` may split an object with `M_dual` transparency into an opaque part (binary alpha, into the opaque bin) and a transparent part (re-binned into a back-to-front bin), and can route a wireframe overlay into the `fixed` bin (cullResult.cxx:149, 203-256). After traversal, `CullBin::finish_cull` sorts and `draw()` emits to the GSG.

**The default bins (defined in `cullBinManager.cxx::setup_initial_bins`, lines 276-288).** In sort order: `background` (`BT_fixed`, sort 10), `opaque` (`BT_state_sorted`, 20), `transparent` (`BT_back_to_front`, 30), `fixed` (`BT_fixed`, 40), `unsorted` (`BT_unsorted`, 50). The official manual explains the global `CullBinManager` and these five defaults: "How to Control Render Order" (https://docs.panda3d.org/1.10/python/programming/rendering-process/controlling-render-order). You change render order either by moving an object to a named bin via `CullBinAttrib` / `NodePath.setBin(name, order)`, or by reconfiguring a bin's type/sort on the global `CullBinManager` (community walkthrough: https://discourse.panda3d.org/t/15220).

**Where to start reading.** `cullResult.cxx::add_object` is the dispatch point (bin selection + transparency splitting). To understand a sort, read the tiny `cullBinStateSorted.cxx`/`cullBinBackToFront.cxx` (their `ObjectData::operator<` is the whole sort). To add a new sorting strategy: subclass `CullBin`, implement `add_object`/`finish_cull`/`draw`/`fill_result_graph`, add a `BT_*` enum value in `cullBinEnums.h`, and register its constructor in `config_cull.cxx::init_libcull()`.

> **Gotcha — back-to-front sorting + nested transparency.** Sibling/parent-child transparent objects in a single back-to-front bin sort only by centroid distance, so a parent decal and its transparent child can z-fight or sort wrong; one proposed fix is an extra sort key on back-to-front bins (GitHub issue #938, DecalEffect discrepancy: https://github.com/panda3d/panda3d/issues/938). Also note: if you put everything in front-to-back/state-sorted bins with no transparency, the binning overhead can dominate for tiny scenes (https://discourse.panda3d.org/t/26309).

**Relevant config.** `config_cull.cxx` registers no `ConfigVariable`s of its own (it only wires up the bin-type factory and the `cull` notify category). The bins themselves are configured at runtime through `CullBinManager`, or seeded at startup via `cull-bin <name> <sort> <type>` lines parsed by `setup_initial_bins` (cullBinManager.cxx:230-267). Transparency-related behavior is governed by the `m-dual*` variables in `config_pgraph.cxx` (above).

## Known shortcomings & footguns

The constructive picture above is only half the story. The same design choices that make the scene graph fast and composable — immutable interned state, cached bounding volumes, copy-on-write nodes, cull-bin sorting — also produce a recognizable set of traps that the community has hit for years. The entries below are community-sourced opinion/history (with maintainer quotes preserved verbatim); they describe *how the subsystem breaks*, complementing the "how it works" material above.

### `setColor` replaces vertex colors; `setColorScale` multiplies — confusable
**Severity: minor (very common) · Status: by-design**

`setColor()` discards a model's vertex colors by applying a flat `ColorAttrib`; `setColorScale()` applies a `ColorScaleAttrib` that *multiplies* the existing colors. They are interchangeable only when the model has no vertex colors — so code works in testing against an untinted model, then breaks on a vertex-colored one. (Both are ordinary `RenderAttrib`s composed during cull, per the state/attrib discussion above.)

> "np.setColor() will completely replace the vertex colors, but
> np.setColorScale() will simply multiply the existing vertex colors." — rdb
> *(maintainer)*, [t/13629](https://discourse.panda3d.org/t/13629)

### `flattenStrong()` breaks already-played Actors and won't flatten past `ModelNode`
**Severity: major · Status: mitigated (`clearModelNodes` + ordering)**

The standard perf fix silently does nothing on a naive `model.flattenStrong()`: it won't merge past the `ModelRoot`/`ModelNode` that every loaded model sits under (see the "flatten doesn't cross ModelNodes" gotcha in [pgraph](#pgraph) above — call `clearModelNodes()` first). Worse, calling it *after* binding/playing animations breaks the Actor.

> "calling flattenStrong() will break an actor if you have already loaded up and
> played some animations." — drwr *(maintainer)*, [t/4310](https://discourse.panda3d.org/t/4310)

### Too-many-Geoms is a pervasive perf trap with only manual mitigation
**Severity: major · Status: by-design (manual flatten; no auto-batching)**

Asset pipelines routinely yield 1000+ `Geom`s, and Panda has no dynamic batching: the only remedy is the manual `clearModelNodes()` + `flattenStrong()` dance — which carries its own footguns (above) and only pays off with many nodes.

> re: Toontown/Pirates perf — "The 'automatic Geom merging method' you describe
> already exists in the form of clearModelNodes() followed by flattenStrong()."
> — rdb *(maintainer)*, [#301](https://github.com/panda3d/panda3d/issues/301)

### Culling uses stale bounds for morphed / CPU-animated / instanced geometry
**Severity: major · Status: by-design (workaround: `OmniBoundingVolume`)**

The cull traversal frustum-culls by each node's *cached* bounding volume and won't recompute it for runtime-morphed geometry (terrain, CPU vertex animation, hardware instancing, off-screen Actors). The symptom is objects that vanish or never appear. The blunt workaround is to attach an `OmniBoundingVolume` to defeat culling entirely for that node.

> "Panda does not automatically recompute the bounding volume of an Actor, because
> Actors move their vertices around a lot." — drwr *(maintainer)*,
> [t/1262](https://discourse.panda3d.org/t/1262)

### Hardware-animated models duplicate GeomVertexData per copy
**Severity: major · Status: still-open ([#421](https://github.com/panda3d/panda3d/issues/421))**

Each independently-animated copy duplicates the entire GeomVertexArrayData because
the `TransformTable` lives under the Geom's GeomVertexData and must be copied per
Character — wasteful for crowds.

### `RenderState`/`RenderAttrib` are immutable; mutator-looking methods silently no-op
**Severity: minor · Status: by-design**

Consistent with the immutable, interned state system described above, `set_attrib`/`add_attrib` return a *new* `RenderState` and leave the original untouched. The names read like in-place setters, so ignoring the return value silently does nothing.

> "state.add_attrib returns a new RenderState and leaves state untouched. So if
> you're using this, then you haven't actually been [applying it]." — rdb
> *(maintainer)*, [t/31476](https://discourse.panda3d.org/t/31476)

### Transparency is order-dependent (no OIT) and breaks when the camera moves
**Severity: major · Status: by-design**

Default `M_alpha` blending requires strict back-to-front draw order, which the `transparent` cull bin provides by sorting on centroid distance (see the [cull](#cull) bin discussion above). Panda has no order-independent transparency, so overlapping/nested transparent objects render wrong, and a "fix" tuned for one camera angle breaks on rotation.

> "Sorting will help if the camera direction does not change, if it changes, it
> will not work." — forum, [t/28748](https://discourse.panda3d.org/t/28748)

### `DecalEffect`/`DepthOffset` conflict with transparency sorting
**Severity: major · Status: still-open ([#938](https://github.com/panda3d/panda3d/issues/938))**

Decals rely on a fixed depth offset, but transparent objects are re-sorted back-to-front by distance, so a decalled transparent child can render *behind* its parent (this is the "nested transparency" gotcha noted in the [cull](#cull) section). A proper fix needs a topological sort over a partial ordering (rdb), e.g. an extra sort key on back-to-front bins.

### Z-fighting / `setDepthOffset` has no real-world unit; default depth range wastes precision
**Severity: minor · Status: by-design (#377 proposes 0..1 range, open)**

`DepthOffsetAttrib` (via `setDepthOffset`) exposes only an opaque integer with no metric meaning; its effect varies with camera distance and near/far. Panda also still defaults to GL's -1..1 depth range, wasting float precision in the middle.

### Where to start (this cluster)

If you are new and want to get oriented fast, read in this order:
1. **`panda/src/pgraph/pandaNode.h`** — the universal node, the `CData`/`PipelineCycler` copy-on-write story (line 701), and the `FancyBits` enum (line 319) that drives cull-time dispatch.
2. **`panda/src/pgraph/renderState.h` + `renderAttrib.h` + `renderAttribRegistry.h`** — the immutable, slot-indexed, interned state-composition system. Read `RenderState::compose` and `RenderAttrib::compose_impl` to internalize "child overrides parent unless override wins."
3. **`panda/src/pgraph/cullTraverser.cxx` `do_traverse()` (line 178)** + **`cullTraverserData.cxx` `apply_transform()` (line 96)** — one frame of culling end to end, including frustum/cull-plane transforms and `RenderEffect` application.
4. **`panda/src/pgraph/geomNode.cxx` `add_for_draw()`** — how a leaf turns accumulated state into a `CullableObject`.
5. **`panda/src/cull/cullResult.cxx` `add_object()`** + the five tiny `cullBin*.cxx` files — how draw order/sorting and transparency actually happen.
6. For threading/CoW work, **PR #1853 (EBR)** (https://github.com/panda3d/panda3d/pull/1853); for the slot system's history, commit `26754b86` (`dev_slots_2008`). All four config files (`config_pgraph.cxx`, `config_pgraphnodes.cxx`, `config_cull.cxx`) double as an index of every tunable and every registered type in the cluster.
