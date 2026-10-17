"""Render a reconstruction as an EPUB 3 package plus provenance.

The EPUB is another renderer of the same ``Reconstruction`` the PDF preview uses:
one extraction, one structural adaptation, two output formats. Sections and the
navigation document are derived from the recognised level-1 headings. The build
is offline and deterministic, and the cache is never modified.
"""

from __future__ import annotations

import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple
from xml.sax.saxutils import escape

from src.utils.atomic_io import atomic_path, write_json_atomic

from .cache import MineruCache
from .export import MineruExportError, ensure_output_outside_cache
from .provenance import build_provenance
from .structure import ImageAsset, Reconstruction, adapt, apply_preview_decoration

EPUB_MIMETYPE = "application/epub+zip"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FIXED_MODIFIED = "2000-01-01T00:00:00Z"
DEFAULT_LANGUAGE = "und"
_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_IMAGE_MEDIA_TYPES = {"png": "image/png", "jpeg": "image/jpeg"}

_HEADING_TAGS = {"heading1": "h1", "heading2": "h2", "heading3": "h3"}
_PARAGRAPH_CLASSES = {"notice": "notice", "caption": "caption", "footnote": "footnote"}

_CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_STYLE_CSS = """body { font-family: serif; line-height: 1.4; margin: 1em; }
h1, h2, h3 { font-family: sans-serif; line-height: 1.2; }
p { margin: 0 0 0.6em 0; text-align: justify; }
p.notice { font-style: italic; color: #444444; }
p.caption, p.footnote { font-style: italic; font-size: 0.9em; }
figure.image { margin: 0.8em 0; text-align: center; }
figure.image img { max-width: 100%; height: auto; }
"""


@dataclass(frozen=True)
class EpubPreviewResult:
    """Outcome of one offline EPUB preview build."""

    epub_path: Path
    provenance_path: Path
    section_count: int
    paragraph_count: int
    image_count: int
    language: str
    review_required: bool


@dataclass(frozen=True)
class _Section:
    title: str
    indices: Tuple[int, ...]


def build_epub_preview(cache: MineruCache, output_dir: Path, *,
                       language: str = DEFAULT_LANGUAGE,
                       title: Optional[str] = None) -> EpubPreviewResult:
    """Build ``preview.epub`` and ``preview.provenance.json`` from a validated cache."""
    output_dir = Path(output_dir)
    ensure_output_outside_cache(output_dir, cache.root)
    if not _LANGUAGE_TAG.fullmatch(language):
        raise MineruExportError(
            f"Language {language!r} is not a BCP-47 language tag; pass --language explicitly.")

    reconstruction = apply_preview_decoration(cache, adapt(cache))
    document_title = title or reconstruction.title
    if not document_title:
        raise MineruExportError(
            "The cache has no recognised level-1 heading to use as a title; "
            "pass --title explicitly.")
    sections = _sections(reconstruction, document_title)
    images = _image_files(reconstruction)
    kinds = {item.output_index: item.kind for item in reconstruction.provenance
             if item.output_index is not None}

    entries: List[Tuple[str, bytes, int]] = [("mimetype", EPUB_MIMETYPE.encode("ascii"),
                                              zipfile.ZIP_STORED)]
    entries.append(("META-INF/container.xml", _CONTAINER_XML.encode("utf-8"),
                    zipfile.ZIP_DEFLATED))
    entries.append(("OEBPS/content.opf",
                    _package_document(cache, reconstruction, sections, images,
                                      language, document_title).encode("utf-8"),
                    zipfile.ZIP_DEFLATED))
    entries.append(("OEBPS/nav.xhtml",
                    _navigation_document(reconstruction, sections).encode("utf-8"),
                    zipfile.ZIP_DEFLATED))
    entries.append(("OEBPS/style.css", _STYLE_CSS.encode("utf-8"), zipfile.ZIP_DEFLATED))
    for number, section in enumerate(sections, 1):
        entries.append((f"OEBPS/text-{number}.xhtml",
                        _section_document(reconstruction, section, number, language,
                                          kinds, images).encode("utf-8"),
                        zipfile.ZIP_DEFLATED))
    for name, (media_type, data) in sorted(images.items()):
        entries.append((f"OEBPS/{name}", data, zipfile.ZIP_DEFLATED))

    output_dir.mkdir(parents=True, exist_ok=True)
    epub_path = output_dir / "preview.epub"
    try:
        with atomic_path(epub_path) as temporary:
            _write_zip(temporary, entries)
    except OSError as exc:
        raise MineruExportError(f"The EPUB preview could not be written: {exc}") from exc

    provenance_path = output_dir / "preview.provenance.json"
    stats = {
        "sections": len(sections),
        "images": sum(len(assets) for assets in reconstruction.images_by_paragraph.values()),
        "paragraphs": len(reconstruction.paragraphs),
        "bytes": epub_path.stat().st_size,
    }
    write_json_atomic(provenance_path, build_provenance(
        cache, reconstruction, output_format="epub", output_stats=stats))
    return EpubPreviewResult(
        epub_path=epub_path,
        provenance_path=provenance_path,
        section_count=len(sections),
        paragraph_count=len(reconstruction.paragraphs),
        image_count=stats["images"],
        language=language,
        review_required=reconstruction.review_required,
    )


