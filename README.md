# Datasheet Organizer

A local cross-platform datasheet library for Windows, macOS, and Linux. Python 3.10+ and a modern browser are the only requirements; no packages or account are required.

## Run

```sh
python3 app.py
```

On Windows: `py app.py`. The app opens at http://127.0.0.1:8765. Use `--port 9000` to change ports or `--no-browser` to suppress automatic opening.

## Features

- Discover vendor-hosted PDF datasheets across TI, Analog Devices, ST, Microchip, NXP, Infineon, onsemi, and Renesas.
- Download PDFs, import existing files, and browse saved documents offline in the browser PDF viewer.
- Search your library by title, vendor, tags, and notes; filter by vendor and favorite documents.
- Edit metadata, add design notes, and remove documents. Duplicate PDF content is saved only once.
- SQLite metadata and PDFs persist in `~/.datasheet-organizer`. Override with the `DATASHEET_HOME` environment variable. Back up that entire directory to preserve your library.

Discovery uses public Bing RSS search, filtering results to selected vendor domains and PDF links. This endpoint can be blocked, rate-limited, or miss documents; the app exposes vendor-scoped web search links and supports direct PDF URLs as fallbacks. The three initial discovery references are a small curated catalog, not live search results. Some vendors block automated downloads; download in your browser and import those files. No vendor API credentials are needed. Online discovery and downloads require internet access; local browsing does not. PDF full-text indexing and native installers are not included.

The service binds only to loopback. Downloads require public HTTPS URLs, reject private addresses and private redirects, validate PDF signatures, and cap files at 40 MB. This is a personal local application, not a multi-user hosted service.

## Verify

```sh
python3 -m unittest discover -s tests -v
```
# DatasheetOrganizer
