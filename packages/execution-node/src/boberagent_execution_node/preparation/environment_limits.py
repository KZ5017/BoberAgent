"""Closed E5-E @2 capacities, never derived from caller input or executable size.

Three copied ~30 MiB uv CPython executables plus stdlib configuration/templates
fit the 128 MiB cumulative write bound. Scratch adds 64 KiB per permitted entry
for filesystem allocation/metadata slack; logical bytes remain separately gated.
The aggregate memory cap covers tmpfs, anonymous export, copy buffers and the
trusted interpreter. C/D's separate limits are deliberately unaffected.
Standalone Python/native literals are cross-checked by native/helper regressions.
"""

WRITE_LIMIT = 128 * 1024**2
MANIFEST_FRAME_LIMIT = 65536  # Four-byte prefix plus at most 65,532 JSON bytes.
EXPORT_LIMIT = WRITE_LIMIT + MANIFEST_FRAME_LIMIT
FILE_LIMIT = 256
SCRATCH_LIMIT = WRITE_LIMIT + FILE_LIMIT * 65536  # 144 MiB, including allocation slack.
MEMORY_LIMIT = 512 * 1024**2
