# md2epub

One markdown file plus one cover image. Out come EPUB, PDF, DOCX, and manuscript markdown, with em-dash and banned-string verification baked in.

## Why this exists

The standard pandoc incantations for cover-bearing EPUBs and cover-page PDFs are non-obvious and break in surprising ways. Three issues recur:

- pandoc's PDF template emits `\maketitle` before `--include-before-body`, so cover images injected that way land on page 2 with a blank or stub page 1. The working pattern is two separate builds (cover-only PDF, content-only PDF) joined with `pdfunite`.
- EPUBs want `--epub-cover-image` to set the cover as the reader's first view.
- KDP wants cover JPGs at 1707x2560 minimum. Generators commonly output 1024x1536; an upscale step belongs in the pipeline.

This tool encodes those choices once, so "I edited the source, regenerate the ebook" is a single command.

## Dependencies

Must be on PATH:

- `pandoc` (with `xelatex` available as a PDF engine)
- `magick` (ImageMagick 7, not the deprecated `convert`)
- `pdfunite` (poppler-utils)
- `pdftotext` (poppler-utils, used by verification)

On Arch/Garuda: `pacman -S pandoc-cli texlive-xetex texlive-latex texlive-latexrecommended texlive-fontsrecommended imagemagick poppler`.

## Usage

```sh
md2epub.py SOURCE.md --cover COVER.png
```

Default output directory is `./output/`. Filenames derive from the title's slug:

- `<slug>.epub`
- `<slug>.pdf`
- `<slug>-manuscript.md`
- `<slug>-manuscript.docx`

The slug comes from `--slug` if given, otherwise from the title; the title comes from `--title` if given, otherwise from YAML frontmatter on the source, otherwise from the source filename's stem.

## Metadata

Optional YAML frontmatter on the source markdown:

```yaml
---
title: My Book
subtitle: An Optional Subtitle
author: First Last
---
```

CLI flags override YAML. The manuscript.md output strips this frontmatter; the EPUB/PDF inject the metadata into pandoc's variables.

## Verification

Every run that builds an EPUB or PDF (i.e. anything beyond `--formats manuscript`) runs a verification pass after the build. The pass greps each output surface for em-dashes (U+2014), en-dashes (U+2013), figure-dashes (U+2015), and minus signs (U+2212). Any nonzero count is a failure and exits non-zero.

Additional `--ban` flags add literal-string checks across the same surfaces:

```sh
md2epub.py source.md --cover cover.png --ban "Project Codename" --ban "internal-only"
```

Skip verification entirely with `--no-check`.

## Options

```
positional:
  SOURCE.md            Source markdown.

required:
  --cover PATH         Cover image. PNG or JPG. Auto-upscaled if smaller than 1707x2560.

selection:
  --output-dir DIR     Default: ./output
  --title T            Overrides YAML.
  --subtitle S         Overrides YAML.
  --author A           Overrides YAML.
  --slug S             Overrides title-derived slug.
  --formats LIST       Comma-separated subset of: epub,pdf,manuscript,docx. Default: all.

pdf:
  --trim WxH           Trim size with units. Default: 6inx9in.
  --margin S           Margin. Default: 0.75in.
  --fontsize S         Default: 10pt.
  --mainfont F         Default: DejaVu Serif.
  --monofont F         Default: DejaVu Sans Mono.

epub:
  --css PATH           Optional CSS file.

verification:
  --ban STRING         Banned literal string (repeatable).
  --no-check           Skip verification.
```

## Examples

Single short paper, full pipeline, default trim:

```sh
md2epub.py my-paper.md --cover cover.png
```

EPUB only, for an upload that needs to move now:

```sh
md2epub.py my-paper.md --cover cover.png --formats epub
```

Custom trim and banned-string sweep:

```sh
md2epub.py book.md --cover cover.jpg --trim 5.5inx8.5in \
    --ban "Working Title" --ban "TODO"
```

Overriding metadata from the command line:

```sh
md2epub.py source.md --cover cover.png \
    --title "Final Title" --author "Real Name" --slug final-title
```

## Scope

md2epub takes one markdown file in and produces formats out. If your source is assembled from multiple files (front matter + body + reference section + back matter), do that assembly first as a separate step. The split keeps md2epub general; project-specific assembly stays in project-specific tooling.

## Status

Pre-release. Working. Not yet pushed to a public repo, license not yet assigned.
