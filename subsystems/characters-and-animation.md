# Characters & animation

This cluster implements Panda3D's skeletal-animation runtime: how a character's joint/slider skeleton is represented, how keyframe animation data is bound to and blended onto that skeleton each frame, and how parametric curves (NURBS/Hermite) drive motion paths and procedurally-generated rope/sheet geometry. The core idea is a pair of parallel hierarchies — a **PartBundle** of `MovingPart`s (the skeleton, in `chan`) and an **AnimBundle** of `AnimChannel`s (the keyframe data, also in `chan`) — that are matched up by name and "wired together" at *bind* time, after which a per-frame `do_update()` pull pumps channel values into joint transforms. `char` specializes that machinery into a real renderable `Character` node with vertex skinning and morph sliders; `parametrics` is a mostly-independent module for curves, used both for motion paths and (via `RopeNode`/`SheetNode`) for renderable curve/surface geometry. Note: there is **no `panda/src/anim` directory** in this source tree — the animation channel system lives entirely in `panda/src/chan`. The egg loader (`panda/src/egg2pg`, `CharacterMaker`/`AnimBundleMaker`) is the producer that builds these structures from `.egg` files.

## char

**What it is.** `panda/src/char` is the renderable character layer: it turns the abstract `chan` PartBundle/MovingPart machinery into an actual scene-graph node (`Character`) whose joints drive soft- or hard-skinned vertices and morph targets. A `Character` owns a `CharacterJointBundle` (the skeleton root) whose joints are `CharacterJoint`s; geometry is bound to those joints through `JointVertexTransform` entries in a `GeomVertexData`'s transform table, and morph targets through `CharacterVertexSlider`. Each frame, before the character is culled, the joints recompute their net/skinning matrices and the GPU/CPU skinning machinery reads them.

**Key classes and roles.**
- `Character` (`character.h`/`.cxx`) — extends `PartBundleNode` (so it is a `PandaNode`). The user-facing animated actor node. Holds `find_joint()`/`find_slider()`, LOD-animation throttling (`set_lod_animation()`), and the per-frame `do_update()` that calls `PartBundle::update()` on each bundle. `cull_callback()` (character.cxx ~line 165) calls `update()` so joint transforms are current before rendering (the related `update_to_now()` is invoked from `calc_tight_bounds()`).
- `CharacterJoint` (`characterJoint.h`/`.cxx`) — extends `MovingPartMatrix` (so it is a `MovingPartBase`/`PartGroup`). One skeletal joint. Beyond the inherited animating `LMatrix4 _value`, it caches `_net_transform`, `_initial_net_transform_inverse`, and the product `_skinning_matrix` that maps a neutral-pose vertex to its animated position. `update_internals()` (declared `final`) recomputes these from the parent joint's net transform. `add_net_transform()`/`add_local_transform()` expose the joint to the scene graph (this is what `Actor.exposeJoint()`/`controlJoint()` use under the hood); they attach a `CharacterJointEffect` to the exposed node.
- `CharacterJointBundle` (`characterJointBundle.h`/`.cxx`) — extends `PartBundle`. The skeleton root; mainly overrides `add_node`/`remove_node` and propagates the owning `Character*` pointer down the joint tree via `r_set_character()`.
- `CharacterSlider` (`characterSlider.h`/`.cxx`) — extends `MovingPartScalar`. A morph slider; a scalar "joint" whose value drives morph blending.
- `JointVertexTransform` (`jointVertexTransform.h`/`.cxx`) — extends `VertexTransform` (from `panda/src/gobj`). The bridge from a `CharacterJoint` into the GPU/CPU vertex pipeline: `mult_matrix()`/`accumulate_matrix()` return the joint's `_skinning_matrix`. Multiple weighted ones per vertex = soft skinning.
- `CharacterVertexSlider` (`characterVertexSlider.h`/`.cxx`) — extends `VertexSlider`. Returns a `CharacterSlider`'s value into the morph (`SliderTable`) pipeline.
- `CharacterJointEffect` (`characterJointEffect.h`/`.cxx`) — extends `RenderEffect`. Auto-added to any node exposed/controlled by a joint; its `adjust_transform()`/`cull_callback()` force the owning `Character` to update first whenever you query the relative transform of the exposed node. Holds the character as a `WPT` (weak pointer) to avoid a reference cycle.

