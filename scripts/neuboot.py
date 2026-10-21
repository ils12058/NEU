#!/usr/bin/env python3
"""Build NeuBoot and run it with disposable QEMU/OVMF resources (Python 3.9+)."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "target"
ARTIFACTS = TARGET / "neuboot"
UEFI_TARGET = "x86_64-unknown-uefi"
IMAGE = TARGET / UEFI_TARGET / "release" / "neuboot.efi"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def build():
    subprocess.run(
        [
            "cargo", "build", "--locked", "--release", "--package", "neuboot",
            "--target", UEFI_TARGET, "--target-dir", str(TARGET),
        ],
        cwd=ROOT,
        check=True,
    )
    # Inspect PE/COFF headers without depending on host-specific binary tools.
    data = IMAGE.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise RuntimeError("The build output is not a PE executable")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe + 24
    if optional + 70 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        raise RuntimeError("The build output has an invalid PE header")
    machine = struct.unpack_from("<H", data, pe + 4)[0]
    magic = struct.unpack_from("<H", data, optional)[0]
    entry = struct.unpack_from("<I", data, optional + 16)[0]
    subsystem = struct.unpack_from("<H", data, optional + 68)[0]
    if (machine, magic, subsystem) != (0x8664, 0x20B, 10) or entry == 0:
        raise RuntimeError("Expected an x86-64 PE32+ EFI application with an entry point")
    print(f"Verified x86-64 PE32+ EFI application: {IMAGE}", flush=True)
    metadata = json.loads(subprocess.check_output(
        ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"],
        cwd=ROOT, text=True,
    ))
    return next(package["version"] for package in metadata["packages"] if package["name"] == "neuboot")


def firmware(qemu):
    code = os.environ.get("OVMF_CODE")
    variables = os.environ.get("OVMF_VARS")
    if code or variables:
        if not (code and variables):
            raise RuntimeError("Set both OVMF_CODE and OVMF_VARS to a matching firmware pair")
        pair = (Path(code).expanduser().resolve(), Path(variables).expanduser().resolve())
        if not all(path.is_file() for path in pair):
            raise RuntimeError("OVMF_CODE and OVMF_VARS must name existing firmware files")
        return pair

    # Resolving the executable handles Homebrew on either ARM64 or Intel Macs.
    roots = (
        Path(qemu).resolve().parent.parent / "share" / "qemu",
        Path("/usr/share/OVMF"),
        Path("/usr/share/ovmf"),
        Path("/usr/share/edk2/ovmf"),
        Path("/usr/share/edk2/x64"),
        Path("/usr/share/qemu"),
        Path("/usr/local/share/qemu"),
    )
    names = (
        ("OVMF_CODE_4M.fd", "OVMF_VARS_4M.fd"),
        ("OVMF_CODE.fd", "OVMF_VARS.fd"),
        ("OVMF_CODE.4m.fd", "OVMF_VARS.4m.fd"),
        # QEMU's x86-64 EDK II firmware shares the i386 variable-store template.
        ("edk2-x86_64-code.fd", "edk2-i386-vars.fd"),
    )
    for root in roots:
        for code_name, vars_name in names:
            pair = (root / code_name, root / vars_name)
            if all(path.is_file() for path in pair):
                return pair
    raise RuntimeError(
        "OVMF was not found. Install OVMF/edk2-ovmf, or set OVMF_CODE and OVMF_VARS "
        "to a matching x86-64, non-Secure-Boot firmware pair."
    )


def drive_path(path):
    """Escape the comma separator in QEMU's -drive option syntax."""
    return str(path).replace(",", ",,")


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def inspect_console(console, version, no_graphics=False, require_gop=False):
    """Validate complete discovery output; separately observe firmware resuming."""
    console = ANSI_ESCAPE.sub("", console).replace("\r", "")
    if "[PANIC]" in console or "[ERROR]" in console:
        raise RuntimeError("NeuBoot reported a failure")
    lines = console.splitlines()
    markers = (
        "NEU", f"NeuBoot v{version}",
        "[OK] UEFI environment initialized", "[OK] NeuBoot execution started",
        "[OK] Firmware discovery completed", "[OK] Bootstrap milestone completed",
        "[OK] Returning to firmware",
    )
    positions = []
    for index, line in enumerate(lines):
        if len(positions) < len(markers) and line == markers[len(positions)]:
            positions.append(index)
    if len(positions) != len(markers):
        return None
    discovery = lines[positions[3] + 1:positions[4]]

    def field(prefix):
        values = [line[len(prefix):] for line in discovery if line.startswith(prefix)]
        if len(values) != 1 or not values[0]:
            raise RuntimeError(f"Expected one nonempty discovery field: {prefix}")
        return values[0]

    field("[INFO] Firmware vendor: ")
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", field("[INFO] UEFI specification revision: ")):
        raise RuntimeError("Invalid UEFI specification revision")
    if not re.fullmatch(r"0x[0-9a-fA-F]{8}", field("[INFO] Firmware revision: ")):
        raise RuntimeError("Invalid firmware revision")
    summary = re.fullmatch(
        r"([1-9]\d*) descriptors, ([1-9]\d*) pages \(4 KiB each\)",
        field("[INFO] Memory map: "),
    )
    if summary is None:
        raise RuntimeError("Invalid memory-map summary")
    descriptors, total_pages = map(int, summary.groups())
    rows = []
    for line in discovery:
        if line.startswith("[INFO] Memory type "):
            row = re.fullmatch(r"\[INFO\] Memory type (\d+) \((.+)\): (\d+) pages", line)
            if row is None:
                raise RuntimeError("Invalid memory-type row")
            rows.append((int(row[1]), int(row[3])))
    types = [ty for ty, _ in rows]
    if not rows or len(rows) > descriptors or types != sorted(set(types)):
        raise RuntimeError("Memory types must be unique, sorted, and backed by descriptors")
    if any(ty > 0xFFFF_FFFF for ty in types) or sum(pages for _, pages in rows) != total_pages:
        raise RuntimeError("Memory-type page counts do not match the snapshot total")

    gop = [line for line in discovery if line.startswith(("[INFO] GOP: ", "[WARN] GOP: "))]
    if len(gop) != 1:
        raise RuntimeError("Expected one GOP availability result")
    if gop[0] == "[INFO] GOP: available":
        if no_graphics:
            raise RuntimeError("GOP was available with emulated graphics disabled")
        if not re.fullmatch(r"[1-9]\d*x[1-9]\d*", field("[INFO] GOP resolution: ")):
            raise RuntimeError("Invalid GOP resolution")
        pixel_format = field("[INFO] GOP pixel format: ")
        size = field("[INFO] GOP framebuffer size: ")
        if pixel_format not in {"Rgb", "Bgr", "Bitmask", "BltOnly"}:
            raise RuntimeError("Invalid GOP pixel format")
        if pixel_format == "BltOnly":
            if size != "unavailable (BltOnly)":
                raise RuntimeError("BltOnly must not expose a direct framebuffer")
        elif not re.fullmatch(r"[1-9]\d* bytes", size):
            raise RuntimeError("Invalid GOP framebuffer size")
    elif "GOP: unavailable (" in gop[0]:
        if require_gop:
            raise RuntimeError("GOP is required for this smoke scenario")
        if no_graphics and gop[0] != "[INFO] GOP: unavailable (protocol not found)":
            raise RuntimeError("Expected missing GOP, rather than a failed protocol query")
        if any(line.startswith(("[INFO] GOP resolution:", "[INFO] GOP pixel format:",
                                "[INFO] GOP framebuffer size:")) for line in discovery):
            raise RuntimeError("Unavailable GOP must not expose mode metadata")
    else:
        raise RuntimeError("Invalid GOP availability result")

    # Observe OVMF continuing after our final marker, rather than assuming that
    # waiting a fixed duration proves return. Do not hardcode boot IDs or targets.
    resumed = any(line.startswith(("BdsDxe: loading ", "BdsDxe: starting "))
                  for line in lines[positions[-1] + 1:])
    return lines[positions[0]:positions[-1] + 1], resumed


