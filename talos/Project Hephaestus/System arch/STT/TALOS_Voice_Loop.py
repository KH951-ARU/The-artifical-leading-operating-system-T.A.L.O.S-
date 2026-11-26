import os
import time
import wave
import ctypes
import difflib
import datetime
import subprocess
from ctypes import wintypes
import numpy as np
import torch

from TALOS_STT_frontend import TalosAudioFrontend
from TALOS_STT_trainer import TalosCRNN, TalosTextTokenizer

# Optional import of your pure-Python TTS engine; falls back cleanly if standalone
try:
    from TALOS_TTS import TalosTTS
except ImportError:
    TalosTTS = None


# =====================================================================
# 1. ZERO-DEPENDENCY LIVE AUDIO STREAMER (WINMM WAVEIN API)
# =====================================================================
class WindowsLiveMicStream:
    """
    Captures continuous 16-bit mono PCM chunks from the default Windows microphone
    using low-level winmm.dll waveIn buffers—zero PyAudio or sounddevice required.
    """

    def __init__(self, sample_rate=16000, chunk_ms=100):
        self.sr = sample_rate
        self.chunk_samples = int(sample_rate * (chunk_ms / 1000.0))
        self.chunk_bytes = self.chunk_samples * 2
        self.winmm = ctypes.windll.winmm
        self.h_wave_in = wintypes.HANDLE()
        self.headers = []
        self.buffers = []

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [
            ("wFormatTag", wintypes.WORD),
            ("nChannels", wintypes.WORD),
            ("nSamplesPerSec", wintypes.DWORD),
            ("nAvgBytesPerSec", wintypes.DWORD),
            ("nBlockAlign", wintypes.WORD),
            ("wBitsPerSample", wintypes.WORD),
            ("cbSize", wintypes.WORD),
        ]

    class WAVEHDR(ctypes.Structure):
        _fields_ = [
            ("lpData", ctypes.c_char_p),
            ("dwBufferLength", wintypes.DWORD),
            ("dwBytesRecorded", wintypes.DWORD),
            ("dwUser", ctypes.POINTER(wintypes.ULONG)),
            ("dwFlags", wintypes.DWORD),
            ("dwLoops", wintypes.DWORD),
            ("lpNext", ctypes.c_void_p),
            ("reserved", ctypes.POINTER(wintypes.ULONG)),
        ]

    def start(self, num_buffers=8):
        wfx = self.WAVEFORMATEX(
            wFormatTag=1,  # WAVE_FORMAT_PCM
            nChannels=1,
            nSamplesPerSec=self.sr,
            nAvgBytesPerSec=self.sr * 2,
            nBlockAlign=2,
            wBitsPerSample=16,
            cbSize=0,
        )
        res = self.winmm.waveInOpen(
            ctypes.byref(self.h_wave_in),
            0xFFFFFFFF,  # WAVE_MAPPER (default mic)
            ctypes.byref(wfx),
            0,
            0,
            0,
        )
        if res != 0:
            raise RuntimeError(f"Failed to open Windows microphone (error {res}).")

        for _ in range(num_buffers):
            buf = ctypes.create_string_buffer(self.chunk_bytes)
            hdr = self.WAVEHDR(
                lpData=ctypes.cast(buf, ctypes.c_char_p),
                dwBufferLength=self.chunk_bytes,
            )
            self.winmm.waveInPrepareHeader(
                self.h_wave_in, ctypes.byref(hdr), ctypes.sizeof(hdr)
            )
            self.winmm.waveInAddBuffer(
                self.h_wave_in, ctypes.byref(hdr), ctypes.sizeof(hdr)
            )
            self.buffers.append(buf)
            self.headers.append(hdr)

        self.winmm.waveInStart(self.h_wave_in)
        self._buf_idx = 0

    def read_chunk(self):
        """Blocks until the next 100ms audio chunk is ready and returns normalized float32."""
        hdr = self.headers[self._buf_idx]
        while not (hdr.dwFlags & 0x00000001):  # WHDR_DONE
            time.sleep(0.01)

        raw = ctypes.string_at(hdr.lpData, hdr.dwBytesRecorded)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        # Re-queue buffer immediately so no audio frames drop
        hdr.dwFlags &= ~0x00000001
        self.winmm.waveInAddBuffer(
            self.h_wave_in, ctypes.byref(hdr), ctypes.sizeof(hdr)
        )
        self._buf_idx = (self._buf_idx + 1) % len(self.headers)
        return audio

    def stop(self):
        self.winmm.waveInStop(self.h_wave_in)
        self.winmm.waveInReset(self.h_wave_in)
        for hdr in self.headers:
            self.winmm.waveInUnprepareHeader(
                self.h_wave_in, ctypes.byref(hdr), ctypes.sizeof(hdr)
            )
        self.winmm.waveInClose(self.h_wave_in)


