# Experimental Blender Color Balance bridge (opt-in)

`tools/editor-adapters/blender_color_balance.py` carries Reel color grades into Blender's native strip **Color Balance** modifier, and reads Color Balance edits back as Reel grades, so a user can keep adjusting a grade with Blender's own controls. It is a standalone tool for projects made by [the experimental cut importer](blender-cut-import.md); it is not a registered runtime adapter and does not change Work rendering.

It supports the Blender **4.3** and **5.3** series. The color math is the same in both; the Python API differs (`sequences_all` and `SequenceColorBalanceData` in 4.3, `strips_all` and `StripColorBalanceData` in 5.x), and the tool selects by version. Other series fail closed with `HOST_VERSION_UNSUPPORTED`.

## What maps exactly

Color Balance can express exactly one thing Reel grades also express: **one ASC CDL operation with saturation 1 at full strength**. The tool maps only that and refuses everything else with `BLENDER_GRADE_NOT_REPRESENTABLE`, naming the reason, rather than approximating:

- curves, HSL, white balance, exposure, LUT and highlight roll-off operations, or more than one operation;
- a saturation other than 1 (Color Balance has no saturation stage; the strip's own Saturation control uses different math);
- a grade strength below 1.

Values must stay inside color-grade-compile's `cdl` bounds (slope 0–4, offset −1–1, power 0.1–4), so every read-back grade compiles.

### Blender's storage and math

From the Blender sources (4.3.2 `sequencer/intern/modifier.cc`; 5.0–5.3 `sequencer/intern/modifiers/MOD_color_balance.cc`):

- **Offset/Power/Slope** (ASC CDL): Blender applies `max(x·slope + offset, 0) ^ power`, where the UI stores `offset + 1` and the **reciprocal** of the power unless *Inverse Power* is set; *Inverse Slope* and *Inverse Offset* invert or negate those values.
- **Lift/Gamma/Gain**: Blender applies `max(((x − 1)·lift + 1)·gain, 0) ^ gamma` with lift stored as `2 − lift`, gamma stored as its reciprocal unless *Inverse Gamma* is set, and an extra curve on lift when *Inverse Lift* is set. Algebraically this is an ASC CDL with `slope = lift·gain`, `offset = (1 − lift)·gain`, `power = gamma`, so both modes read back as one Reel `cdl` operation.
- Reel's CDL clamps to [0,1] before the power stage; Blender only clamps below 0. For positive powers both give the same result after the final [0,1] clamp of the output.
- `color_multiply` multiplies after the power stage, which a CDL cannot express; any value other than 1 is refused. Zero slopes, powers, gains or gammas are refused: 4.3 and 5.x invert them differently.
- 8-bit movie frames go through a 1024-entry table, so Blender's output can differ from the exact formula by under one code value.

## Usage

```sh
# Apply: grades keyed by the strips' reel_instance_id; writes a NEW project, never saves over the opened one.
blender -b --disable-autoexec PROJECT.blend --python-exit-code 1 \
  --python tools/editor-adapters/blender_color_balance.py -- apply ASSIGNMENTS.json NEW.blend
# Read: Color Balance modifiers back as color-grade/1 grades with the declared interpretation.
blender -b --disable-autoexec PROJECT.blend --python-exit-code 1 \
  --python tools/editor-adapters/blender_color_balance.py -- read srgb-sdr-display GRADES.json
```

`ASSIGNMENTS.json` is `{"schema": "blender-color-balance-assignments/1", "grades": {"<reel_instance_id>": <color-grade/1>}}`.

### Host checks (both directions)

- The scene must carry the cut importer's `reel_adapter` binding, have no animation data (keyframed modifier values would change the grade over time), and keep the importer's color setup: sRGB sequencer space, Standard view, no look, exposure 0, gamma 1, no curve mapping.
- Movie strips must use the sRGB colorspace, so code values pass unchanged into the modifier, and must not use linear modifiers (4.3 only) or the strip's own multiply or saturation.
- **Apply** validates every grade and target strip before the first host change. Targets must exist and have no modifiers. After setting a modifier, the tool reads the stored values back and compares the effective CDL with the grade (1e-6, float32 storage). It saves a copy and refuses an existing output path.
- **Read** accepts at most one modifier per movie strip, which must be an enabled Color Balance modifier without a mask. Any other modifier type, a stack or a mask fails with `HOST_MODIFIER_*`. Ungraded strips are listed.
- The interpretation (`bt709-sdr-display` or `srgb-sdr-display`) is the caller's declaration on read: Blender works on code values and does not record one.

The [cut readback](../blender-saved-cut-readback-20261112.md) still rejects every modifier. A project carrying Color Balance must have its grades read with this tool; its cut cannot be read back by the cut bridge until that bridge is extended.

## Acceptance evidence, 2026-11-22

Hosts: the `bpy` 4.3.0 module (Python 3.11) and the `bpy` 5.3.0 module (Python 3.13) from PyPI, run in the background. The cut importer itself pins 4.3.2; 4.3.0 is the same series but a different patch release.

- `tests/editor_adapters/test_blender_color_balance_host.py` (4 tests, skipped without `bpy`) passed in both hosts. Each test builds a scene shaped like the cut importer's, renders without and with the modifier, and compares Blender's pixels with the CDL applied to Blender's own unmodified render, which keeps decoder differences out:
  - applied grade: maximum difference ≤ 1 code value, while the grade changes the picture by more than 20. The saved copy reopens and renders identically. The opened project on disk is unchanged. Read-back values equal the applied ones;
  - a Lift/Gamma/Gain edit made in the host, with and without the invert flags, reads back as a CDL that reproduces the render within 1 code value;
  - a Curves modifier, `color_multiply` 1.5 and a grade with saturation are refused, and the host is left unchanged.
- Real photo clips (the four 420×280 sRGB shots used by the color records, one movie strip each), a warm CDL grade on all four, middle frame of each shot:
  - read-back grades equal the applied ones in both hosts;
  - Blender's graded render versus the CDL applied to its unmodified render: maximum 0.615 code values per shot, mean 0.15–0.17. The grade itself changes the picture by 10–13 code values on average;
  - Blender's graded render versus Reel's own render of the same grade (color-grade-compile, 65-point cube, color-lut-apply, 4:2:0 encode): median ΔE2000 0.73–1.12 per shot. Decoding alone differs by 0–0.34 between Blender and FFmpeg; Reel's output also carries its lossy 4:2:0 encode.
- `tests/editor_adapters/test_blender_color_balance.py` (31 tests, no host) checks the mapping against color-grade-compile's chain on random grades and points (1e-9). It checks Lift/Gamma/Gain against an independent transcription of Blender's formula. It also runs the host rules on stub objects. Replacing `2 − lift` with `lift` makes both test files fail.

Not claimed: GUI acceptance, other Blender versions or patch releases, color under linear-modifier or non-sRGB sequencer setups, other modifier types, animated grades, or that a grade looks right.
