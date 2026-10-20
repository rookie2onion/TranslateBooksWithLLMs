"""Printed contents behavior through the production command and EPUB artifact."""

import json
import zipfile
from xml.etree import ElementTree as ET

from src.core.mineru.local_result import load_local_result
from src.core.mineru.structure import adapt
from tests.test_mineru.mineru_fixture import tree_fingerprint
from tests.test_mineru.test_local_epub import bundle, export, text_block

X = "{http://www.w3.org/1999/xhtml}"


def fixture(tmp_path, *, duplicate=False, unknown=False):
    mixed = "Alpha 9\nCross title\nOther 11\ncontinued 13"
    if unknown:
        mixed = "Lost source words 9\nUnidentified fragment 11"
    figure = {"type": "image", "bbox": [10, 70, 190, 150], "blocks": [
        {"type": "image_body", "bbox": [10, 70, 190, 150], "lines": [
            {"spans": [{"type": "image", "image_path": "figure.jpg"}]}]}]}
    root = bundle(tmp_path, [text_block("Contents", "title", level=1),
        text_block("Main topic 9", "title", level=1), figure, text_block(mixed),
        text_block("Space split 14"), text_block("Paragraph target 15"),
        text_block("Link to heritage 16"), text_block("Appendix 17")])
    path = root / "layout.json"
    layout = json.loads(path.read_text(encoding="utf-8"))
    body = [text_block("Main topic", "title", level=1),
            *[text_block(t, "title", level=2) for t in ["Alpha", "Other", "Cross title continued", "Spacesplit"]],
            text_block("Paragraph target"), text_block("Body text remains unchanged."),
            text_block("Link to cultural heritage", "title", level=2)]
    if duplicate:
        body.append(text_block("Alpha", "title", level=2))
    for records, discarded in [(body, [text_block("16", "page_number")]),
            ([text_block("Appendix first", "title", level=1), text_block("Appendix body.")],
             [text_block("Appendix", "header")]),
            ([text_block("More appendix data.")], [text_block("Appendix", "header")])]:
        layout["pdf_info"].append({"page_idx": len(layout["pdf_info"]), "page_size": [200, 300],
            "para_blocks": records, "discarded_blocks": discarded})
    path.write_text(json.dumps(layout), encoding="utf-8")
    return root


def artifacts(out):
    with zipfile.ZipFile(out / "book.epub") as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    xml = {name: ET.fromstring(data) for name, data in entries.items() if name.endswith(".xhtml")}
    for name, tree in xml.items():
        ids = [node.get("id") for node in tree.iter() if node.get("id")]
        assert len(ids) == len(set(ids)), name
        for node in tree.iter(X + "a"):
            path, _, fragment = node.get("href").partition("#")
            target = "OEBPS/" + path if path else name
            assert target in xml
            if fragment:
                assert any(n.get("id") == fragment for n in xml[target].iter())
    return xml, json.loads((out / "book.report.json").read_text(encoding="utf-8"))


def test_production_command_recovers_contents_and_links_with_source_evidence(tmp_path):
    root = fixture(tmp_path)
    before = tree_fingerprint(root)
    neutral = adapt(load_local_result(root))
    assert not neutral.printed_toc_entries  # Translation/PDF adaptation stays neutral.
    out = tmp_path / "out"
    assert export(root, out) == 0
    xml, report = artifacts(out)
    toc = xml["OEBPS/text-1.xhtml"]
    assert not list(toc.iter(X + "img"))
    plan = report["printed_toc"]
    assert plan["pages"] == [1]
    assert plan["entries"] == plan["linked_entries"] == 8
    details = {r["title"]: r for r in plan["entry_details"]}
    assert details["Space split"]["match_method"] == "whitespace_heading"
    assert details["Paragraph target"]["match_method"] == "exact_paragraph"
    assert details["Link to heritage"]["match_method"] == "printed_label_and_title_words"
    assert details["Appendix"]["match_method"] == "running_header_section_start"
    rows = [(r["title"], r["page_label"]) for r in plan["entry_details"]]
    assert rows[1:4] == [("Alpha", "9"), ("Other", "11"), ("Cross title continued", "13")]
    mixed = next(b for b in plan["blocks"] if b["proof"].get("disjoint_assignments"))
    assert mixed["proof"]["tokens"] == mixed["proof"]["assigned_tokens"] == 5
    assert report["counts"]["blocks_unaccounted"] == 0
    assert any("text-only printed contents" in e["reason"] for e in report["exclusions"])
    assert not any(a.get("href", "").startswith("text-1.xhtml#") for a in xml["OEBPS/nav.xhtml"].iter(X + "a"))
    assert tree_fingerprint(root) == before


