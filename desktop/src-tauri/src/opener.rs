use std::path::Path;
use std::process::{Command, Stdio};

use crate::discovery::no_console;

fn spawn_detached(program: &str, args: &[&str]) -> Result<(), String> {
    let mut command = Command::new(program);
    command.args(args);
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    no_console(&mut command);
    command
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("could not run {}: {}", program, e))
}

pub fn open(target: &str) -> Result<(), String> {
    if cfg!(windows) {
        spawn_detached("cmd", &["/C", "start", "", target])
    } else if cfg!(target_os = "macos") {
        spawn_detached("open", &[target])
    } else {
        spawn_detached("xdg-open", &[target])
    }
}

pub fn open_file(path: &Path, what: &str) -> Result<(), String> {
    if !path.exists() {
        return Err(format!(
            "There is no {} yet - it is written by the installer. Expected it at:\n{}",
            what,
            path.display()
        ));
    }
    open(&path.to_string_lossy())
}
