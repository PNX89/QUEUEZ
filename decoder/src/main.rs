//! Read a recorded session and emit the normalised series, exactly as the Python reader does.
//!
//! WHY THE SAME THING TWICE. One implementation of a format is an implementation and not a
//! specification: nothing has ever had to agree with it, so nowhere does it say which of its
//! behaviours were chosen. Writing it again in a language with different defaults, no exceptions
//! and explicit integer widths is the cheapest way to find out which ones were.
//!
//! The conformance suite runs both against the same committed file and compares the output line
//! by line. Neither is allowed to be the reference: they either agree or the suite fails.
//!
//! WHAT THIS IS NOT. It is a standalone binary reading a file and writing to stdout. There is no
//! Python binding, no extension module and no wheel: the two implementations meet at a file and
//! a byte stream, which is the only interface that does not favour one of them.

use std::env;
use std::fs::File;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::process::ExitCode;

/// One event, reduced to what the normalised series carries.
struct Event {
    offset: i64,
    topic: String,
    domain: String,
    kind: String,
}

/// The columns this expects, in order. Checked against the header rather than assumed, because a
/// column inserted upstream would otherwise shift every field silently.
const EXPECTED_HEADER: &str = "offset,partition,topic,event_id,domain,kind,iso_instant,unix_second,revision_old,revision_new";

fn parse(line: &str) -> Result<Event, String> {
    let fields: Vec<&str> = line.split(',').collect();
    if fields.len() != 10 {
        return Err(format!("expected 10 fields, found {}", fields.len()));
    }
    let offset = fields[0]
        .parse::<i64>()
        .map_err(|error| format!("offset {:?}: {}", fields[0], error))?;
    Ok(Event {
        offset,
        topic: fields[2].to_string(),
        domain: fields[4].to_string(),
        kind: fields[5].to_string(),
    })
}

fn run(path: &str) -> Result<usize, String> {
    let file = File::open(path).map_err(|error| format!("{}: {}", path, error))?;
    let mut lines = BufReader::new(file).lines();

    match lines.next() {
        Some(Ok(header)) if header.trim_end() == EXPECTED_HEADER => {}
        Some(Ok(header)) => {
            return Err(format!(
                "the header has moved.\n  expected {}\n  found    {}",
                EXPECTED_HEADER,
                header.trim_end()
            ))
        }
        Some(Err(error)) => return Err(error.to_string()),
        None => return Err("the file is empty".to_string()),
    }

    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());
    let mut written = 0usize;

    for line in lines {
        let line = line.map_err(|error| error.to_string())?;
        if line.trim().is_empty() {
            continue;
        }
        let event = parse(&line)?;
        // The normalised form, and it has to match the Python one byte for byte. Anything
        // clever here (padding, locale-aware formatting, a float) is a difference the
        // conformance suite would find and nobody would want.
        // A BROKEN PIPE IS NOT AN ERROR HERE. The README shows this piped into `head`, which
        // closes the pipe and would otherwise make a working command print a failure. Rust
        // ignores SIGPIPE by default, so the case has to be handled rather than inherited.
        if let Err(error) = writeln!(
            out, "{}|{}|{}|{}", event.offset, event.topic, event.domain, event.kind
        ) {
            if error.kind() == io::ErrorKind::BrokenPipe {
                return Ok(written);
            }
            return Err(error.to_string());
        }
        written += 1;
    }
    out.flush().map_err(|error| error.to_string())?;
    Ok(written)
}

fn main() -> ExitCode {
    let arguments: Vec<String> = env::args().collect();
    let Some(path) = arguments.get(1) else {
        eprintln!("usage: queuez-decoder <session.csv>");
        return ExitCode::from(2);
    };
    match run(path) {
        Ok(_) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{}", error);
            ExitCode::FAILURE
        }
    }
}
