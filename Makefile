PYTHON ?= python3

.PHONY: help setup build check run smoke clean

help:
	@printf '%s\n' 'make setup  Install the pinned Rust toolchain and UEFI target' 'make build  Build and inspect the UEFI executable' 'make check  Check formatting, Clippy, Rust input tests, and smoke-validator tests' 'make run    Boot in QEMU (close its window or use Ctrl-a x to exit)' 'make smoke  Verify both graphics scenarios and boot-input rejections' 'make clean  Remove generated build and VM artifacts'

setup:
	rustup target add x86_64-unknown-uefi

build:
	$(PYTHON) scripts/neuboot.py build

check:
	cargo fmt --all -- --check
	cargo clippy --locked --package neuboot -- -D warnings
	$(PYTHON) scripts/neuboot.py test
	$(PYTHON) -m unittest discover -s scripts -p 'test_*.py'

run:
	$(PYTHON) scripts/neuboot.py run

smoke:
	$(PYTHON) scripts/neuboot.py smoke --require-gop --decoy-volume
	$(PYTHON) scripts/neuboot.py smoke --no-graphics
	@for scenario in missing malformed unsupported oversized directory; do $(PYTHON) scripts/neuboot.py smoke --boot-input $$scenario || exit $$?; done

clean:
	cargo clean --target-dir target