**Central abstraction & inheritance.** `Character : PartBundleNode : PandaNode`. The joint itself: `CharacterJoint : MovingPartMatrix : MovingPart<ACMatrixSwitchType> : MovingPartBase : PartGroup`. So a character's skeleton *is* a `PartGroup` tree rooted at a `CharacterJointBundle` (a `PartBundle`), exactly the structure `chan` knows how to animate.

**How it plugs in.** Geometry is parented to the scene graph at the level of the character node, **not** under joint nodes (see the `JointVertexTransform` header comment). Animation flows: joints pull values from `chan` channels → `CharacterJoint::update_internals()` builds `_skinning_matrix` → `JointVertexTransform` exposes it → `gobj`'s `TransformBlendTable`/`GeomVertexData` apply skinning (HW or SW). `Character` is produced by `panda/src/egg2pg/characterMaker.cxx` (`CharacterMaker::make_node()`, `build_joint_hierarchy()`, `egg_to_part()`), which also stashes a temporary `_geom_node` pointer on each joint during construction.

**Where to start (bug/feature work).** For skinning/joint-math issues start in `characterJoint.cxx` (`update_internals`, `do_xform`). For "why does my exposed node lag the character" start in `characterJointEffect.cxx`. For per-frame update/LOD throttling start in `character.cxx` (`do_update`, `update_to_now`, `set_lod_animation`). For load-time skeleton construction read `egg2pg/characterMaker.cxx`.

