# Engine subsystems #

Source-grounded deep-dives into the major Panda3D subsystems, written for
developers who want to **read, debug, and modify the engine**. Each page
documents one cluster of related `panda/src` (or `dtool`/`direct`/`pandatool`)
directories and, for every directory, covers:

- what it is and the central abstraction,
- the key classes, their roles, and the inheritance chain (with real file paths),
- how it plugs into the rest of the engine,
- **where to start reading** if you wanted to fix a bug or add a feature there,
- design rationale and gotchas drawn from ~20 years of community discussion
  (forum, Discord, GitHub issues/PRs, and the maintainers' own commits), cited.

Every class name, file path, and inheritance claim on these pages was checked
against the Panda3D `master` source tree by an adversarial verification pass.

Before diving into a specific subsystem, read the
**[Cross-cutting concepts](../cross-cutting-concepts.md)** chapter — the type
system, reference counting, BAM serialization, the threaded pipeline cycler,
and interrogate bindings recur in every subsystem below.

## The subsystems

| Page | Covers (`panda/src` unless noted) |
|------|-----------------------------------|
| [dtool / interrogate / config](dtool.md) | `dtool/src`: dtoolbase, dtoolutil, prc, dconfig, interrogatedb, prckeys, parser-inc |
| [Scene graph](scene-graph.md) | pgraph, pgraphnodes, cull |
| [Graphics objects](graphics-objects.md) | gobj, gsgbase |
| [Display & GSG backends](display-and-gsg.md) | display, glstuff, glgsg, the platform display modules, tinydisplay |
| [Characters & animation](characters-and-animation.md) | char, chan, parametrics |
| [Egg library & loader](egg.md) | egg, egg2pg, pnmimage, pnmimagetypes |
| [Collision & physics](collision-and-physics.md) | collide, physics, bullet, ode |
| [Core utilities](core-utilities.md) | putil, event, pipeline, express, linmath, mathutil |
| [Text, GUI, grutil & particles](text-gui-grutil.md) | text, pnmtext, pgui, grutil, particlesystem, distort |
| [Devices & networking](devices-and-networking.md) | device, dgraph, tform, net, nativenet, downloader, vrpn |
| [Audio](audio.md) | audio, audiotraits, movies (+ ffmpeg) |
| [The direct Python framework](direct-python-framework.md) | `direct/src`: showbase, actor, interval, task, fsm, gui, distributed, stdpy, directnotify, controls |
| [pandatool (asset pipeline)](pandatool.md) | `pandatool/src`: the converters, palettizer, ptloader, bam, pstatserver |

For a one-line description of *every* directory (including the ones without a
full deep-dive), see the [Source tree](../source-tree.md) chapter.

For the project-level, ecosystem, build, and deployment footguns that aren't tied to a
single subsystem, see [Project health, ecosystem & deployment](../project-and-ecosystem.md).
