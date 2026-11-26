import io
import os
import re
import wave
import queue
import threading
import numpy as np

try:
    import winsound

    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

try:
    import scipy.signal

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    import torch
    import torch.nn as nn

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None
    nn = None


class VoiceProfile:
    def __init__(
        self,
        name="T.A.L.O.S. Standard",
        base_pitch_hz=105.0,
        speech_rate=1.0,
        pitch_variance=0.14,
        word_pause_scale=1.0,
        vocal_tract_scale=1.0,
        ring_mod_hz=0.0,
        ring_mod_mix=0.0,
        chorus_mix=0.0,
        bandpass_comms=False,
    ):
        self.name = name
        self.base_pitch_hz = base_pitch_hz
        self.speech_rate = max(0.25, speech_rate)
        self.pitch_variance = pitch_variance
        self.word_pause_scale = max(0.1, word_pause_scale)
        self.vocal_tract_scale = vocal_tract_scale
        self.ring_mod_hz = ring_mod_hz
        self.ring_mod_mix = np.clip(ring_mod_mix, 0.0, 1.0)
        self.chorus_mix = np.clip(chorus_mix, 0.0, 1.0)
        self.bandpass_comms = bandpass_comms

    @classmethod
    def presets(cls):
        return {
            "command": cls(
                name="T.A.L.O.S. Command (Authoritative)",
                base_pitch_hz=92.0,
                speech_rate=0.92,
                pitch_variance=0.12,
                word_pause_scale=1.25,
                vocal_tract_scale=0.94,
                ring_mod_hz=35.0,
                ring_mod_mix=0.15,
                chorus_mix=0.25,
                bandpass_comms=False,
            ),
            "tactical": cls(
                name="T.A.L.O.S. Tactical (Fast & Crisp)",
                base_pitch_hz=112.0,
                speech_rate=1.25,
                pitch_variance=0.08,
                word_pause_scale=0.75,
                vocal_tract_scale=1.0,
                ring_mod_hz=0.0,
                ring_mod_mix=0.0,
                chorus_mix=0.15,
                bandpass_comms=False,
            ),
            "mainframe": cls(
                name="T.A.L.O.S. Classic Mainframe (Monotone)",
                base_pitch_hz=85.0,
                speech_rate=0.88,
                pitch_variance=0.0,
                word_pause_scale=1.4,
                vocal_tract_scale=0.90,
                ring_mod_hz=45.0,
                ring_mod_mix=0.35,
                chorus_mix=0.40,
                bandpass_comms=False,
            ),
        }


