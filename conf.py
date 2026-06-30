# -*- coding: utf-8 -*-
#
# Configuration file for the Sphinx documentation builder.
#
# Modernized 2026: migrated from the (unmaintained) recommonmark parser to
# MyST-Parser, and from the legacy source_parsers / html_theme_path API to
# current Sphinx. See https://www.sphinx-doc.org/en/master/usage/configuration.html
# and https://myst-parser.readthedocs.io/ for the full reference.

import os

# -- Project information -----------------------------------------------------

project = "Panda3D Engine Developer Manual (Unofficial)"
copyright = "Public Domain (Unlicense)"
author = "frainfreeze and contributors"

# The short X.Y version and the full version, including alpha/beta/rc tags.
version = "1.0"
release = "1.0"

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",          # Markdown (CommonMark + extensions) source support
    "sphinx.ext.todo",
    "sphinx.ext.intersphinx",
]

# Accept both reStructuredText and Markdown sources. MyST handles every .md;
# the index and a few legacy pages are .rst.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

master_doc = "index"
language = "en"

templates_path = ["_templates"]

# Files/dirs that are NOT part of the rendered manual.
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    ".venv",
    "_wf_out",            # workflow scratch (raw cluster drafts), if present
    "_wf_shortcomings",   # workflow scratch, if present
    "README.md",          # repo readme, not a manual page
    "old",                # archived legacy material
    "subsystems/README*",
    # The raw community footgun corpus — folded into the subsystem pages and
    # project-and-ecosystem.md; kept on disk as the source, not rendered as a
    # standalone (duplicate) page.
    "PANDA3D_SHORTCOMINGS.md",
    # other.md was split by topic into reference/*.md; excluded so it is not
    # rendered as a duplicate orphan page.
    "other.md",
]

pygments_style = "sphinx"
todo_include_todos = True

# -- MyST-Parser configuration -----------------------------------------------
# Opt-in Markdown extensions. https://myst-parser.readthedocs.io/en/latest/syntax/optional.html

myst_enable_extensions = [
    "colon_fence",     # ::: fenced directives/admonitions
    "deflist",         # definition lists
    "linkify",         # bare URLs become links (needs linkify-it-py)
    "smartquotes",     # nicer quotes/dashes
    "substitution",
    "tasklist",
]

# Auto-generate anchor slugs for headings h1..h3 so cross-page links such as
# [...](egg.md#known-shortcomings-footguns) resolve. The slug algorithm matches
# the GitHub-style anchors used throughout these docs.
myst_heading_anchors = 3

# MyST validates `other.md#heading-slug` cross-page links against explicitly
# registered targets; auto-generated heading-anchor slugs aren't in that
# registry, so it emits a false-positive xref_missing warning even though the
# emitted HTML href is correct and resolves. Silence just that check.
suppress_warnings = ["myst.xref_missing"]

# Relative .md links between source files are resolved to the built pages
# automatically by MyST; no AutoStructify shim required.

# -- intersphinx -------------------------------------------------------------
# Lets us reference the official Panda3D docs by label if we ever want to.
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
# Don't fail the build if intersphinx inventories can't be fetched offline.
intersphinx_disabled_reftypes = ["*"]

# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
htmlhelp_basename = "Panda3DdevManualdoc"

# Don't break the build if _static is empty/missing.
if not os.path.isdir(os.path.join(os.path.dirname(__file__), "_static")):
    html_static_path = []

# -- Options for LaTeX / man / texinfo / epub output -------------------------

latex_elements = {}
latex_documents = [
    (master_doc, "Panda3DdevManual.tex", "Panda3D Developer Manual",
     author, "manual"),
]

man_pages = [
    (master_doc, "panda3ddevmanual", "Panda3D Developer Manual",
     [author], 1)
]

texinfo_documents = [
    (master_doc, "Panda3DdevManual", "Panda3D Developer Manual",
     author, "Panda3DdevManual",
     "A developer-oriented manual for the Panda3D engine internals.",
     "Miscellaneous"),
]

epub_title = project
epub_author = author
epub_publisher = author
epub_copyright = copyright
epub_exclude_files = ["search.html"]
