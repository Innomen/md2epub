#!/usr/bin/env python3
"""
md2epub: one markdown file plus one cover image, out come EPUB, PDF, DOCX, and
manuscript markdown, with dash and banned-string verification baked in.

The point of this tool is to encode the working pandoc + xelatex + pdfunite +
magick incantations in one place, so that "I edited the source, regenerate the
ebook" is a single command instead of three scripts plus manual orchestration.

Dependencies (must be on PATH):
  pandoc      with xelatex available as a PDF engine
  magick      ImageMagick 7 (not the deprecated `convert`); for cover upscale
  pdfunite    poppler-utils; for cover + content PDF assembly
  pdftotext   poppler-utils; for PDF text extraction during verification

Usage:
  md2epub.py SOURCE.md --cover COVER.png

  Outputs (default ./output/):
    <slug>.epub
    <slug>.pdf
    <slug>-manuscript.md
    <slug>-manuscript.docx

  Slug derives from --slug, otherwise from the title (YAML or --title).

Metadata is read from optional YAML frontmatter on SOURCE.md, e.g.:

  ---
  title: My Book
  subtitle: An Optional Subtitle
  author: First Last
  ---

CLI flags override YAML.
"""
import argparse
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


DASH_PATTERN = re.compile(r'[–—―−]')
KDP_COVER_SIZE = (1707, 2560)


