# Neu

Neu is an experimental AI-first operating system project. Its long-term goals
include AI-native interaction, agents as system participants, and AI-aware resource
management. The privileged kernel must remain independent of AI inference and
enforce predictable execution, memory isolation, and resource access.

This repository currently implements **NeuBoot v0.3.0 only**: a small Rust UEFI
application that initializes UEFI support, reports firmware identity, summarizes
a memory-map snapshot, and inspects optional graphics capabilities. It uses the
firmware's text console, finds its own boot volume, and validates a bounded test
input. On success it pauses for five seconds and returns `Status::SUCCESS` to
firmware. Kernel loading remains outside the current milestone.

## Boot volume and provisional input

NeuBoot resolves the filesystem associated with its own `LoadedImage` through
`boot::get_image_file_system(boot::image_handle())`. It never chooses a first
available filesystem, enumerates directory entries, or accepts an input path.
It opens only **`\EFI\NEU\BOOT.INP`**, with `FileMode::Read`. File/root handles and
scoped protocol guards close on success and on errors.

The dedicated fixture is `boot/neuboot/fixtures/boot-input-v1.bin`. It is a
12-byte little-endian record: `NEUI` magic, `u16` version 1, `u16` total length 12,
and a required `u32` diagnostic-fixture kind 1. A 64-byte maximum applies before
parsing; a 65-byte stack buffer reads at most one extra byte to detect oversize.
The reader handles partial reads and requires EOF before validation. Extra
bytes, bad magic/length, unsupported versions, and invalid kinds are rejected.
There is no kernel filename or executable data in this provisional format.

| Condition | Application outcome / returned UEFI status |
| --- | --- |
| Valid v1 fixture | Validation and bootstrap success / `SUCCESS` |
| Boot volume unavailable | Expected rejection / original `NOT_FOUND`, `UNSUPPORTED`, or `NO_MEDIA` |
| Input missing | Expected rejection / `NOT_FOUND` |
| Malformed input or directory in place of a file | Expected rejection / `COMPROMISED_DATA` |
| Unsupported version in a valid envelope | Expected rejection / `UNSUPPORTED` |
| Input larger than 64 bytes | Expected rejection / `BAD_BUFFER_SIZE` |
| Unexpected firmware I/O failure | Fatal boot attempt / original error status |

Rejections use `[REJECT]`; unexpected firmware failures use `[ERROR]`. Both
withhold validation/bootstrap success, pause briefly, and return an error to
firmware. An expected rejection is not a successful boot. See
[ADR 0002](docs/adr/0002-provisional-boot-input-contract.md) for the exact format,
validation precedence, error policy, and provisional compatibility limits.

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
make check       # Rust formatting, Clippy, Rust input tests, and smoke-validator tests
```

Without Make:

```sh
rustup target add x86_64-unknown-uefi
python3 scripts/neuboot.py build
cargo fmt --all -- --check
cargo clippy --locked --package neuboot -- -D warnings
python3 scripts/neuboot.py test
python3 -m unittest discover -s scripts -p 'test_*.py'
```

The small `no_std` input library runs its Rust unit tests on the detected host
target. The `uefi` dependency remains pinned and is enabled only for UEFI targets;
host tests exercise the same parser and bounded reader without firmware mocks.

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
make smoke       # Two valid-input scenarios and five rejection scenarios

# Direct equivalents / options
python3 scripts/neuboot.py run
python3 scripts/neuboot.py run --headless
python3 scripts/neuboot.py smoke --timeout 60
python3 scripts/neuboot.py smoke --require-gop
python3 scripts/neuboot.py smoke --no-graphics
python3 scripts/neuboot.py smoke --require-gop --decoy-volume
python3 scripts/neuboot.py smoke --boot-input missing
```

`--boot-input` also accepts `malformed`, `unsupported`, `oversized`, and
`directory`. These options prepare fixtures inside temporary VM media; they do
not take arbitrary host paths or affect real disks.

Application output structure (values depend on firmware; type rows abbreviated):

```text
NEU
NeuBoot v0.3.0

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
[OK] Boot volume located
[OK] Boot input validated: version 1, diagnostic fixture
[OK] Bootstrap milestone completed
[OK] Returning to firmware
```

Without GOP, the graphics fields are replaced by
`[INFO] GOP: unavailable (protocol not found)`. The completion and return messages
still appear.

The runner builds the application and copies it to `EFI/BOOT/BOOTX64.EFI`, together
with the fixture at `EFI/NEU/BOOT.INP`, in a fresh temporary directory under
`target/neuboot/`. QEMU exposes that directory as
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

`make smoke` runs a GOP-present VM with an invalid decoy volume attached before
the actual boot disk, then a valid-input VM with `-vga none`. It also runs five
independent rejection scenarios: missing, malformed, unsupported, oversized, and
directory input. Negative checks require the exact rejection/status, no success
claim, an OVMF failed-start report, and subsequent firmware continuation. The
harness reports an expected rejection separately from successful validation.

Logs are saved under `target/neuboot/`, named `smoke-decoy.log`,
`smoke-no-graphics.log`, and `smoke-<input-scenario>.log`. A direct default smoke
uses `smoke.log` and accepts optional GOP absence unless `--require-gop` is given.
`run --no-graphics` implies headless operation; `run --boot-input <scenario>` is
available for manual inspection of rejection behavior.

The smoke harness requires an OVMF build with serial text-console output and
`BdsDxe` boot-manager traces. It verifies the StartImage success/failure class and
resumed firmware; it does not independently decode the numeric returned status.
Other firmware logging layouts may need an adapted
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

Milestones 001–003 provide firmware discovery and a bounded boot-input preflight.
There is no kernel image, ELF loader, kernel handoff, `ExitBootServices`, custom
kernel allocator, virtual memory, interrupt handling, scheduler, Secure Boot support,
recovery system, AI execution, or desktop interface. No physical-hardware boot
has been validated. Future `kernel/` and `shared/` directories are deferred until
they contain real implementation.

Validation results and their limits are recorded in
[milestone 001 verification](docs/verification-001.md) and
[milestone 002 verification](docs/verification-002.md), followed by the current
[milestone 003 verification](docs/verification-003.md).

See [ADR 0001](docs/adr/0001-rust-uefi-bootstrap.md) for the initial decision and
the official API references used. Discovery uses the pinned crate's documented
[`system`](https://docs.rs/uefi/0.41.0/uefi/system/index.html),
[`memory_map`](https://docs.rs/uefi/0.41.0/uefi/boot/fn.memory_map.html), and
[`GraphicsOutput`](https://docs.rs/uefi/0.41.0/uefi/proto/console/gop/struct.GraphicsOutput.html)
APIs, including the documented behavior of
[`open_protocol_exclusive`](https://docs.rs/uefi/0.41.0/uefi/boot/fn.open_protocol_exclusive.html).
Boot-volume access uses the documented
[`get_image_file_system`](https://docs.rs/uefi/0.41.0/uefi/boot/fn.get_image_file_system.html),
[`File`](https://docs.rs/uefi/0.41.0/uefi/proto/media/file/trait.File.html), and
[`RegularFile`](https://docs.rs/uefi/0.41.0/uefi/proto/media/file/struct.RegularFile.html)
APIs. The new input/error policy is recorded in ADR 0002; no kernel handoff
structure is defined or retained.

A recommended next milestone is a separately reviewed kernel-artifact and
boot-information ownership contract, before implementing a loader. The current
fixture is provisional, unauthenticated, and unsuitable as a stable kernel ABI.
Kernel loading requires a separate instruction.
