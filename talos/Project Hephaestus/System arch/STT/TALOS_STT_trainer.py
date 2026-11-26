import os
import csv
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# Import your pure-NumPy frontend from Component 1
from talos_stt_frontend import TalosAudioFrontend


# =====================================================================
# 1. CHARACTER TOKENIZER & GREEDY CTC DECODER
# =====================================================================
class TalosTextTokenizer:
    """
    Maps lowercase characters ('a'-'z', space, apostrophe) to integer IDs
    and decodes CTC frame predictions by collapsing repeats and removing blanks.
    """

    def __init__(self):
        # Index 0 is strictly reserved for the CTC <BLANK> token
        self.blank_id = 0
        chars = ["<BLANK>", " ", "'"] + [chr(i) for i in range(ord("a"), ord("z") + 1)]
        self.id_to_char = {i: c for i, c in enumerate(chars)}
        self.char_to_id = {c: i for i, c in enumerate(chars)}
        self.vocab_size = len(chars)  # 29 classes

    def encode(self, text):
        text = text.lower().strip()
        return [self.char_to_id[c] for c in text if c in self.char_to_id]

    def decode_greedy(self, log_probs):
        """
        Collapses consecutive duplicate tokens and strips <BLANK> (0).
        Args:
            log_probs: Tensor of shape (time_steps, vocab_size) or (batch, time_steps, vocab_size)
        """
        if log_probs.dim() == 2:
            log_probs = log_probs.unsqueeze(0)

        best_paths = torch.argmax(log_probs, dim=-1).cpu().numpy()
        decoded_sentences = []

        for path in best_paths:
            chars = []
            prev_id = None
            for token_id in path:
                if token_id != self.blank_id and token_id != prev_id:
                    chars.append(self.id_to_char[int(token_id)])
                prev_id = token_id
            decoded_sentences.append("".join(chars).strip())

        return decoded_sentences


