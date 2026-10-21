//! One read-only input on the filesystem associated with our own loaded image.

use neuboot::input::{self, BootInput, InputError, MAX_INPUT_BYTES, ReadError};
use uefi::proto::media::file::{File, FileAttribute, FileMode, FileType};
use uefi::{Status, boot, cstr16, println};

pub enum BootError {
    VolumeUnavailable(Status),
    MissingInput,
    InvalidInput,
    UnsupportedVersion(u16),
    OversizedInput,
    FirmwareIo {
        operation: &'static str,
        status: Status,
    },
}

impl BootError {
    pub fn status(&self) -> Status {
        match self {
            Self::VolumeUnavailable(status) | Self::FirmwareIo { status, .. } => *status,
            Self::MissingInput => Status::NOT_FOUND,
            Self::InvalidInput => Status::COMPROMISED_DATA,
            Self::UnsupportedVersion(_) => Status::UNSUPPORTED,
            Self::OversizedInput => Status::BAD_BUFFER_SIZE,
        }
    }

    pub fn report(&self) {
        match self {
            Self::VolumeUnavailable(status) => {
                println!("[REJECT] Boot input: boot volume unavailable ({status:?})");
            }
            Self::MissingInput => println!("[REJECT] Boot input: file not found"),
            Self::InvalidInput => println!("[REJECT] Boot input: invalid contents"),
            Self::UnsupportedVersion(version) => {
                println!("[REJECT] Boot input: unsupported version {version}");
            }
            Self::OversizedInput => {
                println!("[REJECT] Boot input: oversized (limit {MAX_INPUT_BYTES} bytes)");
            }
            Self::FirmwareIo { operation, status } => {
                println!("[ERROR] Boot input: firmware I/O failure at {operation}: {status:?}");
            }
        }
        println!("[INFO] Boot input status: {:?}", self.status());
    }
}

fn volume_error(operation: &'static str, status: Status) -> BootError {
    if matches!(
        status,
        Status::NOT_FOUND | Status::UNSUPPORTED | Status::NO_MEDIA
    ) {
        BootError::VolumeUnavailable(status)
    } else {
        BootError::FirmwareIo { operation, status }
    }
}

pub fn read_input() -> Result<BootInput, BootError> {
    // This helper resolves LoadedImage -> its device path -> SimpleFileSystem.
    // Never enumerate filesystems or choose a first-available filesystem handle.
    let mut filesystem = boot::get_image_file_system(boot::image_handle())
        .map_err(|error| volume_error("locate boot volume", error.status()))?;
    let mut root = filesystem
        .open_volume()
        .map_err(|error| volume_error("open boot volume", error.status()))?;
    println!("[OK] Boot volume located");

    // No path is accepted from input, and no directory entries are enumerated.
    let file = root
        .open(
            cstr16!("\\EFI\\NEU\\BOOT.INP"),
            FileMode::Read,
            FileAttribute::empty(),
        )
        .map_err(|error| {
            if error.status() == Status::NOT_FOUND {
                BootError::MissingInput
            } else {
                BootError::FirmwareIo {
                    operation: "open input",
                    status: error.status(),
                }
            }
        })?;
    let mut file = match file.into_type().map_err(|error| BootError::FirmwareIo {
        operation: "identify input file",
        status: error.status(),
    })? {
        FileType::Regular(file) => file,
        FileType::Dir(_) => return Err(BootError::InvalidInput),
    };

    // The extra byte detects oversized files without trusting file-size metadata.
    // File/root handles and the protocol guard close on every return path.
    let mut buffer = [0; MAX_INPUT_BYTES + 1];
    let count = input::read_bounded(&mut buffer, |output| {
        file.read(output).map_err(|error| error.status())
    })
    .map_err(|error| match error {
        ReadError::Oversized => BootError::OversizedInput,
        ReadError::Io(status) => BootError::FirmwareIo {
            operation: "read input",
            status,
        },
        ReadError::InvalidReadCount => BootError::FirmwareIo {
            operation: "read input",
            status: Status::BAD_BUFFER_SIZE,
        },
    })?;
    input::validate(&buffer[..count]).map_err(|error| match error {
        InputError::InvalidContents => BootError::InvalidInput,
        InputError::UnsupportedVersion(version) => BootError::UnsupportedVersion(version),
        InputError::Oversized => BootError::OversizedInput,
    })
}