class TextToPhonemeEncoder:
    def __init__(self, cmudict_path=None):
        self.vocab = [
            "<PAD>",
            "<UNK>",
            " ",
            ",",
            ".",
            "AA",
            "AE",
            "AH",
            "AO",
            "AW",
            "AY",
            "B",
            "CH",
            "D",
            "DH",
            "EH",
            "ER",
            "EY",
            "F",
            "G",
            "HH",
            "IH",
            "IY",
            "JH",
            "K",
            "L",
            "M",
            "N",
            "NG",
            "OW",
            "OY",
            "P",
            "R",
            "S",
            "SH",
            "T",
            "TH",
            "UH",
            "UW",
            "V",
            "W",
            "Y",
            "Z",
            "ZH",
        ]
        self.phoneme_to_id = {phone: index for index, phone in enumerate(self.vocab)}
        self.lexicon = {
            "hello": ["HH", "AH", "L", "OW"],
            "world": ["W", "ER", "L", "D"],
            "system": ["S", "IH", "S", "T", "AH", "M"],
            "active": ["AE", "K", "T", "IH", "V"],
            "talos": ["T", "EY", "L", "AA", "S"],
            "online": ["AA", "N", "L", "AY", "N"],
            "project": ["P", "R", "AA", "JH", "EH", "K", "T"],
            "hephaestus": ["HH", "AH", "F", "EH", "S", "T", "AH", "S"],
            "all": ["AO", "L"],
            "systems": ["S", "IH", "S", "T", "AH", "M", "Z"],
            "operational": ["AA", "P", "ER", "EY", "SH", "AH", "N", "AH", "L"],
            "ready": ["R", "EH", "D", "IY"],
            "for": ["F", "AO", "R"],
            "deployment": ["D", "IH", "P", "L", "OY", "M", "AH", "N", "T"],
        }
        self.digraph_rules = {
            "sh": "SH",
            "ch": "CH",
            "th": "TH",
            "ph": "F",
            "ng": "NG",
            "ee": "IY",
            "ea": "IY",
            "oo": "UW",
            "ou": "AW",
            "ow": "OW",
            "ai": "EY",
            "ay": "EY",
            "oi": "OY",
            "oy": "OY",
            "er": "ER",
            "ar": "AA",
            "or": "AO",
        }
        self.char_rules = {
            "a": "AE",
            "e": "EH",
            "i": "IH",
            "o": "AA",
            "u": "AH",
            "b": "B",
            "c": "K",
            "d": "D",
            "f": "F",
            "g": "G",
            "h": "HH",
            "j": "JH",
            "k": "K",
            "l": "L",
            "m": "M",
            "n": "N",
            "p": "P",
            "q": "K",
            "r": "R",
            "s": "S",
            "t": "T",
            "v": "V",
            "w": "W",
            "x": "K",
            "y": "Y",
            "z": "Z",
        }

        if cmudict_path and os.path.exists(cmudict_path):
            self._load_cmudict(cmudict_path)

    def _load_cmudict(self, filepath):
        loaded_count = 0
        with open(filepath, "r", encoding="latin-1") as cmudict_file:
            for line in cmudict_file:
                if line.startswith(";;;") or not line.strip():
                    continue
                parts = line.strip().split()
                word = re.sub(r"\(\d+\)$", "", parts[0]).lower()
                phones = [re.sub(r"\d", "", phone) for phone in parts[1:]]
                if word not in self.lexicon:
                    self.lexicon[word] = phones
                    loaded_count += 1
        print(f"[G2P] Loaded {loaded_count} words from CMU Dictionary.")

    def normalize_text(self, text):
        text = text.lower()
        text = text.replace("t.a.l.o.s", "talos").replace("t.a.l.o.s.", "talos")

        tags = []
        def _stash_tag(match):
            tags.append(match.group(0))
            return f"__TAG{len(tags) - 1}__"

        text = re.sub(r'<(pause=\d+ms|pitch=\d+)>', _stash_tag, text)
        text = re.sub(r"([,.!?])", r" \1 ", text)
        return re.sub(r"[^a-z0-9_.,!? \s]", "", text)

        for idx, tag in enumerate(tags):
            text = text.replace(f"__tag{idx}__",tag)

        return text.strip()
    
    def _fallback_g2p(self, word):
        phones = []
        index = 0
        while index < len(word):
            digraph = word[index : index + 2]
            if digraph in self.digraph_rules:
                phones.append(self.digraph_rules[digraph])
                index += 2
            else:
                phones.append(self.char_rules.get(word[index], "<UNK>"))
                index += 1
        return phones

    def encode(self, text):
        clean_text = self.normalize_text(text)
        tokens = clean_text.split()
        phoneme_sequence = []

        for i, token in enumerate(tokens):
            if token.startswith('<') and token.endswith('>'):
                phoneme_sequence.append(token)
            elif token in [',']:
                phoneme_sequence.append(",")
            elif token in (".", "!", "?"):
                phoneme_sequence.append(".")
            elif token in self.lexicon:
                phoneme_sequence.extend(self.lexicon[token])
            else:
                phoneme_sequence.extend(self._fallback_g2p(token))

            if i < len(tokens) - 1
                and tokens[i + 1] not in [',','.','!','?'] 
                and not tokens[i].startswith('<'):
                phoneme_sequence.append(" ")
                

        ids = [self.phoneme_to_id.get(p, 1) for p in phoneme_sequence]
        return phoneme_sequence, np.array(ids)


