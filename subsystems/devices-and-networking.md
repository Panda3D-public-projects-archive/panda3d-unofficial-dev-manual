# Devices, data graph & networking

This cluster is Panda3D's input and I/O plumbing: the layer that gets hardware events (mice, keyboards, gamepads, VR trackers) and remote data (TCP/UDP, HTTP) into the engine each frame, and the small typed dataflow graph (the *data graph*) that routes that input into transforms applied to the scene graph. The conceptual keystone is the **data graph** (`panda/src/dgraph`): a tree of `DataNode`s, distinct from the scene graph, that runs single-threaded once per frame and transmits named, typed values *downward* from root to leaves. Around it sit input device discovery (`device`), interaction handlers that turn mouse/button input into transforms and events (`tform`), and three independent communication stacks: synchronous-ish socket networking (`net` over `nativenet`), HTTP/asset downloading (`downloader`), and VR peripheral tracking (`vrpn`).

The single most important distinction to internalize: the **scene graph** is a tree of `PandaNode`s describing spatial hierarchy and is traversed during render (cull/draw). The **data graph** is a tree of `DataNode`s (which *are* `PandaNode`s, so they reuse `NodePath` machinery) describing per-frame data flow; it is traversed by `DataGraphTraverser` early in the frame (`ShowBase`'s `dataLoop` task, sort `-50`). A node like `Trackball` reads mouse input from the data graph and emits a transform; `Transform2SG` is the bridge that takes that data-graph output and stamps it onto a scene-graph node.

---

## device

**What it is.** The hardware-input abstraction layer. It discovers and represents every input device on the machine — keyboards, mice, gamepads, flight sticks, steering wheels, 3D mice, HMDs — behind one flexible `InputDevice` class, and exposes them through a singleton `InputDeviceManager` that performs hot-plug detection. Rather than a deep per-device-type class hierarchy, Panda models a device as a bag of capabilities (buttons, axes, a pointer, a tracker, vibration, battery) so a single class can describe wildly different hardware. This package also contains the data-graph *adapter* nodes (`InputDeviceNode`, `ButtonNode`, `AnalogNode`, `TrackerNode`, `DialNode`, `VirtualMouse`) that pump device state into the data graph, and the older `ClientBase`/`ClientDevice` abstraction reused by VRPN.

**Central abstraction & inheritance.** `InputDevice` (`panda/src/device/inputDevice.h`) derives from `TypedReferenceCount`. Its capability model is built from nested enums/structs in the header: `enum class DeviceClass` (`KEYBOARD`, `MOUSE`, `GAMEPAD`, `FLIGHT_STICK`, `STEERING_WHEEL`, `DANCE_PAD`, `HMD`, `SPATIAL_MOUSE`, `DIGITIZER`, …), `enum class Feature` (`POINTER`, `KEYBOARD`, `TRACKER`, `VIBRATION`, `BATTERY`), `enum class Axis`, and the `ButtonState`/`AxisState` inner classes. Key methods: `is_connected()`, `get_device_class()`, `has_feature()`, `poll()` (calls virtual `do_poll()`), `set_vibration()` (virtual `do_set_vibration()`), and `enable_feature()`. Platform back-ends subclass `InputDevice`:
- `EvdevInputDevice` (`evdevInputDevice.h`) — Linux/FreeBSD evdev gamepads & generic devices.
- `LinuxJoystickDevice` (`linuxJoystickDevice.h`) — older Linux `/dev/input/js*` joystick API.
- `WinRawInputDevice` (`winRawInputDevice.h`) — Windows Raw Input.
- `XInputDevice` (`xInputDevice.h`) — Windows XInput (Xbox controllers).
- `IOKitInputDevice` (`ioKitInputDevice.h`) — macOS IOKit/HID.
- `VirtualMouse` (`virtualMouse.h`) is itself a `DataNode`, not an `InputDevice` — it synthesizes mouse data into the data graph.

**Manager & platform selection.** `InputDeviceManager` (`inputDeviceManager.h`) is a `MemoryBase` singleton (`get_global_ptr()`). `InputDeviceManager::make_global_ptr()` in `inputDeviceManager.cxx` picks the platform implementation at runtime: `WinInputDeviceManager` (Windows), `IOKitInputDeviceManager` (macOS), or `LinuxInputDeviceManager` (Linux), each `final : public InputDeviceManager`. It tracks `_connected_devices` (an `InputDeviceSet`), exposes `get_devices()` / `get_devices(DeviceClass)`, `add_device()`/`remove_device()`, and a virtual `update()` that does per-platform hot-plug scanning and throws connect/disconnect events.

**The `ClientBase`/`ClientDevice` sub-hierarchy** is a second, older device abstraction kept for VRPN. `ClientBase` (`clientBase.h`, `TypedReferenceCount`) represents a *source* of devices (e.g. a VRPN server), with `fork_asynchronous_thread()`, `poll()`, a coordinate-system setting, and a pure-virtual `make_device()`. `ClientDevice` (`clientDevice.h`) derives from `InputDevice`; the concrete leaves are `ClientButtonDevice`, `ClientAnalogDevice`, `ClientDialDevice`, `ClientTrackerDevice` (all `: public ClientDevice`). `TrackerData` (`trackerData.h`, a `MemoryBase`) carries position/orientation tracker samples.

**How it plugs in.** Device state reaches the rest of the engine through data-graph adapter `DataNode`s. `InputDeviceNode` (`inputDeviceNode.h`, `: public DataNode`) "reads the controller data sent from the InputDeviceManager, and transmits it down the data graph" (app-thread only) and outputs `button_events`. `ButtonNode`, `AnalogNode`, `DialNode`, `TrackerNode` (`buttonNode.h` etc., all `: public DataNode`) each wrap one capability of an `InputDevice` *or* a `ClientBase` device and surface it as data-graph output. In Python, `ShowBase.attachInputDevice` does `self.dataRoot.attachNewNode(InputDeviceNode(device, device.name))`.

**Where to start.** To add/fix device support: `inputDevice.h` (the capability model) and the relevant platform file (`evdevInputDevice.cxx`, `winRawInputDevice.cxx`, `xInputDevice.cxx`, `ioKitInputDevice.cxx`). To change discovery/hot-plug, start in `inputDeviceManager.cxx::make_global_ptr` then the platform manager (`linuxInputDeviceManager.cxx`, `winInputDeviceManager.cxx`, `ioKitInputDeviceManager.cxx`). To change how devices feed the data graph, read `inputDeviceNode.cxx` and `buttonNode.cxx`.

**Config vars (`config_device.cxx`).** `asynchronous-clients` (`ConfigVariableBool`, default `true`) — whether `ClientBase` sources may fork a background polling thread.

**Gotchas / notes (community).**
- Input-device support landed in 1.10 ("As of version 1.10, Panda3D gained built-in support for various input devices including … joysticks, gamepads and steering wheels", docs *Joystick Support*, https://docs.panda3d.org/1.10/python/programming/hardware-support/joystick-support). Pre-1.10 code/tutorials won't have `base.devices`.
- Non-standard controllers map unpredictably: a DualShock 4 behaves differently from an Xbox controller, a recurring confusion (forum *Trouble connecting gamepad*, https://discourse.panda3d.org/t/28715). Button/axis identities come from the OS HID descriptor, so the same physical button differs across back-ends.
- XInput hotplug and the `base.devices.gamepads` convenience were added together (commit `d20d6169183df18e941300cebf836008935486ad`, "XInput gamepad hotplugging, add base.devices.gamepads"); FreeBSD evdev support is recent (commit `7be4b7c3bbbfa45fd1b1064e5d14c8e13ffefa69`). The author of nearly all of this subsystem is **rdb**.

---

## dgraph

**What it is.** Per the package README: "the data graph … is the hierarchy of devices, tforms, and any other things which might have an input or an output and need to execute every frame." It is a small, single-threaded dataflow engine that reuses the scene-graph node/`NodePath` machinery but carries *typed named values* instead of geometry. Each `DataNode` declares a set of named inputs and outputs (by `TypeHandle`); when a child is parented under a parent, the child's inputs are auto-wired to the parent's matching-named outputs, and a mismatch logs an error. Data flows strictly downward each frame.

**Central abstraction & inheritance.** `DataNode` (`panda/src/dgraph/dataNode.h`) derives from **`PandaNode`** — this is why data-graph nodes can live under a `NodePath` (`ShowBase`'s `dataRoot`). It is abstract; subclasses call `define_input(name, type)` / `define_output(name, type)` in their constructors and override the protected `do_transmit_data(trav, input, output)`. The header is explicit about the threading contract: *"DataNode does not attempt to cycle its data with a PipelineCycler. The data graph is intended to be used only within a single thread."* Internally `DataNode` keeps `_input_wires`/`_output_wires` (`pmap<string, WireDef>`) and `_data_connections`, rebuilt by `reconnect()` when parentage changes (`parents_changed()` override).

**`DataNodeTransmit`** (`dataNodeTransmit.h`, `: public TypedWritable`) is the value bundle moved between nodes — "basically just an array of `EventParameter`s, one for each registered input or output wire," with `get_data(i)` / `set_data(i, EventParameter)` / `has_data(i)`. It uses `ALLOC_DELETED_CHAIN` for fast recycling and is `bam`-serializable.

**`DataGraphTraverser`** (`dataGraphTraverser.h`) "supervises the traversal of the data graph and the moving of data from one DataNode to its children." Key methods: `traverse(PandaNode *)`, `traverse_below(node, output)`, and `collect_leftovers()`. It carries a `Thread *_current_thread`. The `r_transmit()` recursion plus the `MultipassData` map (`pmap<DataNode*, CollectedData>`) handle the case where a node has multiple parents: it waits until all parents' outputs have arrived before transmitting (multipass), which is what `collect_leftovers()` flushes at the end.

**How it plugs in.** The data graph is driven from `direct/src/showbase/ShowBase.py`: `self.dgTrav = DataGraphTraverser()`, root node `self.dataRootNode = NodePath('dataRoot').node()`, and the `__dataLoop` task (`self.taskMgr.add(self.__dataLoop, 'dataLoop', sort=-50)`) calls `self.dgTrav.traverse(self.dataRootNode)` every frame *before* rendering. The graph's roots are typically `MouseAndKeyboard` (in `panda/src/display`, a `DataNode`) and `InputDeviceNode`s; below them sit `tform` nodes and finally `Transform2SG` leaves. So `dgraph` depends only on `pgraph` (for `PandaNode`) and `event`/`linmath` (for `EventParameter` payloads); everything in `device`, `tform`, and `vrpn`'s nodes depends on it.

**Where to start.** Read `panda/src/dgraph/README.md`, then the long doc comment at the top of `dataNode.h` (the canonical description of the whole subsystem), then `dataGraphTraverser.cxx` for the traversal/multipass logic. To understand a real producer→consumer wiring, trace `MouseAndKeyboard::do_transmit_data` → `Trackball::do_transmit_data` → `Transform2SG::do_transmit_data`.

**Config vars (`config_dgraph.cxx`).** None beyond the notify category `dgraph`. Authored by **drose** (2002).

**Gotchas.** Single-threaded by design — do not assume the data graph honors `PandaNode`'s pipeline-cycling/threading guarantees. Auto-wiring is *by name and type*: if you `define_output("transform", …)` in a parent and `define_input("xform", …)` in the child, they silently won't connect (you'll see an error message, not data). Multiple-parent data nodes are valid but invoke the multipass path. Users hitting "my default camera won't move" often don't realize the camera is moved by data-graph nodes, not scene-graph manipulation (forum, https://discourse.panda3d.org/t/26423).

---

## tform

**What it is.** The "transformers" — data-graph `DataNode`s that interpret mouse/keyboard/button input and turn it into transforms or events. This is where user interaction logic lives: spinning a camera/object (`Trackball`), driving around a plane (`DriveInterface`), hit-testing rectangular screen regions and firing enter/leave/click events (`MouseWatcher`), rethrowing button presses as Panda events (`ButtonThrower`), and bridging data-graph output into the scene graph (`Transform2SG`).

**Central abstraction & inheritance.** Most tform nodes descend from `MouseInterfaceNode` (`mouseInterfaceNode.h`, `: public DataNode`), "the base class for some classes that monitor the mouse and keyboard input and perform some action," providing `require_button()` / `clear_button()` for modifier gating. Inheritance:
- `Trackball : public MouseInterfaceNode` (`trackball.h`) — "acts like Performer in trackball mode … spin around a piece of geometry directly, or … around a camera with the inverse transform." Crucially, *"Trackball … just places a transform in the data graph; parent a `Transform2SG` node under it to actually transform objects."*
- `DriveInterface : public MouseInterfaceNode` (`driveInterface.h`) — vehicle-style motion on a horizontal plane.
- `MouseSubregion : public MouseInterfaceNode` (`mouseSubregion.h`) — restricts mouse handling to a screen sub-rectangle.
- `MouseWatcher : public DataNode, public MouseWatcherBase` (`mouseWatcher.h`) — multiple-inheritance; maintains a list of `MouseWatcherRegion`s, fires region enter/exit/click events, can suppress events from the rest of the data graph, can drive a software cursor, and can log the mouse trail for gesture recognition.
- `ButtonThrower : public DataNode` (`buttonThrower.h`) — "Throws Panda Events for button down/up events generated within the data graph," via `throw_event()`. Intended to sit below a `MouseAndKeyboard` device.
- `Transform2SG : public DataNode` (`transform2sg.h`) — input: a Transform matrix; output: none, but applies that matrix as the transform on a given scene-graph node (`set_node()`). This is the data-graph → scene-graph bridge.

Supporting non-node classes: `MouseWatcherRegion : public TypedWritableReferenceCount, public Namable` (a screen rectangle, `mouseWatcherRegion.h`), `MouseWatcherBase` (region container, `mouseWatcherBase.h`, by **rdb**), `MouseWatcherGroup : public MouseWatcherBase, …` (`mouseWatcherGroup.h`), and `MouseWatcherParameter` (event payload).

**How it plugs in.** Upstream is the data graph's input source (`MouseAndKeyboard`, `InputDeviceNode`); downstream is the scene graph (via `Transform2SG`) and the event system (via `ButtonThrower`/`MouseWatcher` throwing events to `EventHandler`/messenger). `MouseWatcher` also reaches into `display` (`DisplayRegion`) to map normalized mouse coords into the right region — multiple display regions need their own `MouseWatcher` with `setDisplayRegion()`.

**Where to start.** `transform2sg.cxx` is the smallest complete example of a consuming `DataNode` (read input wire, apply to a `PandaNode`). For interaction logic, `mouseWatcher.cxx` (region hit-testing, event throwing) and `trackball.cxx` (mouse delta → matrix). For event rethrow, `buttonThrower.cxx`.

**Config vars (`config_tform.cxx`).** Drive tuning: `drive-forward-speed`, `drive-reverse-speed`, `drive-rotate-speed`, `drive-vertical-dead-zone`, `drive-vertical-center`, `drive-horizontal-dead-zone`, `drive-horizontal-center`, `drive-vertical-ramp-up-time`, `drive-vertical-ramp-down-time`, `drive-horizontal-ramp-up-time`, `drive-horizontal-ramp-down-time` (all `ConfigVariableDouble`). Also `inactivity-timeout` (`ConfigVariableDouble`) and `trackball-use-alt-keys` (`ConfigVariableBool`).

**Gotchas (community).**
- One `MouseWatcher` per `DisplayRegion`: picking coordinates get "fubar" with multiple 2-d display regions unless each region gets its own watcher (forum *Multiple MouseWatchers* https://discourse.panda3d.org/t/10477; *Have different mouseWatchers throw unique events* https://discourse.panda3d.org/t/29066). Use `mouseWatcherNode.setDisplayRegion(...)` (forum https://discourse.panda3d.org/t/8222).
- `MouseWatcher` can *suppress* events for regions it owns; if downstream nodes stop seeing mouse data, a region's suppression flags are the usual cause.
- The mouse trail log is empty unless you enable pointer-event generation on the `GraphicsWindowInputDevice` *and* set a trail-log duration on the `MouseWatcher` (per the `mouseWatcher.h` doc comment).

---

## net

**What it is.** The high-level networking API. It establishes/destroys TCP and UDP connections and moves `Datagram`s over them with optional background reader/writer threads and queued, thread-safe delivery. It is a thin, ergonomic layer over `nativenet`'s raw sockets, adding datagram framing (length headers for TCP), connection lifetime tracking, and queue-based event reporting so the app thread never blocks on the socket.

**Central abstraction & inheritance.**
- `ConnectionManager` (`connectionManager.h`) — "the primary interface to the low-level networking layer." Opens connections: `open_UDP_connection()`, `open_TCP_server_rendezvous(port, backlog)`, `open_TCP_client_connection()`. Use directly if you don't care about tracking unexpected closes; otherwise use the queued subclass.
- `Connection : public ReferenceCount` (`connection.h`) — one socket's worth of state (held via `PT(Connection)`).
- `ConnectionReader` (`connectionReader.h`) — abstract; spins ≥1 threads that watch a mutable set of sockets and process incoming datagrams. Uses Panda's own multi-wait (`select`-style) loop after dropping NSPR's `PR_Poll`. `ConnectionListener : public ConnectionReader` (`connectionListener.h`) instead accepts connections on a rendezvous socket.
- `ConnectionWriter` (`connectionWriter.h`) — 0+ threads writing datagrams to sockets; `send(datagram, connection, block)`, `set_max_queue_size()`.
- The **queued** family adds report queues for non-blocking polling: `QueuedConnectionManager : public ConnectionManager, …` (reports resets/closes), `QueuedConnectionReader : public ConnectionReader, …` (`get_data(NetDatagram&)`), `QueuedConnectionListener : public ConnectionListener, …` (`get_new_connection()`), all built on the shared `QueuedReturn<T>` template (`queuedReturn.h`). `RecentConnectionReader : public ConnectionReader` keeps only the latest datagram.
- `NetDatagram : public Datagram` (`netDatagram.h`) — a `Datagram` that also remembers its source `Connection` and `NetAddress`. `inline constexpr int maximum_udp_datagram = 1500;`. `NetAddress` (`netAddress.h`) wraps a `Socket_Address`.
- Stream adapters bridge to the serialization layer: `DatagramSinkNet : public DatagramSink, public ConnectionWriter` and `DatagramGeneratorNet : public DatagramGenerator, public ConnectionReader, public QueuedReturn<Datagram>` let `bam`/datagram readers/writers operate over the network. `DatagramTCPHeader`/`DatagramUDPHeader` implement framing.

**How it plugs in.** `net` sits on `nativenet` (`Socket_*`) below and `express`/`putil` (`Datagram`, `DatagramSink`/`Generator`) sideways. The typical app pattern (mirrors the forum examples): create a `QueuedConnectionManager`, a `QueuedConnectionReader`, a `ConnectionWriter`, then `open_TCP_client_connection`/`server_rendezvous`, and poll the reader's queue inside a task. It is *not* wired into the data graph or render loop — it's an independent service you poll yourself.

**Where to start.** `connectionManager.cxx` (connection setup), `connectionReader.cxx` (the select/multi-wait threading core and per-epoch limits), `connectionWriter.cxx` (send queue), and the `test_tcp_*` / `test_udp.cxx` / `test_spam_*` programs in this directory as runnable references.

**Config vars (`config_net.cxx`).** `net-max-write-queue`, `net-max-response-queue` (`ConfigVariableInt`), `net-error-abort` (`ConfigVariableBool`), `net-max-poll-cycle`, `net-max-block` (`ConfigVariableDouble`), `net-max-read-per-epoch`, `net-max-write-per-epoch` (`ConfigVariableInt`, throttle bytes per thread wakeup), and `net-thread-priority` (`ConfigVariableEnum<ThreadPriority>`).

**Gotchas (community).**
- TCP datagrams are length-prefixed and bounded: oversized sends raise *"Attempt to send TCP datagram of N bytes—too long!"* — chunk large payloads (forum https://discourse.panda3d.org/t/8299). The TCP header size is configurable (see `tcp-header-size` in `downloader`, shared by the datagram header code).
- UDP receive latency in the default setup is tied to the frame/task loop; one user found removing `igLoop` killed latency but also rendering — the real fix is polling the reader on its own task, not coupling to render (forum https://discourse.panda3d.org/t/601).
- The official docs were historically thin here; community calls the connection setup "unclear in documentation" (forum https://discourse.panda3d.org/t/29819) — the `test_*.cxx` files in this dir are the most reliable reference.
- See `connectionManager.N` for the `PointerTo<Connection>` interrogate force-type directives (relevant if you add published API).

---

## nativenet

**What it is.** The low-level, platform-agnostic socket layer that everything in `net` is built on. It wraps BSD/Winsock sockets in a small C++ class family covering TCP, UDP (incoming/outgoing), listening sockets, addressing, and `select()`-based readiness checking, plus buffered datagram connections with their own ring buffers. It is deliberately thin: most methods are `inline` shims over the OS socket calls, with cross-platform glue in `socket_portable.h`.

**Central abstraction & inheritance.** `Socket_IP : public TypedObject` (`socket_ip.h`) is the base "INET domain socket," exposing `Close()`, `SetNonBlocking()`/`SetBlocking()`, `SetReuseAddress()`, `SetV6Only()`, `GetPeerName()`, raw `SOCKET` access, etc. The header even draws the hierarchy in ASCII:
- `Socket_TCP : public Socket_IP` (`socket_tcp.h`) — connected TCP socket (`SendData`/`RecvData`).
- `Socket_TCP_Listen : public Socket_IP` (`socket_tcp_listen.h`) — rendezvous/accept socket.
- `Socket_UDP_Incoming : public Socket_IP` (`socket_udp_incoming.h`) — bound UDP receiver.
- `Socket_UDP_Outgoing : public Socket_IP` (`socket_udp_outgoing.h`) — UDP sender.
- `Socket_UDP : public Socket_UDP_Incoming` (`socket_udp.h`) — combined send+receive UDP.

Addressing is `Socket_Address` (`socket_address.h`, by **rdb**, IPv4+IPv6 aware — note the `support-ipv6` var in `downloader`). `Socket_Selector` (`socket_selector.h`) and `Socket_fdset` (`socket_fdset.h`) wrap `select()` for multiplexing. `Buffered_DatagramConnection : public Socket_TCP` (`buffered_datagramconnection.h`) layers framed, buffered datagram I/O (using `Buffered_DatagramReader`/`Buffered_DatagramWriter` over `ringbuffer.h`/`membuffer.h`). The `time_*.h` headers provide a small portable clock/timeout toolkit used by the selectors.

**How it plugs in.** This is the bottom of the network stack: `net`'s `Connection`/`ConnectionReader`/`ConnectionWriter` hold and operate `Socket_*` objects; `Socket_Address` backs `NetAddress`. Nothing above `net` should touch these directly. `Buffered_DatagramConnection` is an alternative, self-contained datagram client used in some contexts independent of `net`.

**Where to start.** `socket_ip.h`/`.cxx` for the base socket lifecycle, then `socket_tcp.cxx` and `socket_udp.cxx` for the actual send/recv paths, and `socket_selector.h` for how readiness is polled. `socket_portable.h` is where you'd add OS-specific behavior.

**Config vars (`config_nativenet.cxx`).** None (only the `nativenet` notify category is defined here; IPv6 and TCP-header tuning live in `config_downloader.cxx`).

**Gotchas.** Authored largely by **drose** with IPv6/addressing work by **rdb**. The classes are intentionally low-level and lightly checked (the `socket_tcp.h` comment self-deprecates the base TCP class as "pretty useless" alone) — prefer `net` unless you specifically need raw sockets. Error handling is via `GetLastError()` return codes, not exceptions.

---

## downloader

**What it is.** The HTTP client and asset-acquisition toolkit. It implements an OpenSSL-backed HTTP/HTTPS client with cookies, auth (basic/digest), proxies, chunked/identity transfer decoding, and range requests; plus utilities for unpacking and updating assets: `Decompressor`, `Extractor`, `Patcher`, and the on-disk `DownloadDb`. Most importantly for the engine, `VirtualFileMountHTTP` lets a remote URL root be mounted into the `VirtualFileSystem`, so `.bam`/model/multifile loading can transparently pull from the web.

**Central abstraction & inheritance.**
- `HTTPClient : public ReferenceCount` (`httpClient.h`, gated by `#ifdef HAVE_OPENSSL`) — a request context holding cookies/passwords/certs; supports many simultaneous requests; has a global `HTTPClient::get_global_ptr()`.
- `HTTPChannel : public TypedReferenceCount` (`httpChannel.h`) — one request/response in flight, the workhorse you drive with a per-frame `run()` for async transfers.
- `URLSpec` (`urlSpec.h`) and `DocumentSpec` (`documentSpec.h`) — parsed URL and a URL-plus-cache-validators (ETag/date) descriptor.
- Transfer-encoding stream stack over sockets: `IBioStream`/`OBioStream : public ISocketStream`/`OSocketStream` (`bioStream.h`, OpenSSL BIO wrappers), `IChunkedStream`/`IIdentityStream` (`chunkedStream.h`/`identityStream.h`) for chunked vs. content-length bodies, plus `MultiplexStream` for tee'd output.
- Asset utilities: `Decompressor` (`decompressor.h`, pmime/zlib step-wise), `Extractor` (`extractor.h`, multifile extraction), `Patcher` (`patcher.h`, binary patch application), `DownloadDb` (`downloadDb.h`, version/manifest DB with inner `FileRecord`).
- `VirtualFileMountHTTP : public VirtualFileMount` (`virtualFileMountHTTP.h`) — "Maps a web page (URL root) into the VirtualFileSystem," constructed from a `URLSpec` and an `HTTPClient` (default global).

An `httpChannel_emscripten`/`httpClient_emscripten` variant exists for web builds (delegates to the browser's fetch instead of OpenSSL).

**How it plugs in.** `downloader` sits on `nativenet`/`net` (sockets, via the BIO streams) and OpenSSL, and plugs *up* into `express`'s `VirtualFileSystem` through `VirtualFileMountHTTP` — that's the integration point with `.bam`/multifile asset loading. `HTTPClient::get_global_ptr()` is the default client used by mounts. The asset utilities are used by deployment/patching tooling rather than the render loop.

**Where to start.** `httpChannel.cxx` is the core state machine (connect → send request → read headers → stream body), driven non-blocking by its `run()`/`get_status_code()`. `httpClient.cxx` for connection reuse, auth, and certificate handling. `virtualFileMountHTTP.cxx` to see how a remote file becomes a `VirtualFile`. For asset pipelines, `decompressor.cxx`, `extractor.cxx`, `patcher.cxx`, `downloadDb.cxx`.

**Config vars (`config_downloader.cxx`).** Throttling: `downloader-byte-rate` (`ConfigVariableInt`), `download-throttle` (`ConfigVariableBool`), `downloader-frequency`, `downloader-timeout`, `downloader-timeout-retries`. Step budgets: `decompressor-step-time`, `extractor-step-time`, `patcher-buffer-size`. HTTP: `http-proxy-tunnel` (`Bool`), `http-connect-timeout`, `http-timeout`, `http-skip-body-size`, `http-idle-timeout`, `http-max-connect-count`, `tcp-header-size`, `support-ipv6` (`Bool`), and `early-random-seed` (`Bool`, seeds OpenSSL's RNG early).

**Gotchas (community).**
- The whole HTTPS side is conditional on `HAVE_OPENSSL` (`#ifdef` in `httpClient.h`); builds without OpenSSL have no `HTTPClient`/`HTTPChannel`.
- The intended distribution pattern is to bundle assets as multifiles and mount them (forum https://discourse.panda3d.org/t/3653, https://discourse.panda3d.org/t/3316), optionally over HTTP via `VirtualFileMountHTTP`; this is also the basis of a patch system (forum https://discourse.panda3d.org/t/6162). For local multifiles use `Multifile`/`VirtualFileSystem.mount` directly (forum https://discourse.panda3d.org/t/255).
- Large transfers are designed to be *stepped*: `HTTPChannel::run()` and the `*-step-time` vars let download/decompress/extract spread work across frames instead of blocking — don't call the blocking variants on the app thread.

---

## vrpn

**What it is.** A thin client wrapper around the external VRPN (Virtual Reality Peripheral Network) library, letting Panda receive data from VR trackers, buttons, analog axes, and dials served by a remote `vrpn_server`. It's an optional build component (registers the `"VRPN"` system via `PandaSystem`) and is the canonical concrete implementation of the `ClientBase`/`ClientDevice` abstraction from `device`.

**Central abstraction & inheritance.** `VrpnClient : public ClientBase` (`vrpnClient.h`, `EXPCL_VRPN`) — "A specific ClientBase that connects to a VRPN server and records information on the connected VRPN devices." Constructed with a server name; provides `is_valid()`/`is_connected()`, overrides `make_device()`/`disconnect_device()`/`do_poll()`, and a `convert_to_secs()` helper for VRPN timestamps. The published device leaves derive from the `device` package's `Client*Device` classes:
- `VrpnTrackerDevice : public ClientTrackerDevice` (`vrpnTrackerDevice.h`)
- `VrpnButtonDevice : public ClientButtonDevice` (`vrpnButtonDevice.h`)
- `VrpnAnalogDevice : public ClientAnalogDevice` (`vrpnAnalogDevice.h`)
- `VrpnDialDevice : public ClientDialDevice` (`vrpnDialDevice.h`)

Each device is paired with a non-published per-server-object wrapper that owns the actual VRPN remote callback object and fans out to potentially several Panda devices: `VrpnTracker`, `VrpnButton`, `VrpnAnalog`, `VrpnDial` (plain classes, e.g. `class VrpnTracker {`; the `VrpnTrackerDevice` is `friend class VrpnTracker`). All VRPN headers funnel through `vrpn_interface.h`, which `#include`s `<vrpn_Connection.h>`, `<vrpn_Tracker.h>`, `<vrpn_Analog.h>`, `<vrpn_Button.h>` and works around VRPN quirks (`#undef VRPN_EXPORT_GETTIMEOFDAY`, an explicit `<stdint.h>`).

**How it plugs in.** A `VrpnClient` is a `ClientBase` *source*; you ask it for a device by type+name via `ClientBase::get_device(...)`, which calls `VrpnClient::make_device()`. The resulting `Vrpn*Device` (a `ClientDevice`, hence an `InputDevice`) is then wrapped by a `device`-package data-graph node — `TrackerNode`, `ButtonNode`, `AnalogNode`, or `DialNode` (each has a `(ClientBase*, device_name)` constructor) — to feed VR data into the data graph just like any other input device. Polling is via `ClientBase::poll()`/`do_poll()`, optionally on a forked thread (`fork_asynchronous_thread`, gated by the `asynchronous-clients` config var). Below VRPN lies its own network stack (not Panda's `net`).

**Where to start.** `vrpnClient.cxx` (server connection, device creation/dispatch, `do_poll`), then a concrete pair like `vrpnTracker.cxx` + `vrpnTrackerDevice.cxx` to see the VRPN-callback → `TrackerData` → `ClientTrackerDevice` flow. `vrpn_interface.h` documents the VRPN integration shims.

**Config vars (`config_vrpn.cxx`).** None — only the `vrpn` notify category and `init_type()` registration; it adds `"VRPN"` to `PandaSystem`. Authored by **jason**/**drose** (2001).

**Gotchas.** Build is conditional (`BUILDING_VRPN`); without the external VRPN library this whole package is absent. It reuses the older `ClientBase` polling model rather than the newer `InputDevice`/`InputDeviceManager` hot-plug path, so VRPN devices are *not* discovered by `base.devices` — you instantiate a `VrpnClient` explicitly and pull named devices from it.

---

## Known shortcomings & footguns

This cluster works as described above, but several long-standing rough edges trip up newcomers. The entries below are community-sourced (forum posts and maintainer comments), preserved verbatim. They complement the per-package "Gotchas" notes above with the higher-impact, repeatedly-reported pitfalls.

### `WindowProperties.requestProperties()` is asynchronous

**Severity: major · Status: by-design**

`requestProperties()` only *requests* a window change (size, fullscreen, cursor): it takes effect on the *next* frame and may even be silently rejected by the platform. Beginners set a property, read it back the same frame, see no change, and conclude "nothing happened." (`WindowProperties` lives in the `display` package rather than this cluster, but it is the usual entry point for the device/input plumbing here — e.g. confining or hiding the cursor — so the footgun shows up while wiring input.)

> "requestProperties() does not take effect right away, but rather will take effect
> the next frame." — drwr *(maintainer)*, [t/394](https://discourse.panda3d.org/t/394)

### Gamepad mappings are unreliable; no remapping database

**Severity: minor · Status: still-open**

The built-in input-device support (see [the `device` package](#device) above) reports incorrect axis/button mappings for non-standard controllers, because Panda has no SDL-style community mapping database to normalize them. Button/axis identities come straight from the OS HID descriptor, so the same physical button differs across back-ends and you end up hand-mapping per device. (This is the structural cause behind the "DualShock 4 behaves differently from an Xbox controller" confusion noted in the `device` gotchas.)

### High-level `DistributedObject` networking is Disney-owned, under-documented, and has no open server

**Severity: major · Status: still-open**

Panda's *high-level* networking — the `DistributedObject` system that powered ToonTown and Pirates of the Caribbean Online — is not the `net`/`nativenet` stacks documented above. Those two packages are the low-level, batteries-included path (raw sockets and queued `Datagram` delivery). The `DistributedObject` layer sits much higher up and its Python side lives in `direct`, not here (the OTP-like `direct.distributed` package — see the [`distributed` section of the direct framework page](direct-python-framework.md)). It is poorly documented and unsupported, principally because it is Disney-owned and ships no working server you can drop into your game; the manual itself punts to the forums.

> "The DistributedObject (i.e. high level) networking API is not well
> documented/supported, principally because it is Disney-owned and there isn't a
> working server/support for this... Both points are generally true." — drwr
> *(maintainer)*, [t/5533](https://discourse.panda3d.org/t/5533)

The maintained guidance is essentially "use the low-level datagram protocol ([`net`](#net) over [`nativenet`](#nativenet), above), or an external library like enet" — i.e. there is no batteries-included multiplayer story out of the box.

### `DistributedObject` creation-order pitfalls

**Severity: minor · Status: by-design**

Within that same high-level system, you can't pass required params at construction, and you can't assume that local `DistributedObject`s are created before remote ones, so late-join state sync has to be done in hand-rolled setup functions rather than constructors.

> "When a DistributedObject is not local on a machine, you can't assume any local
> DistributedObjects are created first." — russ, [t/361](https://discourse.panda3d.org/t/361)

For the object lifecycle this interacts with (`generate` / `announceGenerate` / `disable`) and the DC-file field model, see the [`distributed` section of the direct framework page](direct-python-framework.md). General reference-counting and serialization caveats that affect networked state live in [Cross-cutting concepts](../cross-cutting-concepts.md).

---

### Where to start (this cluster)

- **Understand the whole idea first:** `panda/src/dgraph/README.md` and the top doc comment of `panda/src/dgraph/dataNode.h` — they define the data graph and the data-graph-vs-scene-graph distinction that ties this cluster together.
- **See it driven end-to-end:** `direct/src/showbase/ShowBase.py` (`dgTrav`, `dataRoot`, the `__dataLoop` task at sort `-50`, and `attachInputDevice`) shows how roots get attached and traversed each frame.
- **Smallest complete `DataNode`:** `panda/src/tform/transform2sg.cxx` (data graph → scene graph bridge), then `panda/src/tform/trackball.cxx` and `panda/src/tform/mouseWatcher.cxx` for real interaction logic.
- **Input hardware:** `panda/src/device/inputDevice.h` (capability model) and `inputDeviceManager.cxx::make_global_ptr` (platform dispatch), then the platform back-end for your OS (`evdevInputDevice.cxx` / `winRawInputDevice.cxx` / `xInputDevice.cxx` / `ioKitInputDevice.cxx`).
- **Networking:** `panda/src/net/connectionManager.cxx` + `connectionReader.cxx`, with the `test_tcp_*`/`test_udp.cxx` programs as runnable examples; drop to `panda/src/nativenet/socket_ip.h`/`socket_tcp.cxx` only when you need raw sockets.
- **Downloads/assets:** `panda/src/downloader/httpChannel.cxx` (the async HTTP state machine) and `virtualFileMountHTTP.cxx` (VFS integration).
- **VR:** `panda/src/vrpn/vrpnClient.cxx` plus the `vrpnTracker.cxx`/`vrpnTrackerDevice.cxx` pair.
