use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use serde::Serialize;

const ROOT_MARKER: &[&str] = &["installer", "horus_install.py"];

const REPO_MARKER: &[&str] = &["src", "infra", "docker-compose.yml"];

const HOME_SUBDIRS: &[&str] = &["", "Downloads", "Desktop", "Documents", "Horus"];

const BUNDLE_PREFIX: &str = "Horus-Beta";

const MAX_ANCESTORS: usize = 8;

#[derive(Clone, Debug, Serialize)]
pub struct Layout {
    pub root: PathBuf,
    pub repo: PathBuf,
    pub script: PathBuf,
    pub log: PathBuf,
    pub profile: PathBuf,
    pub env_file: PathBuf,
    pub python: Vec<String>,
}

impl Layout {
    pub fn is_installed(&self) -> bool {
        self.env_file.is_file()
    }
}

fn join(base: &Path, parts: &[&str]) -> PathBuf {
    let mut path = base.to_path_buf();
    for part in parts {
        path.push(part);
    }
    path
}

pub fn is_root(candidate: &Path) -> bool {
    join(candidate, ROOT_MARKER).is_file()
}

pub fn find_repo(root: &Path) -> Option<PathBuf> {
    let nested = root.join("horus");
    if join(&nested, REPO_MARKER).is_file() {
        return Some(nested);
    }
    if join(root, REPO_MARKER).is_file() {
        return Some(root.to_path_buf());
    }
    None
}

fn home_dir() -> Option<PathBuf> {
    let key = if cfg!(windows) { "USERPROFILE" } else { "HOME" };
    std::env::var_os(key)
        .map(PathBuf::from)
        .filter(|p| p.is_dir())
}

fn push_ancestors(out: &mut Vec<PathBuf>, start: Option<PathBuf>) {
    if let Some(start) = start {
        for ancestor in start.ancestors().take(MAX_ANCESTORS) {
            out.push(ancestor.to_path_buf());
        }
    }
}

pub fn candidate_roots(saved: Option<PathBuf>) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = Vec::new();

    if let Some(env_root) = std::env::var_os("HORUS_HOME").map(PathBuf::from) {
        out.push(env_root);
    }
    if let Some(saved) = saved {
        out.push(saved);
    }

    push_ancestors(
        &mut out,
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(Path::to_path_buf)),
    );
    push_ancestors(&mut out, std::env::current_dir().ok());

    if let Some(home) = home_dir() {
        for sub in HOME_SUBDIRS {
            let dir = if sub.is_empty() {
                home.clone()
            } else {
                home.join(sub)
            };
            if !dir.is_dir() {
                continue;
            }
            out.push(dir.clone());
            if let Ok(entries) = std::fs::read_dir(&dir) {
                let mut found: Vec<PathBuf> = entries
                    .flatten()
                    .map(|e| e.path())
                    .filter(|p| p.is_dir())
                    .filter(|p| {
                        p.file_name()
                            .and_then(|n| n.to_str())
                            .map(|n| n.starts_with(BUNDLE_PREFIX))
                            .unwrap_or(false)
                    })
                    .collect();
                found.sort();
                out.append(&mut found);
            }
        }
    }

    let mut seen: Vec<PathBuf> = Vec::new();
    out.retain(|p| {
        if seen.contains(p) {
            false
        } else {
            seen.push(p.clone());
            true
        }
    });
    out
}

pub fn find_root(saved: Option<PathBuf>) -> Option<PathBuf> {
    candidate_roots(saved).into_iter().find(|p| is_root(p))
}

fn python_candidates() -> Vec<Vec<String>> {
    let names: &[&[&str]] = if cfg!(windows) {
        &[&["py", "-3"], &["python"], &["python3"]]
    } else {
        &[
            &["python3.13"],
            &["python3.12"],
            &["python3.11"],
            &["python3"],
            &["python"],
        ]
    };
    names
        .iter()
        .map(|parts| parts.iter().map(|s| s.to_string()).collect())
        .collect()
}

fn python_works(cmd: &[String]) -> bool {
    let mut command = Command::new(&cmd[0]);
    command.args(&cmd[1..]);
    command.arg("-c");
    command.arg("import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)");
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    no_console(&mut command);
    matches!(command.status(), Ok(status) if status.success())
}

pub fn find_python() -> Option<Vec<String>> {
    python_candidates()
        .into_iter()
        .find(|cmd| python_works(cmd))
}

pub fn no_console(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(not(windows))]
    {
        let _ = command;
    }
}

pub fn layout_for(root: PathBuf, python: Vec<String>) -> Option<Layout> {
    let repo = find_repo(&root)?;
    Some(Layout {
        script: join(&root, ROOT_MARKER),
        log: root.join("install-log.txt"),
        profile: root.join("horus-profile.json"),
        env_file: repo.join("src").join("infra").join(".env"),
        repo,
        root,
        python,
    })
}
