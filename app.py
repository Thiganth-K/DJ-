# app.py
from flask import Flask, request, jsonify, render_template
import librosa
import numpy as np
import os
import tempfile
import re

from mutagen.id3 import ID3, ID3NoHeaderError

app = Flask(__name__)


def _safe_first_text(frame):
    if frame is None:
        return None
    text = getattr(frame, "text", None)
    if not text:
        return None
    try:
        return str(text[0])
    except Exception:
        return None


def _extract_cue_sheet_text_from_id3(id3: ID3) -> str:
    chunks = []

    for frame in id3.getall("TXXX"):
        desc = (getattr(frame, "desc", "") or "").lower()
        if "cue" in desc:
            for t in getattr(frame, "text", []) or []:
                if t:
                    chunks.append(str(t))

    for frame in id3.getall("COMM"):
        for t in getattr(frame, "text", []) or []:
            if t and "file\"" in str(t).lower() and "track" in str(t).lower():
                chunks.append(str(t))

    for frame in id3.getall("USLT"):
        t = getattr(frame, "text", None)
        if t and "track" in str(t).lower() and "index" in str(t).lower():
            chunks.append(str(t))

    return "\n".join(chunks).strip()


_CUE_TRACK_RE = re.compile(r"^\s*TRACK\s+(\d+)\s+\w+\s*$", re.IGNORECASE)
_CUE_TITLE_RE = re.compile(r"^\s*TITLE\s+\"(.*)\"\s*$", re.IGNORECASE)
_CUE_INDEX_RE = re.compile(r"^\s*INDEX\s+01\s+(\d+):(\d+):(\d+)\s*$", re.IGNORECASE)


def _parse_cue_sheet(cue_text: str):
    # Very small parser: extracts TRACK title + INDEX 01 time.
    # Time format is mm:ss:ff (75 frames per second).
    cues = []
    current_track = None
    current_title = None

    for line in (cue_text or "").splitlines():
        m = _CUE_TRACK_RE.match(line)
        if m:
            current_track = int(m.group(1))
            current_title = None
            continue

        m = _CUE_TITLE_RE.match(line)
        if m and current_track is not None:
            current_title = m.group(1).strip()
            continue

        m = _CUE_INDEX_RE.match(line)
        if m and current_track is not None:
            mm = int(m.group(1))
            ss = int(m.group(2))
            ff = int(m.group(3))
            start_seconds = mm * 60.0 + ss + (ff / 75.0)
            cues.append(
                {
                    "title": current_title or f"Track {current_track:02d}",
                    "start_seconds": float(start_seconds),
                    "source": "cue-sheet",
                }
            )
            continue

    cues.sort(key=lambda x: x["start_seconds"])
    return cues


def _extract_id3_chapters(id3: ID3):
    cues = []
    for chap in id3.getall("CHAP"):
        start_ms = getattr(chap, "start_time", None)
        if start_ms is None:
            continue

        title = None
        sub_frames = getattr(chap, "sub_frames", None) or getattr(chap, "subframes", None)
        if isinstance(sub_frames, dict):
            tit2_list = sub_frames.get("TIT2") or []
            if tit2_list:
                title = _safe_first_text(tit2_list[0])

        cues.append(
            {
                "title": title or getattr(chap, "element_id", None) or "Chapter",
                "start_seconds": float(start_ms) / 1000.0,
                "source": "id3-chap",
            }
        )

    cues.sort(key=lambda x: x["start_seconds"])
    return cues


def extract_metadata_cues(file_path: str):
    # Returns [] if no usable metadata cues.
    try:
        id3 = ID3(file_path)
    except ID3NoHeaderError:
        return []
    except Exception:
        return []

    cues = []
    cues.extend(_extract_id3_chapters(id3))

    cue_text = _extract_cue_sheet_text_from_id3(id3)
    if cue_text:
        cues.extend(_parse_cue_sheet(cue_text))

    # De-dup by (title, time) rounded to 10ms
    seen = set()
    deduped = []
    for c in sorted(cues, key=lambda x: x["start_seconds"]):
        key = ((c.get("title") or "").strip().lower(), round(float(c["start_seconds"]), 2), c.get("source"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    return deduped


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "empty file"}), 400

    data = file.read()
    if not data:
        return jsonify({"error": "empty file"}), 400

    _, ext = os.path.splitext(file.filename)
    ext = (ext or "").lower()

    # MP3 decoding is more reliable via a real file path than BytesIO.
    # (soundfile doesn't support MP3; audioread typically expects a filename.)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext or ".audio") as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        mode = request.args.get("mode", "auto").strip().lower()
        if mode not in ("auto", "metadata", "beats"):
            mode = "auto"

        # Fast path: if the MP3 has embedded cue markers, return those without decoding audio.
        if mode in ("auto", "metadata") and ext == ".mp3":
            metadata_cues = extract_metadata_cues(tmp_path)
            if metadata_cues:
                return jsonify(
                    {
                        "mode": "metadata",
                        "cue_points": metadata_cues,
                        "cue_times": [c["start_seconds"] for c in metadata_cues],
                        "num_cue_points": int(len(metadata_cues)),
                    }
                )

        if mode == "metadata":
            return jsonify(
                {
                    "mode": "metadata",
                    "cue_points": [],
                    "cue_times": [],
                    "num_cue_points": 0,
                    "note": "No embedded metadata cue points found.",
                }
            )

        y, sr = librosa.load(tmp_path, mono=True)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    phrase = request.args.get("phrase", "32")
    try:
        phrase = int(phrase)
    except (TypeError, ValueError):
        phrase = 32
    phrase = max(1, min(256, phrase))

    include_beats = request.args.get("include_beats", "0").strip().lower() in ("1", "true", "yes", "y")

    # Beat tracking
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    # librosa may return tempo as a numpy scalar/array depending on version
    if isinstance(tempo, np.ndarray):
        tempo = float(np.asarray(tempo).reshape(-1)[0]) if tempo.size else 0.0
    else:
        tempo = float(tempo)

    beat_frames = np.asarray(beat_frames, dtype=int)

    # Simple phrase-based cue points (indices are beat indices)
    def pick_cues(num_beats: int, phrase_len: int):
        n = int(num_beats)
        idxs = [0]
        if n > phrase_len:
            idxs.append(phrase_len)
        if n > 2 * phrase_len:
            idxs.append(2 * phrase_len)
        if n > 3 * phrase_len:
            idxs.append(3 * phrase_len)
        if n > phrase_len:
            idxs.append(max(0, n - phrase_len))
        return sorted(set(i for i in idxs if i < n))

    cue_indices = pick_cues(len(beat_frames), phrase)
    cue_frames = beat_frames[cue_indices] if len(cue_indices) else np.asarray([], dtype=int)
    cue_times = librosa.frames_to_time(cue_frames, sr=sr).tolist()

    result = {
        "mode": "beats",
        "tempo": tempo,
        "num_beats": int(len(beat_frames)),
        "phrase": phrase,
        "cue_times": cue_times,
        "cue_indices": cue_indices,
    }

    if include_beats:
        result["beat_times"] = librosa.frames_to_time(beat_frames, sr=sr).tolist()

    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)
