# Testing

## Public, reproducible checks

Python 3.11+:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py" -v
python tests/run_public_validation.py --blender /path/to/blender
```

The public runner uses synthetic geometry: bounded cap repair and rollback, limited patch recovery, strict Tree topology/export smoke and Classic smoke. It propagates process failures and writes logs/results to reports/public_validation. Blender 5.2.1 LTS is the validated target. No private fixture download is required. Optional package identity/UI checks are described in docs/PUBLISHING.md.

GitHub CI runs offline tests and checks the source/package build on Linux; it does not claim a Blender or physical-print pass. A local Windows Blender run is recorded in the release-preparation report supplied with the handoff.

The internal development suite passed 310 checks on the preceding source. It includes additional private real-model regressions and is not represented as reproducible by this smaller public suite.

## Manual tester checklist

Use a model you may share. Check the displayed commit, settings and original orientation. Review underside details, local low points, tip/neck continuity, long stems, raft attachment, slicer layers, and MINI/support alignment after export. Record runtime by phase. Treat warnings and blocked export as incomplete results; do not disable checks merely to finish a test.

When reporting performance, compare identical inputs/settings and avoid simultaneous calculations. When reporting a visual gap, include the scene or a minimal permitted fixture and show whether the object is the final mesh or a diagnostic graph.
