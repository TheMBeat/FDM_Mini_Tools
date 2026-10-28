# Publishing the prepared public repository

Use the separate clean repository. Do not push the internal development repository: its old history contains private models, profiles and generated files.

1. Create an empty GitHub repository, then add its URL as `origin` to the prepared repository.
2. Push the `main` branch. Review Actions → CI.
3. Build with `python tools/build_release.py --output-dir dist` from a clean committed checkout.
4. Optional local packaged UI verification: extract the installable ZIP to a temporary directory, then run Blender with `--factory-startup -b --python-exit-code 1 --python tests/blender_version_ui_smoke.py -- --addon-root /absolute/extracted/fdm_mini_tools --output reports/package_ui.json`.
5. After reviewing the build and tests, tag the exact tested commit `v0.3.0-rc.2` and push that tag. The release workflow prepares a **draft pre-release** with matching source, install ZIP, checksums and metadata. Review the draft before publishing.

```sh
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
git tag -a v0.3.0-rc.2 -m "0.3.0 RC2 experimental test build"
git push origin v0.3.0-rc.2
```

No remote, tag or GitHub release is created by the local preparation. Configure the repository's workflow permissions as needed for the draft release job. Test-model rights are not granted by the add-on license. A follow-up test build should use a new prerelease tag; never move a published tag.
