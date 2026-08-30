# The doc-drift contract

A claim that was true when it was written and is false now is worse than one never made. It
reads as evidence right up until somebody checks it, and the people who check it are
interviewers. So every checkable claim on this repository's front page has a test behind it,
and this file is what `tests/test_doc_contract.py` refers to when it says the contract itself
lives somewhere else.

It was named there and did not exist. Anyone following the reference found nothing, which is
the same failure the contract is about, one level up from the claims it governs.

## The four kinds of claim, and what checks each one here

| Kind | What it covers | Checked by |
| --- | --- | --- |
| NUMBER | a figure on the page against the measurement that produced it | `test_the_numbers_on_the_page_are_the_measured_ones` |
| COMMAND | a command the page offers against what CI actually runs | `test_every_command_the_page_offers_is_one_ci_runs` |
| OUTPUT | a quoted block, line by line, against the transcript it names | `test_every_block_quoted_from_a_transcript_is_in_that_transcript` |
| REFERENCE | every link and path against what exists | `test_every_path_and_link_on_the_page_exists` |

All four live in `tests/test_readme.py`. `tests/test_doc_contract.py` names them and fails if one
is deleted or renamed, so the table above cannot quietly become a description of what used to be
true. That file is generated from a manifest shared across this toolset: editing it achieves
nothing, and the half of the contract that varies per repository is the four names.

## How a path in the prose is resolved

In order: the repository root, then `src/`, then a unique basename anywhere in the tree. The
second step exists because prose names an import path and the file sits under `src/`; both
spellings are correct and refusing the first would be wrong. The third applies only to a claim
with no directory in it, because a claim naming a directory is making a claim about that
directory.

A path the README names on purpose that is genuinely not here is declared in `FILE_EXCEPTIONS`,
and a declared exception that starts resolving is removed rather than left standing. There are
none in this repository.

## What this does not cover, and what does

The contract watches the README. Two other surfaces make claims and are watched elsewhere:

- `site/index.html`, the published card, by `scripts/check_card.py`, which compares the captured
  transcript whole, each cell of the facts strip against `docs/evidence/facts.json`, and the
  figures in the sentence carrying the backwards-clock claim against what the session produces.
  The publication workflow and the offline suite both run it, so they cannot disagree.
- every other file that names a document or repeats a sentence, by `tests/test_prose.py`.