def smoke(command, timeout, capture, version, no_graphics, require_gop):
    log = ARTIFACTS / ("smoke-no-graphics.log" if no_graphics else "smoke.log")
    print(f"Capturing firmware console output: {log}", flush=True)
    # Each VM reads its own capture even if another developer starts a second run.
    with capture.open("w") as output:
        process = subprocess.Popen(
            command, cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                observed = inspect_console(
                    capture.read_text(errors="replace"), version, no_graphics, require_gop
                )
                status = process.poll()
                if status is not None and status != 0:
                    raise RuntimeError(f"QEMU exited with status {status}; inspect {log}")
                if observed is not None and observed[1]:
                    print("\n".join(observed[0]), flush=True)
                    print(f"PASS: firmware discovery and return observed through OVMF; log: {log}")
                    return
                if status is not None:
                    raise RuntimeError(f"QEMU exited before NeuBoot output was verified; inspect {log}")
                time.sleep(0.1)
            raise RuntimeError(f"Discovery and firmware return were not verified within {timeout}s; inspect {log}")
        finally:
            stop(process)
            shutil.copyfile(capture, log)


def run(args):
    qemu = shutil.which(os.environ.get("QEMU", "qemu-system-x86_64"))
    if qemu is None:
        raise RuntimeError("qemu-system-x86_64 was not found on PATH; install QEMU or set QEMU")
    code, variables = firmware(qemu)
    print(f"Host: {platform.system()} {platform.machine()}; guest: x86-64, one CPU, TCG", flush=True)
    print(f"OVMF code: {code}\nOVMF variables template: {variables}", flush=True)
    version = build()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qemu-", dir=ARTIFACTS) as directory:
        temporary = Path(directory)
        esp = temporary / "esp"
        boot = esp / "EFI" / "BOOT"
        boot.mkdir(parents=True)
        shutil.copyfile(IMAGE, boot / "BOOTX64.EFI")
        # Only this private copy of the firmware variable store is writable.
        private_vars = temporary / "OVMF_VARS.fd"
        shutil.copyfile(variables, private_vars)
        command = [
            qemu, "-name", "NeuBoot", "-machine", "q35,accel=tcg",
            "-cpu", "qemu64", "-smp", "1", "-m", "128M",
            "-net", "none", "-no-reboot",
            "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={drive_path(code)}",
            "-drive", f"if=pflash,format=raw,unit=1,file={drive_path(private_vars)}",
            "-drive", f"if=none,id=neuboot,format=raw,readonly=on,file=fat:{drive_path(esp)}",
            "-device", "virtio-blk-pci,drive=neuboot,bootindex=1",
        ]
        if args.no_graphics:
            command += ["-vga", "none"]
        if args.command == "smoke":
            command += ["-display", "none", "-monitor", "none", "-serial", "stdio"]
            smoke(command, args.timeout, temporary / "console.log", version,
                  args.no_graphics, args.require_gop)
        else:
            command += ["-serial", "mon:stdio"]
            if args.headless or args.no_graphics:
                command += ["-display", "none"]
            print("Close QEMU's window or press Ctrl-a then x in this terminal to exit.", flush=True)
            process = subprocess.Popen(command, cwd=ROOT)
            try:
                status = process.wait()
                if status != 0:
                    raise RuntimeError(f"QEMU exited with status {status}")
            finally:
                stop(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="Build and inspect the UEFI executable")
    run_parser = commands.add_parser("run", help="Boot NeuBoot in QEMU")
    run_parser.add_argument("--headless", action="store_true", help="Use only the serial console")
    smoke_parser = commands.add_parser("smoke", help="Verify firmware console output in QEMU")
    smoke_parser.add_argument("--timeout", type=int, default=60, help="Boot timeout in seconds (default: 60)")
    smoke_parser.add_argument("--require-gop", action="store_true",
                              help="Require GOP to verify the graphics-present scenario")
    for vm_parser in (run_parser, smoke_parser):
        vm_parser.add_argument("--no-graphics", action="store_true",
                               help="Disable emulated VGA to exercise missing GOP (implies headless)")
    args = parser.parse_args()
    if args.command == "smoke" and args.timeout <= 6:
        parser.error("--timeout must exceed 6 seconds")
    if args.command == "smoke" and args.require_gop and args.no_graphics:
        parser.error("--require-gop cannot be combined with --no-graphics")
    try:
        if args.command == "build":
            build()
        else:
            run(args)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
