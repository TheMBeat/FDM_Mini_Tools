# FDM Mini Tools 0.3.0 RC1

Experimental test build for Blender 5.2.1 LTS on Windows. No stable/physical-print certification.

Install the complete installable ZIP through Blender Preferences → Add-ons → Install from Disk; enable FDM Mini Tools, then open the N sidebar → FDM Mini. Restart after updates. The displayed commit SHA identifies this exact packaged source.

Follow Model → Profile → Calculate → Review → Export. Classic is the default strategy. Tree uses SLASG contacts by default; the Python sampler, orientation and splitting remain experimental. The SLASG library is bundled; no external path is needed.

Inspect contact, low-point and stem warnings and review slicer layers. Incomplete results remain blocked by normal export. Some models can leave uncovered regions or fail mesh generation. Large meshes can take minutes and block Blender during calculation. Keep originals and previous packages for rollback.

Source, release notes, issue reporting and checksums are supplied with the accompanying public source/release assets. Include the commit SHA, Blender/OS, settings, phase/time and a permitted minimal reproducer in bug reports.

Add-on: GPL-3.0-or-later (LICENSE). Bundled SLASG: MIT (resources/THIRD_PARTY_SLASG.txt). No rights to redistribute third-party test models are included.