def _sections(reconstruction: Reconstruction, fallback_title: str) -> Tuple[_Section, ...]:
    """Split at recognised level-1 headings; pre-heading content joins the first section."""
    heading_indices = [index for index, style in enumerate(reconstruction.styles)
                       if style == "heading1"]
    if not heading_indices:
        return (_Section(title=fallback_title,
                         indices=tuple(range(len(reconstruction.paragraphs)))),)

    boundaries = [0] + heading_indices[1:] + [len(reconstruction.paragraphs)]
    sections = []
    for start, end in zip(boundaries, boundaries[1:]):
        heading = next((reconstruction.paragraphs[index] for index in range(start, end)
                        if reconstruction.styles[index] == "heading1"), "")
        sections.append(_Section(title=heading, indices=tuple(range(start, end))))
    return tuple(sections)


def _image_files(reconstruction: Reconstruction) -> Dict[str, Tuple[str, bytes]]:
    """Map a cache-relative image name to (media type, bytes), deduplicated by hash."""
    files: Dict[str, Tuple[str, bytes]] = {}
    for assets in reconstruction.images_by_paragraph.values():
        for asset in assets:
            name = _image_name(asset)
            if name not in files:
                files[name] = (_IMAGE_MEDIA_TYPES[asset.ext], asset.data)
    return files


def image_resource_name(image_path: str, sha256: str) -> str:
    """Cache-relative EPUB resource name for one image (path supplies the suffix)."""
    suffix = Path(image_path).suffix.lower().lstrip(".")
    suffix = "jpg" if suffix == "jpeg" else suffix
    return f"images/img-{sha256[:12]}.{suffix}"


def _image_name(asset: ImageAsset) -> str:
    return image_resource_name(str(asset.path), asset.sha256)


def _section_document(reconstruction: Reconstruction, section: _Section, number: int,
                      language: str, kinds: Mapping[int, str],
                      images: Mapping[str, Tuple[str, bytes]]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE html>",
        f'<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{_attr(language)}">',
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>{escape(section.title)}</title>",
        '<link rel="stylesheet" type="text/css" href="style.css"/>',
        "</head>",
        "<body>",
    ]
    if number == 1:
        for asset in reconstruction.images_by_paragraph.get(-1, ()):
            parts.append(_figure(asset))
    for index in section.indices:
        text = reconstruction.paragraphs[index]
        style = reconstruction.styles[index]
        if style in _HEADING_TAGS:
            tag = _HEADING_TAGS[style]
            parts.append(f'<{tag} id="h{index}">{escape(text)}</{tag}>')
        else:
            css_class = _PARAGRAPH_CLASSES.get(kinds.get(index, ""), "")
            class_attr = f' class="{css_class}"' if css_class else ""
            parts.append(f"<p{class_attr}>{escape(text)}</p>")
        for asset in reconstruction.images_by_paragraph.get(index, ()):
            parts.append(_figure(asset))
    parts.extend(["</body>", "</html>"])
    return "\n".join(parts)


def _figure(asset: ImageAsset) -> str:
    return (f'<figure class="image"><img src="{_attr(_image_name(asset))}" alt=""/>'
            f"</figure>")


def _navigation_document(reconstruction: Reconstruction,
                         sections: Tuple[_Section, ...]) -> str:
    items = []
    for number, section in enumerate(sections, 1):
        href = f"text-{number}.xhtml"
        children = [
            f'<li><a href="{href}#h{index}">{escape(reconstruction.paragraphs[index])}</a></li>'
            for index in section.indices
            if reconstruction.styles[index] in ("heading2", "heading3")
        ]
        nested = f"<ol>{''.join(children)}</ol>" if children else ""
        items.append(f'<li><a href="{href}">{escape(section.title)}</a>{nested}</li>')
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE html>",
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops">',
        "<head>",
        '<meta charset="utf-8"/>',
        "<title>Contents</title>",
        "</head>",
        "<body>",
        '<nav epub:type="toc" id="toc">',
        "<h1>Contents</h1>",
        f"<ol>{''.join(items)}</ol>",
        "</nav>",
        "</body>",
        "</html>",
    ])


def _package_document(cache: MineruCache, reconstruction: Reconstruction,
                      sections: Tuple[_Section, ...],
                      images: Mapping[str, Tuple[str, bytes]],
                      language: str, document_title: str) -> str:
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, ":".join([
        "mineru-reconstruction", cache.sample_sha256, language, document_title,
        *map(str, cache.source_pages),
    ]))
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        'properties="nav"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    for number in range(1, len(sections) + 1):
        manifest.append(f'<item id="text-{number}" href="text-{number}.xhtml" '
                        f'media-type="application/xhtml+xml"/>')
    for number, (name, (media_type, _)) in enumerate(sorted(images.items()), 1):
        manifest.append(f'<item id="img-{number}" href="{_attr(name)}" '
                        f'media-type="{media_type}"/>')
    spine = [f'<itemref idref="text-{number}"/>' for number in range(1, len(sections) + 1)]
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="pub-id">',
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">',
        f'<dc:identifier id="pub-id">urn:uuid:{identifier}</dc:identifier>',
        f"<dc:title>{escape(document_title)}</dc:title>",
        f"<dc:language>{escape(language)}</dc:language>",
        f"<dc:description>{escape(reconstruction.notice)}</dc:description>",
        f'<meta property="dcterms:modified">{FIXED_MODIFIED}</meta>',
        "</metadata>",
        "<manifest>",
        *manifest,
        "</manifest>",
        "<spine>",
        *spine,
        "</spine>",
        "</package>",
    ])


def _write_zip(path: Path, entries: List[Tuple[str, bytes, int]]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data, compress_type in entries:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
            info.compress_type = compress_type
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})
