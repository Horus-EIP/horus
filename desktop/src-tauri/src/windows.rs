use serde_json::json;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use url::Url;

use crate::prefs::OnClose;
use crate::runner;
use crate::state::Shell;

pub const STATUS_LABEL: &str = "status";
pub const APP_LABEL: &str = "main";

pub const WEB_URL: &str = "http://localhost:3000";

const HARDEN_SCRIPT: &str = r#"
(function () {
  document.addEventListener('contextmenu', function (event) {
    event.preventDefault();
  }, true);
  document.addEventListener('keydown', function (event) {
    var key = (event.key || '').toLowerCase();
    var blocked =
      key === 'f12' ||
      ((event.ctrlKey || event.metaKey) && event.shiftKey &&
        (key === 'i' || key === 'j' || key === 'c')) ||
      ((event.ctrlKey || event.metaKey) && key === 'u');
    if (blocked) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);
})();
"#;

pub fn build_status(app: &AppHandle) -> Result<(), String> {
    let window = WebviewWindowBuilder::new(app, STATUS_LABEL, WebviewUrl::App("index.html".into()))
        .title("Horus")
        .inner_size(820.0, 660.0)
        .min_inner_size(640.0, 520.0)
        .center()
        .resizable(true)
        .build()
        .map_err(|e| format!("could not create the status window: {}", e))?;

    let handle = app.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            if handle.get_webview_window(APP_LABEL).is_some() {
                api.prevent_close();
                if let Some(status) = handle.get_webview_window(STATUS_LABEL) {
                    let _ = status.hide();
                }
            }
        }
    });
    Ok(())
}

pub fn show_status(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(STATUS_LABEL) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn hide_status(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(STATUS_LABEL) {
        let _ = window.hide();
    }
}

pub fn open_app_window(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(window) = handle.get_webview_window(APP_LABEL) {
            let _ = window.show();
            let _ = window.set_focus();
            hide_status(&handle);
            return;
        }
        match create_app_window(&handle) {
            Ok(()) => hide_status(&handle),
            Err(err) => {
                runner::emit_internal(&handle, format!("could not open the app window: {}", err));
                show_status(&handle);
            }
        }
    });
}

fn create_app_window(app: &AppHandle) -> Result<(), String> {
    let url = Url::parse(WEB_URL).map_err(|e| format!("{} is not a valid URL: {}", WEB_URL, e))?;
    let window = WebviewWindowBuilder::new(app, APP_LABEL, WebviewUrl::External(url))
        .title("Horus")
        .inner_size(1440.0, 900.0)
        .min_inner_size(1024.0, 720.0)
        .center()
        .resizable(true)
        .initialization_script(HARDEN_SCRIPT)
        .build()
        .map_err(|e| format!("{}", e))?;

    let handle = app.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            match close_action(&handle) {
                CloseAction::Quit => handle.exit(0),
                CloseAction::Shutdown => {
                    stop_and_quit(&handle);
                }
                CloseAction::Ask => {
                    api.prevent_close();
                    show_status(&handle);
                    runner::emit(&handle, json!({ "kind": "close-requested" }));
                }
            }
        }
    });
    Ok(())
}

enum CloseAction {
    Quit,
    Shutdown,
    Ask,
}

fn close_action(app: &AppHandle) -> CloseAction {
    let remembered = app
        .state::<Shell>()
        .prefs
        .lock()
        .ok()
        .and_then(|prefs| prefs.on_close);
    match remembered {
        Some(OnClose::Leave) => CloseAction::Quit,
        Some(OnClose::Shutdown) => CloseAction::Shutdown,
        None => CloseAction::Ask,
    }
}

fn close_app_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(APP_LABEL) {
        let _ = window.destroy();
    }
}

pub fn stop_now(app: &AppHandle, quit_after: bool) -> Result<(), String> {
    close_app_window(app);
    run_stop(app, quit_after)
}

pub fn stop_and_quit(app: &AppHandle) {
    if let Err(err) = run_stop(app, true) {
        runner::emit_internal(app, err);
        app.exit(0);
    }
}

pub fn restart_now(app: &AppHandle) -> Result<(), String> {
    close_app_window(app);
    show_status(app);
    runner::spawn(app, "restarting", &["--restart", "--json-events"])
}

fn run_stop(app: &AppHandle, quit_after: bool) -> Result<(), String> {
    if quit_after {
        if let Ok(mut guard) = app.state::<Shell>().quit_after_stop.lock() {
            *guard = true;
        }
    }
    show_status(app);
    runner::spawn(app, "stopping", &["--stop", "--json-events"])
}
