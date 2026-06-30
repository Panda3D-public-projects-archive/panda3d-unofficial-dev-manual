# direct (Python show framework)

The `direct` tree is Panda3D's Python-facing application framework: a thin, event-driven object layer that bootstraps a window and scene graph, schedules per-frame work, animates characters and properties, drives UI, and (in the Disney lineage) replicates objects across a network. Almost every class here is a Python wrapper over a C++ core type — `ShowBase` orchestrates `GraphicsEngine`/`AsyncTaskManager`, `Actor` wraps `Character`/`PartBundle`, the interval Python classes subclass `CInterval`, `DirectGui` wraps `PGItem`, and `ConnectionRepository` subclasses `CConnectionRepository`. Three patterns recur everywhere and are worth internalizing before reading any single subsystem: (1) **global singletons** written into Python builtins by `ShowBase` (`base`, `taskMgr`, `messenger`, `render`, `loader`, `ivalMgr`); (2) **`DirectObject` inheritance**, which gives any class `accept()`/`addTask()` sugar over the messenger and task manager; and (3) the **`config_*.cxx` registration** of `ConfigVariable*` tuning knobs read by both C++ and Python. The C++ halves of these subsystems live under the same directories (e.g. `direct/src/interval/cInterval.cxx`, `direct/src/distributed/cConnectionRepository.cxx`), compiled into `panda3d.direct`.

## showbase

**What it is.** The application bootstrap and foundation layer. `ShowBase` opens the graphics window, builds the 2-D and 3-D scene graphs, wires up input devices, installs the per-frame task loops, and publishes the well-known globals. Instantiating it (`base = ShowBase()`) is what turns a bare Python process into a running Panda app. The directory also holds the foundational utility classes that the rest of `direct` depends on: `DirectObject`, `Messenger`, `Loader`, `EventManager`, plus a large grab-bag of debugging/profiling tools (`GarbageReport`, `ContainerLeakDetector`, `OnScreenDebug`, `BufferViewer`).

**Key classes and roles.**
- `ShowBase` — `direct/src/showbase/ShowBase.py` (~3550 lines). Subclasses `DirectObject` so it can hang hooks on `window-event`. Holds `self.graphicsEngine` (`GraphicsEngine.getGlobalPtr()`), `self.win`, `self.render`/`self.render2d`/`self.aspect2d`/`self.pixel2d`, `self.cam`/`self.camera`, `self.cTrav` (collision traverser), `self.taskMgr`, `self.loader`, `self.eventMgr`, `self.messenger`. Major setup methods: `makeDefaultPipe()`, `openDefaultWindow()`/`openMainWindow()`, `setupRender()`, `setupRender2d()`, `setupRender2dp()`, `setupDataGraph()`, `setupMouse()`, `makeCamera()`.
- `DirectObject` — `direct/src/showbase/DirectObject.py`. The base class for "anything that responds to events." Provides `accept`/`acceptOnce`/`ignore`/`ignoreAll` (forwarding to the global `messenger`) and `addTask`/`doMethodLater`/`removeAllTasks` (forwarding to `taskMgr`, tagging the task `owner=self`). Tracks per-object tasks in `self._taskList` and listening state for leak detection (`detectLeaks()`).
- `Messenger` — `direct/src/showbase/Messenger.py`. The Python event bus. Nested dict `eventName -> {objMsgrId -> [method, extraArgs, persistent]}` plus a reverse `objMsgrId -> set(eventNames)` for fast `ignoreAll`. Thread-safe via a `direct.stdpy.threading.Lock`; supports cross-task-chain delivery through `_eventQueuesByTaskChain`. The singleton is `MessengerGlobal.messenger`.
- `EventManager` — `direct/src/showbase/EventManager.py`. Bridges the **C++** `EventQueue`/`EventHandler` to the Python `Messenger`: its `processEvents()` drains the C++ queue each frame and re-throws into `messenger`. Singleton in `EventManagerGlobal.eventMgr`.
- `Loader` — `direct/src/showbase/Loader.py`. `DirectObject` wrapper over the C++ `Loader` (`PandaLoader.getGlobalPtr()`, stored as `self.loader`). `loadModel()` accepts sync or async (`callback=`/`blocking=False`, returns a future-like `_Callback`), plus `loadFont`, `loadTexture`, `loadSfx`/`loadMusic`, `asyncFlattenStrong`.
- Support/utility: `BulletinBoard` (a global key/value store with change events), `Audio3DManager`, `SfxPlayer`, `Transitions` (fades/iris), `PythonUtil` (huge utility module imported widely), `Factory`, `JobManager`/`Job` (time-sliced cooperative jobs), and the debug suite (`GarbageReport`, `ObjectReport`, `ContainerLeakDetector`, `OnScreenDebug`, `BufferViewer`).

**How it plugs in.** `ShowBase.__init__` writes the globals into `builtins` (`base`, `render`, `render2d`, `aspect2d`, `taskMgr`, `loader`, `messenger`, etc.) and also into the `ShowBaseGlobal` module. The per-frame engine is assembled in `restart()` as a fixed set of tasks with carefully chosen `sort` values: `resetPrevTransform` (sort -51) → `dataLoop` (-50, runs the data graph / mouse / input) → user tasks → `ivalLoop` (20, steps the interval manager) → `collisionLoop` (30) → `garbageCollectStates` (46) → `igLoop` (50, calls `graphicsEngine.renderFrame()`) → `audioLoop` (60, updates 3-D sound positions after cull). `run()` simply calls `taskMgr.run()`. This sort ordering is the single most important thing to understand about frame timing — if you add a task that must see fresh input but run before render, give it a sort between -50 and 50.

**Where to start.** To change startup/window/scene-graph wiring, read `ShowBase.__init__`, `openDefaultWindow`, `setupRender*`, and `restart`. For event flow, read `Messenger.send`/`accept`/`__dispatch` together with `EventManager.processEvents`. For asset loading, `Loader.loadModel`.

