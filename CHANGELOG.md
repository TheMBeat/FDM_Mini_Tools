# Changelog

## 0.3.0 RC2 — language and installation fix

- English/German interface and explanatory tooltips using Blender language settings.
- Clearly named INSTALL_IN_BLENDER and SOURCE_DO_NOT_INSTALL assets.
- Archive structure validation and actual installation checks in an isolated Blender profile.
- Saved property identifiers and support safety gates preserved.

## 0.3.0 RC2 — experimental public test build

- Five-step workflow and Simple / Advanced / Expert settings.
- Verified commit identity in packaged builds.
- SLASG Classic fallback and default SLASG contact acquisition for experimental Tree supports.
- Short contact cones/necks, rounded junctions, unified raft and mesh/collision/export gates.
- Bounded recovery for low points and uncovered underside patches; branch reuse and stem stabilization.
- Faster layer analysis, geometry reuse and early BVH ray rejection, retaining finite-radius checks.
- Transactional repair of near-duplicate Boolean-cap endpoints, with a strict 0.000002 mm displacement bound.
- Experimental orientation, splitting, flat glue faces by default and optional hemispherical connectors.

Known limitations and measured cases: docs/RELEASE_NOTES.md. No stable or physical-print certification.