def parse_yaml_frontmatter(text):
    """Return (metadata_dict, body_without_frontmatter). Minimal single-level key:value."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return {}, text
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            end = i
            break
    if end is None:
        return {}, text
    meta = {}
    for raw in lines[1:end]:
        if ':' not in raw:
            continue
        k, v = raw.split(':', 1)
        meta[k.strip()] = v.strip().strip('"').strip("'")
    body = ''.join(lines[end + 1:]).lstrip('\n')
    return meta, body


def slugify(title):
    s = re.sub(r'[^A-Za-z0-9]+', '-', title or '').strip('-')
    return s or 'book'


def cover_dimensions(path):
    r = subprocess.run(
        ['magick', 'identify', '-format', '%w %h', str(path)],
        capture_output=True, text=True, check=True,
    )
    w, h = r.stdout.strip().split()
    return int(w), int(h)


def prepare_cover(src, work_dir, target=KDP_COVER_SIZE):
    """Return a JPG cover path at >= target dimensions. Upscale via magick Lanczos if needed."""
    w, h = cover_dimensions(src)
    needs_resize = w < target[0] or h < target[1]
    needs_jpg = src.suffix.lower() not in ('.jpg', '.jpeg')
    if not needs_resize and not needs_jpg:
        return src
    out = work_dir / 'cover-kdp.jpg'
    cmd = ['magick', str(src), '-filter', 'Lanczos']
    if needs_resize:
        cmd += ['-resize', f'{target[0]}x{target[1]}']
    cmd += ['-quality', '92', str(out)]
    subprocess.run(cmd, check=True)
    return out


def build_epub(source_md, css, cover_jpg, out_path):
    cmd = ['pandoc', str(source_md), '--toc', '--toc-depth=2']
    if css and Path(css).exists():
        cmd += ['--css', str(css)]
    cmd += ['--epub-cover-image', str(cover_jpg), '-o', str(out_path)]
    subprocess.run(cmd, check=True)


def build_docx(source_md, out_path):
    subprocess.run(['pandoc', str(source_md), '-o', str(out_path)], check=True)


def build_pdf(source_md, cover_jpg, title, subtitle, author, out_path,
              trim_width='6in', trim_height='9in', margin='0.75in',
              fontsize='10pt', mainfont='DejaVu Serif', monofont='DejaVu Sans Mono'):
    """Two-build-and-unite pattern. Pandoc's PDF template emits \\maketitle before
    --include-before-body and claims page 1, so a cover injected through that route
    lands on page 2. Building a cover-only PDF and a content-only PDF and joining
    them with pdfunite is the working pattern."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cover_tex = tmp / 'cover-only.tex'
        cover_tex.write_text(
            r"\documentclass[12pt]{article}" "\n"
            r"\usepackage[paperwidth=" + trim_width + r",paperheight=" + trim_height + r",margin=0in]{geometry}" "\n"
            r"\usepackage{graphicx}" "\n"
            r"\pagestyle{empty}" "\n"
            r"\begin{document}" "\n"
            r"\thispagestyle{empty}" "\n"
            r"\noindent\centerline{\includegraphics[width=\paperwidth,height=\paperheight,keepaspectratio]{"
            + str(cover_jpg) + r"}}" "\n"
            r"\end{document}" "\n"
        )
        subprocess.run(
            ['xelatex', '-interaction=nonstopmode', '-output-directory', str(tmp), str(cover_tex)],
            capture_output=True, check=False,
        )
        cover_pdf = tmp / 'cover-only.pdf'
        content_pdf = tmp / 'content-only.pdf'
        cmd = [
            'pandoc', str(source_md),
            '--pdf-engine=xelatex',
            '--toc', '--toc-depth=2',
            '-V', f'geometry:paperwidth={trim_width}',
            '-V', f'geometry:paperheight={trim_height}',
            '-V', f'geometry:margin={margin}',
            '-V', f'fontsize={fontsize}',
            '-V', f'mainfont={mainfont}',
            '-V', f'monofont={monofont}',
            '-V', 'documentclass=article',
            '-V', f'title={title}',
            '-V', f'subtitle={subtitle}',
            '-V', f'author={author}',
            '-o', str(content_pdf),
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        subprocess.run(['pdfunite', str(cover_pdf), str(content_pdf), str(out_path)], check=True)


def epub_body_text(epub_path):
    with zipfile.ZipFile(epub_path) as z:
        parts = [
            z.read(name).decode('utf-8', errors='replace')
            for name in z.namelist()
            if name.endswith('.xhtml')
        ]
    return '\n'.join(parts)


def pdf_text(pdf_path):
    r = subprocess.run(['pdftotext', str(pdf_path), '-'], capture_output=True, text=True)
    return r.stdout


def verify(surfaces, bans):
    """surfaces: dict[label -> text]. bans: iterable of literal strings.
    Print a per-surface report. Return True if all clean."""
    ok = True
    for label, text in surfaces.items():
        dashes = len(DASH_PATTERN.findall(text))
        ban_hits = {b: text.count(b) for b in bans}
        bits = [f"dashes={dashes}"] + [f"'{b}'={ban_hits[b]}" for b in bans]
        line = f"  {label:14}  " + '  '.join(bits)
        if dashes or any(ban_hits.values()):
            ok = False
            line += '   FAIL'
        print(line)
    return ok


def main():
    ap = argparse.ArgumentParser(
        description='Markdown to EPUB / PDF / DOCX / manuscript.md with a cover, in one shot.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument('source', type=Path, help='Source markdown (may include YAML frontmatter).')
    ap.add_argument('--cover', type=Path, required=True,
                    help='Cover image (PNG or JPG). Auto-upscaled if smaller than 1707x2560.')
    ap.add_argument('--output-dir', type=Path, default=Path('output'),
                    help='Directory for output files. Created if missing. Default: ./output')
    ap.add_argument('--title', help='Book title. Overrides YAML.')
    ap.add_argument('--subtitle', default='', help='Subtitle. Overrides YAML.')
    ap.add_argument('--author', default='', help='Author name. Overrides YAML.')
    ap.add_argument('--slug', help='Output filename stem. Overrides title-derived slug.')
    ap.add_argument('--css', type=Path, help='Optional CSS file for the EPUB.')
    ap.add_argument('--formats', default='epub,pdf,manuscript,docx',
                    help='Comma-separated subset of: epub,pdf,manuscript,docx. Default: all.')
    ap.add_argument('--ban', action='append', default=[],
                    help='Banned literal string. Checked across all output surfaces. Repeatable.')
    ap.add_argument('--no-check', action='store_true',
                    help='Skip dash + banned-string verification of outputs.')
    ap.add_argument('--trim', default='6inx9in',
                    help='PDF trim size, format WIDTHxHEIGHT with units. Default: 6inx9in.')
    ap.add_argument('--margin', default='0.75in', help='PDF margin. Default: 0.75in.')
    ap.add_argument('--fontsize', default='10pt', help='PDF body font size. Default: 10pt.')
    ap.add_argument('--mainfont', default='DejaVu Serif', help='PDF main font. Default: DejaVu Serif.')
    ap.add_argument('--monofont', default='DejaVu Sans Mono', help='PDF mono font. Default: DejaVu Sans Mono.')
    args = ap.parse_args()

    if not args.source.is_file():
        print(f"Source not found: {args.source}", file=sys.stderr)
        sys.exit(2)
    if not args.cover.is_file():
        print(f"Cover not found: {args.cover}", file=sys.stderr)
        sys.exit(2)

    formats = {f.strip() for f in args.formats.split(',') if f.strip()}
    allowed = {'epub', 'pdf', 'manuscript', 'docx'}
    bad = formats - allowed
    if bad:
        print(f"Unknown formats: {sorted(bad)}. Allowed: {sorted(allowed)}", file=sys.stderr)
        sys.exit(2)

    src_text = args.source.read_text()
    meta, body = parse_yaml_frontmatter(src_text)
    title = args.title or meta.get('title') or args.source.stem
    subtitle = args.subtitle or meta.get('subtitle', '')
    author = args.author or meta.get('author', '')
    slug = args.slug or slugify(title)

    try:
        trim_w, trim_h = args.trim.lower().split('x')
    except ValueError:
        print(f"--trim must be WIDTHxHEIGHT (e.g. 6inx9in); got {args.trim!r}", file=sys.stderr)
        sys.exit(2)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f'[md2epub] source: {args.source}')
    print(f'[md2epub] slug:   {slug}')

    with tempfile.TemporaryDirectory() as work_dir:
        work_dir = Path(work_dir)
        cover_jpg = prepare_cover(args.cover, work_dir)
        if cover_jpg != args.cover:
            print(f'[md2epub] cover prepared: {cover_jpg.name} (Lanczos upscale to {KDP_COVER_SIZE[0]}x{KDP_COVER_SIZE[1]})')

        manuscript_path = args.output_dir / f'{slug}-manuscript.md'
        manuscript_path.write_text(body)
        if 'manuscript' in formats:
            print(f'[md2epub] manuscript.md: {manuscript_path.stat().st_size:,} bytes')

        outputs = {}
        if 'epub' in formats:
            epub_path = args.output_dir / f'{slug}.epub'
            build_epub(args.source, args.css, cover_jpg, epub_path)
            print(f'[md2epub] EPUB: {epub_path.stat().st_size:,} bytes')
            outputs['epub'] = epub_path

        if 'docx' in formats:
            docx_path = args.output_dir / f'{slug}-manuscript.docx'
            build_docx(manuscript_path, docx_path)
            print(f'[md2epub] DOCX: {docx_path.stat().st_size:,} bytes')

        if 'pdf' in formats:
            pdf_path = args.output_dir / f'{slug}.pdf'
            build_pdf(manuscript_path, cover_jpg, title, subtitle, author, pdf_path,
                      trim_width=trim_w, trim_height=trim_h, margin=args.margin,
                      fontsize=args.fontsize, mainfont=args.mainfont, monofont=args.monofont)
            print(f'[md2epub] PDF:  {pdf_path.stat().st_size:,} bytes')
            outputs['pdf'] = pdf_path

        if not 'manuscript' in formats:
            manuscript_path.unlink()

        print('[md2epub] complete.')

        if args.no_check:
            return

        surfaces = {}
        if 'manuscript' in formats:
            surfaces['manuscript.md'] = body
        if 'epub' in outputs:
            surfaces['EPUB XHTML'] = epub_body_text(outputs['epub'])
        if 'pdf' in outputs:
            surfaces['PDF text'] = pdf_text(outputs['pdf'])

        if not surfaces:
            return

        print()
        print(f'[verify] surfaces: {", ".join(surfaces)}')
        if args.ban:
            print(f'[verify] bans:     {args.ban}')
        ok = verify(surfaces, args.ban)
        print('[verify] OK' if ok else '[verify] FAIL')
        sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
