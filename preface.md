# Preface #

This is an **unofficial engine developer manual** for Panda3D, for those who
want to understand, debug, and modify the **engine internals**, not just use it
to make games. (For the user-facing manual, see the official docs at
<https://docs.panda3d.org>.)

The manual is organized in several parts:

 1. **[Source tree](source-tree.md)** — a developer's map of the codebase: one
    entry per directory, saying what it is and where to start reading.

 2. **[Engine subsystems](subsystems/index.md)** — source-grounded deep-dives into
    each major subsystem (audio, dtool, the scene graph, characters &
    animation, collision & physics, …): the central classes, inheritance,
    entry points, and gotchas, with cited community context.

 3. **[Cross-cutting concepts](cross-cutting-concepts.md)** — the foundational
    patterns every subsystem relies on: the `TypeHandle` type system, reference
    counting & `PointerTo`, BAM serialization, the threaded pipeline cycler, and
    interrogate Python bindings. **Read this first.**

 4. **[File formats & reference](reference/index.md)** — egg-file syntax, the config (PRC)
    system, render-order/cull bins, the GraphicsEngine, and other reference
    material. Some of this is older legacy documentation.

 5. **Miscellaneous & F.A.Q.**, and the **Appendix**.

**On currency.** Parts 1–3 were re-derived from the Panda3D `master` branch
(the 1.11 development line, post-`v1.10.16`) and verified against the actual
source code. Part 4 retains older material — some of it dates back to the
Disney/CMU era (2002 onward) and may describe deprecated APIs; it is kept for
its still-useful reference content (egg syntax, PRC, etc.), but treat specific
API details there with appropriate suspicion and check against the source.

**Primary source of truth.** Throughout, the C++/Python source code is the
authority. File paths are given relative to the repository root (e.g.
`panda/src/audio/audioManager.h`). When in doubt, read the code.
