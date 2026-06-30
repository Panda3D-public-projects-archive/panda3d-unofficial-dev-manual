# Multi-Texturing in Maya

A good rule of thumb is to create your Multi-Layered shader first to get an idea of what kind of blend mode you want. You can do that by using Maya's `kLayeredShader`.

The following blend modes from Maya are supported directly in Panda.

"Multiply" => "Modulate"

"Over" => "Decal"

"Add" => "Add"

More blend modes will be supported very soon. You should be able to pview this change if you restart Maya from the "runmaya.bat" (or however you restart Maya).

Once the shader is set up, you should create the texture coordinates or uvsets for your multitexture. Make sure the uvset name matches the shader names that you made in the `kLayeredShader`. For example, if the two shaders (not the texture file name) in your `kLayeredShader` are called "base" and "top", then your geometry (that will have the layered shader) will have two uvsets called "base" and "top".

After this you will link the uvsets to the appropriate shaders.

A reminder note: by default the alpha channel of the texture on the bottom is dropped in the conversion. If you want to retain the alpha channel of your texture, please make a connection to the alpha channel in Maya when setting up the shader (alpha on the `layerShader` will be highlighted in yellow).
