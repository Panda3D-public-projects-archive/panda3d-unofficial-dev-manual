# The GraphicsEngine

The `GraphicsEngine` is where it all begins. There is only one, global, `GraphicsEngine` in an application, and its job is to keep all of the pointers to your open windows and buffers, and also to manage the task of doing the rendering, for all of the open windows and buffers. Panda normally creates a `GraphicsEngine` for you at startup, which is available as `base.graphicsEngine`. There is usually no reason to create a second `GraphicsEngine`.

Note also that the following interfaces are strictly for the advanced user. Normally, if you want to create a new window or an offscreen buffer for rendering, you would just use the `base.openWindow()` or `window.makeTextureBuffer()` interfaces, which handle all of the details for you automatically.

However, please continue reading if you want to understand in detail how Panda manages windows and buffers, or if you have special needs that are not addressed by the above convenience methods.

## GraphicsPipe

Each application will also need at least one `GraphicsPipe`. The `GraphicsPipe` encapsulates the particular API used to do rendering. For instance, there is one `GraphicsPipe` class for OpenGL rendering, and a different `GraphicsPipe` for DirectX. Although it is possible to create a `GraphicsPipe` of a specific type directly, normally Panda will create a default `GraphicsPipe` for you at startup, which is available in `base.pipe`.

The `GraphicsPipe` object isn't often used directly, except to create the individual `GraphicsWindow` and `GraphicsBuffer` objects.

## GraphicsWindow and GraphicsBuffer

The `GraphicsWindow` class is the class that represents a single onscreen window for rendering. Panda normally opens a default window for you at startup, which is available in `base.win`. You can create as many additional windows as you like. (Note, however, that some graphics drivers incur a performance penalty when multiple windows are open simultaneously.)

Similarly, `GraphicsBuffer` is the class that represents a hidden, offscreen buffer for rendering special offscreen effects, such as render-to-texture. It is common for an application to have many offscreen buffers open at once.

Both classes inherit from the base class `GraphicsOutput`, which contains all of the code common to rendering to a window or offscreen buffer.

## GraphicsStateGuardian

The `GraphicsStateGuardian`, or GSG for short, represents the actual graphics context. This class manages the actual nuts-and-bolts of drawing to a window; it manages the loading of textures and vertex buffers into graphics memory, and has the functions for actually drawing triangles to the screen. (During the process of rendering the frame, the "graphics state" changes several times; the GSG gets its name from the fact that most of its time is spent managing this graphics state.)

You would normally never call any methods on the GSG directly; Panda handles all of this for you, via the `GraphicsEngine`. This is important, because in some modes, the GSG may operate almost entirely in a separate thread from all of your application code, and it is important not to interrupt that thread while it might be in the middle of drawing.

Each `GraphicsOutput` object keeps a pointer to the GSG that will be used to render that window or buffer. It is possible for each `GraphicsOutput` to have its own GSG, or it is possible to share the same GSG between multiple different `GraphicsOutput`s. Normally, it is preferable to share GSGs, because this tends to be more efficient for managing graphics resources.

Consider the following diagram to illustrate the relationship between these classes. This shows a typical application with one window and two offscreen buffers:

|                |  GraphicsPipe  |                |
| -------------: | :------------: | -------------- |
|              / |       \|       | \              |
| GraphicsOutput | GraphicsOutput | GraphicsOutput |
|             \| |       \|       | \|             |
|            GSG |      GSG       | GSG            |

The `GraphicsPipe` was used to create each of the three `GraphicsOutput`s, of which one is a `GraphicsWindow`, and the remaining two are `GraphicsBuffer`s. Each `GraphicsOutput` has a pointer to the GSG that will be used for rendering. Finally, the `GraphicsEngine` is responsible for managing all of these objects.

In the above illustration, each window and buffer has its own GSG, which is legal, although it's usually better to share the same GSG across all open windows and buffers.

## Rendering a frame

There is one key interface to rendering each frame of the graphics simulation:

```python
base.graphicsEngine.renderFrame()
```

This method causes all open `GraphicsWindow`s and `GraphicsBuffer`s to render their contents for the current frame. In order for Panda3D to render anything, this method must be called once per frame. Normally, this is done automatically by the task `igloop`, which is created when you start Panda.

