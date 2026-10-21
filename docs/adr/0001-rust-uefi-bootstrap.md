# ADR 0001: Custom Rust UEFI bootstrap

- Status: Accepted for milestone 001; revisable.
- Date: 2026-10-21.

## Context

Neu needs a small, understandable starting point for its boot infrastructure.
This milestone establishes execution under firmware, without selecting a kernel
architecture or implementing kernel loading.

## Decision

Implement NeuBoot as a `no_std`, `no_main` Rust application for
`x86_64-unknown-uefi`, using `uefi` 0.41.0 and its documented zero-argument
`#[entry] fn main() -> Status` interface. Initialize the crate's helpers, use the
UEFI text console, pause briefly, and return `Status::SUCCESS` to firmware. Keep
the implementation single-core and prohibit unsafe code in the NeuBoot crate.

Enable only the dependency's panic handler; this application needs neither a
global allocator nor a logging facade. Its version comes from Cargo metadata.
The maintained `uefi` crate owns the underlying unsafe firmware interface; no
project-written unsafe operation is needed.

Pin Rust and the `uefi` release, keep Cargo's dependency lockfile in the source
tree, disable release PDB generation, and set the PE timestamp to zero rather
than embedding the build time. A small build script applies `/DEBUG:NONE` only
to release images: rustc's PE linker otherwise generates a varying PDB identifier
even without source debug information. Debug builds keep normal PDB generation.
Run QEMU with TCG so the same command works on x86-64 and ARM64 development hosts.
Use read-only directory-backed FAT boot media on a VirtIO disk with explicit boot
priority, and a disposable OVMF variable store.

## Consequences

The small custom application exposes the firmware boundary directly and is easy
to compile and observe. It provides no kernel boot functionality yet. Taking
ownership of a custom loader will require explicit, later decisions about image
formats, boot information, failure handling, and firmware service lifetime.
The five-second firmware stall deliberately keeps this milestone's output
readable; it is not a scheduling mechanism. Software emulation prioritizes host
portability over boot speed. The smoke harness checks real console output and
stops the VM itself after allowing the application to return.

No AI inference belongs in this boot path or the privileged kernel. Runtime,
desktop, and kernel subsystems are outside this decision.

## References

- [uefi 0.41.0 crate documentation](https://docs.rs/uefi/0.41.0/uefi/)
- [Current entry-point contract](https://docs.rs/uefi/0.41.0/uefi/attr.entry.html)
- [Rust UEFI Book: creating an application](https://rust-osdev.github.io/uefi-rs/tutorial/app.html)
- [Rust UEFI Book: building](https://rust-osdev.github.io/uefi-rs/tutorial/building.html)
- [QEMU: virtual FAT disk images](https://www.qemu.org/docs/master/system/images.html#virtual-fat-disk-images)
- [LLVM LLD: explicit PE timestamps](https://lists.llvm.org/pipermail/llvm-commits/Week-of-Mon-20180514/552858.html)
- [Rust 1.95 PE linker debug-info handling](https://github.com/rust-lang/rust/blob/1.95.0/compiler/rustc_codegen_ssa/src/back/linker.rs)
