PYTHON ?= python3

.PHONY: help setup build check run smoke clean

help:
	@printf '%s\n' 'make setup  Install the pinned Rust toolchain and UEFI target' 'make build  Build and inspect the UEFI executable' 'make check  Check Rust formatting and Clippy' 'make run    Boot in QEMU (close its window or use Ctrl-a x to exit)' 'make smoke  Verify firmware console output in headless QEMU' 'make clean  Remove generated build and VM artifacts'

setup:
	rustup target add x86_64-unknown-uefi

build:
	$(PYTHON) scripts/neuboot.py build

check:
	cargo fmt --all -- --check
	cargo clippy --locked --package neuboot -- -D warnings

run:
	$(PYTHON) scripts/neuboot.py run

smoke:
	$(PYTHON) scripts/neuboot.py smoke

clean:
	cargo clean --target-dir target