## Using a GraphicsEngine to create windows and buffers

In order to render in Panda3D, you need a `GraphicsStateGuardian`, and either a `GraphicsWindow` (for rendering into a window) or a `GraphicsBuffer` (for rendering offscreen). You cannot create or destroy these objects directly; instead, you must use interfaces on the `GraphicsEngine` to create them. Before you can create either of the above, you need to have a `GraphicsPipe`, which specifies the particular graphics API you want to use (e.g. OpenGL or DirectX). The default `GraphicsPipe` specified in your `Config.prc` file has already been created at startup, and can be accessed by `base.pipe`.

Now that you have a `GraphicsPipe` and a `GraphicsEngine`, you can create a `GraphicsStateGuardian` object. This object corresponds to a single graphics context on the graphics API, e.g. a single OpenGL context. (The context owns all of the OpenGL or DirectX objects like display lists, vertex buffers, and texture objects.) You need to have at least one `GraphicsStateGuardian` before you can create a `GraphicsWindow`:

```python
myGsg = base.graphicsEngine.makeGsg(base.pipe)
```

Now that you have a `GraphicsStateGuardian`, you can use it to create an onscreen `GraphicsWindow` or an offscreen `GraphicsBuffer`:

```python
base.graphicsEngine.makeWindow(gsg, name, sort)
base.graphicsEngine.makeBuffer(gsg, name, sort, xSize, ySize, wantTexture)
```

`gsg` is the `GraphicsStateGuardian`, `name` is an arbitrary name you want to assign to the window/buffer, and `sort` is an integer that determines the order in which the windows/buffers will be rendered. The buffer-specific arguments `xSize` and `ySize` decide the dimensions of the buffer, and `wantTexture` should be set to `True` if you want to retrieve a texture from this buffer later on.

You can also use:

```python
graphicsEngine.makeParasite(host, name, sort, xSize, ySize)
```

where `host` is a `GraphicsOutput` object. It creates a buffer but it does not allocate room for itself. Instead it renders to the framebuffer of `host`. It effectively has `wantTexture` set to `True` so you can retrieve a texture from it later on. See The `GraphicsOutput` class and Graphics Buffers and Windows for more information.

```python
myWindow   = base.graphicsEngine.makeWindow(myGsg, "HelloWorld", 0)
myBuffer   = base.graphicsEngine.makeBuffer(myGsg, "HiWorld", 0, 800, 600, True)
myParasite = base.graphicsEngine.makeBuffer(myBuffer, "Ima leech", 0, 800, 600)
```

Note: if you want the buffers to be visible, add the following to your configuration file:

```text
show-buffers true
```

This causes the buffers to be opened as windows instead, which is useful while debugging.

## Sharing graphics contexts

It is possible to share the same `GraphicsStateGuardian` among multiple different `GraphicsWindow`s and/or `GraphicsBuffer`s; if you do this, then the graphics context will be used to render into each window one at a time. This is particularly useful if the different windows will be rendering many of the same objects, since then the same texture objects and vertex buffers can be shared between different windows.

It is also possible to use a different `GraphicsStateGuardian` for each different window. This means that if a particular texture is to be rendered in each window, it will have to be loaded into graphics memory twice, once in each context, which may be wasteful. However, there are times when this may be what you want to do, for instance if you have multiple graphics cards and you want to render to both of them simultaneously. (Note that the actual support for simultaneously rendering to multiple graphics cards is currently unfinished in Panda at the time of this writing, but the API has been designed with this future path in mind.)

## Closing windows

To close a specific window or buffer you use `removeWindow(window)`. To close all windows use `removeAllWindows()`:

```python
base.graphicsEngine.removeWindow(myWindow)
base.graphicsEngine.removeAllWindows()
```

## More about GraphicsEngine

Here is some other useful functionality of the `GraphicsEngine` class.

- `getNumWindows()` — Returns the number of windows and buffers that this `GraphicsEngine` object is managing.
- `isEmpty()` — Returns `True` if this `GraphicsEngine` is not managing any windows or buffers.

See the API for advanced functionality of `GraphicsEngine` and `GraphicsStateGuardian`.