# =====================================================================
# 2. PYTORCH DATASET & VARIABLE-LENGTH BATCH COLLATE
# =====================================================================
class TalosSpeechDataset(Dataset):
    """Reads manifest.csv and extracts trimmed Log-Mel Spectrograms on the fly."""

    def __init__(self, dataset_dir, frontend, tokenizer, augment=True):
        self.dataset_dir = dataset_dir
        self.frontend = frontend
        self.tokenizer = tokenizer
        self.augment = augment
        self.samples = []

        manifest_path = os.path.join(dataset_dir, "manifest.csv")
        with open(manifest_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                wav_path = os.path.join(dataset_dir, row["filepath"])
                if os.path.exists(wav_path) and row["transcript"].strip():
                    self.samples.append((wav_path, row["transcript"].strip()))

    def __len__(self):
        return len(self.samples)

    def _spec_augment(self, mel):
        """Lightweight frequency & time masking so the model generalises from small datasets."""
        mel = mel.copy()
        n_mels, n_steps = mel.shape

        # Mask a random band of up to 8 Mel frequency bins
        if n_mels > 10:
            f_width = np.random.randint(1, 9)
            f_start = np.random.randint(0, n_mels - f_width)
            mel[f_start : f_start + f_width, :] = 0.0

        # Mask a random slice of up to 12 time frames
        if n_steps > 20:
            t_width = np.random.randint(1, 13)
            t_start = np.random.randint(0, n_steps - t_width)
            mel[:, t_start : t_start + t_width] = 0.0

        return mel

    def __getitem__(self, idx):
        wav_path, transcript = self.samples[idx]
        audio = self.frontend.load_wav(wav_path)
        trimmed = self.frontend.trim_silence(audio)
        if len(trimmed) < 400:
            trimmed = audio  # Fallback if trimming was too aggressive

        log_mel = self.frontend.extract_log_mel_spectrogram(trimmed, normalize=True)
        if self.augment:
            log_mel = self._spec_augment(log_mel)

        target_ids = self.tokenizer.encode(transcript)
        return (
            torch.tensor(log_mel, dtype=torch.float32),  # (n_mels, time_steps)
            torch.tensor(target_ids, dtype=torch.long),  # (target_len,)
            transcript,
        )


def ctc_collate_fn(batch):
    """Pads spectrograms and transcripts in a batch to uniform lengths for CTC loss."""
    batch_size = len(batch)
    n_mels = batch[0][0].shape[0]

    max_time = max(item[0].shape[1] for item in batch)
    max_target = max(item[1].shape[0] for item in batch)

    padded_specs = torch.zeros(batch_size, 1, n_mels, max_time, dtype=torch.float32)
    padded_targets = torch.zeros(batch_size, max_target, dtype=torch.long)
    input_lengths = torch.zeros(batch_size, dtype=torch.long)
    target_lengths = torch.zeros(batch_size, dtype=torch.long)
    raw_texts = []

    for i, (spec, target, text) in enumerate(batch):
        t_len = spec.shape[1]
        y_len = target.shape[0]

        padded_specs[i, 0, :, :t_len] = spec
        padded_targets[i, :y_len] = target

        # Two stride-2 Conv2d layers reduce the time dimension by a factor of 4
        input_lengths[i] = max(1, (t_len + 1) // 2)
        input_lengths[i] = max(1, (input_lengths[i] + 1) // 2)
        target_lengths[i] = y_len
        raw_texts.append(text)

    return padded_specs, padded_targets, input_lengths, target_lengths, raw_texts


# =====================================================================
# 3. CRNN ACOUSTIC MODEL (CNN + BI-GRU)
# =====================================================================
class TalosCRNN(nn.Module):
    def __init__(self, n_mels=64, vocab_size=29):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(32),
            nn.GELU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(64),
            nn.GELU(),
            nn.Dropout(0.15),
        )

        rnn_in_dim = 64 * (n_mels // 4)
        self.gru = nn.GRU(
            input_size=rnn_in_dim,
            hidden_size=256,
            num_layers=2,
            bidirectional=True,
            batch_first=True,
            dropout=0.2,
        )
        self.classifier = nn.Linear(256 * 2, vocab_size)

    def forward(self, x):
        # x: (batch, 1, n_mels, time)
        x = self.conv(x)
        b, c, f, t = x.size()
        x = x.permute(0, 3, 1, 2).contiguous().view(b, t, c * f)
        x, _ = self.gru(x)
        logits = self.classifier(x)
        return torch.nn.functional.log_softmax(logits, dim=-1)


# =====================================================================
# 4. TRAINING LOOP & LIVE INFERENCE HELPER
# =====================================================================
def train_talos_stt(
    dataset_dir="talos_stt_dataset",
    model_save_path="talos_stt_weights.pt",
    epochs=60,
    batch_size=8,
    lr=1e-3,
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[T.A.L.O.S. STT] Training on device: {device}")

    frontend = TalosAudioFrontend(sample_rate=16000, n_mels=64)
    tokenizer = TalosTextTokenizer()
    dataset = TalosSpeechDataset(dataset_dir, frontend, tokenizer, augment=True)

    if len(dataset) == 0:
        raise RuntimeError(
            f"No recordings found in {dataset_dir}/manifest.csv. Record audio first!"
        )

    loader = DataLoader(
        dataset, batch_size=batch_size, shuffle=True, collate_fn=ctc_collate_fn
    )

    model = TalosCRNN(n_mels=64, vocab_size=tokenizer.vocab_size).to(device)
    criterion = nn.CTCLoss(blank=tokenizer.blank_id, zero_infinity=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0

        for specs, targets, in_lens, tgt_lens, _ in loader:
            specs = specs.to(device)
            targets = targets.to(device)

            optimizer.zero_grad()
            log_probs = model(specs)  # (batch, time, vocab)

            # PyTorch CTCLoss expects time-first shape: (time, batch, vocab)
            log_probs_time_first = log_probs.permute(1, 0, 2)
            loss = criterion(log_probs_time_first, targets, in_lens, tgt_lens)

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=2.0)
            optimizer.step()
            total_loss += loss.item()

        scheduler.step()
        avg_loss = total_loss / len(loader)

        # Print progress and sample greedy transcription every 10 epochs
        if epoch % 10 == 0 or epoch == 1:
            model.eval()
            with torch.no_grad():
                sample_spec, _, sample_text = dataset[0]
                sample_out = model(sample_spec.unsqueeze(0).unsqueeze(0).to(device))
                pred_text = tokenizer.decode_greedy(sample_out)[0]
            print(
                f"Epoch {epoch:02d}/{epochs} | CTC Loss: {avg_loss:.4f} | "
                f"Target: '{sample_text}' -> Pred: '{pred_text}'"
            )

    torch.save(
        {
            "model_state": model.state_dict(),
            "n_mels": 64,
            "vocab_size": tokenizer.vocab_size,
        },
        model_save_path,
    )
    print(f"\n[T.A.L.O.S. STT] Training complete! Weights saved to {model_save_path}")


def transcribe_wav(wav_path, weights_path="talos_stt_weights.pt"):
    """Loads saved weights and transcribes a single WAV file offline."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    frontend = TalosAudioFrontend(sample_rate=16000, n_mels=64)
    tokenizer = TalosTextTokenizer()

    checkpoint = torch.load(weights_path, map_location=device, weights_only=True)
    model = TalosCRNN(
        n_mels=checkpoint["n_mels"],
        vocab_size=checkpoint["vocab_size"],
    ).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    audio = frontend.load_wav(wav_path)
    trimmed = frontend.trim_silence(audio)
    log_mel = frontend.extract_log_mel_spectrogram(
        trimmed if len(trimmed) > 400 else audio
    )
    tensor_in = (
        torch.tensor(log_mel, dtype=torch.float32).unsqueeze(0).unsqueeze(0).to(device)
    )
    with torch.no_grad():
        log_probs = model(tensor_in)
    return tokenizer.decode_greedy(log_probs)[0]


if __name__ == "__main__":
    train_talos_stt(
        dataset_dir="talos_stt_dataset",
        model_save_path="talos_stt_weights.pt",
        epochs=60,
        batch_size=8,
        lr=1e-3,
    )
