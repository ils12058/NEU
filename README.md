# Neu

Neu is an experimental AI-first operating system project. Its long-term goals
include AI-native interaction, agents as system participants, and AI-aware resource
management. The privileged kernel must remain independent of AI inference and
enforce predictable execution, memory isolation, and resource access.

This repository currently implements **NeuBoot v0.2.0 only**: a small Rust UEFI
application that initializes UEFI support, reports firmware identity, summarizes
a memory-map snapshot, and inspects optional graphics capabilities. It uses the
firmware's text console, pauses for five seconds, and returns `Status::SUCCESS`
to firmware. Kernel loading remains outside the current milestone.

## Firmware discovery

| Observation | Reported information |
| --- | --- |
| Firmware identity | Vendor, UEFI specification revision, raw vendor-defined firmware revision |
| Memory-map snapshot | Descriptor count, total 4 KiB pages, page counts for each distinct memory type |
| Optional GOP | Availability, current resolution, pixel format, framebuffer size in bytes |

Memory-map acquisition is required; a firmware error returns an error status
instead of reporting successful discovery. The crate owns one temporary
`LOADER_DATA` pool buffer and releases it while boot services remain active.
Descriptor references stay within that lifetime. The type summary uses no
additional heap storage, includes unknown/OEM types by numeric ID, checks the
total for overflow, and prints types in numeric order. It does not dump addresses
or individual descriptors. These are snapshot totals across **all** memory
types, including reserved and MMIO ranges; they are not a measure of usable RAM.

GOP is optional: absence is informational, and lookup/open failures are warnings
that allow the bootstrap to complete. The first GOP handle found is inspected;
multi-display selection is deferred. NeuBoot reads the current mode without
setting a mode or reading/writing framebuffer contents. `BltOnly` modes report
direct framebuffer size as unavailable and skip the crate's framebuffer accessor.

The safe GOP API opens the protocol exclusively and closes it before printing
copied mode metadata. As documented by `uefi`, an exclusive open may disconnect
existing `ByDriver` consumers on other firmware. This prototype uses that scoped
safe API rather than introducing an unsafe, untracked protocol reference. No
project-written unsafe code, Rust global allocator, or kernel allocator is added.

## Stack and dependencies

