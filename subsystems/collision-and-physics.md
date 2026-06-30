# Collision & physics

Panda3D ships **four independent collision/physics subsystems** that a developer must not confuse. `panda/src/collide` is Panda's own *detection-only* collision engine (shapes + a scene-graph traverser + pluggable response handlers). `panda/src/physics` is a tiny *native particle/force* integrator with no rigid-body constraints. `panda/src/bullet` and `panda/src/ode` are thin C++ wrappers around two third-party rigid-body engines (Bullet and the Open Dynamics Engine). They share two cross-cutting concepts only: every one exposes a `PandaNode` (or, for ODE, a plain `TypedObject`) so it can hang in or alongside the scene graph, and all use the engine-wide `CollideMask` (`BitMask32`) for from/into filtering. The big mental model: **native collide = detection with you writing the response; Bullet/ODE = full dynamics you let the engine simulate; physics = forces on point masses.**

## collide

**What it is.** The native collision system. You build *solids* (sphere, box, capsule, ray, segment, polygon, plane, parabola, heightfield…), group them into `CollisionNode`s in the scene graph, register the moving ones ("colliders") with a `CollisionTraverser`, and once per frame call `traverser.traverse(root)`. The traverser walks the scene graph below `root`, does bounding-volume culling, runs the actual shape-vs-shape intersection tests, packages each hit as a `CollisionEntry`, and dispatches the entries to a `CollisionHandler` you chose. It is **detection plus dispatch only** — it never integrates forces; any "physical" response (pushing, gravity, floor-snapping) is implemented inside specific handlers, not in the core.

**Central abstraction — `CollisionSolid` and double dispatch.** `panda/src/collide/collisionSolid.h` is the `CopyOnWriteObject`-derived base for every shape. Its header comment states it works "very similarly to the way `BoundingVolume` … work[s]. There's a different subclass for each basic shape of solid, and double-dispatch function calls handle the subset of the N\*N intersection tests that we care about." The mechanism: a *from* solid implements `test_intersection(entry)` which calls `entry.get_into()->test_intersection_from_<myshape>(entry)` — the second virtual call resolves on the *into* solid's runtime type, so the right pairwise routine runs without any `switch`. Example, `collisionSphere.cxx:59`:

```cpp
PT(CollisionEntry) CollisionSphere::
test_intersection(const CollisionEntry &entry) const {
  return entry.get_into()->test_intersection_from_sphere(entry);
}
```

Unimplemented pairs fall through to `CollisionSolid::report_undefined_from_intersection` / `report_undefined_intersection_test` (collisionSolid.cxx) which emit a warning, so adding a shape that "can't collide into X" degrades gracefully rather than crashing.

