import wave
import numpy as np


class TalosAudioFrontend:
    """
    Pure-NumPy Speech-to-Text Audio Frontend for T.A.L.O.S.
    Handles WAV loading, Voice Activity Detection (VAD), pre-emphasis,
    framing, FFT power spectrum, and Mel-filterbank extraction from scratch.
    """

    def __init__(
        self,
        sample_rate=16000,
        frame_ms=25.0,
        hop_ms=10.0,
        n_fft=512,
        n_mels=64,
        f_min=80.0,
        f_max=7600.0,
        pre_emphasis=0.97
    ):
        self.sr = sample_rate
        self.frame_len = int(round((frame_ms / 1000.0) * sample_rate))  # 400 samples @ 16kHz
        self.hop_len = int(round((hop_ms / 1000.0) * sample_rate))      # 160 samples @ 16kHz
        self.n_fft = n_fft
        self.n_mels = n_mels
        self.f_min = f_min
        self.f_max = min(f_max, sample_rate / 2.0)
        self.pre_emphasis = pre_emphasis

        # Precompute Hamming window and Mel filterbank matrix once for speed
        self.window = np.hamming(self.frame_len)
        self.mel_filterbank = self._build_mel_filterbank()

    # =====================================================================
    # 1. PURE-PYTHON WAV READER & RESAMPLER
    # =====================================================================
    def load_wav(self, filepath):
        """Loads a 16-bit PCM WAV file into a normalized [-1.0, 1.0] float32 array."""
        with wave.open(filepath, 'rb') as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            file_sr = wf.getframerate()
            n_frames = wf.getnframes()
            raw_bytes = wf.readframes(n_frames)

        if sampwidth != 2:
            raise ValueError(f"Expected 16-bit PCM WAV, got {sampwidth * 8}-bit.")

        audio = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Mix stereo/multi-channel down to mono
        if n_channels > 1:
            audio = audio.reshape(-1, n_channels).mean(axis=1)

        # Linear interpolation resampling if file sample rate differs from target
        if file_sr != self.sr:
            duration = len(audio) / float(file_sr)
            target_len = int(round(duration * self.sr))
            old_indices = np.linspace(0, len(audio) - 1, num=len(audio))
            new_indices = np.linspace(0, len(audio) - 1, num=target_len)
            audio = np.interp(new_indices, old_indices, audio).astype(np.float32)

        return audio

    # =====================================================================
    # 2. VOICE ACTIVITY DETECTION (ENERGY + ZERO-CROSSING RATE)
    # =====================================================================
    def trim_silence(self, audio, energy_threshold_ratio=0.08, pad_ms=150.0):
        """
        Strips leading and trailing silence using short-time RMS energy
        while keeping a small buffer pad so initial consonants (P, T, K, S) aren't clipped.
        """
        if len(audio) < self.frame_len:
            return audio

        # Slice audio into frames to measure RMS energy
        n_frames = 1 + (len(audio) - self.frame_len) // self.hop_len
        rms_energies = np.zeros(n_frames)

        for i in range(n_frames):
            start = i * self.hop_len
            frame = audio[start : start + self.frame_len]
            rms_energies[i] = np.sqrt(np.mean(frame ** 2) + 1e-12)

        peak_energy = np.max(rms_energies)
        if peak_energy < 1e-5:
            return np.array([], dtype=np.float32)  # Completely silent clip

        threshold = peak_energy * energy_threshold_ratio
        active_frames = np.where(rms_energies > threshold)[0]

        if len(active_frames) == 0:
            return np.array([], dtype=np.float32)

        pad_samples = int(round((pad_ms / 1000.0) * self.sr))
        start_sample = max(0, active_frames[0] * self.hop_len - pad_samples)
        end_sample = min(len(audio), active_frames[-1] * self.hop_len + self.frame_len + pad_samples)

        return audio[start_sample:end_sample]

    # =====================================================================
    # 3. MEL-FILTERBANK & SPECTROGRAM EXTRACTION
    # =====================================================================
    @staticmethod
    def _hz_to_mel(hz):
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    @staticmethod
    def _mel_to_hz(mel):
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    def _build_mel_filterbank(self):
        """Constructs triangular Mel-scale filter weights from scratch."""
        mel_min = self._hz_to_mel(self.f_min)
        mel_max = self._hz_to_mel(self.f_max)

        # n_mels + 2 points for left edge, center peak, and right edge of each triangle
        mel_points = np.linspace(mel_min, mel_max, self.n_mels + 2)
        hz_points = self._mel_to_hz(mel_points)

        # Convert Hz frequencies to nearest FFT bin indices
        fft_bins = np.floor((self.n_fft + 1) * hz_points / self.sr).astype(int)
        n_freq_bins = self.n_fft // 2 + 1
        filterbank = np.zeros((self.n_mels, n_freq_bins), dtype=np.float32)

        for m in range(1, self.n_mels + 1):
            f_left = fft_bins[m - 1]
            f_center = fft_bins[m]
            f_right = fft_bins[m + 1]

            # Rising slope of triangle
            for k in range(f_left, f_center):
                if f_center > f_left:
                    filterbank[m - 1, k] = (k - f_left) / float(f_center - f_left)

            # Falling slope of triangle
            for k in range(f_center, f_right):
                if f_right > f_center:
                    filterbank[m - 1, k] = (f_right - k) / float(f_right - f_center)

        return filterbank

    def extract_log_mel_spectrogram(self, audio, normalize=True):
        """
        Converts raw 1D audio into a 2D Log-Mel Spectrogram of shape (n_mels, time_steps)
        ready for a CRNN acoustic model.
        """
        if len(audio) < self.frame_len:
            audio = np.pad(audio, (0, self.frame_len - len(audio)))

        # 1. Pre-emphasis filter: boosts high-frequency consonants (S, T, K, F)
        emphasized = np.append(audio[0], audio[1:] - self.pre_emphasis * audio[:-1])

        # 2. Vectorized sliding-window framing using stride_tricks (zero Python loops)
        n_frames = 1 + (len(emphasized) - self.frame_len) // self.hop_len
        shape = (n_frames, self.frame_len)
        strides = (emphasized.strides[0] * self.hop_len, emphasized.strides[0])
        frames = np.lib.stride_tricks.as_strided(emphasized, shape=shape, strides=strides)

        # 3. Apply Hamming window and compute Real FFT Power Spectrum
        windowed_frames = frames * self.window
        mag_spectrum = np.abs(np.fft.rfft(windowed_frames, n=self.n_fft))
        power_spectrum = (1.0 / self.n_fft) * (mag_spectrum ** 2)

        # 4. Project onto Mel-scale filterbank and take natural log
        mel_energies = np.dot(power_spectrum, self.mel_filterbank.T)
        mel_energies = np.maximum(mel_energies, 1e-10)
        log_mel = np.log(mel_energies).T  # Shape: (n_mels, time_steps)

        # 5. Utterance-level Cepstral Mean & Variance Normalization (CMVN)
        if normalize:
            mean = np.mean(log_mel, axis=1, keepdims=True)
            std = np.std(log_mel, axis=1, keepdims=True) + 1e-8
            log_mel = (log_mel - mean) / std

        return log_mel.astype(np.float32)


