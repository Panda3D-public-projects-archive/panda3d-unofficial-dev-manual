# File formats & reference #

Legacy reference material on Panda3D's file formats, configuration, and a few
specific workflows. Much of this predates the modern docs and describes the
engine at a detailed, format-spec level; it has been cleaned up and split by
topic, but treat specific API details with appropriate suspicion and check
against the source or the [Engine subsystems](../subsystems/index.md) pages,
which document the current code.

## Contents

| Page | What it covers |
|------|----------------|
| [The GraphicsEngine](graphics-engine.md) | `GraphicsEngine`/`GraphicsPipe`/`GraphicsStateGuardian`/`GraphicsWindow`/`GraphicsBuffer` — creating windows & offscreen buffers (see also [Display & GSG backends](../subsystems/display-and-gsg.md)). |
| [ppython](ppython.md) | What `ppython` is and why it exists. |
| [Panda Audio API](audio-api.md) | `AudioManager`/`AudioSound` usage (see also the [Audio](../subsystems/audio.md) deep-dive). |
| [Coding style](coding-style.md) | Panda3D's C++ coding-style conventions. |
| [Collision flags](collision-flags.md) | Collision bit-flag reference (see also [Collision & physics](../subsystems/collision-and-physics.md)). |
| [egg-palettize](egg-palettize.md) | The texture-palettizer tool and `.txa` syntax (see also [pandatool](../subsystems/pandatool.md)). |
| [The egg file format](egg-syntax.md) | The full `.egg` file-format specification — entries, geometry, grouping, collision, animation (see also the [Egg library & loader](../subsystems/egg.md) deep-dive). |
| [How to control render order](render-order.md) | Cull bins, sort order, and depth sorting (see also [Scene graph](../subsystems/scene-graph.md)). |
| [How to make a multipart actor](multipart-actors.md) | Multipart vs. half-body actors and how to assemble them. |
| [MultiGen model flags](multigen-flags.md) | MultiGen exporter model-flag reference. |
| [Multi-texturing in Maya](maya-multitexturing.md) | Setting up multi-texturing in the Maya exporter. |
| [The Config (PRC) system](config-prc.md) | Defining, assigning, querying, and managing PRC config variables (see also the [dtool / config](../subsystems/dtool.md) deep-dive). |