**Which solids may be "from" vs "into".** Only shapes that override `test_intersection` are legal *colliders* (the moving "from" object). Grepping the implementations, that set is exactly: `CollisionBox`, `CollisionCapsule`, `CollisionLine`, `CollisionSegment`, `CollisionRay`, `CollisionParabola`, `CollisionSphere`, `CollisionInvSphere` (collisionBox.cxx, collisionCapsule.cxx, collisionLine.cxx, collisionSegment.cxx, collisionRay.cxx, collisionParabola.cxx, collisionSphere.cxx, collisionInvSphere.cxx). `CollisionPolygon`, `CollisionPlane`, `CollisionHeightfield`, and `CollisionFloorMesh` are **into-only** — they have `test_intersection_from_*` methods but no `test_intersection`. This is why polygon-into-polygon detection is impossible; see the trusted answer "CollisionPolygon into CollisionPolygon?" (<https://discourse.panda3d.org/t/27424>): *"With Panda's internal collision system"* you cannot use a polygon as a from-object.

**Key classes / files and inheritance:**
- `CollisionSolid` (`collisionSolid.h`) → concrete solids: `CollisionSphere` (`collisionSphere.h`), `CollisionBox` (`collisionBox.h`), `CollisionCapsule` (`collisionCapsule.h`, formerly `CollisionTube` — the bam reader still records the obsolete type name, see config_collide.cxx:163), `CollisionRay` (`collisionRay.h`) → `CollisionLine` (`collisionLine.h`), `CollisionSegment` (`collisionSegment.h`), `CollisionParabola` (`collisionParabola.h`), `CollisionPlane` (`collisionPlane.h`) → `CollisionPolygon` (`collisionPolygon.h`) → `CollisionGeom` (`collisionGeom.h`), `CollisionSphere` → `CollisionInvSphere` (`collisionInvSphere.h`), `CollisionHeightfield` (`collisionHeightfield.h`), `CollisionFloorMesh` (`collisionFloorMesh.h`).
- `CollisionNode` (`collisionNode.h`) — `PandaNode` subclass holding `pvector<COWPT(CollisionSolid)>`; carries the **from** mask (`_from_collide_mask`) and inherits the **into** mask from `PandaNode::set_into_collide_mask`. Two solids collide only if `from_mask & into_mask` is non-zero. Note the comment at `collisionNode.h:106`: solids/masks are **not pipeline-cycled** — "We assume the collision traversal will take place in App only."
- `CollisionTraverser` (`collisionTraverser.h`) — a `Namable` (NOT a node). Owns `Colliders` (`pmap<NodePath, PT(CollisionHandler)>`) and dispatches via three width-specialized traversal paths: `r_traverse_single` / `_double` / `_quad`, selected by how many colliders share a pass (controlled by `allow-collider-multiple`; uses one-word `BitMask`, `DoubleBitMask`, or `QuadBitMask`).
- `CollisionEntry` (`collisionEntry.h`) — one detected hit. `TypedWritableReferenceCount`. Carries from/into solids and nodes, parametric `t`, and optional `surface_point` / `surface_normal` / `interior_point` / `contact_pos` / `contact_normal` (each `has_*`-guarded). Handlers read these to compute responses. All getters take a `NodePath space` so coordinates are returned relative to whatever frame you ask for.
- `CollisionHandler` (`collisionHandler.h`) abstract; concrete tree: `CollisionHandlerQueue` (`collisionHandlerQueue.h`, just records sorted entries for you to inspect), `CollisionHandlerEvent` (`collisionHandlerEvent.h`, throws Panda events on enter/again/exit) → `CollisionHandlerPhysical` (`collisionHandlerPhysical.h`, abstract base for handlers that *move* the collider) → `CollisionHandlerPusher` (`collisionHandlerPusher.h`, wall-sliding) → `CollisionHandlerFluidPusher`, plus `CollisionHandlerFloor` (`collisionHandlerFloor.h`, snap to ground) and `CollisionHandlerGravity` (`collisionHandlerGravity.h`, the usual character-controller handler). `CollisionHandlerHighestEvent` is a variant of the event handler.

**How it plugs in.** The traverser is *independent of the cull/draw pipeline*: you drive it yourself, normally from a task. `CollisionNode::cull_callback` (collisionNode.h:45) lets collision geometry optionally render its viz. `CollisionNode` links against `p3tform` (CMakeLists.txt:88) because handlers like the pusher use `DriveInterface` (collisionHandlerPhysical.h includes `driveInterface.h`). The native `physics` module bridges here through `PhysicsCollisionHandler` (in `panda/src/physics`, derives from `CollisionHandlerPusher`) — that's the one place collide and the native physics engine touch. There is no auto-update: forgetting to add the traverse task is the single most common "nothing collides" bug.

**Where to start (entry points).**
- Add a new *shape*: create `collisionXxx.h/.cxx`, derive from `CollisionSolid`, implement `make_copy`, `get_collision_origin`, `compute_internal_bounds`, the `test_intersection_from_*` you support, and (if it can be a collider) `test_intersection`. Register it in `config_collide.cxx` (`init_type` + `register_with_read_factory`) and add to `CMakeLists.txt`.
- Add/fix a *response*: subclass `CollisionHandler` (or `CollisionHandlerPhysical` if it moves bodies) and implement `add_entry` / `end_group` (+`handle_entries`/`apply_linear_force` for physical handlers).
- Debug a *miss*: start in `CollisionTraverser::traverse` → `prepare_colliders_*` → `r_traverse_*` → `compare_collider_to_*` (collisionTraverser.cxx). Turn on `DO_COLLISION_RECORDING` builds and use `traverser.show_collisions(root)` (`CollisionVisualizer`, collisionVisualizer.h) plus per-solid `show()` to see bounds.

**Gotchas / rationale (community).**
- *"Are CollisionRays meant to strike geometry only?"* (trusted, <https://discourse.panda3d.org/t/11777>): rays detect `CollisionNode`s and their polygons by default; visible geometry is **not** collidable unless you set its into mask / use a `CollisionNode`. New devs constantly forget that visible model geometry needs `setCollideMask`/`CollisionNode` to be an into-object.
- *Bit masks decide everything*: `from_mask & into_mask != 0` is the gate; an all-zero into mask = invisible to collisions.
- *Performance*: combining `CollisionNode`s is dangerous — see `flatten-collision-nodes` below — because the system "relies heavily on bounding volume tests to be efficient" (config_collide.cxx:81).

**Config variables (config_collide.cxx):** `respect-prev-transform` (false — opt-in motion/CCD per traverser), `respect-effective-normal` (true — lets polygons report a faked normal for smooth floors/ramps), `allow-collider-multiple` (false — Double/QuadBitMask multi-collider passes), `flatten-collision-nodes` (false — guards against merging bounds), `collision-parabola-bounds-threshold` / `-sample`, `fluid-cap-amount`, `pushers-horizontal`.

## physics

**What it is.** Panda's *original, lightweight native physics*: not rigid bodies, but **point masses with forces and an Euler integrator**. You attach `Physical` objects (each holding one or more `PhysicsObject` point masses) and `LinearForce`/`AngularForce` instances to a `PhysicsManager`, pick a `LinearIntegrator` + `AngularIntegrator`, and call `manager.do_physics(dt)` each frame. There are **no constraints, no collision shapes, and no contact solving** of its own — it's the engine behind ParticleSystems and simple "thing affected by gravity/wind/friction" actors. For anything needing stacking, joints, or accurate contacts, use Bullet.

**Central abstraction.** `Physical` (`physical.h`, `TypedReferenceCount`) is "a set of physically modeled attributes. If you want physics applied to your class, derive it from this." It owns a `PhysicsObject::Vector`, plus per-object `LinearForce`/`AngularForce` vectors, and a convenience `_phys_body` pointer to the single object when there's only one. `PhysicsObject` (`physicsObject.h`) is the actual particle (position, velocity, mass, orientation). The force hierarchy roots at `BaseForce` (`baseForce.h`, "pure virtual base class for all forces that could POSSIBLY exist") → `LinearForce` (`linearForce.h`) and `AngularForce` (`angularForce.h`).

**Key classes / files:**
- `PhysicsManager` (`physicsManager.h`) — top-level coordinator. Crucial design note in its header: *"the physicals container is NOT reference counted"* — a `Physical` removes itself from its manager on death, so you must keep your own `PT` to it. `do_physics(dt)` applies global forces, then runs the integrators over every attached `Physical`.
- `PhysicsObject` (`physicsObject.h`), `PhysicsObjectCollection` (`physicsObjectCollection.h`).
- Linear forces (all `LinearForce` subclasses, each `make_copy` + `get_child_vector`): `LinearVectorForce`, `LinearRandomForce`, `LinearFrictionForce`, `LinearSourceForce`, `LinearSinkForce`, `LinearJitterForce`, `LinearNoiseForce`, `LinearCylinderVortexForce`, `LinearDistanceForce`, `LinearControlForce`, `LinearUserDefinedForce` (files `linear*Force.h`). Angular: `AngularVectorForce` (`angularVectorForce.h`). A force can be mass-dependent or not (`set_mass_dependent`) and per-axis masked (`set_vector_masks`).
- Integrators: `BaseIntegrator` (`baseIntegrator.h`) → `LinearIntegrator`/`AngularIntegrator` → `LinearEulerIntegrator` (`linearEulerIntegrator.h`), `AngularEulerIntegrator` (`angularEulerIntegrator.h`). Only Euler is provided.
- Scene-graph glue: `ForceNode` (`forceNode.h`, hangs a force in the graph so it inherits a transform), `PhysicalNode` (`physicalNode.h`, `PandaNode` holding `Physical`s; `safe_to_flatten()` returns **false**), and `ActorNode` (`actorNode.h`) → derives from `PhysicalNode` and "assumes responsibility for its own transform": `transform_changed()` copies PandaNode→PhysicsObject ("shoves") and `update_transform()` copies PhysicsObject→PandaNode, so external moves and simulated moves stay in sync.
- `PhysicsCollisionHandler` (`physicsCollisionHandler.h`) — the bridge to `collide`: a `CollisionHandlerPusher` that also injects friction and forces into the colliding `ActorNode`'s `PhysicsObject` (`apply_friction`, `apply_net_shove`, `apply_linear_force`). This is how native physics gets collision response — it *borrows* the collide traverser.

**How it plugs in.** Entirely manual and pull-based: nothing integrates physics for you. A `PhysicsManager` is a free object; `ForceNode`/`PhysicalNode` only exist to give forces and bodies a scene-graph transform. Collision is *not* built in — you pair it with a `CollisionTraverser` + `PhysicsCollisionHandler`. `p3physics` links only against `panda` (CMakeLists.txt:44).

**Where to start (entry points).** New force: subclass `LinearForce`/`AngularForce`, implement `make_copy` + `get_child_vector` (the per-object force vector), register in `config_physics.cxx`. Integration/step bugs: read `PhysicsManager::do_physics` (physicsManager.cxx) and `linearEulerIntegrator.cxx` / `angularEulerIntegrator.cxx`. Transform-sync bugs (body teleports / doesn't follow node): `actorNode.cxx` `transform_changed` / `update_transform` and `_transform_limit`.

**Gotchas / rationale (community).** When asked to compare the native engine, ODE and Bullet (e.g. <https://discourse.panda3d.org/t/13096>, <https://discourse.panda3d.org/t/14907>), the consensus is that the native module is fine for particles and simple force-driven motion but lacks rigid-body dynamics; *"you are much better off with Panda Bullet"* for real physics. The manager-doesn't-own-physicals rule is the classic memory footgun: drop your last reference and the body silently vanishes from the sim.

**Config variables (config_physics.cxx):** none are registered as `ConfigVariable`s; only a notify category `physics` is defined. `PhysicsManager::_random_seed` is a `ConfigVariableInt` declared on the class (physicsManager.h:84) and seeds the random forces (`init_random_seed`).

## bullet

**What it is.** A wrapper around the **Bullet** rigid-body/soft-body engine (`enn0x`, 2010). `BulletWorld` owns a `btDiscreteDynamicsWorld`; Panda node subclasses wrap Bullet's collision objects; `BulletShape` subclasses wrap `btCollisionShape`. You build bodies as ordinary scene-graph nodes, `world.attach(node)` them, and call `world.do_physics(dt, max_substeps, stepsize)` each frame — the wrapper copies transforms scene-graph→Bullet before stepping and Bullet→scene-graph after, so your visible models follow the simulation automatically. This is the **recommended** engine for new projects.

**Central abstraction — `BulletBodyNode` and the shape wrapper.** `BulletBodyNode` (`bulletBodyNode.h`, a `PandaNode`) is the abstract base for everything with a Bullet collision object; it manages a list of `BulletShape`s (with per-shape local transforms), the into-mask, kinematic/static flags, and contact-notification flags. Its concrete subclasses:
- `BulletRigidBodyNode` (`bulletRigidBodyNode.h`) — wraps `btRigidBody`: mass/inertia, linear/angular velocity, damping, `apply_force`/`apply_impulse`/`apply_torque`, sleep thresholds, per-axis `linear_factor`/`angular_factor`, and the all-important `do_sync_p2b()` (Panda→Bullet) / `do_sync_b2p()` (Bullet→Panda).
- `BulletGhostNode` (`bulletGhostNode.h`) — `btGhostObject`: detects overlaps but applies **no** physical response (triggers/sensors).
- `BulletSoftBodyNode` (`bulletSoftBodyNode.h`) — cloth/rope/volumetric `btSoftBody`.
- `BulletBaseCharacterControllerNode` / `BulletCharacterControllerNode` (`bulletCharacterControllerNode.h`) — kinematic capsule controller.

`BulletShape` (`bulletShape.h`, `TypedWritableReferenceCount`) is the abstract base whose pure virtual `btCollisionShape *ptr()` hands the raw Bullet shape to the body. Subclasses: `BulletBoxShape`, `BulletSphereShape`, `BulletCapsuleShape`, `BulletCylinderShape`, `BulletConeShape`, `BulletPlaneShape`, `BulletConvexHullShape`, `BulletConvexPointCloudShape`, `BulletMultiSphereShape`, `BulletMinkowskiSumShape`, `BulletTriangleMeshShape` (+ `BulletTriangleMesh`), `BulletHeightfieldShape`, `BulletSoftBodyShape` (files `bullet*Shape.h`).

**Other key pieces:** `BulletWorld` (`bulletWorld.h`) — gravity, `do_physics`, `attach`/`remove`, ray/sweep/contact queries (`ray_test_closest`/`ray_test_all` → `BulletClosestHitRayResult`/`BulletAllHitsRayResult`; `sweep_test_closest`; `contact_test`/`contact_test_pair` → `BulletContactResult`), manifolds, and debug node. Constraints root at `BulletConstraint` (`bulletConstraint.h`): `BulletHingeConstraint`, `BulletConeTwistConstraint`, `BulletSliderConstraint`, `BulletSphericalConstraint` (ball-socket), `BulletGenericConstraint` (files `bullet*Constraint.h`). `BulletVehicle`/`BulletWheel` provide the raycast-vehicle. `BulletDebugNode` (`bulletDebugNode.h`) renders wireframes. `bullet_includes.h` pulls in the Bullet API; `bullet_utils.h/.cxx` convert `LMatrix4`↔`btTransform`, `LVecBase3`↔`btVector3`.

**How it plugs in (transform sync — the crux).** `BulletWorld::do_physics` (bulletWorld.cxx:231) calls `do_sync_p2b(dt, num_substeps)` for every attached body/softbody/ghost/character, steps `btDynamicsWorld::stepSimulation`, then `do_sync_b2p()` writes results back (lines 261–303). Each `BulletRigidBodyNode` overrides `transform_changed()` and `parents_changed()` so that moving or **reparenting** a node updates the Bullet transform. That reparent hook is a real fix, not theory: trusted commit *"bullet: sync rigid body transform when node is reparented"* (commits:f183d901…, fixes #629) — *"Reparenting a node will change its net transform, so it should cause a transform sync."* `BulletBodyNode::add_shapes_from_collision_solids(CollisionNode*)` (bulletBodyNode.h:54) converts native `collide` solids into Bullet shapes — the one explicit bridge from the native system. Bullet reuses Panda's `CollideMask` for filtering (see trusted docs <https://docs.panda3d.org/1.10/python/programming/physics/bullet/collision-filtering>: *"Two objects collide if the two masks have at least one bit in common"*) when `bullet-filter-algorithm` is `FA_mask`.

**Where to start (entry points).** New shape: subclass `BulletShape`, implement `ptr()`, register in `config_bullet.cxx`, add to `CMakeLists.txt`. Stepping/sync bugs: `bulletWorld.cxx` `do_physics`/`do_sync_p2b`/`do_sync_b2p` and `bulletRigidBodyNode.cxx` `transform_changed`/`do_transform_changed`. Query bugs: `bullet*RayResult.*`, `bulletContactResult.*`. Constraints: `bulletConstraint.cxx` + the specific joint.

**Gotchas / rationale (community).** Bullet is the maintainer-recommended engine — maintainer `rdb` (trusted, <https://discourse.panda3d.org/t/28943>): *"currently Bullet is much more popular than ODE."* Common pitfalls surfaced in the forum: a static (mass 0) body never moves even if you set its transform unless it's kinematic; triangle-mesh shapes are concave and may only be static; and soft-body↔rigid-body joints need `appendLinearJoint`/`appendAnchor` (<https://discourse.panda3d.org/t/13502>). `do_physics` is marked `BLOCKING` — it releases the GIL but must run in App.

**Config variables (config_bullet.cxx):** `bullet-max-objects` (1024), `bullet-gc-lifetime` (256), `bullet-broadphase-algorithm` (`BA_dynamic_aabb_tree`), `bullet-filter-algorithm` (`FA_mask`), `bullet-sap-extents` (1000.0), `bullet-enable-contact-events` (false), `bullet-split-impulse` (false), `bullet-solver-iterations` (10), `bullet-additional-damping` (false) and its four `bullet-additional-damping-*` tuning values.

## ode

**What it is.** A wrapper around the **Open Dynamics Engine**. Unlike Bullet, the ODE classes are **not scene-graph nodes** — `OdeWorld`, `OdeBody`, `OdeGeom`, `OdeSpace`, `OdeJoint` are plain `TypedObject`s that hold raw ODE handles (`dWorldID`, `dBodyID`, `dGeomID`, `dSpaceID`, `dJointID`); `OdeMass` is a `TypedReferenceCount` that wraps a `dMass` inertia-tensor struct (not a handle). You therefore drive ODE more like the raw C API and **copy transforms yourself** between an `OdeBody` and the `NodePath` you want it to control (there is no `transform_changed` auto-sync inside `OdeBody` — `grep` finds no `NodePath` member; the convenience sync lives in higher-level Python `direct` code, not in this C++ module). Functional but, per the community, the less-polished option.

**Central abstractions.**
- `OdeWorld` (`odeWorld.h`) wraps `dWorldID`: gravity, ERP/CFM (error-reduction / constraint-force-mixing), `step()` vs `quick_step()` (the iterative `quick_step_num_iterations` solver), auto-disable thresholds, and a surface-parameter table (`init_surface_table`, `set_surface_entry`, per-body dampening) used by `OdeUtil::collide` to build contacts.
- `OdeBody` (`odeBody.h`) wraps `dBodyID`: `set_position`/`set_quaternion`, velocities, forces/torques, and an `OdeMass` (`odeMass.h`, the inertia tensor).
- `OdeGeom` (`odeGeom.h`, base for collision shapes wrapping `dGeomID`): `OdeSphereGeom`, `OdeBoxGeom`, `OdeCylinderGeom`, `OdeCappedCylinderGeom`, `OdePlaneGeom`, `OdeRayGeom`, `OdeConvexGeom`, `OdeTriMeshGeom` (+ `OdeTriMeshData`) — files `ode*Geom.h`.
- `OdeSpace` (`odeSpace.h`) is the broadphase: `OdeSimpleSpace`, `OdeHashSpace`, `OdeQuadTreeSpace` (`odeSimpleSpace.h`, `odeHashSpace.h`, `odeQuadTreeSpace.h`).
- `OdeJoint` (`odeJoint.h`, wraps `dJointID`): `OdeHingeJoint`, `OdeHinge2Joint`, `OdeBallJoint`, `OdeSliderJoint`, `OdeUniversalJoint`, `OdeAMotorJoint`, `OdeLMotorJoint`, `OdeFixedJoint`, `OdeNullJoint`, `OdePlane2dJoint`, `OdeContactJoint` (files `ode*Joint.h`); joints live in an `OdeJointGroup` (`odeJointGroup.h`). `OdeJointFeedback` (in `odeJoint.h`) wraps `dJointFeedback`.
- Contacts/collision: `OdeContact` / `OdeContactGeom` (`odeContact.h`, `odeContactGeom.h`) describe a contact point; `OdeSurfaceParameters` (`odeSurfaceParameters.h`) holds friction/bounce; `OdeContactJoint` is the transient joint created per contact each step; `OdeCollisionEntry` (`odeCollisionEntry.h`) and `OdeUtil` (`odeUtil.h`) wrap `dSpaceCollide`/near-callbacks.

**How it plugs in.** The classic ODE loop is fully manual: `space.collide(...)` (or `OdeUtil::collide`) → for each near pair create `OdeContactJoint`s in a `OdeJointGroup` → `world.quick_step(dt)` → `jointGroup.empty()` → copy each `OdeBody` pose onto its `NodePath`. Because nothing here is a `PandaNode`, ODE objects never appear in the scene graph; the binding to visuals is whatever copying you write. `bullet_utils`-style conversions live in `odeHelperStructs.h`/`ode_includes.h`. The library defines its own notify categories (`ode`, `odeworld`, `odebody`, `odejoint`, `odespace`, `odegeom` — config_ode.cxx).

**Where to start (entry points).** Stepping/solver: `odeWorld.cxx` (`step`/`quick_step`, ERP/CFM, auto-disable, surface table). Collision/contacts: `odeUtil.cxx`, `odeSpace.cxx`, `odeContact*.cxx`, `odeContactJoint.cxx`. New geom/joint: subclass `OdeGeom`/`OdeJoint`, register in `config_ode.cxx`, add to `CMakeLists.txt`. Sync/pose bugs are almost always in *your* copy code, not the wrapper.

**Gotchas / rationale (community).** ODE is **stable but not a development focus**. Maintainer `rdb` (trusted, <https://discourse.panda3d.org/t/28943>): there are *"no plans at present to remove ODE,"* it *"is not a maintenance burden,"* but it is not being actively developed. Direct user experience is blunt — *"I found Panda's ODE wrapping to be very buggy and incomplete"* (<https://discourse.panda3d.org/t/14907>). Practical takeaway for a contributor: prefer extending Bullet unless you specifically need ODE; if you touch ODE, expect to fill gaps. There is no contact response without manually creating `OdeContactJoint`s — forgetting that step yields bodies that interpenetrate freely.

**Config variables (config_ode.cxx):** none registered (no `ConfigVariable*`); only notify categories are defined. Tuning (gravity, ERP, CFM, auto-disable, surface params) is done through `OdeWorld` setters at runtime, mirroring ODE's own API rather than Panda's PRC config.

## Known shortcomings & footguns

The four subsystems above are battle-tested but carry a long tail of community-mined footguns — places where the design, the defaults, or the history bite developers. The catalogue below is community-sourced opinion and history; quotes are preserved verbatim from maintainers and the issue tracker.

### Native collision: no polygon-polygon; long-standing solid-test matrix gaps
**Severity: major · Status: mitigated (matrix slowly filled)**

The built-in system never supported polygon-polygon tests, and the into-test matrix had holes (e.g. capsule-into-polygon was simply *not implemented* — it falsely reported collisions — until 1.10.13). This is the practical face of the into-only solids and double-dispatch matrix described under [collide](#collide) above (`CollisionPolygon` has no `test_intersection`, so it can never be a "from" object).

> "Panda does not currently support polygon-polygon tests; just sphere-polygon and
> line-polygon." — drwr *(maintainer)*, [t/356](https://discourse.panda3d.org/t/356)

### Colliding against *visible* geometry is very slow and easy to enable by accident
**Severity: major · Status: still-open (rdb agrees the design is wrong)**

If a "from" mask overlaps `GeomNode.getDefaultCollideMask()` (bit 20, set on all visible geometry), Panda silently turns visible geometry into collision geometry on the fly — orders of magnitude slower — and people enable it accidentally. (The "visible geometry isn't collidable unless you opt it in" rule and the `from_mask & into_mask` gate are covered in the collide Gotchas above.)

> "the way collision-with-visible-geometry is configured makes it easy to shoot
> yourself in the foot accidentally. Having some kind of a special, explicit
> collision solid... would indeed be a better design." — rdb *(maintainer)*,
> [#1846](https://github.com/panda3d/panda3d/issues/1846)

### "from" vs "into" masks and the magic default bit-20 confuse everyone
**Severity: minor (very common) · Status: by-design**

The asymmetric from/into `BitMask32` model (the engine-wide `CollideMask`, see [Cross-cutting concepts](../cross-cutting-concepts.md)) plus the magic default into-bit generates a steady stream of "collide mask not working / everything is slow" questions (see the previous entry).

### Fast objects tunnel through thin geometry; built-in has no CCD, Bullet's is incomplete
**Severity: major · Status: mitigated (Bullet CCD exists but limited)**

The classic "bullet passes through the wall." The built-in system has no continuous collision (note `respect-prev-transform` is opt-in per traverser); Bullet's CCD itself doesn't respect group/collision masks ([#504](https://github.com/panda3d/panda3d/issues/504), open).

### `CollisionHandlerPusher` gets stuck at convex corners
**Severity: major · Status: mitigated**

At a convex corner ≤90°, two polygons push the sphere along opposing normals whose lateral components cancel, jamming the character — *the* reason sample Roaming Ralph was filed as using an "inferior" method ([#565](https://github.com/panda3d/panda3d/issues/565)).

> "both are shoving the sphere out of it, but since you're coming at them from the
> opposite angle, both shoves' X coordinates are cancelling each other out." —
> rdb *(maintainer)*, [#879](https://github.com/panda3d/panda3d/issues/879)

### `CollisionHandlerFloor` jitter / "falls through floor at high velocity"
**Severity: minor · Status: still-open (tuning footgun)**

`setMaxVelocity` is a sharp trade-off (too high → sinks through floor; too low → jitter and gliding down slopes), with confusing `setOffset`/`setReach`.

### Bullet ↔ scene-graph transform sync bugs (reparent / scale / drift)
**Severity: major · Status: partially-fixed**

Keeping Bullet and the scene graph in sync is Panda's job (the `do_sync_p2b`/`do_sync_b2p` machinery described under [bullet](#bullet) above) and has bugs: rotation zeroed on first `do_physics()` after placement ([#629](https://github.com/panda3d/panda3d/issues/629), fixed); `setScale` on a rigid body makes the sim "go crazy" because Bullet dislikes scale/shear ([#328](https://github.com/panda3d/panda3d/issues/328), open); child nodes drift proportional to speed ([#617](https://github.com/panda3d/panda3d/issues/617), open).

> "Bullet generally doesn't like scaling (or shearing)." — Moguri *(maintainer)*,
> [#328](https://github.com/panda3d/panda3d/issues/328)

### Bullet is scale/units-sensitive; single precision is the default
**Severity: major · Status: by-design (inherent to Bullet)**

Too-small/large objects or excessive forces (gravity 98 vs 9.8) cause deep interpenetration → huge restitution → jitter/"explosions." Panda builds Bullet in single precision by default; double requires recompiling. Collision `margin` must be hand-tuned.

### `doPhysics(dt)` is framerate-dependent unless you pass max-substeps
**Severity: major · Status: by-design (footgun in default arg)**

The second parameter (max substeps) of `world.do_physics` defaults to 1, so when frame rate drops below the 60 Hz internal step the simulation silently runs in slow motion — passing `dt` isn't enough.

> "The problem is actually that you have not specified a maximum number of substeps
> as the second parameter of doPhysics. The default is 1." — rdb *(maintainer)*,
> [#325](https://github.com/panda3d/panda3d/issues/325)

### Bullet's character controller is generic; you're expected to write your own
**Severity: major · Status: by-design / mitigated**

The bundled `BulletCharacterControllerNode` nudges (and is nudged by) dynamic bodies (an upstream Bullet bug with no API to fix it), and box shapes "get stuck rather easily." enn0x's consistent advice: write your own.

> "Character controller nudges objects and is nudged by objects." (OPEN ISSUES) —
> enn0x, [t/9601](https://discourse.panda3d.org/t/9601)

### The old built-in PhysicsManager/ActorNode is "rarely used" and quietly discouraged
**Severity: historical · Status: effectively-abandoned**

The Disney-era force-based physics (the native [physics](#physics) module above) never grew into a real rigid-body engine. Maintainers steer users to Bullet (real dynamics) or bare collision (basic movement). Remember the ownership caveat noted above: `PhysicsManager` does **not** reference-count its physicals (see the reference-counting discussion in [Cross-cutting concepts](../cross-cutting-concepts.md)), so dropping your last `PT` silently removes the body from the sim.

> "ActorNode is part of the rarely used built-in physics system." — rdb
> *(maintainer)*, [t/27136](https://discourse.panda3d.org/t/27136)

### ODE support is half-baked and effectively superseded by Bullet
**Severity: major · Status: effectively-abandoned**

ODE got only "rudimentary direct support" (consistent with the fully-manual, not-a-`PandaNode` design described under [ode](#ode) above); you write glue copying transforms each frame, ODE and Panda's collision systems can't be combined, and there were real double-precision bugs (collisions into `OdeTriMesh` passing through on distro builds, [#174](https://github.com/panda3d/panda3d/issues/174)).

### The old Particle Panel / particle system is clunky and buggy
**Severity: minor · Status: still-open (legacy)**

The Tkinter Particle Panel is hard to use, has broken factories (Z-Spin), and save bugs (sprite particles → "SpriteAnim not defined", [#544](https://github.com/panda3d/panda3d/issues/544)).

### `CollisionTube` was a misnomer (it's a capsule)
**Severity: minor · Status: fixed (renamed `CollisionCapsule`, alias kept)**

Renaming was held up purely by the need to write the old name into older `.bam` files (the bam reader still records the obsolete type name, see config_collide.cxx:163 above) — illustrating how the legacy serialization format makes even trivial API cleanups expensive ([#347](https://github.com/panda3d/panda3d/issues/347)). On the `.bam` versioning machinery this constrains, see [Cross-cutting concepts](../cross-cutting-concepts.md).

### Where to start (this cluster)

- **Pick the right subsystem first.** Detection only, you write the response, lots of ray/shape picking → `panda/src/collide`. Real rigid-body dynamics, joints, vehicles, recommended → `panda/src/bullet`. Particles / simple force-driven motion → `panda/src/physics`. Legacy ODE projects → `panda/src/ode` (stable, unmaintained).
- **Native collide reading order:** `collisionSolid.h` (double-dispatch contract) → a concrete pair like `collisionSphere.cxx` (`test_intersection` + `test_intersection_from_sphere`) → `collisionTraverser.cxx` (`traverse` → `prepare_colliders_*` → `r_traverse_*` → `compare_collider_to_*`) → `collisionEntry.h` → a handler (`collisionHandlerGravity.cxx` is the most instructive). Config knobs in `config_collide.cxx`.
- **Bullet reading order:** `bulletWorld.h/.cxx` (`do_physics`, `do_sync_p2b`/`b2p`, queries) → `bulletBodyNode.h` → `bulletRigidBodyNode.h/.cxx` (`transform_changed`, force API) → `bulletShape.h` (+ one concrete shape). Conversions in `bullet_utils.cxx`; tuning in `config_bullet.cxx`.
- **Physics reading order:** `physicsManager.h` (ownership caveat) → `physical.h`/`physicsObject.h` → `linearForce.h` + one force → `actorNode.cxx` (transform sync) → `physicsCollisionHandler.h` (the bridge to `collide`).
- **ODE reading order:** `odeWorld.h` (solver/surface table) → `odeBody.h`/`odeMass.h` → `odeSpace.h` + `odeUtil.cxx` (collision) → `odeContactJoint.cxx` + `odeJointGroup.h` (the manual contact loop).
- **One sentence to remember:** native `collide` and the two third-party engines are *separate worlds* — they only meet via `CollideMask` filtering, `BulletBodyNode::add_shapes_from_collision_solids`, and `PhysicsCollisionHandler`; do not expect a Bullet body to be seen by a `CollisionTraverser` or vice versa.
