#![no_main]
#![no_std]

use core::time::Duration;
use uefi::{Status, boot, entry, println};

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
    println!("[OK] Bootstrap milestone completed");

    // Keep the firmware console readable before returning control to firmware.
    boot::stall(Duration::from_secs(5));
    Status::SUCCESS
}
