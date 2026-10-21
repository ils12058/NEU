# Milestone 003 verification

Date: 2026-10-21 (Asia/Manila).
Baseline: `6f515028f5fc4a2a7f381c7ebef3d1ce78e880c5` (NeuBoot v0.2.0).
Working branch: `feat/boot-volume-input`.
Application version: **0.3.0**.

## Environment

- Host: macOS 27.0.1, ARM64.
- Rust/Cargo: pinned 1.95.0; firmware target: `x86_64-unknown-uefi`.
- Rust unit-test target: `aarch64-apple-darwin`, detected from `rustc -vV`.
- Dependency: `uefi` 0.41.0 with only `panic_handler`. Dependency versions are
  unchanged; only NeuBoot's package version changes in `Cargo.lock`.
- Python: 3.14.7; runner/test source also parsed with Python 3.9 grammar.
- QEMU: 11.0.0, Q35, x86-64 TCG, one CPU, 128 MiB RAM, no guest network.
- Firmware: Homebrew QEMU's `edk2-x86_64-code.fd` / `edk2-i386-vars.fd` pair.
- Media: read-only VirtIO FAT directory plus a private writable firmware-variable
  copy; every VM directory lives temporarily under `target/neuboot/`.

## Implementation evidence

`get_image_file_system(image_handle())` associates filesystem access with the
executing image's loaded-image device context. The boot-volume module opens
exactly `\EFI\NEU\BOOT.INP` as read-only and checks that it is a regular file.
It does not enumerate filesystems or directory entries. Resource wrappers close
before the owned validation result reaches the entry point, on all return paths.

[ADR 0002](adr/0002-provisional-boot-input-contract.md) records the provisional
12-byte NEUI v1 format, 64-byte input cap, 65-byte stack reader, validation order,
and expected-rejection versus fatal-I/O policy. No project-written unsafe code,
global allocator, kernel loader, or third-party dependency was added. ADR 0001
and historical verification reports are preserved. Firmware discovery source is
unchanged from v0.2.

## Commands and checks executed

```sh
make build
make check
make smoke
```

| Check | Result |
| --- | --- |
| Release compilation and runner PE inspection | Passed |
| `file` / `objdump -p` | x86-64 PE32+ EFI application, subsystem 10, entry RVA `0x19f0` |
| Release metadata | PE timestamp zero; no PE debug directory |
| rustfmt and Clippy with warnings denied | Passed |
| Actual Rust parser/reader unit tests | 10 passed on the host target |
| Python fixture/console-validator tests | 16 passed |
| QEMU/OVMF runtime scenarios | All seven passed, as detailed below |
| Firmware discovery | Identity, internally consistent memory totals, and GOP handling passed in every VM |
| VM resources | No temporary `qemu-*` directories remained after the scenarios |
| Project safety lint | Existing `unsafe_code = "forbid"` retained; no project unsafe operations |

The host Rust tests execute the actual parser and reader: repository fixture,
every truncated v1 length, magic/length/kind errors, unsupported versions,
validation precedence, padding, the exact size boundary, short reads, an I/O
failure after a valid prefix, and an invalid callback read count. The Rust reader
tests use callback-supplied byte streams, not UEFI firmware I/O.

The Python tests exercise fixture preparation and the host-side smoke verifier:
firmware-independent values/version, existing GOP cases, memory consistency,
input rejection classes, wrong outcomes, success-after-rejection, missing
failed-start evidence, and firmware rejecting a claimed success. They are not
substitutes for the actual Rust or VM tests.

## Actual QEMU/OVMF results

All runs observed `Boot volume located`. Both successful runs observed
`Boot input validated: version 1, diagnostic fixture` and bootstrap completion.
All rejected runs withheld both success messages.

| VM scenario | Actual application result | Firmware observation | Log under `target/neuboot/` |
| --- | --- | --- | --- |
| Valid fixture, GOP required, invalid decoy volume attached first | Validated; `SUCCESS` path | Continued without failed-start report | `smoke-decoy.log` |
| Valid fixture, `-vga none` | Validated; GOP unavailable, nonfatal | Continued without failed-start report | `smoke-no-graphics.log` |
| Fixed fixture missing | `[REJECT]` file not found; `NOT_FOUND` | Failed start: `Not Found`, then continued | `smoke-missing.log` |
| Bad fixture magic | `[REJECT]` invalid contents; `COMPROMISED_DATA` | Failed start: `Compromised Data`, then continued | `smoke-malformed.log` |
| Version 2 in an otherwise valid envelope | `[REJECT]` unsupported version 2; `UNSUPPORTED` | Failed start: `Unsupported`, then continued | `smoke-unsupported.log` |
| 65-byte fixture | `[REJECT]` oversized; `BAD_BUFFER_SIZE` | Failed start: `Bad Buffer Size`, then continued | `smoke-oversized.log` |
| Directory at the fixed input path | `[REJECT]` invalid contents; `COMPROMISED_DATA` | Failed start: `Compromised Data`, then continued | `smoke-directory.log` |

