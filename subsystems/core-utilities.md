# Core utilities, events & pipeline

This cluster is the foundation every other engine system stands on. It defines how Panda3D objects are reference-counted and serialized to disk (`.bam`), how time is measured, how events and tasks are dispatched, how threads and the copy-on-write "pipeline" keep the render and app threads from stepping on each other, how raw bytes are packed/unpacked and pulled out of a virtual file system, and the vector/matrix/bounding-volume math used throughout the scene graph. The two abstractions to internalize first are **`TypedWritable`** (the serializable, RTTI-tagged base class, in `putil`) plus **`Datagram`/`DatagramIterator`** (the byte stream it serializes into, in `express`), and the **`PipelineCycler` + `CycleData`** copy-on-write machinery (in `pipeline`) that makes the scene graph safely readable from multiple threads. Almost everything else here exists to support those.

A note on the build: these six directories compile into three DLLs. `express` builds `libp3express`; `pipeline` builds `libp3pipeline`; `putil`, `event`, `linmath`, and `mathutil` all roll into `libpanda`. The `EXPCL_PANDA_EXPRESS` / `EXPCL_PANDA_PIPELINE` / `EXPCL_PANDA_PUTIL` / `EXPCL_PANDA_EVENT` / `EXPCL_PANDA_LINMATH` / `EXPCL_PANDA_MATHUTIL` export macros on each class tell you which library a symbol lives in, which matters when you trace a dependency.

---

## putil

**What it is.** `panda/src/putil` ("Panda utilities") is the grab-bag of core object-management machinery that needs the threading library but is more general than any one subsystem. Its crown jewel is the **BAM serialization system**: a self-describing binary format that writes and reads arbitrary graphs of polymorphic, pointer-linked objects. It also holds the global clock, the type-keyed object factory, bit masks, the button registry, and the copy-on-write base classes. It is the heaviest directory in the cluster and the one a new contributor most often needs to extend (every persistent engine object touches it).

**Central abstraction and inheritance chain.** Everything serializable derives from **`TypedWritable`** (`putil/typedWritable.h`), which itself extends `TypedObject` (from `dtool`, the RTTI base). The canonical chain is:

```
TypedObject  ->  TypedWritable  ->  TypedWritableReferenceCount  ->  CachedTypedWritableReferenceCount  ->  CopyOnWriteObject
```

- `TypedWritable` (`putil/typedWritable.h`) declares the two methods every serializable class overrides: `write_datagram(BamWriter*, Datagram&)` to flatten itself into bytes, and `fillin(DatagramIterator&, BamReader*)` to read itself back. `complete_pointers()` re-links pointers to other objects after they are all read, and `finalize()` runs once the whole file is in. Note it carries `_bam_modified` (an `UpdateSeq`) and a tagged-pointer list of `BamWriter`s so a live object can be re-serialized incrementally.
- `TypedWritableReferenceCount` (`putil/typedWritableReferenceCount.h`) is `TypedWritable` + `ReferenceCount` (multiple inheritance) — the base for objects managed by `PointerTo`.
- `CachedTypedWritableReferenceCount` (`putil/cachedTypedWritableReferenceCount.h`) adds a separate "cache" reference count so the cache can hold an object without preventing normal lifetime semantics.
- `CopyOnWriteObject` (`putil/copyOnWriteObject.h`) adds the `cache_unref()`-driven copy-on-write protocol used together with `CopyOnWritePointer`.

