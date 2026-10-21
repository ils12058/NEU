# Milestone 002 verification

Date: 2026-10-21 (Asia/Manila).
Baseline: `bb8ae80` (NeuBoot v0.1.0).
Implementation branch: `feat/firmware-discovery`.
Application version: **0.2.0**.

## Environment

- Host: macOS 27.0.1, ARM64.
- Rust/Cargo: pinned 1.95.0; target: `x86_64-unknown-uefi`.
- Dependency: pinned `uefi` 0.41.0, with only `panic_handler` enabled. No new
  dependencies or dependency upgrades; the lockfile changes only NeuBoot's version.
- Python: 3.14.7. Both runner files also passed a Python 3.9 syntax parse.
- QEMU: 11.0.0, Q35, x86-64 TCG, one CPU, 128 MiB RAM, networking disabled.
- OVMF: Homebrew QEMU's `edk2-x86_64-code.fd` and `edk2-i386-vars.fd` pair.
  Firmware code was read-only; each VM used a private copy of the variable store.
- Boot media: temporary read-only VirtIO FAT directory containing
  `EFI/BOOT/BOOTX64.EFI`, with explicit boot priority.

## Implementation and ownership

The original identity, initialization, bootstrap completion, five-second pause,
and successful firmware return remain. A small discovery module reports firmware
identity, a memory-map snapshot, and optional GOP metadata between startup and
bootstrap completion. A final return marker helps distinguish application output
from subsequent firmware execution.

`boot::memory_map(MemoryType::LOADER_DATA)` supplies a crate-owned temporary
firmware-pool buffer. Descriptor borrows remain inside its scope, and the buffer
is dropped with boot services active. The overall page sum is checked for
overflow; per-type sums are bounded by that checked total. Repeated scans print
each distinct type in numeric order without allocating a histogram or assuming
a closed set of firmware/OEM types. There is no global Rust or kernel allocator,
no retained map key or descriptor pointer, and no kernel boot-information format.

GOP absence is informational. Lookup/open errors are warnings and do not fail
the bootstrap. The safe scoped exclusive protocol guard is dropped before
printing copied mode information. No mode-setting, blit, or framebuffer-memory
access occurs. `BltOnly` avoids the framebuffer accessor and reports its size as
unavailable. Project-written unsafe code remains forbidden.

These are routine observations within ADR 0001's firmware boundary; no new ADR
or kernel architecture decision was introduced.

## Executed checks

| Check | Observed result |
| --- | --- |
| `make build` | Release UEFI compilation and PE header validation passed |
| `file` and `objdump -p` | x86-64 PE32+ EFI application, subsystem 10, entry RVA `0x1970` |
| Release metadata | PE timestamp zero, no PE debug directory |
| `make check` | rustfmt, Clippy with warnings denied, and all 11 smoke-validator tests passed |
| `make smoke` / graphics present | Firmware identity, memory summary, GOP mode metadata, and firmware continuation verified |
| `make smoke` / `-vga none` | GOP reported missing; discovery, bootstrap completion, and firmware continuation still verified |
| Version expectation | Runtime banner matched the version read from `cargo metadata`; validator tests also used an unrelated version |
| Memory consistency | Per-type page counts summed to the total in both actual VM logs; IDs were unique and sorted |
| Resource cleanup | No `target/neuboot/qemu-*` temporary VM directories remained after either scenario |
| Python compatibility | Runner and validator-test source parsed with Python 3.9 grammar |
| Diff whitespace | `git diff --check` passed |

Commands:

```sh
make build
make check
make smoke

# Individual VM scenarios:
python3 scripts/neuboot.py smoke --require-gop
python3 scripts/neuboot.py smoke --no-graphics
```

`--require-gop` is a positive-test assertion for the configured VM, not an
application requirement. A direct `smoke` command without that flag accepts
optional GOP absence. The no-graphics scenario requires `NOT_FOUND` rather than
mistaking an unrelated protocol-open failure for successful absence handling.

The validator's synthetic tests cover alternate version/firmware values, missing
GOP, optional open failure, the positive GOP requirement, `BltOnly`, an unknown
memory-type ID, inconsistent page totals, duplicate types, incomplete discovery,
a return marker without firmware continuation, and a panic after success output.
These tests exercise the host-side validator; they do not simulate those firmware
conditions inside the Rust application.

## Actual observations

