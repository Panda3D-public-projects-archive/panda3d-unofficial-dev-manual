# pandatool (asset pipeline tools)

`pandatool` is the standalone toolchain that lives entirely *outside* the runtime engine: command-line converters, the texture-atlasing `egg-palettize`, the egg/bam compilers, the runtime model-loader plugin (`ptloader`), and the PStats profiling server with its GUI front-ends. Everything is organized around three serialization layers — **egg** (plain-text scene graph, the canonical interchange format), **bam** (binary compiled form for runtime), and **native 3D formats** (`.flt`, `.lwo`, `.x`, plus everything Assimp reads). Two abstract plugin interfaces unify the import/export paths: `SomethingToEggConverter` (any `xxx2egg`) and `EggToSomethingConverter` (any `egg2xxx`); these same converters are reused at *runtime* by `ptloader`'s `LoaderFileTypePandatool` so that `pview foo.flt` or `loader.loadModel("bar.lwo")` work transparently. Orthogonal to all of this, `pstatserver` + `gtk-stats`/`win-stats`/`mac-stats` aggregate and visualize the profiling stream emitted by the engine's `pstatclient`.

Almost the entire cluster is authored by `drose` (David Rose), with the Assimp integration by `rdb` (Rüdiger Dreier). The egg-centric design means most converters never touch the live scene graph — they build an `EggData` tree in memory and let the egg library do the heavy lifting. Below, each directory is documented with its central abstraction, inheritance chain, integration points, entry points for bug-fixing, and community-sourced gotchas.

---

## egg-palettize

**What it is.** The standalone command-line front-end (`egg-palettize`) that drives the texture-atlasing engine in `palettizer/`. It reads a set of egg files plus a `.txa` configuration script, analyzes every texture reference, packs textures into shared "palette" images, rewrites the egg files to point at the new palettes, and remembers all of this in a persistent database (`textures.boo`, a bam file) so subsequent runs are incremental.

**Central classes & inheritance.**
- `EggPalettize` (`pandatool/src/egg-palettize/eggPalettize.h`) — `class EggPalettize : public EggMultiFilter`. This is the program object; `EggMultiFilter` (from `eggbase/`) gives it multi-egg-in/multi-egg-out command-line plumbing. Its `run()` is the whole workflow.
- `TxaFileFilter` (`pandatool/src/egg-palettize/txaFileFilter.h`) — `class TxaFileFilter : public TexturePoolFilter`; a runtime `TexturePoolFilter` callback (not a `.txa` script preprocessor) that, once registered, gets a chance to modify every texture as it is loaded from disk through the texture pool.

**How `run()` flows** (see `eggPalettize.cxx` ~lines 600–835): create or load the global `Palettizer *pal` from the `textures.boo` database (`new Palettizer` or `DCAST(Palettizer, obj)` after a bam read), `pal->read_txa_file(...)`, then the pipeline `pal->process_all()` → `pal->optimal_resize()` → `pal->read_stale_eggs()` → `pal->generate_images()` → `pal->write_eggs()`. The tool is thin; the logic lives in `palettizer/`.

**Where to start.** `eggPalettize.cxx` `run()` to understand the command-line phases; the `-H` help text it prints is the authoritative reference for `.txa` syntax.

