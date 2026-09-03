# Packaged defaults

Reference data that ships inside the plugin. The runtime looks for each file at the plugin root first and under
`defaults/` second — Decky-packaged installs carried these flattened into the root — so they keep their bare names; do
not move or rename them.

## `config.json` — in-tree default

The platform-slug map and other default configuration. It is maintained in this repo (not vendored) and carries no
checksum gate.

## What used to live here

`bios_registry.json` — a frozen snapshot of which firmware files each platform and libretro core wanted — was vendored
here from an [emu-atlas](https://github.com/danielcopper/emu-atlas) release and read at runtime by `FirmwareService`. It
is gone: the file no longer exists upstream, so the snapshot could never be refreshed again and drifted a little further
with every RetroDECK update. Firmware requirements are now read live off the installed cores through the vendored
resolver (`backend/_vendor/atlas/`, provenance in [`_vendor/README.md`](../backend/_vendor/README.md)), which is data no
snapshot has to keep in step.

A plugin-owned `xbox_bios_registry.json` was carried here for a while, hand-maintained for `xemu` (a standalone
emulator, entirely out of scope for the libretro-derived generator that used to produce `bios_registry.json`). It is
gone too: the vendored resolver's own `standalone_firmware.json` (`backend/_vendor/atlas/data/`) now carries Xbox's MCPX
boot ROM, flash BIOS and hard-disk-image requirements natively — reverse-engineered against xemu's own source with
citations, which our hand-maintained hash list never was — so Xbox is answered through the exact same live-resolution
path every other platform (including every other standalone emulator) already uses, with no Xbox-specific code
anywhere in this plugin.