**Gotchas / rationale (community).** The builtins are *deprecated for real projects* — "Don't use things like render, loader and run without the self or base prefix… they are deprecated" ([discourse 27417](https://discourse.panda3d.org/t/27417)); the supported alternative is the `ShowBaseGlobal` module, added precisely so code can `from direct.showbase.ShowBaseGlobal import base` instead of relying on builtins (commit [`4f50f6ab`](https://github.com/panda3d/panda3d) "showbase: use ShowBaseGlobal module as alternative to builtin scope"). `base` itself is set in `ShowBase.__init__` (historically "line 305"), which is why grepping for an assignment to `base` is confusing — it is `builtins.base = self` ([discourse 7206](https://discourse.panda3d.org/t/7206)). Animations that "won't load from any point in the program" are usually a sign the task manager / `base` was not yet running ([docs: Actor Animations](https://docs.panda3d.org/1.10/python/programming/models-and-actors/actor-animations)).

## actor

**What it is.** `Actor` is the Python wrapper over the C++ `Character` skeletal-animation system. It manages one or more model files ("parts"), the animations bound to each part, level-of-detail (LOD) switching, sub-parts (joint subsets sharing a bundle), and playback control (`play`/`loop`/`pose`/`stop`). It is the standard way to put an animated character into a Panda scene.

**Key classes and roles.**
- `Actor` — `direct/src/actor/Actor.py` (~2670 lines). Multiply inherits `DirectObject` **and** `NodePath`, so an Actor *is* a node you can `reparentTo(render)`. Its state lives in three dicts keyed by LOD name: `__partBundleDict` (LOD → partName → `PartDef`), `__animControlDict` (LOD → partName → animName → `AnimDef`), and `__subpartDict` (subpart name → `SubpartDef`).
- Nested `Actor.PartDef` — holds a `partBundleNP`, a `PartBundleHandle`, and the `partModel` (ModelRoot, kept so the ModelPool refcount stays accurate). `getBundle()` returns the underlying C++ `PartBundle`.
- Nested `Actor.AnimDef` — tracks one animation per part: `filename`, `animBundle`, and a possibly-`None` `animControl` (None until the anim is *bound*).
- Nested `Actor.SubpartDef` — a named subset of joints (`PartSubset`) of a real part, letting you, e.g., play a different anim on the upper vs. lower body of one bundle.
- `DistributedActor` — `direct/src/actor/DistributedActor.py`. Combines `Actor` with `DistributedNode` for networked characters.

**How it plugs in.** Loading uses the `Loader` with `LoaderOptions.LFConvertSkeleton` (models) and `LFConvertAnim` (anims) — see the class-level `modelLoaderOptions`/`animLoaderOptions`. Binding an animation to a part produces an `AnimControl` from the C++ side; `Actor` exposes this through `getAnimControl`, `play`, `loop`, `pose`, `controlJoint`/`exposeJoint` (the latter feed `ActorInterval`/`LerpAnimInterval` in the interval system). Parts are connected with `attach(part, parent, joint)`; multipart actors expose joints to which other parts/props are parented.

**Where to start.** `Actor.__init__` (the single-vs-multipart branching and copy-constructor path), `loadModel`/`loadAnims`, `bindAnim`/`__bindAnimToPart`, `makeSubpart`, and the LOD methods `setLODNode`/`addLOD`/`setLOD`. To debug "animation plays on the wrong joints," look at `SubpartDef` and `__animControlDict` resolution.

**Gotchas / rationale (community).** `autoBindAnims` / `auto_bind` will *rename* animations based on the bundle name, which surprises people coming from glTF ([discourse 29364](https://discourse.panda3d.org/t/29364)); for multipart actors people ask exactly how `autoBindAnims` resolves parts from an `Actor` instance ([discord](https://discord.com/channels/524691714909274162/1057767450843824198/1252977929554628678)). glTF historically did not support multiple parts in one file ([discourse 27799](https://discourse.panda3d.org/t/27799)). To duplicate a piece of a multipart actor, `find()` the part and `copyTo()` it rather than re-instancing the Actor ([discourse 15016](https://discourse.panda3d.org/t/15016)).

**Config variables.** Class-level `ConfigVariableBool`s read at construction: `validate-subparts` (default True), `merge-lod-bundles` (default True — collapses LOD bundles for efficiency), `allow-async-bind` (default True — binds animations off-thread).

## interval

**What it is.** A timeline system for scripted animation: smoothly interpolate ("lerp") node properties, call functions at points in time, play sounds/animations, and compose all of these into nested `Sequence`/`Parallel` structures. The performance-critical pieces are C++ (`CInterval` and subclasses, `CIntervalManager`); the Python layer subclasses them and adds Python-only interval types and the factory/sugar API.

**Central abstraction and inheritance.** `CInterval` (`direct/src/interval/cInterval.h`) is the base "timeline component": a named action with a `duration`, an `open_ended` flag, a `State` (`S_initial`/`S_started`/`S_paused`/`S_final`), and the `priv_*` step methods (`priv_initialize`, `priv_step`, `priv_finalize`, …) that the manager drives via `priv_do_event(t, EventType)`. C++ subclasses (all in this dir): `CLerpInterval` → `CLerpNodePathInterval` (the workhorse — lerps pos/hpr/scale/color/tex on a NodePath) and `CLerpAnimEffectInterval`; `CConstraintInterval` → `CConstrainPos/Hpr/PosHpr/TransformInterval`; the instantaneous `HideInterval`/`ShowInterval`/`WaitInterval`; and `CMetaInterval` (the container). On the Python side, `Interval` (`direct/src/interval/Interval.py`) is a parallel base inheriting `DirectObject` for intervals that *must* be implemented in Python (e.g. `ActorInterval`, `FunctionInterval`); the Lerp Python classes instead subclass the C++ `CLerpNodePathInterval` directly (`LerpNodePathInterval` → `LerpPosInterval`, `LerpHprInterval`, … in `LerpInterval.py`).

**Key classes and roles.**
- `MetaInterval` / `Sequence` / `Parallel` / `Track` — `direct/src/interval/MetaInterval.py`, subclassing `CMetaInterval`. A `Sequence` plays children back-to-back, a `Parallel` overlaps them. The Python layer flattens a tree of nested MetaIntervals into the *single* root `CMetaInterval` for the C++ engine, using relative-start constants `PREVIOUS_END`/`PREVIOUS_START`/`TRACK_START` (`CMetaInterval.RSPreviousEnd` etc.). `CMetaInterval` stores its plan as a list of `DefType` records (`DT_c_interval`, `DT_ext_index`, `DT_push_level`, `DT_pop_level`).
- `IntervalManager` (`direct/src/interval/IntervalManager.py`) extends the C++ `CIntervalManager`; the global is `ivalMgr`. `step()` calls the C++ `step()` then `__doPythonCallbacks()`, which fires `privPostEvent` on just-removed and event-bearing intervals and flushes a private `EventQueue` so interval `doneEvent`s are serviced immediately rather than next frame.
- `ActorInterval` / `LerpAnimInterval` (`direct/src/interval/ActorInterval.py`) drive Actor animation frames over time; `SoundInterval`, `ParticleInterval`, `MopathInterval`, `ProjectileInterval` (ballistic motion), `FunctionInterval`/`Func`/`Wait` (`FunctionInterval.py`), `IndirectInterval`. `IntervalGlobal.py` re-exports everything for the canonical `from direct.interval.IntervalGlobal import *`.

**How it plugs in.** `ShowBase.restart` adds the `ivalLoop` task (sort 20) which calls `ivalMgr.step()` once per frame. Intervals are awaitable in coroutines: `cInterval_ext.cxx` implements `__await__` (line 47), so `await Sequence(...)` works in tasks. `LerpNodePathInterval` mutates `TransformState`/`RenderState` on a target `NodePath` directly in C++.

**Where to start.** To add a new lerp type, mirror an existing class in `LerpInterval.py` and (if it needs C++ speed) the `CLerpNodePathInterval` machinery; for a Python-only interval, subclass `Interval` and implement `privInitialize`/`privStep`/`privFinalize` (see `ActorInterval.privStep`). To debug timing/ordering, read `cMetaInterval.cxx` and the `IntervalManager.__doPythonCallbacks` flush.

**Gotchas / rationale (community).** The correct way to nest is `append()`/`extend()` on a `Sequence`/`Parallel`, not constructing one from another — "The correct way to add intervals, sequences or parallels is: `SqOrParallel.append(OtherSqOrParallel)`" ([discourse 3331](https://discourse.panda3d.org/t/3331)). Sequences are also called MetaIntervals; this is the C++ name leaking through ([docs](https://docs.panda3d.org/1.10/python/programming/intervals/sequences-and-parallels)). Function intervals fire a callback at a single instant, distinct from *function-lerp* intervals which pass a value over a range ([docs](https://docs.panda3d.org/1.10/python/programming/intervals/function-intervals)).

**Config variables** (`direct/src/interval/config_interval.cxx`): `interval-precision` (default 1000.0 — the default `CMetaInterval::set_precision`, controls fixed-point timing granularity) and `verify-intervals` (default false — assert if `priv_*` functions are called out of order; turn on when debugging).

## task

**What it is.** A Python wrapper around the C++ `AsyncTaskManager`/`PythonTask`. It schedules per-frame callbacks, delayed callbacks (`doMethodLater`), and coroutines, supports multiple task chains (including threaded ones), and includes profiling helpers. This module replaced the old all-Python task system.

**Key classes and roles.**
- `TaskManager` — `direct/src/task/Task.py`. Wraps `self.mgr = AsyncTaskManager.getGlobalPtr()`. Public API: `add()`, `doMethodLater()`, `remove()`, `removeTasksMatching()`, `step()` (poll once, then `doYield`), and `run()` (loop until exception/KeyboardInterrupt). The global instance is `TaskManagerGlobal.taskMgr` (and `base.taskMgr`).
- `Task` — the module exposes the C++ `PythonTask` plus the status sentinels `cont`, `done`, `again`, `pickup`, `exit` and helpers `Task.pause()`, `Task.sequence()`, `Task.loop()`, `Task.gather()`. A task function returns one of these to control rescheduling: `Task.cont` (run again next frame), `Task.done` (stop), `Task.again` (re-delay by the original delay).
- `FrameProfiler.py`, `TaskProfiler.py`, `Timer.py`, `MiniTask.py` — profiling/diagnostics and a lightweight task variant.

**How it plugs in.** This is the heartbeat of the whole engine — `ShowBase.restart` registers all the loop tasks here, and `DirectObject.addTask`/`doMethodLater` funnel into it with `owner=self` so tasks are auto-removed when their owner is cleaned up. Coroutine support is first-class: a task function may be `async def`, and `await`-ing intervals, futures, or `Task.pause(t)` suspends without blocking the frame.

**Where to start.** `TaskManager.add`/`doMethodLater` for the scheduling contract, `step` for the per-frame poll + `doYield` (sleep/throttle) logic, and the coroutine path in `Task.py`. For frame-budget/threaded chains see `setupTaskChain` and the C++ `AsyncTaskChain`.

**Gotchas / rationale (community).** `Task.gather()` interoperability with raw coroutines vs. futures is subtle — you can `await asyncio.gather(...)` over a mix of Panda futures and Python coroutines, but Panda's own `gather` expects awaitables and has historically tripped people up ([discourse 27313](https://discourse.panda3d.org/t/27313), [discord](https://discord.com/channels/524691714909274162/1057767450843824198/1357858817613893632)). Awaitables in tasks include all intervals and `Task.pause()` ([docs: Coroutines](https://docs.panda3d.org/1.10/python/programming/tasks-and-events/coroutines)). Task return value semantics are the classic footgun — forgetting to return `Task.cont` stops the task after one frame ([docs: Tasks](https://docs.panda3d.org/1.10/python/programming/tasks-and-events/tasks)).

## fsm

**What it is.** Two finite-state-machine frameworks for game logic. The modern `FSM` defines states *implicitly* by `enterX`/`exitX`/`filterX` method naming; the older `ClassicFSM` defines states as explicit `State` objects with a transition table. Both manage enter/exit handlers and guard illegal transitions.

**Key classes and roles.**
- `FSM` — `direct/src/fsm/FSM.py`, subclasses `DirectObject`. State is a string in `self.state`; transitions go through `request()` (polite — may be denied) or `demand()` (forced — must succeed). Internals: `defaultFilter`, `__setState`, `forceTransition`, a transition-in-progress guard raising `AlreadyInTransition`, and a `RLock` (`direct.stdpy.threading.RLock`) for reentrancy. `request()` returns a `Transition` (a tuple subclass with `__await__`), so async enter/exit handlers are supported — the FSM stays in the transition state until the coroutine returns. `stateArray` supports cyclic next/prev requests.
- `State` / `StateData` — `direct/src/fsm/State.py`, `StateData.py`. The ClassicFSM building blocks: a `State` holds an `enterFunc`, `exitFunc`, and a list of allowed transitions; `StateData` is a state with associated load/unload data.
- `ClassicFSM` — `direct/src/fsm/ClassicFSM.py`. The original table-driven machine. `FourState`/`FourStateAI` are higher-level patterns built on top.

**How it plugs in.** FSMs are plain `DirectObject`s — no special hook into the frame loop. They are driven by your code or by messenger events (`accept('foo', self.demand, ['SomeState'])`). The async transition support ties into the task/coroutine system. Distributed FSMs (`FourStateAI`) are common in the OTP-style server code.

**Where to start.** `FSM.request`/`demand`/`defaultFilter`/`__setState` is the whole contract for the new style. For the classic style read `ClassicFSM.request` and `State`. `SampleFSM.py` is a runnable example.

**Gotchas / rationale (community).** During a transition it is illegal to call `request()` — doing so raises `AlreadyInTransition`; use `demand()` (which queues) if you must change state from within an enter/exit ([docs: Advanced FSM Tidbits](https://docs.panda3d.org/1.10/python/programming/finite-state-machines/advanced-fsm-tidbits)). Every FSM starts and ends in the implicit `"Off"` state, and `cleanup()` returns it there ([docs: Simple FSM Usage](https://docs.panda3d.org/1.10/python/programming/finite-state-machines/simple-fsm-usage)). Coroutine enter/exit is a deliberate, relatively recent feature: "Enter and exit funcs can be marked `async`, and the FSM will remain in the transition state until they return" ([github #1037](https://github.com/panda3d/panda3d/issues/1037)).

## gui

**What it is.** DirectGui — the Python UI toolkit wrapping the C++ `PGItem` widget nodes (`PGButton`, `PGFrame`, `PGEntry`, `PGSliderBar`, …) from `panda/src/pgui`. Each widget is a scene-graph node configured through an option dictionary (Tkinter/Pmw-style `('name', default, handler)` triples), with components composited from sub-widgets.

**Central abstraction and inheritance.** `DirectGuiBase` (`direct/src/gui/DirectGuiBase.py`) subclasses `DirectObject` and implements the option system: `defineoptions`/`addoptions` build `self._optionInfo = {keyword: [default, current, handler]}`, `createcomponent`/`component` manage composite sub-widgets, and `configure`/`__setitem__`/`cget` read/write options at runtime (calling the option's handler). `DirectGuiWidget(DirectGuiBase, NodePath)` adds the actual scene-graph node: it instantiates the C++ widget via the `pgFunc` option (`self.guiItem = self['pgFunc']('')`, e.g. `PGItem`), assigns a `guiId`, and manages frame style/state/bounds. The widget hierarchy is `DirectFrame(DirectGuiWidget)` → `DirectButton(DirectFrame)` → `DirectCheckButton`/`DirectRadioButton`, with siblings `DirectLabel`, `DirectEntry`, `DirectScrollBar`/`DirectSlider`/`DirectWaitBar`, `DirectScrolledList`/`DirectScrolledFrame`, `DirectOptionMenu`, `DirectDialog`. `DirectFrame` uses `pgFunc=PGItem`; `DirectButton` uses `pgFunc=PGButton`.

**Key files.** `DirectGuiGlobals.py` (aliased `DGG`) holds the constants: mouse buttons (`LMB`/`MMB`/`RMB`), states (`NORMAL`/`DISABLED`), frame styles mapped to `PGFrameStyle` (`FLAT`/`RAISED`=`TBevelOut`/`SUNKEN`=`TBevelIn`/`GROOVE`/`RIDGE`/`TEXTUREBORDER`), dialog results, and event-name prefixes (`DESTROY`, `B1PRESS`, etc.). `OnscreenText.py`/`OnscreenImage.py`/`OnscreenGeom.py` are lighter non-interactive helpers (thin NodePath wrappers, not full DirectGui widgets).

**How it plugs in.** DirectGui nodes are reparented under `aspect2d`/`pixel2d` (set up by `ShowBase.setupRender2d`), which sit beneath a `PGTop` node whose `PGMouseWatcherBackground` routes mouse events. Widget events arrive through the messenger as `event + self.guiId` strings (`bind()`/`unbind()` in `DirectGuiBase`); `command=` callbacks are convenience wiring over that. Fonts default to `TextNode.getDefaultFont()`.

**Where to start.** Read the long header comment in `DirectGuiBase.py` (it documents the 5-step option-resolution order), then `DirectGuiWidget.__init__`, then a concrete widget like `DirectButton.py` to see how it adds `PGButton` states and component text. For new widgets, copy a sibling and supply the right `pgFunc` + `optiondefs`.

**Gotchas / rationale (community).** "DirectGUI widgets are just nodes in the scene-graph, like any other… the classes you instantiate in Python inherit from NodePath" — so `hide()`/`show()`/`reparentTo()` all work and are the right way to toggle visibility ([discourse 25615](https://discourse.panda3d.org/t/25615)). The keyword/option list is famously under-documented; the authoritative source is the `optiondefs` in each widget's source (e.g. text-shadow options) — contributors are routinely pointed at `DirectGuiBase.py` on GitHub to find them ([discourse 28843](https://discourse.panda3d.org/t/28843), [discourse 26913](https://discourse.panda3d.org/t/26913)).

## distributed

**What it is.** The distributed-networking system — Panda's implementation of the Disney Online ("OTP") architecture for replicating objects across clients and servers. Objects are described in **DC files** (`.dc`, parsed by the C++ `dcparser` into a `DCFile`/`DCClass`); each networked class has client (`DistributedX`), AI/server (`DistributedXAI`), owner-view (`DistributedXOV`), and UberDOG (`DistributedXUD`) flavors. Repositories own the connection and the table of live objects.

**Central abstraction and inheritance.**
- `DistributedObjectBase(DirectObject)` (`DistributedObjectBase.py`) → `DistributedObject` (`DistributedObject.py`, the client base) with parallel `DistributedObjectAI`/`DistributedObjectOV`/`DistributedObjectUD`. Each DO carries `self.dclass` (its `DCClass`), `doId`, `parentId`, `zoneId`, and an `activeState` lifecycle: `ESNew → ESGenerating → ESGenerated → (disabled)`. The lifecycle hooks are `generate()` / `generateInit()` / `announceGenerate()` (object is now usable) and `disable()` / `delete()` / `deleteOrDelay()`. `neverDisable`/`cacheable` flags control whether the object survives zone changes or is cached on teardown (actors are expensive, so `cacheable`).
- `DistributedNode(DistributedObject, NodePath)` adds scene-graph presence; `DistributedSmoothNode(DistributedNode, DistributedSmoothNodeBase)` adds dead-reckoning/smoothing (the heavy lifting is in C++ `cDistributedSmoothNodeBase.cxx` and a `SmoothMover`).
- Repositories: `ConnectionRepository(DoInterestManager, DoCollectionManager, CConnectionRepository)` (`ConnectionRepository.py`) is the base — it multiply-inherits the **C++** `CConnectionRepository` (`cConnectionRepository.h`), which manages the socket, reads/writes datagrams, and *handles field-update datagrams entirely in C++* (passing unknown message types up to Python). `ClientRepositoryBase(ConnectionRepository)` → `ClientRepository` (the CMU/built-in client). `ServerRepository` (`ServerRepository.py`) is a standalone Python server for the built-in (non-Astron) protocol.

**Key supporting classes.** `DoInterestManager` (zone interest), `DoCollectionManager`/`DoHierarchy` (the doId→object table and parenting), `CRCache`/`CRDataCache` (cached disabled DOs), `ClockDelta` (`ClockDelta.py` — `networkToLocalTime`/`localToNetworkTime` for timestamp sync across machines), `TimeManager`/`TimeManagerAI` (the DO that performs clock sync), `NetMessenger` (a `Messenger` subclass that sends events *across the network* between AI/UD processes), `ParentMgr`/`RelatedObjectMgr`/`InterestWatcher`, and `PyDatagram`/`PyDatagramIterator` (Pythonic datagram builders over the C++ `Datagram`). `MsgTypes.py`/`MsgTypesCMU.py` enumerate the wire message codes. `direct.dc` is the built-in DC file.

**How it plugs in.** A repository connects, the server sends "generate" datagrams, `CConnectionRepository` decodes field updates and dispatches them by `doId`; Python constructs the right `DistributedX` from `dclass`, fills required fields, then fires `announceGenerate`. Smooth nodes register a per-frame task to interpolate buffered position telemetry. The system is largely independent of the render loop except through `DistributedNode`'s scene-graph membership and the smoothing task.

**Where to start.** `DistributedObject.generate`/`announceGenerate`/`disable` for the object lifecycle; `ConnectionRepository.__init__` and the C++ `cConnectionRepository.cxx` for the I/O path; `ClientRepository.py` + `ServerRepository.py` for the built-in protocol end-to-end; `SampleObject.py` + `direct.dc` for a minimal example. `ClockDelta.networkToLocalTime` is the place to understand timestamp handling.

**Gotchas / rationale (community).** OTP proper is "proprietary Disney technology"; the open `direct.distributed` system is OTP-*like* but not OTP, and the heavyweight production path is **Astron**, "designed to support massively multiplayer games… much more scalable than the built-in server, but also more complicated" ([discourse 27232](https://discourse.panda3d.org/t/27232), [discourse 9033](https://discourse.panda3d.org/t/9033)). When inspecting what a DistributedObject sends, read its DC class definition for the actual fields ([stackoverflow](https://stackoverflow.com/questions/20296611/python-server-emulator-for-toontown)). `DistributedSmoothNode` does "unique stuff in a task to help minimize the effects of laggy updates," and mis-sized timestamps are a classic source of datagram-iterator assertion errors ([discourse 8909](https://discourse.panda3d.org/t/8909), [discourse 2130](https://discourse.panda3d.org/t/2130)).

**Config variables** (`direct/src/distributed/config_distributed.cxx`): `game-server-timeout-ms` (20000), `min-lag`/`max-lag` (0.0 — artificially delay inbound messages to test latency tolerance), `handle-datagrams-internally` (true — let C++ handle field-update datagrams for speed; set false to force all handling into Python, useful when debugging).

## stdpy

**What it is.** Drop-in replacements for several Python standard-library modules, re-implemented on top of Panda's own threading and virtual-file-system primitives so that Panda threads (which the GIL-free C++ side knows about) cooperate correctly and so file I/O can read from mounted multifiles/VFS.

**Key files and roles.**
- `thread.py` — re-implements the low-level `_thread` API using `core.PythonThread`; tracks threads in a module-level `_threads` dict, exposes `start_new_thread`, `LockType`, and Panda's `Thread.force_yield`/`consider_yield`. Crucially these are *Panda* threads, so they show up in PStats and respect `Thread.getCurrentThread()`.
- `threading.py` / `threading2.py` — the higher-level `threading` API (`Thread`, `Lock`, `RLock`, `Condition`, `Event`) over the above. `threading2` is a closer emulation of the CPython implementation. These are what `Messenger` and `FSM` import for their locks.
- `file.py` — file objects backed by the `VirtualFileSystem`, so `open()` can read assets inside mounted `.mf` multifiles.
- `glob.py` — globbing that searches the VFS as well as the real filesystem.
- `pickle.py` — a pickle variant that tolerates Panda's C++ objects.

**How it plugs in.** Used pervasively inside `direct` precisely so the framework's own synchronization participates in Panda's threading model rather than the OS's. App code may also import them to make `threading`/`open` VFS-aware.

**Where to start.** `thread.py` (`start_new_thread`, `_add_thread`, `_get_thread_wrapper`) for the mapping to `PythonThread`; `threading.py` for the public lock/thread classes; `file.py` for VFS-backed I/O.

**Gotchas / rationale (community).** The whole point of `direct.stdpy.file` is to "interface more easily with Panda" assets/VFS rather than raw OS files ([discourse 11938](https://discourse.panda3d.org/t/11938)). Thread *cleanup* after a thread finishes has been a real bug surface — two upstream fixes touch exactly this: commit [`1dc02f6a`](https://github.com/panda3d/panda3d) "stdpy: fix direct.stdpy.threading cleanup issue after thread runs" and [`1f017997`](https://github.com/panda3d/panda3d) "fix issues with direct.stdpy.threading thread cleanup" (both `Fixes: #164`). If you touch the thread-tracking dicts, mind those.

## directnotify

**What it is.** The categorized logging/notification system used throughout `direct`. Every subsystem creates a named `Notifier` category (`directNotify.newCategory("ShowBase")`) and logs at `debug`/`info`/`warning`/`error` levels; categories are configured independently and the Python side integrates with the C++ `Notify` system so Python and C++ log lines share one stream.

**Key classes and roles.**
- `DirectNotify` — `direct/src/directnotify/DirectNotify.py`. The registry: `newCategory(name)` creates/returns a `Notifier`, `getCategory(name)` looks one up, `setDconfigLevels()` reads per-category verbosity from config (e.g. `notify-level-showbase debug`).
- `Notifier` — `direct/src/directnotify/Notifier.py`. The per-category logger. Methods `debug`/`info`/`warning`/`error`/`setDebug`/`setInfo`/`setWarning`. By default it pipes through a `StreamWriter(Notify.out())` (gated by `notify-integrate`, default True) so Python output joins the C++ `NotifyCategory` stream, optionally with timestamps (`notify-timestamp`). `error()` raises; it can also forward to the C++ severities (`NSDebug`/`NSInfo`/`NSWarning`/`NSError`).
- `Logger` / `RotatingLog` — `Logger.py`, `RotatingLog.py`. Optional file-logging backend (rotating log files); the global default is `LoggerGlobal.defaultLogger`.
- The registry singleton is `DirectNotifyGlobal.directNotify`.

**How it plugs in.** This is the most widely-imported module in `direct` — `DirectObject`, `Messenger`, `Interval`, `Actor`, every Distributed class etc. all hold a class-level `notify = directNotify.newCategory(...)`. Because it wraps the C++ `NotifyCategory`, log levels set in a `.prc` file (`notify-level-*`) control both layers.

**Where to start.** `DirectNotify.newCategory`/`setDconfigLevels` for category management, `Notifier.__init__`/`error`/`__str__` for how a line is formatted and routed, `Notifier.setServerDelta` for the networked timestamp offset.

**Config variables.** `notify-integrate` (default True — route Python notifies into the C++ `Notify.out()` stream), `notify-timestamp` (default False), and the per-category `notify-level-<category>` PRC variables consumed by `setDconfigLevels`.

## controls

**What it is.** Avatar-control / locomotion systems: a family of "walker" classes implementing different movement and collision models (gravity, raw physics, gridless, swimming, ghost/dev/observer), plus a `ControlManager` that swaps the active walker and a per-process `InputState` that aggregates directional input from multiple sources.

**Key classes and roles.**
- `ControlManager` — `direct/src/controls/ControlManager.py`. Registry of named walkers (`self.controls = {}`); `add(controls, name)` registers, `use(name, avatar)` swaps the active one — disabling the old walker's avatar controls and collisions, then enabling the new one for the avatar (`setAvatar`, `setCollisionsActive`, `enableAvatarControls`).
- Walkers (all `DirectObject` subclasses): `GravityWalker` (`GravityWalker.py`, the standard one — uses a C++ `CollisionHandlerGravity` `self.lifter` with `setGravity`, and enter/again collision patterns), `NonPhysicsWalker` (simple, no gravity), `PhysicsWalker` (full physics engine), `BattleWalker`, `SwimWalker`, `GhostWalker`, `DevWalker` (no-clip), `ObserverWalker`, `TwoDWalker`. They share an interface (`setAvatar`, `setWalkSpeed`, `enableAvatarControls`, `handleAvatarControls`, `setCollisionsActive`) so `ControlManager` can treat them uniformly.
- `InputState` — `direct/src/controls/InputState.py`. A `DirectObject` that tracks named boolean inputs (`set`/`isSet`/`watch`/`watchWithModifiers`) from multiple `inputSource`s, returning revocable tokens (`InputStateWatchToken`, `InputStateForceToken`, `InputStateTokenGroup`). Walkers poll it each frame for `forward`/`reverse`/`turnLeft`/`turnRight`/`jump`. The process-wide singleton is created in `direct/src/showbase/InputStateGlobal.py` as `inputState` (and `base.inputState`).

**How it plugs in.** A walker's `handleAvatarControls` runs as a task, reads `InputState`, integrates motion, and feeds the avatar `NodePath` and a `CollisionTraverser`/`CollisionHandlerGravity`. Collision events come back through the messenger via the `addInPattern("enter%in")` / `addAgainPattern` hooks. `ControlManager` is the seam game code uses to switch movement modes (walking → swimming → ghost). These build directly on the C++ collision system (`panda/src/collide`) and physics (`panda/src/physics`).

**Where to start.** `ControlManager.add`/`use` for swapping; `GravityWalker.__init__` (lifter/collision setup) and its `handleAvatarControls`/`enableAvatarControls` for the core movement loop; `InputState.watch`/`set`/`isSet` for the input plumbing. To add a movement mode, copy `NonPhysicsWalker` or `GravityWalker` and register it with the manager.

**Gotchas / design notes.** The walkers are an extracted-from-Toontown/Pirates lineage, so several (`BattleWalker`, `SwimWalker`, `GhostWalker`) carry game-specific assumptions; `GravityWalker` and `NonPhysicsWalker` are the general-purpose ones. `GravityWalker` has a `_legacyLifter` mode toggling `CollisionHandlerGravity.setLegacyMode` — relevant when porting old content whose floor-collision behavior changed.

## Known shortcomings & footguns

The same global-state, dual-API, and reference-counting design that makes `direct` quick to live-code in also produces a well-worn set of traps. The entries below are community-mined opinion and history, preserved verbatim where quoted; severity/status tags reflect the catalogue's assessment, not a guarantee.

### The camelCase / snake_case dual interface (the "original sin")
**Severity: major · Status: mitigated (snake_case aliases auto-generated; `direct.*` incomplete)**

Every public method exists under two spellings. The C++ codebase is snake_case; when first wrapped to a (pre-Python) scripting language that couldn't use underscores, camelCase was invented and kept. The result buries discoverability, confuses newcomers about which name is "real," and doubles autocomplete noise. (The interrogate binding generator that produces these aliases is covered in [Cross-cutting concepts](../cross-cutting-concepts.md).)

> "That is the origin of the camelCase convention. When this scripting language
> was changed to Python, the convention was kept, because PEP 8 didn't really
> exist at the time." — rdb *(maintainer)*, [t/28928](https://discourse.panda3d.org/t/28928)

### snake_case methods with camelCase *arguments*
**Severity: major · Status: still-open**

The migration aliased method *names* but not keyword-argument names in the hand-written `direct.*` tree, producing `task_mgr.do_method_later(..., extraArgs=[...], appendTask=True)`.

> "we forgot that there are arguments that are still in camelCase. So we now have
> a bunch of snake_case methods with camelCase arguments. What a mess." — rdb
> *(maintainer)*, [#1795](https://github.com/panda3d/panda3d/issues/1795)

### Magic global builtins injected into `__builtins__`
**Severity: major · Status: mitigated (`ShowBaseGlobal` escape hatch added; still injected)**

Instantiating `ShowBase` slams ~8 names (`base`, `render`, `loader`, `taskMgr`, `messenger`, `globalClock`, `camera`, …) into Python's builtin namespace so they "appear out of thin air" (see the `showbase` section above and its note on the supported `ShowBaseGlobal` alternative). This breaks static analysis, linters, IDE autocomplete, and Cython/freezing (the names don't exist at compile time). Universally considered inelegant — kept for Disney-era live-coding convenience and backward compat.

> "No one loves this builtin slamming, no one claims it is elegant, but we've got
> it for now." — drwr *(maintainer)*, [t/5433](https://discourse.panda3d.org/t/5433)

> globals exist because "Walt Disney Imagineering uses the DIRECT library for
> live coding, and it's convenient to have all the relevant variables handy in
> the interactive interpreter." — rdb *(maintainer)*, [t/28928](https://discourse.panda3d.org/t/28928)

### Globals break IDEs/linters (`undefined variable` everywhere)
**Severity: major · Status: mitigated (workarounds)**

Because `render`/`loader`/`base`/`taskMgr` only materialize at runtime, PyCharm/VSCode/Pylint flag every use as an error with no autocomplete. drwr explicitly accepts the trade-off.

> "that's well worth the inconvenience of not being able to use tools like PyLint
> so easily." — drwr *(maintainer)*, [t/5433](https://discourse.panda3d.org/t/5433)

### ShowBase is a process-wide singleton — can't run two
**Severity: major · Status: still-open (by-design)**

Only one `ShowBase` can exist per process; a second raises *"Attempt to spawn multiple ShowBase instances!"*. This blocks multi-window/multi-context apps, embedding multiple viewports, and clean restart-without-process-exit. Rooted in the global-state design.

> "Only being able to spawn a single instance is a known limitation for ShowBase.
> You could create multiple processes and have them communicate." — Moguri,
> [t/26613](https://discourse.panda3d.org/t/26613)

### Stringly-typed events fail silently on typo
**Severity: minor · Status: by-design**

Events are raw strings (`self.accept("player-stopped", …)`); a misspelled event name simply never fires — no error, no warning (see the `Messenger` description in the `showbase` section above). The messenger's debug-watch also matches by *substring*, so `"AvatarMove"` fires for `"AvatarMovementFrozen"`.

### No bundled type stubs (.pyi)
**Severity: major · Status: mitigated (3rd-party `types-panda3d`; not shipped)**

Panda ships no `.pyi` stubs, so Pylance/mypy can't see the C++-wrapped modules at all — no autocomplete, no type-checking — unless you install a *separate* community package. interrogate-generated bindings also yield wrong return types (e.g. `loadModel` inferred as `list | Any | _Callback`).

> "vscode's pylance language server does not recognize contents of these files...
> the reason is for lacking type stub files." — BlackEagle1983,
> [#1329](https://github.com/panda3d/panda3d/issues/1329)

### Cryptic C++ assertions leak into Python as `AssertionError`
**Severity: major · Status: still-open (partial fix proposed in #966)**

Invalid args surface as opaque `AssertionError: _error_type == ET_ok` — the literal C++ assert expression, meaningless to newcomers. rdb opened an issue to map these to proper `IndexError`/`KeyError`, but it's a vast surface only incrementally addressed.

> "the error messages can be awfully difficult to decipher for newcomers... we
> would translate some to IndexError, KeyError." — rdb *(maintainer)*,
> [#966](https://github.com/panda3d/panda3d/issues/966)

### `loadPrcFileData("", "...")` — the empty first arg, and config must precede ShowBase
**Severity: minor · Status: by-design**

The standard in-code config call has a mysterious empty first string (a page name) that trips up nearly every beginner, and it silently does nothing if called *after* ShowBase init (config is read at startup). The PRC config system itself lives in dtool — see the [dtool page](dtool.md).

### PRC config loads at static-init time — apps can't control it
**Severity: major · Status: still-open (acknowledged hard)**

Config files are processed during static initialization, before `main()`, so app developers can't control which files load; the documented customization path was to recompile Panda. CFSworks filed a design issue; rdb agrees but notes Panda itself uses config at static-init time, making it hard to untangle. (This is a dtool config-system behavior surfacing in Python apps — see the [dtool page](dtool.md).)

> "Don't load anything at static init time: It takes away control... app
> developers are expected to recompile Panda(!)." — CFSworks *(maintainer)*,
> [#245](https://github.com/panda3d/panda3d/issues/245)

### Naming your config `Config.prc` silently overrides Panda's defaults
**Severity: minor · Status: by-design (naming trap)**

A user file named `Config.prc` shadows Panda's bundled default, knocking out default display settings — surfacing as *"Your Config.prc file must name at least one valid panda display library."* (PRC file discovery is a dtool concern — see the [dtool page](dtool.md).)

### Getters/setters instead of properties (un-Pythonic)
**Severity: minor · Status: mitigated (property aliases added later)**

The API was built on `getX()/setX()` chains (`node.get_transform().get_pos().get_x()`). rdb later added property access (`node.transform.pos.x`), but it was contentious and rolled out gradually; old style remains everywhere in docs/samples.

### Python profiler hidden behind an undocumented config var
**Severity: minor · Status: by-design (discoverability)**

Panda's built-in Python profiler only activates via the obscure `pstats-python-profiler 1` (the `FrameProfiler`/`TaskProfiler` helpers in the `task` section above); users routinely don't know it exists and reach for raw cProfile, which interacts awkwardly with the main loop.

### Intervals/Actors get garbage-collected unless you store a reference
**Severity: major · Status: by-design (recurring trap)**

An interval/Actor created locally plays for a moment then silently dies when its only reference goes out of scope. The engine does not keep them alive for you. (This is the Python side of Panda's intrusive reference counting — see the reference-counting discussion in [Cross-cutting concepts](../cross-cutting-concepts.md).)

> "You must keep a reference to an Actor, or else it will self destruct and become
> static geometry." — teedee, [t/13352](https://discourse.panda3d.org/t/13352)

> "you need to store a reference to the Actor object otherwise it goes out of
> scope and gets cleaned up." — rdb *(maintainer)*, Discord

### `Func(myfunction())` vs `Func(myfunction)` calls the function immediately
**Severity: major · Status: by-design (footgun)**

The trailing parens invoke the function at *construction* and store its return (`None`) instead of deferring the call. drwr calls it "a common error." (See `FunctionInterval`/`Func` in the `interval` section above.)

> "make sure you are doing Func(myfunction) and not Func(myfunction())... The
> second form calls myfunction right on the spot, and stores None... which is
> almost certainly not what you wanted." — drwr *(maintainer)*,
> [t/9069](https://discourse.panda3d.org/t/9069)

### The `Task.cont`/`again`/`done` return-value model
**Severity: minor (very common) · Status: by-design (confusion)**

Forgetting to return anything defaults to `done` (task stops after one frame). Returning `Task.cont` from a task that *starts an interval* restarts the interval every frame so it never progresses. (See the `task` section above for the return-value sentinels.)

> "The problem with returning Task.cont is that it means the play() method will be
> called again next frame, and again and again... so the interval is constantly
> being restarted." — drwr *(maintainer)*, [t/1516](https://discourse.panda3d.org/t/1516)

### `doMethodLater` rejects a Task object; `extraArgs` clobbers the implicit `task` arg
**Severity: minor · Status: by-design (API wart)**

It expects a *function*, not a `Task`; and supplying `extraArgs` removes the implicit `task` parameter — which drwr admits is "difficult to do with the current definition."

### LerpInterval start/end values are captured at construction, not play time
**Severity: minor · Status: by-design (surprising)**

A Lerp built early with a node's current position animates from a stale start once finally played — unlike normal Python evaluation expectations.

### Coroutine tasks can't be `remove()`d while awaiting; can't be resumed
**Severity: major · Status: mitigated (`cancel()` added; `remove()` still fails)**

A coroutine task stuck in `await` can't be killed via `task.remove()`. And because tasks inherit from Future, a finished/cancelled coroutine task can never be re-added — so a *pause* feature for coroutines is structurally impossible.

> "futures (by their nature) can transition from the 'running' to the 'done' state
> only once... once a task is 'done'... it cannot go back to the 'running' state."
> — rdb *(maintainer)*, [#911](https://github.com/panda3d/panda3d/issues/911)

### Panda's async/`gather` doesn't behave like stdlib asyncio
**Severity: major · Status: still-open**

Porting `asyncio.gather` examples discards results; `Task.gather` "does not seem to work"; and asyncio primitives are unsafe across task chains (see the `Task.gather` note in the `task` section above).

> "please note that asyncio isn't thread-safe, so you can't use asyncio.Lock
> across multiple threads (this includes threaded task chains)." — rdb
> *(maintainer)*, [t/28380](https://discourse.panda3d.org/t/28380)

### Running the main loop off the main thread breaks
**Severity: minor · Status: by-design**

Starting `run()`/`taskMgr.step()` from a `threading.Thread` raises *"ValueError: signal only works in main thread"* and logs clock-jump warnings; the task loop is also non-reentrant (`taskMgr.step()` inside another step asserts).

### NodePaths/scene-graph objects aren't directly picklable
**Severity: minor · Status: mitigated (BAM is the supported path; pickle partial)**

Users trying to `pickle` NodePaths/nodes to save a scene hit walls — the supported serialization is BAM (see the Datagram/BamReader discussion in [Cross-cutting concepts](../cross-cutting-concepts.md)), and pickle support is partial (e.g. `CollisionTraverser`/`CollisionHandler` aren't picklable, blocking any class that holds them — [#1090](https://github.com/panda3d/panda3d/issues/1090)).

### Type-identity check reads uninitialized memory; pickle returns references not copies
**Severity: minor · Status: fixed (specific cases in #554)**

Panda detects "is this a Panda C++ object?" by reading a signature at a fixed struct offset — uninitialized memory for non-Panda objects (valgrind warnings, CPython-internal-dependent). (This is the interrogate `DtoolInstance_Check`/`PY_PANDA_SIGNATURE` mechanism described in [Cross-cutting concepts](../cross-cutting-concepts.md).) The same thread surfaced a pickle bug where `ParamNodePath.get_value()` returned a reference, corrupting unpickled NodePaths ([#554](https://github.com/panda3d/panda3d/issues/554)).

### Where to start (this cluster)

A new contributor should read in this order:

1. **`direct/src/showbase/ShowBase.py`** — `__init__`, `openDefaultWindow`, `setupRender*`, and especially `restart()` (the sorted per-frame task pipeline). This is the spine everything else hangs from.
2. **`direct/src/showbase/DirectObject.py`** (tiny, ~120 lines) — understand `accept`/`addTask`; nearly every other class inherits this.
3. **`direct/src/showbase/Messenger.py`** + **`direct/src/showbase/EventManager.py`** — the event bus and its bridge to the C++ `EventQueue`.
4. **`direct/src/task/Task.py`** — `TaskManager.add`/`step`/`run`; the frame heartbeat and coroutine support.
5. Then pick a vertical: **`interval/cInterval.h` + `interval/Interval.py` + `interval/MetaInterval.py`** for animation timelines, **`actor/Actor.py`** for characters, **`gui/DirectGuiBase.py`** for UI, or **`distributed/DistributedObject.py` + `distributed/ConnectionRepository.py` + `distributed/cConnectionRepository.h`** for networking.

Throughout, remember the layering rule: the Python class is usually a thin wrapper, and the real algorithm is in the sibling `c*.cxx`/`c*.h` (compiled into `panda3d.direct`) or in the core (`panda3d.core`). When a Python method just marshals arguments and calls `CSomething.method(self, ...)`, jump to the C++ for the actual behavior.
