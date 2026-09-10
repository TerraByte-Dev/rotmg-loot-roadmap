// RotMG Loot Roadmap - Tauri 2 desktop shell.
//
// The shell owns three things the standalone roadmap.html cannot do for itself:
// always-on-top with a pin toggle, window opacity, and remembering where the
// window was - without stranding it on a monitor that has since been unplugged.
//
// Everything else - all data, all rendering, all persistence of kits and tracked
// items - stays in the page, exactly as it is in the file people already have.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    AppHandle, Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder,
};
use tauri_plugin_window_state::{StateFlags, WindowExt};

/// Geometry only.
///
/// VISIBLE is excluded because the window is created hidden and shown by hand
/// after the monitor guard has run - restoring visibility would flash it onto a
/// phantom monitor before we could rescue it. FULLSCREEN and DECORATIONS are
/// excluded because an always-on-top overlay that comes back fullscreen, or
/// chromeless with no way to close it, is a support call.
fn state_flags() -> StateFlags {
    StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED
}

// ---------------------------------------------------------------------------
// Monitor guard
// ---------------------------------------------------------------------------

/// A window is only "recoverable" if a grabbable slice of it lands on a monitor
/// that is currently attached. One pixel on-screen is as lost as none: the user
/// cannot drag what they cannot click.
const MIN_VISIBLE_W: i32 = 160;
const MIN_VISIBLE_H: i32 = 48;

fn is_recoverable(win: &WebviewWindow) -> bool {
    let (Ok(pos), Ok(size)) = (win.outer_position(), win.outer_size()) else {
        return false;
    };
    let Ok(monitors) = win.available_monitors() else {
        return false;
    };
    if monitors.is_empty() {
        return false;
    }

    let (wl, wt) = (pos.x, pos.y);
    let (wr, wb) = (pos.x + size.width as i32, pos.y + size.height as i32);

    // A tiny window is allowed to be tiny; don't demand more overlap than it has.
    let need_w = MIN_VISIBLE_W.min(size.width as i32);
    let need_h = MIN_VISIBLE_H.min(size.height as i32);

    monitors.iter().any(|m| {
        let (mp, ms) = (m.position(), m.size());
        let (ml, mt) = (mp.x, mp.y);
        let (mr, mb) = (mp.x + ms.width as i32, mp.y + ms.height as i32);
        let ow = (wr.min(mr) - wl.max(ml)).max(0);
        let oh = (wb.min(mb) - wt.max(mt)).max(0);
        ow >= need_w && oh >= need_h
    })
}

/// Put the window back on the primary monitor, clamped to fit it. Called only
/// when `is_recoverable` said no - a saved 3840x2160 geometry from a docked
/// setup does not fit the 1920x1080 laptop panel it comes home to.
fn rescue(win: &WebviewWindow) -> tauri::Result<()> {
    if win.is_maximized().unwrap_or(false) {
        // Maximized state is relative to a monitor that may no longer exist.
        let _ = win.unmaximize();
    }

    let Some(primary) = win.primary_monitor()? else {
        return win.center();
    };
    let (mp, ms) = (primary.position(), primary.size());
    let cur = win.outer_size()?;

    let w = cur.width.min(ms.width.saturating_sub(96)).max(320);
    let h = cur.height.min(ms.height.saturating_sub(96)).max(240);

    win.set_size(PhysicalSize::new(w, h))?;
    win.set_position(PhysicalPosition::new(
        mp.x + ((ms.width.saturating_sub(w)) / 2) as i32,
        mp.y + ((ms.height.saturating_sub(h)) / 2) as i32,
    ))
}

// ---------------------------------------------------------------------------
// Opacity
// ---------------------------------------------------------------------------
//
// Tauri 2 has no set_opacity - verified against tauri 2.11.5, on the Windows
// target build of the docs where the cfg(windows) methods are visible. On
// Windows the way to do this is a layered top-level window.
//
// WS_EX_LAYERED is added only while the window is actually translucent and
// removed at 100%, so the normal case pays nothing for the feature.

#[cfg(windows)]
fn apply_opacity(win: &WebviewWindow, alpha: f64) -> Result<(), String> {
    use windows::Win32::Foundation::COLORREF;
    use windows::Win32::UI::WindowsAndMessaging::{
        GetWindowLongPtrW, SetLayeredWindowAttributes, SetWindowLongPtrW, GWL_EXSTYLE, LWA_ALPHA,
        WINDOW_EX_STYLE, WS_EX_LAYERED,
    };

    // Below ~30% the window is unusable and looks broken rather than subtle.
    let a = alpha.clamp(0.30, 1.0);
    let hwnd = win.hwnd().map_err(|e| e.to_string())?;

    unsafe {
        let cur = WINDOW_EX_STYLE(GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32);

        if a >= 1.0 {
            if (cur & WS_EX_LAYERED).0 != 0 {
                SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (cur & !WS_EX_LAYERED).0 as isize);
            }
            return Ok(());
        }

        if (cur & WS_EX_LAYERED).0 == 0 {
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (cur | WS_EX_LAYERED).0 as isize);
        }
        SetLayeredWindowAttributes(hwnd, COLORREF(0), (a * 255.0).round() as u8, LWA_ALPHA)
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg(not(windows))]
fn apply_opacity(_win: &WebviewWindow, _alpha: f64) -> Result<(), String> {
    Err("window opacity is Windows-only".into())
}

