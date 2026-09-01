use std::io::{BufRead, BufReader, Read};
use std::process::{Command, Stdio};
use std::thread;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};

use crate::discovery::no_console;
use crate::state::Shell;
use crate::windows;

pub const EVENT_CHANNEL: &str = "horus://event";

const EVENT_PREFIX: &str = "@@HORUS ";

pub fn emit(app: &AppHandle, payload: Value) {
    let _ = app.emit(EVENT_CHANNEL, payload);
}

pub fn emit_internal(app: &AppHandle, text: impl Into<String>) {
    emit(app, json!({ "kind": "internal", "text": text.into() }));
}

pub fn emit_error(app: &AppHandle, text: impl Into<String>) {
    emit(app, json!({ "kind": "error", "text": text.into() }));
}

fn emit_output(app: &AppHandle, text: String) {
    emit(app, json!({ "kind": "output", "text": text }));
}

fn for_each_line<R: Read>(source: R, mut on_line: impl FnMut(String)) {
    let mut reader = BufReader::new(source);
    let mut bytes: Vec<u8> = Vec::with_capacity(512);
    loop {
        bytes.clear();
        match reader.read_until(b'\n', &mut bytes) {
            Ok(0) => return,
            Ok(_) => {
                while matches!(bytes.last(), Some(b'\n') | Some(b'\r')) {
                    bytes.pop();
                }
                on_line(String::from_utf8_lossy(&bytes).into_owned());
            }
            Err(_) => return,
        }
    }
}

fn clear_busy(shell: &Shell) {
    if let Ok(mut busy) = shell.busy.lock() {
        *busy = false;
    }
    if let Ok(mut phase) = shell.phase.lock() {
        *phase = None;
    }
    if let Ok(mut pid) = shell.pid.lock() {
        *pid = None;
    }
}

pub fn spawn(app: &AppHandle, phase: &str, args: &[&str]) -> Result<(), String> {
    let shell = app.state::<Shell>();
    let layout = shell.layout()?;

    {
        let mut busy = shell
            .busy
            .lock()
            .map_err(|_| "the shell is in a bad state; reopen Horus".to_string())?;
        if *busy {
            return Err("Horus is already working on that. Give it a moment.".into());
        }
        *busy = true;
    }
    if let Ok(mut current) = shell.phase.lock() {
        *current = Some(phase.to_string());
    }

    let mut command = Command::new(&layout.python[0]);
    command.args(&layout.python[1..]);
    command.arg(&layout.script);
    command.args(args);
    command.current_dir(&layout.root);
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    command.env("PYTHONUNBUFFERED", "1");
    command.env("NO_COLOR", "1");
    no_console(&mut command);

    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(e) => {
            clear_busy(&shell);
            return Err(format!(
                "Could not run Python.\n\n{} {}\n\n{}",
                layout.python.join(" "),
                layout.script.display(),
                e
            ));
        }
    };

    if let Ok(mut pid) = shell.pid.lock() {
        *pid = Some(child.id());
    }

    emit(app, json!({ "kind": "phase", "phase": phase }));

    if let Some(stdout) = child.stdout.take() {
        let handle = app.clone();
        thread::spawn(move || {
            for_each_line(stdout, |line| emit_output(&handle, line));
        });
    }
    if let Some(stderr) = child.stderr.take() {
        let handle = app.clone();
        thread::spawn(move || {
            for_each_line(stderr, |line| handle_stderr_line(&handle, line));
        });
    }

    let handle = app.clone();
    thread::spawn(move || {
        let code = match child.wait() {
            Ok(status) => status.code().unwrap_or(-1),
            Err(_) => -1,
        };
        let shell = handle.state::<Shell>();
        let phase = shell
            .phase
            .lock()
            .ok()
            .and_then(|guard| guard.clone())
            .unwrap_or_default();
        clear_busy(&shell);
        let quit_after = shell
            .quit_after_stop
            .lock()
            .map(|guard| *guard)
            .unwrap_or(false);

        emit(
            &handle,
            json!({ "kind": "finished", "code": code, "phase": phase }),
        );

        if quit_after {
            if let Ok(mut guard) = shell.quit_after_stop.lock() {
                *guard = false;
            }
            handle.exit(0);
        }
    });

    Ok(())
}

fn handle_stderr_line(app: &AppHandle, line: String) {
    let parsed: Option<Value> = line
        .strip_prefix(EVENT_PREFIX)
        .and_then(|rest| serde_json::from_str::<Value>(rest).ok());

    let Some(data) = parsed else {
        emit_output(app, line);
        return;
    };
    if data.get("event").and_then(Value::as_str) == Some("ready") {
        windows::open_app_window(app);
    }
    emit(app, json!({ "kind": "installer", "data": data }));
}

pub fn kill(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let pid = shell.pid.lock().ok().and_then(|guard| *guard);
    let Some(pid) = pid else { return };

    let pid_text = pid.to_string();
    let mut command = if cfg!(windows) {
        let mut c = Command::new("taskkill");
        c.args(["/PID", pid_text.as_str(), "/F"]);
        c
    } else {
        let mut c = Command::new("kill");
        c.args(["-TERM", pid_text.as_str()]);
        c
    };
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    no_console(&mut command);
    let _ = command.status();
}
