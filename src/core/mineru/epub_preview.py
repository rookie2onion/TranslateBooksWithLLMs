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
from typing import Any, Dict, List, Mapping, Optional, Tuple
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from src.utils.atomic_io import atomic_path, write_json_atomic

from .cache import MineruCache
from .export import MineruExportError, ensure_output_outside_cache
from .provenance import build_provenance
from .structure import (
    ImageAsset,
    Reconstruction,
    SourceContent,
    adapt,
    apply_preview_decoration,
)

EPUB_MIMETYPE = "application/epub+zip"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FIXED_MODIFIED = "2000-01-01T00:00:00Z"
DEFAULT_LANGUAGE = "und"
_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_INLINE_TAGS = re.compile(r"(</?(?:sup|sub|em|strong|b|i)>)")
_IMAGE_MEDIA_TYPES = {"png": "image/png", "jpeg": "image/jpeg"}

_HEADING_TAGS = {f"heading{level}": f"h{level}" for level in range(1, 7)}
_PARAGRAPH_CLASSES = {"notice": "notice", "caption": "caption", "footnote": "footnote",
                      "printed_toc_group": "toc-group", "printed_toc_label": "toc-group",
                      "printed_toc_unresolved": "toc-unresolved"}

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

_SOURCE_CSS = _STYLE_CSS + """body { overflow-wrap: anywhere; }
p { text-align: start; }
h1, h2, h3, h4, h5, h6 { break-after: avoid; }
figure.image { break-inside: avoid; margin: 1em 0; }
figure.image img { display: block; margin: 0 auto; }
figcaption { font-size: 0.9em; text-align: start; margin-top: 0.4em; }
ul.reference { list-style: none; padding-inline-start: 1em; }
li { margin-bottom: 0.4em; }
ol.printed-toc { list-style: none; padding: 0 0 0 1em; margin: .2em 0 1.2em; }
ol.printed-toc li { text-align: start; line-height: 1.45; }
p.toc-group { font-weight: bold; margin: 1.1em 0 .4em; break-after: avoid; }
.toc-page { white-space: nowrap; color: #555; }
p.toc-unresolved { white-space: pre-wrap; }
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
    return _build_epub(cache, reconstruction, output_dir / "preview.epub",
                       language=language, title=document_title)


def build_original_epub(cache: MineruCache, output_dir: Path, *,
                        language: str = DEFAULT_LANGUAGE,
                        title: Optional[str] = None) -> EpubPreviewResult:
    """Export the preview-neutral source through the shared EPUB packager."""
    ensure_output_outside_cache(output_dir, cache.root)
    if not _LANGUAGE_TAG.fullmatch(language):
        raise MineruExportError("Pass a valid BCP-47 source language.")
    source = adapt(cache, printed_toc=True)
    document_title = _INLINE_TAGS.sub("", title or source.title)
    if not document_title:
        raise MineruExportError("No recognized title; pass --title explicitly.")
    if source.counts["blocks_unaccounted"]:
        raise MineruExportError("Recognized blocks remain unaccounted; export stopped.")
    return _build_epub(cache, source, Path(output_dir) / "book.epub",
                       language=language, title=document_title)


def _build_epub(cache: MineruCache, reconstruction: Reconstruction | SourceContent,
                epub_path: Path, *, language: str, title: str) -> EpubPreviewResult:
    document_title = title
    sections = _sections(reconstruction, document_title)
    images = _image_files(reconstruction)
    kinds = {item.output_index: item.kind for item in reconstruction.provenance
             if item.output_index is not None}
    toc_targets, paragraph_anchors = _toc_targets(reconstruction, sections)

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
    css = _SOURCE_CSS if isinstance(reconstruction, SourceContent) else _STYLE_CSS
    entries.append(("OEBPS/style.css", css.encode("utf-8"), zipfile.ZIP_DEFLATED))
    for number, section in enumerate(sections, 1):
        entries.append((f"OEBPS/text-{number}.xhtml",
                        _section_document(reconstruction, section, number, language,
                                          kinds, images, toc_targets, paragraph_anchors).encode("utf-8"),
                        zipfile.ZIP_DEFLATED))
    for name, (media_type, data) in sorted(images.items()):
        entries.append((f"OEBPS/{name}", data, zipfile.ZIP_DEFLATED))

    if isinstance(reconstruction, SourceContent):
        for name, data, _ in entries:
            if name.endswith((".xml", ".opf", ".xhtml")):
                try:
                    ElementTree.fromstring(data)
                except ElementTree.ParseError as exc:
                    raise MineruExportError(f"Invalid generated EPUB document {name}: {exc}") from exc

    epub_path.parent.mkdir(parents=True, exist_ok=True)
    original = isinstance(reconstruction, SourceContent)
    provenance_path = epub_path.with_suffix(".report.json") if original else (
        epub_path.parent / "preview.provenance.json")
    stats = {
        "sections": len(sections),
        "images": sum(len(assets) for assets in reconstruction.images_by_paragraph.values()),
        "paragraphs": len(reconstruction.paragraphs),
        "bytes": 0,
    }
    if isinstance(reconstruction, SourceContent):
        excluded = {x.block_index: x.reason for x in reconstruction.exclusions}
        visuals = {a.block_index: a for group in reconstruction.images_by_paragraph.values()
                   for a in group}
        preserved = {index: asset for index, asset in visuals.items() if asset.kind != "image"}
        image_records = [
            {"page": cache.pages[b.page_index].source_page, "block": b.index,
             "type": b.type, "reason": b.preservation_reason or "provider_source_image",
             "resource": _image_name(visuals[b.index]),
             "regions": [{"page": cache.pages[r.page_index].source_page, "bbox": list(r.bbox)}
                         for r in b.source_regions] or [
                             {"page": cache.pages[b.page_index].source_page, "bbox": list(b.bbox)}],
             "method": "pdf_crop" if (cache.generated_root is not None and
                 b.image_path is not None and
                 b.image_path.is_relative_to(cache.generated_root)) else "provider_image"}
            for b in cache.blocks if b.index in visuals]
        report: Dict[str, Any] = {
            "artifact": {"format": "epub", "translated": False},
            "coverage": {"scope": "supplied_result", "pages": len(cache.pages),
                         "source_pdf_page_count_verified": bool(cache.source_sha256)},
            "recognition_sha256": cache.sample_sha256,
            "source_pdf_sha256": cache.source_sha256 or None,
            "source_pdf_admission": "unique_bundle_origin_and_page_geometry" if
                cache.source_sha256 else None,
            "counts": dict(reconstruction.counts), "epub": stats,
            "blocks": [{"page": cache.pages[b.page_index].source_page, "block": b.index,
                        "type": b.type, "disposition": "excluded" if b.index in excluded
                        else "source_image" if b.index in preserved else "emitted",
                        **({"reason": excluded[b.index]} if b.index in excluded else {})}
                       for b in cache.blocks],
            "source_preserved": [r for r in image_records if r["block"] in preserved],
            "image_fallbacks": [r for r in image_records if r["method"] == "pdf_crop"],
            "exclusions": [{"page": x.source_page, "type": x.source_type,
                            "reason": x.reason} for x in reconstruction.exclusions],
            "findings": [{"code": x.code, "page": cache.pages[x.sample_page].source_page
                          if x.sample_page is not None else None, "block": x.block_index,
                          "severity": x.severity, "message": x.message}
                         for x in reconstruction.findings],
            "reader_check": {"performed": False},
        }
        if cache.printed_toc and reconstruction.printed_toc_entries:
            plan = cache.printed_toc
            provenance = {p.output_index: p for p in reconstruction.provenance if p.output_index is not None}
            report["printed_toc"] = {
                "pages": list(plan.pages), "entries": len(reconstruction.printed_toc_entries),
                "linked_entries": sum(entry.target_block in toc_targets for entry in reconstruction.printed_toc_entries.values()),
                "omitted_images": sorted(plan.omitted_images),
                "blocks": [{"block": index, "method": block.method, "proof": dict(block.proof)}
                           for index, block in plan.blocks.items()],
                "entry_details": [{"block": provenance[index].block_index, "title": entry.title,
                    "page_label": entry.page_label, "target_block": entry.target_block,
                    "href": toc_targets.get(entry.target_block), "match_method": entry.match_method,
                    "evidence": dict(entry.evidence), "source_spans": list(entry.source_spans),
                    "source_ranges": [list(r) for r in entry.source_ranges], "label_range": entry.label_range}
                    for index, entry in reconstruction.printed_toc_entries.items()]}
    else:
        report = build_provenance(cache, reconstruction, output_format="epub", output_stats=stats)
    try:
        with atomic_path(epub_path) as temporary:
            _write_zip(temporary, entries)
            report["epub"]["bytes"] = temporary.stat().st_size
            write_json_atomic(provenance_path, report)
    except OSError as exc:
        raise MineruExportError(f"The EPUB and report could not be written: {exc}") from exc
    return EpubPreviewResult(
        epub_path=epub_path,
        provenance_path=provenance_path,
        section_count=len(sections),
        paragraph_count=len(reconstruction.paragraphs),
        image_count=stats["images"],
        language=language,
        review_required=reconstruction.review_required,
    )


def _toc_targets(source: Reconstruction | SourceContent, sections: Tuple[_Section, ...]) -> tuple[dict, dict]:
    """Resolve source block locators only after final output indices exist."""
    if not isinstance(source, SourceContent) or not source.printed_toc_entries:
        return {}, {}
    wanted = {entry.target_block for entry in source.printed_toc_entries.values() if entry.target_block is not None}
    outputs = {index: number for number, section in enumerate(sections, 1) for index in section.indices}
    targets, anchors = {}, {}
    for item in source.provenance:
        index = item.output_index
        if (item.block_index not in wanted or index is None or item.block_index in targets
                or item.kind not in {"heading", "paragraph"}):
            continue
        anchor = f"h{index}" if source.styles[index] in _HEADING_TAGS else f"p{index}"
        targets[item.block_index] = f"text-{outputs[index]}.xhtml#{anchor}"
        if source.styles[index] not in _HEADING_TAGS:
            anchors[index] = anchor
    return targets, anchors


def _sections(reconstruction: Reconstruction | SourceContent,
              fallback_title: str) -> Tuple[_Section, ...]:
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


def _image_files(reconstruction: Reconstruction | SourceContent) -> Dict[str, Tuple[str, bytes]]:
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


def _section_document(reconstruction: Reconstruction | SourceContent, section: _Section, number: int,
                      language: str, kinds: Mapping[int, str],
                      images: Mapping[str, Tuple[str, bytes]],
                      toc_targets: Mapping[int, str] | None = None,
                      paragraph_anchors: Mapping[int, str] | None = None) -> str:
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
    captions: Dict[int, List[int]] = {}
    attached = set()
    if isinstance(reconstruction, SourceContent):
        visual_blocks = {a.block_index for group in reconstruction.images_by_paragraph.values()
                         for a in group}
        for item in reconstruction.provenance:
            if (item.block_index in visual_blocks and item.output_index is not None
                    and item.kind in {"caption", "footnote"}):
                captions.setdefault(item.block_index, []).append(item.output_index)
                attached.add(item.output_index)

    def figure(asset: ImageAsset) -> str:
        if not isinstance(reconstruction, SourceContent):
            return _figure(asset)
        indices = captions.get(asset.block_index, [])
        content = "".join(f'<p>{_inline(reconstruction.paragraphs[i])}</p>' for i in indices)
        caption = f"<figcaption>{content}</figcaption>" if content else ""
        return (f'<figure class="image"><img src="{_attr(_image_name(asset))}" alt=""/>'
                f"{caption}</figure>")

    if number == 1:
        for asset in reconstruction.images_by_paragraph.get(-1, ()):
            parts.append(figure(asset))
    open_list = ""
    open_tag = ""
    for index in section.indices:
        if index in attached:
            for asset in reconstruction.images_by_paragraph.get(index, ()):
                parts.append(figure(asset))
            continue
        text = reconstruction.paragraphs[index]
        rendered = _inline(text) if isinstance(reconstruction, SourceContent) else escape(text)
        style = reconstruction.styles[index]
        list_kind = reconstruction.list_styles.get(index, "") if isinstance(
            reconstruction, SourceContent) else ""
        if isinstance(reconstruction, SourceContent) and index in reconstruction.printed_toc_entries:
            entry = reconstruction.printed_toc_entries[index]
            rendered = _inline(entry.title)
            href = toc_targets.get(entry.target_block) if toc_targets is not None and entry.target_block is not None else None
            if href:
                rendered = f'<a href="{_attr(href)}">{rendered}</a>'
            rendered += f'\u00a0 <span class="toc-page">{escape(entry.page_label)}</span>'
        if open_list and list_kind != open_list:
            parts.append(f"</{open_tag}>")
            open_list = ""
        if list_kind:
            if not open_list:
                open_tag = "ol" if list_kind == "printed-toc" else "ul"
                parts.append(f'<{open_tag} class="{_attr(list_kind)}">')
                open_list = list_kind
            parts.append(f"<li>{rendered}</li>")
        elif style in _HEADING_TAGS:
            tag = _HEADING_TAGS[style]
            parts.append(f'<{tag} id="h{index}">{rendered}</{tag}>')
        else:
            css_class = _PARAGRAPH_CLASSES.get(kinds.get(index, ""), "")
            class_attr = f' class="{css_class}"' if css_class else ""
            anchor = (paragraph_anchors or {}).get(index)
            id_attr = f' id="{anchor}"' if anchor else ""
            parts.append(f"<p{class_attr}{id_attr}>{rendered}</p>")
        for asset in reconstruction.images_by_paragraph.get(index, ()):
            if open_list:
                parts.append(f"</{open_tag}>")
                open_list = ""
            parts.append(figure(asset))
    if open_list:
        parts.append(f"</{open_tag}>")
    parts.extend(["</body>", "</html>"])
    return "\n".join(parts)


def _figure(asset: ImageAsset) -> str:
    return (f'<figure class="image"><img src="{_attr(_image_name(asset))}" alt=""/>'
            f"</figure>")


def _navigation_document(reconstruction: Reconstruction | SourceContent,
                         sections: Tuple[_Section, ...]) -> str:
    items = []
    for number, section in enumerate(sections, 1):
        href = f"text-{number}.xhtml"
        children = [
            f'<li><a href="{href}#h{index}">{escape(reconstruction.paragraphs[index])}</a></li>'
            for index in section.indices
            if reconstruction.styles[index] in ("heading2", "heading3")
        ]
        if isinstance(reconstruction, SourceContent):
            children = _nested_headings(reconstruction, section, href)
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


def _nested_headings(source: SourceContent, section: _Section, href: str) -> List[str]:
    """Nest only actual headings; skipped levels do not fabricate TOC entries."""
    root = ElementTree.Element("ol")
    stack = [(1, root)]
    for index in section.indices:
        style = source.styles[index]
        if style not in _HEADING_TAGS or style == "heading1":
            continue
        level = int(style[-1])
        while len(stack) > 1 and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        if parent is not root:
            children = parent.find("ol")
            if children is None:
                children = ElementTree.SubElement(parent, "ol")
            parent = children
        item = ElementTree.SubElement(parent, "li")
        ElementTree.SubElement(item, "a", {"href": f"{href}#h{index}"}).text = _INLINE_TAGS.sub(
            "", source.paragraphs[index])
        stack.append((level, item))
    return [ElementTree.tostring(item, encoding="unicode") for item in root]


def _package_document(cache: MineruCache, reconstruction: Reconstruction | SourceContent,
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
        f"<dc:description>{escape(reconstruction.notice if isinstance(reconstruction, Reconstruction) else '')}</dc:description>",
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


def _inline(value: str) -> str:
    """Preserve MinerU's explicit inline tags; escape all other source text."""
    return "".join(part if _INLINE_TAGS.fullmatch(part) else escape(part)
                   for part in _INLINE_TAGS.split(value))
