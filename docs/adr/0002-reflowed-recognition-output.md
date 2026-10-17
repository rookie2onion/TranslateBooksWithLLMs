# Reflowed recognition output instead of geometric replication

The next online-recognition integration will produce reflowed renditions rather than geometric replicas of source PDF pages. Acceptance requires preserving reading order, heading hierarchy, images, and the content and associations of captions and footnotes, but does not require matching source pagination, line breaks, or element positions. This continues the existing reconstruction direction and accommodates translated text changing length without turning pipeline integration into a page-layout replication project.

## Consequences

- A source-language reconstruction preview is not evidence that a translated book preserves these properties; the translation path needs its own acceptance proof.
- Source preservation for tables, formulas, and image-embedded text is recorded separately in [ADR 0003](0003-source-preserved-complex-content.md).
- Output-format sequencing, delivery entrypoints, and open operational choices are tracked in the [integration planning record](../plans/mineru-online-translation-integration.md).
