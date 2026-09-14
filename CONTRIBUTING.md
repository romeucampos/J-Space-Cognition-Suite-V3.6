# Contributing

Contributions should preserve J-Space's selective, lightweight operating design and keep the
English and Chinese README files aligned when shared behavior or public claims change.

Before submitting a change:

1. Keep edits scoped to a demonstrated problem or a clearly stated capability.
2. Reuse established suite language when a script enforces a documented invariant.
3. Run the integrity check and the complete standard-library test suite on Python 3.10+.
4. Add a focused regression test for any controller or verifier defect.
5. Identify the source and rights for any external text, code, data, image, or model trace. Do
   not submit private, undisclosed, or source-untraceable material. Publicly documented
   third-party traces require point-of-use attribution, provenance labelling, a rights analysis,
   and an entry in `THIRD_PARTY_NOTICES.md`.

Keep runtime prose in English, with `README.zh-CN.md` as the Chinese guide. Preserve source
quotations and multilingual research examples. Keep Unicode fixtures and multilingual input
recognition in code; those validate compatibility rather than changing the instruction language.
Write protocols in the second person and use brief first-person task commitments. Distinguish
research results from engineering choices and measured task outcomes from performance claims.

For control changes, validate real CLI workflows in disposable directories, including rejected
operations and stale evidence. Check the shared record, source receipts, map, and reports after
each state transition. Keep repair actions available when a work gate blocks. For substantial
suite changes, perform two independent review rounds covering requirements, language, routes,
runtime behavior, portability, and practical usage; fix findings and retain review evidence
outside the public package. Keep public tests and CI reproducible. Do not include private
conversation summaries, development transcripts, unpublished research, paper drafts, review
prompts, or internal delivery/change reports in the distributed tree.

Unless explicitly stated otherwise, intentionally submitted contributions are provided under
the repository's Apache License 2.0 in accordance with Section 5 of that license. Third-party
materials retain their original terms and must also be recorded in `THIRD_PARTY_NOTICES.md`.
