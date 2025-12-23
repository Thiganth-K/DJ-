from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class CuePoint:
    title: str
    start_seconds: float
    source: str  # e.g. "id3-chap" or "cue-sheet"


def _mmssff_to_seconds(mm: int, ss: int, ff: int) -> float:
    # CUE sheets use 75 frames per second.
    return mm * 60 + ss + (ff / 75.0)


_CUE_TRACK_RE = re.compile(r"^\s*TRACK\s+(\d+)\s+\w+\s*$", re.IGNORECASE)
_CUE_TITLE_RE = re.compile(r"^\s*TITLE\s+\"(.*)\"\s*$", re.IGNORECASE)
_CUE_INDEX01_RE = re.compile(r"^\s*INDEX\s+01\s+(\d+):(\d+):(\d+)\s*$", re.IGNORECASE)

_CUE_TITLE_UNQUOTED_RE = re.compile(r"^\s*TITLE\s+([^\"].*?)\s*$", re.IGNORECASE)

_TIMESTAMPED_LINE_RE = re.compile(
    r"^\s*\[?(\d+:\d+(?::\d+)?(?:\.\d+)?)\]?\s*(?:[-–—:]\s*)?(.*?)\s*$"
)


def parse_cue_sheet_text(cue_text: str) -> list[CuePoint]:
    """Parse a CUE sheet and return cue points (TRACK INDEX 01).

    This is a best-effort parser intended for embedded CUE text found in tags.
    """

    cue_points: list[CuePoint] = []

    current_track_no: str | None = None
    current_track_title: str | None = None

    for raw_line in cue_text.splitlines():
        line = raw_line.strip("\ufeff\n\r")
        if not line:
            continue

        m = _CUE_TRACK_RE.match(line)
        if m:
            current_track_no = m.group(1)
            current_track_title = None
            continue

        m = _CUE_TITLE_RE.match(line)
        if m and current_track_no is not None:
            current_track_title = m.group(1)
            continue

        m = _CUE_TITLE_UNQUOTED_RE.match(line)
        if m and current_track_no is not None:
            current_track_title = m.group(1).strip()
            continue

        m = _CUE_INDEX01_RE.match(line)
        if m and current_track_no is not None:
            mm, ss, ff = int(m.group(1)), int(m.group(2)), int(m.group(3))
            title = current_track_title or f"Track {int(current_track_no):02d}"
            cue_points.append(
                CuePoint(title=title, start_seconds=_mmssff_to_seconds(mm, ss, ff), source="cue-sheet")
            )

    cue_points.sort(key=lambda c: c.start_seconds)
    return cue_points


def _parse_time_to_seconds(value: str) -> float | None:
    v = value.strip()

    # hh:mm:ss(.ms)
    m = re.match(r"^(\d+):(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?$", v)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        ss = int(m.group(3))
        ms = int((m.group(4) or "0").ljust(3, "0"))
        return hh * 3600 + mm * 60 + ss + (ms / 1000.0)

    # mm:ss(.ms)
    m = re.match(r"^(\d+):(\d{1,2})(?:\.(\d{1,3}))?$", v)
    if m:
        mm = int(m.group(1))
        ss = int(m.group(2))
        ms = int((m.group(3) or "0").ljust(3, "0"))
        return mm * 60 + ss + (ms / 1000.0)

    # seconds(.ms)
    m = re.match(r"^(\d+)(?:\.(\d{1,3}))?$", v)
    if m:
        ss = int(m.group(1))
        ms = int((m.group(2) or "0").ljust(3, "0"))
        return ss + (ms / 1000.0)

    return None


def parse_timestamped_lines(text: str) -> list[CuePoint]:
    """Parse common "timestamp title" formats.

    Examples handled:
    - 01:23.456 Intro
    - [01:23.456] Intro
    - 01:23 - Intro
    """

    cue_points: list[CuePoint] = []
    for raw_line in text.splitlines():
        line = raw_line.strip("\ufeff\n\r")
        if not line:
            continue

        m = _TIMESTAMPED_LINE_RE.match(line)
        if not m:
            continue

        ts = m.group(1)
        title = (m.group(2) or "").strip() or "Cue"
        seconds = _parse_time_to_seconds(ts)
        if seconds is None:
            continue

        cue_points.append(CuePoint(title=title, start_seconds=seconds, source="timestamp-text"))

    cue_points.sort(key=lambda c: c.start_seconds)
    return cue_points


def _looks_like_cue_sheet(text: str) -> bool:
    # Heuristic: embedded cue sheets commonly contain TRACK/INDEX and FILE.
    t = text.upper()
    return ("TRACK" in t and "INDEX 01" in t) or ("FILE" in t and "TRACK" in t)


