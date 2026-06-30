# Egg library & loader

Egg is Panda3D's native ASCII interchange format for geometry, materials, textures, and animation. This cluster has two halves that deliberately do not know about each other: `panda/src/egg` is a self-contained in-memory model of an egg file (a parse tree of `EggNode`s that has **no dependency on the scene graph** — you can read, edit, mesh, and re-write egg data without ever touching a `PandaNode`), and `panda/src/egg2pg` is the *only* bridge that converts that tree into a renderable `PandaNode` graph (geometry, `Character`, `AnimBundle`, collision solids, render state). Both rely on `panda/src/pnmimage` (the `PNMImage` image-IO abstraction) and its plugin pack `panda/src/pnmimagetypes` for reading/writing texture images. The key architectural idea to internalize: **"egg lives in its own world"** — the egg library is a tools-grade data structure (used by `pview`, `egg-trans`, `egg-optchar`, Maya/Max exporters), and `EggLoader` is a thin, one-directional materialization layer on top of it.

## egg

**What it is.** The authoritative in-memory representation of an egg file: a reference-counted tree of nodes plus a hand-written flex/bison parser. An `EggData` corresponds 1:1 to a file on disk; its children are the toplevel egg entries. Everything here is double-precision (`LMatrix4d`, `LPoint3d`, `CoordinateSystem`) and tools-oriented — it knows nothing about `Geom`, `RenderState`, or `PandaNode`. You use it directly when you want to inspect or transform geometry offline (recompute normals, compute tangents/binormals for normal mapping, triangulate, strip-mesh, collapse equivalent textures) before handing it to the loader, or instead of the loader entirely.

**Central abstraction & inheritance chain.** The root is `EggObject : TypedReferenceCount` (`panda/src/egg/eggObject.h`), which holds optional `EggUserData`. Everything is reference-counted (`PT(EggNode)`), so the tree is shared-ownership and safe to splice between containers. The two main branches:

- **The hierarchy branch:** `EggObject` → `EggNamedObject` (`panda/src/egg/eggNamedObject.h`) → `EggNode` (`panda/src/egg/eggNode.h`) → `EggGroupNode` (`panda/src/egg/eggGroupNode.h`). `EggNode` is "anything that can be a child in the egg tree" (groups, joints, polygons, vertex pools — but *not* vertices) and is abstract (`virtual void write(ostream&, int) const = 0`). It also caches the per-node coordinate frames (`_vertex_frame`, `_node_frame`, and their inverses) and the `_under_flags` bits (`UF_under_instance`/`UF_under_transform`/`UF_local_coord`) that record whether the node sits beneath an `<Instance>`/`<Transform>` — these are recomputed automatically by `update_under()` as the tree is mutated. `EggGroupNode` is a non-leaf container that **is an STL container of `PT(EggNode)`** (implemented as a `plist`, not a vector, to keep iterators stable across insert/erase — see the comment at `eggGroupNode.h:52`). `EggData : EggGroupNode` is the file root (`panda/src/egg/eggData.h`); its children are the toplevel egg entries, and it carries the file's `CoordinateSystem`, filename, and timestamp.
- **The leaf/attribute branches** inherit from `EggNode` plus mixins:
  - `EggGroup : EggGroupNode, EggRenderMode, EggTransform` (`panda/src/egg/eggGroup.h`) models `<Group>`, `<Instance>`, and `<Joint>`. Its big `_flags`/`_flags2` bitfields encode group type (`GT_group`/`GT_instance`/`GT_joint`), billboard type (`BT_*`), collision solid type (`CST_plane`/`CST_polygon`/`CST_sphere`/`CST_box`/`CST_tube`/...), collide flags (`CF_descend`/`CF_keep`/`CF_intangible`/...), DCS type (`DC_*`), and `<Dart>` character-root type (`DT_structured`/`DT_sync`/...). A single `EggGroup` therefore carries an enormous amount of loader-relevant metadata.
  - `EggPrimitive : EggNode, EggAttributes, EggRenderMode` (`panda/src/egg/eggPrimitive.h`) is the abstract base for drawable geometry and is itself a vector of `PT(EggVertex)`. It declares `virtual EggPrimitive *make_copy() const = 0`, a `Shading` enum (`S_overall`/`S_per_face`/`S_per_vertex`) that drives attribute unification, and per-primitive `EggTexture`/`EggMaterial`/`bface` references. Concrete subclasses: `EggPolygon`, `EggTriangleStrip`/`EggTriangleFan`/`EggCompositePrimitive`, `EggPoint`, `EggLine`, `EggPatch`, `EggNurbsCurve`/`EggNurbsSurface`.
  - `EggVertex : EggObject, EggAttributes` (`panda/src/egg/eggVertex.h`) is a 1–4 component position with optional normal/color and multiple named UV sets (`EggVertexUV`) and aux columns (`EggVertexAux`). Vertices are owned by an `EggVertexPool`; primitives reference pool vertices, and a vertex tracks back-references to the `EggGroup`s (joints, via a membership-weighted `GroupRef`) and `EggPrimitive`s that use it (`PrimitiveRef`). That joint→vertex membership map is exactly what `CharacterMaker` consumes for skinning.

