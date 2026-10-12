"""Making recorded videos lighter with ffmpeg, when it is installed."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

# Playwright records VP8 at 25 fps even when nothing moves, which is most of a run (the model
# thinks between actions). VP9 at 5 fps is about 7 times lighter and the text stays readable.
RUN_VIDEO_ARGS = (
    "-c:v",
    "libvpx-vp9",
    "-crf",
    "40",
    "-b:v",
    "0",
    "-r",
    "5",
    "-row-mt",
    "1",
    "-deadline",
    "realtime",
    "-cpu-used",
    "8",
    "-an",
)


def reencode(path: Path, args: Sequence[str] = RUN_VIDEO_ARGS, timeout: float = 300) -> bool:
    """Re-encode a file in place with ffmpeg. The original is kept when ffmpeg is missing,
    fails, times out or produces a bigger file. Returns True when the file was replaced."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not path.is_file():
        return False
    tmp = path.with_name(path.stem + ".tmp" + path.suffix)
    try:
        done = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-i", str(path), *args, str(tmp)],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if done.returncode != 0 or not tmp.is_file() or not 0 < tmp.stat().st_size < path.stat().st_size:
            return False
        tmp.replace(path)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        tmp.unlink(missing_ok=True)
