"""Local result export tested through the agreed command/artifact boundary."""

import json
import zipfile
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from src.core.mineru.__main__ import main
from tests.test_mineru.mineru_fixture import tree_fingerprint

XHTML = "{http://www.w3.org/1999/xhtml}"


def text_block(text, kind="text", **extra):
    return {"type": kind, "bbox": [10, 20, 190, 50],
            "lines": [{"spans": [{"type": "text", "content": text}]}], **extra}


def bundle(tmp_path, blocks, discarded=()):
    root = tmp_path / "input"
    (root / "images").mkdir(parents=True)
    Image.new("RGB", (40, 20), "blue").save(root / "images" / "figure.jpg")
    layout = {"_version_name": "3.4.4", "_backend": "hybrid", "pdf_info": [
        {"page_idx": 0, "page_size": [200, 300], "para_blocks": blocks,
         "preproc_blocks": blocks, "discarded_blocks": list(discarded)}]}
    (root / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    return root


def export(root, out, *extra):
    return main(["--input", str(root), "--output-dir", str(out),
                 "--language", "de", "--title", "Sample book", "--json", *extra])


def documents(out):
    with zipfile.ZipFile(out / "book.epub") as archive:
        assert archive.namelist()[0] == "mimetype"
        assert archive.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        for name in archive.namelist():
            if name.endswith((".xhtml", ".opf", ".xml")):
                ET.fromstring(archive.read(name))
        return [ET.fromstring(archive.read(n)) for n in archive.namelist()
                if n.startswith("OEBPS/text-")]


def test_local_command_exports_original_text_images_and_report(tmp_path):
    root = bundle(tmp_path, [text_block("Before heading"),
                            text_block("Recognized title", "title", level=1),
                            text_block("A & B < C"),
                            {"type": "image", "bbox": [10, 70, 190, 150], "blocks": [
                                {"type": "image_body", "bbox": [10, 70, 190, 150],
                                 "lines": [{"spans": [{"type": "image",
                                                        "image_path": "figure.jpg"}]}]}]}])
    before = tree_fingerprint(root)
    out = tmp_path / "output"
    assert export(root / "layout.json", out) == 0
    docs = documents(out)
    text = "".join(docs[0].itertext())
    assert text.count("A & B < C") == 1
    assert "Before heading" in text
    assert "preview" not in text.lower()
    assert len(docs[0].findall(f".//{XHTML}img")) == 1
    report = json.loads((out / "book.report.json").read_text(encoding="utf-8"))
    assert report["counts"]["blocks_seen"] == 4
    assert report["counts"]["blocks_unaccounted"] == 0
    assert report["coverage"]["scope"] == "supplied_result"
    assert tree_fingerprint(root) == before


def test_local_command_preserves_reference_items_figcaption_and_discarded_note(tmp_path):
    figure = {"type": "image", "bbox": [10, 70, 190, 180], "blocks": [
        {"type": "image_body", "bbox": [10, 70, 190, 150],
         "lines": [{"spans": [{"type": "image", "image_path": "figure.jpg"}]}]},
        text_block("Figure caption", "image_caption"),
        text_block("Figure credit", "image_footnote")]}
    refs = [text_block("[1] First reference", "ref_text"),
            text_block("[2] Second reference", "ref_text")]
    root = bundle(tmp_path, [text_block("Book", "title", level=1), *refs, figure, figure],
                  [text_block("A substantive note.", "page_footnote")])
    out = tmp_path / "output"
    assert export(root, out) == 0
    doc = documents(out)[0]
    items = doc.findall(f".//{XHTML}ul/{XHTML}li")
    assert ["".join(x.itertext()) for x in items] == ["[1] First reference", "[2] Second reference"]
    caption = doc.find(f".//{XHTML}figure/{XHTML}figcaption")
    assert "Figure caption" in "".join(caption.itertext())
    text = "".join(doc.itertext())
    assert text.count("Figure caption") == 2
    assert len(doc.findall(f".//{XHTML}figure")) == 2
    assert "A substantive note." in text


def test_local_command_crops_formula_paragraph_and_table_without_changing_input(tmp_path):
    import pymupdf

    formula = text_block("Source text")
    formula["lines"][0]["spans"].append({"type": "inline_equation", "content": "x=1"})
    table = {"type": "table", "bbox": [10, 80, 190, 160], "blocks": [
        {"type": "table_body", "bbox": [10, 80, 190, 160], "lines": [
            {"spans": [{"type": "table", "image_path": "", "html": "<table/>"}]}]}]}
    root = bundle(tmp_path, [text_block("Book", "title", level=1), formula, table])
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=300)
        page.insert_text((12, 35), "Source text x=1")
        page.draw_rect(pymupdf.Rect(10, 80, 190, 160))
        pdf.save(root / "fixture_origin.pdf")
    before = tree_fingerprint(root)
    out = tmp_path / "output"
    assert export(root, out, "--source-pdf", str(root / "fixture_origin.pdf")) == 0
    doc = documents(out)[0]
    assert len(doc.findall(f".//{XHTML}img")) == 2
    assert "Source text" not in "".join(doc.itertext())
    report = json.loads((out / "book.report.json").read_text(encoding="utf-8"))
    assert report["counts"]["source_preserved"] == 2
    assert len(report["source_preserved"]) == 2
    assert all(x["method"] == "pdf_crop" for x in report["source_preserved"])
    assert tree_fingerprint(root) == before


