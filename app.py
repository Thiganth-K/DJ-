# app.py
from flask import Flask, request, jsonify, render_template
import librosa
import numpy as np
import io
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

    # Beat tracking -> beatgrid [web:2][web:20]
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    # librosa may return tempo as a numpy scalar/array depending on version
    if isinstance(tempo, np.ndarray):
        tempo = float(np.asarray(tempo).reshape(-1)[0]) if tempo.size else 0.0
    else:
        tempo = float(tempo)

    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

    # Simple phrase-based cue points
    def pick_cues(beat_times, phrase=32):
        n = len(beat_times)
        idxs = [0]
        if n > phrase: idxs.append(phrase)
        if n > 2 * phrase: idxs.append(2 * phrase)
        if n > 3 * phrase: idxs.append(3 * phrase)
        if n > phrase: idxs.append(max(0, n - phrase))
        return sorted(set(i for i in idxs if i < n))

    cue_indices = pick_cues(beat_times)
    cue_times = [beat_times[i] for i in cue_indices]

    return jsonify(
        {
            "tempo": tempo,
            "beat_times": beat_times,
            "cue_times": cue_times,
            "cue_indices": cue_indices,
        }
    )

if __name__ == "__main__":
    app.run(debug=True)
