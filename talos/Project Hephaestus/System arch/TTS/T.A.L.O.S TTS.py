import io
import os
import re
import wave
import queue
import threading
import urllib.request
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
        name="T.A.L.O.S. Natural Human",
        base_pitch_hz=108.0,
        speech_rate=1.0,
        pitch_variance=0.18,
        word_pause_scale=1.0,
        vocal_tract_scale=1.0,
        breathiness=0.14,  # Subtle vocal cord air turbulence (0.05 to 0.30)
        pitch_jitter=0.012,  # Natural human vocal cord micro-variation
        room_ambience=0.18,  # Subtle acoustic room warmth (replaces robotic chorus)
        ring_mod_hz=0.0,  # Kept at 0.0 for natural human voice
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
        self.breathiness = np.clip(breathiness, 0.0, 0.5)
        self.pitch_jitter = np.clip(pitch_jitter, 0.0, 0.05)
        self.room_ambience = np.clip(room_ambience, 0.0, 0.5)
        self.ring_mod_hz = ring_mod_hz
        self.ring_mod_mix = np.clip(ring_mod_mix, 0.0, 1.0)
        self.chorus_mix = np.clip(chorus_mix, 0.0, 1.0)
        self.bandpass_comms = bandpass_comms

    @classmethod
    def presets(cls):
        return {
            "command": cls(
                name="T.A.L.O.S. Crisp Baritone",
                base_pitch_hz=106.0,
                speech_rate=0.96,
                pitch_variance=0.20,
                word_pause_scale=1.10,
                vocal_tract_scale=0.98,
                breathiness=0.10,
                pitch_jitter=0.010,
                room_ambience=0.05
            ),
            "tactical": cls(
                name="T.A.L.O.S. Clear Tenor",
                base_pitch_hz=126.0,
                speech_rate=1.05,
                pitch_variance=0.22,
                word_pause_scale=0.95,
                vocal_tract_scale=1.02,
                breathiness=0.12,
                pitch_jitter=0.012,
                room_ambience=0.04
            ),
            "warm_alto": cls(
                name="T.A.L.O.S. Clear Alto",
                base_pitch_hz=188.0,
                speech_rate=1.00,
                pitch_variance=0.24,
                word_pause_scale=1.00,
                vocal_tract_scale=1.14,
                breathiness=0.14,
                pitch_jitter=0.012,
                room_ambience=0.05
            )
        }

