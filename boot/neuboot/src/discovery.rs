//! Firmware observations while boot services remain active; no kernel boot state.

use uefi::boot::{self, MemoryType};
use uefi::mem::memory_map::MemoryMap;
use uefi::proto::console::gop::{GraphicsOutput, PixelFormat};
use uefi::{Result, Status, println, system};

pub fn report() -> Result {
    report_identity();
    report_memory_map()?;
    report_graphics();
    println!("[OK] Firmware discovery completed");
    Ok(())
}

fn report_identity() {
    let vendor = system::firmware_vendor();
    if vendor.is_empty() {
        println!("[INFO] Firmware vendor: unavailable");
    } else {
        println!("[INFO] Firmware vendor: {vendor}");
    }
    println!(
        "[INFO] UEFI specification revision: {}",
        system::uefi_revision()
    );
    // This field's interpretation is vendor-defined, so preserve its raw value.
    println!(
        "[INFO] Firmware revision: {:#010x}",
        system::firmware_revision()
    );
}

fn report_memory_map() -> Result {
    // The crate owns and frees this temporary firmware-pool allocation. Borrowed
    // descriptors never leave this scope; later allocations can change the live
    // map without changing this snapshot. No Rust global allocator is needed.
    let map = boot::memory_map(MemoryType::LOADER_DATA)?;
    let total_pages = map
        .entries()
        .try_fold(0_u64, |total, descriptor| {
            total.checked_add(descriptor.page_count)
        })
        .ok_or(Status::BAD_BUFFER_SIZE)?;
    if map.is_empty() || total_pages == 0 {
        return Err(Status::COMPROMISED_DATA.into());
    }
    println!(
        "[INFO] Memory map: {} descriptors, {total_pages} pages (4 KiB each)",
        map.len()
    );

    // Scan the small snapshot once per distinct type instead of allocating a
    // histogram or assuming all firmware/OEM types fit a fixed-size table.
    // Numeric ordering keeps the output stable for a given snapshot.
    let mut next_type = map.entries().map(|entry| entry.ty).min_by_key(|ty| ty.0);
    while let Some(ty) = next_type {
        // The checked total above bounds every subset of these unsigned counts.
        let pages: u64 = map
            .entries()
            .filter(|entry| entry.ty == ty)
            .map(|entry| entry.page_count)
            .sum();
        println!("[INFO] Memory type {} ({ty:?}): {pages} pages", ty.0);
        next_type = map
            .entries()
            .map(|entry| entry.ty)
            .filter(|candidate| candidate.0 > ty.0)
            .min_by_key(|ty| ty.0);
    }
    Ok(())
}

fn report_graphics() {
    let handle = match boot::get_handle_for_protocol::<GraphicsOutput>() {
        Ok(handle) => handle,
        Err(error) if error.status() == Status::NOT_FOUND => {
            println!("[INFO] GOP: unavailable (protocol not found)");
            return;
        }
        Err(error) => {
            println!("[WARN] GOP: unavailable (lookup failed: {error})");
            return;
        }
    };

    let (mode, framebuffer_size) = {
        // Use the crate's safe scoped access. Close the protocol before console
        // output and before returning to firmware; keep only copied metadata.
        let mut gop = match boot::open_protocol_exclusive::<GraphicsOutput>(handle) {
            Ok(gop) => gop,
            Err(error) => {
                println!("[WARN] GOP: unavailable (open failed: {error})");
                return;
            }
        };
        let mode = gop.current_mode_info();
        // frame_buffer() panics for BltOnly. Such modes have no directly
        // accessible framebuffer, and we must not attempt to obtain one.
        let framebuffer_size = if mode.pixel_format() == PixelFormat::BltOnly {
            None
        } else {
            Some(gop.frame_buffer().size())
        };
        (mode, framebuffer_size)
    };

    let (width, height) = mode.resolution();
    println!("[INFO] GOP: available");
    println!("[INFO] GOP resolution: {width}x{height}");
    println!("[INFO] GOP pixel format: {:?}", mode.pixel_format());
    match framebuffer_size {
        Some(bytes) => println!("[INFO] GOP framebuffer size: {bytes} bytes"),
        None => println!("[INFO] GOP framebuffer size: unavailable (BltOnly)"),
    }
}