# =====================================================================
# 2. FUZZY COMMAND ROUTER & ACTION EXECUTOR
# =====================================================================
class TalosCommandRouter:
    """
    Matches raw CTC character transcriptions against known T.A.L.O.S. commands
    using sequence similarity so minor spelling slips still trigger reliably.
    """

    def __init__(self, tts_engine=None):
        self.tts = tts_engine
        self.active = True
        self.muted = False
        self.commands = {
            "talos status report": self.cmd_status,
            "activate tactical mode": self.cmd_tactical,
            "systems operational": self.cmd_status,
            "run diagnostics": self.cmd_diagnostics,
            "open terminal": self.cmd_open_terminal,
            "what time is it": self.cmd_time,
            "mute audio": self.cmd_mute,
            "unmute audio": self.cmd_unmute,
            "shutdown system": self.cmd_shutdown,
        }

    def speak(self, text):
        print(f"[T.A.L.O.S.]: {text}")
        if self.muted:
            return
        if self.tts is not None:
            self.tts.speak(text)

    def dispatch(self, raw_transcript, min_confidence=0.68):
        if not raw_transcript:
            return

        print(f"[HEARD] '{raw_transcript}'")
        best_cmd = None
        best_score = 0.0

        for known_phrase in self.commands:
            score = difflib.SequenceMatcher(None, raw_transcript, known_phrase).ratio()
            if score > best_score:
                best_score = score
                best_cmd = known_phrase

        if best_score >= min_confidence and best_cmd is not None:
            print(f"[MATCH] '{best_cmd}' (confidence: {best_score:.0%})")
            self.commands[best_cmd]()
        else:
            print(f"[IGNORED] Low command match ({best_score:.0%})")

    # --- Built-in System Actions ---
    def cmd_status(self):
        self.speak(
            "All primary subsystems are online and operating within normal parameters."
        )

    def cmd_tactical(self):
        self.speak("Tactical mode engaged. Monitoring active telemetry.")

    def cmd_diagnostics(self):
        self.speak("Running acoustic and neural diagnostics. Zero faults detected.")

    def cmd_open_terminal(self):
        self.speak("Opening command terminal.")
        subprocess.Popen(["cmd.exe"], creationflags=subprocess.CREATE_NEW_CONSOLE)

    def cmd_time(self):
        now = datetime.datetime.now().strftime("%I:%M %p").lstrip("0")
        self.speak(f"The current time is {now}.")

    def cmd_mute(self):
        self.speak("Audio output muted.")
        self.muted = True

    def cmd_unmute(self):
        self.muted = False
        self.speak("Audio output restored.")

    def cmd_shutdown(self):
        self.speak("Powering down voice interface. Standing by.")
        self.active = False


# =====================================================================
# 3. LIVE CONTINUOUS LISTENING LOOP (VAD TRIGGER -> STT -> TTS)
# =====================================================================
class TalosVoiceAssistant:
    def __init__(self, weights_path="talos_stt_weights.pt"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.frontend = TalosAudioFrontend(sample_rate=16000, n_mels=64)
        self.tokenizer = TalosTextTokenizer()

        if not os.path.exists(weights_path):
            raise FileNotFoundError(
                f"Missing {weights_path}. Run talos_stt_trainer.py first to train your model."
            )

        checkpoint = torch.load(
            weights_path, map_location=self.device, weights_only=True
        )
        self.model = TalosCRNN(
            n_mels=checkpoint["n_mels"], vocab_size=checkpoint["vocab_size"]
        ).to(self.device)
        self.model.load_state_dict(checkpoint["model_state"])
        self.model.eval()

        tts_instance = TalosTTS() if TalosTTS is not None else None
        self.router = TalosCommandRouter(tts_engine=tts_instance)
        self.mic = WindowsLiveMicStream(sample_rate=16000, chunk_ms=100)

    def _transcribe_buffer(self, audio_array):
        trimmed = self.frontend.trim_silence(audio_array)
        if len(trimmed) < 800:
            return ""
        log_mel = self.frontend.extract_log_mel_spectrogram(trimmed, normalize=True)
        tensor_in = (
            torch.tensor(log_mel, dtype=torch.float32)
            .unsqueeze(0)
            .unsqueeze(0)
            .to(self.device)
        )
        with torch.no_grad():
            log_probs = self.model(tensor_in)
        return self.tokenizer.decode_greedy(log_probs)[0]

    def run(
        self, speech_threshold=0.025, silence_timeout_sec=0.8, max_utterance_sec=4.5
    ):
        print("==========================================================")
        print("  T.A.L.O.S. HANDS-FREE VOICE INTERFACE ONLINE")
        print("==========================================================")
        print("Listening continuously... Press Ctrl+C to force exit.\n")

        self.mic.start()
        self.router.speak("Talos voice interface online.")

        utterance_chunks = []
        pre_roll_buffer = (
            []
        )  # Keeps 300ms before trigger so initial consonants aren't lost
        is_speaking = False
        silence_chunks = 0

        max_silence_chunks = int(silence_timeout_sec / 0.1)
        max_total_chunks = int(max_utterance_sec / 0.1)

        try:
            while self.router.active:
                chunk = self.mic.read_chunk()
                rms = float(np.sqrt(np.mean(chunk**2) + 1e-12))

                if not is_speaking:
                    pre_roll_buffer.append(chunk)
                    if len(pre_roll_buffer) > 3:
                        pre_roll_buffer.pop(0)

                    if rms >= speech_threshold:
                        is_speaking = True
                        silence_chunks = 0
                        utterance_chunks = list(pre_roll_buffer)
                        print("[VAD] Speech detected...")
                else:
                    utterance_chunks.append(chunk)
                    if rms < speech_threshold:
                        silence_chunks += 1
                    else:
                        silence_chunks = 0

                    # End utterance on trailing pause or maximum phrase duration.
                    if (
                        silence_chunks >= max_silence_chunks
                        or len(utterance_chunks) >= max_total_chunks
                    ):
                        full_audio = np.concatenate(utterance_chunks)
                        transcript = self._transcribe_buffer(full_audio)
                        self.router.dispatch(transcript)

                        # Reset state for next command.
                        is_speaking = False
                        utterance_chunks = []
                        pre_roll_buffer = []
                        silence_chunks = 0
        except KeyboardInterrupt:
            print("\n[T.A.L.O.S.] Manual interrupt received.")
        finally:
            self.mic.stop()
            print("[T.A.L.O.S.] Microphone stream closed.")


if __name__ == "__main__":
    assistant = TalosVoiceAssistant(weights_path="talos_stt_weights.pt")
    assistant.run(speech_threshold=0.025, silence_timeout_sec=0.8)