@pytest.mark.parametrize("missing_kind", ["table", "text"])
def test_unpreservable_content_does_not_replace_existing_book(tmp_path, capsys, missing_kind):
    record = ({"type": "table", "bbox": [10, 80, 190, 160], "blocks": [
        {"type": "table_body", "bbox": [10, 80, 190, 160], "lines": []}]}
        if missing_kind == "table" else text_block("Formula context"))
    if missing_kind == "text":
        record["lines"][0]["spans"].append({"type": "inline_equation", "content": "x"})
    root = bundle(tmp_path, [record])
    out = tmp_path / "output"
    out.mkdir()
    (out / "book.epub").write_bytes(b"existing valid book")
    assert export(root, out) == 1
    assert (out / "book.epub").read_bytes() == b"existing valid book"
    assert "page 1 block 0" in capsys.readouterr().err
    assert not (out / "book.report.json").exists()


def test_unrelated_pdf_is_rejected_before_export(tmp_path, capsys):
    import pymupdf

    root = bundle(tmp_path, [text_block("Book", "title", level=1)])
    for path, content in [(root / "fixture_origin.pdf", "Original"),
                          (tmp_path / "unrelated.pdf", "Other source")]:
        with pymupdf.open() as pdf:
            pdf.new_page(width=200, height=300).insert_text((20, 50), content)
            pdf.save(path)
    assert export(root, tmp_path / "output", "--source-pdf", str(tmp_path / "unrelated.pdf")) == 1
    assert "fingerprint" in capsys.readouterr().err


def test_heading_hierarchy_survives_in_content_and_navigation(tmp_path):
    root = bundle(tmp_path, [text_block("Chapter", "title", level=1),
                            text_block("Section", "title", level=2),
                            text_block("Subsection", "title", level=3),
                            text_block("Detail", "title", level=4)])
    out = tmp_path / "output"
    assert export(root, out) == 0
    doc = documents(out)[0]
    assert doc.find(f".//{XHTML}h4").text == "Detail"
    with zipfile.ZipFile(out / "book.epub") as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
    path = f".//{XHTML}nav/{XHTML}ol/{XHTML}li/{XHTML}ol/{XHTML}li/{XHTML}ol/{XHTML}li"
    assert nav.find(path).find(f"{XHTML}a").text == "Subsection"


def test_xml_control_characters_are_preserved_as_source_image_not_rewritten(tmp_path):
    import pymupdf

    root = bundle(tmp_path, [text_block("Recognized\u0003word")])
    with pymupdf.open() as pdf:
        pdf.new_page(width=200, height=300).insert_text((12, 35), "Recognized word")
        pdf.save(root / "fixture_origin.pdf")
    out = tmp_path / "output"
    assert export(root, out) == 0
    assert len(documents(out)[0].findall(f".//{XHTML}img")) == 1
    report = json.loads((out / "book.report.json").read_text())
    assert report["source_preserved"][0]["reason"] == "xml_control_character"


def test_explicit_inline_markup_is_rendered_and_footer_page_number_excluded(tmp_path):
    footer = text_block("8", "page_number", bbox=[90, 285, 105, 295])
    root = bundle(tmp_path, [text_block("Area m<sup>2</sup> and H<sub>2</sub>O & x < y")], [footer])
    out = tmp_path / "output"
    assert export(root, out) == 0
    doc = documents(out)[0]
    assert doc.find(f".//{XHTML}sup").text == "2"
    assert doc.find(f".//{XHTML}sub").text == "2"
    report = json.loads((out / "book.report.json").read_text())
    assert report["blocks"][1]["disposition"] == "excluded"


def test_report_write_failure_keeps_previous_book(tmp_path):
    root = bundle(tmp_path, [text_block("A normal paragraph")])
    out = tmp_path / "output"
    out.mkdir()
    (out / "book.epub").write_bytes(b"previous book")
    (out / "book.report.json").mkdir()
    assert export(root, out) == 1
    assert (out / "book.epub").read_bytes() == b"previous book"


