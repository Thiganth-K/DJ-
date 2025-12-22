# DJ-

Simple web tool to upload an `.mp3` and extract embedded cue points.

What it extracts (best-effort):
- ID3v2 chapter frames: `CHAP` / `CTOC`
- Embedded CUE sheet text if present in common text tags

## Run (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:5000

## API

`POST /api/extract` with `multipart/form-data` field `file`.

Response:

```json
{"cue_points":[{"title":"Intro","start_seconds":0.0,"source":"id3-chap"}]}
```