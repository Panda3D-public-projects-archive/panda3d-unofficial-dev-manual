# Project health, ecosystem & deployment

Everything below is drawn from the community-mined catalogue and is preserved as
community-sourced opinion and history, with maintainer quotes flagged
*(maintainer)* and verbatim.

These are the meta-issues that *cause* many of the technical ones elsewhere in
the manual.

## Bus factor: one part-time maintainer carries the project
**Severity: major · Status: by-nature-of-project**

Development and maintenance are overwhelmingly concentrated in one person (rdb).
It is the root cause behind doc gaps, stale samples, unaddressed feature requests, 
and slow releases.

Do note that the maintainer and core community are very responsive, Panda3D is very stable,
and any critical errors get imediately dealt with. rdb has been providing superior work for 
a very long time now. The question is how to help him with the workload, and not if he is 
not enough.

## Institutional withdrawal (Disney → CMU → community)
**Severity: historical/formative · Status: improved (community took over)**

Panda originated at Disney's VR Studio, was transferred to CMU's ETC, and then
CMU effectively stopped maintaining it (~2009, after Josh Yelon left) — only
hosting servers. rdb candidly warned the project would die without a maintainer
and engineered the pivot to community maintenance. The funding question
(donations, a paid developer) was raised but never durably solved.

[Donate on open collective - Panda3D](https://opencollective.com/panda3d)

and the [Sponsors page](https://www.panda3d.org/sponsors/)

## Recurring "Is Panda3D dead?" perception
**Severity: major · Status: still-open**

The project's image lags its actual activity. Dated website, old "stable"
download dates, and stale blog posts make newcomers assume abandonment - a
direct adoption deterrent. 

> "The question 'Is Panda3D dead?' comes nearly every half a year." — bigfoot29,
> [t/3450](https://discourse.panda3d.org/t/3450)

> "I was a bit concerned when I first looked at the website, thinking that the
> project was no longer maintained. The latest version considered stable...
> released two years ago." — AndreM, [t/13274](https://discourse.panda3d.org/t/13274)

## Misleading "Active developers: CMU and Disney" in the manual
**Severity: minor · Status: improved**

The manual credited CMU and Disney long after both had effectively stepped back,
both misattributing credit and discouraging contribution ("two big companies are
on it, they don't need me"). rdb conceded the page was misleading.

> "Reading the manual page again, it is true that the manual page is a bit
> misleading, though." — rdb *(maintainer)*, [t/13274](https://discourse.panda3d.org/t/13274)

## Small community vs. mainstream engines; users weigh switching to Godot
**Severity: major · Status: by-nature-of-project**

The community is small relative to Unity/Unreal/Godot, with thin advertising and
few learning resources. drwr notes only "two people officially associated with
Panda" frequent the forums and the community is "somewhat smaller than Ogre3D."

> "there are only two people officially associated with Panda who frequent these
> forums." — drwr *(maintainer)*, [t/1514](https://discourse.panda3d.org/t/1514)

> "if I was making games only but still really needed an open source engine, I'd
> invest time switching to Godot over Panda... If Godot chose Python over a
> custom language I'd be gone by now." — sutemp, [t/29653](https://discourse.panda3d.org/t/29653)

## Maintainers' own tech-debt admissions: "old and crufty," "needs a rewrite"
**Severity: major · Status: still-open**

Across years, drwr and rdb openly describe large swaths of the engine as legacy
cruft: ShowBase, the shader generator, `genPyCode`, `interrogate`, the Max
exporter, half-finished parallel-render code.

> "This is an example of some of the cruft that has accumulated in ShowBase over
> the years." — drwr *(maintainer)*, [t/2859](https://discourse.panda3d.org/t/2859)

> "The genPyCode version makepanda uses is a mess though... it definitely needs a
> rewrite." — rdb *(maintainer)*, [t/4624](https://discourse.panda3d.org/t/4624)

## No first-party visual / level / scene / shader editor
**Severity: major · Status: by-design + resource-limited**

Panda has no visual editor. The CMU-era SceneEditor was buggy, broke across
releases, and was removed as "half-finished." rdb frames code-first as
intentional but ties the missing editor to "limited developer resources." Users
repeatedly cite this as an adoption cost vs. Unity/Unreal.

> "The scene editor is only half-finished... It needs a developer." —
> Josh_Yelon *(maintainer)*, [t/1918](https://discourse.panda3d.org/t/1918)

> "I can't make any promises about a visual shader editor, though. Aside from the
> limited developer resources, Panda3D has always been a bit more of a hands-on
> engine than Unity and Unreal." — rdb *(maintainer)*, [t/28342](https://discourse.panda3d.org/t/28342)

## PR-review bottleneck
**Severity: minor · Status: still-open (symptom of the bus factor)**

The single-maintainer bottleneck shows up as `CHANGES_REQUESTED`/"needs rebase"
stalls on the tracker; community PRs (e.g. type-stub work, #1217) stall and get
revived months later. A direct consequence of the bus factor (see above).

---

## Documentation & learning curve

### Documentation is incomplete/sparse — maintainers concur
**Severity: major · Status: still-open (improving)**

Entire subsystems (particles, collision specifics, networking, clip planes, cube
maps) are sparse or undocumented; drwr's standard answer for gaps is "look in the
source code."

> "As for where to find this sort of information when the manual is lacking, well,
> I looked in the source code..." — drwr *(maintainer)*, [t/9447](https://discourse.panda3d.org/t/9447)

> "Yes, fair, the documentation is a mess." — rdb *(maintainer)*,
> [t/28342](https://discourse.panda3d.org/t/28342)

### Auto-generated API reference is hard to navigate and example-free
**Severity: major · Status: improved (Sphinx, 2019)**

The Python API reference is auto-generated from C++ by `interrogate`. It
historically lacked method descriptions, inheritance info, and examples, and
contained confusing "semantic twins" (`panda3d.core.Loader` vs
`showbase.Loader.Loader`). (The `interrogate` binding generator is documented in
[dtool / interrogate / config](subsystems/dtool.md).)

> "The API reference is automatically generated from scanning the source files.
> It is true that it is far from perfect." — drwr *(maintainer)*,
> [t/8953](https://discourse.panda3d.org/t/8953)

### C++ API documentation perpetually incomplete
**Severity: major · Status: still-open**

Because docs are generated from the C++ side but written for Python consumers,
C++ users hit "To-Do" placeholders for years; the Sphinx migration explicitly
deferred a C++ API reference.

> "most of the parts of C++ manual is incomplete with a 'To-Do' markings here and
> there." — Juggernaut, [t/12231](https://discourse.panda3d.org/t/12231)

### Outdated/incorrect docs — covers removed APIs, wrong sample paths
**Severity: major · Status: still-open (perennial)**

Manual pages reference removed APIs (`makeGsg`/`makeOutput`), point to wrong
sample locations, and describe deprecated workflows. Beginners waste time on
dead tangents.

> "The base.graphicsEngine.makeGsg is also not there any more. The manual seems
> outdated?" — clcheung, [t/5418](https://discourse.panda3d.org/t/5418)

### Ancient sample programs teaching obsolete patterns
**Severity: major · Status: still-open**

Bundled samples "look as if they were made 10 years ago" and teach obsolete
patterns (native physics, fixed-function, old camera drivers), with no samples
for modern needs (PBR, terrain collision, water, networking). A 2019 rewrite
effort stalled.

> "we still have the same old samples that look as if they were made 10 years ago
> (and they where)." — wezu 2019, [t/24289](https://discourse.panda3d.org/t/24289)

### Steep learning curve despite "short learning curve" marketing
**Severity: major · Status: still-open**

Panda markets an "easy learning curve" (its ETC teaching origin), but thin docs
invert that for beginners.

> "the learning curve with sketchy documentation makes it that much harder and a
> lot of good programmers leave. I almost left the other day because of the docs."
> — ta2025, [t/311](https://discourse.panda3d.org/t/311)

### Link rot & rotting user-hosted tutorials
**Severity: minor · Status: by-nature-of-project**

Much community knowledge lived in forum links to personal file-hosts (EarthLink,
funpic.de, CVS) that 404 over time, so old tutorials lead to dead downloads.

> "A search of panda3d.org produces nothing but a few dead links." — ScottGrant,
> [t/1175](https://discourse.panda3d.org/t/1175)

---

## Build & installation

### pip wheels lag new Python releases ("No matching distribution found")
**Severity: major · Status: still-open (structural; reactively mitigated)**

Panda ships per-Python-version binary wheels, so each new CPython release breaks
`pip install panda3d` until a maintainer manually builds new wheels — and the pip
error gives no hint that a missing wheel is the cause. Recurs every Python cycle.
(A downstream consequence of the bus factor — see above.)

> "This is because there are no Python 3.9 builds of Panda 1.10.7 on PyPI." —
> Moguri *(maintainer)*, [#1030](https://github.com/panda3d/panda3d/issues/1030)

### Three build systems over time (ppremake → makepanda → CMake), each confusing
**Severity: major · Status: makepanda standard; CMake migration still incomplete**

ppremake and makepanda were mutually-incompatible (mixing them silently corrupted
builds); the multi-year CMake migration (PR #717/#859/#322) still doesn't cover
wheels, installers, Maya/Max tools, Android, or makepanda's critical compiler
flags — so the project maintains all three simultaneously.

> "the problem is that you used both build systems: ppremake, and makepanda. The
> two aren't compatible with each other." — Josh_Yelon *(maintainer)*,
> [t/279](https://discourse.panda3d.org/t/279)

> "one thing I'm still missing from the CMake branch is the compiler options that
> makepanda specifies... some of these are fairly critical." — rdb *(maintainer)*,
> [#717](https://github.com/panda3d/panda3d/pull/717)

### `interrogate` (homegrown C++→Python binding generator) is fragile and mandatory
**Severity: major · Status: still-open (by-design tool; recurring bugs)**

Bindings come from a bespoke tool that re-parses C++ via its own CPPParser. It's
mandatory (the build can't skip it), breaks with each new Python C-API change, and
has fragile static-init/build-order assumptions. When it fails, the whole build
fails. (See [dtool / interrogate / config](subsystems/dtool.md) for how the tool
works.)

> "Makepanda cannot function without interrogate." — Josh_Yelon *(maintainer)*,
> [t/279](https://discourse.panda3d.org/t/279)

### Source builds depend on fragile, version-pinned thirdparty packages
**Severity: major · Status: still-open (recurrent breakage)**

Builds break whenever a bundled/system dep drifts: OpenEXR 2.3→2.4 (linker
errors), OpenCV 4.x (removed `CV_CAP_*`), QuickTime removal on Mojave, libjpeg.so
mismatches. The standard mitigation is "disable that optional feature"
(`--no-opencv`, …).

### macOS install-location churn & maintainer-bandwidth gaps
**Severity: major · Status: mitigated**

The SDK installed into `/Developer` (deprecated, then removed in Catalina); the
installer then refused to run; and `import panda3d` failed because the install
location wasn't on Python 3.7+'s `sys.path`. Compounded by the maintainer lacking
hardware new enough to reproduce — another symptom of limited resources.

> "Given that my Mac Mini cannot install Mojave, let alone Catalina, it seems we
> have a need for a new macOS maintainer." — rdb *(maintainer)*,
> [#760](https://github.com/panda3d/panda3d/issues/760)

## Deployment & packaging

### The old `.p3d` web-browser plugin / runtime: abandoned, removed
**Severity: historical · Status: removed-in-1.11**

For ~5 years Panda's flagship distribution story was an NPAPI browser plugin +
"Panda3D Runtime" (`packp3d`/`pdeploy`/`.p3d`) — heavily prioritized by drwr over
other work. Browsers killed NPAPI, making the whole effort dead weight and leaving
a generation of docs pointing at the defunct `runtime.panda3d.org`.

> "due to major browsers having dropped support for native browser plug-ins...
> there's no point in continuing development on it." — rdb *(maintainer)*,
> [t/24059](https://discourse.panda3d.org/t/24059)

> "the full multi-stage pipeline implementation has been put off a bit longer, to
> make room for the browser plugin, which is much more important to my employer."
> — drwr *(maintainer)*, [t/3904](https://discourse.panda3d.org/t/3904)

### `build_apps` static dependency analysis silently drops modules
**Severity: major · Status: mitigated (manual `include_modules`)**

It freezes only statically-detectable imports, so dynamically-imported deps
(numpy via a transitive dep, scipy, tensorflow, pywin32, keyring) are silently
omitted → runtime `ImportError`. Panda even hard-codes "hidden imports" for scipy.

> "numpy isn't being detected because build_apps isn't detecting that you're using
> it." — rdb *(maintainer)*, [#1409](https://github.com/panda3d/panda3d/issues/1409)

### macOS codesign / notarization minefield
**Severity: major · Status: partially-fixed**

Frozen Mach-O binaries fail Apple's strict codesign validation ("main executable
failed strict validation"), blocking notarization; and a `codesign
--remove-signature` step randomly inflated `.dylib`s into the gigabyte range
([#871](https://github.com/panda3d/panda3d/issues/871),
[#927](https://github.com/panda3d/panda3d/issues/927)).

### Mobile (iOS/Android) perpetually experimental/unsupported
**Severity: major · Status: still-open**

10+ years of "experimental proof-of-concept ports" with no packaging path, no
docs, no release builds.

> "We have experimental proof-of-concept iOS and Android ports. Lot of work to
> still do, though." — rdb *(maintainer)*, [t/14229](https://discourse.panda3d.org/t/14229)

---

## Severity & status summary

- **Blocker** (on affected configs): macOS modern-GPU/Metal (10.4), core-profile
  default-shader cliff (6.3).
- **Major** (the bulk): build/wheel fragility, the C++/Python lifetime cycles,
  thread-unsafety, transparency/shader-generator gaps, `.bam` version lock,
  glTF-as-addon, Bullet sync/units, single-precision worlds, DirectGUI, the bus
  factor.
- **Minor / footgun** (correct-but-surprising): `setColor` vs `setColorScale`,
  `Func(fn())`, forward-slash paths, NPOT resize, `loadPrcFileData("", ...)`,
  stereo-no-spatialize, async `requestProperties`.

**What improved over time:** the docs migration to Sphinx + GitHub PR
contributions (2019), snake_case API aliases, `ShowBaseGlobal` as a builtins
escape hatch, the Cg→in-house-shader-compiler and shader-generator/FFP parity
work in 1.10/1.11, thread-safe build options, many real engine-side leak fixes,
and the `tp_traverse` GC integration for Python subclasses. The trajectory is
positive; the constraint is maintainer bandwidth.