class TextToPhonemeEncoder:
    def __init__(self, cmudict_path=None, auto_download=True):
        # Include stressed & unstressed phoneme variants in vocabulary
        base_vowels = [
            "AA",
            "AE",
            "AH",
            "AO",
            "AW",
            "AY",
            "EH",
            "ER",
            "EY",
            "IH",
            "IY",
            "OW",
            "OY",
            "UH",
            "UW",
        ]
        stressed_vowels = [f"{v}{s}" for v in base_vowels for s in ("0", "1", "2")]
        consonants = [
            "B",
            "CH",
            "D",
            "DH",
            "F",
            "G",
            "HH",
            "JH",
            "K",
            "L",
            "M",
            "N",
            "NG",
            "P",
            "R",
            "S",
            "SH",
            "T",
            "TH",
            "V",
            "W",
            "Y",
            "Z",
            "ZH",
        ]
        self.vocab = (
            ["<PAD>", "<UNK>", " ", ",", "."]
            + base_vowels
            + stressed_vowels
            + consonants
        )
        self.phoneme_to_id = {p: i for i, p in enumerate(self.vocab)}

        # Custom sci-fi overrides with primary stress (1) marked
        self.lexicon = {
            "talos": ["T", "EY1", "L", "AA0", "S"],
            "hephaestus": ["HH", "AH0", "F", "EH1", "S", "T", "AH0", "S"],
        }

        if cmudict_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            cmudict_path = os.path.join(script_dir, "cmudict.dict")

        if not os.path.exists(cmudict_path) and auto_download:
            self._download_cmudict(cmudict_path)

        if os.path.exists(cmudict_path):
            self._load_cmudict(cmudict_path)

        self.digraph_rules = {
            "sh": "SH",
            "ch": "CH",
            "th": "TH",
            "ph": "F",
            "ng": "NG",
            "ee": "IY1",
            "ea": "IY1",
            "oo": "UW1",
            "ou": "AW1",
            "ow": "OW1",
            "ai": "EY1",
            "ay": "EY1",
            "oi": "OY1",
            "oy": "OY1",
            "er": "ER0",
            "ar": "AA1",
            "or": "AO1",
        }

        self.char_rules = {
            "a": "AE1",
            "e": "EH1",
            "i": "IH1",
            "o": "AA1",
            "u": "AH1",
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

    def _download_cmudict(self, save_path):
        """Fetches CMUdict from local 'cmudict' package first, or falls back to GitHub."""
        try:
            import cmudict as cmu_pkg
            entries = cmu_pkg.dict()
            with open(save_path, 'w', encoding='utf-8') as f:
                for word, pronunciations in entries.items():
                    for phones in pronunciations:
                        f.write(f"{word} {' '.join(phones)}\n")
            print(f"[G2P] Extracted {len(entries):,} words from local cmudict package.")
            return
        except ImportError:
            pass

        url = "https://githubusercontent.com"
        print("[G2P] Downloading full 134,000-word CMU Pronouncing Dictionary...")
        try:
            urllib.request.urlretrieve(url, save_path)
            print(f"[G2P] Saved dictionary cache to: {save_path}")
        except Exception as e:
            print(f"[G2P] Offline mode active: Could not reach GitHub ({e}).")

    def _load_cmudict(self, filepath):
        """Parses CMUdict entries while preserving 0/1/2 lexical stress markers."""
        loaded_count = 0
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(";;;"):
                    continue
                line = line.split("#", 1)[0].strip()
                parts = line.split()
                if len(parts) < 2:
                    continue
                word = re.sub(r"\(\d+\)$", "", parts[0]).lower()
                phones = parts[1:]  # Keep stress markers (e.g., EY1, AH0)
                if word not in self.lexicon:
                    self.lexicon[word] = phones
                    loaded_count += 1
        print(f"[G2P] Loaded {loaded_count:,} words with lexical stress markers.")

    def encode(self, text):
        clean_text = self.normalize_text(text)
        tokens = clean_text.split()
        phoneme_sequence = []

        for i, token in enumerate(tokens):
            if token.startswith("<") and token.endswith(">"):
                phoneme_sequence.append(token)
            elif token in [","]:
                phoneme_sequence.append(",")
            elif token in [".", "!", "?"]:
                phoneme_sequence.append(".")
            elif token in self.lexicon:
                phoneme_sequence.extend(self.lexicon[token])
            else:
                phoneme_sequence.extend(self._fallback_g2p(token))

            if (
                i < len(tokens) - 1
                and tokens[i + 1] not in [",", ".", "!", "?"]
                and not tokens[i + 1].startswith("<")
                and not token.startswith("<")
            ):
                phoneme_sequence.append(" ")

        ids = [self.phoneme_to_id.get(p, 1) for p in phoneme_sequence]
        return phoneme_sequence, np.array(ids)

    def normalize_text(self, text):
        text = text.lower()
        text = text.replace("t.a.l.o.s", "talos").replace("t.a.l.o.s.", "talos")

        tags = []

        def _stash_tag(match):
            tags.append(match.group(0))
            return f"__tag{len(tags) - 1}__"

        text = re.sub(r"<(pause=\d+(?:ms)?|pitch=\d+)>", _stash_tag, text)
        text = re.sub(r"([,.!?])", r" \1 ", text)
        text = re.sub(r"[^a-z0-9_.,!? \s]", "", text)
        for idx, tag in enumerate(tags):
            text = text.replace(f"__tag{idx}__", tag)
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


class TimeDomainFormantPlanner:
    """
    Converts stressed phoneme sequences into smooth, continuous vocal-tract
    control trajectories (F0 pitch, F1/F2/F3 formants, bandwidths, and noise)
    for direct time-domain synthesis without Griffin-Lim phase distortion.
    """
    def __init__(self, sample_rate=22050, frame_ms=5.0, voice_profile=None):
        self.sr = sample_rate
        self.frame_ms = frame_ms
        self.samples_per_frame = int(round((frame_ms / 1000.0) * sample_rate))
        self.profile = voice_profile if voice_profile else VoiceProfile()

        # (F1_Hz, F2_Hz, F3_Hz, Voiced_Gain, Noise_Gain, Fric_Center_Hz, Fric_BW_Hz, Base_MS)
        self.phoneme_physics = {
            ' ':  (500,  1500, 2500, 0.0,  0.0,  3000, 1000, 65),
            ',':  (500,  1500, 2500, 0.0,  0.0,  3000, 1000, 180),
            '.':  (500,  1500, 2500, 0.0,  0.0,  3000, 1000, 280),
            # Vowels
            'AA': (730,  1090, 2440, 1.0,  0.01, 3000, 1200, 125),
            'AE': (660,  1720, 2410, 1.0,  0.01, 3000, 1200, 125),
            'AH': (520,  1190, 2390, 1.0,  0.01, 3000, 1200, 100),
            'AO': (570,  840,  2410, 1.0,  0.01, 3000, 1200, 125),
            'AW': (700,  1000, 2400, 1.0,  0.01, 3000, 1200, 145),
            'AY': (700,  1500, 2450, 1.0,  0.01, 3000, 1200, 145),
            'EH': (530,  1840, 2480, 1.0,  0.01, 3000, 1200, 110),
            'ER': (490,  1350, 1690, 1.0,  0.02, 2500, 1000, 120),
            'EY': (450,  2100, 2650, 1.0,  0.01, 3000, 1200, 135),
            'IH': (390,  1990, 2550, 1.0,  0.01, 3000, 1200, 95),
            'IY': (270,  2290, 3010, 1.0,  0.01, 3200, 1200, 120),
            'OW': (450,  800,  2400, 1.0,  0.01, 3000, 1200, 135),
            'OY': (500,  900,  2400, 1.0,  0.01, 3000, 1200, 145),
            'UH': (440,  1020, 2240, 1.0,  0.01, 3000, 1200, 95),
            'UW': (300,  870,  2240, 1.0,  0.01, 3000, 1200, 120),
            # Nasals & Liquids
            'L':  (350,  1050, 2400, 0.85, 0.01, 2500, 1000, 75),
            'M':  (280,  900,  2200, 0.75, 0.00, 2000, 800,  85),
            'N':  (280,  1400, 2200, 0.75, 0.00, 2200, 800,  85),
            'NG': (280,  1900, 2300, 0.75, 0.00, 2200, 800,  90),
            'R':  (420,  1300, 1600, 0.85, 0.01, 2200, 900,  75),
            'W':  (300,  610,  2200, 0.85, 0.01, 2000, 800,  75),
            'Y':  (280,  2100, 2800, 0.85, 0.01, 2800, 900,  75),
            # Fricatives
            'S':  (400,  1600, 2600, 0.0,  0.55, 5600, 1400, 100),
            'SH': (400,  1600, 2600, 0.0,  0.55, 3100, 1100, 105),
            'Z':  (250,  1500, 2600, 0.55, 0.42, 5400, 1400, 90),
            'ZH': (250,  1500, 2600, 0.55, 0.42, 3000, 1100, 90),
            'F':  (400,  1400, 2400, 0.0,  0.28, 4600, 2200, 90),
            'V':  (250,  1200, 2400, 0.55, 0.22, 4200, 2000, 80),
            'TH': (400,  1400, 2400, 0.0,  0.25, 4800, 2400, 90),
            'DH': (250,  1300, 2400, 0.55, 0.20, 4400, 2000, 80),
            'HH': (500,  1500, 2500, 0.0,  0.32, 2200, 1600, 75),
            # Plosives
            'P':  (400,  1100, 2100, 0.0,  0.40, 1600, 1200, 65),
            'B':  (200,  900,  2000, 0.50, 0.25, 1500, 1100, 65),
            'T':  (400,  1600, 2600, 0.0,  0.50, 4200, 1500, 65),
            'D':  (200,  1600, 2600, 0.50, 0.30, 3800, 1400, 65),
            'K':  (400,  1800, 2400, 0.0,  0.45, 2200, 1100, 70),
            'G':  (200,  1800, 2400, 0.50, 0.28, 2100, 1100, 70),
            'CH': (400,  1700, 2600, 0.0,  0.55, 3400, 1200, 85),
            'JH': (250,  1700, 2600, 0.50, 0.42, 3200, 1200, 85),
        }

    def forward(self, phoneme_sequence, profile_override=None):
        prof = profile_override if profile_override else self.profile
        raw_trajectory = []

        spoken_tokens = [p for p in phoneme_sequence if not p.startswith('<')]
        total_spoken = max(1, len(spoken_tokens) - 1)
        spoken_idx = 0

        active_base_pitch = prof.base_pitch_hz
        prev_f1, prev_f2, prev_f3 = 500.0, 1500.0, 2500.0
        prev_voiced = False

        clean_phones = [p for p in phoneme_sequence if not p.startswith('<')]
        clean_idx = 0

        # Nasal anti-resonance zero frequencies (oral cavity side-branch absorption)
        nasal_zeros = {'M': 1050.0, 'N': 1450.0, 'NG': 1850.0}

        for raw_phone in phoneme_sequence:
            if raw_phone.startswith('<pitch='):
                active_base_pitch = float(re.search(r'\d+', raw_phone).group())
                continue

            if raw_phone.startswith('<pause='):
                ms = float(re.search(r'\d+', raw_phone).group())
                n_frames = max(1, int(round(ms / self.frame_ms)))
                for _ in range(n_frames):
                    raw_trajectory.append((
                        active_base_pitch, prev_f1, prev_f2, prev_f3,
                        0.0, 0.0, 3000.0, 1000.0, 0.0, 1200.0
                    ))
                prev_voiced = False
                continue

            stress = None
            if raw_phone[-1] in ('0', '1', '2'):
                stress = int(raw_phone[-1])
                phone = raw_phone[:-1]
            else:
                phone = raw_phone

            next_voiced = False
            if clean_idx + 1 < len(clean_phones):
                nxt = clean_phones[clean_idx + 1]
                nxt_base = nxt[:-1] if nxt[-1] in ('0', '1', '2') else nxt
                nxt_physics = self.phoneme_physics.get(nxt_base)
                if nxt_physics and nxt_physics[3] > 0.4:
                    next_voiced = True
            clean_idx += 1

            f1, f2, f3, v_gain, n_gain, fric_hz, fric_bw, base_ms = self.phoneme_physics.get(
                phone, (500, 1500, 2500, 0.3, 0.2, 3000, 1200, 75)
            )

            # Determine nasal coupling and anti-resonance notch frequency
            is_nasal = phone in nasal_zeros
            target_nasal_mix = 0.85 if is_nasal else 0.0
            target_anti_hz = nasal_zeros.get(phone, 1200.0) * prof.vocal_tract_scale

            stress_pitch, stress_dur, stress_amp = 1.0, 1.0, 1.0
            if stress == 1:
                stress_pitch, stress_dur, stress_amp = 1.12, 1.22, 1.12
            elif stress == 2:
                stress_pitch, stress_dur, stress_amp = 1.05, 1.08, 1.04
            elif stress == 0:
                stress_pitch, stress_dur, stress_amp = 0.96, 0.82, 0.88
                f1 = 0.8 * f1 + 0.2 * 500.0
                f2 = 0.8 * f2 + 0.2 * 1500.0

            if phone in [' ', ',', '.']:
                dur_ms = (base_ms * prof.word_pause_scale) / prof.speech_rate
            else:
                dur_ms = (base_ms * stress_dur) / prof.speech_rate

            n_frames = max(2, int(round(dur_ms / self.frame_ms)))

            target_f1 = f1 * prof.vocal_tract_scale
            target_f2 = f2 * prof.vocal_tract_scale
            target_f3 = f3 * prof.vocal_tract_scale

            progress = spoken_idx / total_spoken
            spoken_idx += 1
            arch = np.sin(np.pi * min(1.0, progress * 1.15)) * (prof.pitch_variance * 0.45)
            declination = -prof.pitch_variance * 0.65 * progress
            phrase_pitch = active_base_pitch * (1.0 + arch + declination) * stress_pitch

            is_voiced = v_gain > 0.4

            for t in range(n_frames):
                frac = t / max(1, n_frames - 1)
                glide = 0.5 - 0.5 * np.cos(np.pi * min(1.0, frac / 0.65))
                cur_f1 = (1.0 - glide) * prev_f1 + glide * target_f1
                cur_f2 = (1.0 - glide) * prev_f2 + glide * target_f2
                cur_f3 = (1.0 - glide) * prev_f3 + glide * target_f3

                if phone in ['P', 'B', 'T', 'D', 'K', 'G']:
                    if frac < 0.60:
                        env = 0.02
                    elif frac < 0.82:
                        env = 1.25
                    else:
                        env = 0.45
                elif is_voiced:
                    attack = min(1.0, frac / 0.20) if not prev_voiced else 1.0
                    release = min(1.0, (1.0 - frac) / 0.20) if not next_voiced else 1.0
                    env = (0.35 + 0.65 * min(attack, release)) * stress_amp
                else:
                    env = np.sin(np.pi * (t + 0.5) / n_frames) ** 0.35

                syllable_arc = 1.0 + 0.03 * np.sin(np.pi * frac)
                jitter = 1.0 + np.random.uniform(-prof.pitch_jitter * 0.5, prof.pitch_jitter * 0.5)
                cur_pitch = phrase_pitch * syllable_arc * jitter

                raw_trajectory.append((
                    cur_pitch, cur_f1, cur_f2, cur_f3,
                    v_gain * env, n_gain * env, fric_hz, fric_bw,
                    target_nasal_mix, target_anti_hz
                ))

            if is_voiced:
                prev_f1, prev_f2, prev_f3 = target_f1, target_f2, target_f3
            prev_voiced = is_voiced

        if not raw_trajectory:
            return []

        arr = np.array(raw_trajectory, dtype=np.float64)
        smooth_kernel = np.array([0.15, 0.2, 0.3, 0.2, 0.15])
        for col in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
            arr[:, col] = np.convolve(arr[:, col], smooth_kernel, mode='same')

        return [tuple(row) for row in arr]

    def _generate_harmonic_comb(self, pitch_hz):
        """Models a natural human glottal source with warm -12dB/octave spectral tilt."""
        comb = np.zeros(self.n_mels)
        for harmonic in range(1, 45):
            freq = pitch_hz * harmonic
            if freq >= self.sr / 2.0:
                break
            # Steeper roll-off (-1.15 exponent) creates warm human chest resonance instead of buzz
            amplitude = 1.0 / (harmonic**1.15)
            # Boost fundamental (F0) and 2nd harmonic slightly for natural vocal body
            if harmonic == 1:
                amplitude *= 1.35
            elif harmonic == 2:
                amplitude *= 1.15
            comb += amplitude * np.exp(-0.5 * ((self.bin_freqs - freq) / 26.0) ** 2)
        return comb


class TimeDomainGlottalVocoder:
    """
    5-Formant Time-Domain Vocal Tract Synthesizer with Nasal Anti-Resonances.
    Combines F1-F3 oral formants, F4-F5 fixed laryngeal resonators, and a
    time-varying biquad notch filter for realistic nasal consonants.
    """
    def __init__(self, sample_rate=22050, frame_ms=5.0):
        self.sr = sample_rate
        self.samples_per_frame = int(round((frame_ms / 1000.0) * sample_rate))

    def _rosenberg_glottal_wave(self, pitch_track):
        n_samples = len(pitch_track)
        phase = np.cumsum(pitch_track / self.sr) % 1.0

        # Sharper glottal closure (tp=0.42, tn=0.58) generates richer upper harmonics for clarity
        tp = 0.42
        tn = 0.58

        pulse = np.zeros(n_samples)
        open_mask = phase < tp
        close_mask = (phase >= tp) & (phase < tn)

        p_open = phase[open_mask] / tp
        pulse[open_mask] = 3.0 * (p_open ** 2) - 2.0 * (p_open ** 3)

        p_close = (phase[close_mask] - tp) / (tn - tp)
        pulse[close_mask] = 1.0 - (p_close ** 2)

        # Lip radiation derivative (+6dB/oct lift) without heavy low-pass muffling
        glottal_source = np.diff(pulse, prepend=0.0)
        return glottal_source

    def synthesize(self, trajectory, breathiness=0.12, vocal_tract_scale=1.0):
        if not trajectory:
            return np.zeros(self.sr // 10)

        step = self.samples_per_frame
        n_frames = len(trajectory)
        n_samples = n_frames * step

        frame_x = np.arange(n_frames) * step
        sample_x = np.arange(n_samples)

        arr = np.array(trajectory, dtype=np.float64)
        pitch_track = np.interp(sample_x, frame_x, arr[:, 0])
        f1_track = np.interp(sample_x, frame_x, arr[:, 1])
        f2_track = np.interp(sample_x, frame_x, arr[:, 2])
        f3_track = np.interp(sample_x, frame_x, arr[:, 3])
        v_gain_track = np.interp(sample_x, frame_x, arr[:, 4])
        n_gain_track = np.interp(sample_x, frame_x, arr[:, 5])
        fric_hz_track = np.interp(sample_x, frame_x, arr[:, 6])
        nasal_mix_track = np.interp(sample_x, frame_x, arr[:, 8])
        anti_hz_track = np.interp(sample_x, frame_x, arr[:, 9])

        # 1. Crisp glottal pulse + controlled breath aspiration
        glottal = self._rosenberg_glottal_wave(pitch_track)
        glottal /= (np.max(np.abs(glottal)) + 1e-8)

        white_noise = np.random.normal(0.0, 0.28, n_samples)
        aspiration = white_noise * breathiness * (0.4 + 0.6 * np.abs(glottal))
        voiced_excitation = (glottal + aspiration) * v_gain_track

        # 2. Clarity-balanced Formants: attenuate muddy low F1 (0.62) & boost crisp F2/F3 (0.95 / 0.65)
        f1_out = self._apply_smooth_resonator(voiced_excitation, f1_track, bandwidth_hz=65.0, gain=0.62)
        f2_out = self._apply_smooth_resonator(voiced_excitation + 0.30 * f1_out, f2_track, bandwidth_hz=85.0, gain=0.95)
        f3_out = self._apply_smooth_resonator(voiced_excitation + 0.25 * f2_out, f3_track, bandwidth_hz=120.0, gain=0.65)

        # 3. Laryngeal Formants (F4 ~3350Hz & F5 ~3850Hz) for crisp vocal articulation
        f4_track = np.full(n_samples, 3350.0 * vocal_tract_scale)
        f5_track = np.full(n_samples, 3850.0 * vocal_tract_scale)
        f4_out = self._apply_smooth_resonator(voiced_excitation + 0.20 * f3_out, f4_track, bandwidth_hz=200.0, gain=0.35)
        f5_out = self._apply_smooth_resonator(voiced_excitation + 0.15 * f4_out, f5_track, bandwidth_hz=250.0, gain=0.20)

        oral_speech = f1_out + f2_out + f3_out + f4_out + f5_out

        # 4. Controlled Nasal Cavity Branch (reduced murmur boominess)
        nasal_murmur_freq = np.full(n_samples, 265.0 * vocal_tract_scale)
        nasal_murmur = self._apply_smooth_resonator(voiced_excitation, nasal_murmur_freq, bandwidth_hz=60.0, gain=0.55)
        notched_oral = self._apply_smooth_notch(oral_speech, anti_hz_track, bandwidth_hz=180.0)

        voiced_speech = (1.0 - nasal_mix_track) * oral_speech + nasal_mix_track * (0.45 * nasal_murmur + 0.65 * notched_oral)

        # 5. Crisp consonant frication (S, SH, T, K, F, TH)
        fric_excitation = white_noise * n_gain_track
        unvoiced_speech = self._apply_smooth_resonator(fric_excitation, fric_hz_track, bandwidth_hz=850.0, gain=1.45)

        waveform = voiced_speech + unvoiced_speech

        # 6. High-pass mud cut (< 110Hz) + subtle upper-mid presence boost (~2.5kHz)
        spectrum = np.fft.rfft(waveform)
        freqs = np.fft.rfftfreq(len(waveform), d=1.0 / self.sr)
        eq_curve = np.ones_like(freqs)
        # Cut sub-120Hz rumble/muddiness
        eq_curve[freqs < 120.0] = (freqs[freqs < 120.0] / 120.0) ** 2
        # Gentle +3.5dB vocal clarity boost centered at 2400Hz
        eq_curve += 0.45 * np.exp(-0.5 * ((freqs - 2400.0) / 900.0) ** 2)
        waveform = np.fft.irfft(spectrum * eq_curve, n=len(waveform))

        peak = np.max(np.abs(waveform))
        if peak > 1e-8:
            waveform = (waveform / peak) * 0.94
        return waveform

    def _apply_smooth_resonator(self, signal, freq_track, bandwidth_hz, gain=1.0):
        """Sample-accurate time-varying biquad bandpass filter (pole pair)."""
        n_samples = len(signal)
        out = np.zeros(n_samples)

        r = np.exp(-np.pi * bandwidth_hz / self.sr)
        r2 = r * r
        scale = (1.0 - r2) * 0.5
        a1_track = 2.0 * r * np.cos(2.0 * np.pi * np.clip(freq_track, 60.0, self.sr * 0.45) / self.sr)

        y1 = 0.0
        y2 = 0.0
        for i in range(n_samples):
            y0 = scale * signal[i] + a1_track[i] * y1 - r2 * y2
            out[i] = y0
            y2 = y1
            y1 = y0

        return out * gain

    def _apply_smooth_notch(self, signal, zero_freq_track, bandwidth_hz=180.0):
        """
        Sample-accurate time-varying biquad anti-resonance (zero pair).
        Carves out spectral valleys created by the oral cavity side-branch during nasals.
        """
        n_samples = len(signal)
        out = np.zeros(n_samples)

        r = np.exp(-np.pi * bandwidth_hz / self.sr)
        r2 = r * r
        b1_track = -2.0 * r * np.cos(2.0 * np.pi * np.clip(zero_freq_track, 200.0, self.sr * 0.45) / self.sr)

        x1 = 0.0
        x2 = 0.0
        for i in range(n_samples):
            x0 = signal[i]
            out[i] = x0 + b1_track[i] * x1 + r2 * x2
            x2 = x1
            x1 = x0

        return out

    def synthesize(self, trajectory, breathiness=0.14, vocal_tract_scale=1.0):
        if not trajectory:
            return np.zeros(self.sr // 10)

        step = self.samples_per_frame
        n_frames = len(trajectory)
        n_samples = n_frames * step

        frame_x = np.arange(n_frames) * step
        sample_x = np.arange(n_samples)

        arr = np.array(trajectory, dtype=np.float64)
        pitch_track = np.interp(sample_x, frame_x, arr[:, 0])
        f1_track = np.interp(sample_x, frame_x, arr[:, 1])
        f2_track = np.interp(sample_x, frame_x, arr[:, 2])
        f3_track = np.interp(sample_x, frame_x, arr[:, 3])
        v_gain_track = np.interp(sample_x, frame_x, arr[:, 4])
        n_gain_track = np.interp(sample_x, frame_x, arr[:, 5])
        fric_hz_track = np.interp(sample_x, frame_x, arr[:, 6])
        nasal_mix_track = np.interp(sample_x, frame_x, arr[:, 8])
        anti_hz_track = np.interp(sample_x, frame_x, arr[:, 9])

        # 1. Continuous glottal pulse + soft breath aspiration
        glottal = self._rosenberg_glottal_wave(pitch_track)
        glottal /= (np.max(np.abs(glottal)) + 1e-8)

        white_noise = np.random.normal(0.0, 0.30, n_samples)
        aspiration = white_noise * breathiness * (0.4 + 0.6 * np.abs(glottal))
        voiced_excitation = (glottal + aspiration) * v_gain_track

        # 2. Primary oral formants (F1, F2, F3)
        f1_out = self._apply_smooth_resonator(voiced_excitation, f1_track, bandwidth_hz=85.0, gain=1.0)
        f2_out = self._apply_smooth_resonator(voiced_excitation + 0.35 * f1_out, f2_track, bandwidth_hz=115.0, gain=0.70)
        f3_out = self._apply_smooth_resonator(voiced_excitation + 0.25 * f2_out, f3_track, bandwidth_hz=160.0, gain=0.42)

        # 3. Fixed Laryngeal Formants (F4 ~3350Hz & F5 ~3850Hz) for human vocal ring & brilliance
        f4_track = np.full(n_samples, 3350.0 * vocal_tract_scale)
        f5_track = np.full(n_samples, 3850.0 * vocal_tract_scale)
        f4_out = self._apply_smooth_resonator(voiced_excitation + 0.20 * f3_out, f4_track, bandwidth_hz=240.0, gain=0.22)
        f5_out = self._apply_smooth_resonator(voiced_excitation + 0.15 * f4_out, f5_track, bandwidth_hz=300.0, gain=0.12)

        oral_speech = f1_out + f2_out + f3_out + f4_out + f5_out

        # 4. Nasal Cavity Branch: low-frequency nasal murmur (~265Hz) + oral anti-resonance notch
        nasal_murmur_freq = np.full(n_samples, 265.0 * vocal_tract_scale)
        nasal_murmur = self._apply_smooth_resonator(voiced_excitation, nasal_murmur_freq, bandwidth_hz=65.0, gain=0.95)
        notched_oral = self._apply_smooth_notch(oral_speech, anti_hz_track, bandwidth_hz=200.0)

        # Blend smoothly between pure oral speech and nasal-coupled speech
        voiced_speech = (1.0 - nasal_mix_track) * oral_speech + nasal_mix_track * (0.65 * nasal_murmur + 0.55 * notched_oral)

        # 5. Unvoiced consonant frication
        fric_excitation = white_noise * n_gain_track
        unvoiced_speech = self._apply_smooth_resonator(fric_excitation, fric_hz_track, bandwidth_hz=1100.0, gain=1.10)

        waveform = voiced_speech + unvoiced_speech
        waveform = np.tanh(waveform * 1.2)
        waveform = np.convolve(waveform, np.array([0.15, 0.2, 0.3, 0.2, 0.15]), mode='same')

        peak = np.max(np.abs(waveform))
        if peak > 1e-8:
            waveform = (waveform / peak) * 0.92
        return waveform

    def _to_wav_bytes(self, waveform):
        pcm_data = np.int16(waveform * 32767)
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sr)
            wf.writeframes(pcm_data.tobytes())
        return buf.getvalue()

    def save_wav(self, filename, waveform):
        with open(filename, 'wb') as f:
            f.write(self._to_wav_bytes(waveform))

    def speak_realtime(self, waveform, async_play=False):
        if not HAS_WINSOUND:
            print("[Audio] winsound is only available on Windows. Use save_wav() instead.")
            return
        wav_bytes = self._to_wav_bytes(waveform)
        flags = winsound.SND_MEMORY | (winsound.SND_ASYNC if async_play else 0)
        winsound.PlaySound(wav_bytes, flags)
                
class TalosDSPChain:
    """Applies sci-fi AI vocal textures using pure-NumPy signal processing."""
    def __init__(self, sample_rate=22050):
        self.sr = sample_rate

    def _apply_ring_mod(self, audio, freq_hz, mix):
        if freq_hz <= 0 or mix <= 0:
            return audio
        t = np.arange(len(audio)) / self.sr
        carrier = np.sin(2.0 * np.pi * freq_hz * t)
        modulated = audio * carrier
        return (1.0 - mix) * audio + mix * modulated

    def _apply_chorus(self, audio, mix):
        if mix <= 0:
            return audio
        n = len(audio)
        t = np.arange(n) / self.sr
        indices = np.arange(n, dtype=np.float64)

        delay1 = (0.012 + 0.002 * np.sin(2.0 * np.pi * 1.4 * t)) * self.sr
        delay2 = (0.021 + 0.003 * np.sin(2.0 * np.pi * 0.9 * t + 1.5)) * self.sr

        tap1 = np.interp(np.clip(indices - delay1, 0, n - 1), indices, audio)
        tap2 = np.interp(np.clip(indices - delay2, 0, n - 1), indices, audio)

        wet = 0.5 * (tap1 + tap2)
        return (1.0 - mix) * audio + mix * wet

    def _apply_radio_bandpass(self, audio, low_hz=300.0, high_hz=3800.0):
        spectrum = np.fft.rfft(audio)
        freqs = np.fft.rfftfreq(len(audio), d=1.0 / self.sr)

        mask = np.ones_like(freqs)
        mask[freqs < low_hz] = np.exp(-((low_hz - freqs[freqs < low_hz]) / 80.0) ** 2)
        mask[freqs > high_hz] = np.exp(-((freqs[freqs > high_hz] - high_hz) / 250.0) ** 2)

        filtered = np.fft.irfft(spectrum * mask, n=len(audio))
        return np.tanh(filtered * 1.5)

    def _apply_room_ambience(self, audio, mix):
        if mix <= 0:
            return audio
        delays_ms = [18.0, 31.0, 47.0]
        gains = [0.35, 0.22, 0.12]
        wet = np.zeros_like(audio)
        for d_ms, g in zip(delays_ms, gains):
            shift = int((d_ms / 1000.0) * self.sr)
            if shift < len(audio):
                wet[shift:] += g * audio[:-shift]
        wet = np.convolve(wet, np.array([0.25, 0.5, 0.25]), mode='same')
        return (1.0 - mix) * audio + mix * (audio + wet)

    def process(self, waveform, profile):
        out = waveform.copy()
        out = self._apply_ring_mod(out, profile.ring_mod_hz, profile.ring_mod_mix)
        out = self._apply_chorus(out, profile.chorus_mix)
        out = self._apply_room_ambience(out, getattr(profile, 'room_ambience', 0.15))
        if profile.bandpass_comms:
            out = self._apply_radio_bandpass(out)

        peak = np.max(np.abs(out))
        if peak > 1e-8:
            out = (out / peak) * 0.95
        return out

class TalosTTS:
    def __init__(self, voice_profile=None, cmudict_path=None):
        self.profile = voice_profile if voice_profile else VoiceProfile.presets()["command"]
        self.g2p = TextToPhonemeEncoder(cmudict_path=cmudict_path)
        self.acoustic = TimeDomainFormantPlanner(voice_profile=self.profile)
        self.vocoder = TimeDomainGlottalVocoder()
        self.dsp = TalosDSPChain(sample_rate=self.vocoder.sr)
        
        self._speech_queue = queue.Queue()
        self._worker_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self._worker_thread.start()

    def _synthesize(self, text, active_profile):
        phonemes, _ = self.g2p.encode(text)
        trajectory = self.acoustic.forward(phonemes, profile_override=active_profile)
        raw_waveform = self.vocoder.synthesize(
            trajectory,
            breathiness=active_profile.breathiness,
            vocal_tract_scale=active_profile.vocal_tract_scale
        )
        return self.dsp.process(raw_waveform, active_profile)
    
    def _queue_worker(self):
        """Continuously processes queued speech tasks one by one in order."""
        while True:
            text, profile, save_path, play_audio = self._speech_queue.get()
            try:
                waveform = self._synthesize(text, profile)
                if save_path:
                    self.vocoder.save_wav(save_path, waveform)
                if play_audio:
                    # Blocking play inside worker thread guarantees zero audio overlap
                    self.vocoder.speak_realtime(waveform, async_play=False)
            finally:
                self._speech_queue.task_done()

    def say(self, text, profile=None, save_path=None, play_audio=True):
        """Blocking call: synthesizes and speaks immediately on the calling thread."""
        active_profile = profile if profile else self.profile
        waveform = self._synthesize(text, active_profile)
        if save_path:
            self.vocoder.save_wav(save_path, waveform)
        if play_audio:
            self.vocoder.speak_realtime(waveform, async_play=False)
        return waveform

    def speak_async(self, text, profile=None, save_path=None, play_audio=True):
        """Non-blocking call: queues text for background speech without halting T.A.L.O.S."""
        active_profile = profile if profile else self.profile
        self._speech_queue.put((text, active_profile, save_path, play_audio))

    def wait_until_done(self):
        """Blocks until all queued speech announcements finish playing."""
        self._speech_queue.join()


# =====================================================================
# PIPELINE EXECUTION
# =====================================================================

if __name__ == "__main__":
    tts = TalosTTS()
    presets = VoiceProfile.presets()

    print("[T.A.L.O.S.] Queuing startup announcements...")
    tts.speak_async(
        "Talos project hephaestus. <pause=400> All systems operational.",
        profile=presets["command"],
        save_path="talos_command.wav",
        play_audio=True,
    )
    tts.speak_async(
        "<pitch=80> Warning. <pitch=115> Tactial comms link active.",
        profile=presets["tactical"],
    )

    print("[T.A.L.O.S.] Main OS loop unblocked while speaking!")
    tts.wait_until_done()
    print("[T.A.L.O.S.] Speech queue complete.")

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
