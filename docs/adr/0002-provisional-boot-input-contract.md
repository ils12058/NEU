# ADR 0002: Provisional bounded diagnostic input and boot error policy

- Status: Accepted for milestone 003 testing; the format is **provisional**.
- Date: 2026-10-21.
- Builds on: [ADR 0001](0001-rust-uefi-bootstrap.md).

## Context

NeuBoot needs to establish its loaded-image filesystem association, bounded
read-only input handling, and explicit failures before any kernel loading is
considered. A fixture must test these boundaries without looking like an
executable or introducing a general configuration language.

## Boot-volume boundary

Resolve `boot::get_image_file_system(boot::image_handle())`. In `uefi` 0.41.0,
this opens the current `LoadedImage`, obtains its device context, resolves that
device's path to `SimpleFileSystem`, and returns a scoped protocol guard. Do not
enumerate filesystem handles or choose a filesystem merely because it is first.

Open the root and exactly `\EFI\NEU\BOOT.INP` with `FileMode::Read`. Report only
that the volume was located. Paths are compile-time constants; neither file
contents nor command-line data choose a guest file path. There is no directory
enumeration, traversal syntax, create/write call, file-size allocation, or
writable-storage requirement.

File, root-directory, and protocol wrappers close on every return path through
the crate's ownership rules. Only a small owned parsed result leaves this scope;
no file/firmware pointers or buffer borrows become boot state. The existing safe
protocol APIs use exclusive opens, with the firmware driver-consumer caveat
already documented for discovery.

## NEUI v1 fixture format

The file is binary. All integer fields are unsigned, little-endian, and required.

| Offset | Length | Field | v1 requirement |
| --- | --- | --- | --- |
| 0 | 4 | Magic | ASCII `NEUI` |
| 4 | 2 | Format version | `1` |
| 6 | 2 | Declared total file length | `12` |
| 8 | 4 | Input kind | `1`: diagnostic test fixture |

The complete v1 file is exactly these 12 bytes:

```text
4e 45 55 49 01 00 0c 00 01 00 00 00
```

The dedicated repository fixture is `boot/neuboot/fixtures/boot-input-v1.bin`.
It contains no executable, path, command, pointer, or kernel configuration.

There is an independent maximum input size of **64 bytes**, including all
headers and data. The reader uses a **65-byte stack buffer**, allowing one
detection byte beyond the limit. It handles short reads, continues until EOF,
and rejects a 65th byte immediately. It never accepts a valid prefix while
ignoring trailing data or a subsequent read failure. No input-sized heap buffer
or file metadata query is needed.

Validation precedence is deliberate:

1. Reject inputs above 64 bytes as oversized.
2. Require at least the 8-byte envelope, correct magic, and declared length equal
   to the actual complete input length. Failure is invalid contents.
3. Reject any version other than 1 as unsupported, without interpreting its body.
4. For version 1, require exactly 12 bytes and diagnostic-fixture kind 1. Missing
   fields, unknown kinds, and padding/trailing bytes are invalid contents.

A syntactically valid envelope with an unknown version is still rejected; its
payload is never accepted or executed. This order keeps malformed envelopes from
being mislabeled as a meaningful unsupported version.

## Error and completion policy

Input and volume failures end the current boot attempt. Expected rejection does
not mean success. It means a well-defined input/environment condition that can be
reported and returned to firmware without pretending validation succeeded.

| Condition | Classification | Returned UEFI status |
| --- | --- | --- |
| Valid v1 diagnostic fixture | Success | `SUCCESS` |
| Initial volume resolution/open returns `NOT_FOUND`, `UNSUPPORTED`, or `NO_MEDIA` | Expected volume-unavailable rejection | Original status |
| Fixed file open returns `NOT_FOUND` | Expected missing-input rejection | `NOT_FOUND` |
| Invalid envelope, v1 contents, or a directory in place of the file | Expected invalid-input rejection | `COMPROMISED_DATA` |
| Valid envelope, unsupported version | Expected version rejection | `UNSUPPORTED` |
| Input above the 64-byte limit | Expected size rejection | `BAD_BUFFER_SIZE` |
| Other resolution/open/type/read failures | Unexpected firmware I/O failure; fatal to this boot attempt | Original firmware error |
| Reader reports more bytes than its supplied buffer | Unexpected read-contract failure | `BAD_BUFFER_SIZE` |

An unavailable volume produces `[REJECT] Boot input: boot volume unavailable`.
Other expected rejections also use `[REJECT]`, while unexpected firmware I/O
failures use `[ERROR]` and identify only the operation and status. A media error
after the root was opened is an unexpected I/O failure, rather than a missing
file. The returned status is also printed for diagnosis.

All these input failures withhold both `Boot input validated` and `Bootstrap
milestone completed`. After a five-second pause, NeuBoot announces return after
boot failure and returns the error status. Successful input alone permits the
original bootstrap completion, pause, and `Status::SUCCESS` return. Firmware
discovery still precedes this preflight, and optional GOP absence stays nonfatal.

`COMPROMISED_DATA` is a structural-error status here; it does not imply a
cryptographic integrity or authenticity check.

## Verification boundary

The parser and bounded reader live in a small `no_std` library in the existing
NeuBoot package. Real host Rust unit tests use the same code; firmware-specific
dependency activation is restricted to UEFI targets. No parser dependency or
parallel interpretation of the binary format is introduced into the application.

The QEMU runner puts the fixture on disposable read-only FAT media and supports
missing, malformed, unsupported, oversized, and directory variants. A decoy
volume attached before the boot disk contains invalid input, while the image's
own volume contains the valid fixture. This checks the image-associated lookup
in a multi-volume VM. Disk/variable-store resources remain private to each run.

Positive smoke checks require validation/bootstrap success and firmware
continuation without an OVMF failed-start report. Negative checks require the
expected rejection and reported status, no success claims, a firmware failed-start
report, and continuation. Thus, firmware resuming by itself cannot satisfy an
input-validation test. Raw numeric return statuses are not independently decoded.

## Consequences and limits

The format is intentionally rigid and test-only, with no stable compatibility
promise, extensions, text options, kernel paths, resource policy, authentication,
or handoff representation. Future non-test boot inputs require another reviewed
contract/version decision. This milestone does not select or implement a kernel
image format, ELF parser, loading policy, `ExitBootServices`, or handoff mechanism.

The safe API boundary still relies on conforming firmware. Physical hardware,
unavailable loaded-image volumes, storage-removal/device failures, and firmware
handle-close failures need separate runtime fault-injection coverage.

## Official references

- [uefi 0.41.0 image-associated filesystem lookup](https://docs.rs/uefi/0.41.0/uefi/boot/fn.get_image_file_system.html)
- [SimpleFileSystem and root-directory access](https://docs.rs/uefi/0.41.0/uefi/proto/media/fs/struct.SimpleFileSystem.html)
- [File protocol and read-only open mode](https://docs.rs/uefi/0.41.0/uefi/proto/media/file/trait.File.html)
- [RegularFile read API](https://docs.rs/uefi/0.41.0/uefi/proto/media/file/struct.RegularFile.html)
