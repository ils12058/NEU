# Neu

Neu is an experimental AI-first operating system project. Its long-term goals
include AI-native interaction, agents as system participants, and AI-aware resource
management. The privileged kernel must remain independent of AI inference and
enforce predictable execution, memory isolation, and resource access.

This repository currently implements **NeuBoot v0.1.0 only**: a small Rust UEFI
application that initializes UEFI support, prints diagnostics to the firmware's
text console, pauses for five seconds, and returns `Status::SUCCESS` to firmware.

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
make check       # Rust formatting and Clippy
```

Without Make:

```sh
rustup target add x86_64-unknown-uefi
python3 scripts/neuboot.py build
cargo fmt --all -- --check
cargo clippy --locked --package neuboot -- -D warnings
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
make smoke       # Headless boot; verify all five expected console lines in order

# Direct equivalents / options
python3 scripts/neuboot.py run
python3 scripts/neuboot.py run --headless
python3 scripts/neuboot.py smoke --timeout 60
```

Expected application output:

```text
NEU
NeuBoot v0.1.0

[OK] UEFI environment initialized
[OK] NeuBoot execution started
[OK] Bootstrap milestone completed
```

The runner builds the application and copies it to `EFI/BOOT/BOOTX64.EFI` in a
fresh temporary directory under `target/neuboot/`. QEMU exposes that directory as
a **read-only virtual FAT disk** on VirtIO with explicit boot priority, and uses
a private writable copy of the OVMF variable-store template. Firmware code is
opened read-only. Temporary VM files
are removed when the runner exits. No host boot settings, physical disks, or host
EFI partitions are used.

After five seconds NeuBoot returns to OVMF; QEMU itself remains running. Close its
window or press **Ctrl-a, then x** in the launching terminal to exit. The smoke
command captures the actual firmware console through OVMF's serial console,
allows six seconds after observing the expected output for the application's
pause and return, then stops QEMU. It saves `target/neuboot/smoke.log`. This verifies
console output; it does not independently inspect the returned firmware status.
The smoke check requires an OVMF build that routes its text console to serial.

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

The first milestone provides firmware initialization and console diagnostics.
There is no kernel image, ELF loader, kernel handoff, `ExitBootServices`, custom
allocator, virtual memory, interrupt handling, scheduler, Secure Boot support,
recovery system, AI execution, or desktop interface. No physical-hardware boot
has been validated. Future `kernel/` and `shared/` directories are deferred until
they contain real implementation.

Validation results and their limits are recorded in
[milestone 001 verification](docs/verification-001.md).

See [ADR 0001](docs/adr/0001-rust-uefi-bootstrap.md) for the initial decision and
the official API references used. A proposed next milestone is a read-only
firmware inventory (firmware identity, console capabilities, and protocol
availability) with reproducible VM checks. Kernel loading requires a separate
instruction.
