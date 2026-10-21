PYTHON ?= python3

.PHONY: help setup build check run smoke clean

help:
	@printf '%s\n' 'make setup  Install the pinned Rust toolchain and UEFI target' 'make build  Build and inspect the UEFI executable' 'make check  Check Rust formatting, Clippy, and smoke-validator tests' 'make run    Boot in QEMU (close its window or use Ctrl-a x to exit)' 'make smoke  Verify discovery and firmware return, with and without graphics' 'make clean  Remove generated build and VM artifacts'

setup:
	rustup target add x86_64-unknown-uefi

build:
	$(PYTHON) scripts/neuboot.py build

check:
	cargo fmt --all -- --check
	cargo clippy --locked --package neuboot -- -D warnings
	$(PYTHON) -m unittest discover -s scripts -p 'test_*.py'

run:
	$(PYTHON) scripts/neuboot.py run

smoke:
	$(PYTHON) scripts/neuboot.py smoke --require-gop
	$(PYTHON) scripts/neuboot.py smoke --no-graphics

clean:
	cargo clean --target-dir target