- Rust **1.95.0**, pinned in `rust-toolchain.toml`, with Cargo, rustfmt, and Clippy.
- Rust target: `x86_64-unknown-uefi` (the cross-linker is bundled with Rust).
- [`uefi` 0.41.0](https://docs.rs/uefi/0.41.0/uefi/), with dependency versions
  recorded in `Cargo.lock`; only its `panic_handler` feature is enabled.
- Python **3.9+** for the standard-library-only build and VM runner.
- QEMU (`qemu-system-x86_64`) and **x86-64 OVMF/EDK II** firmware for execution.
- Make is optional; each command also has a direct equivalent below.

Supported development hosts are macOS and Linux. Install Rust through
[`rustup`](https://rustup.rs/). For the emulator:

```sh
# macOS / Homebrew (QEMU includes EDK II firmware)
brew install qemu

# Debian / Ubuntu
sudo apt install qemu-system-x86 ovmf python3 make
```

The runner detects firmware relative to the installed QEMU executable and in
common Linux package locations. It uses software emulation (TCG), including on
Apple Silicon, with one x86-64 CPU, 128 MiB RAM, and networking disabled.

## Build

```sh
make setup       # Install the pinned toolchain, components, and UEFI target
make build       # Build release image and check its PE/COFF headers
make check       # Rust formatting, Clippy, and smoke-validator regression tests
```

Without Make:

```sh
rustup target add x86_64-unknown-uefi
python3 scripts/neuboot.py build
cargo fmt --all -- --check
cargo clippy --locked --package neuboot -- -D warnings
python3 -m unittest discover -s scripts -p 'test_*.py'
```

The underlying Cargo build command is:

```sh
cargo build --locked --release --package neuboot --target x86_64-unknown-uefi --target-dir target
```

Output: `target/x86_64-unknown-uefi/release/neuboot.efi`, a PE32+ x86-64 EFI
application. The build script checks the machine, PE32+ format, EFI application
subsystem, and nonzero entry point. Dependencies are locked, the compiler is
pinned, release PDB generation is disabled, and the linker sets the PE timestamp
to zero. Debug builds retain their normal debugging information. Reproducibility
across different host paths or platforms still requires separate verification.

## Run and verify

```sh
make run         # Open QEMU and boot NeuBoot
make smoke       # Verify discovery and firmware return, with and without GOP

# Direct equivalents / options
python3 scripts/neuboot.py run
python3 scripts/neuboot.py run --headless
python3 scripts/neuboot.py smoke --timeout 60
python3 scripts/neuboot.py smoke --require-gop
python3 scripts/neuboot.py smoke --no-graphics
```

Application output structure (values depend on firmware; type rows abbreviated):

```text
NEU
NeuBoot v0.2.0

[OK] UEFI environment initialized
[OK] NeuBoot execution started
[INFO] Firmware vendor: <vendor or unavailable>
[INFO] UEFI specification revision: <revision>
[INFO] Firmware revision: <raw hexadecimal revision>
[INFO] Memory map: <count> descriptors, <count> pages (4 KiB each)
[INFO] Memory type <id> (<name>): <count> pages
...
[INFO] GOP: available
[INFO] GOP resolution: <width>x<height>
[INFO] GOP pixel format: <format>
[INFO] GOP framebuffer size: <bytes> bytes
[OK] Firmware discovery completed
[OK] Bootstrap milestone completed
[OK] Returning to firmware
```

Without GOP, the graphics fields are replaced by
`[INFO] GOP: unavailable (protocol not found)`. The completion and return messages
still appear.

The runner builds the application and copies it to `EFI/BOOT/BOOTX64.EFI` in a
fresh temporary directory under `target/neuboot/`. QEMU exposes that directory as
a **read-only virtual FAT disk** on VirtIO with explicit boot priority, and uses
a private writable copy of the OVMF variable-store template. Firmware code is
opened read-only. Temporary VM files are removed when the runner exits. No host
boot settings, physical disks, or host EFI partitions are used.

After five seconds NeuBoot returns to OVMF; QEMU itself remains running. Close its
window or press **Ctrl-a, then x** in the launching terminal to exit. The smoke
command captures the actual firmware console through OVMF's serial console and
checks identity fields, internally consistent memory totals, and available GOP
metadata. It reads the expected NeuBoot version through `cargo metadata` instead
of hardcoding it. It then requires an OVMF boot-manager continuation after
NeuBoot's final return marker and stops QEMU. Boot-entry IDs, firmware versions,
memory counts, resolution, and framebuffer size are not pinned by assertions.

`make smoke` runs a GOP-present scenario and a second VM with `-vga none` that
requires the expected missing-protocol result. Logs are saved as
`target/neuboot/smoke.log` and `target/neuboot/smoke-no-graphics.log`. A direct
`smoke` command accepts optional GOP absence unless `--require-gop` is given.
`run --no-graphics` is also available and implies headless operation.

The smoke harness requires an OVMF build with serial text-console output and
`BdsDxe` boot-manager traces. It verifies resumed firmware, not the numeric value
of the returned status. Other firmware logging layouts may need an adapted
continuation check even if the application executes correctly.

If firmware detection fails, provide a matching non-Secure-Boot x86-64 pair:

```sh
OVMF_CODE=/path/to/OVMF_CODE.fd OVMF_VARS=/path/to/OVMF_VARS.fd make run
```

Set `QEMU` to another `qemu-system-x86_64` executable if needed. The script does
not install emulator packages automatically. For a slow host, increase the smoke
timeout. If serial console output is unavailable, use `make run` to inspect the
graphical firmware console instead.

## Clean

```sh
make clean
# or: cargo clean --target-dir target
```

This removes build outputs and saved VM logs under `target/`.

## Status and limits

Milestones 001 and 002 provide firmware initialization and read-only discovery.
There is no kernel image, ELF loader, kernel handoff, `ExitBootServices`, custom
kernel allocator, virtual memory, interrupt handling, scheduler, Secure Boot support,
recovery system, AI execution, or desktop interface. No physical-hardware boot
has been validated. Future `kernel/` and `shared/` directories are deferred until
they contain real implementation.

Validation results and their limits are recorded in
[milestone 001 verification](docs/verification-001.md) and
[milestone 002 verification](docs/verification-002.md).

See [ADR 0001](docs/adr/0001-rust-uefi-bootstrap.md) for the initial decision and
the official API references used. Discovery uses the pinned crate's documented
[`system`](https://docs.rs/uefi/0.41.0/uefi/system/index.html),
[`memory_map`](https://docs.rs/uefi/0.41.0/uefi/boot/fn.memory_map.html), and
[`GraphicsOutput`](https://docs.rs/uefi/0.41.0/uefi/proto/console/gop/struct.GraphicsOutput.html)
APIs, including the documented behavior of
[`open_protocol_exclusive`](https://docs.rs/uefi/0.41.0/uefi/boot/fn.open_protocol_exclusive.html).
These observations do not define or retain a kernel handoff structure, so no
additional architecture decision is needed for this milestone.

A proposed next milestone is a read-only check of the boot volume and an
explicit boot-input/error-handling contract, still without executing a kernel.
Kernel loading requires a separate instruction.
