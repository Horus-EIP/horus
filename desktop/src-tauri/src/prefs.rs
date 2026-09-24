use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum OnClose {
    Leave,
    Shutdown,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Prefs {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub root: Option<PathBuf>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub on_close: Option<OnClose>,
}

fn config_dir() -> Option<PathBuf> {
    if cfg!(windows) {
        return std::env::var_os("APPDATA").map(|base| PathBuf::from(base).join("Horus"));
    }
    if cfg!(target_os = "macos") {
        return std::env::var_os("HOME").map(|home| {
            PathBuf::from(home)
                .join("Library")
                .join("Application Support")
                .join("Horus")
        });
    }
    if let Some(xdg) = std::env::var_os("XDG_CONFIG_HOME") {
        let path = PathBuf::from(xdg);
        if path.is_absolute() {
            return Some(path.join("horus"));
        }
    }
    std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config").join("horus"))
}

fn path() -> Option<PathBuf> {
    config_dir().map(|dir| dir.join("desktop.json"))
}

pub fn load() -> Prefs {
    let Some(file) = path() else {
        return Prefs::default();
    };
    let Ok(text) = std::fs::read_to_string(&file) else {
        return Prefs::default();
    };
    serde_json::from_str(&text).unwrap_or_default()
}

pub fn save(prefs: &Prefs) -> Result<(), String> {
    let file = path().ok_or_else(|| {
        "no configuration directory on this system (neither APPDATA nor HOME is set)".to_string()
    })?;
    if let Some(dir) = file.parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("{}: {}", dir.display(), e))?;
    }
    let text = serde_json::to_string_pretty(prefs)
        .map_err(|e| format!("could not serialise preferences: {}", e))?;
    std::fs::write(&file, text + "\n").map_err(|e| format!("{}: {}", file.display(), e))
}