/// `invoke("set_window_opacity", { alpha: 0.85 })`
///
/// Not listed in capabilities/default.json on purpose: Tauri 2 applies the ACL to
/// plugin commands, and to app commands only when the app ships its own
/// permissions manifest. This app does not, so its own commands are reachable.
#[tauri::command]
fn set_window_opacity(window: WebviewWindow, alpha: f64) -> Result<(), String> {
    apply_opacity(&window, alpha)
}

/// Put the window in the middle of the PRIMARY monitor.
///
/// Only used on a first run, where there is no saved geometry to honour. Tauri's
/// `center: true` centres on whichever monitor it thinks the window is on, and on a
/// stacked multi-monitor desktop that came out as the display ABOVE the primary - the
/// app opened somewhere the user was not looking.
fn center_on_primary(win: &WebviewWindow) -> tauri::Result<()> {
    let Some(primary) = win.primary_monitor()? else {
        return win.center();
    };
    let (mp, ms) = (primary.position(), primary.size());
    let cur = win.outer_size()?;

    // The configured size is in logical pixels; on a scaled display it can come out
    // taller than the screen it is being centred on. 1180x860 became 1493x1085 on a
    // 1920x1080 panel, so the title bar sat off the top edge. Fit first, then centre.
    let w = cur.width.min(ms.width.saturating_sub(80)).max(640);
    let h = cur.height.min(ms.height.saturating_sub(80)).max(400);
    if w != cur.width || h != cur.height {
        win.set_size(PhysicalSize::new(w, h))?;
    }

    win.set_position(PhysicalPosition::new(
        mp.x + ((ms.width.saturating_sub(w)) / 2) as i32,
        mp.y + ((ms.height.saturating_sub(h)) / 2) as i32,
    ))
}

// ---------------------------------------------------------------------------
// The overlay widget
// ---------------------------------------------------------------------------
//
// A second, small, chromeless, always-on-top window that loads the SAME page with
// #widget on the URL. The page sees the hash and renders a compact tracked-items
// list instead of the full app, so there is no second frontend to keep in sync.
//
// Opacity lives here rather than on the main window on purpose: a see-through main
// window is unreadable, while a see-through overlay beside the game is the point.

#[tauri::command]
fn open_widget(app: AppHandle, alpha: f64) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("widget") {
        let _ = w.show();
        let _ = w.set_focus();
        let _ = apply_opacity(&w, alpha);
        return Ok(());
    }

    // A URL fragment does not survive WebviewUrl::App - "index.html#widget" is resolved as
    // a PATH, the custom protocol finds no such file, and the window renders blank white.
    // An init script runs before the document and carries the mode with no URL parsing.
    let w = WebviewWindowBuilder::new(&app, "widget", WebviewUrl::App("index.html".into()))
        .initialization_script("window.__ROTMG_WIDGET__ = true;")
        .title("Loot Roadmap - overlay")
        .inner_size(340.0, 460.0)
        .min_inner_size(240.0, 180.0)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(true)
        .build()
        .map_err(|e| e.to_string())?;

    // Opacity has to wait for the window to exist; setting it on the builder is not
    // a thing, and a layered style applied before first paint can show as a flash.
    let _ = apply_opacity(&w, alpha);
    let _ = w.show();
    Ok(())
}

/// `invoke("set_widget_opacity", { alpha: 0.85 })` - a no-op when the overlay is
/// not open, because the page keeps the value and passes it to `open_widget`.
#[tauri::command]
fn set_widget_opacity(app: AppHandle, alpha: f64) -> Result<(), String> {
    match app.get_webview_window("widget") {
        Some(w) => apply_opacity(&w, alpha),
        None => Ok(()),
    }
}

// ---------------------------------------------------------------------------

fn main() {
    tauri::Builder::default()
        // Closing the main window quits. Without this the chromeless overlay keeps the
        // process alive with no taskbar entry and no way to close it - it survived the
        // app being shut down and had to be killed from Task Manager.
        .on_window_event(|window, event| {
            if window.label() == "main" && matches!(event, tauri::WindowEvent::Destroyed) {
                window.app_handle().exit(0);
            }
        })
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(
            tauri_plugin_window_state::Builder::new()
                .with_state_flags(state_flags())
                // Do not let the plugin restore on window-ready. We restore in
                // setup() so the guard can run between "restored" and "shown".
                .skip_initial_state("main")
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            set_window_opacity,
            set_widget_opacity,
            open_widget
        ])
        .setup(|app| {
            let win = app
                .get_webview_window("main")
                .expect("window 'main' is declared in tauri.conf.json");

            // Is this a first run? Ask before restore_state creates the file.
            let first_run = app
                .path()
                .app_config_dir()
                .map(|d| !d.join(".window-state.json").exists())
                .unwrap_or(true);

            // Order matters: restore -> validate -> rescue -> show.
            let _ = win.restore_state(state_flags());

            if first_run {
                // Nothing to honour, so put it where the user is actually looking.
                let _ = center_on_primary(&win);
            } else if !is_recoverable(&win) {
                let _ = rescue(&win);
            }

            win.show()?;
            let _ = win.set_focus();

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running RotMG Loot Roadmap");
}
