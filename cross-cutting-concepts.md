# Cross-cutting concepts

Before you can sensibly read or modify *any* Panda3D cluster, you need to recognize five patterns that recur in nearly every header in the tree.

---

## 1. TypeHandle / RTTI — Panda's hand-rolled type system

**What it is.** Panda does not trust C++ `typeid`/`dynamic_cast`. Instead, every class that needs runtime type identification carries a static `TypeHandle`, which is *just an integer index* into a single process-wide `TypeRegistry`. The registry stores the name, the parent/child links, and (optionally) the associated Python type for each registered class. This is the foundation the other four patterns lean on: serialization dispatch, downcasting, and Python wrapping all key off the `TypeHandle`.

**Key files / classes / macros.**
- `dtool/src/dtoolbase/typeHandle.h` — `class TypeHandle final`; it wraps a single `int _index` and offers `get_name()`, `is_derived_from()`, `get_index()`, plus the sentinel values `TypeHandle::none()` (index 0) and `TypeHandle::invalid()` (index -1).
- `dtool/src/dtoolbase/typeRegistry.h` — `class TypeRegistry`, the single global tree. `TypeRegistry::ptr()` returns the singleton; `register_type()`, `record_derivation()`, `find_type()`, and `is_derived_from()` live here.
- `dtool/src/dtoolbase/typedObject.h` — `class TypedObject`, the abstract base that adds the virtual `get_type()`, plus inline `is_of_type()` / `is_exact_type()` and the `force_init_type()` hook.
- `dtool/src/dtoolbase/register_type.h` — the overloaded `register_type(TypeHandle &, name, parent1…parent4)` convenience functions and the `get_type_handle(type)` / `do_init_type(type)` template helpers.
- `panda/src/express/dcast.h` (+ `dcast.T`) — the `DCAST`, `DCAST_INTO_V`, `DCAST_INTO_R` macros.

**How it works.** Every type follows a fixed boilerplate (the header comment in `typedObject.h` literally warns you to keep the formatting identical so `sed` scripts can rewrite it en masse). In the `.h`:

```cpp
static TypeHandle get_class_type() { return _type_handle; }
static void init_type() {
  BaseClass::init_type();
  register_type(_type_handle, "MyClass", BaseClass::get_class_type());
}
virtual TypeHandle get_type() const { return get_class_type(); }
virtual TypeHandle force_init_type() { init_type(); return get_class_type(); }
private:
  static TypeHandle _type_handle;
```

and in the `.cxx` exactly one line: `TypeHandle MyClass::_type_handle;`. The static `_type_handle` starts as `TypeHandle::none()` (index 0) because static-initialization order is unspecified — see the comment in `typeHandle.h` explaining the default constructor must do nothing. At startup each library's config function (the `ConfigureFn` / `init_libX()` shown in `typedObject.h`) calls every class's `init_type()`, which calls `register_type()`, which asks the `TypeRegistry` to hand out the next free integer and record the parent links. From then on, `obj->get_type()` returns that integer and `is_of_type(handle)` (in `typedObject.I`) is a near-free integer compare with a fall-through to `TypeRegistry::is_derived_from()` walking the recorded derivation tree.

**How DCAST works.** `DCAST(MyType, ptr)` expands (via `dcast.h`) to `_dcast((MyType*)0, ptr)`. In `dcast.T`, `_dcast` calls `_dcast_verify(want_handle, sizeof(WantType), ptr)`, which checks `ptr->is_of_type(want_handle)` *before* doing the C-style downcast; on failure it returns `nullptr` instead of corrupting memory. Under `NDEBUG` (`DO_DCAST` undefined) the check compiles away to a raw cast, so DCAST is safe in debug and fast in release. `DCAST_INTO_V` / `DCAST_INTO_R` additionally `nassert` and early-return. This is why you almost never see a bare `dynamic_cast` in Panda — downcasting is funneled through `get_type()`.