def test_duplicate_target_stays_text_without_a_guessed_link(tmp_path):
    out = tmp_path / "out"
    assert export(fixture(tmp_path, duplicate=True), out) == 0
    _, report = artifacts(out)
    plan = report["printed_toc"]
    alpha = next(r for r in plan["entry_details"] if r["title"] == "Alpha")
    assert alpha["href"] is None
    assert plan["linked_entries"] == plan["entries"] - 1


def test_positioned_columns_keep_wrapped_titles_and_source_span_coverage(tmp_path):
    root = fixture(tmp_path)
    path = root / "layout.json"
    layout = json.loads(path.read_text(encoding="utf-8"))

    def span(value, x, y):
        return {"type": "text", "content": value, "bbox": [x, y, x + 65, y + 8]}

    layout["pdf_info"][0]["para_blocks"][3] = {"type": "text", "bbox": [10, 70, 190, 150],
        "lines": [{"spans": [span("Alpha 9", 10, 70), span("Other 13", 110, 70)]},
                  {"spans": [span("Cross title", 10, 80), span("Appendix 17", 110, 80)]},
                  {"spans": [span("continued 11", 10, 90)]}]}
    path.write_text(json.dumps(layout), encoding="utf-8")
    out = tmp_path / "out"
    assert export(root, out) == 0
    _, report = artifacts(out)
    details = report["printed_toc"]["entry_details"]
    assert [(r["title"], r["page_label"]) for r in details[1:5]] == [
        ("Alpha", "9"), ("Cross title continued", "11"), ("Other", "13"), ("Appendix", "17")]
    assert sorted(s for row in details[1:5] for s in row["source_spans"]) == [
        "0:0", "0:1", "1:0", "1:1", "2:0"]


def test_unknown_contents_text_is_retained_with_a_review_finding(tmp_path):
    out = tmp_path / "out"
    assert export(fixture(tmp_path, unknown=True), out) == 0
    xml, report = artifacts(out)
    unresolved = xml["OEBPS/text-1.xhtml"].find(f'.//{X}p[@class="toc-unresolved"]')
    assert unresolved.text == "Lost source words 9\nUnidentified fragment 11"
    assert any(f["code"] == "printed_toc_unresolved" for f in report["findings"])
    assert report["counts"]["blocks_unaccounted"] == 0


def test_ordinary_pages_are_not_promoted_by_terminal_numbers(tmp_path):
    root = fixture(tmp_path)
    path = root / "layout.json"
    layout = json.loads(path.read_text(encoding="utf-8"))
    layout["pdf_info"][1]["para_blocks"] = [text_block("Chapter 2024", "title", level=1),
        text_block("A substantive ordinary paragraph ending in a year 1999")]
    path.write_text(json.dumps(layout), encoding="utf-8")
    cache = load_local_result(root)
    assert cache.printed_toc.pages == (1,)
    layout["pdf_info"][0]["para_blocks"][0] = text_block("Ordinary chapter", "title", level=1)
    path.write_text(json.dumps(layout), encoding="utf-8")
    assert load_local_result(root).printed_toc is None
