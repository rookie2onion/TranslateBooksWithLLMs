# Explicitly authorized online recognition

PDF translation has one user-facing recognition path: MinerU online, with no native extraction selector or implicit local fallback. Online recognition is still opt-in: submitting a task's PDF to the third party requires explicit authorization for that task, so selecting a document alone must not trigger provider upload. The deployer supplies a MinerU account and credentials through the existing `.env` mechanism; quota usage and any charges belong to that account, without project-funded recognition or a new billing system.

This favors one predictable recognition path and a visible privacy and cost boundary over multiple extraction modes or an unexpected third-party fallback.

## Consequences

- This release is for personal use. Do not add commercial compliance workflows or long policy-warning dialogs; retain a brief, explicit task-level confirmation that the PDF will be sent to MinerU.
- Missing authorization must leave the document unuploaded to MinerU; there is no automatic local-extraction substitute for a denied online task.
- Server-side and non-Web entrypoints must not bypass the per-task authorization boundary.
- Recognition authorization does not authorize an actual test run in this repository; live document submissions still need explicit approval.
- Provider retention and deletion rules remain unverified. Further policy research is not a gate for this personal-use development scope, but the application must not promise immediate deletion or a retention period that has not been established.
- Stopping local work must not be described as confirmed remote cancellation or avoidance of quota usage or charges.
