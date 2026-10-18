"""Terminal lyric player for Level Five - Tumi.

Put this script and your MP3 in the same folder.
Supported audio names: TUMI.mp3 or tumi.mp3 (case-sensitive filesystems supported).
Edit LYRICS with (seconds, "lyric line") entries before normal playback.

Run:
    python3 lyric_player_ready.py
Optional timestamp helper:
    python3 lyric_player_ready.py --record
"""
from pathlib import Path
import sys
import time
import os

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
from mutagen import File as MutagenFile

BASE_DIR = Path(__file__).resolve().parent
AUDIO_CANDIDATES = [BASE_DIR / "TUMI.mp3", BASE_DIR / "tumi.mp3"]
AUDIO_FILE = next((p for p in AUDIO_CANDIDATES if p.is_file()), None)
TITLE = "Level Five  ::  Tumi (Official Single)"
BAR_WIDTH = 38

# Put your own lyric lines here, with the time (in seconds) each line starts.
# These are sample placeholders, not the actual song lyrics.
LYRICS = [
    (0.0, "♪ intro ♪"),
    (12.5, "Add your first lyric line here..."),
    (18.0, "Add your second lyric line here..."),
    (24.0, "Add your third lyric line here..."),
]

RAINBOW = [
    "\033[38;5;121m",  # mint green
    "\033[38;5;213m",  # pink
    "\033[38;5;226m",  # yellow
    "\033[38;5;208m",  # orange
    "\033[38;5;45m",   # cyan-blue
    "\033[38;5;177m",  # violet
]
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def rainbow_words(text: str) -> str:
    words = text.split()
    if not words:
        return ""
    return " ".join(f"{RAINBOW[i % len(RAINBOW)]}{word}{RESET}" for i, word in enumerate(words))


def audio_duration(path: Path) -> float:
    info = MutagenFile(str(path))
    if info is None or info.info is None or not getattr(info.info, "length", None):
        raise RuntimeError("Could not read the audio duration. Check that the file is a valid MP3.")
    return float(info.info.length)


def init_audio() -> float:
    if AUDIO_FILE is None:
        raise FileNotFoundError(
            "Could not find TUMI.mp3 or tumi.mp3. Put the MP3 beside this Python file."
        )
    duration = audio_duration(AUDIO_FILE)
    pygame.mixer.init()
    pygame.mixer.music.load(str(AUDIO_FILE))
    return duration


def current_line(position: float) -> str:
    line = "♪ ♪"
    for timestamp, text in sorted(LYRICS, key=lambda item: item[0]):
        if position >= timestamp:
            line = text
        else:
            break
    return line


def play() -> None:
    duration = init_audio()
    if not LYRICS:
        print("LYRICS is empty. Add (seconds, 'line text') entries in the code first.")
        return

    # Keep a four-line area and redraw it during playback.
    print("\033[?25l", end="", flush=True)  # hide cursor
    print(TITLE)
    print()
    print()
    print()
    start = time.monotonic()
    pygame.mixer.music.play()
    try:
        while pygame.mixer.music.get_busy():
            position_ms = pygame.mixer.music.get_pos()
            elapsed = position_ms / 1000 if position_ms >= 0 else time.monotonic() - start
            elapsed = min(elapsed, duration)
            filled = min(BAR_WIDTH, int((elapsed / duration) * BAR_WIDTH)) if duration else 0
            bar = "\033[38;5;121m" + "█" * filled + RESET + "░" * (BAR_WIDTH - filled)
            lyric = rainbow_words(current_line(elapsed))
            progress_line = f"{format_time(elapsed)} / {format_time(duration)}  [{bar}]"

            sys.stdout.write("\033[4A")
            sys.stdout.write(f"\033[2K{BOLD}\033[38;5;121m{TITLE}{RESET}\n")
            sys.stdout.write("\033[2K\n")
            sys.stdout.write(f"\033[2K{BOLD}» {lyric}{RESET}\n")
            sys.stdout.write(f"\033[2K{progress_line}\n")
            sys.stdout.flush()
            time.sleep(0.06)
        print("\n\nPlayback finished.")
    except KeyboardInterrupt:
        print("\nPlayback stopped.")
    finally:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
        print("\033[?25h", end="", flush=True)  # restore cursor


def record() -> None:
    """Optional helper: press Enter when each new lyric line begins to note its time."""
    duration = init_audio()
    print(f"Audio: {AUDIO_FILE.name} ({format_time(duration)})")
    input("Press ENTER to start the song. Then press ENTER when each new lyric line STARTS.\n")
    pygame.mixer.music.play()
    start = time.monotonic()
    timestamps = []
    try:
        while pygame.mixer.music.get_busy():
            input(f"Line {len(timestamps) + 1}: press ENTER at the START of the next line (Ctrl+C to stop) ")
            position_ms = pygame.mixer.music.get_pos()
            elapsed = position_ms / 1000 if position_ms >= 0 else time.monotonic() - start
            if elapsed < duration:
                timestamps.append(round(elapsed, 2))
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
    print("\nTimestamp samples (copy these times into LYRICS and add the matching lines):")
    for stamp in timestamps:
        print(f"    ({stamp}, \"Add lyric line here...\"),")


if __name__ == "__main__":
    try:
        if "--record" in sys.argv:
            record()
        else:
            play()
    except (FileNotFoundError, RuntimeError, pygame.error) as exc:
        print(f"Error: {exc}")
        print("Check that the MP3 is beside this script and that pygame/mutagen are installed.")