Both runs printed vendor `EDK II`, UEFI specification revision `2.7` using the
crate's revision formatter, and raw firmware revision `0x00010000`.

| Observation | Default VGA | VGA disabled |
| --- | --- | --- |
| Descriptor count | 100 | 97 |
| Total represented pages | 3,244,960 | 3,244,960 |
| Distinct memory types | 11 | 11 |
| GOP | Available | Unavailable: protocol not found |
| Current resolution | 1280 x 800 | Not queried |
| Pixel format | `Bgr` | Not queried |
| Framebuffer size | 4,096,000 bytes | Not queried |
| Bootstrap and discovery completion | Observed | Observed |
| Firmware resumed after return marker | Observed | Observed |

Memory-type page counts in the recorded snapshots:

| Type | Default VGA | VGA disabled |
| --- | --- | --- |
| 0 `RESERVED` | 3,211,396 | 3,211,396 |
| 1 `LOADER_CODE` | 13 | 13 |
| 2 `LOADER_DATA` | 2 | 2 |
| 3 `BOOT_SERVICES_CODE` | 938 | 938 |
| 4 `BOOT_SERVICES_DATA` | 9,849 | 9,810 |
| 5 `RUNTIME_SERVICES_CODE` | 256 | 256 |
| 6 `RUNTIME_SERVICES_DATA` | 581 | 581 |
| 7 `CONVENTIONAL` | 20,369 | 20,408 |
| 9 `ACPI_RECLAIM` | 18 | 18 |
| 10 `ACPI_NON_VOLATILE` | 514 | 514 |
| 11 `MMIO` | 1,024 | 1,024 |

The total includes reserved and MMIO address ranges, so it is not the VM's RAM
capacity. Counts are observations, not stable test expectations.

In each raw log, `[OK] Returning to firmware` was followed by OVMF's `BdsDxe`
loading/starting its firmware UI. The smoke harness checks continuation without
pinning a boot-entry number or target name. It then terminates QEMU and removes
the private VM directory. The logs remain under `target/neuboot/smoke.log` and
`target/neuboot/smoke-no-graphics.log` until `make clean`.

The verified release image is 35,328 bytes, SHA-256:

```text
bbadda1777da732ebf2a3b96e29265f36b192c1a33328b0ecd341cd83c690141
```

## Limitations and unexecuted cases

- No physical hardware, Linux host, other firmware release, or multi-display
  configuration was tested.
- Real `BltOnly`, missing-vendor, custom memory-type, memory-map overflow/OOM,
  and GOP lookup/open-failure firmware paths were not fault-injected. The
  validator-only cases above are not evidence of executing those Rust branches.
- The documented safe exclusive GOP open can cause firmware to disconnect an
  existing `ByDriver` consumer. The guard closes automatically; reconnection is
  firmware behavior, not guaranteed by this prototype. No such failure was
  observed in the tested OVMF configuration.
- Snapshots can become outdated immediately after acquisition. They are
  diagnostic observations, not allocation authority or a handoff memory map.
- The return check depends on serial console and OVMF `BdsDxe` traces. It observes
  resumed firmware, not the numeric return status. Correct execution on firmware
  without those traces would require a different return check.
- No new cross-host or clean-build reproducibility comparison was performed for
  milestone 002. The pinned toolchain, lockfile policy, and deterministic release
  linker configuration remain unchanged.
- No kernel loading, handoff, `ExitBootServices`, kernel memory management,
  interrupt handling, scheduling, Secure Boot verification, graphics UI, or AI
  service was implemented.

No unresolved build or runtime failures remain in the tested configuration.

## Files changed

| File | Change |
| --- | --- |
| `Cargo.toml`, `Cargo.lock` | NeuBoot version 0.2.0; dependency versions unchanged |
| `boot/neuboot/src/main.rs` | Invoke discovery, propagate required errors, announce return |
| `boot/neuboot/src/discovery.rs` | New firmware identity, memory-map summary, and optional GOP inspection |
| `scripts/neuboot.py` | Cargo-derived version, discovery validation, firmware-continuation checks, graphics-disabled scenario |
| `scripts/test_neuboot.py` | New validator regression tests |
| `Makefile` | Wire validator tests and both VM scenarios into existing commands |
| `README.md` | Current behavior, commands, ownership, optional capabilities, and limits |
| `docs/verification-002.md` | This record |

Recommended next milestone: read-only boot-volume inspection and an explicit
boot-input/error-handling contract. Kernel loading needs separate authorization.
