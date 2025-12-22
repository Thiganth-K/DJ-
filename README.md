# DJ-

Simple web tool to upload an audio file (e.g. `.mp3`) and extract beat-based cue points.

What it returns (best-effort):
- If the `.mp3` contains embedded markers: ID3 chapters (`CHAP`) and/or an embedded CUE sheet (fast; no audio decoding)
- Otherwise: estimated tempo, beat count, and simple phrase-based cue points (slower)

## Run (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:5000

## API

`POST /analyze` with `multipart/form-data` field `file`.

Optional query params:
- `phrase` (default `32`): phrase length in beats
- `include_beats=1`: include full `beat_times` array in the response (slower / bigger payload)
- `mode=auto|metadata|beats` (default `auto`):
	- `auto`: try embedded metadata first, else fall back to beat-based
	- `metadata`: only embedded metadata cues (returns empty if none)
	- `beats`: always run beat-based cue extraction

Response:

```json
{"tempo":128.0,"num_beats":640,"phrase":32,"cue_times":[0.0,60.1,120.2],"cue_indices":[0,32,64]}
```