**Why it's built this way.** Panda predates reliable, portable C++ RTTI and still has to solve problems `typeid` cannot:
- **Cross-DLL identity.** `type_info` objects are not guaranteed comparable across shared-library boundaries on every platform; a process-wide integer registry is. (`TypeRegistry`'s comment even anticipates migrating to shared memory.)
- **Python integration.** `TypeRegistry::record_python_type()` and `TypeHandle::wrap_python()` map a C++ type to its `PyTypeObject`, so a returned C++ pointer can be wrapped as the *correct* Python subclass. `typeid` gives you nothing here.
- **Serialization dispatch.** The `.bam` factory (concept 3) reconstructs objects keyed by `TypeHandle`. You need a stable, serializable type id — an integer the registry controls, not a compiler-private symbol.
- **Optional cost.** A class can declare a `TypeHandle` *without* inheriting `TypedObject`, avoiding even one vtable slot, when virtual `get_type()` isn't needed (see `ThatThingie` in the `typeHandle.h` example).

**Where to look / gotchas.** If `get_type()` returns `TypeHandle::none()`, the class's `init_type()` never ran — that's the symptom of a missing `init_type()` call in a library's config function, and it's exactly what `force_init_type()` exists to repair on the fly. The `TypeRegistry` is mutex-guarded (`MutexImpl _lock`) but derivations are cached lazily (`_derivations_fresh`/`rebuild_derivations()`), so adding types after startup is legal but triggers a rebuild. See the **dtool** subsystem page for where these headers sit in the library stack, and the **scene-graph** page for how `PandaNode` and friends use DCAST pervasively.

---

## 2. Reference counting & PointerTo<T> — intrusive memory management

**What it is.** Panda manages heap object lifetime with *intrusive* reference counting: the count lives **inside** the object (a base class `ReferenceCount`), and smart-pointer templates `PointerTo<T>` / `ConstPointerTo<T>` increment it on copy and decrement on destruction, deleting the object when the count hits zero. It is Panda's `shared_ptr`, but hand-rolled and older.

**Key files / classes / macros.**
- `panda/src/express/referenceCount.h` — `class ReferenceCount : public MemoryBase`; the count is `mutable patomic<int> _ref_count` plus a `patomic<WeakReferenceList *> _weak_list`. Public API: `ref()`, `unref()`, `get_ref_count()`, `weak_ref()`/`weak_unref()`, and the helper `unref_delete()`.
- `panda/src/express/pointerTo.h` — `template <class T> class PointerTo` and `ConstPointerTo`, both deriving from `PointerToBase<T>`. The abbreviation macros: `#define PT(type) PointerTo< type >` and `#define CPT(type) ConstPointerTo< type >`.
- `panda/src/express/typedReferenceCount.h` — `class TypedReferenceCount : public TypedObject, public ReferenceCount`. This is the everyday base for "an object that is both type-identified and refcounted."
- `panda/src/express/weakPointerTo.h`, `weakReferenceList.h` — `WeakPointerTo<T>` and the shared `WeakReferenceList`.

**How it works.** `ref()` does an atomic `_ref_count.fetch_add(1, relaxed)`; `unref()` does `fetch_sub(1, release)` and returns whether the new count is nonzero (`referenceCount.I`). Critically, `unref()` **does not delete** — a member function deleting `this` is hazardous — so the actual delete happens in `PointerTo`'s destructor / `unref_delete()` once `unref()` reports zero. `PointerTo<T>` overloads `operator*`, `operator->`, and `operator T*()` so it behaves like a raw pointer (`pointerTo.h`), and offers `.p()` to skip a double-cast when downcasting. The const-ness convention is spelled out in `pointerTo.h`: `ConstPointerTo<X>` ≈ `const X *` (can re-point, can't mutate), whereas `const PointerTo<X>` ≈ `X * const` (can mutate, can't re-point).

`ReferenceCount` also bakes in a debug safety net: a fresh object starts at count 0; the destructor (`referenceCount.I`) `nassert`s the count is 0 or `local_ref_count`, then stores the poison value `deleted_ref_count` (-100) so a stray `PointerTo` to freed memory trips an assertion instead of silently corrupting. `local_object()` sets a huge sentinel count (`local_ref_count = 10000000`) so you may legally put a refcounted object on the stack and pass it to functions that ref/unref it without it being deleted out from under you.

**WeakPointerTo.** `WeakPointerTo<T>` (`weakPointerTo.h`) does **not** keep the object alive. The first weak reference lazily creates a `WeakReferenceList` (`referenceCount.h::get_weak_list()`), shared by all weak pointers to that object. On destruction `ReferenceCount` calls `weak_list->mark_deleted()`, so `was_deleted()` becomes true and `lock()` safely returns a null `PointerTo`. This is the tool for **breaking reference cycles** (e.g. a child that needs to see its parent without keeping it alive).

**Why it's built this way.**
- **Predates C++11.** `std::shared_ptr` didn't exist when this was written; the design is from the late 1990s (`@date 1998-10-23`).
- **Cache locality / size.** An intrusive count is one word inside the object — no separate control block, no second allocation, and the pointer is exactly one machine word (vs. `shared_ptr`'s two). Sorting a `pvector<PT(X)>` doesn't touch any control blocks.
- **Cross-language.** The same count that C++ uses is the count Python participates in (see below), so an object can be co-owned by both worlds with one mechanism.
- **Atomic but optional.** `patomic<int>` makes ref/unref thread-safe for the render pipeline (concept 4) without a per-object lock.

**Where to look / gotchas.**
- **Never `new`+raw-pointer a `ReferenceCount` subclass and let it leak or double-free** — assign it to a `PT()` immediately. The poison-value assertions in `~ReferenceCount` exist precisely because people forget.
- **Stack-allocating a `ReferenceCount` subclass** and pointing a `PT()` at it will try to `delete` a stack address — call `local_object()` or just don't.
- **The Python footgun.** When you subclass `PandaNode` in Python or call `node.set_python_tag(key, value)` (the `PY_EXTENSION set_python_tag` in `pandaNode.h`), Python holds a reference to the C++ object *and* the C++ object holds a reference back to the Python object/tag. That's a cross-language cycle the C++ refcounter and Python's GC each only see half of, so it never collects. Break it explicitly (clear the tag, use a weak reference) — this is the single most common memory leak in Panda Python code. See the **direct-python-framework** and **dtool** pages.

---

## 3. Datagram / BamReader / BamWriter — `.bam` serialization & versioning

**What it is.** Panda's universal binary serialization layer. A `Datagram` is a growable binary blob you append typed fields to; `BamWriter`/`BamReader` walk an object graph, ask each object to write/read *itself*, and patch up inter-object pointers by id. The same machinery backs `.bam` model files, the on-disk model cache, and network object transmission.

**Key files / classes / macros.**
- `panda/src/express/datagram.h` — `class Datagram : public TypedObject`. You call `add_bool`, `add_int32`, `add_float64`, `add_string`, `add_stdfloat`, etc. (default little-endian; `add_be_*` for big-endian). The bytes live in a `PTA_uchar _data`.
- `panda/src/express/datagramIterator.h` — `DatagramIterator`, the read cursor with matching `get_int32()`, `get_string()`, … in the same field order.
- `panda/src/putil/typedWritable.h` — `class TypedWritable : public TypedObject`. The two virtuals every serializable class overrides: `write_datagram(BamWriter *, Datagram &)` and `fillin(DatagramIterator &, BamReader *)`. Plus `complete_pointers()` for the pointer-patching pass and `finalize()`.
- `panda/src/putil/bamReader.h`, `bamWriter.h` — the graph walkers. `BamReader` defines `typedef Factory<TypedWritable> WritableFactory` and the static `register_factory()` / `get_factory()`.
- `panda/src/putil/bam.h` — the magic number and version constants (see below).
- `panda/src/putil/factory.h` — the generic `Factory<Type>` keyed by `TypeHandle`.

**How it works (the round trip).** Writing: `BamWriter::write_object()` looks at an object's `TypeHandle`, writes it (once) along with a fresh **object id**, then calls the object's `write_datagram()`. Inside `write_datagram()` the object serializes its own scalar fields into the `Datagram` and, for any pointer to another `TypedWritable`, calls `manager->write_pointer()` — which records the referenced object's id rather than the raw pointer. PandaNode is the canonical example (`pandaNode.cxx`):

```cpp
void PandaNode::write_datagram(BamWriter *manager, Datagram &dg) {
  TypedWritable::write_datagram(manager, dg);   // chain to base
  dg.add_string(get_name());
  manager->write_cdata(dg, _cycler);            // its CycleData (concept 4)
}
```

Reading is the mirror image driven by the **factory**. Each class registers itself once:

```cpp
void PandaNode::register_with_read_factory() {
  BamReader::get_factory()->register_factory(get_class_type(), make_from_bam);
}
TypedWritable *PandaNode::make_from_bam(const FactoryParams &params) {
  PandaNode *node = new PandaNode("");
  DatagramIterator scan; BamReader *manager;
  parse_params(params, scan, manager);
  node->fillin(scan, manager);   // read fields back in the same order
  return node;
}
```

When `BamReader` hits an object id in the stream it reads the `TypeHandle`, looks up the registered `make_from_bam` in the `WritableFactory`, and calls it. `fillin()` reads the scalars and registers each pointer-by-id with `manager->read_pointer()`. Because objects may be read before the objects they point to, the actual pointers are resolved in a second pass: once all referenced objects exist, `BamReader` calls `complete_pointers(p_list, manager)` so each object can store the now-resolved pointers, and finally `finalize()`. This two-phase (read fields → complete pointers) design is what lets a `.bam` file encode an arbitrary cyclic object graph as a flat list.

**Versioning.** `bam.h` holds the format identity, and these are the **current real values in this tree**:

```cpp
inline const std::string _bam_header{"pbj\0\n\r", 6};  // magic number
inline constexpr unsigned short _bam_major_ver = 6;
inline constexpr unsigned short _bam_first_minor_ver = 14;
inline constexpr unsigned short _bam_last_minor_ver = 46;
inline constexpr unsigned short _bam_minor_ver = 46;
```

The magic `pbj\0\n\r` includes CR/LF so corruption from text-mode file transfers is detected. **Major** version bumps are breaking (major 6 since 2006-02-11, "factor out PandaNode::CData"); **minor** bumps are backward-compatible additions. The file records the writer's version; `fillin()` methods branch on `manager->get_file_minor_ver()` to read old layouts. The long changelog comments in `bam.h` (minor 14 → 46, the latest being 2025-08-03 adding `ModelRoot::_loader_type`) document exactly which field each minor version introduced — read them when you add a serialized field, and bump `_bam_minor_ver` accordingly.

**Why it's built this way.** A single serialization format for files, cache, *and* network means model loading, the disk cache, and `TypedWritable::encode_to_bam_stream()` (in-memory pickling, also the basis of Python `__reduce__`) all share one tested codepath. Keying reconstruction off `TypeHandle` (concept 1) rather than C++ constructors is what makes it extensible across DLLs and from custom classes — register a factory and your type is `.bam`-serializable.

**Where to look / gotchas.** Field order in `write_datagram()` and `fillin()` **must match exactly**, including the chained base-class call first. If you add a field, you must (a) bump `_bam_minor_ver`, (b) guard the read with a version check so old files still load, and (c) leave the write unconditional. Forgetting `register_with_read_factory()` yields a "unknown type in bam file" failure at load. See the **egg** and **pandatool** pages (model conversion to `.bam`) and the **devices-and-networking** page (the same Datagrams over sockets).

---

## 4. PipelineCycler / Copy-on-Write — the threaded render pipeline

**What it is.** Panda can run its render loop as a software pipeline of stages — classically **App → Cull → Draw** — on separate threads. The problem: the Cull thread must read a *stable, consistent* snapshot of the scene graph while the App thread is busy mutating it for the next frame. The solution is the `PipelineCycler`: per-object state lives in a `CycleData` page, and the cycler keeps one copy **per pipeline stage**, copy-on-write, so each stage reads its own immutable snapshot. This is widely considered the hardest concept in the engine.

**Key files / classes / macros.**
- `panda/src/pipeline/cycleData.h` — `class CycleData`. You subclass it to hold the per-stage state. Note it inherits `NodeReferenceCount` *only when* `DO_PIPELINING` is defined; otherwise it's a plain `MemoryBase` stored inline. Its key virtual is `make_copy()` (used for the copy-on-write).
- `panda/src/pipeline/pipelineCycler.h` — `template<class CycleDataType> struct PipelineCycler : public PipelineCyclerBase`. The accessors: `read()`, `write()`, `read_stage()`, `write_stage()`, `elevate_read()`.
- `panda/src/pipeline/pipelineCyclerBase.h` — typedef selecting the implementation by build flags: `PipelineCyclerTrueImpl` (THREADED_PIPELINE), `PipelineCyclerDummyImpl` (DO_PIPELINING, no threads — self-validating), or `PipelineCyclerTrivialImpl` (neither — zero overhead).
- `panda/src/pipeline/cycleDataReader.h`, `cycleDataWriter.h` (and `…StageReader/Writer`, `…LockedReader`) — the RAII accessor wrappers.
- `panda/src/putil/copyOnWriteObject.h` — `class CopyOnWriteObject : public CachedTypedWritableReferenceCount`, the related COW base for large shared assets (e.g. geometry), with `make_cow_copy()` and `get_read_pointer()`/`get_write_pointer()`.

**How it works.** A class that needs pipelined state declares a nested `CData : public CycleData`, a `PipelineCycler<CData> _cycler` member, and a set of accessor typedefs. `PandaNode` is the textbook case (`pandaNode.h`):

```cpp
class CData : public BoundsData { ... virtual CycleData *make_copy() const; ... };
PipelineCycler<CData> _cycler;
typedef CycleDataReader<CData>      CDReader;
typedef CycleDataWriter<CData>      CDWriter;
typedef CycleDataStageReader<CData> CDStageReader;
typedef CycleDataStageWriter<CData> CDStageWriter;
```

**The read cycle.** To read, construct a `CDReader cdata(_cycler);` (`cycleDataReader.h`). It calls `_cycler.read_unlocked(current_thread)`, stashing a `const CData *` for the current thread's pipeline stage, and overloads `operator->` so `cdata->_some_field` reads that stage's snapshot. It's `const` throughout — a reader can never mutate. When `cdata` goes out of scope its destructor releases the pointer. Because each stage holds its own copy, the Cull thread reading stage 1 is completely insulated from the App thread writing stage 0.

**The write cycle.** To mutate, construct a `CDWriter cdata(_cycler);` (`cycleDataWriter.h`). Under the hood `_cycler.write(thread)` does the **copy-on-write**: if this stage still shares its `CData` page with a downstream stage, it calls `CData::make_copy()` to fork a private, writable copy first, so your edits don't retroactively change a snapshot another thread is mid-read on. You then write through `cdata->_some_field = …;` and the destructor publishes it.

**Cycling.** Once per frame `Pipeline::cycle()` advances every cycler: stage *N*'s data moves to stage *N+1* (App's just-finished frame becomes Cull's input, Cull's becomes Draw's), and the tail copy is retired. So at any instant App, Cull, and Draw each see a different, internally consistent generation of the scene.

**`DO_PIPELINING` is a compile flag** because all of this has a cost. When it's off, `PipelineCycler` (`pipelineCycler.h`) stores the `CycleDataType _typed_data` **directly inline** with no pointer and no copy, the `PipelineCyclerTrivialImpl` is selected, and `CDReader`/`CDWriter` collapse to thin wrappers around a single pointer. The whole abstraction compiles away to near-zero overhead in a single-threaded build, which is why the accessor classes hide their internals from interrogate (`#ifndef CPPPARSER`) and why the code is so disciplined about going through readers/writers — that discipline is exactly what makes the no-op build correct.

**Why it's built this way.** Lock-free reads. Rather than locking the scene graph while Cull traverses it (which would serialize App and Cull), each thread reads an immutable snapshot and the only synchronization is the once-per-frame `cycle()`. Copy-on-write means unmodified data is *shared* (one `CData` referenced by several stages) and only forked when actually written — most nodes don't change every frame, so most pages are never copied. The `NodeReferenceCount`-vs-`MemoryBase` split in `cycleData.h` exists precisely so the refcounting needed to share pages between stages is present only when pipelining is compiled in.

**Where to look / gotchas.** Never cache a raw `CData *` across frames — it's only valid for the lifetime of its `CDReader`/`CDWriter` and only for the current stage. Holding a `CDWriter` longer than necessary forces copies and serializes threads. To touch stages other than the current one (e.g. propagating a change upstream), use `CDStageWriter`/`write_stage()` and the `OPEN_ITERATE_*_STAGES` macros from `pipelineCycler.h`. See the **scene-graph** page for how `PandaNode`, `TransformState`, and `RenderState` use cyclers, and the **display-and-gsg** page for the Draw stage.

---

## 5. Interrogate — automatic Python binding generation

**What it is.** Almost every C++ class in Panda is usable from Python without anyone hand-writing a binding. A build-time tool called **interrogate** parses the C++ headers, finds everything marked for export, and emits C++ glue that exposes those classes/methods as a CPython extension module. The single most visible artifact in the headers is the `PUBLISHED:` access specifier.

**Note on this tree.** The interrogate *parser tool itself* (and its C++ parser) has been moved out of this repository into the separate `panda3d-interrogate` project — you can confirm it here: `dtool/src/interrogate` and `dtool/src/cppparser` **do not exist** in this checkout. What remains is the **runtime** support every binding links against, under `dtool/src/interrogatedb/`.

**Key files / classes / macros.**
- `dtool/src/dtoolbase/dtoolbase_cc.h` — where `PUBLISHED` is `#define`d. There are two definitions: when the interrogate pass is running (`CPPPARSER` defined) it becomes the custom keyword `__published`; in a normal compile it becomes plain `public`:
  ```cpp
  #define PUBLISHED __published   // during interrogate's parse
  #define PUBLISHED public        // during the real C++ compile
  ```
  So `PUBLISHED:` is invisible to your C++ compiler (it's just `public`) but is a flag interrogate keys on. Related markers in the same area: `PY_EXTENSION(...)`, `EXTENSION(...)`, `MAKE_PROPERTY(...)`, `MAKE_SEQ(...)`, `BLOCKING`, `EXPCL_*` — all noise to the compiler, all meaningful to interrogate.
- `dtool/src/interrogatedb/interrogate_request.h` — the C-level entry points by which a generated module registers its interrogate database at import time.
- `dtool/src/interrogatedb/py_panda.h` (+ `py_panda.I`, `py_compat.h`) — the CPython wrapper layer (below).

**How it works (build flow).** During the build (driven by `makepanda` or CMake), interrogate is run over each library's headers with `CPPPARSER` defined, so it sees `__published`/`__extension` etc. It records every `PUBLISHED:` class, method, property, and enum into an interrogate database and emits a generated `*_igate.cxx` of CPython glue plus a per-module init. Those generated files are compiled and linked into the Python extension modules (`panda3d.core`, etc.). At `import` time the module registers its database (`interrogate_request.h`) and builds the Python type objects. The C++ compiler proper never sees `__published` — `PUBLISHED` is just `public` to it — so the *same* headers serve both the parse pass and the real compile.

**The wrapper structs.** Every Panda object exposed to Python is a CPython object whose layout is `Dtool_PyInstDef` (`py_panda.h`):

```cpp
struct Dtool_PyInstDef {
  PyObject_HEAD
  struct Dtool_PyTypedObject *_My_Type;  // points to the class wrapper
  void *_ptr_to_object;                  // the actual C++ object
  unsigned short _signature;             // == PY_PANDA_SIGNATURE; marks "this is a Panda object"
  bool _memory_rules;                    // do we own/unref the pointer?
  bool _is_const;
};
```

and each wrapped C++ class has one `Dtool_PyTypedObject`:

```cpp
struct Dtool_PyTypedObject {
  PyTypeObject _PyType;                 // a real Python type
  TypeHandle _type;                     // ties it back to concept 1's registry
  ModuleClassInitFunction _Dtool_ModuleClassInit;
  UpcastFunction _Dtool_UpcastInterface;   // up-cast in the C++ hierarchy
  WrapFunction _Dtool_WrapInterface;       // wrap a C++ ptr as the right Py subclass
  CoerceFunction _Dtool_ConstCoerce, _Dtool_Coerce;
};
```

The macro `DtoolInstance_Check(obj)` verifies `_signature == PY_PANDA_SIGNATURE`; `DtoolInstance_VOID_PTR(obj)` recovers the C++ pointer; `DtoolInstance_UPCAST` walks the hierarchy. Note the explicit tie-in to the other concepts: `_type` is a `TypeHandle` (concept 1, used to wrap a returned base pointer as its true Python subclass), and `_memory_rules` is how the wrapper participates in `ReferenceCount` (concept 2) so Python's refcount and Panda's refcount stay in sync.

**The dual camelCase / snake_case API.** Panda's C++ uses `snake_case` (`set_pos`, `get_num_children`). Historically the Python API was `camelCase` (`setPos`). Interrogate is what generates *both* names for each published method (and `getNumChildren`/`get_num_children` both resolve to the same wrapper), which is why old tutorials use `nodePath.setPos(...)` while the C++ and modern Python both use `set_pos`. That dual binding is an interrogate feature, not duplicated source.

**Why it's built this way.** Hand-writing and maintaining bindings for thousands of methods across a moving API is infeasible; generating them from the headers means the Python API tracks the C++ API automatically, and only an access specifier (`PUBLISHED:`) decides what's exposed. Routing wrapping through `TypeHandle` lets a function declared to return a base-class pointer hand Python back the *most-derived* wrapper type, and routing ownership through `_memory_rules` + `ReferenceCount` lets a single object be co-owned by C++ and Python safely.

**Where to look / gotchas.** To expose a new method to Python you put it under a `PUBLISHED:` specifier — that's usually all it takes. Methods that need a Python-only signature (taking/returning `PyObject *`) are marked `PY_EXTENSION`/`EXTENSION` and implemented in a separate `*_ext.cxx` (e.g. `PandaNode::set_python_tag` in `pandaNode.h`) so the core class stays Python-free. Because the parser tool lives in `panda3d-interrogate`, changes to *binding generation behavior* (as opposed to runtime glue) are made in that repo, not here. See the **dtool** subsystem page for the library layout and the **direct-python-framework** page for how the generated `panda3d` modules are consumed.

---

### How the five fit together

These concepts compose, and you'll see them stacked in almost every header:

- `TypedReferenceCount` = **TypedObject** (concept 1) + **ReferenceCount** (concept 2) — the workhorse base class.
- `TypedWritable` (concept 3) is a `TypedObject`; the `.bam` factory reconstructs objects keyed by their **TypeHandle** (concept 1).
- `CycleData` (concept 4) becomes a `NodeReferenceCount` (concept 2) when pipelining is on, and its `write_datagram`/`fillin` plug straight into the **bam** system (concept 3).
- `PUBLISHED:` (concept 5) decorates classes that are usually `TypedReferenceCount`s, and interrogate's `Dtool_PyTypedObject` carries a **TypeHandle** (concept 1) and obeys **reference counting** (concept 2) via `_memory_rules`.

Recognize these five and the per-cluster chapters become a matter of *which* `TypedWritable`s exist, *what* their `CData` holds, and *which* methods are `PUBLISHED` — the mechanics are always the same.
