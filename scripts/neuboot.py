#!/usr/bin/env python3
"""Build NeuBoot and run it with disposable QEMU/OVMF resources (Python 3.9+)."""

import argparse
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
EXPECTED_LINES = (
    "NEU",
    "NeuBoot v0.1.0",
    "[OK] UEFI environment initialized",
    "[OK] NeuBoot execution started",
    "[OK] Bootstrap milestone completed",
)
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


def smoke(command, timeout, capture):
    log = ARTIFACTS / "smoke.log"
    print(f"Capturing firmware console output: {log}", flush=True)
    # Each VM reads its own capture even if another developer starts a second run.
    with capture.open("w") as output:
        process = subprocess.Popen(
            command, cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + timeout
        observed_at = None
        try:
            while time.monotonic() < deadline:
                console = ANSI_ESCAPE.sub("", capture.read_text(errors="replace")).replace("\r", "")
                if "[PANIC]" in console or "[ERROR]" in console:
                    raise RuntimeError(f"NeuBoot reported a failure; inspect {log}")
                lines = console.splitlines()
                # Require the complete banner and success messages in order.
                position = 0
                for line in lines:
                    if position < len(EXPECTED_LINES) and line == EXPECTED_LINES[position]:
                        position += 1
                if position == len(EXPECTED_LINES) and observed_at is None:
                    observed_at = time.monotonic()
                status = process.poll()
                if status is not None and status != 0:
                    raise RuntimeError(f"QEMU exited with status {status}; inspect {log}")
                # Allow the application's five-second pause and return to firmware.
                if observed_at is not None and (time.monotonic() - observed_at >= 6 or status == 0):
                    print("\n".join(EXPECTED_LINES), flush=True)
                    print(f"PASS: NeuBoot output observed through OVMF's console; log: {log}")
                    return
                if status is not None:
                    raise RuntimeError(f"QEMU exited before NeuBoot output was verified; inspect {log}")
                time.sleep(0.1)
            raise RuntimeError(f"NeuBoot output was not verified within {timeout}s; inspect {log}")
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
    build()
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
        if args.command == "smoke":
            command += ["-display", "none", "-monitor", "none", "-serial", "stdio"]
            smoke(command, args.timeout, temporary / "console.log")
        else:
            command += ["-serial", "mon:stdio"]
            if args.headless:
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
    args = parser.parse_args()
    if args.command == "smoke" and args.timeout <= 6:
        parser.error("--timeout must exceed 6 seconds")
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
