# Third-party notices

`vendor/pi-0.85.1/` contains an unmodified frozen installation of `@earendil-works/pi-coding-agent` version 0.85.1 and its dependency tree. The package identifies its license as MIT and its upstream repository as https://github.com/earendil-works/pi (packages/coding-agent).

Dependency license files, package metadata, notices and shrinkwrap are retained in that directory. Each dependency remains subject to its own license; the root MIT license applies to Hourglass Bench's first-party code only.

`harness/pi-lock.json` records SHA-256 digests for the vendored files. `harness_runner.verify_frozen()` validates them before model execution. No globally installed agent package is modified.

The exact upstream v0.85.1 root MIT license is reproduced in [licenses/pi-MIT.txt](licenses/pi-MIT.txt).