**Gotchas (community).** The canonical minimal recipe is to make an output dir, `touch textures.txa`, then `egg-palettize -d result -opt -nodb myfile.egg` ([discourse t/8176](https://discourse.panda3d.org/t/8176)); `-nodb` skips the persistent database for one-shot runs. `.txa` lines are size/quality rules like `*.png : 100% nearest`, and you can assign textures directly to a named group to control the install subdirectory ([discourse t/924](https://discourse.panda3d.org/t/924)). The `:margin` option historically sampled from the texture *edge*, producing visible margin artifacts — a known reported bug ([GitHub #192](https://github.com/panda3d/panda3d/issues/192)); the margin exists to prevent bleedover between neighbors when a palette is mip-reduced ([discourse t/3545](https://discourse.panda3d.org/t/3545)).

---

## palettizer

**What it is.** The actual atlasing engine behind `egg-palettize`. It models the full problem domain — source textures on disk, the egg files that reference them, palette "groups" that travel together in VRAM, individual palette pages/images, and the placement of each texture on a page — and serializes that entire model graph to/from `textures.boo` via the BAM system for incremental re-runs.

**Central abstraction & inheritance.** `Palettizer` (`pandatool/src/palettizer/palettizer.h`) is `class Palettizer : public TypedWritable`; it is the engine and the BAM-serializable root. A module-global `extern Palettizer *pal;` is the single shared instance for a session. Nearly every other class here is also `TypedWritable` and registers with the BAM read factory (see `config_palettizer.cxx`, `init_palettizer()`), so the whole object graph round-trips through bam:
- `EggFile` (`eggFile.h`) — one egg model and its texture references.
- `PaletteGroup` / `PaletteGroups` (`paletteGroup.h`, `paletteGroups.h`) — sets of textures that move together in memory; the unit of grouping that the `.txa` file controls.
- `TextureImage` (`textureImage.h`) — one logical source texture, possibly placed into several groups.
- `SourceTextureImage` / `DestTextureImage` (`sourceTextureImage.h`, `destTextureImage.h`) — the on-disk input vs. the generated output, both subclasses of `ImageFile` (`imageFile.h`).
- `PalettePage` / `PaletteImage` (`palettePage.h`, `paletteImage.h`) — a page groups placements sharing texture properties; the image is the packed bitmap.
- `TexturePlacement` / `TexturePosition` (`texturePlacement.h`, `texturePosition.h`) — where a texture sits on a palette image (the bin-packing result).
- `TextureReference` / `TextureProperties` / `TextureRequest` — how an egg references a texture, the format/filter/mipmap properties that decide packability, and the requested resize.
- `TxaFile` / `TxaLine` (`txaFile.h`, `txaLine.h`) — parsed `.txa` rules; `TxaLine` is `friend class` of `Palettizer`.
- `OmitReason` (`omitReason.h`), `TextureMemoryCounter`, `FilenameUnifier` (path canonicalization), `pal_string_utils` — supporting utilities.

**How it plugs in.** Pure pandatool; depends on the egg library (to read/rewrite egg texture references), `pnmimage` (to load/save the actual bitmaps via `PNMFileType`), and the BAM reader/writer in `putil` for `textures.boo`. It does *not* touch the live scene graph. The output is twofold: modified egg files + generated palette image files.

**Where to start.** `palettizer.cxx` — the `process_all`/`optimal_resize`/`generate_images`/`write_eggs` methods are the algorithm. To change packing, look at `texturePlacement.cxx` and `paletteImage.cxx`. To change which textures are eligible to combine, look at `textureProperties.cxx` (equality drives page assignment).

**Config / versioning.** `config_palettizer.cxx` only registers types; behavior is driven by the `.txa` file and command-line switches. Note the static `Palettizer::_pi_version` / `_min_pi_version` / `_read_pi_version` fields — the database format is versioned, and `complete_pointers`/`finalize` handle reading older `textures.boo` files.

---

## converter

**What it is.** The two abstract base classes that define the entire converter plugin contract, shared by both the standalone `xxx2egg`/`egg2xxx` tools and the runtime `ptloader`. This is the seam that lets one converter implementation serve both a command-line program and a loader plugin.

**Central abstractions.**
- `SomethingToEggConverter` (`pandatool/src/converter/somethingToEggConverter.h`) — base for all importers. Pure-virtual `make_copy()`, `get_name()`, `get_extension()`, `convert_file(const Filename &)`. It holds a `PT(EggData) _egg_data` target, a `PathReplace` for filename remapping, animation parameters (`AnimationConvert`, frame range, frame rates, character name), and `get_input_units()`. Crucially it also offers `convert_to_node(const LoaderOptions &, const Filename &)` and `supports_convert_to_node()` so a converter can optionally produce a `PandaNode` *directly* (the fast path) instead of going through egg.
- `EggToSomethingConverter` (`eggToSomethingConverter.h`) — base for all exporters; `write_file(const Filename &)`, plus `_output_units` and `_output_coordinate_system`.
- `TxoConverter` (`txoConverter.h`) — `class TxoConverter : public ProgramBase, public WithOutputFile`; handles `.txo` precompiled-texture-object files.

**How it plugs in.** Every concrete converter (`FltToEggConverter`, `LwoToEggConverter`, `XFileToEggConverter`, `VRMLToEggConverter`, `DXFToEggConverter`, `ObjToEggConverter`, `DAEToEggConverter`) derives from `SomethingToEggConverter`. Standalone tools wrap them via `eggbase/somethingToEgg.h`; `ptloader` wraps them via `LoaderFileTypePandatool`.

**Where to start.** `somethingToEggConverter.h` is the contract to read before implementing a new format. To add a converter you implement these virtuals, then register it in two places: a standalone `xxx2egg` program (in the format's `xxxprogs/` dir) and `config_ptloader.cxx`.

---

## ptloader

**What it is.** The runtime bridge that registers pandatool's converters with the engine's `Loader` system so non-egg formats load transparently. When you `loadModel("foo.flt")`, the engine consults the `LoaderFileTypeRegistry`, finds the `LoaderFileTypePandatool` registered for `.flt`, and it runs the `FltToEggConverter`.

**Central class & inheritance.** `LoaderFileTypePandatool` (`pandatool/src/ptloader/loaderFileTypePandatool.h`) — `class LoaderFileTypePandatool : public LoaderFileType`. It is a thin adapter holding a `SomethingToEggConverter *_loader` and an optional `EggToSomethingConverter *_saver`, forwarding `get_extension`/`supports_load`/`supports_save` to them.

**Load path** (`loaderFileTypePandatool.cxx` `load_file`): it `make_copy()`s the loader (converters are not assumed reentrant), sets the search path from the file's directory, maps `LoaderOptions::LF_convert_anim/skeleton/channels` onto `AnimationConvert`, then — if `ptloader-load-node` is true and the converter `supports_convert_to_node()` — calls `convert_to_node()` for the fast direct-to-`PandaNode` path. Otherwise it falls back through egg: build `EggData`, `convert_file()`, optionally rescale units to `ptloader-units`, synthesize point primitives or recompute normals if missing, then `load_egg_data()`.

**How it plugs in.** `config_ptloader.cxx` `init_libptloader()` is the registration hub: it initializes the `flt`, `lwo`, `xfile` libs and registers `LoaderFileTypePandatool` wrappers for FLT, LWO, DXF, VRML, and X-file converters. Maya is registered as a **deferred type** (`reg->register_deferred_type("mb", "mayaloader")`) so the heavy Maya API libs load only on demand. Note the obj/dae registrations are currently commented out in this file — those formats are reached through other paths (Assimp / dedicated tools).

**Where to start.** `config_ptloader.cxx` to see which formats are wired up, then `loaderFileTypePandatool.cxx::load_file` for the conversion/animation/units logic.

**Gotchas (community).** The engine supports deferred loading of loader file types ([commit 25a599e3](https://github.com/panda3d/panda3d), `panda/src/pgraph/loader.cxx`). For the `.x` format specifically, Panda can load it directly at load time without a manual `x2egg` step precisely because of this registration ([discourse t/2690](https://discourse.panda3d.org/t/2690)).

**Config variables** (`config_ptloader.cxx`): `ptloader-units` (`DistanceUnit`, default `DU_invalid`) — auto-convert loaded models to these units; `ptloader-load-node` (bool, default `true`) — allow the faster direct-to-`PandaNode` path; set false to force the more-reliable egg route.

---

## bam

**What it is.** The egg↔bam compiler suite plus bam introspection. `egg2bam` compiles a (possibly large, human-readable) egg into a compact binary bam for fast runtime loading, with options to bake textures into `.txo`/compressed-texture (`.ctex`) form; `bam2egg` decompiles; `bam-info` dumps structure; `pts2bam` builds a point cloud bam.

**Central classes & inheritance.**
- `EggToBam` (`pandatool/src/bam/eggToBam.h`) — `class EggToBam : public EggToSomething`. Beyond plain serialization it can finalize textures through a real graphics pipeline.
- `BamToEgg` (`bamToEgg.h`) — `class BamToEgg : public SomethingToEgg`; reverses the process.
- `PtsToBam` (`ptsToBam.h`) — `class PtsToBam : public ProgramBase, public WithOutputFile`.
- `BamInfo` (`bamInfo.h`) — `class BamInfo : public ProgramBase`; read-only introspection.

**The `-ctex` subtlety.** `EggToBam` is unusual among tools in that it spins up an actual offscreen GPU context. `eggToBam.cxx` `make_buffer()` uses `GraphicsPipeSelection::get_global_ptr()` to create a `GraphicsPipe`/`GraphicsStateGuardian`/`GraphicsEngine` and an offscreen `GraphicsOutput` (`BF_fb_props_optional`, falling back to single-buffered) so textures can be loaded, compressed, and re-extracted as `.ctex` at the requested quality. `collect_textures()` walks the `PandaNode`/`RenderState` graph to find every `Texture`, and `convert_txo()` writes the `.txo` form. This is the one converter that depends on `display`/`gobj` graphics modules, not just egg.

**Where to start.** `eggToBam.cxx` `run()`/`handle_args()` for option parsing, `make_buffer()`/`convert_txo()` for the texture-baking path. For decompile bugs, `bamToEgg.cxx`.

**Gotchas (community).** `egg2bam` *complains if textures aren't present* and you must install them on the model path before compiling ([docs: Converting Egg to Bam](https://docs.panda3d.org/1.10/python/pipeline/egg-files/converting-egg-to-bam)). `bam2egg` is explicitly described by maintainers as "not a very good tool" and a lossy round-trip (e.g. textures can be lost going bam→egg→obj) ([discourse t/23842](https://discourse.panda3d.org/t/23842), [t/15781](https://discourse.panda3d.org/t/15781)) — prefer keeping the original egg/source rather than decompiling bam.

---

## eggbase

**What it is.** The shared command-line + I/O scaffolding for every egg-manipulating program. It provides standard options (normals handling, coordinate-system, units, transform/scale/rotate/translate) and the single-egg vs. multi-egg processing patterns that nearly every tool in the cluster builds on.

**Central abstraction & inheritance chain.** `EggBase` (`pandatool/src/eggbase/eggBase.h`) — `class EggBase : public ProgramBase`. It centralizes `add_normals_options()`, `add_transform_options()`, the `NormalsMode` enum, coordinate-system handling, and `convert_paths()`. The class tree:
- `EggSingleBase : public EggBase` (`eggSingleBase.h`) — one egg in scope.
  - `EggReader : virtual public EggSingleBase` (`eggReader.h`)
  - `EggWriter : virtual public EggSingleBase, public WithOutputFile` (`eggWriter.h`)
  - `EggFilter : public EggReader, public EggWriter` (`eggFilter.h`) — single egg in → single egg out (diamond via virtual inheritance).
    - `EggConverter : public EggFilter` (`eggConverter.h`)
      - `SomethingToEgg : public EggConverter` (`somethingToEgg.h`) — wraps a `SomethingToEggConverter` for a standalone `xxx2egg` program.
      - `EggToSomething : public EggConverter` (`eggToSomething.h`) — wraps an `EggToSomethingConverter` for `egg2xxx`.
- `EggMultiBase : public EggBase` (`eggMultiBase.h`) — many eggs at once.
  - `EggMultiFilter : public EggMultiBase` (`eggMultiFilter.h`) — batch in/out; this is what `EggPalettize` and most `egg-*` optimizer tools extend.
- `EggMakeSomething` (`eggMakeSomething.h`) — generators that emit egg without reading one.

**How it plugs in.** Sits between the engine's egg library and every tool program; depends on `progbase` (`ProgramBase`, option dispatch) and the egg library. Bam/converter/palettize/fltprogs/etc. all enter through one of these bases.

**Where to start.** `eggBase.cxx` for the shared option dispatchers (`dispatch_normals`, `dispatch_scale`, `dispatch_rotate_xyz`). To write a new converter program, subclass `SomethingToEgg` or `EggToSomething` and look at how `bam/` does it.

---

## flt

**What it is.** A complete reader/writer for MultiGen **OpenFlight** (`.flt`) — a record-based binary hierarchy format used heavily in simulation/GIS. Models are trees of "beads" (groups, objects, LODs, instances) each carrying transforms, geometry, materials, textures, and external references, written sequentially with ancillary records.

**Central abstraction & inheritance.** `FltRecord` (`pandatool/src/flt/fltRecord.h`) — `class FltRecord : public TypedReferenceCount`, the base for everything; it manages children/subfaces/extensions/ancillary records and comments. The key subtree:
- `FltBead : public FltRecord` (`fltBead.h`) — a record that carries a transform matrix.
  - `FltBeadID : public FltBead` (`fltBeadID.h`) — a bead with an ID/name.
    - `FltHeader : public FltBeadID` (`fltHeader.h`) — the file header *and* document-tree root; owns the material/texture/color palettes and vertex pool.
    - `FltGeometry : public FltBeadID` (`fltGeometry.h`) — indexed faces/vertices.
    - `FltGroup`, `FltObject`, `FltLOD`, `FltFace`, `FltMesh`, `FltInstanceRef`/`FltInstanceDefinition`, `FltExternalReference`, `FltLightSourceDefinition`, `FltEyepoint`, `FltCurve`.
- Palette/attribute records: `FltMaterial`, `FltTexture`, `FltPackedColor`, `FltLocalVertexPool`.
- Binary I/O: `FltRecordReader` / `FltRecordWriter` (`fltRecordReader.h`, `fltRecordWriter.h`) read/write opcode-tagged records; `FltOpcode` enumerates record types; `FltError` is the error enum.

**How it plugs in.** Pure parser; produces the FLT object tree consumed by `fltegg`. Depends only on `pandatoolbase` + `putil` (`Datagram`/`DatagramIterator`).

**Where to start.** `fltHeader.cxx` (read/write entry), `fltRecordReader.cxx`/`fltRecordWriter.cxx` for the binary layer, and `make_new_record` dispatch on `FltOpcode` to add a new record type.

**Config variable** (`config_flt.cxx`): `flt-error-abort` (bool) — when set, abort on FLT read errors instead of trying to continue.

---

## lwo

**What it is.** A reader for LightWave Object (`.lwo`) files, built on a generic **IFF** (Interchange File Format) chunk layer. IFF is a tagged, length-prefixed, big-endian chunk format; the `lwo*` classes are concrete chunk types layered on the generic `iff*` primitives.

**Central abstractions.**
- IFF layer: `IffInputFile` (`pandatool/src/lwo/iffInputFile.h`) — `class IffInputFile : public TypedObject`, a big-endian reader (`get_be_int32`, `get_be_float32`, chunk alignment) with a virtual `make_new_chunk(IffId)` factory hook. `IffChunk` (`iffChunk.h`) is the base chunk; `IffGenericChunk` holds unrecognized data; `IffId` is the 4-byte tag.
- LWO layer: `LwoInputFile : public IffInputFile` (`lwoInputFile.h`) overrides `make_new_chunk` to mint the right LWO chunk type. `LwoChunk`/`LwoGroupChunk` are LWO chunk bases. Concrete chunks: `LwoHeader` (`lwoHeader.h`, the FORM root), `LwoLayer`, `LwoPoints` (vertex positions), `LwoPolygons`, `LwoPolygonTags`, `LwoSurface` (+ the many `LwoSurfaceBlock*` sub-records for texture projection/opacity/coordinate systems), `LwoClip`/`LwoStillImage` (image references), `LwoDiscontinuousVertexMap`, `LwoBoundingBox`.

**How it plugs in.** Pure parser feeding `lwoegg`. The IFF layer is generic enough to be reused for other chunked formats. Depends only on `pandatoolbase` + `putil`.

**Where to start.** `lwoInputFile.cxx::make_new_chunk` is the dispatch table — the place to register a new chunk type. `iffInputFile.cxx` for the byte-level reading. `config_lwo.cxx` registers types only (no config variables).

---

## xfile

**What it is.** A reader/writer for Microsoft DirectX **X-files** (`.x`), supporting text, binary, and compressed encodings via a generated lexer/parser, plus the format's distinctive **template** system (X-files declare their own data schemas as templates, optionally identified by GUID).

**Central abstraction & inheritance.**
- `XFileNode` (`pandatool/src/xfile/xFileNode.h`) — base for all nodes in the X hierarchy.
  - `XFile : public XFileNode` (`xFile.h`) — the whole document in memory; handles `read`/`write` across `FT_text`/`FT_binary`/`FT_compressed` and `FS_32`/`FS_64` float sizes, resolves templates by name or `WindowsGuid`, and ships built-in `standard_templates` (compiled from `standardTemplates.x`).
  - `XFileTemplate` (`xFileTemplate.h`) — a type/schema definition; `XFileDataDef`/`XFileArrayDef` describe member layout.
  - `XFileDataNode` (`xFileDataNode.h`) → `XFileDataNodeTemplate` / `XFileDataNodeReference` — typed data instances.
- `XFileDataObject` (`xFileDataObject.h`) and its leaves `XFileDataObjectInteger`/`Double`/`String`/`Array` — the actual scalar/array values.
- `WindowsGuid` (`windowsGuid.h`) — GUID parsing/comparison for template identity.
- Lexer/parser: `xLexer.lxx`/`xParser.yxx` (flex/bison; `*.prebuilt` checked in), `XFileParseData`.

**How it plugs in.** Produces the X document tree consumed by `xfileegg` (`XFileToEggConverter`). Registered into `ptloader` so `.x` loads directly at runtime.

**Where to start.** `xFile.cxx` `read`/`read_header` for format detection, `xFileNode.cxx`/`xFileDataNode.cxx` for the tree, and the `.yxx`/`.lxx` grammar for text parsing. `config_xfile.cxx` registers types only.

---

## fltegg / lwoegg / xfileegg (format→egg converters)

These three sibling directories each contain exactly one converter that turns a parsed native tree into an `EggData`, implementing the `SomethingToEggConverter` contract from `converter/`:
- `FltToEggConverter` (`pandatool/src/fltegg/fltToEggConverter.h`) — translates FLT bead hierarchy, transforms, materials/textures into egg. (The reverse egg→flt path is not a `fltegg` converter class; it lives in the `egg2flt` program `fltprogs/eggToFlt.h`, `class EggToFlt : public EggToSomething`, which does the conversion inline.)
- `LwoToEggConverter` (`pandatool/src/lwoegg/lwoToEggConverter.h`) — maps LWO layers/surfaces/points/polygons into egg geometry with materials and texture references.
- `XFileToEggConverter` (`pandatool/src/xfileegg/xFileToEggConverter.h`) — walks X-file templates/data objects into egg hierarchies, including animation and materials.

Each `make_copy()`s cleanly so it can be reused by both its standalone `xxx2egg` program and `ptloader`. **Where to start:** the `convert_file()` / build-tree method in the respective `.cxx`. (`vrmlegg`, `dxfegg`, `objegg`, `daeegg` follow the identical pattern; obj/dae are not wired into `ptloader` by default.)

---

## assimp

**What it is.** Integration of the third-party **Assimp** (Open Asset Import Library), giving Panda a single plugin that reads a broad family of formats (`.fbx`, `.dae`, `.obj`, `.blend`, `.3ds`, etc.) by building Panda nodes directly from Assimp's `aiScene` — bypassing egg entirely.

**Central classes & inheritance.**
- `AssimpLoader` (`pandatool/src/assimp/assimpLoader.h`) — `class AssimpLoader : public TypedReferenceCount`. Wraps an `Assimp::Importer`, calls `read(filename)` then `build_graph()` to populate `PT(ModelRoot) _root`. Internally it builds per-material `RenderState`s and per-mesh `Geom`s (points/lines/triangles), converts skeletons via `create_joint()` into a `Character`/`CharacterJointBundle`, and animations via `create_anim_channel()` into `AnimBundle`s. A `BoneMap` ties `aiNode`s to joints.
- `LoaderFileTypeAssimp` (`loaderFileTypeAssimp.h`) — `LoaderFileType` registration; queries Assimp for its supported extension list.
- Assimp callback adapters: `PandaIOStream` (`pandaIOStream.h`), `PandaIOSystem` (`pandaIOSystem.h`) route Assimp's file I/O through Panda's VFS; `PandaLogger` (`pandaLogger.h`) routes Assimp logging into Panda's notify.

**How it plugs in.** `config_assimp.cxx` `init_libassimp()` registers a single `LoaderFileTypeAssimp` with the `LoaderFileTypeRegistry`, so it sits alongside `ptloader` in the loader registry but builds nodes itself (it does *not* go through `SomethingToEggConverter`/egg). Depends on the external `assimp` library and the core `pgraph`/`gobj`/`char` modules.

**Where to start.** `assimpLoader.cxx` — `build_graph()` is the dispatcher; `load_node`/`load_mesh`/`load_material`/`create_joint`/`create_anim_channel` are the per-feature builders. To support a new Assimp feature, that's where it goes.

**Gotchas (community).** Assimp can load FBX and DAE directly into Panda's native format, and is the recommended route for those formats, but maintainers caution that FBX/DAE animation support is *not as well supported* as glTF/bam/egg ([discourse t/15426](https://discourse.panda3d.org/t/15426); [Discord](https://discord.com/channels/524691714909274162/1057767450843824198/1217347017248866344)). For new projects, glTF (via the separate `panda3d-gltf` plugin) is generally preferred over the Assimp path.

**Config variables** (`config_assimp.cxx`): `assimp-calc-tangent-space`, `assimp-join-identical-vertices` (default true; merges duplicate verts), `assimp-improve-cache-locality` (reorders tris), `assimp-remove-redundant-materials`, `assimp-fix-infacing-normals`, `assimp-optimize-meshes`, `assimp-optimize-graph` (flattens hierarchy; default false — can lose hierarchy), `assimp-flip-winding-order`, `assimp-gen-normals` + `assimp-smooth-normal-angle` (crease angle), `assimp-collapse-dummy-root-node` (default true as of 1.10.13; collapses Assimp's synthetic root). Several note that you may need to clear the model-cache after changing them.

---

## pstatserver

**What it is.** The generic, GUI-agnostic PStats server framework: it accepts TCP/UDP connections from clients running the engine's `pstatclient`, decodes their profiling stream, maintains an in-memory model of each client's collectors/threads/frames, and provides the data structures behind every chart type. GUI front-ends (`gtk-stats`, `win-stats`, `mac-stats`, `text-stats`) subclass it.

**Central abstractions.**
- `PStatServer` (`pandatool/src/pstatserver/pStatServer.h`) — `class PStatServer : public ConnectionManager`. The connection manager; you `listen(port)`, it spawns a `PStatReader` per connection and calls the pure-virtual `make_monitor(const NetAddress &)` so the subclass supplies the right monitor type. `main_loop()`/`poll()` drive it. Also owns the shared "user guide bars" (horizontal reference lines).
- `PStatMonitor` (`pStatMonitor.h`) — `class PStatMonitor : public ReferenceCount`, the **abstract front-end interface**. One is created per connected client. It holds the `PStatClientData`, per-thread `PStatView`s, collector colors, and a set of empty virtual hooks (`new_collector`, `new_thread`, `new_data`, `lost_connection`, `open_strip_chart`, `open_flame_graph`, `open_piano_roll`, `open_timeline`) that a GUI subclass overrides to actually draw.
- `PStatClientData` (`pStatClientData.h`) — the decoded model of one client: its collector definitions, thread list, and frame data.
- `PStatReader` (`pStatReader.h`) — owns the per-connection socket and feeds data into the client data / views.
- View model: `PStatView`/`PStatViewLevel` (`pStatView.h`) compute the hierarchical collector totals per frame; `PStatThreadData` holds per-thread frame history.
- Graph base classes: `PStatGraph` (`pStatGraph.h`) is the abstract graph; `PStatStripChart`, `PStatFlameGraph`, `PStatPianoRoll`, `PStatTimeline` are the concrete analysis types (still GUI-agnostic — they compute layout, the toolkit subclass paints).
- `PStatListener : ConnectionListener` (`pStatListener.h`) accepts rendezvous connections.

**How it plugs in.** It is the server half of the protocol whose client half is `panda/src/pstatclient` in the engine. Depends on the `net`/`nativenet` modules (`ConnectionManager`/`Connection`). The toolkit dirs below only subclass `PStatServer`/`PStatMonitor`/the graph classes.

**Where to start.** `pStatServer.cxx` for connection lifecycle, `pStatMonitor.h` for the virtual hooks you must implement in a new GUI, and `pStatStripChart.cxx`/`pStatFlameGraph.cxx` for the per-chart math.

**Gotchas / design (community docs).** The server is split deliberately: "The generic server code is in `pandatool/src/pstatserver`, and the GUI-specific server code is in `pandatool/src/gtk-stats` and `pandatool/src/win-stats`" ([docs: PStats Internals](https://docs.panda3d.org/1.10/python/optimization/pstats/internals)). The client connects over TCP to `pstats-host`:`pstats-port` and then streams frame data over UDP. By default only one strip chart opens per client; the default graph layout is customizable ([docs: Customizing the UI](https://docs.panda3d.org/1.10/python/optimization/pstats/customization)). Each client thread can get its own set of graphs ([docs: Thread Profiling](https://docs.panda3d.org/1.10/python/optimization/pstats/thread-profiling)).

---

## gtk-stats

**What it is.** The GTK+ front-end that turns the abstract pstatserver model into real windows: strip charts, flame graphs, piano rolls, timelines, and the label stacks/legends, plus the chart-selection menus. This is the default Linux PStats GUI (`pstats` on Linux).

**Central classes & inheritance.**
- `GtkStatsServer : public PStatServer, public ProgramBase` (`pandatool/src/gtk-stats/gtkStatsServer.h`) — the concrete server; implements `make_monitor()` to return a `GtkStatsMonitor`. `gtkStats.cxx` is the `main()`: it calls `gtk_init(&argc,&argv)`, `new GtkStatsServer`, then enters the loop.
- `GtkStatsMonitor : public PStatMonitor` (`gtkStatsMonitor.h`) — per-client window; overrides the `open_*`/`new_*` hooks to create GTK widgets.
- `GtkStatsGraph` (`gtkStatsGraph.h`) — shared GTK rendering base for a graph window; `GtkStatsStripChart`, `GtkStatsFlameGraph`, `GtkStatsPianoRoll`, `GtkStatsTimeline` subclass it and the corresponding `pstatserver` graph class (multiple inheritance: GTK widget side + analysis side).
- `GtkStatsLabel` / `GtkStatsLabelStack` (`gtkStatsLabel.h`) — collector legend/labels.
- `GtkStatsChartMenu` (`gtkStatsChartMenu.h`) — the menu for opening new charts.

**How it plugs in.** Depends on `pstatserver` (the abstract framework) and GTK+. The pattern repeats verbatim in `win-stats` (Win32) and `mac-stats` (Cocoa) — same class names with `WinStats`/`MacStats` prefixes — so a fix here often needs mirroring there.

**Where to start.** `gtkStats.cxx` `main()` → `gtkStatsServer.cxx::make_monitor` → `gtkStatsMonitor.cxx` `open_strip_chart`/`open_flame_graph`. For a rendering bug in a specific chart, edit the matching `gtkStats<ChartType>.cxx`; remember the layout math lives in the `pstatserver` base, only the painting is here.

---

## Known shortcomings & footguns

The constructive picture above describes how the toolchain *works*; this section collects the community-mined ways it *breaks*. These are sourced from the Panda3D discourse/Discord and issue tracker — i.e. opinion, history, and reported experience — and are reproduced here because they shape day-to-day pipeline decisions. The focus here is the command-line tools, exporters, and the asset-pipeline workflow; the format-intrinsic `.egg`/`.bam` limitations live on the [egg](egg.md) page, and joint-control/animation footguns on the [characters-and-animation](characters-and-animation.md) page.

### `bam2egg` is a lossy decompile — no clean round-trip from `.bam`
**Severity: major · Status: by-design**

There is effectively no reliable way back from `.bam`. `bam2egg` loses attributes it doesn't understand, so if you lose your `.egg` source you may not fully recover it, and you can't convert between bam versions this way. (This is the maintainer-level confirmation of the `bam/` "Gotchas" note above — keep the original egg/source rather than decompiling bam.)

> "bam2egg is nowhere close to a robust conversion, so it doesn't surprise me that it loses lots of useful attributes." — drwr *(maintainer)*, [t/12022](https://discourse.panda3d.org/t/12022)

### glTF support is an external pip addon, not core
**Severity: major · Status: by-design (strategic direction is gltf)**

The de-facto modern interchange format isn't loadable out of the box — you `pip install panda3d-gltf` (Moguri's separate project). The built-in Assimp-based alternative (see the [assimp](#assimp) section above) is, per rdb, "very low-quality."

> "are you using panda3d-gltf... or the very low-quality built-in Assimp-based glTF loader?" — rdb *(maintainer)*, [#1420](https://github.com/panda3d/panda3d/issues/1420)

### glTF loader fails in frozen/packaged apps
**Severity: major · Status: still-open (manual registration workaround)**

Because the loader registers via Python entry points read by ShowBase, packaged apps lose it: works in dev, then *"Extension of file X.gltf is unrecognized"* in the distributable. You must manually register with `LoaderFileTypeRegistry` — the same registry the `ptloader`/`assimp` plugins populate (see the [ptloader](#ptloader) and [assimp](#assimp) sections above).

### Built-in Assimp loader (.obj/.fbx/.dae) was build-from-source & low quality
**Severity: major · Status: mitigated (now shipped) / historically painful**

For years, loading `.obj`/`.fbx`/`.dae` required compiling Panda from source plus `load-file-type p3assimp`. Even when working, it's "very low-quality," animations were broken, and Egg-library-routed converters inherit egg's limits (no lights). FBX in particular is poorly supported. (This expands the maintainer caution in the [assimp](#assimp) "Gotchas" note that FBX/DAE animation is less well supported than glTF/bam/egg.)

### Blender exporter situation is fragmented and rot-prone
**Severity: major · Status: still-open**

There is no single blessed exporter. The old chicken exporter (≤2.49) and YABEE (≤2.79) are dead on modern Blender; the recommended blend2bam works but commonly fails with *"SystemError: GPU API is not available in background mode,"* Draco issues, and addon interference.

> "yabee is just straight up broken on 3.6... Blend2Bam is failing for me with... SystemError: GPU API is not available in background mode." — CeyaSpaceCowboy, [t/29473](https://discourse.panda3d.org/t/29473)

### Maya/3ds Max exporters are per-DCC-version binaries that chronically lag
**Severity: major · Status: largely abandoned**

`maya2egg` is compiled against a specific Maya version (`maya2egg2009`, …) and needs a matching install; new Maya releases routinely lack a working exporter for a long time, and the binary may not even ship in the wheel. (This is the practical cost of the per-DCC, deferred-Maya wiring noted in the [ptloader](#ptloader) section above, where Maya is a deferred loader type.)

> "I don't know why maya2egg isn't found; I suspect... they are not included with the wheel." — rdb *(maintainer)*, [t/28333](https://discourse.panda3d.org/t/28333)

For the model-path / forward-slash / case-sensitivity path footguns (loader vs `Filename`/`PNMImage` path resolution, the Unix forward-slash requirement on Windows, and per-OS filename case-sensitivity), see [the egg page's footguns](egg.md#known-shortcomings-footguns).

---

### Where to start (this cluster)

- **Adding a new model format / fixing an importer:** read `converter/somethingToEggConverter.h` (the contract), then a concrete example end-to-end — `flt/` (parser) + `fltegg/fltToEggConverter.cxx` (parser→egg) — and register it in `ptloader/config_ptloader.cxx`.
- **Runtime loading behavior (`loadModel`/`pview` of non-egg files):** `ptloader/loaderFileTypePandatool.cxx::load_file` is the single chokepoint for the egg path and the direct-to-node fast path, plus units/animation handling.
- **Texture atlasing:** `egg-palettize/eggPalettize.cxx::run` for the phases, then `palettizer/palettizer.cxx` for the engine; `palettizer/texturePlacement.cxx` + `paletteImage.cxx` for packing.
- **egg↔bam compilation:** `bam/eggToBam.cxx` (note the offscreen-GPU `-ctex` path via `make_buffer()`), `bam/bamToEgg.cxx` for decompile.
- **Assimp-imported formats (FBX/DAE/OBJ/blend):** `assimp/assimpLoader.cxx::build_graph` — a self-contained node builder that does not touch egg.
- **PStats GUI/profiling:** `pstatserver/pStatMonitor.h` (the virtual interface) and `pStatServer.cxx` (connections); `gtk-stats/gtkStats.cxx` `main()` for the reference GUI wiring.
- **Shared tool plumbing (options, normals, units, single vs. multi egg):** `eggbase/eggBase.cxx` and the `EggSingleBase`/`EggMultiBase` hierarchy.