def _iter_id3_text_candidates(tags: Any) -> list[str]:
    """Collect potential text blobs that might contain cue/chapter info.

    We intentionally scan a broad set of frames because many tools store CUE-like
    text in nonstandard places.
    """

    candidates: list[str] = []

    for frame in tags.values():
        # TXXX: user text frames can have a descriptor and one or more values.
        if frame.__class__.__name__ == "TXXX":
            desc = getattr(frame, "desc", None)
            if isinstance(desc, str) and desc.strip():
                candidates.append(desc)
            try:
                for v in getattr(frame, "text", []) or []:
                    if isinstance(v, str) and v.strip():
                        candidates.append(v)
            except Exception:
                pass

        # COMM: comments (descriptor + text)
        if frame.__class__.__name__ == "COMM":
            desc = getattr(frame, "desc", None)
            if isinstance(desc, str) and desc.strip():
                candidates.append(desc)
            try:
                v = getattr(frame, "text", None)
                if isinstance(v, list):
                    for t in v:
                        if isinstance(t, str) and t.strip():
                            candidates.append(t)
                elif isinstance(v, str) and v.strip():
                    candidates.append(v)
            except Exception:
                pass

        # USLT: lyrics/unsynced text
        if frame.__class__.__name__ == "USLT":
            try:
                v = getattr(frame, "text", None)
                if isinstance(v, str) and v.strip():
                    candidates.append(v)
            except Exception:
                pass

        # Generic: any frame exposing a `.text` list of strings.
        try:
            v = getattr(frame, "text", None)
            if isinstance(v, list):
                for t in v:
                    if isinstance(t, str) and t.strip():
                        candidates.append(t)
        except Exception:
            pass

    # Keep unique but preserve order.
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def extract_cue_points_from_mp3(file_path: str) -> list[CuePoint]:
    """Extract cue points from an MP3.

    Supported sources (best-effort):
    - ID3v2 CHAP/CTOC chapter frames
    - Embedded CUE sheet text in common text fields (TXXX/COMM/USLT)

    Returns a sorted list of CuePoint.
    """

    cue_points: list[CuePoint] = []

    try:
        from mutagen.id3 import ID3
        from mutagen.id3._frames import CHAP, CTOC, TIT2
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: mutagen. Install via pip install mutagen") from exc

    try:
        tags = ID3(file_path)
    except Exception:
        tags = None

    # 1) ID3 chapters (CHAP)
    if tags is not None:
        chap_frames: list[CHAP] = []
        for frame in tags.values():
            if isinstance(frame, CHAP):
                chap_frames.append(frame)

        # Respect CTOC ordering if present; otherwise sort by start time.
        ordered_element_ids: list[str] | None = None
        ctoc_frames = [f for f in tags.values() if isinstance(f, CTOC)]
        if ctoc_frames:
            # Prefer a top-level CTOC (flags has top-level bit set) if possible.
            top_level = next((c for c in ctoc_frames if getattr(c, "flags", 0) & 0x2), ctoc_frames[0])
            ordered_element_ids = list(getattr(top_level, "child_element_ids", []) or [])

        chap_by_id = {getattr(ch, "element_id", ""): ch for ch in chap_frames}

        if ordered_element_ids:
            ordered_chaps = [chap_by_id[eid] for eid in ordered_element_ids if eid in chap_by_id]
        else:
            ordered_chaps = sorted(chap_frames, key=lambda ch: float(getattr(ch, "start_time", 0) or 0))

        for ch in ordered_chaps:
            start_ms = float(getattr(ch, "start_time", 0) or 0)

            title = None
            subframes = getattr(ch, "sub_frames", {}) or {}
            if isinstance(subframes, dict):
                # Prefer TIT2, but fall back to other text-like subframes.
                tit2 = subframes.get("TIT2")
                if isinstance(tit2, TIT2) and tit2.text:
                    title = str(tit2.text[0])
                if not title:
                    for sf in subframes.values():
                        try:
                            txt = getattr(sf, "text", None)
                            if isinstance(txt, list) and txt and isinstance(txt[0], str) and txt[0].strip():
                                title = txt[0].strip()
                                break
                        except Exception:
                            continue

            if not title:
                element_id = getattr(ch, "element_id", None)
                title = str(element_id) if element_id else "Chapter"

            cue_points.append(CuePoint(title=title, start_seconds=start_ms / 1000.0, source="id3-chap"))

        # 2) Embedded cue text in other frames
        if not cue_points:
            candidate_texts = _iter_id3_text_candidates(tags)

            # Prefer true cue sheets when we can detect them.
            for text in candidate_texts:
                if _looks_like_cue_sheet(text):
                    cue_points = parse_cue_sheet_text(text)
                    if cue_points:
                        break

        # 3) Fallback: timestamped plain text
        if not cue_points:
            for text in _iter_id3_text_candidates(tags):
                parsed = parse_timestamped_lines(text)
                # Avoid false positives: require at least 2 cues.
                if len(parsed) >= 2:
                    cue_points = parsed
                    break

    cue_points.sort(key=lambda c: c.start_seconds)

    # De-dupe identical timestamps/titles
    deduped: list[CuePoint] = []
    seen: set[tuple[str, int, str]] = set()
    for c in cue_points:
        key = (c.title, int(round(c.start_seconds * 1000)), c.source)
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    return deduped
