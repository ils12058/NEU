#![no_main]
#![no_std]

use core::time::Duration;
use uefi::{Status, boot, entry, println};

mod boot_volume;
mod discovery;

#[entry]
fn main() -> Status {
    if let Err(error) = uefi::helpers::init() {
        println!("[ERROR] UEFI support initialization failed: {error}");
        return error.status();
    }

    println!("NEU");
    println!("NeuBoot v{}", env!("CARGO_PKG_VERSION"));
    println!();
    println!("[OK] UEFI environment initialized");
    println!("[OK] NeuBoot execution started");

    if let Err(error) = discovery::report() {
        println!("[ERROR] Firmware discovery failed: {error}");
        return error.status();
    }

    match boot_volume::read_input() {
        Ok(input) => println!(
            "[OK] Boot input validated: version {}, diagnostic fixture",
            input.version
        ),
        Err(error) => {
            error.report();
            boot::stall(Duration::from_secs(5));
            println!("[INFO] Returning to firmware after boot failure");
            return error.status();
        }
    }

    println!("[OK] Bootstrap milestone completed");

    // Keep the firmware console readable before returning control to firmware.
    boot::stall(Duration::from_secs(5));
    println!("[OK] Returning to firmware");
    Status::SUCCESS
}
