Unofficial Panda3D engine developer manual
==========================================

A developer oriented manual for **understanding and modifying the Panda3D engine
internals** , built from the engine source (the primary source of truth) 
and ~20 years of community knowledge.

[![Documentation Status](https://readthedocs.org/projects/panda-developer-manual/badge/?version=latest)](http://panda-developer-manual.readthedocs.io/en/latest/?badge=latest)
[![Download as PDF](https://img.shields.io/badge/download-PDF-blue.svg?style=flat-square)](http://readthedocs.org/projects/panda-developer-manual/downloads/pdf/latest/)
[![Download as HTML](https://img.shields.io/badge/download-HTML-blue.svg?style=flat-square)](http://readthedocs.org/projects/panda-developer-manual/downloads/htmlzip/latest/)
[![Download as EPUB](https://img.shields.io/badge/download-EPUB-blue.svg?style=flat-square)](http://readthedocs.org/projects/panda-developer-manual/downloads/epub/latest/)


### Building the docs with [uv](https://docs.astral.sh/uv/) (recommended)

```bash
uv run make html             # creates venv with deps & builds, output in _build/html/
```

Other output formats: `make epub`, `make latexpdf` (PDF needs a LaTeX install).

----

Released to the public domain under the [Unlicense](UNLICENSE).

[sphinx]: https://www.sphinx-doc.org/
[myst]: https://myst-parser.readthedocs.io/
[uv]: https://docs.astral.sh/uv/