class FormantSpectrogramGenerator:
    def __init__(self, sample_rate=22050, n_mels=80, voice_profile=None):
        self.sr = sample_rate
        self.n_mels = n_mels
        self.profile = voice_profile or VoiceProfile()

        min_mel = 2595.0 * np.log10(1.0)
        max_mel = 2595.0 * np.log10(1.0 + (self.sr / 2.0) / 700.0)
        mels = np.linspace(min_mel, max_mel, self.n_mels)
        self.bin_freqs = 700.0 * (10.0 ** (mels / 2595.0) - 1.0)

        self.phoneme_physics = {
            " ": (0, 0, 0, 0.0, 0.0, 6),
            ",": (0, 0, 0, 0.0, 0.0, 16),
            ".": (0, 0, 0, 0.0, 0.0, 24),
            "AA": (730, 1090, 2440, 1.0, 0.02, 11),
            "AE": (660, 1720, 2410, 1.0, 0.02, 11),
            "AH": (520, 1190, 2390, 1.0, 0.02, 9),
            "AO": (570, 840, 2410, 1.0, 0.02, 11),
            "AW": (700, 1000, 2400, 1.0, 0.02, 13),
            "AY": (700, 1500, 2450, 1.0, 0.02, 13),
            "EH": (530, 1840, 2480, 1.0, 0.02, 10),
            "ER": (490, 1350, 1690, 1.0, 0.03, 11),
            "EY": (450, 2100, 2650, 1.0, 0.02, 12),
            "IH": (390, 1990, 2550, 1.0, 0.02, 9),
            "IY": (270, 2290, 3010, 1.0, 0.02, 11),
            "OW": (450, 800, 2400, 1.0, 0.02, 12),
            "OY": (500, 900, 2400, 1.0, 0.02, 13),
            "UH": (440, 1020, 2240, 1.0, 0.02, 9),
            "UW": (300, 870, 2240, 1.0, 0.02, 11),
            "L": (350, 1050, 2400, 0.8, 0.02, 7),
            "M": (280, 900, 2200, 0.7, 0.01, 8),
            "N": (280, 1400, 2200, 0.7, 0.01, 8),
            "NG": (280, 1900, 2300, 0.7, 0.01, 8),
            "R": (420, 1300, 1600, 0.8, 0.02, 7),
            "W": (300, 610, 2200, 0.8, 0.01, 7),
            "Y": (280, 2100, 2800, 0.8, 0.01, 7),
            "S": (0, 0, 5500, 0.0, 0.85, 9),
            "SH": (0, 0, 3200, 0.0, 0.85, 9),
            "Z": (250, 1500, 5200, 0.5, 0.70, 8),
            "ZH": (250, 1500, 3000, 0.5, 0.70, 8),
            "F": (0, 0, 4500, 0.0, 0.50, 8),
            "V": (250, 1200, 4200, 0.5, 0.40, 7),
            "TH": (0, 0, 4800, 0.0, 0.45, 8),
            "DH": (250, 1300, 4500, 0.5, 0.35, 7),
            "HH": (500, 1500, 2500, 0.0, 0.55, 7),
            "P": (0, 0, 1500, 0.0, 0.60, 5),
            "B": (200, 900, 2000, 0.5, 0.35, 5),
            "T": (0, 0, 4000, 0.0, 0.75, 5),
            "D": (200, 1600, 2600, 0.5, 0.40, 5),
            "K": (0, 0, 2200, 0.0, 0.70, 5),
            "G": (200, 1800, 2400, 0.5, 0.40, 5),
            "CH": (0, 0, 3500, 0.0, 0.80, 7),
            "JH": (250, 1700, 3200, 0.5, 0.65, 7),
        }

    def forward(self, phoneme_sequence, profile_override=None):
        profile = profile_override if profile_override else self.profile
        frames = []

        for phone_index, phone in enumerate(phoneme_sequence):
            f1, f2, f3, voiced_gain, noise_gain, base_duration = (
                self.phoneme_physics.get(
                    phone,
                    (500, 1500, 2500, 0.3, 0.3, 6),
                )
            )

            if phone in (" ", ",", "."):
                duration = max(
                    2,
                    int(
                        round(
                            base_duration
                            * profile.word_pause_scale
                            / profile.speech_rate
                        )
                    ),
                )
            else:
                duration = max(
                    2,
                    int(round(base_duration / profile.speech_rate)),
                )

            f1 *= profile.vocal_tract_scale
            f2 *= profile.vocal_tract_scale
            if voiced_gain > 0:
                f3 *= profile.vocal_tract_scale

            progress = phone_index / max(1, len(phoneme_sequence) - 1)
            pitch_multiplier = (
                1.0 + profile.pitch_variance * 0.5 - profile.pitch_variance * progress
            )
            harmonics = self._generate_harmonic_comb(
                profile.base_pitch_hz * pitch_multiplier
            )

            for time_index in range(duration):
                envelope = np.sin(np.pi * (time_index + 0.5) / duration) ** 0.5
                if phone in ("P", "B", "T", "D", "K", "G"):
                    envelope = 1.0 if time_index == duration - 1 else 0.05

                tract_filter = np.zeros(self.n_mels) + 0.02
                if f1 > 0:
                    tract_filter += np.exp(-0.5 * ((self.bin_freqs - f1) / 90.0) ** 2)
                if f2 > 0:
                    tract_filter += 0.7 * np.exp(
                        -0.5 * ((self.bin_freqs - f2) / 130.0) ** 2
                    )
                if f3 > 0:
                    tract_filter += 0.4 * np.exp(
                        -0.5 * ((self.bin_freqs - f3) / 180.0) ** 2
                    )

                noise_shape = np.exp(
                    -0.5 * ((self.bin_freqs - max(2000, f3)) / 1200.0) ** 2
                )
                voiced_energy = voiced_gain * harmonics * tract_filter
                unvoiced_energy = (
                    noise_gain * noise_shape * (0.7 + 0.3 * np.random.rand(self.n_mels))
                )
                total_magnitude = envelope * (voiced_energy + unvoiced_energy) + 1e-4
                frames.append(np.log(total_magnitude))

        spectrogram = np.array(frames).T
        kernel = np.array([0.2, 0.6, 0.2])
        for mel_index in range(self.n_mels):
            spectrogram[mel_index] = np.convolve(
                spectrogram[mel_index],
                kernel,
                mode="same",
            )
        return spectrogram

    def _generate_harmonic_comb(self, pitch_hz):
        comb = np.zeros(self.n_mels)
        for harmonic in range(1, 35):
            freq = pitch_hz * harmonic
            if freq >= self.sr / 2.0:
                break
            amplitude = 1.0 / (harmonic**0.75)
            comb += amplitude * np.exp(-0.5 * ((self.bin_freqs - freq) / 35.0) ** 2)
        return comb


