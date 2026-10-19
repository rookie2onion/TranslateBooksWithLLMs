# Book Translation

Terminology for recognizing document content and producing readable book renditions.

## Language

**Online recognition**:
Recognition of document text, structure, and visual assets by a third-party service. It is distinct from translation, which changes the content's language.

**Upload authorization**:
The user's explicit permission to send a particular task's source document to the online recognition service. Selecting a document does not by itself grant upload authorization.

**Reconstruction**:
A readable rendition assembled from recognized document content and visual assets. Reconstruction does not, by itself, mean translation or an exact replica of the source pages.

**Original-language EPUB**:
A reconstruction in EPUB form that retains the recognized source language without translation. It may combine reflowed text with source-preserved images of complex content.

**Local recognition pause**:
A halt in this application's recognition work while the provider's task may continue. Continuing the task means retrieving its existing result, not implicitly requesting recognition again.

**Whole-book coverage**:
Every source page has a recognition result, and every recognized block is retained or has a stated exclusion. Coverage does not guarantee recognition accuracy or translation of source-preserved text.

**Source-preserved content**:
Content retained in its source form rather than semantically translated, including tables, formulas, and text embedded in images. It is present in the rendition, but its internal text remains untranslated.

**Reflowed layout**:
A layout that preserves the content's reading order and structural relationships while allowing pagination, line breaks, and element positions to differ from the source.
_Avoid_: Geometric replica, page facsimile
