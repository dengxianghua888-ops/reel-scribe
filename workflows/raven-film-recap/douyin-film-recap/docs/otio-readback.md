# Saved-snapshot readback proposals (X2)

X2 compares an X1 base export, the current film Storyboard, and a newly saved
OTIO snapshot. It never changes the host project, Storyboard, state, or generation
pointer. It does not automatically adopt a proposal. It does not open, save,
reopen, or render in an actual NLE.

## Use

Save a new OTIO export from the editing host using its own workflow. Then archive
that saved file and its referenced media into a **new** local snapshot directory:

```bash
python -m douyin_film_recap.otio_readback capture \
  --export-package ./exports/cuts-001 \
  --saved-otio ./host-work/saved-edit.otio \
  --media-root ./exports/cuts-001 \
  --snapshot-dir ./readbacks/saved-edit-001

python -m douyin_film_recap.otio_readback propose \
  --export-package ./exports/cuts-001 --work-dir ./work/project \
  --snapshot-dir ./readbacks/saved-edit-001 \
  --output ./readbacks/proposal-001.json
```

`media-root` is explicit; its default is the saved OTIO file's directory. Only
safe relative media paths are followed. Absolute paths, `file://`, network URLs,
escaping paths and links are preserved as raw evidence but block interpretation.
This is a restricted file interchange route, not a general native-project parser.
Missing media is a finding; no remote fetch or relink guess occurs.

The capture directory contains exact saved OTIO bytes, independent verified
resource copies, snapshot-manifest.json and a last-written COMPLETE checksum
manifest. Optional `--caption-document` supplies a JSON `{ "captions": [...] }`
with explicit stable caption IDs. `--companions-json` supplies a mapping of
archive names to saved files (for example an untouched native project or ASS).
Companions are archived byte-for-byte as opaque evidence, never interpreted or
reapplied. All paths must be new. Existing files are never replaced.

The saved snapshot is hash-sealed, not an OS-enforced immutable file or signed
trust record. The original host file is compared again after capture. A later
change is reported as DIVERGED; the archived branch remains available. Absence
of a later change is not a cross-system CAS or a promise about unsaved host edits.

Readback pins the existing COMPLETE checksum manifests for both the export and
saved snapshot. The binding, projection, original Storyboard, snapshot manifest,
saved OTIO and optional caption JSON are parsed from the same byte buffers that
match their pinned checksum rows. A changed member or even a self-consistent
replacement snapshot is rejected, rather than reporting the old identity for
new fields. Resource, optional caption and opaque companion identities that
provide a snapshot path must agree with that member's sealed SHA and any recorded
byte length; rewriting only the seal cannot certify contradictory manifest data.
Both packages are checked again before returning a proposal; byte
drift is a blocking error, not an opaque host-format compatibility finding.
Failure preserves the archived bytes and current film authority. These are
observable boundary checks, not a continuous filesystem lock or a guarantee
against a hostile process with the same permissions.


## Comparison contract

- Base identity comes from the verified X1 export binding and projection.
- Current identity/version comes from the existing I2 `freeze_revision` token,
  including sources and narration bytes. Same path with new narration bytes is
  a different binding, not an unchanged clip.
- Host identity requires persistent recap export, track, occurrence and resource
  IDs. Clip names, source paths, text and timecodes are not replacement IDs.
  Repeated-source instances cannot be matched after losing IDs. No fuzzy matching.
- Clip.1 and the single-active-reference Clip.2 upgrade are interpreted. Gaps
  reconstruct target placement; source range comes from the actual OTIO field,
  never stale recap metadata. Exact known source/timeline rates are restored
  only after validating the serialized double rate; subframes are rejected.
- Same SHA at a new safe relative path is a valid media relocation. New bytes
  with the old resource ID are a conflict. Ranges beyond verified source frames
  or samples are rejected even if a legacy duration field is too large.
- Only confirmed host-only field changes are proposed. The report distinguishes
  host-only, current-only, converged and conflicting changes. It binds a hash
  of every current field value as a future precondition.
- Same-field concurrent changes conflict. Different timing fields also conflict
  when their anchors interact. Current changes to narration, source evidence,
  audio ownership or protected fields require review before a host timing edit.
  Notes/title-only current edits are retained and do not create a false conflict.
- Unknown fields/effects/markers survive in raw snapshots and an opaque report.
  Timing edits affecting their clip, track or unknown global scope are blocked
  for adoption. Merely retaining an unknown keyframe blob does not prove safety.
- Deletion, additions, split/merge, ID loss and caption removal require an explicit
  mapping outside this first readback subset. They are not inferred from absence.
- Caption comparison requires explicit stable IDs. If the current Storyboard
  changed, an explicit current caption map is required; old caption timing is
  not assumed valid. Raw SRT numbering is never treated as a persistent ID.

Statuses are NO_CHANGES, READY_FOR_REVIEW, NEEDS_REVIEW, CONFLICT or DIVERGED.
READY_FOR_REVIEW means field interpretation is available for review; it does not
mean the film can execute those edits, that narration intent was inferred, or
that QC passed. A conflict report may retain independent, nonconflicting proposed
fields so the reviewer can see useful work, but no proposal is automatically run.