**Key supporting classes & roles.**
- `EggVertexPool` (`panda/src/egg/eggVertexPool.h`) — the shared store of vertices; a primitive's vertices must all belong to one pool. This indirection is what lets the loader deduplicate and build `GeomVertexData`.
- `EggTexture` (`panda/src/egg/eggTexture.h`) and `EggMaterial` (`panda/src/egg/eggMaterial.h`) — declarative texture/material records (filename, wrap/filter/env modes, combine modes, format). They are pooled via `EggTextureCollection`/`EggMaterialCollection`; `EggData::collapse_equivalent_textures()`/`collapse_equivalent_materials()` merge duplicates.
- `EggAttributes` (`panda/src/egg/eggAttributes.h`) — mixin carrying per-vertex/per-primitive normal, color, and UVs (morphs via `EggMorphList`).
- `EggRenderMode` (`panda/src/egg/eggRenderMode.h`) — mixin for alpha mode, depth-write/test, visibility, depth-offset, draw-order, bin. The `EggNode::determine_*()` virtuals (e.g. `determine_alpha_mode`) walk *up* the tree to resolve an inherited render mode.
- `EggTransform` (`panda/src/egg/eggTransform.h`) — mixin for `<Transform>` matrices.
- Animation: `EggTable` (`panda/src/egg/eggTable.h`) models `<Table>`/`<Bundle>`; `EggAnimData`/`EggSAnimData`/`EggXfmAnimData`/`EggXfmSAnim` (`panda/src/egg/eggAnimData.h`, `eggXfmAnimData.h`) hold the sampled animation values.
- Meshing/optimization: `EggMesher` (`panda/src/egg/eggMesher.h`) plus `EggMesherEdge`/`EggMesherStrip`/`EggMesherFanMaker` implement triangle-strip/fan generation; `EggBinMaker` (`panda/src/egg/eggBinMaker.h`) is the generic binning framework the loader subclasses.
- Parser: `panda/src/egg/lexer.lxx` (flex) and `panda/src/egg/parser.yxx` (bison) generate the tokenizer/grammar; prebuilt outputs (`parser.cxx.prebuilt`, `lexer.cxx.prebuilt`) ship in-tree so a build doesn't require flex/bison. `EggData::read()` drives them; `EggNode::parse_egg()` lets you parse an egg fragment into an existing node.