class PureMathVocoder:
    def __init__(
        self,
        sample_rate=22050,
        n_fft=1024,
        hop_length=256,
        n_mels=80,
        force_numpy=False,
    ):
        self.sr = sample_rate
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.n_mels = n_mels
        self.use_scipy = HAS_SCIPY and not force_numpy
        self.window = np.hanning(self.n_fft)
        self.mel_basis = self._create_mel_filterbank()
        self.inv_mel_basis = np.linalg.pinv(self.mel_basis)

    def _hz_to_mel(self, hz):
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    def _mel_to_hz(self, mel):
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    def _create_mel_filterbank(self):
        min_mel = self._hz_to_mel(0)
        max_mel = self._hz_to_mel(self.sr / 2.0)
        mels = np.linspace(min_mel, max_mel, self.n_mels + 2)
        hz_points = self._mel_to_hz(mels)
        bin_points = np.floor((self.n_fft + 1) * hz_points / self.sr).astype(int)
        bin_points = np.clip(bin_points, 0, self.n_fft // 2)

        filters = np.zeros((self.n_mels, int(self.n_fft // 2 + 1)))
        for mel_index in range(1, self.n_mels + 1):
            left = bin_points[mel_index - 1]
            center = bin_points[mel_index]
            right = bin_points[mel_index + 1]
            if center > left:
                for bin_index in range(left, center):
                    filters[mel_index - 1, bin_index] = (bin_index - left) / (
                        center - left
                    )
            if right > center:
                for bin_index in range(center, right):
                    filters[mel_index - 1, bin_index] = (right - bin_index) / (
                        right - center
                    )
        return filters

    def _stft(self, audio):
        if self.use_scipy:
            _, _, stft_matrix = scipy.signal.stft(
                audio,
                fs=self.sr,
                window=self.window,
                nperseg=self.n_fft,
                noverlap=self.n_fft - self.hop_length,
            )
            return stft_matrix

        pad_len = self.n_fft // 2
        padded_audio = np.pad(
            audio,
            (pad_len, pad_len),
            mode="reflect",
        )
        num_frames = 1 + (len(padded_audio) - self.n_fft) // self.hop_length
        stft_matrix = np.zeros(
            (self.n_fft // 2 + 1, num_frames),
            dtype=np.complex128,
        )
        for frame_index in range(num_frames):
            start = frame_index * self.hop_length
            frame = padded_audio[start : start + self.n_fft] * self.window
            stft_matrix[:, frame_index] = np.fft.rfft(frame)
        return stft_matrix

    def _istft(self, stft_matrix):
        if self.use_scipy:
            _, audio = scipy.signal.istft(
                stft_matrix,
                fs=self.sr,
                window=self.window,
                nperseg=self.n_fft,
                noverlap=self.n_fft - self.hop_length,
            )
            return audio

        num_frames = stft_matrix.shape[1]
        expected_len = self.n_fft + self.hop_length * (num_frames - 1)
        audio = np.zeros(expected_len)
        window_sum = np.zeros(expected_len)

        for frame_index in range(num_frames):
            start = frame_index * self.hop_length
            frame = np.fft.irfft(
                stft_matrix[:, frame_index],
                n=self.n_fft,
            )
            audio[start : start + self.n_fft] += frame * self.window
            window_sum[start : start + self.n_fft] += self.window**2

        nonzero = window_sum > 1e-8
        audio[nonzero] /= window_sum[nonzero]
        pad_len = self.n_fft // 2
        return audio[pad_len:-pad_len]

    def griffin_lim(self, log_mel_spec, n_iter=48):
        mel_spec = np.exp(log_mel_spec)
        linear_spec = np.maximum(
            1e-10,
            np.dot(self.inv_mel_basis, mel_spec),
        )
        angles = np.exp(2j * np.pi * np.random.rand(*linear_spec.shape))
        complex_spec = linear_spec * angles

        for _ in range(n_iter):
            audio = self._istft(complex_spec)
            stft_matrix = self._stft(audio)
            min_frames = min(
                linear_spec.shape[1],
                stft_matrix.shape[1],
            )
            stft_matrix = stft_matrix[:, :min_frames]
            target_magnitude = linear_spec[:, :min_frames]
            angles = np.exp(1j * np.angle(stft_matrix))
            complex_spec = target_magnitude * angles

        final_audio = self._istft(complex_spec)
        peak = np.max(np.abs(final_audio))
        if peak > 0:
            final_audio = final_audio / (peak + 1e-8)
        return final_audio

    def _to_wav_bytes(self, waveform):
        pcm_data = np.int16(waveform * 32767)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sr)
            wav_file.writeframes(pcm_data.tobytes())
        return buffer.getvalue()

    def save_wav(self, filename, waveform):
        with open(filename, "wb") as wav_file:
            wav_file.write(self._to_wav_bytes(waveform))

    def speak_realtime(self, waveform, async_play=False):
        if not HAS_WINSOUND:
            print(
                "[Audio] winsound is only available on Windows. "
                "Use save_wav() instead."
            )
            return

        wav_bytes = self._to_wav_bytes(waveform)
        flags = winsound.SND_MEMORY
        if async_play:
            flags |= winsound.SND_ASYNC
        winsound.PlaySound(wav_bytes, flags)


class TalosTTS:
    def __init__(self, voice_profile=None, cmudict_path=None, force_numpy=False):
        self.profile = voice_profile if voice_profile else VoiceProfile.presets()["command"]
        self.g2p = TextToPhonemeEncoder(cmudict_path=cmudict_path)
        self.acoustic = FormantSpectrogramGenerator(voice_profile=self.profile)
        self.vocoder = PureMathVocoder(force_numpy=force_numpy)
        self.dsp = TalosDSPChain(sample_rate=self.vocoder.sr)

    def say(self, text, profile=None, save_path=None, play_audio=True):
        active_profile = profile if profile else self.profile
        phonemes, _ = self.g2p.encode(text)
        mel_spec = self.acoustic.forward(phonemes, profile_override=active_profile)
        raw_waveform = self.vocoder.griffin_lim(mel_spec, n_iter=48)
        
        # Apply post-processing DSP effects chain
        waveform = self.dsp.process(raw_waveform, active_profile)
        
        if save_path:
            self.vocoder.save_wav(save_path, waveform)
        if play_audio:
            self.vocoder.speak_realtime(waveform)
            
        return waveform


if __name__ == "__main__":
    tts = TalosTTS()
    presets = VoiceProfile.presets()

    print(f"Speaking with: {presets['command'].name}")
    tts.say(
        "Talos project hephaestus. All systems operational.",
        profile=presets["command"],
        save_path="talos_command.wav",
        play_audio=True,
    )

    custom_voice = VoiceProfile(
        name="T.A.L.O.S. Custom Override",
        base_pitch_hz=130.0,
        speech_rate=1.15,
        pitch_variance=0.22,
        word_pause_scale=0.8,
        vocal_tract_scale=1.05,
    )
    print(f"Speaking with: {custom_voice.name}")
    tts.say(
        "System active, ready for deployment.",
        profile=custom_voice,
        play_audio=True,
    )
