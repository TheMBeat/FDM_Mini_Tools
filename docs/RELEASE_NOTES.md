# 0.3.0 RC2 — experimental test release

Fixes issue #1: English source interface, German localization including tooltips, clearer install asset names, validated one-folder ZIP layout and isolated Blender installation checks.

This release is for feedback and testing. Select **pre-release** on GitHub; do not mark it stable.

Tested: Blender 5.2.1 LTS on Windows. Other platforms are unverified. The development baseline passed 310 automated checks; the public subset intentionally uses synthetic fixtures and excludes private real-model files. See docs/TESTING.md for the independently reproducible public checks.

Latest Body case at the reference pose: 83 rooted contacts, zero unresolved selected contacts, all 14 detected low points covered, unified closed raft, zero non-manifold edges or degenerate faces and zero forbidden collision pairs. **68 heuristic underside review regions and two stem warnings remain.** The normal export gate correctly reports incomplete. Selected contacts being rooted does not prove complete surface coverage.

A prepared high-resolution Luca planning/mesh/audit comparison improved from 188 to 153 seconds in the preceding performance patch with identical graph and mesh signature. Import and optimization were excluded. Whole-model preparation can still take minutes; no universal speed guarantee.

## Assets and installation

- `INSTALL_IN_BLENDER_fdm_mini_tools_0.3.0_RC2_<commit>.zip`: install this in Blender.
- `SOURCE_DO_NOT_INSTALL_fdm_mini_tools_<commit>.zip`: matching source snapshot, not directly installable.
- `SHA256SUMS.txt`: SHA-256 checksums for both ZIPs.
- `release.json`: source commit and build metadata.

Back up your previous add-on ZIP before replacing it. Restart Blender after installation, then check the displayed commit. Report that SHA with feedback. No private models or printer profiles are distributed.

Known open issues: incomplete contact coverage; some difficult routes and Boolean cases; long-stem warnings; synchronous UI; experimental orientation, splitting, bridge assumptions and glue fit. Physical prints, slicer review and connector calibration remain required for confidence in a particular model.

Languages: English source and German translations follow Blender Preferences > Interface > Translation. Enable Interface and Tooltips for a German interface with German explanations. No saved property identifiers or support algorithms were changed for this fix.
