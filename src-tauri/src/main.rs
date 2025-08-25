#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    stock_mcpilot::run()
}

mod stock_mcpilot {
    pub fn run() {
        tauri::Builder::default()
            .run(tauri::generate_context!())
            .expect("error while running tauri application");
    }
}
