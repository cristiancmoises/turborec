# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it
**privately** so it can be addressed before public disclosure.

- **Preferred:** open a private
  [GitHub Security Advisory](../../security/advisories/new) for this repository.
- Please do **not** open a public issue for security-sensitive reports.

When reporting, please include:

- a description of the issue and its potential impact,
- steps to reproduce or a proof of concept, and
- any relevant logs, output, or environment details.

We aim to acknowledge valid reports promptly and will keep you informed as a
fix is developed.

## Supported Versions

This project is maintained on a best-effort basis. Security fixes target the
latest commit on the default branch; there are no long-term support branches.

## Recording and Privacy

Run the recorder and Windows setup as your ordinary user, not root or an
administrator. Current Windows setup is per-user; old machine-wide installations
must be removed separately through the operating system's normal uninstall UI.

Choose a recording directory that other users cannot modify. New POSIX
recording folders are private (`0700`), and the CLI uses umask `0077` for new
files. Existing user data is not chmodded. FFmpeg's no-overwrite option is a
collision safeguard, not atomic destination binding; external recorder and OS
path policies still matter for a hostile shared folder.

The app masks supplied stream keys before quoting command previews. Streaming
credentials nevertheless appear in the child FFmpeg argv and may be visible
to other users on a shared host or in shell history. Review diagnostic logs
before sharing: device names, window titles, paths and recordings can be private.

Since version 3.10.2 the app bounds retained child-process diagnostics and presents redacted
recording failures in the GUI. Review errors before sharing them anyway. A
failed final mux preserves intermediate recordings for recovery; those files
may contain the same private content as the intended output. Synthetic encoder
startup validation is not a security audit or certification of physical capture
on every GPU/operating system. Driver installation and reboots remain operator
decisions, not automatic recorder actions.

Version 3.10.4 validates GPU availability against the selected encoder profile.
For a custom Wayland backend, both configured executable paths must be absolute;
use only trusted binaries with compatible shared libraries. Path validation is
not signature verification or proof of ABI compatibility. The SecurityOPS Guix
NVIDIA variant pins the matching backend without changing global library paths.

Download releases from the project's official forges and compare `SHA256SUMS`
before installing or extracting. Checksums detect changed bytes; they are not
a digital signature or proof that an external dependency is uncompromised.
When building or publishing, keep the checkout, build/cache, `dist` and release
asset directories private. Do not publish from a directory another user can
replace files in. Keep the verified checksum manifest and recheck payloads when
moving them between build and publication environments.
See the [PT-BR privacy guidance](docs/README.pt-BR.md#gravação-segura-e-privacidade).

Security reviews and functional tests are complementary, not a guarantee of
exhaustive security or physical-device support on every machine.

## Responsible Use

This repository may contain system administration or security tooling intended
for **authorized, lawful use only** — on systems you own or have explicit
written permission to operate on. You are responsible for complying with all
applicable laws and policies. The maintainers accept no liability for misuse or
for any damage resulting from use of this software.
