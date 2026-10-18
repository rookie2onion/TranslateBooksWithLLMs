# MinerU online V2 table and formula contract (source-preserved content)

Evidence used by the source-preserved content slice (issue #22). This note records
what was verified, not an implementation proposal.

## Observed online representation

The authorized online probe recorded by issue #20 requested `model_version=vlm`
with `enable_table=true` and `enable_formula=true`. The service returned:

- `layout.json`: `_backend: "hybrid"`, `_version_name: "3.4.4"`, `_ocr_enable: true`
- one `*_content_list_v2.json`, grouped by page
- V2 block types `title`, `paragraph`, `image`, `page_footnote`, `page_header`,
  `page_number` on the selected sample

The sample contained no table or formula case, so the table/formula shapes below
come from the first-party 3.4.4 implementation that produces that same V2 file.
The online service's reported `_version_name` pins the schema version; an online
result from another engine version that reports different shapes is not accepted
by the loader.

## First-party schema evidence (MinerU 3.4.4)

Source inspected from the published `mineru==3.4.4` wheel:

- `mineru/backend/vlm/vlm_middle_json_mkcontent.py`:
  `make_blocks_to_content_list_v2()` builds the V2 blocks consumed here.
- `mineru/utils/enum_class.py`: `ContentTypeV2` names the type strings
  (`table`, `equation_interline`, `simple_table`, `complex_table`,
  `equation_inline`).

The contracted shapes are:

```json
{
  "type": "table",
  "bbox": [x0, y0, x1, y1],
  "content": {
    "image_source": {"path": "images/....jpg"},
    "table_caption": [{"type": "text", "content": "..."}],
    "table_footnote": [{"type": "text", "content": "..."}],
    "html": "<table>...</table>",
    "table_type": "simple_table | complex_table",
    "table_nest_level": 1
  }
}
```

```json
{
  "type": "equation_interline",
  "bbox": [x0, y0, x1, y1],
  "content": {
    "math_content": "E = mc^2",
    "math_type": "latex",
    "image_source": {"path": "images/....jpg"}
  }
}
```

Inline formulas are not separate blocks: they are
`{"type": "equation_inline", "content": "<latex>"}` runs inside a text block's
span list (for example `paragraph_content`).

## Preservation decisions

- **Supplied asset only.** Tables and interline formulas are embedded from the
  provider's `image_source` asset. The loader validates its cache-relative path,
  extension, byte/pixel bounds, decodability and fingerprint.
- **No speculative crop.** The source PDF is fingerprint-matched, but a missing
  supplied asset is an explicit result failure rather than a crop from page
  geometry. Page identity and geometry alone were not established as reliable
  enough for silent cropping, and a dropped or mis-cropped block must never
  appear as a successful book.
- **No semantic table claim.** The contracted `html` body is validated as a
  string but never rendered or translated. The PDF embeds the source image and
  says it is untranslated; editable/semantic table reconstruction is out of
  scope.
- **Reading position and associations.** The source image is anchored at the
  adapter's current reading position (including before the first paragraph,
  anchor `-1`). Table captions/footnotes are emitted as independently
  translatable paragraphs with their own provenance; the image keeps its
  source-page provenance.
- **Separated accounting.** Ordinary figures, source-preserved blocks, translated
  paragraphs and failed translation chunks are counted separately in the
  accounting sidecar and the task-status summary.
- **Inline formulas are a stated limitation.** MinerU 3.4.4 does emit an
  `equation_inline` span type, but this application has no verified preservation
  path for a formula run embedded in a paragraph (no isolated supplied image,
  and translating LaTeX as prose is unsafe). Documents containing such runs fail
  with the stable `mineru_unsupported_content` code instead of silently dropping
  the formula. Non-LaTeX `math_type` variants are refused for the same reason.
- **Unknown structures stay fail-closed.** Other block types, span types and
  table/formula shapes not in the contract above are rejected as invalid results.