**Gotchas / rationale (community).**
- `controlJoint()` writes a joint; `exposeJoint()` reads it — they are different operations and easy to confuse ([forum t/11953](https://discourse.panda3d.org/t/11953), drwr: "You want exposeJoint(), not controlJoint()"). A controlled joint's transform is specified in the joint's **local** space, not world space, which trips people up for look-at code ([forum t/7346](https://discourse.panda3d.org/t/7346)).
- Dynamic joints (set via `controlJoint`, backed by `AnimChannelMatrixDynamic`) lagged a frame when blends were active; fixed in commit `737096d8` ("fix laggy dynamic joints when blends are in effect", touching `chan/animChannelMatrixDynamic.*`) — useful precedent if you touch dynamic-joint timing.
- The skeleton hierarchy must be fully connected for `BT_normalized_linear` blending or body parts "fly off" (see `chan` below).

**Config variables (`config_char.cxx`).** `even-animation` (bool, default false): recompute every character's vertices every frame regardless of need, to even out frame rate (otherwise vertices are computed lazily). It directly selects `force_update()` vs `update()` in `Character::do_update()`.

## chan

**What it is.** `panda/src/chan` is the engine-agnostic animation-channel library (its `README.md`: "a support library for char, as well as any other libraries that want to define objects whose values change over time"). It defines two mirror hierarchies: the **part** side — a `PartBundle` of `MovingPart`s, the *animatable* object — and the **anim** side — an `AnimBundle` of `AnimChannel`s, the *keyframe data*. Binding walks both trees in tandem and connects each part to the matching channel; an `AnimControl` then manages playback timing, and a per-frame `do_update()` pulls (optionally blended) channel values into the parts.

**Key classes and roles.**
- `PartGroup` (`partGroup.h`/`.cxx`) — base of the part hierarchy, `: TypedWritableReferenceCount, Namable`. Implements `check_hierarchy()` (verifies a part tree matches an anim tree, tolerating differences per `HierarchyMatchFlags`), `bind_hierarchy()` (the actual wiring), and the recursive `do_update()`. The `HierarchyMatchFlags` enum (`HMF_ok_part_extra`, `HMF_ok_anim_extra`, `HMF_ok_wrong_root_name`) lives here.
- `PartBundle` (`partBundle.h`/`.cxx`) — root of the part tree, `: PartGroup`. The control surface for animation: `bind_anim()`/`load_bind_anim()` (sync/async binding → `do_bind_anim()` at partBundle.cxx ~577), blending (`set_blend_type()`, `set_anim_blend_flag()`, `set_control_effect()`, `set_frame_blend_flag()`), and `freeze_joint()`/`control_joint()`/`release_joint()`. The `BlendType` enum (BT_linear, BT_normalized_linear, BT_componentwise, BT_componentwise_quat) is defined here with detailed comments. Thread-safe per-pipeline-stage state lives in a nested `CData : CycleData` (blend map, blend type, root xform, frame-blend flag) cycled via `PipelineCycler`.
- `PartBundleNode` (`partBundleNode.h`/`.cxx`) — `: PandaNode`. Scene-graph attachment point that owns one or more `PartBundle`s through `PartBundleHandle`. `Character` derives from this.
- `MovingPartBase` (`movingPartBase.h`/`.cxx`) — `: PartGroup`, abstract. One animatable piece (a joint or slider). Holds `_channels` (one `AnimChannelBase` per bound `AnimControl`/channel index), the resolved `_effective_channel`/`_effective_control`, and any `_forced_channel`. Its `do_update()` (movingPartBase.cxx ~108) decides whether anything changed, calls `get_blend_value()` if so, then `update_internals()`.
- `MovingPart<SwitchType>` (`movingPart.h`/`.I`) — templated subclass adding the typed `_value`/`_default_value` and `make_default_channel()`. Instantiated as `MovingPartMatrix` (`movingPartMatrix.h`/`.cxx`, value = `LMatrix4`) and `MovingPartScalar` (`movingPartScalar.h`/`.cxx`, value = `PN_stdfloat`). **`MovingPartMatrix::get_blend_value()` is where matrix blending actually happens** — it has the four `case PartBundle::BT_*` branches (movingPartMatrix.cxx lines ~81/125/201/277).
- `AnimGroup` (`animGroup.h`/`.cxx`) — base of the anim hierarchy, mirror of `PartGroup`. Root must be an `AnimBundle`.
- `AnimBundle` (`animBundle.h`/`.cxx`) — `: AnimGroup`. Root of an animation's channel tree; carries frame rate and frame count. Wrapped in scene graph by `AnimBundleNode`.
- `AnimChannelBase` (`animChannelBase.h`) → `AnimChannel<SwitchType>` (`animChannel.h`, template) — abstract channel returning a value per frame. `ACMatrixSwitchType`/`ACScalarSwitchType` give `AnimChannelMatrix`/`AnimChannelScalar`. Concrete leaves:
  - `AnimChannelMatrixXfmTable` (`animChannelMatrixXfmTable.h`/`.cxx`) — the workhorse: per-component (i,j,k, a,b,c, h,p,r, x,y,z) keyframe tables, the format the egg loader produces, with optional FFT compression.
  - `AnimChannelScalarTable` (`.h`/`.cxx`) — scalar keyframe table (morph sliders).
  - `AnimChannelMatrixDynamic`/`AnimChannelScalarDynamic` — value driven live from a node/value (used by `control_joint`).
  - `AnimChannelMatrixFixed`/`AnimChannelFixed` — constant value (used by `freeze_joint`).
- `AnimControl` (`animControl.h`/`.cxx`) — `: TypedReferenceCount, AnimInterface, Namable`. One per (bundle, anim) binding. Holds the `_channel_index` into each part's `_channels`, the `_bound_joints` BitArray (a `PartSubset` may bind only some joints), play/stop/loop state (via `AnimInterface`), and `channel_has_changed()` used by `do_update()` to skip work. Supports async binds via `_pending`/`wait_pending()`.
- `AnimControlCollection` (`animControlCollection.h`/`.cxx`) — named dictionary of `AnimControl`s; what `auto_bind()` fills and what `Actor` wraps.
- `auto_bind()` (`auto_bind.h`/`.cxx`) — free function: walks a subgraph, collects all `AnimBundleNode`s and `PartBundleNode`s, groups by name, and binds matching pairs (`r_find_bundles()` + `bind_anims()`). This is `WindowFramework::loop_animations()`'s engine.
- `BindAnimRequest` (`bindAnimRequest.h`/`.cxx`) — `: ModelLoadRequest` (itself an `AsyncTask`), for asynchronous `load_bind_anim()`.
- `AnimPreloadTable` (`animPreloadTable.h`/`.cxx`) — metadata (name, frame rate, num frames) letting `Actor` defer actually loading anim files until bound.

**Central abstraction & inheritance.** Part side: `MovingPartMatrix : MovingPart<ACMatrixSwitchType> : MovingPartBase : PartGroup`, rooted at `PartBundle : PartGroup`. Anim side: `AnimChannelMatrixXfmTable : AnimChannel<ACMatrixSwitchType> : AnimChannelBase : AnimGroup`, rooted at `AnimBundle : AnimGroup`. **Binding** in `PartBundle::do_bind_anim()`: it `check_hierarchy()`-validates the two trees, picks a free channel index, then `bind_hierarchy()` walks both trees pushing a channel into each part's `_channels[channel_index]` (a part can hold many channels for blending). **Updating** in `do_update()`: `MovingPartBase::do_update()` consults the `PartBundle::CData::_blend` map (AnimControl → weight), asks each control whether its channel changed, calls `get_blend_value()` to combine them, then `update_internals()`.

**How it plugs in.** Produced by `egg2pg/animBundleMaker.cxx` (`AnimBundleMaker::make_bundle()`, `create_xfm_channel()` builds `AnimChannelMatrixXfmTable`s) for anims and `characterMaker.cxx` for parts. Consumed by `char` (`CharacterJoint`/`CharacterSlider` are `MovingPart`s). `direct/src/actor/Actor.py` is the high-level Python wrapper that orchestrates `bind_anim`, `AnimControlCollection`, and joint control. The whole subsystem is BAM-serializable (every class registers with the read factory in `config_chan.cxx`).

**Where to start (bug/feature work).**
- Binding / "my animation won't bind" → `partBundle.cxx::do_bind_anim` and `partGroup.cxx::check_hierarchy`/`bind_hierarchy`. Turn on `notify-level-chan debug` to see the per-joint bind log emitted by `bind_hierarchy()`.
- Blending math / artifacts → `movingPartMatrix.cxx::get_blend_value` (the four BlendType cases).
- Playback timing / looping / async → `animControl.cxx` + `bindAnimRequest.cxx`.
- Auto-binding multiple anims → `auto_bind.cxx`.
- New channel type → subclass `AnimChannel<SwitchType>`, mirror the `XfmTable` pattern, register in `config_chan.cxx`.

**Gotchas / rationale (community).**
- `BT_normalized_linear` blends rotation/translation linearly but applies scale/shear separately to avoid limb squashing; **"if the hierarchy is disconnected, body parts can fly off… it's essential the skeleton hierarchy be completely connected"** (verbatim from the `BlendType` enum comment in `partBundle.h`; echoed at [forum t/1021](https://discourse.panda3d.org/t/1021)).
- When two anims are supposed to influence the same joint but only one does after a re-export, the usual cause is a joint that exists in one anim's hierarchy but not the part hierarchy — a `check_hierarchy` mismatch ([forum t/26324](https://discourse.panda3d.org/t/26324)).
- drwr's own one-paragraph description of binding is a good orientation: "Panda basically walks through an AnimBundle hierarchy and the corresponding PartBundle hierarchy, and basically connects each [matching node]" ([forum t/14466](https://discourse.panda3d.org/t/14466)). Anything in `panda3d.*` is C++ (this library); anything in `direct.*` (e.g. `Actor`) is the Python layer on top.
- The `"morph"` child is special-cased in `check_hierarchy()` so a model/anim mismatch on just the morph node is silently tolerated.

**Config variables (`config_chan.cxx`).**
- `compress-channels` (bool, false) + `compress-chan-quality` (int, 95): lossy FFT compression of channels when writing BAM (shrinks file only, not runtime memory); values >100 are debug-only lossless modes documented in the source comment.
- `read-compressed-channels` (bool, true): allow loading compressed channels.
- `interpolate-frames` (bool, false): interpolate between keyframes vs. holding each frame; also per-character via `PartBundle::set_frame_blend_flag()`.
- `restore-initial-pose` (bool, true): zeroing all control effects returns the actor to its default pose rather than freezing the last computed pose.
- `async-bind-priority` (int, 100): task priority for asynchronous `load_bind_anim()`.

## parametrics

**What it is.** `panda/src/parametrics` is a self-contained math/geometry module for parametric curves and surfaces: cubic/Hermite/NURBS curves usable as motion paths (the `ParametricCurve` family), plus a separate, newer NURBS evaluator used to render curves and surfaces as geometry (`NurbsCurveEvaluator` → `RopeNode`, `NurbsSurfaceEvaluator` → `SheetNode`). Important design fact stated in the headers: **the evaluator/Rope/Sheet path is a deliberately parallel reimplementation, not built on `ParametricCurve`** — `ropeNode.h` and `nurbsCurveEvaluator.h` both say it "is not related to NurbsCurve… and will probably eventually replace the whole ParametricCurve class hierarchy."

**Key classes and roles.**
- `ParametricCurve` (`parametricCurve.h`/`.cxx`) — abstract base, `: PandaNode`. Defines the curve interface: `get_point()`, `get_tangent()`, `get_pt()`, `get_2ndtangent()`, arc-length helpers `calc_length()`/`find_length()`, curve-type hints (`PCT_XYZ`/`PCT_HPR`/`PCT_T` for motion-path role), and egg I/O. Used directly as a motion path (read by `t` over `[0, get_max_t()]`).
- `PiecewiseCurve` (`piecewiseCurve.h`/`.cxx`) — `: ParametricCurve`. A curve stitched from multiple segments; base for the concrete curve types.
- `CubicCurveseg` (`cubicCurveseg.h`/`.cxx`) — `: ParametricCurve`. A single cubic (Bezier/Hermite/B-spline-expressible) segment; the atomic piece used by `PiecewiseCurve`.
- `HermiteCurve` (`hermiteCurve.h`/`.cxx`) — `: PiecewiseCurve`. Editable Hermite curve with control vertices (`HermiteCurveCV`); the classic hand-edited motion path.
- `NurbsCurve` (`nurbsCurve.h`/`.cxx`) — `: PiecewiseCurve, NurbsCurveInterface` (multiple inheritance, declared `final`). The old-style NURBS motion-path curve.
- `NurbsCurveInterface` (`nurbsCurveInterface.h`/`.cxx`) — mixin abstracting NURBS knot/CV access so `NurbsCurve` and converters share code.
- `NurbsCurveEvaluator` (`nurbsCurveEvaluator.h`/`.cxx`/`.I`) — `: ReferenceCount`. The **new** NURBS engine: an array of `NurbsVertex`es (each may live in its own `NodePath` coordinate space) + a knot vector; `evaluate()` produces a `NurbsCurveResult`. Backed by `NurbsBasisVector` (`nurbsBasisVector.*`).
- `NurbsCurveResult` (`nurbsCurveResult.h`/`.cxx`/`.I`) — cached evaluation of a `NurbsCurveEvaluator` at the current control-point positions; what you actually sample for points/tangents each frame.
- `NurbsSurfaceEvaluator` / `NurbsSurfaceResult` (`nurbsSurfaceEvaluator.*`, `nurbsSurfaceResult.*`) — the 2-parameter analogues, for `SheetNode`.
- `NurbsVertex` (`nurbsVertex.h`/`.cxx`/`.I`) — one control point: position, weight, optional rel-space `NodePath`, and extended dimensions.
- `ParametricCurveCollection` (`parametricCurveCollection.h`/`.cxx`/`.I`) — `: ReferenceCount`. Groups several `ParametricCurve`s (e.g. an XYZ curve + an HPR curve + a timewarp curve) into one motion path; provides combined `evaluate()` and arc-length re-parameterization. This is what Python's `Mopath`/`MopathInterval` wraps.
- `RopeNode` (`ropeNode.h`/`.cxx`/`.I`) — `: PandaNode`. Renders a `NurbsCurveEvaluator` curve as geometry every frame (`cull_callback()` regenerates the `Geom`). `RenderMode` (thread/tape/billboard/tube), `UVMode`, `NormalMode`, subdivision, thickness, and tube-up control the generated strip. Thread-safe state in a nested `CData : CycleData`.
- `SheetNode` (`sheetNode.h`/`.cxx`/`.I`) — `: PandaNode`. The surface analogue: renders a `NurbsSurfaceEvaluator` as a tessellated sheet, also with a `CData : CycleData`.
- `CurveFitter` (`curveFitter.h`/`.cxx`/`.I`) — fits a curve through sampled data points; used by tools and to bake motion paths.

**Central abstraction & inheritance.** Two parallel stacks. Motion-path stack: `NurbsCurve / HermiteCurve : PiecewiseCurve : ParametricCurve : PandaNode`. Render/eval stack: `NurbsCurveEvaluator : ReferenceCount` → `NurbsCurveResult`, surfaced by `RopeNode : PandaNode` (and the surface equivalents). `ParametricCurveCollection` ties motion-path curves together.

**How it plugs in.** Curves enter the scene graph as `PandaNode`s (`ParametricCurve`, `RopeNode`, `SheetNode`) and are produced by the egg loader from `<NurbsCurve>`/`<BezierCurve>` egg entries (see `egg2pg/eggLoader.cxx`; note the `egg-load-old-curves` config var that selects `NurbsCurve` vs the evaluator path). The motion-path side is consumed almost entirely from Python: `direct.directutil.Mopath` and `direct.interval.MopathInterval` evaluate a `ParametricCurveCollection`/`NurbsCurveEvaluator` to drive a NodePath along a path. `RopeNode`/`SheetNode` integrate with the render pipeline by regenerating geometry in their `cull_callback()`, so control points (which may be other `NodePath`s) animate the rope/sheet live.

**Where to start (bug/feature work).** For motion-path evaluation/arc-length problems start in `parametricCurve.cxx` (`calc_length`/`find_length`/`r_calc_length`) and `parametricCurveCollection.cxx`. For "my rope looks wrong / has bad UVs/normals" start in `ropeNode.cxx::cull_callback` (geometry generation) and `nurbsCurveResult.cxx` (sampling). For NURBS evaluation math start in `nurbsCurveEvaluator.cxx` + `nurbsBasisVector.cxx`. New curve type → subclass `ParametricCurve` (or feed a `NurbsCurveEvaluator`); register in `config_parametrics.cxx`.

**Gotchas / rationale (community).**
- There are genuinely *two* NURBS implementations; the `Evaluator`/`Rope` one is the intended successor and is what most modern motion-path code uses. A community NURBS-mopath helper sets `egg-load-old-curves 0` to force the new path and uses `NurbsCurveEvaluator` directly with `evalTangent` for orientation along the path ([forum t/24287](https://discourse.panda3d.org/t/24287)).
- For simple paths people often skip this module entirely and use interval `LerpFunc`/`Sequence` instead; the parametric module is for genuine spline paths and procedural rope/tube geometry ([forum t/24287](https://discourse.panda3d.org/t/24287), [forum t/29500](https://discourse.panda3d.org/t/29500) gives working 1.10 curve sample code).

**Config variables.** `config_parametrics.cxx` only defines the `parametrics` notify category and the type/factory registrations — no tunable `ConfigVariable`s live here. (The related `egg-load-old-curves` toggle that decides which NURBS path the egg loader uses lives in `egg2pg`, not here.)

## Known shortcomings & footguns

The constructive description above covers how the skeleton/channel machinery works; the
community has also documented a set of recurring footguns specific to character setup and
skeletal animation. These are mined from the forums/issue tracker and preserved here as
community-sourced opinion and history. (Format-level complaints — `.bam`/`.egg`/glTF
versioning and exporters — live on the egg/asset-pipeline pages; only the
animation/character entries are reproduced below.)

### `controlJoint()` is setup-time-only, irreversible, and local-space
**Severity: major · Status: by-design**

Procedural joint control has sharp, easy-to-miss rules: (1) it must be called *before* any
animation plays; (2) it is irreversible ("forever" — the workaround is to keep two `Actor`
copies); and (3) the transform you supply is the joint's *local* transform relative to its
parent, and `controlJoint`/`exposeJoint` are not inverses and don't share a coordinate
space. (This is the same `controlJoint`/local-space subtlety noted in the `char` Gotchas
above and implemented by `CharacterJoint::add_local_transform()` / `add_net_transform()`.)

> "(1) You have to call controlJoint() at setup time, before you play any
> animations... (3) the transform... needs to be the joint's local transform from
> its parent." — drwr *(maintainer)*, [t/226](https://discourse.panda3d.org/t/226)

> "Sorry, controlJoint() is forever." — drwr *(maintainer)*, [t/1224](https://discourse.panda3d.org/t/1224)

### `controlJoint` vs `exposeJoint`: write-only vs read-only, different spaces
**Severity: minor (very common) · Status: by-design**

`controlJoint()` writes a transform *into* the animation; `exposeJoint()` reads the
animated joint *out*. Users call the wrong one constantly, and even the right one returns
mismatched numbers because one works in local space and the other in net/world space (see
the `char` Gotchas above, where `exposeJoint` is implemented via `add_net_transform()` and
`CharacterJointEffect`).

### egg loader silently ignores collision geometry on *animated* models

The egg loader's handling of collision geometry on animated models is covered in [the egg page's footguns](egg.md#known-shortcomings-footguns).

### Where to start (this cluster)

A new contributor should read in this order:
1. `panda/src/chan/README.md` — the one-paragraph charter for the whole animation system.
2. `panda/src/chan/partBundle.h` — read the `BlendType` enum comments and the `bind_anim`/`set_control_effect` signatures; this is the public control surface.
3. `panda/src/chan/partGroup.cxx` — `check_hierarchy()` and `bind_hierarchy()`: how part and anim trees are matched and wired. Then `movingPartBase.cxx::do_update()` for the per-frame pull, and `movingPartMatrix.cxx::get_blend_value()` for the actual blend math (the four `BT_*` cases).
4. `panda/src/char/character.cxx` (`do_update`, `cull_callback`) and `characterJoint.cxx` (`update_internals`) — how the abstract machinery becomes a skinned, renderable actor; then `jointVertexTransform.cxx` for the hand-off into `gobj` vertex skinning.
5. `panda/src/egg2pg/characterMaker.cxx` and `animBundleMaker.cxx` — the producers, to see how a real `.egg` becomes a PartBundle + AnimBundle.
6. For curves, `panda/src/parametrics/parametricCurve.h` (motion-path interface) and `ropeNode.cxx::cull_callback` (renderable NURBS), keeping in mind the evaluator path is the modern one.

Two debugging levers worth knowing immediately: set `notify-level-chan debug` to get the per-joint bind trace from `bind_hierarchy()`/`auto_bind()`, and remember that the Python `Actor` (`direct/src/actor/Actor.py`) is the layer most users touch — many "engine" bugs are actually in that wrapper, not in `chan`/`char`.
