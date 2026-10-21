# Milestone 001 verification

Date: 2026-10-21 (Asia/Manila).

## Environment

- Host: macOS 27.0.1, ARM64.
- Rust/Cargo: 1.95.0; target: `x86_64-unknown-uefi`.
- `uefi`: 0.41.0, with exact transitive versions in `Cargo.lock`.
- Python: 3.14.7.
- QEMU: 11.0.0, x86-64 TCG, Q35, one CPU, 128 MiB RAM.
- Firmware: QEMU's `edk2-x86_64-code.fd` and `edk2-i386-vars.fd` pair,
  detected from the Homebrew QEMU installation. Only a temporary copy of the
  variable store was writable.

## Results

| Check | Result |
| --- | --- |
| `make setup` | UEFI target installed for the pinned toolchain |
| `make build` | Release compilation and PE/COFF header checks passed |
| `file` / `objdump -p` | x86-64 PE32+, EFI application subsystem 10, entry RVA `0x1000` |
| Release metadata | PE timestamp zero; no PE debug directory |
| `make check` | rustfmt and Clippy with warnings denied passed |
| `make smoke` | OVMF booted `EFI/BOOT/BOOTX64.EFI`; all five expected lines observed in order |
| Firmware continuation | OVMF continued to its firmware UI after the application output |
| Two clean release builds | Byte-identical executables at the same checkout path on this host |
| `make clean` | Removed the local `target/` directory, including saved VM artifacts |
| Runner error handling | Invalid timeout, missing QEMU, and incomplete firmware override rejected with actionable messages |
| Temporary VM cleanup | No temporary QEMU directories left after completion |

The 12,288-byte release executable from both clean builds has SHA-256:

```text
9e26dd379797ee8d79a0a0d55e807295dd63be8cee8dfae459417e2b8a771d4e
```

Clean-build comparison procedure: run `make clean` followed by `make build`,
record the executable's SHA-256, then repeat from clean and compare. After that
comparison, run `make check` and `make smoke` against the final implementation.

Actual application console output captured through OVMF's serial text console:

```text
NEU
NeuBoot v0.1.0

[OK] UEFI environment initialized
[OK] NeuBoot execution started
[OK] Bootstrap milestone completed
```

The raw boot log is generated at `target/neuboot/smoke.log`; `make clean` removes
it. After the last application line, the log records OVMF starting `UiApp`,
confirming firmware resumed. The smoke runner stops QEMU itself after allowing
six seconds for NeuBoot's five-second pause and return.

## Resolved issues

- QEMU's default disk attachment rejected read-only virtual FAT media. The
  runner now attaches it through VirtIO, which supports a read-only block device.
- The supplied OVMF variable template preferred its internal shell. An explicit
  `bootindex=1` selects the NeuBoot disk and its fallback executable.
- Initial clean builds varied in the PE timestamp and embedded PDB identifier.
  The target configuration now zeros the timestamp, and a small build script
  disables release PDB generation. Debug builds retain PDB support.

No build or runtime failures remain in the verified configuration.

## Limits

Linux hosts, other firmware versions, physical hardware, and reproducibility
across different checkout paths or hosts were not tested. The automatic smoke
check requires firmware serial-console routing. The application returns
`Status::SUCCESS` in source; the harness observes resumed firmware but does not
independently read the returned status value. No kernel or other Neu subsystem
was implemented.

## Created files

| File | Purpose |
| --- | --- |
| `Cargo.toml` | Cargo workspace, shared version/dependency/lint settings, panic policy |
| `Cargo.lock` | Exact dependency versions and checksums |
| `rust-toolchain.toml` | Pinned compiler, rustfmt, Clippy, and UEFI target |
| `.cargo/config.toml` | Default UEFI target and deterministic PE timestamp |
| `.gitignore` | Generated artifacts and local cache exclusions |
| `boot/neuboot/Cargo.toml` | NeuBoot binary crate with no host test harness |
| `boot/neuboot/build.rs` | Disable variable PDB metadata in release images |
| `boot/neuboot/src/main.rs` | UEFI initialization, identity, diagnostics, and successful return |
| `scripts/neuboot.py` | Build/PE checks, firmware discovery, isolated QEMU runs, smoke verification |
| `Makefile` | Setup, build, check, run, smoke, and clean commands |
| `README.md` | Project overview, dependencies, usage, status, and limitations |
| `docs/adr/0001-rust-uefi-bootstrap.md` | Initial bootloader decision, tradeoffs, and official sources |
| `docs/verification-001.md` | This verification record |

The previously empty directory was initialized as a local Git repository on
`main`. No pre-existing project files needed modification. Future `kernel/` and
`shared/` directories were deferred.
