# Changelog

## 1.0.0 - 2026-01-31
- **Forked:** Original repos https://github.com/PavelVe/home-assistant-addons
- **Migration:** Replaced Gammu/USB modem backend with Keenetic Router API (RCI) integration.
- **Added:** New configuration options for Keenetic router connection (`keenetic_host`, `keenetic_username`, `keenetic_password`, `keenetic_modem_interface`).
- **Removed:** USB device passthrough configuration (`device_path`, `pin`).
- **Removed:** Flash SMS support (not supported by Keenetic RCI).
- **Removed:** Detailed SMS capacity reporting (simplified to placeholders).
- **Changed:** Docker image size significantly reduced (removed gammu/build dependencies).
- **Updated:** Documentation to reflect router-based architecture.