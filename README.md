# High Scope Capture

Desktop tool that pairs Olympus STM 7 microscope captures with LOT data from the plant MES and files each image into a shared QC folder with a JSON sidecar.

## How it works

```
┌───────────────── PyQt GUI (this app) ─────────────────┐
│                                                        │
│  1.  Operator types LOT ID → Fetch                     │
│  2.  App calls MES SOAP `getDetailLotMES`              │
│  3.  Operator presses [Arm for capture]                │
│  4.  App starts watching D:\Auto save\ recursively     │
│  5.  Operator keeps using Olympus Stream normally      │
│      (Snap button → Stream auto-saves .tif)            │
│  6.  App detects the new .tif, parses OME-XML,         │
│      copies to shared folder with sidecar JSON         │
│  7.  Repeat 5–6 until [Disarm]                         │
└────────────────────────────────────────────────────────┘
```

## Setup

1. **Install Python 3.12+** (already present on the target PCs).
2. **Install dependencies:**
   ```powershell
   python -m pip install -r requirements.txt
   ```
3. **Copy the example config:**
   ```powershell
   copy config\settings.example.yaml config\settings.yaml
   ```
4. **Edit `config\settings.yaml`** — in particular `storage.shared_root` must point at the shared QC folder (e.g. `//fileserver/qc-images`).
5. **Configure Olympus Stream** to auto-save `.tif` into `D:\Auto save\` (per-day subfolder `folder_YYYYMMDD` is expected and handled).

## Running

```powershell
python main.py
```

Or specify a config:

```powershell
python main.py --config config\settings.yaml
```

## Output layout

```
<shared_root>\YYYY\MM\<LOT_ID>\
    <LOT_ID>_<YYYYMMDD_HHMMSS>_<hostname>_<seq>.tif
    <LOT_ID>_<YYYYMMDD_HHMMSS>_<hostname>_<seq>.json
```

The `.tif` is a byte-for-byte copy of the file Olympus saved — OME-XML metadata is preserved. The `.json` sidecar adds LOT context and a flattened subset of OME fields for quick search/filter.

## Project layout

```
app/
    config.py            # pydantic settings loader
    models/
        lot.py           # LotDetail (from MES)
        capture.py       # OmeAcquisition + CaptureRecord
    services/
        lot_client.py    # zeep SOAP client (getDetailLotMES)
        omexml.py        # parse OME-XML from TIFF tag 270
        capture.py       # watchdog file watcher
        image_store.py   # atomic copy + sidecar writer
    gui/
        main_window.py   # PyQt6 main window
    utils/
        logging.py
config/
    settings.example.yaml
tests/
    test_omexml.py       # parse Ball1.tif / Ball2.tif samples
main.py                  # entry point
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Cannot reach MES server" at startup | WSDL URL unreachable — check the box is on the plant network |
| LOT shows red border, "LOT not found" | `Reply_Code != 0` returned by MES; message is from the server |
| TIFF saved but sidecar missing / crashes on parse | OME-XML malformed — file is still safe, just parse fails; check `logs/app.log` |
| Same file appears twice in the session list | Olympus rewrote the file; de-dupe is by path — if this recurs, inspect logs |
