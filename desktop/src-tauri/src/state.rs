use std::sync::Mutex;

use crate::discovery::Layout;
use crate::prefs::Prefs;

#[derive(Default)]
pub struct Shell {
    pub layout: Mutex<Option<Layout>>,
    pub prefs: Mutex<Prefs>,
    pub busy: Mutex<bool>,
    pub pid: Mutex<Option<u32>>,
    pub phase: Mutex<Option<String>>,
    pub quit_after_stop: Mutex<bool>,
}

impl Shell {
    pub fn layout(&self) -> Result<Layout, String> {
        self.layout
            .lock()
            .ok()
            .and_then(|guard| guard.clone())
            .ok_or_else(|| "Horus has not found its files yet.".to_string())
    }
}
