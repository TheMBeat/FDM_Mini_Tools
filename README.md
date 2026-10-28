# FDM Mini Tools

Experimental Blender add-on for preparing FDM miniatures: model cleanup, orientation, SLASG Classic supports and Tree supports with short SLA-style tips.

**0.3.0 RC2 — public test build.** Tested locally with Blender **5.2.1 LTS on Windows**, primarily for a 0.2 mm nozzle. Other systems and physical print quality are unverified. Tree supports can still leave uncovered regions or fail mesh validation. Keep the original model and review every result in your slicer.

## Language / Sprache

English and German are included, with explanatory tooltips. Select the language in Blender Preferences → Interface → Translation. For German, choose Deutsch and enable **Interface** and **Tooltips**. Disable Interface translation to keep English labels; tooltip translation can be toggled separately. Saved settings do not change when switching languages.

Englisch und Deutsch sind enthalten. Unter Blender-Einstellungen → Oberflaeche → Uebersetzung **Deutsch**, **Oberflaeche** und **Tooltips** aktivieren.

## Install

Download the **INSTALL_IN_BLENDER** asset from [Releases](https://github.com/TheMBeat/FDM_Mini_Tools/releases). Do not install GitHub **Code → Download ZIP**, a **SOURCE_DO_NOT_INSTALL** archive, or the outer Actions artifact ZIP. Never add, rename or nest folders manually.

The installer must contain `fdm_mini_tools/__init__.py` directly inside one top-level `fdm_mini_tools/` folder. No version folder surrounds it.

1. Download the **`INSTALL_IN_BLENDER_fdm_mini_tools_0.3.0_RC2_<commit>.zip`** release asset. GitHub's automatic source ZIP is not the installable add-on.
2. In Blender: Preferences → Add-ons → menu → Install from Disk; select that ZIP and enable **FDM Mini Tools**.
3. Open the 3D View sidebar with `N`, then **FDM Mini**. Restart Blender when replacing an installed version.
4. Check the displayed commit SHA when reporting results. The bundled SLASG library needs no separate installation.

## Test workflow

Follow the five panels: **Model → Profile → Calculate → Review → Export**. Start with a small model you are allowed to use, the Balanced preset and Simple settings. Classic is the default strategy. Tree is experimental; its default contact backend is SLASG. The optional Python sampler has not demonstrated parity.

Review missing-contact, low-point and stem warnings. A successful calculation does not prove printability. Normal export remains blocked for incomplete results. Do not treat an explicitly incomplete preview as a print recommendation.

## Current limits

- Uncovered regions, unresolved routes and long-stem warnings remain possible.
- Boolean mesh construction can fail safely; the latest patch repairs a narrowly bounded near-duplicate cap case.
- Large models can take minutes and block Blender's interface during calculation.
- Orientation, splitting, connectors and printer bridge values are experimental; actual fit and print quality need physical testing.
- The Body reference case has 83 rooted tips, all 14 detected low points covered and a closed raft, but still 68 heuristic review regions and two stem warnings. This is not a stable release.

See [release notes](docs/RELEASE_NOTES.md), [testing](docs/TESTING.md) and [contributing](CONTRIBUTING.md). Report bugs with Blender version, displayed commit, settings, phase/time, screenshots and a shareable reproducer. Do not upload purchased models without permission.

## Development

Python 3.11+ and NumPy are required for offline tests; Blender supplies its own Python/NumPy for Blender tests.

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py" -v
python tests/run_public_validation.py --blender /path/to/blender
python tools/build_release.py --output-dir dist
```

Build from a clean committed checkout. Release packages embed the real source commit and file checksums. The public repository deliberately excludes private models, printer profiles, development logs and historical install packages.

## License

Add-on code: **GPL-3.0-or-later**; see [LICENSE](LICENSE). Bundled SLASG by morokko-at-gh: **MIT**; see [third-party notices](THIRD_PARTY_NOTICES.md). No test-model redistribution rights are implied.
