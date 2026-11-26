import os
import csv
import time
import wave
import ctypes
from ctypes import wintypes
import winsound
import numpy as np


# =====================================================================
# 1. ZERO-DEPENDENCY WINDOWS MICROPHONE CAPTURE (VIA WINMM.DLL)
# =====================================================================
class WindowsMicRecorder:
    """
    Records 16-bit mono PCM audio directly from the default Windows microphone
    using native winmm.dll MCI commands—no PyAudio or external libraries needed.
    """
    def __init__(self, sample_rate=16000):
        self.sr = sample_rate
        self.winmm = ctypes.windll.winmm
        self.winmm.mciSendStringW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.UINT,
            wintypes.HANDLE
        ]
        self.winmm.mciSendStringW.restype = wintypes.UINT

    def _mci(self, command):
        buf = ctypes.create_unicode_buffer(256)
        err = self.winmm.mciSendStringW(command, buf, 256, None)
        if err != 0:
            err_buf = ctypes.create_unicode_buffer(256)
            self.winmm.mciGetErrorStringW(err, err_buf, 256)
            raise RuntimeError(f"Windows MCI Audio Error ({err}): {err_buf.value}")
        return buf.value

    def record_to_wav(self, filepath, duration_sec=3.0):
        """Records from the default mic for `duration_sec` and writes a clean 16kHz WAV."""
        alias = "talos_mic"
        try:
            self._mci(f"close {alias}")
        except RuntimeError:
            pass

        self._mci(f"open new type waveaudio alias {alias}")
        self._mci(
            f"set {alias} time format ms bitspersample 16 "
            f"channels 1 samplespersec {self.sr} alignment 2 bytespersec {self.sr * 2}"
        )
        self._mci(f"record {alias}")
        time.sleep(duration_sec)
        self._mci(f"stop {alias}")

        abs_path = os.path.abspath(filepath)
        self._mci(f'save {alias} "{abs_path}"')
        self._mci(f"close {alias}")


# =====================================================================
# 2. DATASET RECORDER, VALIDATOR & MANIFEST LABELER
# =====================================================================
class TalosDatasetManager:
    """
    Manages recording, audio quality checks (clipping/silence), playback verification,
    and CSV manifest labeling for training T.A.L.O.S. STT from scratch.
    """
    def __init__(self, dataset_dir="talos_stt_dataset", sample_rate=16000):
        self.dataset_dir = dataset_dir
        self.wav_dir = os.path.join(dataset_dir, "wavs")
        self.manifest_path = os.path.join(dataset_dir, "manifest.csv")
        self.mic = WindowsMicRecorder(sample_rate=sample_rate)
        self.sr = sample_rate

        os.makedirs(self.wav_dir, exist_ok=True)
        if not os.path.exists(self.manifest_path):
            with open(self.manifest_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["filepath", "transcript", "duration_sec", "rms_energy"])

    def _inspect_wav(self, filepath):
        """Checks duration, peak clipping, and RMS volume to reject bad takes."""
        with wave.open(filepath, "rb") as wf:
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        duration = len(audio) / float(self.sr)
        rms = float(np.sqrt(np.mean(audio ** 2) + 1e-12))
        peak = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
        return duration, rms, peak

    def _next_clip_id(self):
        existing = [f for f in os.listdir(self.wav_dir) if f.endswith(".wav")]
        return f"utterance_{len(existing) + 1:05d}.wav"

    def append_to_manifest(self, rel_path, transcript, duration, rms):
        clean_text = "".join(c for c in transcript.lower() if c.isalpha() or c in (" ", "'")).strip()
        with open(self.manifest_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([rel_path, clean_text, f"{duration:.3f}", f"{rms:.5f}"])

    def run_interactive_session(self, prompts, takes_per_prompt=5, record_sec=3.0):
        """Guides you through recording multiple takes per command phrase."""
        print("==========================================================")
        print("  T.A.L.O.S. STT DATASET RECORDER & LABELER")
        print("==========================================================")
        print(f"Dataset folder : {os.path.abspath(self.dataset_dir)}")
        print(f"Prompts queued : {len(prompts)} phrases x {takes_per_prompt} takes")
        print("Controls       : [ENTER] Record | [R] Replay last | [S] Skip | [Q] Quit\n")

        last_saved = None

        for p_idx, phrase in enumerate(prompts, start=1):
            take = 1
            while take <= takes_per_prompt:
                cmd = input(
                    f"[{p_idx}/{len(prompts)} | Take {take}/{takes_per_prompt}] "
                    f'Phrase: "{phrase}" > '
                ).strip().lower()

                if cmd == "q":
                    print("\n[T.A.L.O.S.] Session saved and closed.")
                    return
                elif cmd == "s":
                    print("  -> Skipped phrase.")
                    break
                elif cmd == "r":
                    if last_saved and os.path.exists(last_saved):
                        print("  -> Playing back last recording...")
                        winsound.PlaySound(last_saved, winsound.SND_FILENAME)
                    else:
                        print("  -> No recording to replay yet.")
                    continue

                filename = self._next_clip_id()
                full_path = os.path.join(self.wav_dir, filename)
                rel_path = os.path.join("wavs", filename)

                print(f"  [REC] Speak now ({record_sec:.1f}s)...", end="", flush=True)
                self.mic.record_to_wav(full_path, duration_sec=record_sec)
                print(" Done!")

                duration, rms, peak = self._inspect_wav(full_path)

                # Automatic quality gate: reject silent or severely clipped recordings
                if rms < 0.005:
                    print(f"  [WARN] Too quiet (RMS={rms:.4f}). Discarded—please speak louder.")
                    os.remove(full_path)
                    continue
                if peak > 0.99:
                    print(f"  [WARN] Mic clipping detected (Peak={peak:.2f}). Lower mic gain or step back.")

                self.append_to_manifest(rel_path, phrase, duration, rms)
                last_saved = full_path
                print(f"  [SAVED] {filename} | RMS={rms:.4f} | Label='{phrase.lower()}'")
                take += 1

        print("\n[T.A.L.O.S.] All prompts complete! Dataset ready for CTC training.")


# =====================================================================
# STANDALONE DATASET COLLECTION RUNNER
# =====================================================================
if __name__ == "__main__":
    # Core T.A.L.O.S. command vocabulary (add or edit phrases as needed)
    talos_commands = [
        "talos status report",
        "activate tactical mode",
        "systems operational",
        "run diagnostics",
        "open terminal",
        "close window",
        "what time is it",
        "mute audio",
        "unmute audio",
        "shutdown system"
    ]

    recorder = TalosDatasetManager(dataset_dir="talos_stt_dataset", sample_rate=16000)
    recorder.run_interactive_session(
        prompts=talos_commands,
        takes_per_prompt=5,
        record_sec=2.8
    )
