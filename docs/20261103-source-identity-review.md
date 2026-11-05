# Candidate bytes and source identity review (2026-11-03)

Base: `93ba9289aa6d3e883bc569f7161a7a002ea2ccda`.

## Acceptance criteria

- `work-variant-create` hashes exactly the byte buffer parsed as its candidate.
  Replacing the file between the initial reference check and parse, or during
  scope validation, fails before the child SQLite store is initialized.
- A normal variant retains its candidate reference, verified document and parent
  lineage. Its parent is never mutated. Existing scope and parent-version checks
  remain in force.
- Execution-plan source reuse is checked by validated content SHA-256, not by
  caller-chosen source ID. Same-path aliases, symlinks and identical copies cannot
  authorize overlapping reuse. Explicit reuse and non-overlapping cuts remain
  supported.
- Run runtime/package/drama regressions, library structure and fatal Python lint;
  run the unchanged film subsystem suite when its dependencies are available.

## Implementation references and limits

- [pip hash verification](https://github.com/pypa/pip/blob/main/src/pip/_internal/utils/hashes.py)
  checks hashes over byte chunks or a file object. It is mature package-installation
  infrastructure, [MIT licensed](https://github.com/pypa/pip/blob/main/LICENSE.txt).
  The relevant idea here is verifying consumed bytes, not trusting a separately
  checked pathname. This change also follows the repository's existing Work
  preview and commit pattern. No pip code or dependency is added.
- [restic content IDs](https://github.com/restic/restic/blob/master/internal/restic/id.go)
  derive an ID from SHA-256 of content, independent of a path label. It is mature
  backup software, [BSD-2-Clause licensed](https://github.com/restic/restic/blob/master/LICENSE).
  The small policy change here applies content identity only to overlap checks;
  it does not implement restic, add storage deduplication, or certify provenance.

Sources inspected 2026-11-03; links follow upstream branches rather than pinning
an imported version. No upstream implementation was copied.

The deterministic SQLite and synthetic-clock regression fixtures are not real
media/provider/user acceptance. Hash equality identifies identical bytes, not
semantic equivalence of separately encoded media. A second path check before
variant initialization is not a filesystem lock: the authoritative variant
still derives from the single verified in-memory buffer if the path changes
later. No parent or source file is overwritten by the operation.