# =====================================================================
# STANDALONE DIAGNOSTIC TEST
# =====================================================================
if __name__ == "__main__":
    frontend = TalosAudioFrontend(sample_rate=16000, n_mels=64)

    # Generate a 1.5-second synthetic test signal: 0.3s silence + 0.8s speech-like tone + 0.4s silence
    sr = 16000
    t_voice = np.linspace(0, 0.8, int(sr * 0.8), endpoint=False)
    synthetic_voice = 0.4 * np.sin(2 * np.pi * 220 * t_voice) + 0.2 * np.sin(2 * np.pi * 880 * t_voice)
    test_clip = np.concatenate([
        np.zeros(int(sr * 0.3), dtype=np.float32),
        synthetic_voice.astype(np.float32),
        np.zeros(int(sr * 0.4), dtype=np.float32)
    ])

    print(f"[VAD] Raw audio length     : {len(test_clip)} samples ({len(test_clip)/sr:.2f}s)")
    trimmed = frontend.trim_silence(test_clip)
    print(f"[VAD] Trimmed audio length : {len(trimmed)} samples ({len(trimmed)/sr:.2f}s)")

    features = frontend.extract_log_mel_spectrogram(trimmed)
    print(f"[FFT] Log-Mel tensor shape : {features.shape} -> (n_mels, time_frames)")
    print(f"[FFT] Feature mean / std   : {features.mean():.4f} / {features.std():.4f}")
