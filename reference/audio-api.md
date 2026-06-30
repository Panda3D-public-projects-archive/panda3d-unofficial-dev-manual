# Panda Audio Documentation

## AudioManager and AudioSound

The `AudioManager` is a combination of a file cache and a category of sounds (e.g. sound effects, battle sounds, or music).

The first step is to decide which `AudioManager` to use and load it.

Once you have an `AudioManager` (e.g. `effectsManager`), a call to `get_sound(<file>)` on that manager should get you an `AudioSound` (e.g. `mySound = effectsManager.getSound("bang")`).

After getting a sound from an `AudioManager`, you can tell the sound to change its volume, loop, start time, play, stop, etc. There is no need to involve the `AudioManager` explicitly in these operations.

Simply delete the sound when you're done with it. (The `AudioSound` knows which `AudioManager` it is associated with, and will do the right thing).

The audio system provides an API for the rest of Panda, and leaves a lot of leeway to the low level sound system. This is good and bad. On the good side: it's easier to understand, and it allows for widely varying low level systems. On the bad side: it may be harder to keep the behavior consistent across implementations (please try to keep them consistent when adding an implementation).

## Example usage

**Python example:**

```python
effects = AudioManager.createAudioManager()
music = AudioManager.createAudioManager()
bang = effects.load("bang")
background = music.load("background_music")
background.play()
bang.play()
```

**C++ example:**

```cpp
AudioManager effects = AudioManager::create_AudioManager();
AudioManager music = AudioManager::create_AudioManager();
bang = effects.get_sound("bang");
background = music.get_sound("background_music");
background.play();
bang.play();
```
