# app.py
from flask import Flask, request, jsonify, render_template
import librosa
import numpy as np
import os
import tempfile

app = Flask(__name__)


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
