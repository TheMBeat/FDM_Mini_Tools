# Contributing

Use a branch and open a pull request with the problem, resulting behavior and validation. Keep changes small. Preserve Classic target binding, the default SLASG contact backend, continuous finite-radius collision checks, rooted paths, mesh/raft checks and incomplete-export gates.

Run the offline tests and available Blender tests listed in docs/TESTING.md. Compare contact coverage, rooted/unresolved tips, low points, collisions and topology on at least two different geometries for support changes. Never tailor production logic to a model name or fixed contact coordinates. Performance comparisons need identical model, orientation, settings and distance.

Report the displayed commit SHA, Blender/OS, preset and changed settings, expected/actual behavior, last phase, elapsed time and a minimal reproducer. Include logs only after checking for personal paths or identifiers. Use models you may share; do not attach purchased or restricted STLs. A source checkout without generated _build.json will correctly show an unverified development build.

Physical print validation is required before claiming stable or equivalent print quality.
