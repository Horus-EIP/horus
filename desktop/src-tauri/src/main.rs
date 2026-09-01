#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod appmenu;
mod discovery;
mod opener;
mod prefs;
mod runner;
mod state;
mod windows;

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};

use prefs::OnClose;
use state::Shell;

const VERSION: &str = env!("CARGO_PKG_VERSION");

#[tauri::command]
fn bootstrap(app: AppHandle) -> Value {
    let shell = app.state::<Shell>();

    let saved = shell.prefs.lock().ok().and_then(|prefs| prefs.root.clone());

    let Some(root) = discovery::find_root(saved.clone()) else {
        return json!({
            "state": "not-found",
            "version": VERSION,
            "root": saved.map(|p| p.to_string_lossy().into_owned()).unwrap_or_default(),
        });
    };

    let Some(python) = discovery::find_python() else {
        return json!({
            "state": "no-python",
            "version": VERSION,
            "root": root.to_string_lossy(),
        });
    };

    let Some(layout) = discovery::layout_for(root.clone(), python) else {
        return json!({
            "state": "not-found",
            "version": VERSION,
            "root": root.to_string_lossy(),
        });
    };

    let installed = layout.is_installed();
    let payload = json!({
        "state": if installed { "ready" } else { "not-installed" },
        "version": VERSION,
        "root": layout.root.to_string_lossy(),
        "repo": layout.repo.to_string_lossy(),
        "python": layout.python.join(" "),
        "log": layout.log.to_string_lossy(),
        "profile": layout.profile.to_string_lossy(),
        "web_url": windows::WEB_URL,
    });

    if let Ok(mut current) = shell.layout.lock() {
        *current = Some(layout);
    }
    payload
}

#[tauri::command]
fn set_root(app: AppHandle, path: String) -> Result<(), String> {
    let candidate = std::path::PathBuf::from(path.trim());
    if !candidate.is_dir() {
        return Err(format!("There is no folder at {}", candidate.display()));
    }
    if !discovery::is_root(&candidate) {
        return Err(format!(
            "{} does not look like the Horus folder - it has no installer folder \
             inside it. Pick the folder that holds README-FIRST.txt.",
            candidate.display()
        ));
    }
    if discovery::find_repo(&candidate).is_none() {
        return Err(format!(
            "{} has an installer but no Horus source in it. This usually means \
             the ZIP was only partly extracted; extract all of it and try again.",
            candidate.display()
        ));
    }

    let shell = app.state::<Shell>();
    let mut prefs = shell
        .prefs
        .lock()
        .map_err(|_| "the shell is in a bad state; reopen Horus".to_string())?;
    prefs.root = Some(candidate);
    if let Err(message) = prefs::save(&prefs) {
        runner::emit_internal(&app, format!("could not remember that folder: {}", message));
    }
    Ok(())
}

#[tauri::command]
fn start_stack(app: AppHandle) -> Result<(), String> {
    runner::spawn(&app, "starting", &["--start", "--json-events"])
}

#[tauri::command]
fn restart_stack(app: AppHandle) -> Result<(), String> {
    windows::restart_now(&app)
}

#[tauri::command]
fn stop_stack(app: AppHandle, then_quit: bool) -> Result<(), String> {
    windows::stop_now(&app, then_quit)
}

#[tauri::command]
fn open_path(app: AppHandle, which: String) -> Result<(), String> {
    if which == "web" {
        return opener::open(windows::WEB_URL);
    }
    let layout = app.state::<Shell>().layout()?;
    match which.as_str() {
        "log" => opener::open_file(&layout.log, "install log"),
        "profile" => opener::open_file(&layout.profile, "hardware profile"),
        "bundle" => opener::open(&layout.root.to_string_lossy()),
        other => Err(format!("nothing known as {:?} to open", other)),
    }
}

#[tauri::command]
fn show_app_window(app: AppHandle) {
    windows::open_app_window(&app);
}

#[tauri::command]
fn close_decision(app: AppHandle, shutdown: bool, remember: bool) {
    if remember {
        if let Ok(mut prefs) = app.state::<Shell>().prefs.lock() {
            prefs.on_close = Some(if shutdown {
                OnClose::Shutdown
            } else {
                OnClose::Leave
            });
            if let Err(message) = prefs::save(&prefs) {
                runner::emit_internal(&app, format!("could not remember that: {}", message));
            }
        }
    }
    if !shutdown {
        app.exit(0);
        return;
    }
    if let Err(err) = windows::stop_now(&app, true) {
        runner::emit_internal(&app, err);
        app.exit(0);
    }
}

#[tauri::command]
fn close_decision_cancel(app: AppHandle) {
    windows::open_app_window(&app);
}

#[tauri::command]
fn cancel_and_quit(app: AppHandle) {
    runner::kill(&app);
    app.exit(0);
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

fn main() {
    tauri::Builder::default()
        .manage(Shell::default())
        .invoke_handler(tauri::generate_handler![
            bootstrap,
            set_root,
            start_stack,
            restart_stack,
            stop_stack,
            open_path,
            show_app_window,
            close_decision,
            close_decision_cancel,
            cancel_and_quit,
            quit_app,
        ])
        .setup(|app| {
            let handle = app.handle().clone();

            if let Ok(mut prefs) = app.state::<Shell>().prefs.lock() {
                *prefs = prefs::load();
            }

            if let Err(message) = appmenu::install(&handle) {
                runner::emit_internal(&handle, format!("no application menu: {}", message));
            }

            app.on_menu_event(|app, event| {
                appmenu::handle(app, event.id().as_ref());
            });

            windows::build_status(&handle)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Horus could not start its window system");
}