**Key geometry operations** (declared on `EggGroupNode`, `panda/src/egg/eggGroupNode.h`): `recompute_vertex_normals(threshold, cs)`, `recompute_polygon_normals(cs)`, `recompute_tangent_binormal(...)` / `recompute_tangent_binormal_auto()`, `triangulate_polygons(flags)`, `mesh_triangles(flags)`, `remove_unused_vertices(recurse)`, `get_connected_shading()` / `unify_attributes(...)`. Note from the community: **the egg library is the only part of Panda that computes tangents/binormals** — "The only part of Panda that calculates tangents/binormals is built into the egg library. If you load your geometry using the EggData class, you can compute the[m]" ([discourse 11167](https://discourse.panda3d.org/t/11167), trusted). For normal-mapping a non-egg model you must route through `EggData` or `egg-trans -tbnall`.

**How it plugs into the engine.** It doesn't, directly — that's the point. The egg library links only against `panda/src/putil`, `linmath`, `mathutil`, `pipeline`, etc. (see `panda/src/egg/CMakeLists.txt`); it has **no `#include "pandaNode.h"`**. Consumers are: `egg2pg` (the loader/saver), the standalone egg tools in `pandatool/`, and Python code that walks `EggData` to extract material/texture info ("read the egg file directly via the EggData structure and its related interfaces and walk through the egg hierarchy" — [discourse 13599](https://discourse.panda3d.org/t/13599), trusted).

**Where to start reading.** To fix a parse/IO bug: `eggData.cxx` (`read`/`write_egg`/`post_read`/`pre_write`) → `parser.yxx`/`lexer.lxx`. To fix geometry math: `eggGroupNode.cxx` for the `recompute_*` and `mesh_triangles`/`triangulate_polygons` methods, then `eggMesher.cxx`. To add a new egg syntax keyword: add a token in `lexer.lxx`, a grammar rule in `parser.yxx`, and a corresponding `EggNode` subclass + `init_type()` registration in `config_egg.cxx`.

**Gotchas / rationale.**
- Egg files store vertices in **global coordinates**; a `<Transform>` on a group does not move its vertices — it is metadata that the loader bakes/flattens. This routinely confuses people: "Egg files store vertices in global coordinates; that is the definition... However, the Panda scene gra[ph]" ([discourse 8991](https://discourse.panda3d.org/t/8991), trusted).
- `EggGroupNode` uses `plist` not `pvector` specifically to avoid iterator invalidation during edits (`eggGroupNode.h:52`).
- Don't reach for the egg interface at runtime for game logic: "Once you have it loaded, you don't need the egg interface any more, unless you want to kno[w]" ([discourse 3377](https://discourse.panda3d.org/t/3377), trusted).

**Config variables** (`panda/src/egg/config_egg.cxx`): `egg-mesh` (convert to tristrips/fans), `egg-unroll-fans`, `egg-retesselate-coplanar`, `egg-consider-fans`, `egg-max-tfan-angle`, `egg-min-tfan-tris`, `egg-coplanar-threshold`, `egg-subdivide-polys` (obsolete), `egg-support-old-anims`, `egg-recursion-limit` (anti-stack-overflow hack for recursive traversals), `egg-precision` (digits when writing), `egg-test-vref-integrity` (non-production vertex-ref checking), plus the visual debug toggles `egg-show-tstrips`/`egg-show-qsheets`/`egg-show-quads`.

## egg2pg

**What it is.** The converter that turns an `EggData` tree into a Panda scene graph. It is the sole place where egg concepts are *materialized* into engine objects: `EggPrimitive`→`Geom`/`GeomVertexData`, `EggGroup`→`PandaNode`/`ModelNode`/`PandaNode`-with-collisions, `<Dart>` group→`Character` with joints, `<Bundle>` `EggTable`→`AnimBundleNode`, `EggTexture`→`Texture`+`TextureStage`+`RenderState`. It owns the high-precision-double → single-precision-float conversion, coordinate-system conversion, geometry binning, render-state synthesis, vertex-data sharing, and post-load `SceneGraphReducer` flattening. The package is "not exported" (`EggLoader` is internal); end users call the free functions `load_egg_file()` / `load_egg_data()`.

**Central abstraction.** `EggLoader` (`panda/src/egg2pg/eggLoader.h`, implementation `eggLoader.cxx`) — a plain class (not a `TypedObject`), instantiated per load, holding the `PT(EggData) _data`, the resulting `PT(PandaNode) _root`, caches (`_textures`, `_materials`, `_groups`, `_vertex_pool_data`, `_transform_states`), and an `_error` flag. Note the loader **copies** the `EggData` in its constructor (`EggLoader(const EggData*)` does `_data(new EggData(*data))`), because the conversion mutates the tree destructively (meshing, vertex removal, attribute unification). Its driver is `build_graph()` (`eggLoader.cxx:166`), and the order matters:

1. `expand_all_object_types()` — expand `<ObjectType>` macros from `egg-object-type-*` config vars; this can prune out large portions of the scene before any work is done.
2. `load_textures()` — read every `EggTexture` into a `Texture`/`TextureStage` (this is where `PNMImage` gets used, indirectly via `TexturePool`/`Texture::read`).
3. Vertex cleanup: `clear_connected_shading()` / `remove_unused_vertices()` / `get_connected_shading()` / `unify_attributes(..., egg_flat_shading, ...)` — run **twice** (`eggLoader.cxx:180-190`), because unifying attributes can make vertices identical, which connects more primitives, which changes the shading classification again.
4. `separate_switches()` (keep primitives under a `<Switch>`/sequence from being merged into one polyset) and, if `egg-emulate-bface`, `emulate_bface()`.
5. `remove_invalid_primitives()` then **binning**: `EggBinner binner(*this); binner.make_bins(_data);` — this rewrites the tree, wrapping groups of similar primitives in `EggBin` nodes.
6. Build the graph: create a `ModelRoot`, then recurse `make_node(child, _root)` over every toplevel child.
7. `reparent_decals()`, `start_sequences()`, `apply_deferred_nodes()`.

**The `make_node` dispatch.** `make_node(EggNode*, PandaNode*)` (`eggLoader.cxx:1799`) is a hand-written type switch (`is_of_type` + `DCAST`) into overloads for `EggBin`, `EggGroup`, `EggTable`, and the generic `EggGroupNode`. The `EggBin` overload (`eggLoader.cxx:1817`) reads the bin number set by the binner: `BN_polyset`/`BN_patches` → `make_polyset()` (build a `GeomNode`), `BN_lod` → `make_lod()` (build an `LODNode`), NURBS bins → the parametric makers. The `EggGroup` overload is where `<Dart>` triggers `CharacterMaker`, where collision flags trigger the `make_collision_*` family, and where billboard/transform state becomes a node arc via `create_group_arc()`.

**Key classes & roles.**
- `EggBinner : EggBinMaker` (`panda/src/egg2pg/eggBinner.h`) — pre-processes the egg tree so that "similar" primitives are grouped into one `EggBin` that will become a single `Geom`/`GeomNode`, and so related LOD children land under one `LODNode`. `get_bin_number()` returns `BN_polyset`/`BN_lod`/`BN_nurbs_surface`/`BN_nurbs_curve`/`BN_patches`; `sorts_less()` orders within a bin. This is the mechanism behind "the egg loader does a pretty good job of combining these by itself" (rationale for `egg-combine-geoms` defaulting false).
- `EggRenderState : EggUserData` (`panda/src/egg2pg/eggRenderState.h`) — computes the `CPT(RenderState)` for each primitive (texture attribs, material attribs, transparency, tex-gen, tex-matrix bake-in via `_bake_in_uvs`). Instances are attached to `EggPrimitive`s as user-data by the binner, and `compare_to()` lets primitives with identical state share a bin. This is the heart of "egg modes → engine `RenderAttrib`s" translation.
- `CharacterMaker` (`panda/src/egg2pg/characterMaker.h`) — converts a `<Dart>` `EggGroup` subtree into a `Character` node with a `CharacterJointBundle`. It maps `EggGroup` joints → `PartGroup`/`CharacterJoint`, builds the `VertexTransform`/`VertexSlider` objects that drive hardware/soft skinning, and decides each primitive's "home" (`determine_primitive_home`) for rigid-vs-animated geometry. Community note: this is loader-internal — "That's used by the egg loader for the purpose of constructing a Character object out of an egg file. You need to under[stand the Character interface instead]" ([discourse 3377](https://discourse.panda3d.org/t/3377), trusted). Don't call it yourself to build characters at runtime.
- `AnimBundleMaker` (`panda/src/egg2pg/animBundleMaker.h`) — converts a `<Bundle>` `EggTable` hierarchy into an `AnimBundle`/`AnimBundleNode`, creating `AnimChannelMatrixXfmTable` (joint transforms) and `AnimChannelScalarTable` (morph sliders) from the `EggXfmSAnim`/`EggSAnimData` tables, carrying `_fps`/`_num_frames`.
- `DeferredNodeProperty` (`panda/src/egg2pg/deferredNodeProperty.h`) — collects state that can't be applied during the first traversal (notably collide masks, `F_has_from_collide_mask`/`F_has_into_collide_mask`) and is applied in a second pass via `apply_deferred_nodes()`. `compose()` merges parent into child.
- `EggSaver` (`panda/src/egg2pg/eggSaver.h`) — the reverse direction: walks a `PandaNode` scene graph and emits an `EggData`. Backs `save_egg_file()`/`save_egg_data()`.
- `LoaderFileTypeEgg : LoaderFileType` (`panda/src/egg2pg/loaderFileTypeEgg.h`) — registers `.egg` with the engine-wide `LoaderFileTypeRegistry` (in `config_egg2pg.cxx`), so the generic `Loader`/`loader.loadModel()` path dispatches egg files here. `load_file()` ultimately calls `load_egg_file()`.
- Entry-point free functions: `load_egg_file(filename, cs, record)` and `load_egg_data(EggData*, cs)` (`panda/src/egg2pg/load_egg_file.h`). Note `load_egg_data` **destroys** the passed structure (it steals the children into the loader's own `EggData`). `egg_parametrics.cxx` handles NURBS curve/surface conversion.

**How it plugs into the engine.** This is the dependency-heavy side: `eggLoader.h` includes `pandaNode.h`, `texture.h`, `geomVertexData.h`, `geomPrimitive.h`, `textureAttrib.h`, `textureStage.h`, `texGenAttrib.h`, `colorBlendAttrib.h`, and pulls in collision (`CollisionNode`/`CollisionSolid`), portal/occluder/polylight nodes, `Character`/`AnimBundleNode`, and `ModelRoot`. After building, `load_from_loader()` (`load_egg_file.cxx:22`) optionally runs a `SceneGraphReducer` (`gr.flatten`, `gr.collect_vertex_data`, `gr.unify`) when `egg-flatten`/`egg-unify` are set. So egg2pg sits between the egg library (upstream) and essentially all of grutil/pgraph/char/collide (downstream).

**Where to start reading.** Read top-to-bottom: `load_egg_file.cxx` (the public funnel and post-load flatten/unify) → `eggLoader.cxx::build_graph()` (the pipeline) → `eggLoader.cxx::make_node(...)` overloads (`eggLoader.cxx:1799+`, dispatch on egg node type) → `eggLoader.cxx::make_polyset` / `make_vertex_data` / `make_primitive` for geometry. For render-state bugs: `eggRenderState.cxx::fill_state()`. For binning/Geom-combination: `eggBinner.cxx`. For character/animation bugs: `characterMaker.cxx` and `animBundleMaker.cxx`. For collision-solid generation: the `make_collision_*` family in `eggLoader.cxx`.

**Gotchas / rationale.**
- The two-pass shading/attribute unification (step 3 above) is subtle: changing `egg-flat-shading` changes whether per-face normals/colors duplicate vertices vs. set `ShadeModelAttrib::M_flat`, which in turn affects whether geometry can later be combined by `flatten_strong`.
- `egg-max-vertices` (default 65534) and `egg-max-indices` (65535) cap a single `GeomVertexData`/`GeomPrimitive` — historically tied to 16-bit index limits; very large egg meshes get split.
- Skinning weights are quantized (`egg-vertex-membership-quantize`, default 0.1) and capped (`egg-vertex-max-num-joints`, default 4) for runtime performance — set quantize to 0 / max-joints to -1 to preserve exact data.
- The `<Transform>`-is-not-on-the-vertices subtlety (see egg section) is *resolved here*: the loader flattens transforms / bakes them, which is why a "Transform node [looks] cancelled by [the] loader" to users ([discourse 8991](https://discourse.panda3d.org/t/8991), trusted).

**Config variables** (`panda/src/egg2pg/config_egg2pg.cxx`): geometry/scene-graph — `egg-flatten`, `egg-flatten-radius`, `egg-unify`, `egg-combine-geoms`, `egg-rigid-geometry`, `egg-flat-shading`, `egg-flat-colors`, `egg-max-vertices`, `egg-max-indices`; rendering/textures — `egg-ignore-mipmaps`, `egg-ignore-filters`, `egg-ignore-decals`, `egg-alpha-mode`, `egg-implicit-alpha-binary`, `egg-preload-simple-textures`, `egg-force-srgb-textures`; normals/coords — `egg-normal-scale`, `egg-show-normals`, `egg-coordinate-system`; characters — `egg-vertex-membership-quantize`, `egg-vertex-max-num-joints`; behavior — `egg-accept-errors`, `egg-suppress-hidden`, `egg-emulate-bface`, `egg-load-old-curves`, `egg-load-classic-nurbs-curves`; plus the `egg-object-type-*` template registered in `init_libegg2pg()`.

## pnmimage

**What it is.** Panda's format-agnostic in-memory image abstraction and the dispatcher to per-format readers/writers. `PNMImage` is a 2-D array of "xels" (the generic pixel type from the old netpbm "pnm library" that this was originally layered over — see the class comment in `pnmImage.h:30`). Crucially it is **not** the GPU `Texture` class; it's the CPU-side image used for loading/saving image files, generating mipmaps/simple-textures, filtering, painting, and color-space conversion. The egg loader uses it transitively (textures are read through `Texture`→`PNMImage`/`PfmFile`), and lots of the engine (fonts, heightfields, `PfmVizzer`, screenshots) uses it directly.

**Central abstraction & inheritance.** `PNMImageHeader` (`panda/src/pnmimage/pnmImageHeader.h`) is the base carrying dimensions, `num_channels`, `maxval`, `ColorSpace`, and `PNMFileType`. `PNMImage : PNMImageHeader` (`panda/src/pnmimage/pnmImage.h`) adds the actual pixel array plus a large API. The color model is the thing to understand: a `PNMImage` has a **maxval** (integer encoding range) and a **`ColorSpace`** (e.g. `CS_linear`, `CS_sRGB`), and the API splits into linear-float methods (`get_xel`, `set_xel`, `fill`) and raw-encoded `_val` methods (`get_xel_val`, `to_val`, `from_val`). All ordinary operations are color-space correct; `convert_srgb.cxx`/`convert_srgb_sse2.cxx` provide the (optionally SSE2-accelerated) sRGB↔linear transfer functions. The class is explicitly **not thread-safe** (`pnmImage.h:55`).

**Key supporting classes & roles.**
- `PNMFileType` (`panda/src/pnmimage/pnmFileType.h`) — abstract base (a `TypedWritable`) for "a kind of image file." Subclasses implement `get_name()`, extensions, `has_magic_number()`/`matches_magic_number()`, and factory methods `make_reader()`/`make_writer()`. Concrete subclasses live in `pnmimagetypes`.
- `PNMFileTypeRegistry` (`panda/src/pnmimage/pnmFileTypeRegistry.h`) — the global singleton (`get_global_ptr()`) mapping extensions and magic numbers to `PNMFileType`s. `get_type_from_extension()` and `get_type_from_magic_number()` are how `PNMImage::read()` figures out which plugin to use; `sort_preferences()` orders types when several claim an extension.
- `PNMReader` / `PNMWriter` (`panda/src/pnmimage/pnmReader.h`, `pnmWriter.h`) — abstract per-stream codecs created by a `PNMFileType`. A reader exposes `read_data()` / `read_row()` (with `supports_read_row()`), `is_floating_point()` + `read_pfm()` for HDR formats, and `set_read_size()` so the image can be downsampled while decoding. `PNMReaderEmscripten` is the WebGL/browser variant.
- `PfmFile` (`panda/src/pnmimage/pfmFile.h`) — a sibling of `PNMImage` for **floating-point** data (1–4 channel tables of `PN_float32`): height fields, displacement maps, lens-distortion meshes. Shares `PNMImageHeader` and the reader/writer infrastructure; has its own filtering/resize (`box_filter`, `gaussian_filter`, `quick_filter`, `resize`) and `load`/`store` to interconvert with `PNMImage`.
- Painting/filtering: `PNMBrush` (`panda/src/pnmimage/pnmBrush.h`) and `PNMPainter` (`panda/src/pnmimage/pnmPainter.h`) draw into an image; `pnm-image-filter.cxx` (+ `-core`/`-sparse-core` includes) implements resampling/box/Gaussian filters; `ppmcmap.cxx` does color-map quantization; `pnmbitio.cxx` handles sub-byte bit IO.

**How it plugs into the engine.** `PNMImage` is the CPU image used by `Texture::read`/`Texture::write` (so every texture loaded from PNG/JPG/etc. flows through here), by `gobj`/`TexturePool`, fonts (`text`), `display` screenshots, terrain/heightfield tools, and the egg loader's texture path. It depends downward only on `putil`, `linmath`, `express` (no GPU code). The plugin set in `pnmimagetypes` registers itself into this package's registry at static-init time.

**Where to start reading.** For a format-dispatch or magic-number bug: `pnmImage.cxx::read()` → `pnmFileTypeRegistry.cxx`. For pixel/color-space math: `pnmImage.I` (the inline `to_val`/`from_val`/`get_xel`) and `convert_srgb.cxx`. For a resampling artifact: `pnm-image-filter.cxx`. To add a new image format: subclass `PNMFileType` (+ `PNMReader`/`PNMWriter`) in `pnmimagetypes`, implement magic-number matching, and register it in `init_libpnmimagetypes()` (see next section). Note the open design issue that readers always go through a full `PNMImage`/`PfmFile`, causing extra copies: "Currently, PNMReader reads all textures through PNMImage or PfmFile. This often involves unnecessary copies and format conversions" ([github #1435](https://github.com/panda3d/panda3d/issues/1435), trusted).

**Gotchas / rationale.**
- `PNMImage` vs. `Texture` is a frequent confusion: compressed/mipmapped GPU formats like DDS are *not* image formats and **cannot** be loaded via `PNMImage`/`PNMImageHeader` — "DDS has to be loaded via Texture, because it is a texture format, and not an image format like PNG" ([discourse 23727](https://discourse.panda3d.org/t/23727), trusted).
- Maxval is independent of channel count; reading 16-bit PNGs gives `maxval==65535`, and mixing `_val` and float APIs without accounting for maxval/color-space is a classic source of wrong colors.

**Config variables** (`panda/src/pnmimage/config_pnmimage.cxx`): the `PfmFile`-related `pfm-force-littleendian`, `pfm-reverse-dimensions`, `pfm-resize-quick`, `pfm-resize-gaussian`, `pfm-resize-radius`.

## pnmimagetypes

**What it is.** The plugin pack of concrete `PNMFileType` implementations — one (or two: reader + writer) per on-disk image format. None of these is referenced by name from `pnmimage`; they self-register into `PNMFileTypeRegistry` at library-init time, which is what makes format support pluggable and conditional on which third-party libraries were found at build time. This directory is where you go to add, fix, or understand a specific format codec.

**Key classes & roles** (each is a `PNMFileType` subclass; readers/writers are often split into separate `.cxx`):
- `PNMFileTypePNG` (`pnmFileTypePNG.h`, gated `HAVE_PNG`, uses libpng) — lossless; honors `png-compression-level` and `png-palette`.
- `PNMFileTypeJPG` (`pnmFileTypeJPG.h`, with `pnmFileTypeJPGReader.cxx`/`...Writer.cxx`, `HAVE_JPEG`, libjpeg) — honors `jpeg-quality`.
- `PNMFileTypeTIFF` (`pnmFileTypeTIFF.h`, `HAVE_TIFF`, libtiff).
- `PNMFileTypeEXR` (`pnmFileTypeEXR.h`, `HAVE_OPENEXR`) — HDR; integrates with the floating-point `read_pfm` path.
- `PNMFileTypeBMP` (`pnmFileTypeBMP.h` + `bmp.h`, reader/writer split, `HAVE_BMP`) — honors `bmp-bpp`.
- `PNMFileTypeSGI` (`pnmFileTypeSGI.h` + `sgi.h`, reader/writer split, `HAVE_SGI_RGB`) — honors `sgi-storage-type` (RLE vs verbatim) and `sgi-imagename`.
- `PNMFileTypeTGA` (`pnmFileTypeTGA.h`, `HAVE_TGA`) — honors `tga-rle`, `tga-colormap`, `tga-grayscale`.
- `PNMFileTypePNM` (`pnmFileTypePNM.h`, `HAVE_PNM`) — the native PBM/PGM/PPM family.
- `PNMFileTypeIMG` (`pnmFileTypeIMG.h`) — raw r,g,b byte dumps; honors `img-header-type`/`img-size`.
- `PNMFileTypeSoftImage` (`pnmFileTypeSoftImage.h`, `HAVE_SOFTIMAGE_PIC`).
- `PNMFileTypePfm` (`pnmFileTypePfm.h`) — the `.pfm` floating-point reader/writer feeding `PfmFile`; **always registered** (not behind a `HAVE_*` guard).
- `PNMFileTypeStbImage` (`pnmFileTypeStbImage.h` + bundled `stb_image.h`, `HAVE_STB_IMAGE`) — the public-domain fallback decoder "used when compiling without support for more specific libraries that are more full-featured, such as libpng or libjpeg" (header comment). This is how a minimal build still reads common formats.

**Central pattern.** Every type provides a `register_with_read_factory()` (for Bam deserialization of the type token) and is instantiated + registered in `init_libpnmimagetypes()` (`panda/src/pnmimagetypes/config_pnmimagetypes.cxx`), each inside its `#ifdef HAVE_*` block, e.g. `PNMFileTypePNG::init_type(); PNMFileTypePNG::register_with_read_factory(); tr->register_type(new PNMFileTypePNG);`. The same init also calls `PandaSystem::add_system("libpng"/"libjpeg"/"libtiff"/"openexr")` so the presence of a codec is reportable at runtime. Magic-number detection (`matches_magic_number`) is what lets the registry identify a format from a stream when the extension lies.

**How it plugs in.** Strictly a producer for `pnmimage`'s registry; it depends on `pnmimage` plus the external image libraries. Consumers never name these classes — they go through `PNMImage::read`/`write` and the registry. CMake/`HAVE_*` defines decide which are compiled in, so two builds of Panda can support different format sets.

**Where to start reading.** To fix a format-specific decode bug, open the matching `pnmFileType<Format>*.cxx` (reader/writer pair) and follow `make_reader`/`read_data`/`read_row`. To add a format: copy the smallest existing pair (BMP or the stb wrapper is a good template), implement magic-number + extensions + reader/writer, then add the `#ifdef`/registration block to `config_pnmimagetypes.cxx`. To debug "why isn't my X file recognized," check the `HAVE_X` guard (was the dependency found at build time?) and `matches_magic_number()`.

**Config variables** (`panda/src/pnmimagetypes/config_pnmimagetypes.cxx`): `sgi-storage-type`, `sgi-imagename`, `tga-rle`, `tga-colormap`, `tga-grayscale`, `img-header-type`, `img-size`, `jpeg-quality`, `png-compression-level`, `png-palette`, `bmp-bpp`. Each format also gets its own notify category (`pnmimage_png`, `pnmimage_jpg`, etc.).

## Where to start (this cluster)

For a new contributor, follow the data through the pipeline:

1. **Understand the model first:** `panda/src/egg/eggData.h` → `eggGroupNode.h` → `eggNode.h`/`eggObject.h` (the container/inheritance spine), then `eggPrimitive.h`/`eggVertex.h`/`eggVertexPool.h` (geometry) and `eggGroup.h` (the flag-rich glue node). Remember: **no scene-graph types appear here on purpose.**
2. **The bridge:** `panda/src/egg2pg/load_egg_file.cxx` (public entry + post-load flatten/unify) then `panda/src/egg2pg/eggLoader.cxx::build_graph()` — this single method is the map of the whole conversion. Branch into `eggBinner.cxx` (grouping into Geoms), `eggRenderState.cxx` (egg modes → `RenderState`), and `characterMaker.cxx`/`animBundleMaker.cxx` (animation).
3. **The image layer:** `panda/src/pnmimage/pnmImage.h` + `pnmFileTypeRegistry.h` for the dispatch model; then any `panda/src/pnmimagetypes/pnmFileType<Format>.cxx` for concrete codecs.
4. **Config knobs as a roadmap:** the three `config_*.cxx` files (`config_egg.cxx`, `config_egg2pg.cxx`, `config_pnmimagetypes.cxx`) double as an annotated index of every tunable behavior and which subsystem owns it.

Key cross-cutting takeaway to keep while reading: the egg library is a *tools-grade, double-precision, scene-graph-free* data structure; `EggLoader` is the **one-way** materialization layer (and `EggSaver` the reverse); `PNMImage`/`PfmFile` are CPU image IO that the loader uses only transitively via `Texture`. Keep these boundaries intact when adding features — e.g. do not add `pandaNode.h` includes to `panda/src/egg`.

## Known shortcomings & footguns

The constructive picture above is only half the story. The asset-format and loading layer is also where Panda3D collects some of its most-cited footguns — community-mined complaints about formats (`.egg`, `.bam`), model loading, DCC exporters, and the modern-interchange (glTF/FBX/Assimp) support gaps. These are preserved here as community-sourced opinion and history; severity/status tags are the original authors'. Animation-specific joint footguns and the standalone command-line converters live on neighbouring pages (noted inline).

### `.bam` files are version-locked
**Severity: major · Status: by-design (still-open) — the #1 asset complaint**

Each `.bam` is tied to a specific Panda bam-version; a newer/older Panda refuses to load it, with no built-in migration. The official advice is always "keep the `.egg` source and regenerate" — which is why the egg library exists as the authoritative source representation (see the egg section above). `.bam` is the serialized scene-graph cache, not an authoring format.

> "the bam file is tied to a particular version of Panda, and if you later
> download a version... that no longer supports the version of the bam file(s)...
> you will need to regenerate them." — drwr *(maintainer)*, [t/1132](https://discourse.panda3d.org/t/1132)

> "Using .bam files for a demo has been a mistake, since .bam files are
> version-dependant." — enn0x, [t/2138](https://discourse.panda3d.org/t/2138)

### `.egg` is verbose ASCII and slow to load
**Severity: minor · Status: by-design tradeoff**

`.egg` is human-readable but "many times larger than the file it was converted from" and slow to parse (the hand-written flex/bison parser in `panda/src/egg`, see above). The workaround (`.bam`) reintroduces the version-lock above, and gzip/pzip compression *worsens* load time.

> "It's normal for egg files to get quite large. The egg syntax is pretty verbose
> and fluffy." — drwr/trusted, [t/229](https://discourse.panda3d.org/t/229)

### `.egg` can't express PBR materials or lights
**Severity: major · Status: by-design (drives the glTF push)**

`.egg` predates PBR and stores no lights, so any egg-routed pipeline silently drops modern materials/lighting — colliding with Blender 2.8+ being PBR-only. This is the format limitation that motivates the strategic move toward glTF (next entries) and the deprecation limbo (last entry). (`EggMaterial`/`EggTexture` above are declarative records with no PBR channels.)

> "EGG doesn't support PBR materials, and... Blender 2.8 only does PBR." — Moguri
> *(maintainer)*, Discord

For the asset-exporter and DCC-tool footguns (glTF as an external pip addon, the glTF loader failing in frozen apps, the built-in Assimp `.obj`/`.fbx`/`.dae` loader, the fragmented Blender exporter situation, and the lagging Maya/3ds Max exporters), see [pandatool's footguns](pandatool.md#known-shortcomings-footguns).

### egg loader ignores collision geometry on *animated* models
**Severity: minor · Status: by-design**

`<Collide>` tags in an egg loaded as an animated Actor are silently ignored — so collision works on a static model and vanishes once it's an Actor. This is a limitation of the egg2pg loader path: the `make_collision_*` family in `eggLoader.cxx` (see the egg2pg section above) does not run for `<Dart>`/character subtrees.

> "The egg loader does not support loading collision geometry from an animated egg
> file. It is an unfortunate limitation... and it confuses a lot of people." —
> drwr *(maintainer)*, [t/5849](https://discourse.panda3d.org/t/5849)

### Path resolution is inconsistent: model-path vs cwd
**Severity: major · Status: still-open (acknowledged clunky)**

`loader.loadModel()` resolves against `model-path`; raw `Filename`/`PNMImage` resolve against the cwd. The same relative path works in one call and fails in another, and an IDE changing the cwd silently breaks loading. (`Filename`'s VFS/real-filesystem path model is covered in [Cross-cutting concepts](../cross-cutting-concepts.md).)

> "there is an inconsistency between the loader for egg files and PNMImage and
> Filename... loader finds files relative to the python file directory[,] Filename
> finds files relative to the cwd." — James, [t/29979](https://discourse.panda3d.org/t/29979)

### Unix-style forward-slash paths required everywhere, even on Windows
**Severity: minor (very common) · Status: by-design**

All Panda APIs require forward slashes regardless of OS; Windows users naturally pass backslashes (or `os.path`/`str(pathlib.Path)` output) and get failures or mangling. (This is the `Filename` convention — see [Cross-cutting concepts](../cross-cutting-concepts.md).)

### Filename case-sensitivity differs by OS
**Severity: major · Status: by-design**

A mis-cased path loads fine on Windows (with only a non-fatal "incorrect case" warning) but fails outright on Linux/macOS — so the bug is invisible until cross-platform.

> "On Windows, the incorrect case doesn't matter, and the file will load anyway.
> Not so on Linux." — drwr *(maintainer)*, [t/2392](https://discourse.panda3d.org/t/2392)

### Non-power-of-two textures get silently resized (blurriness)
**Severity: minor · Status: by-design (config-mitigable)**

NPOT textures are resized at load (`textures-power-2 down/up`), introducing blurriness with no error; pixel-art/UI textures lose quality unexpectedly. (Texture images flow through `PNMImage` and the loader's `load_textures()` step — see the pnmimage and egg2pg sections above.)

### No built-in asset hot-reload; reloading leaks/duplicates geometry
**Severity: minor · Status: still-open**

No live reload. Rolling your own reload-on-change grows vertex/normal counts and memory each time (model caching + Actor not cleanly releasing the old model — the reference-counted `EggData`/`PandaNode` ownership discussed throughout this page and in [Cross-cutting concepts](../cross-cutting-concepts.md)).

### `.egg` deprecation limbo
**Severity: minor · Status: in-limbo**

Maintainers signal `.egg` will eventually be deprecated for glTF and now recommend glTF — yet egg is "not officially considered outdated yet" and remains the only fully-native, fully-featured authoring format with mature tooling, leaving new users without a clear "which format" answer.
