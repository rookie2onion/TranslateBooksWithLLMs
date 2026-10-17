# Preserve complex source content instead of reconstructing its semantics

The first online PDF translation release may preserve tables and formulas as source images and leave text embedded in image pixels unchanged, rather than promising semantic table translation, editable reconstruction, or image-text redrawing. Body text and independently recognized captions and footnotes remain translatable; source-preserved content must be explicitly identified as untranslated. This bounds the integration effort while preserving the original information instead of silently dropping currently unsupported structures.

## Consequences

- Source-image preservation must retain the correct source block, its reading-order position, and its relationship to nearby captions or notes.
- A block that cannot be reliably preserved must cause an explicit failure, not disappear from an apparently successful book.
- Whole-document content coverage must not be described as proof that every visible word has been translated.
