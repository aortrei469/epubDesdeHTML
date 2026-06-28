#!/usr/bin/env python3
"""
Genera un EPUB3 válido a partir de los archivos HTML, CSS e imágenes en libro/.
Las páginas se ordenan alfabéticamente (mismo orden que ls -1).
No modifica los archivos fuente.

Uso:
    python generar_epub.py
"""

import os
import re
import sys
import uuid
import zipfile
import shutil
import tempfile
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

try:
    from lxml import etree
    import html5lib
except ImportError:
    print("ERROR: Instala dependencias: pip install -r requirements.txt")
    sys.exit(1)


LIBRO_DIR = Path("libro")
OUTPUT_FILE = "libro.epub"

BOOK_ID = str(uuid.uuid4())
BOOK_TITLE = "xxxxxxxxxxxxxx"
BOOK_AUTHOR = "xxxxxxxxxxxxxxxxxxx"
BOOK_LANG = "es"
BOOK_PUBLISHER = "Autoedición"

EXTS_XHTML = {".html", ".htm", ".xhtml"}

MIME_MAP = {
    ".html": "application/xhtml+xml",
    ".htm": "application/xhtml+xml",
    ".xhtml": "application/xhtml+xml",
    ".css": "text/css",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/vnd.microsoft.icon",
    ".woff": "application/font-woff",
    ".woff2": "application/font-woff2",
    ".ttf": "application/font-sfnt",
    ".otf": "application/font-sfnt",
    ".xml": "application/xml",
    ".js": "application/javascript",
    ".json": "application/json",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
}


def get_mime(path: Path) -> str:
    ext = path.suffix.lower()
    mime = MIME_MAP.get(ext)
    if mime:
        return mime
    guessed = mimetypes.guess_type(str(path))[0]
    return guessed or "application/octet-stream"


def slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "id"


_item_id_counter: dict[str, int] = {}
_seen_norm: dict[str, str] = {}  # lowercase path → preferred (actual) path

def _normalize_rel(path: Path, base: Path) -> str:
    return str(path.relative_to(base)).replace("\\", "/")

def item_id_from_path(path: Path, base: Path) -> str:
    rel = path.relative_to(base)
    stem = rel.parent / rel.stem
    raw = str(stem.with_suffix("")).replace("/", "-")
    safe = slugify(raw)
    if safe == "":
        safe = "id"
    if safe[0].isdigit():
        safe = "p-" + safe
    if safe in _item_id_counter:
        _item_id_counter[safe] += 1
        safe = f"{safe}-{_item_id_counter[safe]}"
    else:
        _item_id_counter[safe] = 0
    return safe


def dedup_path(paths: list[Path], base: Path) -> list[Path]:
    """Remove case-insensitive duplicates, preferring the all-lowercase path."""
    seen: dict[str, Path] = {}
    result: list[Path] = []
    for p in paths:
        low = _normalize_rel(p, base).lower()
        if low in seen:
            existing = seen[low]
            # Prefer the path that has more lowercase chars in the directory part
            existing_upper = sum(1 for c in str(existing.relative_to(base)) if c.isupper())
            new_upper = sum(1 for c in str(p.relative_to(base)) if c.isupper())
            if new_upper < existing_upper:
                # Replace with the one that has fewer uppercase chars
                result[result.index(existing)] = p
                seen[low] = p
            continue
        seen[low] = p
        result.append(p)
    return result


def html_to_xhtml(content: str) -> str:
    content = content.lstrip("\ufeff")  # Strip BOM
    doc = html5lib.parse(content, treebuilder="lxml", namespaceHTMLElements=False)
    result = etree.tostring(
        doc,
        method="xml",
        doctype="<!DOCTYPE html>",
        encoding="utf-8",
        xml_declaration=True,
    )
    xhtml = result.decode("utf-8")
    # Add XHTML default namespace if not present
    if 'xmlns="http://www.w3.org/1999/xhtml"' not in xhtml:
        xhtml = xhtml.replace("<html", '<html xmlns="http://www.w3.org/1999/xhtml"', 1)
    return xhtml