The decoy volume contains malformed input at the same fixed path and is attached
before the actual boot disk, whose boot priority remains first. The valid result
with both volumes present exercises the image-associated lookup; no filesystem
handle enumeration was added for the test.

Firmware identity stayed `EDK II`, UEFI revision `2.7` through the crate formatter,
and raw firmware revision `0x00010000`. GOP-present runs reported 1280 x 800,
`Bgr`, 4,096,000 framebuffer bytes. The graphics-disabled run reported
`GOP: unavailable (protocol not found)` and still validated input successfully.
Memory-type totals equaled the snapshot total of 3,244,960 pages in all runs;
this includes reserved/MMIO ranges and is not usable-RAM capacity. Specific
firmware values and descriptor counts are observations, not fixed assertions.

Each negative log includes the expected rejection/status, the final boot-failure
return marker, an OVMF `BdsDxe: failed to start ...` report, and then a new firmware
loading/starting event. Thus the test harness's negative-scenario PASS means
**correct rejection**, not successful input validation or a successful boot.
Mere firmware continuation cannot pass these checks. Boot-entry numbers and
firmware target names are not pinned.

The 39,936-byte verified release image has SHA-256:

```text
3f4e822964554e04ac8b14557a9dca8237c6f4dffb3ae13735729998ce4a3f69
```

## Remaining limitations and tests not executed

- Actual unavailable-image-volume, media removal, firmware access denial, device
  corruption, and file-close failure were not injected under OVMF. Their error
  classification is implemented, but no runtime pass is claimed for those paths.
- The I/O-after-valid-prefix and short-read checks are real Rust tests with
  synthetic readers; they do not demonstrate faulty UEFI storage behavior.
- No physical hardware, Linux host, second firmware release, real `BltOnly`, or
  multi-display environment was tested. The existing exclusive-protocol-open
  driver-consumer caveat remains.
- Smoke return checks require OVMF serial console and `BdsDxe` traces. They check
  success/failure class and continuation, not an independent numeric decoding of
  the firmware return register.
- Rust ownership and the crate's Drop implementations close handles; firmware
  allocation/handle accounting was not independently instrumented. Host temporary
  VM cleanup was checked directly.
- No new clean-build/cross-host reproducibility comparison was made. Existing
  deterministic release linker settings and pinned toolchain remain unchanged.
- NEUI v1 is a provisional diagnostic-only format, without authentication or
  kernel configuration semantics. No executable parsing/loading, memory
  placement, `ExitBootServices`, handoff, graphics UI, or AI service is present.

No unresolved build or runtime failures remain in the verified scenarios.

## Changed files

| File | Change |
| --- | --- |
| `Cargo.toml`, `Cargo.lock` | NeuBoot v0.3.0; dependency versions unchanged |
| `boot/neuboot/Cargo.toml` | Restrict UEFI dependency activation to UEFI targets for host library tests |
| `boot/neuboot/src/main.rs` | Run required boot-input preflight and return explicit failure statuses |
| `boot/neuboot/src/lib.rs` | New `no_std` entry for firmware-independent contract code |
| `boot/neuboot/src/input.rs` | New bounded reader, binary validator, and actual Rust unit tests |
| `boot/neuboot/src/boot_volume.rs` | New loaded-image filesystem lookup, fixed-path read-only access, and error reporting |
| `boot/neuboot/fixtures/boot-input-v1.bin` | New dedicated 12-byte non-executable test fixture |
| `scripts/neuboot.py` | Fixture preparation, host Rust tests, expected boot outcomes, decoy volume, negative scenarios |
| `scripts/test_neuboot.py` | Extended fixture/console-verifier regression tests |
| `Makefile` | Integrate Rust tests and all seven VM scenarios |
| `README.md` | Current behavior, commands, provisional contract, and limits |
| `docs/adr/0002-provisional-boot-input-contract.md` | New provisional format and error-policy decision |
| `docs/verification-003.md` | This verification record |

Recommended next step: a separately reviewed kernel-artifact and boot-information
ownership contract before any loader implementation. Verification was performed
on local, uncommitted feature-branch changes; no merge or push was part of that
verification run.
