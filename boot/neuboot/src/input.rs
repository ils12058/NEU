//! Provisional NEUI v1 fixture envelope. This is not a kernel configuration ABI.

pub const MAX_INPUT_BYTES: usize = 64;
const HEADER_BYTES: usize = 8;
const V1_BYTES: usize = 12;

#[derive(Debug, PartialEq, Eq)]
pub struct BootInput {
    pub version: u16,
}

#[derive(Debug, PartialEq, Eq)]
pub enum InputError {
    InvalidContents,
    UnsupportedVersion(u16),
    Oversized,
}

pub fn validate(bytes: &[u8]) -> Result<BootInput, InputError> {
    if bytes.len() > MAX_INPUT_BYTES {
        return Err(InputError::Oversized);
    }
    if bytes.len() < HEADER_BYTES || &bytes[..4] != b"NEUI" {
        return Err(InputError::InvalidContents);
    }
    let version = u16::from_le_bytes([bytes[4], bytes[5]]);
    let declared_length = u16::from_le_bytes([bytes[6], bytes[7]]);
    if usize::from(declared_length) != bytes.len() {
        return Err(InputError::InvalidContents);
    }
    if version != 1 {
        return Err(InputError::UnsupportedVersion(version));
    }
    if bytes.len() != V1_BYTES {
        return Err(InputError::InvalidContents);
    }
    let kind = u32::from_le_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]);
    if kind != 1 {
        return Err(InputError::InvalidContents);
    }
    Ok(BootInput { version })
}

#[derive(Debug, PartialEq, Eq)]
pub enum ReadError<E> {
    Io(E),
    Oversized,
    InvalidReadCount,
}

/// Consume at most the limit plus one detection byte, including short reads.
/// The callback keeps the small reader testable without a firmware dependency.
pub fn read_bounded<E>(
    buffer: &mut [u8; MAX_INPUT_BYTES + 1],
    mut read: impl FnMut(&mut [u8]) -> Result<usize, E>,
) -> Result<usize, ReadError<E>> {
    let mut used = 0;
    loop {
        let remaining = &mut buffer[used..];
        let count = read(remaining).map_err(ReadError::Io)?;
        if count > remaining.len() {
            return Err(ReadError::InvalidReadCount);
        }
        if count == 0 {
            return Ok(used);
        }
        used += count;
        if used > MAX_INPUT_BYTES {
            return Err(ReadError::Oversized);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIXTURE: &[u8; V1_BYTES] = include_bytes!("../fixtures/boot-input-v1.bin");

    #[test]
    fn accepts_the_repository_fixture() {
        assert_eq!(validate(FIXTURE), Ok(BootInput { version: 1 }));
    }

    #[test]
    fn rejects_every_truncated_v1_record() {
        for length in 0..V1_BYTES {
            assert_eq!(
                validate(&FIXTURE[..length]),
                Err(InputError::InvalidContents)
            );
        }
    }

    #[test]
    fn rejects_bad_magic_declared_length_and_required_kind() {
        for index in [0, 1, 2, 3, 6, 7, 8, 9, 10, 11] {
            let mut bytes = *FIXTURE;
            bytes[index] ^= 0xFF;
            assert_eq!(validate(&bytes), Err(InputError::InvalidContents));
        }
        let mut bytes = *FIXTURE;
        bytes[8] = 0;
        assert_eq!(validate(&bytes), Err(InputError::InvalidContents));
    }

    #[test]
    fn rejects_unsupported_versions_without_interpreting_their_payload() {
        for version in [0_u16, 2, u16::MAX] {
            let mut bytes = *FIXTURE;
            bytes[4..6].copy_from_slice(&version.to_le_bytes());
            assert_eq!(
                validate(&bytes),
                Err(InputError::UnsupportedVersion(version))
            );
        }
    }

    #[test]
    fn malformed_envelope_takes_precedence_over_unsupported_version() {
        let mut bytes = *FIXTURE;
        bytes[4] = 2;
        bytes[6] = 0;
        assert_eq!(validate(&bytes), Err(InputError::InvalidContents));
    }

    #[test]
    fn rejects_padding_and_distinguishes_the_size_limit() {
        let mut bytes = [0_u8; MAX_INPUT_BYTES + 1];
        bytes[..V1_BYTES].copy_from_slice(FIXTURE);
        assert_eq!(
            validate(&bytes[..V1_BYTES + 1]),
            Err(InputError::InvalidContents)
        );
        bytes[6] = MAX_INPUT_BYTES as u8;
        assert_eq!(
            validate(&bytes[..MAX_INPUT_BYTES]),
            Err(InputError::InvalidContents)
        );
        assert_eq!(validate(&bytes), Err(InputError::Oversized));
    }

    #[test]
    fn consumes_partial_reads_until_eof() {
        let mut source = FIXTURE.as_slice();
        let mut buffer = [0; MAX_INPUT_BYTES + 1];
        let count = read_bounded::<()>(&mut buffer, |output| {
            let count = source.len().min(3).min(output.len());
            output[..count].copy_from_slice(&source[..count]);
            source = &source[count..];
            Ok(count)
        });
        assert_eq!(count, Ok(V1_BYTES));
        assert_eq!(
            validate(&buffer[..count.unwrap()]),
            Ok(BootInput { version: 1 })
        );
    }

    #[test]
    fn exact_limit_is_readable_but_one_extra_byte_is_oversized() {
        for length in [MAX_INPUT_BYTES, MAX_INPUT_BYTES + 1] {
            let mut left = length;
            let mut buffer = [0; MAX_INPUT_BYTES + 1];
            let result = read_bounded::<()>(&mut buffer, |output| {
                let count = left.min(output.len());
                output[..count].fill(0);
                left -= count;
                Ok(count)
            });
            if length == MAX_INPUT_BYTES {
                assert_eq!(result, Ok(MAX_INPUT_BYTES));
            } else {
                assert_eq!(result, Err(ReadError::Oversized));
            }
        }
    }

    #[test]
    fn a_valid_prefix_does_not_hide_an_io_failure() {
        let mut buffer = [0; MAX_INPUT_BYTES + 1];
        let mut first = true;
        let result = read_bounded(&mut buffer, |output| {
            if first {
                output[..V1_BYTES].copy_from_slice(FIXTURE);
                first = false;
                Ok(V1_BYTES)
            } else {
                Err("read failed")
            }
        });
        assert_eq!(result, Err(ReadError::Io("read failed")));
    }

    #[test]
    fn invalid_reader_lengths_are_not_file_validation_errors() {
        let mut buffer = [0; MAX_INPUT_BYTES + 1];
        assert_eq!(
            read_bounded::<()>(&mut buffer, |output| Ok(output.len() + 1)),
            Err(ReadError::InvalidReadCount)
        );
    }
}