def extract_title(html_path: Path) -> str:
    content = html_path.read_text(encoding="utf-8")
    m = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return html_path.stem.replace("_", " ").title()


def make_container_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''


def make_toc_xhtml(pages: list[tuple[str, str, str]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE html>',
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">',
        "<head>",
        "<title>Tabla de contenidos</title>",
        '<meta charset="UTF-8"/>',
        "</head>",
        "<body>",
        '<nav epub:type="toc">',
        "<h1>Tabla de contenidos</h1>",
        "<ol>",
    ]
    for _id, href, title in pages:
        esc_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        lines.append(f'<li><a href="{href}">{esc_title}</a></li>')
    lines.extend(["</ol>", "</nav>", "</body>", "</html>"])
    return "\n".join(lines)


def make_ncx(pages: list[tuple[str, str, str]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">',
        "<head>",
        f'<meta name="dtb:uid" content="urn:uuid:{BOOK_ID}"/>',
        '<meta name="dtb:depth" content="1"/>',
        '<meta name="dtb:totalPageCount" content="0"/>',
        '<meta name="dtb:maxPageNumber" content="0"/>',
        "</head>",
        f"<docTitle><text>{BOOK_TITLE}</text></docTitle>",
        f"<docAuthor><text>{BOOK_AUTHOR}</text></docAuthor>",
        "<navMap>",
    ]
    for i, (_id, href, title) in enumerate(pages, 1):
        esc_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.extend([
            f'<navPoint id="navpoint-{i}" playOrder="{i}">',
            f"<navLabel><text>{esc_title}</text></navLabel>",
            f'<content src="{href}"/>',
            "</navPoint>",
        ])
    lines.extend(["</navMap>", "</ncx>"])
    return "\n".join(lines)


def make_opf(
    pages: list[tuple[str, str, str]],
    assets: list[tuple[str, str, str]],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<package xmlns="http://www.idpf.org/2007/opf"'
        ' version="3.0" unique-identifier="book-id">',
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:opf="http://www.idpf.org/2007/opf">',
        '    <dc:identifier id="book-id">urn:uuid:BOOK_ID</dc:identifier>',
        "    <dc:title>BOOK_TITLE</dc:title>",
        "    <dc:language>BOOK_LANG</dc:language>",
        "    <dc:creator>BOOK_AUTHOR</dc:creator>",
        "    <dc:publisher>BOOK_PUBLISHER</dc:publisher>",
        "    <dc:date>NOW_DATE</dc:date>",
        '    <meta property="dcterms:modified">NOW</meta>',
        "  </metadata>",
        "  <manifest>",
    ]

    # nav and ncx
    lines.append(
        '    <item id="nav" href="toc.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>'
    )
    lines.append(
        '    <item id="ncx" href="toc.ncx"'
        ' media-type="application/x-dtbncx+xml"/>'
    )

    # pages
    for _id, href, _title in pages:
        mime = get_mime(Path(href))
        lines.append(f'    <item id="{_id}" href="{href}" media-type="{mime}"/>')

    # assets
    for _id, href, mime in assets:
        lines.append(f'    <item id="{_id}" href="{href}" media-type="{mime}"/>')

    lines.extend(["  </manifest>", '  <spine toc="ncx">'])

    # spine references pages
    for _id, _href, _title in pages:
        lines.append(f'    <itemref idref="{_id}"/>')

    lines.extend(["  </spine>", "</package>"])

    opf = "\n".join(lines)
    opf = opf.replace("BOOK_ID", BOOK_ID)
    opf = opf.replace("BOOK_TITLE", BOOK_TITLE)
    opf = opf.replace("BOOK_AUTHOR", BOOK_AUTHOR)
    opf = opf.replace("BOOK_LANG", BOOK_LANG)
    opf = opf.replace("BOOK_PUBLISHER", BOOK_PUBLISHER)
    opf = opf.replace("NOW_DATE", now[:10])
    opf = opf.replace("NOW", now)
    return opf


def main():
    _item_id_counter.clear()
    _seen_norm.clear()

    if not LIBRO_DIR.is_dir():
        print(f"ERROR: No se encuentra el directorio '{LIBRO_DIR}'")
        sys.exit(1)

    html_src = sorted(LIBRO_DIR.glob("*.html"))
    if not html_src:
        print(f"ERROR: No hay archivos *.html en '{LIBRO_DIR}/'")
        sys.exit(1)

    css_src = sorted(LIBRO_DIR.glob("css/*"))
    image_src = sorted(
        (f for f in LIBRO_DIR.rglob("*") if f.is_file()
         and "images" in f.parts
         and f.suffix.lower() in MIME_MAP
         and get_mime(f).startswith("image/")),
        key=lambda p: str(p).lower(),
    )
    image_src = dedup_path(image_src, LIBRO_DIR)

    print(f"Páginas HTML: {len(html_src)}")
    print(f"CSS:          {len(css_src)}")
    print(f"Imágenes:     {len(image_src)}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        oebps = tmp / "OEBPS"
        oebps.mkdir()

        # -- mimetype (sin compresión, primero en el ZIP) --
        (tmp / "mimetype").write_text("application/epub+zip")

        # -- META-INF/container.xml --
        (tmp / "META-INF").mkdir()
        (tmp / "META-INF" / "container.xml").write_text(make_container_xml())

        # -- Convertir y copiar HTML (renombrados a .xhtml como exige epubcheck) --
        pages: list[tuple[str, str, str]] = []
        for src in html_src:
            title = extract_title(src)
            item_id = item_id_from_path(src, LIBRO_DIR)

            content = src.read_text(encoding="utf-8")
            xhtml = html_to_xhtml(content)
            xhtml_name = src.stem + ".xhtml"
            dest = oebps / xhtml_name
            dest.write_text(xhtml, encoding="utf-8")

            href = xhtml_name
            pages.append((item_id, href, title))
            print(f"  ✓ {src.name} → {xhtml_name}  ({title})")

        # -- Copiar CSS --
        assets: list[tuple[str, str, str]] = []
        (oebps / "css").mkdir(exist_ok=True)
        for src in css_src:
            shutil.copy2(src, oebps / "css" / src.name)
            item_id = item_id_from_path(src, LIBRO_DIR)
            href = str(Path("css") / src.name)
            assets.append((item_id, href, "text/css"))

        # -- Copiar imágenes --
        for src in image_src:
            rel = src.relative_to(LIBRO_DIR)
            dest = oebps / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            item_id = item_id_from_path(src, LIBRO_DIR)
            href = str(rel)
            assets.append((item_id, href, get_mime(src)))

        # -- toc.xhtml --
        toc = make_toc_xhtml(pages)
        (oebps / "toc.xhtml").write_text(toc, encoding="utf-8")

        # -- toc.ncx --
        ncx = make_ncx(pages)
        (oebps / "toc.ncx").write_text(ncx, encoding="utf-8")

        # -- content.opf --
        opf = make_opf(pages, assets)
        (oebps / "content.opf").write_text(opf, encoding="utf-8")

        # -- Empaquetar EPUB --
        if os.path.exists(OUTPUT_FILE):
            os.remove(OUTPUT_FILE)

        with zipfile.ZipFile(OUTPUT_FILE, "w", zipfile.ZIP_DEFLATED) as epub:
            epub.write(tmp / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            for f in sorted(tmp.rglob("*")):
                if f.is_file() and f.parent != tmp:
                    arcname = str(f.relative_to(tmp))
                    epub.write(f, arcname)

    print(f"\n EPUB generado: {OUTPUT_FILE}")
    print(f"    ID: {BOOK_ID}")


if __name__ == "__main__":
    main()