**BAM read/write — the key classes.**
- `BamWriter` (`putil/bamWriter.h`/`.cxx`) walks an object, assigns each unique object an integer object-id, writes each type's name + a `TypeHandle` the first time it is seen, and emits each object's datagram. `BamReader` (`putil/bamReader.h`/`.cxx`) is the inverse: it reads the linear stream of datagrams, and for each object looks up a registered factory function to construct an empty instance, then calls its `fillin()`. The header comment is precise: "A Bam file can be thought of as a linear collection of objects… The objects may include pointers to other objects within the Bam file; the BamReader automatically manages these (with help from code within each class) and restores the pointers correctly." Inside `fillin`, you call `manager->read_pointer(scan)` for each referenced object; `BamReader` then calls your `complete_pointers()` once those targets exist (`read_pointer`/`read_pointers` are at `bamReader.h:169-170`).
- **Registration is the gotcha.** Each class must register a static "make from bam" factory function with the read factory via `BamReader::register_factory(TypeHandle, CreateFunc*)` (`bamReader.h:204`), conventionally from a `register_with_read_factory()` method that must be *called explicitly at init time* — it cannot be a vtable call because the object does not exist yet. If you forget, reading silently fails. The community has repeatedly hit this: a developer who copied the `Material` class found it "stopped being saved in BAM" until registration was added (discourse.panda3d.org/t/29203), and core devs discussed why the manual step is unavoidable in [Standardize TypedWritable #1630](https://github.com/panda3d/panda3d/issues/1630): "We can't use a vtable call for `register_with_read_factory` since those can only be done on an already-constructed object." Python types can now subclass `TypedWritable` and override `get_class_type`/`write_datagram` — see [#1495](https://github.com/panda3d/panda3d/issues/1495).
- The `Factory<TypedWritable>` template (`putil/factory.h`) is the generic type-keyed constructor registry; `WritableFactory` is a typedef of it inside `BamReader`. `register_factory()` maps a `TypeHandle` to a `CreateFunc*`.

**Versioning.** `putil/bam.h` holds the magic header `"pbj\0\n\r"` and the current version: major `6`, minor `46` at time of writing, with a remarkable inline changelog of every minor bump since 2007. When you add a field to a serializable class, you bump `_bam_minor_ver`, write the field unconditionally in `write_datagram`, and read it conditionally in `fillin` guarded by `manager->get_file_minor_ver()`. `BamReader::get_file_major_ver()`/`get_file_minor_ver()`/`get_file_endian()`/`get_file_stdfloat_double()` (`bamReader.h:147-150`) expose what the file on disk actually used (endianness and float-vs-double are per-file, set by `bam-endian` and `bam-stdfloat-double`).

**Other notable types.** `ClockObject` (`putil/clockObject.h`) keeps both real time (`get_real_time()`) and discrete frame time (`get_frame_time()`), supports timing modes (`M_normal`, `M_non_real_time`, `M_forced`, `M_degrade`, `M_slave`, `M_limited`, `M_integer`…) and notably stores its frame time inside a `PipelineCycler` (it includes `cycleData.h`), so frame time is itself pipelined per-thread-stage. `BitMask`/`BitArray` (`putil/bitMask.h`, `bitArray.h`) back `CollideMask`/`DrawMask`. `ButtonRegistry`/`ButtonHandle` (`putil/buttonRegistry.h`, `buttonHandle.h`) intern keyboard/mouse buttons. `BamCache` (`putil/bamCache.h`) is the on-disk model cache that stores converted assets as bam.

**How it plugs in.** `PandaNode`, `Texture`, `Geom`, `RenderState`, materials — essentially every persistent object in the scene graph — derive (transitively) from `TypedWritable` and define `write_datagram`/`fillin`. The model loader reads `.bam` via `BamReader`; `BamCache` writes them. `ClockObject::get_global_clock()` drives `AsyncTaskManager` (event) and animation.

**Entry points.** To understand serialization, read `bamReader.cxx` (`read_object`, `resolve`) and `bamWriter.cxx` (`write_object`, `enqueue_object`) side by side; pick any simple class with `write_datagram`/`fillin`/`register_with_read_factory` (e.g. `putil/bamCacheRecord.cxx` or a `RenderAttrib` subclass) as a template. To add a field to a bam-serialized class: edit its `write_datagram`/`fillin`, bump the minor version in `bam.h`.

**Config variables** (`putil/config_putil.cxx`): `bam-version`, `bam-endian` (default native), `bam-stdfloat-double` (write doubles vs floats), `bam-texture-mode` (how textures are embedded), `sleep-precision`, `preload-textures`, `preload-simple-textures`, `compressed-textures`, `cache-check-timestamps`, plus the all-important search paths `model-path` and `plugin-path` (`get_model_path()`/`get_plugin_path()`).

---

## event

**What it is.** `panda/src/event` is two related systems. The **event system** is a name-based publish/subscribe message bus: code calls `throw_event("name", params...)`, events accumulate on an `EventQueue`, and an `EventHandler` dispatches them to registered C++ hooks (Python's `messenger` is the scripting-side analogue). The **task system** is the cooperative/threaded scheduler: `AsyncTask`s are run each frame by an `AsyncTaskManager` across one or more `AsyncTaskChain`s, and `AsyncFuture` provides await-able results. This is the directory behind `base.messenger` and `taskMgr`.

**Event side — key classes.**
- `Event` (`event/event.h`) is a named message carrying a list of `EventParameter`s (`event/eventParameter.h`) and an optional receiver. `EventParameter` is a variant that can hold a number, string, or any `TypedWritableReferenceCount`/`TypedReferenceCount`.
- `EventQueue` (`event/eventQueue.h`) is the FIFO that `throw_event` pushes onto; there is a global queue.
- `EventHandler` (`event/eventHandler.h`) "maintains a set of 'hooks', function pointers assigned to event names, and calls the appropriate hooks when the matching event is detected." It supports plain function hooks, callback+`void*` hooks, and (C++11) `std::function` lambda hooks, kept in separate `pmap<string, …>` tables (`_hooks`, `_cbhooks`, `_lambdahooks`). `process_events()` drains the queue and dispatches; `get_future(name)` returns an `AsyncFuture` that completes when the named event next fires. `get_global_event_handler()` is the singleton.
- `throw_event.h` provides the free functions `throw_event(name, p1..p4)` and `throw_event_directly(handler, …)` — the primary way C++ code raises events without touching the queue object directly.
- Input plumbing types `ButtonEvent`/`ButtonEventList` and `PointerEvent`/`PointerEventList` live here too.

**Task side — central abstraction and chain.**
- `AsyncFuture` (`event/asyncFuture.h`, `TypedReferenceCount` + `Completable::Data`) is the await-able primitive; `AsyncGatheringFuture` waits on several.
- `AsyncTask` (`event/asyncTask.h`) **inherits from `AsyncFuture` and `Namable`** — every task is itself a future. You subclass it and override `do_task()`, returning a `DoneStatus`: `DS_done`, `DS_cont` (run again next frame), `DS_again` (restart), `DS_pickup`, `DS_exit`, `DS_pause`, `DS_interrupt`, or `DS_await` (suspend until another task/future finishes). `GenericAsyncTask` (`event/genericAsyncTask.h`) wraps a C function pointer; `PythonTask` (`event/pythonTask.h`) wraps a Python callable; `AsyncTaskSequence` runs sub-tasks in order; `AsyncTaskPause` sleeps.
- `AsyncTaskManager` (`event/asyncTaskManager.h`, `TypedReferenceCount` + `Namable`) owns the tasks and one or more `AsyncTaskChain` (`event/asyncTaskChain.h`). A chain is the scheduling unit: it has a thread count, a frame-budget, a tick-clock flag, and sorts tasks by `sort` then `priority`. The global manager is what Python's `taskMgr` wraps. To run tasks on a background thread you create a multi-threaded chain — the docs describe `taskMgr.setupTaskChain('chain', numThreads=…)` ([Task Chains](https://docs.panda3d.org/1.10/python/programming/tasks-and-events/task-chains)).

**Gotchas / maintainer notes.** The low-level `Thread`/`Mutex` classes in `pipeline` are not the intended app-level concurrency API — a core contributor's advice on the forum: "Pay no attention to those classes in the API reference; they're very low-level. There are much better high-level tools for threading your tasks" — i.e. task chains ([discourse.panda3d.org/t/6906](https://discourse.panda3d.org/t/6906)). Task `DoneStatus` values in code exceed those documented in older manuals ([discourse.panda3d.org/t/9446](https://discourse.panda3d.org/t/9446)); trust `asyncTask.h`.

**How it plugs in.** `ShowBase` builds a global `AsyncTaskManager`; engine subsystems (collision, animation, audio, the igLoop/dataLoop render tasks) all register tasks on it. `throw_event` is used pervasively for window events, button presses, and collision notifications. `ClockObject` (putil) supplies the per-frame `dt` tasks read via `get_dt()`.

**Entry points.** Read `eventHandler.cxx` (`dispatch_event`, `process_events`) for the event flow, and `asyncTaskManager.cxx` + `asyncTaskChain.cxx` (`do_poll`, `service_one_task`, `cycle`) for the scheduler loop. To add a new built-in event, `throw_event` it and add a hook. To change task scheduling, start in `AsyncTaskChain::do_poll`.

**Config variables** (`event/config_event.cxx`): primarily the type-registration init function; task/threading tuning is exposed mostly through `pipeline` (`support-threads`) and Python-level config. (`config_event.cxx` registers no `ConfigVariable*` of its own — confirmed by grep.)

---

## pipeline

**What it is.** `panda/src/pipeline` provides Panda's threading abstraction and the **copy-on-write "pipeline cycler"** that lets the app thread mutate the scene graph while the render (Cull/Draw) thread reads a stable older copy. It abstracts native threads, mutexes, condition variables and semaphores behind a uniform API with three swappable back-ends (true OS threads, "simple" cooperative user-space threads, or a dummy no-thread build), and it implements the N-stage data-cycling that is the heart of Panda's multithreaded render model.

**Threading primitives.**
- `Thread` (`pipeline/thread.h`, `TypedReferenceCount` + `Namable`) is the abstract thread: subclass and override `thread_main()`. Statics `get_main_thread()`, `get_current_thread()`, `get_current_pipeline_stage()`, `is_true_threads()`/`is_simple_threads()`. Crucially, each `Thread` carries a **pipeline stage** (`get_pipeline_stage()`), which selects which copy of cycled data it sees. The concrete impl is chosen at compile time via `threadImpl.h` (`threadPosixImpl`, `threadWin32Impl`, `threadSimpleImpl`, or `threadDummyImpl`). `ExternalThread`/`MainThread` represent threads Panda didn't create.
- `Mutex` (`pipeline/pmutex.h`) is a non-reentrant lock; its header warns explicitly that double-locking "can deadlock itself" on some platforms and to use `ReMutex` (`pipeline/reMutex.h`) if you need reentrancy. `LightMutex`/`LightReMutex` (`pipeline/lightMutex.h`, `lightReMutex.h`) are spin-based, lower-overhead locks for very short critical sections. Each `Mutex` inherits from either `MutexDebug` or `MutexDirect` depending on `DEBUG_THREADS` — the debug variant tracks lock ownership and detects deadlocks. `ConditionVar`/`ConditionVarFull` (`pipeline/conditionVar.h`) and `Semaphore` (`pipeline/psemaphore.h`) round out the toolkit. RAII holders `MutexHolder`, `ReMutexHolder`, `LightMutexHolder` acquire on construct and release on destruct — always prefer these.

**The pipeline cycler — central abstraction.** This is the part you must understand to work on the scene graph safely.
- `CycleData` (`pipeline/cycleData.h`) is "a single page of data maintained by a PipelineCycler." You subclass it to hold the fields that must be protected across pipeline stages, and you must implement `make_copy()` (used to fork a stage's data on write). Note the conditional base class: when `DO_PIPELINING` is compiled in, `CycleData` is a `NodeReferenceCount` (so different stages can share the same page until one writes); when pipelining is disabled it is a plain `MemoryBase` stored inline for zero overhead.
- `PipelineCycler<CycleDataType>` (`pipeline/pipelineCycler.h`) "maintains different copies of a page of data between stages of the graphics pipeline." You never read or write its data directly. Instead you wrap it:
  - `CycleDataReader<CData>` (`pipeline/cycleDataReader.h`) — RAII, gives a `const CData*` for the current thread's stage.
  - `CycleDataWriter<CData>` (`pipeline/cycleDataWriter.h`) — RAII, gives a mutable `CData*`, performing the copy-on-write fork if another stage still references the old page.
  - Stage-specific variants (`CycleDataStageReader/Writer`, `CycleDataLockedReader`) let upstream code reach into a specific stage.
- `Pipeline` (`pipeline/pipeline.h`) is the manager that owns the set of stages and performs `cycle()` once per frame, which shifts every cycler's stage-N data down to stage N+1 (this is what "publishes" the app thread's changes to the render thread). The handy `OPEN_ITERATE_*` macros in `pipelineCycler.h` walk the stages for cache-invalidation passes. When `DO_PIPELINING` is off, the whole apparatus collapses to a trivial inline implementation with the same interface (`pipelineCyclerTrivialImpl.h`).

**Gotchas / design rationale / maintainer notes.** The threaded cycler has a real history of subtle bugs. A 2024 fix, [`pipeline: fix multithreaded render pipeline deadlock`](https://github.com/panda3d/panda3d/commit/e04ddbef9a49c84823d8a172f75bff283c81864e), notes the deadlock "happens when another thread holds a cycler lock and then attempts to call `Pipeline::remove_cycler`." More fundamentally, the ongoing PR [Implement EBR to solve scenegraph threading (#1853)](https://github.com/panda3d/panda3d/pull/1853) states bluntly that "Panda3D's threaded `PipelineCycler` has not been reliably thread-safe" and reworks reclamation using epoch-based reclamation (EBR) — essential reading if you touch `pipeline.cxx`/`pipelineCyclerTrueImpl.cxx`. Community reports also tie occasional DirectX crashes to "the multithreaded render pipeline" ([discourse.panda3d.org/t/25621](https://discourse.panda3d.org/t/25621)). Treat the COW invariants as load-bearing: a `CycleDataWriter` obtained while a reader is live in the same stage is a bug.

**How it plugs in.** `PandaNode`, `RenderState`, `TransformState`, `Geom`, `Camera` and basically every mutable scene-graph object embeds one or more `PipelineCycler<...CData>` members and exposes their fields only through CDReaders/CDWriters. The threaded render pipeline (`display`/`pgraph`) relies entirely on this. `ClockObject` (putil) also pipelines its frame time. Without `pipeline`, nothing in `pgraph` could be touched from two threads.

**Entry points.** Read `pipeline.cxx` (`cycle`, `add_cycler`, `remove_cycler`) and `pipelineCyclerTrueImpl.cxx` (`write_upstream`, `cycle`, the elevate/lock logic) for the COW core; read `pmutex.h` + `mutexDebug.cxx` to understand lock instrumentation; read `thread.cxx` + the chosen `thread*Impl.cxx` for the threading abstraction. To add a thread-safe field to a scene-graph node, follow an existing node's `CData` pattern.

**Config variables** (`pipeline/config_pipeline.cxx`): `support-threads` (master switch for true threading), `name-deleted-mutexes` (debug aid), `thread-stack-size`. Whether `DO_PIPELINING`/`DEBUG_THREADS` are defined is decided at *compile* time, not via config.

---

## express

**What it is.** `panda/src/express` is the lowest-level support library (`libp3express`, depended on by everything). It holds the byte-level serialization primitives (`Datagram` and friends) that BAM is built on, the reference-counting/smart-pointer machinery (`ReferenceCount`, `PointerTo`, weak pointers), the `Filename` abstraction, the **virtual file system** (transparently overlaying directories, multifiles, zip archives and ramdisks), and stream-based compression/encryption/hashing utilities.

**Serialization primitives.**
- `Datagram` (`express/datagram.h`, a `TypedObject`) is "an ordered list of data elements, formatted in memory for transmission over a socket or writing to a data file." You append typed values with `add_bool`/`add_int8/16/32/64`/`add_uint*`/`add_float32/64`/`add_stdfloat`/`add_string`/`add_wstring`/`add_blob`; default packing is little-endian, with explicit `add_be_*` big-endian variants. It is headerless — the reader must know the field order.
- `DatagramIterator` (`express/datagramIterator.h`) reads them back with matching `get_*` calls. `DatagramGenerator`/`DatagramSink` (`express/datagramGenerator.h`, `datagramSink.h`) are the abstract source/destination interfaces `BamReader`/`BamWriter` consume — concrete versions in putil (`datagramInputFile`, `datagramOutputFile`, `datagramBuffer`) read/write disk or memory.
- `Ramfile` (`express/ramfile.h`) is an in-memory file-like buffer; `StringStream`, `SubStream`, `Buffer`, `CircBuffer` are related byte plumbing.

**Object lifetime.** `ReferenceCount` (`express/referenceCount.h`, base `MemoryBase`) is "a base class for all things that want to be reference-counted… works in conjunction with PointerTo to automatically delete objects when the last pointer goes away." It uses an atomic count (`ref()`/`unref()`), supports weak references (`weak_ref()`/`get_weak_list()`), `local_object()` (mark stack-allocated, never delete), and the lock-free helpers `ref_if_nonzero()`/`unref_if_one()`. `PointerTo<T>` / `ConstPointerTo<T>` (`express/pointerTo.h`, the `PT()`/`CPT()` macros) are the smart pointers; `WeakPointerTo` (`express/weakPointerTo.h`) holds non-owning refs that null out on delete; `PointerToArray` (`express/pointerToArray.h`) is a refcounted shareable array used heavily by `GeomVertexData`. `TypedReferenceCount` (`express/typedReferenceCount.h`) is `TypedObject` + `ReferenceCount`.

**Virtual file system.**
- `VirtualFileSystem` (`express/virtualFileSystem.h`) presents "a hierarchy of directories and files that appears to be one continuous file system, even though the files may originate from several different sources." `get_global_ptr()` is the singleton. You `mount()` a `Multifile`, `ZipArchive`, or physical directory at a mount point; `get_file()`, `open_read_file()`, `scan_directory()`, `resolve_filename()` then operate across all mounts transparently. Most I/O methods are tagged `BLOCKING` (they may yield under SIMPLE_THREADS).
- `VirtualFile` (`express/virtualFile.h`) is the abstract file handle; `VirtualFileMount` (`express/virtualFileMount.h`) is the abstract mount, with concrete subclasses `VirtualFileMountSystem` (real OS dir), `VirtualFileMountMultifile`, `VirtualFileMountZip`, `VirtualFileMountRamdisk`, and `VirtualFileMountAndroidAsset`. `Multifile` (`express/multifile.h`) is Panda's own archive format (optionally compressed/encrypted).

**Compression/hashing.** `compress_string`/`decompress_string` (`express/compress_string.h`) and the `IDecompressStream`/`OCompressStream` zlib wrappers (`express/zStream.h`), `encrypt_string`/`decrypt_string` (`express/encrypt_string.h`, OpenSSL via `openSSLWrapper.h`), `HashVal`/`ChecksumHashGenerator` (`express/hashVal.h`), and `Patchfile` (`express/patchfile.h`) for binary diffs.

**Gotchas / maintainer notes.** The most common VFS confusion is the relationship between mounting and the model loader's search path: mounting a Multifile does **not** add it to `model-path`. As a core dev advised someone who couldn't load a mounted model, check that `mount()` actually returned success and that `.` (or the mount point) is on the model-path ([discourse.panda3d.org/t/7342](https://discourse.panda3d.org/t/7342)); the loader resolves a relative filename against `model-path` first, and only then does the resolved path hit the VFS ([discourse.panda3d.org/t/2606](https://discourse.panda3d.org/t/2606)). `dcast<T>()` (`express/dcast.h`) is the checked downcast used everywhere; it can be made to verify at runtime via the `verify-dcast` config var.

**How it plugs in.** `putil`'s BAM system serializes into `Datagram`s and reads from `DatagramGenerator`s defined here. The model `Loader`, texture loading, shader loading, and `BamCache` all go through `VirtualFileSystem`. `ReferenceCount`/`PointerTo` underlie every managed object in the engine, including all of `putil`, `pgraph`, and `mathutil`.

**Entry points.** Read `datagram.cxx`/`datagramIterator.cxx` to see byte packing; `virtualFileSystem.cxx` (`mount`, `get_file`, `find_file`) for asset resolution; `referenceCount.h`/`.I` + `pointerTo.h` for lifetime semantics; `multifile.cxx` for the archive format.

**Config variables** (`express/config_express.cxx`): `patchfile-window-size`, `patchfile-increment-size`, `patchfile-buffer-size`, `patchfile-zone-size`, `keep-temporary-files`, `multifile-always-binary`, `collect-tcp`, `collect-tcp-interval`, plus lazily-created `use-high-res-clock`, `paranoid-clock`, and `verify-dcast`.

---

## linmath

**What it is.** `panda/src/linmath` is Panda's linear-algebra library: 2/3/4-component vectors and points, 3×3/4×4 matrices, quaternions, and coordinate-system utilities. Its defining design choice is that it implements each type for both `float` and `double` (and partially `int`) **without C++ templates**, using a header-reincludes-with-different-macros trick.

**The dual-instantiation trick (read this first or the directory makes no sense).** Instead of templates, each type is written once in a `*_src.h`/`*_src.cxx` file using the macros `FLOATTYPE`/`FLOATNAME(x)`/`FLOATCONST(...)`. The public header (e.g. `lvecBase3.h`) includes `fltnames.h` then `lvecBase3_src.h`, then includes `dblnames.h` then `lvecBase3_src.h` again, then `intnames.h`. `fltnames.h` defines `FLOATTYPE=float` and `FLOATNAME(ARG)=ARG##f`, so `lvecBase3_src.h` expands once into `LVecBase3f` and again (via `dblnames.h`) into `LVecBase3d`. The header itself documents the rationale: it is "a poor man's template… to avoid some of the inherent problems with templates: compiler complexity and distributed code bloat… plus it allows us to implement if-based specialization on numeric type" — and notes VC++'s historically poor template support. **Consequence for contributors:** edit the `*_src.h`/`*_src.cxx` files, never the per-type generated wrappers, and remember a single edit affects both the `f` and `d` variants.

**Central classes and chain.** The base of the vector hierarchy is `LVecBase{2,3,4}` (`linmath/lvecBase3.h` etc.), the raw n-tuple. `LVector{2,3,4}` and `LPoint{2,3,4}` derive from the corresponding `LVecBase` to give *semantic* distinction (a vector transforms differently from a point under an affine matrix). `LMatrix3`/`LMatrix4` (`linmath/lmatrix.h` → `lmatrix3_src.h`, `lmatrix4_src.h`) are the matrices; `LQuaternion`/`LRotation`/`LOrientation` (`linmath/lquaternion.h`, `lrotation.h`, `lorientation.h`) are rotations. `PN_stdfloat` (float or double per build) determines whether the unsuffixed Python names map to the `f` or `d` instantiation. `LColor` is an alias for an `LVecBase4`.

**Coordinate system + helpers.** `coordinateSystem.h` defines the `CoordinateSystem` enum (`CS_zup_right`, `CS_yup_right`, `CS_zup_left`, `CS_yup_left`, `CS_default`); Panda's default is Z-up right-handed, and many transform operations take an optional `CoordinateSystem` argument so the engine can interoperate with Y-up tools. `compose_matrix`/`decompose_matrix` (`linmath/compose_matrix.h`) convert between a matrix and scale/shear/HPR/translate components. `deg_2_rad.h` holds angle conversions; `mathNumbers.h` holds constants; `configVariableColor.h` is a config-var type for colors.

**How it plugs in.** These types are the vocabulary of the entire engine: `NodePath::set_pos/hpr/mat`, `TransformState`, `Geom` vertex data, camera frustums, lighting, and physics all speak `LVecBase`/`LMatrix`/`LQuaternion`. `mathutil`'s bounding volumes and planes are built directly on them. They are serialized via `Datagram` (each `*_src.h` includes `datagram.h`/`datagramIterator.h`).

**Entry points.** Read `lvecBase3_src.h`/`.I` together with `fltnames.h`/`dblnames.h` until the macro expansion is clear; then `lmatrix4_src.h` for matrix ops and `lquaternion_src.cxx` for rotation math. `compose_matrix_src.cxx` is where transform decomposition (and its HPR conventions) live.

**Config variables** (`linmath/config_linmath.cxx`): `paranoid-hpr-quat` (extra validation when converting HPR↔quaternion) and `no-singular-invert` (controls behavior when inverting a singular matrix).

---

## mathutil

**What it is.** `panda/src/mathutil` builds geometric algorithms on top of `linmath`: the family of **bounding volumes** used for view-frustum culling and collision broad-phase, the `Plane`/`Frustum`/`Parabola` shapes, polygon triangulation, Perlin noise, a Mersenne-Twister RNG, and the FFT-based animation compressor.

**Central abstraction and inheritance chain.** The bounding-volume hierarchy is rooted at `BoundingVolume` (`mathutil/boundingVolume.h`, a `TypedReferenceCount`):

```
BoundingVolume
  -> GeometricBoundingVolume            (has a position in 3-space)
       -> FiniteBoundingVolume          (has finite extent)
            -> BoundingSphere
            -> BoundingBox
            -> BoundingHexahedron
       -> BoundingLine, BoundingPlane    (infinite extents)
  (plus OmniBoundingVolume, UnionBoundingVolume, IntersectionBoundingVolume)
```

`BoundingVolume` is abstract: subclasses implement `make_copy()`, `output()`, and the protected double-dispatch hooks. The `contains()` API returns a bitmask of `IF_no_intersection`/`IF_possible`/`IF_some`/`IF_all`/`IF_dont_understand`. **Design note worth understanding:** intersection and `extend_by` use *double dispatch* — `BoundingVolume::extend_by()` calls the virtual `extend_other()` on the argument, which calls back the type-specific `extend_by_sphere`/`extend_by_box`/… on `this`. This is why adding a new bounding-volume type means adding the matching `extend_by_*`/`contains_*`/`around_*` overrides across the existing types; the pairwise matrix is intentional, not accidental.

**Other key types.** `BoundingSphere` (`mathutil/boundingSphere.h`) and `BoundingBox` (`mathutil/boundingBox.h`) are the two volumes you meet most (each `PandaNode` keeps one). `Plane` (`mathutil/plane.h`, dual float/double like linmath) and the `Frustum` (`LFrustum`, `mathutil/frustum.h` → `frustum_src.h`) builds projection matrices and feeds culling. `Mersenne` (`mathutil/mersenne.h`) is the deterministic PRNG; `Randomizer` (`mathutil/randomizer.h`) wraps it. `PerlinNoise2`/`PerlinNoise3` and the `StackedPerlinNoise*` provide procedural noise. `Triangulator`/`Triangulator3` (`mathutil/triangulator.h`) tessellate polygons (used by text and procedural geometry). `FFTCompressor` (`mathutil/fftCompressor.h`) compresses animation channels. `look_at`/`rotate_to` (`mathutil/look_at.h`, `rotate_to.h`) build orientation matrices.

**How it plugs in.** Bounding volumes are the contract between `pgraph` and the cull traversal: `PandaNode::get_bounds()` returns a `BoundingVolume`, the `CullTraverser` tests it against the camera `Frustum`, and the collision system (`collide`) uses them for broad-phase. `bounds-type` (config) controls whether nodes default to sphere or box bounds. Everything here consumes `LPoint`/`LVecBase`/`LMatrix` from linmath. (Note: `BoundingVolume` is a `TypedReferenceCount`, not a `TypedWritable` — bounding volumes are not BAM/`Datagram`-serializable; in this directory only `FFTCompressor` and `Parabola` use datagrams.)

**Entry points.** Read `boundingVolume.cxx` plus `boundingSphere.cxx` and `boundingBox.cxx` to see the double-dispatch pattern concretely; `frustum_src.cxx` for projection-matrix construction; `triangulator.cxx` if you touch text/geometry tessellation. To add a bounding-volume type, mirror an existing subclass's full set of dispatch overrides.

**Config variables** (`mathutil/config_mathutil.cxx`): `bounds-type` (`best`/`sphere`/`box`/`fastest` — the default `BoundingVolume::BoundsType` for new nodes) and the FFT-compressor tuning knobs `fft-offset`, `fft-factor`, `fft-exponent`, `fft-error-threshold`.

---

## Where to start (this cluster)

A new contributor should read, in this order:

1. **`express/referenceCount.h` + `express/pointerTo.h`** — object lifetime. Nothing else makes sense until `PT()`/`CPT()`/`WeakPointerTo` are clear.
2. **`putil/typedWritable.h`** then **`putil/bamReader.h`/`bamReader.cxx`** + **`putil/bamWriter.cxx`**, alongside **`express/datagram.h`/`datagramIterator.h`** — the serialization stack end to end. Use a small existing class's `write_datagram`/`fillin`/`register_with_read_factory` as your worked example, and keep `putil/bam.h` open for the version rules.
3. **`pipeline/cycleData.h` + `pipeline/pipelineCycler.h` + `pipeline/cycleDataReader.h`/`cycleDataWriter.h`**, then **`pipeline/pipeline.cxx`** (`cycle`) and **`pipeline/pipelineCyclerTrueImpl.cxx`** — the copy-on-write threading model. Skim PR [#1853 (EBR)](https://github.com/panda3d/panda3d/pull/1853) before changing anything here.
4. **`event/eventHandler.cxx`** (event dispatch) and **`event/asyncTaskManager.cxx`/`asyncTaskChain.cxx`** (the task loop) — how per-frame work and messages actually run.
5. **`linmath/lvecBase3_src.h` with `fltnames.h`/`dblnames.h`** and **`mathutil/boundingVolume.cxx` + `boundingSphere.cxx`** — the math vocabulary and the bounding-volume double dispatch that the scene graph and culler depend on.

---

## Known shortcomings & footguns

The machinery above works as described, but three areas of this cluster account for the lion's share of recurring confusion: **object lifetime** (the C++/Python refcounting boundary built on `express`'s `ReferenceCount`/`PointerTo` and `putil`'s state caches), **threading** (what the `pipeline` cycler and the cooperative/true-threads back-ends actually guarantee), and **numeric precision** (the single-precision default of `linmath`). The entries below are community-sourced (forum threads, issues, maintainer comments) and are preserved as opinion/history, not re-derived. For the constructive background to all of them, keep [Cross-cutting concepts](../cross-cutting-concepts.md) open alongside this section.

**Memory, reference counting & object lifetime.** Almost every footgun in this first group stems from the C++/Python refcounting boundary that `express`'s `ReferenceCount`/`PointerTo` (see the **express** section above) and the broader refcount discussion in [Cross-cutting concepts](../cross-cutting-concepts.md) describe constructively.

### Five different cleanup methods — acknowledged bad design
**Severity: major · Status: by-design (admitted)**

To tear down an object you must call the *right* method for its type: `removeNode()` (NodePath), `destroy()` (DirectGUI), `cleanup()`/`delete()` (Actor), `removeTask()`, `ignoreAll()`. There is no uniform "destroy this." drwr concedes it is a genuine design flaw from organic evolution.

> "There should be only one method name for cleaning up all objects... Instead, we
> have cleanup(), destroy(), removeNode(), delete(), and maybe others, and you
> just have to know what kind of object you have... It's a problem... it wasn't
> designed like that; it evolved." — drwr *(maintainer)*,
> [t/5032](https://discourse.panda3d.org/t/5032)

### `setPythonTag(x, self)` / subclassing PandaNode creates an uncollectable cycle
**Severity: major · Status: by-design (manual `clearPythonTag`/weakrefs only)**

The standard idiom to recover a Python subclass from a NodePath — `np.setPythonTag('trueClass', self)` — creates a reference cycle (node → tag → Python object → node). Because the Python object wraps a C++ object, **Python's cyclic GC cannot collect it**; the node leaks forever unless you manually `clearPythonTag()`.

> "you have created a reference count loop... it will never be freed by Python's
> reference-counting mechanism. Worse... it will never be garbage collected
> either." — drwr *(maintainer)*, [t/2844](https://discourse.panda3d.org/t/2844)

### NodePaths cannot be weakly referenced
**Severity: minor · Status: by-design**

The clean fix for the cycle above would be a `weakref`, but `NodePath` (a C-extension type) can't be weakly referenced — `weakref.ref(NodePath())` raises `TypeError`. Users discover this only after their "fix" fails.

> "I'm attempting to provide a weak back-reference to a NodePath... It appears,
> however, that this is impossible." — Fixer, [t/1500](https://discourse.panda3d.org/t/1500)

### `self.accept(...)` registers `self` in the global messenger — invisible leak
**Severity: major · Status: by-design (mitigated by `ignoreAll()`)**

Any `DirectObject.accept('event', self.method)` stores a reference to `self` in the global messenger table (the scripting analogue of the `event` system's `EventHandler` hooks described above), so the object is never GC'd (and keeps firing handlers) until `ignore()`/`ignoreAll()` is called. One of the most common silent leaks.

> "if you call self.accept('blahblah', self.doodah), then you have created a
> circular reference count... so you have to break that reference by calling
> self.ignoreAll() eventually." — drwr *(maintainer)*, [t/11245](https://discourse.panda3d.org/t/11245)

### Storing a task handle on the object it spawns leaks the whole object
**Severity: major · Status: by-design**

`self.myTask = taskMgr.add(self.update, ...)` creates a cycle (task → method → self → task; see the `AsyncTask`/`PythonTask` discussion in the **event** section above). drwr personally root-caused a real user leak to exactly one stored pointer.

> "If you leave just one Pointer behind, that's a memory leak." — user, with drwr
> replying *"it's really a problem with Python more than Panda."* —
> [t/11209](https://discourse.panda3d.org/t/11209)

### `removeNode()` vs `detachNode()` — pervasive "it frees memory" myth
**Severity: major · Status: by-design (partially documented)**

`removeNode()` and `detachNode()` are *almost identical* — neither frees memory directly; the node is freed only when its C++ refcount hits zero (the `ReferenceCount`/`PointerTo` semantics from the **express** section). The widespread belief that `removeNode()` "deletes and frees" is wrong, and a single stray reference to any child keeps the whole branch alive.

> "'removeNode()'... This is not quite true. removeNode() does not clean up any
> memory. In fact, removeNode() and detachNode() are almost identical." — rdb
> *(maintainer)*, correcting another trusted user,
> [t/12955](https://discourse.panda3d.org/t/12955)

### Calling `removeNode()` on an Actor is wrong — must use `cleanup()`/`delete()`
**Severity: minor · Status: by-design (runtime warning)**

Actors retain animation/control handles; `removeNode()` leaves them dangling. A special-case lifetime rule on top of the already-confusing NodePath rules.

> "Never call removeNode on an actor, always use either actor.delete() or
> actor.cleanup()!" — rdb *(maintainer)*, [t/3421](https://discourse.panda3d.org/t/3421)

### The TransformState/RenderState cache looks like a leak; disabling it crashes
**Severity: major · Status: by-design (config knobs, each with sharp edges)**

State objects are interned in a global cache (the `CachedTypedWritableReferenceCount` machinery in the **putil** section above) that is purged at the end of each task step. A tight loop that never yields to the task loop (e.g. `while True: world.do_physics(...)`) accumulates entries indefinitely — indistinguishable from a leak (one user hit 70% of 8GB in minutes). The escape hatches each bite: `transform-cache 0` → **segfault** at `ShowBase` startup; `uniquify-transforms 0` → assertion errors/segfaults. Only `garbage-collect-states 0` was safe.

> "Normally, the transform cache is configured to purge itself at the end of each
> task step, which you are never reaching." — drwr *(maintainer)*,
> [t/13303](https://discourse.panda3d.org/t/13303)

### Caches that aren't leaks: geom/vertex-data cache, ModelPool, TexturePool
**Severity: minor · Status: by-design**

Several internal caches "allocate once, never free, just recycle," so removing models doesn't return RAM to the OS — the #1 false-positive "leak" report. `flattenStrong()` specifically duplicates vertex data that lingers in the cache. `loadModel`/`loadTexture` go through global pools that retain assets until you explicitly `unloadModel()`/`releaseAll...()`.

> "many of Panda's memory allocation schemes are designed to allocate memory once,
> but never free it. Instead, it gets recycled." — drwr *(maintainer)*,
> [t/7603](https://discourse.panda3d.org/t/7603)

### The architectural root: persistent C++↔Python wrapper identity
**Severity: major · Status: partially fixed (`tp_traverse` in #1640; edge cases remain)**

A C++ object and its Python wrapper don't share identity; making the C++ object hold its wrapper persistent creates an uncollectable cycle. This is the root cause behind the `setPythonTag` cycle above and PythonTask GC issues. rdb implemented a `tp_traverse`-based fix but flagged an unsolved weakref/threading edge case.

> "It would be convenient if Panda's C++ objects were consistently exposed to
> Python with the same instance... This would require the C++ object to hold onto
> a reference to said Python wrapper, though, creating a reference cycle that
> won't automatically be taken care of." — [#1410](https://github.com/panda3d/panda3d/issues/1410)

### `del` ≠ delete, and Panda holds hidden references
**Severity: minor · Status: by-design (inherent)**

> "The fundamental problem is that we are shoehorning two languages together, and
> pretending that it's all one language. This works well up to a point." — drwr
> *(maintainer)*, [t/6123](https://discourse.panda3d.org/t/6123)

There are "(mostly) no tools that can tell you which things are holding references to a given object."

### Manual `ref()`/`unref()` is a crash/leak footgun
**Severity: minor · Status: by-design (documented hazard)**

C++ users must store engine objects in `PT()`/`CPT()` smart pointers immediately or risk deletion underfoot (see the `PointerTo` discussion in the **express** section above); manually calling `ref()`/`unref()` "messes up Panda's internal bookkeeping, and will likely cause crashes and memory leaks" (official docs).

### A long tail of genuine engine leaks/use-after-frees (mostly fixed by rdb)
**Severity: individually minor, broad · Status: fixed**

The commit history shows a steady stream of *real* engine-side lifetime bugs rdb fixed — confirming this is genuinely bug-prone, not just user error: a double-free when a weak state pointer is locked during GC (#499), use-after-free with the transform cache disabled (#1733), Bullet persistent-manifold leak (#1193), SimpleHashMap leak (#1077), a per-frame leak on newer macOS (Metal autorelease), and the real DirectGuiWidget cycle (t/5032).

**Threading.** The next group maps directly onto the `pipeline` section above and the **PipelineCycler / Copy-on-Write** discussion in [Cross-cutting concepts](../cross-cutting-concepts.md) — read that constructive material first, then note where the guarantees stop.

### Panda is fundamentally single-threaded; SIMPLE_THREADS gives no parallelism
**Severity: major · Status: by-design**

The default cooperative SIMPLE_THREADS build (`threadSimpleImpl`, see the **pipeline** threading primitives above) plus the GIL means threads give concurrency, never CPU parallelism. A thread that fails to call `Thread.considerYield()` (or calls `time.sleep`) blocks *all* other threads.

> "Python does not support threading in the normal sense, because it uses a Global
> Interpreter Lock (GIL)... you shouldn't expect any performance gains from
> parallelism." — drwr *(maintainer)*, [t/7277](https://discourse.panda3d.org/t/7277)

> "naive use rarely gives any speed-up at all; usually, its use results in an
> overall performance penalty." — drwr *(maintainer)*, [t/7832](https://discourse.panda3d.org/t/7832)

### Default build is NOT compiled thread-safe — 2nd-thread calls crash
**Severity: major (historically blocker) · Status: mitigated (thread-safe builds shipped)**

The shipped Panda was deliberately built non-thread-safe (faster malloc, no per-op locking). Touching the scene graph/collision/intervals from a second thread "will certainly crash eventually" without an `HAVE_THREADS` recompile.

> "the current version of Panda as distributed on the website is not compiled to
> be thread-safe... you will certainly crash eventually." — drwr *(maintainer)*,
> [t/2206](https://discourse.panda3d.org/t/2206)

### The Interval system isn't thread-safe; "use a separate scene graph" doesn't help
**Severity: major · Status: by-design**

You must funnel all interval calls through one thread, and even unrelated scene graphs can't run in parallel because Panda keeps *global caches/tables* (the same state caches discussed under memory above) updated on any mutation.

> "There are some global caches and tables that Panda would keep updating... so
> even if you're mucking about in two unrelated scene graphs, you'll get
> [problems]." — drwr *(maintainer)*, [t/4409](https://discourse.panda3d.org/t/4409)

### `DO_PIPELINING` / `threading-model Cull/Draw` is experimental and deadlocks
**Severity: major · Status: still-open (experimental) / some deadlocks fixed**

Whether `DO_PIPELINING` is compiled in is a build-time decision (see the **pipeline** section), and the threaded cycler has a documented history of subtle bugs (PR [#1853](https://github.com/panda3d/panda3d/pull/1853) reworks reclamation precisely because it "has not been reliably thread-safe").

> "Be very careful when enabling DO_PIPELINING... The pipelining support in Panda
> is incomplete and experimental. It is likely to fail to compile, crash,
> deadlock, or destroy your favorite childhood toy." — drwr *(maintainer)*,
> [t/7429](https://discourse.panda3d.org/t/7429)

Async model/texture loading under multithreaded rendering readily deadlocks ([#217](https://github.com/panda3d/panda3d/issues/217)); modifying geometry in another thread freezes the app ([#1033](https://github.com/panda3d/panda3d/issues/1033)); there was an acknowledged deadlock with the shadow system ([#162](https://github.com/panda3d/panda3d/issues/162)).

### `time.sleep()` in a cooperative thread stalls *everything*
**Severity: major · Status: by-design under SIMPLE_THREADS**

`time.sleep()` inside a Panda thread blocks ALL cooperative threads (and produced a silent crash in one report). Use `Thread.considerYield()`/Panda sleep instead.

### `sync-video` is only a request; "limited" clock mode isn't steady
**Severity: minor · Status: by-design / driver-limited**

`sync-video 1` only *requests* vsync (drivers can ignore it); the `clock-mode limited` alternative (a `ClockObject` mode — see `ClockObject` in the **putil** section above) busy-waits and "doesn't tend to result in a very steady frame rate." No robust cross-platform fixed-timestep guarantee.

**Numeric precision.** The last two map onto `linmath`: every vertex, transform, and matrix above is a `PN_stdfloat`, which is single-precision in the default build.

### Single-precision vertices/transforms — the large-world / far-from-origin limit
**Severity: major · Status: by-design (double-precision build available)**

Vertices, transforms, and camera/projection matrices are single-precision (the GPU demands it; this is the `PN_stdfloat = float` default of the **linmath** section above), so objects far from the origin (~10⁵+ units) get visibly jerky/jittery as low-order digits truncate. The standard fix is a floating-origin design; a double-precision recompile helps for the CPU-side math.

> "the single-precision floats used by Panda (and by your graphics hardware)... have
> only got about 5 or 6 digits of precision... It's usually better to keep all of
> your numbers within a few thousand of zero." — drwr *(maintainer)*,
> [t/7288](https://discourse.panda3d.org/t/7288)

> "Welcome to the wonderful world of limited floating point precision... a common
> issue when you have objects far far away from the origin." — eldee, with the
> reporter confirming *"Recompiling with double made everything butter smooth."* —
> [t/26403](https://discourse.panda3d.org/t/26403)

### Opening a window can force the FPU into single-precision mode (driver bug)
**Severity: minor · Status: mostly-fixed-in-1.7.1 (driver-dependent)**

On some DirectX/OpenGL configs, creating a graphics context forced the whole process FPU into single-precision mode, so even *Python's* local doubles silently lost precision.

> "the act of opening a window and creating a graphics context forces your FPU into
> single-precision mode, so that everything becomes single-precision, even your
> local Python variables." — drwr *(maintainer)*, [t/11247](https://discourse.panda3d.org/t/11247)