def test_merged_source_image_keeps_regions_from_both_pages(tmp_path):
    import pymupdf

    first = text_block("First\u0003part", index=1, bbox=[10, 220, 190, 250])
    first["lines"][0]["spans"][0]["bbox"] = [10, 220, 190, 250]
    first["lines"].append({"bbox": [10, 20, 190, 50], "spans": [
        {"type": "text", "content": "Second part", "bbox": [10, 20, 190, 50], "cross_page": True}]})
    root = bundle(tmp_path, [first])
    layout = json.loads((root / "layout.json").read_text())
    empty = {"type": "text", "index": 2, "bbox": [10, 20, 190, 50], "lines": [], "lines_deleted": True}
    layout["pdf_info"].append({"page_idx": 1, "page_size": [200, 300], "para_blocks": [empty], "discarded_blocks": []})
    (root / "layout.json").write_text(json.dumps(layout))
    (root / "block_list.json").write_text(json.dumps({"pdfData": [
        [{"id": "merged", "type": "text", "index": 1, "bbox": first["bbox"], "text": "First\u0003part Second part"}],
        [{"id": "merged", "type": "text", "index": 2, "bbox": empty["bbox"], "text": ""}]],
        "mergeConnections": [{"blocks": ["0-0", "1-0"], "type": "merge"}]}))
    with pymupdf.open() as pdf:
        pdf.new_page(width=200, height=300).draw_rect(pymupdf.Rect(10, 220, 190, 250), fill=(1,0,0))
        pdf.new_page(width=200, height=300).draw_rect(pymupdf.Rect(10, 20, 190, 50), fill=(0,0,1))
        pdf.save(root / "fixture_origin.pdf")
    out = tmp_path / "output"
    assert export(root, out) == 0
    report = json.loads((out / "book.report.json").read_text())
    entry = report["source_preserved"][0]
    assert [x["page"] for x in entry["regions"]] == [1, 2]
    with zipfile.ZipFile(out / "book.epub") as z:
        import io
        with Image.open(io.BytesIO(z.read("OEBPS/" + entry["resource"]))) as image:
            assert image.getpixel((image.width//2, 10))[:3] == (255,0,0)
            assert image.getpixel((image.width//2, image.height-10))[:3] == (0,0,255)


def test_source_preserved_figure_includes_caption_outside_image_bbox(tmp_path):
    import pymupdf

    body = {"type": "image_body", "bbox": [10, 20, 80, 80], "lines": [
        {"spans": [{"type": "image", "image_path": "figure.jpg", "bbox": [10, 20, 80, 80]}]}]}
    caption = text_block("Caption\u0003marker", "image_caption", bbox=[100, 200, 180, 240])
    caption["lines"][0]["spans"][0]["bbox"] = caption["bbox"]
    root = bundle(tmp_path, [{"type": "image", "index": 1, "bbox": body["bbox"],
                             "blocks": [body, caption]}])
    with pymupdf.open() as pdf:
        pdf.new_page(width=200, height=300)
        pdf.save(root / "fixture_origin.pdf")
    out = tmp_path / "output"
    assert export(root, out) == 0
    report = json.loads((out / "book.report.json").read_text())
    assert [x["bbox"] for x in report["source_preserved"][0]["regions"]] == [body["bbox"], caption["bbox"]]


@pytest.mark.parametrize("size", [(1200, 1600), (600, 2400)])
def test_reader_keeps_large_images_proportional_without_horizontal_clipping(tmp_path, size):
    import pymupdf

    root = bundle(tmp_path, [{"type": "image", "bbox": [10, 20, 190, 250], "blocks": [
        {"type": "image_body", "bbox": [10, 20, 190, 250], "lines": [
            {"spans": [{"type": "image", "image_path": "figure.jpg"}]}]}]}])
    Image.new("RGB", size, "blue").save(root / "images" / "figure.jpg")
    out = tmp_path / "output"
    assert export(root, out) == 0
    with pymupdf.open(out / "book.epub") as book:
        book.layout(width=420, height=640, fontsize=18)
        images = [(page, block) for page in book for block in page.get_text("dict")["blocks"]
                  if block["type"] == 1]
        assert images
        visible = []
        for page, block in images:
            # A tall image may continue on the next reader page. Check the
            # uncropped transform, not the clipped fragment's aspect ratio.
            whole = pymupdf.Rect(0, 0, 1, 1) * pymupdf.Matrix(block["transform"])
            assert whole.x0 >= 0 and whole.x1 <= page.rect.width
            assert abs(whole.width / whole.height - size[0]/size[1]) < 0.01
            box = pymupdf.Rect(block["bbox"])
            visible.append(((box.y0-whole.y0)/whole.height, (box.y1-whole.y0)/whole.height))
        assert min(start for start, end in visible) < 0.001
        assert max(end for start, end in visible) > 0.999


@pytest.mark.parametrize("kind", ["image", "chart"])
def test_missing_visual_crop_is_reported(tmp_path, kind):
    import pymupdf

    root = bundle(tmp_path, [{"type": kind, "bbox": [10, 20, 190, 150], "blocks": [
        {"type": f"{kind}_body", "bbox": [10, 20, 190, 150], "lines": [
            {"spans": [{"type": kind, "image_path": "missing.jpg"}]}]}]}])
    with pymupdf.open() as pdf:
        pdf.new_page(width=200, height=300)
        pdf.save(root / "fixture_origin.pdf")
    out = tmp_path / "output"
    assert export(root, out) == 0
    report = json.loads((out / "book.report.json").read_text())
    fallback = report["image_fallbacks"][0]
    assert fallback["type"] == kind
    assert fallback["reason"] == "image_missing_asset"
    assert fallback["method"] == "pdf_crop"
    with zipfile.ZipFile(out / "book.epub") as z:
        assert "OEBPS/" + fallback["resource"] in z.namelist()