## Eventual adoption boundary

The report carries `current_revision_base` and identifies the existing
`revision.adopt_revision` entry. A later integration must map an authorized
subset back into a Storyboard candidate, set explicit scope, revalidate the
current base and source/evidence/protection contracts, and rerun affected QC.
No new revision database or editable Work copy is created. The initial I2 local
entry supports a narrower set of changes than every field visible in an OTIO
proposal; unsupported trim/order/audio/caption mapping remains pending.

There is no host CAS. Therefore even eventual adoption would certify only this
saved branch, never overwrite or synchronize a live host project. Actual host
import, ID survival after saved reopen, rendered equivalence and an adopted
roundtrip all remain NOT_RUN until independently tested in a named host version.

## Local tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_otio_readback.py -v
PYTHONPATH=src python -m unittest discover -s tests -p test_readback_snapshot_identity.py -v
```

Tests cover unchanged files, repeated-source lost IDs, field/cross-field conflicts,
notes preservation, protected and semantic anchors, unknown effects, media
relocation/drift, Clip.2 upgrade, caption IDs/current binding, live-file divergence,
tampering, no-overwrite and narration replacement at the same path. The fixtures
exercise saved JSON/media contracts, not actual host behavior.

### Track endpoints and trailing blank intervals

Readback retains each recognized track's exact rational endpoint, including Gap
durations. Endpoint changes are compared against both the exported and current
cut projections; unsupported terminal blank intervals return a blocking conflict
and no adoptable changes. This applies to shorter audio tracks even when the
overall timeline maximum is unchanged. A later snapshot that removes an added
tail gap back to the original export is correctly unchanged relative to that
export, not treated as a diff against the previous snapshot. No active host file
is modified.

Snapshot capture rejects `..` traversal in destination, package, saved-OTIO and
media-root paths before creating any directory. It rejects symlink components
before canonical containment checks. A snapshot cannot be created inside the
frozen export package, including its media directory; rejected capture leaves
the package's original member set and checksums intact.

### Offline media relocation checks

The saved-branch tests explicitly distinguish a safe relative relocation with
the same SHA from a replacement with the same name and different bytes. Missing
media and old absolute media references return blocking findings even when the
old absolute file still exists; capture does not guess a replacement path. A
symlink inside an otherwise valid media root cannot supply a resource either.
These negative captures preserve the exact saved OTIO bytes, capture no unsafe
resource, and produce a conflict with no proposed adoption. They do not repair
the host project or prove a particular NLE can relink the media.

If the original saved file later becomes unavailable, `live_origin=UNKNOWN`
describes only that observation gap. The verified snapshot may still yield a
historical proposal for review; `adoption_performed=false`, `active_host_write=false`
and `host_cas=false` remain in force. This is neither proof that a live edit was
applied nor proof that the host project stayed unchanged. Existing same-field,
timing-dependency and unknown-effect conflicts remain blocking.

## Host validation record template

Current host acceptance is **NOT_RUN**: no named NLE/version has been selected or
accessed for these offline contracts. Copy the following record into the existing
task report when an authorized host is available. Leave actual results and
evidence blank until observed; an official OTIO parser test or a byte-only
fixture cannot fill a host result. This is a report template, not a new exchange
format, automated adoption path, or requirement to install an editor now.

| Record field | Actual value |
|---|---|
| Test date and operator | |
| Host product, exact version and build | |
| OS/version/architecture; importer/exporter or adapter version | |
| Repository commit; export ID and export-binding SHA256 | |
| Base Storyboard SHA256; package checksum manifest SHA256 | |
| Authorized media resource IDs and SHA256; explicit media root | |
| Saved project/OTIO identity and SHA256 before and after reopen | |
| Requested edit, permitted fields/ranges, protected fields | |
| Re-exported OTIO/snapshot/proposal identities and SHA256 | |
| Affected audio/video output identities and SHA256 | |

| Check | Actual result / evidence | Status |
|---|---|---|
| Import into the named host: tracks, media references, frame/sample rates and gaps | | NOT_RUN |
| Save to a new host project, close, reopen and verify the saved state | | NOT_RUN |
| Compare export/track/occurrence/resource IDs across saved reopen, including repeated sources | | NOT_RUN |
| Exercise one explicitly supported timing edit; record intended and actual source/target ranges | | NOT_RUN |
| Re-export and capture a new saved branch; compare expected fields and non-target preservation | | NOT_RUN |
| Check ID-loss, same-field conflict and unknown-effect cases remain unadopted | | NOT_RUN |
| Inspect the affected rendered picture and audio with exact covered time ranges | | NOT_RUN |
| Record unresolved losses, conflicts, unsupported fields and any failed/partial step | | NOT_RUN |

A supported timing proposal still needs fresh current-version checks, explicit
mapping and affected QC before any later adoption. A host reopen does not certify
rendered audio/video equivalence; a rendered excerpt does not certify the whole
film. Keep engineering, host interchange and human audiovisual results separate.
