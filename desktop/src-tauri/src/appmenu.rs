use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{AppHandle, Manager};

use crate::opener;
use crate::runner;
use crate::state::Shell;
use crate::windows;

pub fn install(app: &AppHandle) -> Result<(), String> {
    let show_app = item(app, "menu-show-app", "Show the Horus Window")?;
    let show_status = item(app, "menu-show-status", "Show Status and Controls")?;
    let browser = item(app, "menu-browser", "Open in a Browser")?;
    let restart = item(app, "menu-restart", "Restart Horus")?;
    let stop = item(app, "menu-stop", "Stop Horus")?;
    let log = item(app, "menu-log", "Open install-log.txt")?;
    let profile = item(app, "menu-profile", "Open horus-profile.json")?;
    let folder = item(app, "menu-folder", "Open the Horus Folder")?;

    let horus = Submenu::with_items(
        app,
        "Horus",
        true,
        &[
            &show_app,
            &show_status,
            &browser,
            &sep(app)?,
            &restart,
            &stop,
            &sep(app)?,
            &log,
            &profile,
            &folder,
            &sep(app)?,
            &PredefinedMenuItem::quit(app, None).map_err(err)?,
        ],
    )
    .map_err(err)?;

    let edit = Submenu::with_items(
        app,
        "Edit",
        true,
        &[
            &PredefinedMenuItem::undo(app, None).map_err(err)?,
            &PredefinedMenuItem::redo(app, None).map_err(err)?,
            &sep(app)?,
            &PredefinedMenuItem::cut(app, None).map_err(err)?,
            &PredefinedMenuItem::copy(app, None).map_err(err)?,
            &PredefinedMenuItem::paste(app, None).map_err(err)?,
            &PredefinedMenuItem::select_all(app, None).map_err(err)?,
        ],
    )
    .map_err(err)?;

    let menu = Menu::with_items(app, &[&horus, &edit]).map_err(err)?;
    let _previous = app.set_menu(menu).map_err(err)?;
    Ok(())
}

fn err(e: tauri::Error) -> String {
    e.to_string()
}

fn item(app: &AppHandle, id: &str, text: &str) -> Result<MenuItem<tauri::Wry>, String> {
    MenuItem::with_id(app, id, text, true, None::<&str>).map_err(err)
}

fn sep(app: &AppHandle) -> Result<PredefinedMenuItem<tauri::Wry>, String> {
    PredefinedMenuItem::separator(app).map_err(err)
}

pub fn handle(app: &AppHandle, id: &str) {
    match id {
        "menu-show-app" => windows::open_app_window(app),
        "menu-show-status" => windows::show_status(app),
        "menu-browser" => report(app, opener::open(windows::WEB_URL)),
        "menu-restart" => report(app, windows::restart_now(app)),
        "menu-stop" => report(app, windows::stop_now(app, false)),
        "menu-log" => with_layout(app, |app, layout| {
            report(app, opener::open_file(&layout.log, "install log"))
        }),
        "menu-profile" => with_layout(app, |app, layout| {
            report(app, opener::open_file(&layout.profile, "hardware profile"))
        }),
        "menu-folder" => with_layout(app, |app, layout| {
            report(app, opener::open(&layout.root.to_string_lossy()))
        }),
        _ => {}
    }
}

fn with_layout(app: &AppHandle, action: impl FnOnce(&AppHandle, crate::discovery::Layout)) {
    match app.state::<Shell>().layout() {
        Ok(layout) => action(app, layout),
        Err(message) => report(app, Err(message)),
    }
}

fn report(app: &AppHandle, outcome: Result<(), String>) {
    if let Err(message) = outcome {
        windows::show_status(app);
        runner::emit_error(app, message);
    }
}
