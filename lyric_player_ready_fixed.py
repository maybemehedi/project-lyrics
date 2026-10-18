"""Terminal lyric player with LRC lyrics, colorful UI, seeking, and timestamp recording.

Files expected beside this script:
    TUMI.mp3
    lyrics.lrc

Run playback:
    python3 lyric_player_ready_fixed.py

Record fresh timestamps by pressing Enter at the beginning of each displayed lyric line:
    python3 lyric_player_ready_fixed.py --record

Controls during playback:
    Click the progress bar to seek (terminals with SGR mouse support)
    Left/Right arrows: seek -/+ 5 seconds
    Space: pause/resume
    Home/End: jump to beginning/end
    Q or Ctrl+C: quit
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import select
import shutil
import sys
import time

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
from mutagen import File as MutagenFile

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows fallback
    termios = None
    tty = None

BASE_DIR = Path(__file__).resolve().parent
AUDIO_CANDIDATES = [BASE_DIR / "TUMI.mp3", BASE_DIR / "tumi.mp3"]
AUDIO_FILE = next((p for p in AUDIO_CANDIDATES if p.is_file()), None)
LYRICS_FILE = BASE_DIR / "lyrics.lrc"
RECORDED_LYRICS_FILE = BASE_DIR / "lyrics.recorded.lrc"
TITLE = "Level Five :: Tumi"
BAR_WIDTH = 38
RAINBOW = ["\033[38;5;121m", "\033[38;5;213m", "\033[38;5;226m",
           "\033[38;5;208m", "\033[38;5;45m", "\033[38;5;177m"]
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CLEAR_LINE = "\033[2K"
LRC_PATTERN = re.compile(r"\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]")


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def format_lrc_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"[{minutes:02d}:{remainder:05.2f}]"


def rainbow_words(text: str) -> str:
    return " ".join(
        f"{RAINBOW[i % len(RAINBOW)]}{word}{RESET}"
        for i, word in enumerate(text.split())
    )


def audio_duration(path: Path) -> float:
    info = MutagenFile(str(path))
    if info is None or info.info is None:
        raise RuntimeError("Could not read audio metadata. Check that the MP3 is valid.")
    length = getattr(info.info, "length", None)
    if length is None or length <= 0:
        raise RuntimeError("Could not determine the audio duration.")
    return float(length)


def load_lyrics() -> list[tuple[float, str]]:
    """Load timestamped lines from lyrics.lrc."""
    if not LYRICS_FILE.is_file():
        raise FileNotFoundError(
            f"Could not find {LYRICS_FILE.name}. Put it beside this Python file."
        )
    lyrics: list[tuple[float, str]] = []
    with LYRICS_FILE.open("r", encoding="utf-8-sig") as file:
        for raw_line in file:
            line = raw_line.strip()
            matches = list(LRC_PATTERN.finditer(line))
            if not matches:
                continue
            lyric_text = line[matches[-1].end():].strip()
            if not lyric_text or lyric_text.startswith("#"):
                continue
            for match in matches:
                minutes = int(match.group(1))
                seconds = int(match.group(2))
                fraction_text = match.group(3) or ""
                if len(fraction_text) == 3:
                    fraction = int(fraction_text) / 1000
                elif len(fraction_text) == 2:
                    fraction = int(fraction_text) / 100
                elif len(fraction_text) == 1:
                    fraction = int(fraction_text) / 10
                else:
                    fraction = 0.0
                lyrics.append((minutes * 60 + seconds + fraction, lyric_text))
    lyrics.sort(key=lambda item: item[0])
    return lyrics


def current_line(position: float, lyrics: list[tuple[float, str]]) -> str:
    current = "♪ ♪"
    for timestamp, text in lyrics:
        if position < timestamp:
            break
        current = text
    return current


def init_audio() -> float:
    if AUDIO_FILE is None:
        raise FileNotFoundError(
            "Could not find TUMI.mp3 or tumi.mp3. Put the MP3 beside this Python file."
        )
    duration = audio_duration(AUDIO_FILE)
    pygame.mixer.init()
    pygame.mixer.music.load(str(AUDIO_FILE))
    return duration


def read_escape_sequence(first_char: str) -> str:
    """Read a short terminal escape sequence after ESC, if one is available."""
    sequence = first_char
    deadline = time.monotonic() + 0.025
    while time.monotonic() < deadline:
        ready, _, _ = select.select([sys.stdin], [], [], 0.003)
        if not ready:
            continue
        char = sys.stdin.read(1)
        sequence += char
        if char.isalpha() or char in "Mm":
            break
    return sequence


def parse_mouse_click(sequence: str) -> tuple[int, int] | None:
    """Return (x, y) for SGR left-button-down events."""
    match = re.fullmatch(r"\x1b\[<(\d+);(\d+);(\d+)M", sequence)
    if not match:
        return None
    button, x, y = (int(value) for value in match.groups())
    if (button & 3) != 0:  # left click only
        return None
    return x, y


def play() -> None:
    lyrics = load_lyrics()
    if not lyrics:
        raise RuntimeError(
            "No timestamped lyrics found. Add lines like [00:12.50]Your lyric here to lyrics.lrc."
        )

    duration = init_audio()
    stdin_is_tty = sys.stdin.isatty() and termios is not None and tty is not None
    old_terminal_settings = None
    mouse_enabled = False
    cursor_hidden = False
    paused = False
    quit_requested = False
    anchor_position = 0.0
    anchor_clock = time.monotonic()

    def get_position() -> float:
        if paused:
            return anchor_position
        return min(duration, max(0.0, anchor_position + (time.monotonic() - anchor_clock)))

    def seek(target: float) -> None:
        nonlocal anchor_position, anchor_clock
        target = max(0.0, min(float(target), max(0.0, duration - 0.08)))
        was_paused = paused
        pygame.mixer.music.stop()
        pygame.mixer.music.play(start=target)
        anchor_position = target
        anchor_clock = time.monotonic()
        if was_paused:
            pygame.mixer.music.pause()

    def render(position: float) -> None:
        filled = min(BAR_WIDTH, int(position / duration * BAR_WIDTH)) if duration else 0
        prefix = f"{format_time(position)} / {format_time(duration)}  ["
        bar = (f"{RAINBOW[0]}{'█' * filled}{RESET}"
               f"{DIM}{'░' * (BAR_WIDTH - filled)}{RESET}")
        lyric = current_line(position, lyrics)
        width = shutil.get_terminal_size((100, 24)).columns
        max_lyric_chars = max(20, min(70, width - 8))
        if len(lyric) > max_lyric_chars:
            lyric = lyric[:max_lyric_chars - 1] + "…"
        status = "PAUSED" if paused else "PLAYING"
        # Layout is fixed to rows 1–5, so click coordinates on row 4 map to the bar.
        output = (
            "\033[H" + CLEAR_LINE + f"{BOLD}{RAINBOW[0]}{TITLE}{RESET}  {DIM}{status}{RESET}\n"
            + CLEAR_LINE + "\n"
            + CLEAR_LINE + f"{BOLD}» {rainbow_words(lyric)}{RESET}\n"
            + CLEAR_LINE + prefix + bar + f"]\n"
            + CLEAR_LINE + f"{DIM}Click bar to seek  |  ←/→ ±5s  |  Space pause  |  Home/End  |  Q quit{RESET}\n"
        )
        sys.stdout.write(output)
        sys.stdout.flush()

    try:
        if stdin_is_tty:
            fd = sys.stdin.fileno()
            old_terminal_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            sys.stdout.write("\033[?25l\033[?1000h\033[?1006h")
            mouse_enabled = True
            cursor_hidden = True
        # Clear old terminal content so the progress bar has a stable row for mouse coordinates.
        sys.stdout.write("\033[2J\033[H")
        render(0.0)
        pygame.mixer.music.play()
        anchor_position = 0.0
        anchor_clock = time.monotonic()

        while not quit_requested:
            now = time.monotonic()
            elapsed = get_position()
            if not paused and elapsed >= duration:
                break
            # Bail out if the decoder ended unexpectedly (e.g. broken MP3), except during pause.
            if not paused and elapsed > 0.5 and not pygame.mixer.music.get_busy():
                break

            if stdin_is_tty:
                ready, _, _ = select.select([sys.stdin], [], [], 0.06)
                if ready:
                    char = sys.stdin.read(1)
                    if char == "\x1b":
                        seq = read_escape_sequence(char)
                        click = parse_mouse_click(seq)
                        if click:
                            x, y = click
                            prefix_length = len(f"{format_time(elapsed)} / {format_time(duration)}  [")
                            bar_start_col = prefix_length + 1  # terminal coordinates are 1-based
                            if y == 4 and bar_start_col <= x < bar_start_col + BAR_WIDTH:
                                fraction = (x - bar_start_col) / max(1, BAR_WIDTH - 1)
                                seek(fraction * duration)
                        elif seq.endswith("[D"):
                            seek(get_position() - 5.0)
                        elif seq.endswith("[C"):
                            seek(get_position() + 5.0)
                        elif seq.endswith("[H"):
                            seek(0.0)
                        elif seq.endswith("[F"):
                            seek(duration - 0.2)
                    elif char in ("q", "Q", "\x03"):
                        quit_requested = True
                    elif char == " ":
                        if paused:
                            pygame.mixer.music.unpause()
                            anchor_clock = time.monotonic()
                            paused = False
                        else:
                            anchor_position = get_position()
                            pygame.mixer.music.pause()
                            paused = True
            else:
                time.sleep(0.06)

            render(get_position())

        if not quit_requested:
            print("\nPlayback finished.")
        else:
            print("\nPlayback stopped.")
    except KeyboardInterrupt:
        print("\nPlayback stopped.")
    finally:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
        if stdin_is_tty and old_terminal_settings is not None:
            sys.stdout.write("\033[?1000l\033[?1006l")
            if cursor_hidden:
                sys.stdout.write("\033[?25h")
            sys.stdout.flush()
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_terminal_settings)


def record() -> None:
    """Capture a timestamp for each existing lyric line and save a separate LRC file."""
    lyrics = load_lyrics()
    if not lyrics:
        raise RuntimeError("No lyric lines found in lyrics.lrc to timestamp.")
    duration = init_audio()
    print(f"Audio: {AUDIO_FILE.name} ({duration:.2f} seconds / {format_time(duration)})")
    print(f"Will timestamp {len(lyrics)} lyric lines from {LYRICS_FILE.name}.")
    print("When you hear each line BEGIN, press Enter once. Try to press on the first sung syllable.")
    input("Press Enter to start playback from 00:00... ")
    captured: list[tuple[float, str]] = []
    start_clock = 0.0
    try:
        pygame.mixer.music.play()
        start_clock = time.monotonic()
        for index, (_, lyric_text) in enumerate(lyrics, start=1):
            try:
                input(f"Line {index:02d}/{len(lyrics):02d}: {lyric_text}\nPress Enter at the start of this line... ")
            except EOFError:
                break
            stamp = min(duration, max(0.0, time.monotonic() - start_clock))
            if stamp >= duration:
                print("The audio has ended; stopping timestamp capture.")
                break
            captured.append((round(stamp, 2), lyric_text))
            print(f"  recorded {format_lrc_time(stamp)}")
    except KeyboardInterrupt:
        print("\nRecording stopped early; saving timestamps captured so far.")
    finally:
        pygame.mixer.music.stop()
        pygame.mixer.quit()

    if not captured:
        print("No timestamps recorded; no new file was written.")
        return
    with RECORDED_LYRICS_FILE.open("w", encoding="utf-8") as file:
        file.write("\n".join(f"{format_lrc_time(stamp)}{text}" for stamp, text in captured) + "\n")
    print(f"\nSaved {len(captured)} timestamped lines to {RECORDED_LYRICS_FILE.name}.")
    print("Review it, then replace lyrics.lrc with this file if the timing looks good.")


if __name__ == "__main__":
    try:
        if "--record" in sys.argv:
            record()
        else:
            play()
    except (FileNotFoundError, RuntimeError, pygame.error) as exc:
        print(f"Error: {exc}")
        print("Check that the MP3 and lyrics.lrc are beside this script.")
        print("Install dependencies with: python3 -m pip install -r requirements.txt")
