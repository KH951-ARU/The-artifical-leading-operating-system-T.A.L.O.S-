import json
import os
import re
from collections import Counter
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# ==========================================
# 1. FROM-SCRATCH BYTE-PAIR ENCODING (BPE)
# ==========================================
class ScratchBPETokenizer:
    def __init__(self, num_merges=150):
        self.num_merges = num_merges
        self.merges = {}
        self.vocab = {}
        self.itos = {}

    def _get_stats(self, ids):
        counts = Counter()
        for pair in zip(ids, ids[1:]):
            counts[pair] += 1
        return counts

    def _merge(self, ids, pair, idx):
        new_ids = []
        i = 0
        while i < len(ids):
            if i < len(ids) - 1 and ids[i] == pair[0] and ids[i + 1] == pair[1]:
                new_ids.append(idx)
                i += 2
            else:
                new_ids.append(ids[i])
                i += 1
        return new_ids

    def train(self, text):
        # Start with raw UTF-8 byte values (0-255)
        ids = list(text.encode("utf-8"))
        self.vocab = {i: bytes([i]) for i in range(256)}
        self.merges = {}

        for i in range(self.num_merges):
            stats = self._get_stats(ids)
            if not stats:
                break
            top_pair = max(stats, key=stats.get)
            new_id = 256 + i
            ids = self._merge(ids, top_pair, new_id)
            self.merges[top_pair] = new_id
            self.vocab[new_id] = self.vocab[top_pair[0]] + self.vocab[top_pair[1]]

    def encode(self, text):
        ids = list(text.encode("utf-8"))
        while len(ids) >= 2:
            stats = self._get_stats(ids)
            pair = min(stats, key=lambda p: self.merges.get(p, float("inf")))
            if pair not in self.merges:
                break
            ids = self._merge(ids, pair, self.merges[pair])
        return ids

    def decode(self, ids):
        byte_stream = b"".join(self.vocab[i] for i in ids if i in self.vocab)
        return byte_stream.decode("utf-8", errors="replace")

    @property
    def vocab_size(self):
        return len(self.vocab)

    def state_dict(self):
        # Convert tuple keys to strings for safe serialization
        return {
            "num_merges": self.num_merges,
            "merges": {f"{k[0]},{k[1]}": v for k, v in self.merges.items()},
            "vocab": self.vocab
        }

    def load_state_dict(self, state):
        self.num_merges = state["num_merges"]
        self.merges = {tuple(map(int, k.split(","))): v for k, v in state["merges"].items()}
        self.vocab = state["vocab"]


# ==========================================
# 2. MINI-GPT TRANSFORMER ARCHITECTURE
# ==========================================
class MiniTalosLLM(nn.Module):
    def __init__(self, vocab_size, embed_dim=96, num_heads=4, num_layers=3, max_len=128):
        super().__init__()
        self.config = {
            "vocab_size": vocab_size,
            "embed_dim": embed_dim,
            "num_heads": num_heads,
            "num_layers": num_layers,
            "max_len": max_len
        }
        self.max_len = max_len
        self.token_embedding = nn.Embedding(vocab_size, embed_dim)
        self.position_embedding = nn.Embedding(max_len, embed_dim)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim,
            nhead=num_heads,
            dim_feedforward=embed_dim * 4,
            dropout=0.1,
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.lm_head = nn.Linear(embed_dim, vocab_size)

    def forward(self, idx, targets=None):
        B, T = idx.shape
        positions = torch.arange(0, T, device=idx.device).unsqueeze(0)
        x = self.token_embedding(idx) + self.position_embedding(positions)

        causal_mask = nn.Transformer.generate_square_subsequent_mask(T).to(idx.device)
        x = self.transformer(x, mask=causal_mask, is_causal=True)
        logits = self.lm_head(x)

        loss = None
        if targets is not None:
            B, T, C = logits.shape
            loss = F.cross_entropy(logits.view(B * T, C), targets.view(B * T))
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, max_new_tokens=40, temperature=0.6):
        self.eval()
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.max_len:]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :] / temperature
            probs = F.softmax(logits, dim=-1)
            next_token = torch.multinomial(probs, num_samples=1)
            idx = torch.cat((idx, next_token), dim=1)
        return idx


# ==========================================
# 3. .PT CHECKPOINT SAVE & LOAD SYSTEM
# ==========================================
def save_checkpoint(filepath, model, optimizer, tokenizer, dataset_list):
    checkpoint = {
        "model_config": model.config,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "tokenizer_state": tokenizer.state_dict(),
        "dataset": dataset_list
    }
    torch.save(checkpoint, filepath)
    print(f"[SYSTEM] Checkpoint saved to {filepath}")

def load_checkpoint(filepath, device):
    checkpoint = torch.load(filepath, map_location=device, weights_only=False)
    
    tokenizer = ScratchBPETokenizer()
    tokenizer.load_state_dict(checkpoint["tokenizer_state"])
    
    cfg = checkpoint["model_config"]
    model = MiniTalosLLM(**cfg).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3)
    optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
    
    return model, optimizer, tokenizer, checkpoint["dataset"]


# ==========================================
# 4. FINE-TUNING & INTERACTIVE CHAT LOOP
# ==========================================
def train_on_corpus(model, optimizer, tokenizer, dataset_list, steps=150, device="cpu"):
    full_text = "".join(dataset_list) * 15
    data_ids = torch.tensor(tokenizer.encode(full_text), dtype=torch.long)
    block_size = min(64, len(data_ids) - 2)
    if block_size < 4:
        return

    model.train()
    for _ in range(steps):
        ix = torch.randint(len(data_ids) - block_size, (8,))
        x = torch.stack([data_ids[i:i + block_size] for i in ix]).to(device)
        y = torch.stack([data_ids[i + 1:i + block_size + 1] for i in ix]).to(device)

        _, loss = model(x, y)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()


if __name__ == "__main__":
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ckpt_path = "talos_checkpoint.pt"

    if os.path.exists(ckpt_path):
        print("[SYSTEM] Loading existing Talos checkpoint...")
        model, optimizer, tokenizer, dataset = load_checkpoint(ckpt_path, device)
    else:
        print("[SYSTEM] Initializing new BPE tokenizer and Talos brain...")
        dataset = [
            "User: Hello Talos\nTalos: Systems online. How may I assist you?\n",
            "User: Turn on the lights\nTalos: [ACTION: lights_on()] Turning on the lights.\n",
            "User: What time is it\nTalos: [ACTION: get_time()] Checking the system clock.\n",
            "User: Status report\nTalos: All core modules are operating within normal parameters.\n"
        ]
        tokenizer = ScratchBPETokenizer(num_merges=120)
        tokenizer.train("".join(dataset))

        model = MiniTalosLLM(vocab_size=tokenizer.vocab_size).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3)
        
        print("[SYSTEM] Running initial baseline training...")
        train_on_corpus(model, optimizer, tokenizer, dataset, steps=250, device=device)
        save_checkpoint(ckpt_path, model, optimizer, tokenizer, dataset)

    print("\n--- Talos Interactive Loop Ready ---")
    print("Commands: Type '/fix <ideal reply>' to correct the last response, or '/quit' to exit.\n")

    last_user_prompt = ""

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "/quit":
            save_checkpoint(ckpt_path, model, optimizer, tokenizer, dataset)
            break

        # Handle interactive correction and immediate learning
        if user_input.startswith("/fix "):
            if not last_user_prompt:
                print("[SYSTEM] Ask a question first before submitting a correction.")
                continue
            
            corrected_reply = user_input[5:].strip()
            new_pair = f"User: {last_user_prompt}\nTalos: {corrected_reply}\n"
            dataset.append(new_pair)
            
            print("[SYSTEM] Rebuilding BPE vocabulary and fine-tuning on correction...")
            # Re-train BPE if new words appeared, or keep existing merges for stability
            train_on_corpus(model, optimizer, tokenizer, dataset, steps=120, device=device)
            save_checkpoint(ckpt_path, model, optimizer, tokenizer, dataset)
            print(f"[SYSTEM] Learned: '{corrected_reply}'\n")
            continue

        # Standard generation
        last_user_prompt = user_input
        prompt_text = f"User: {user_input}\nTalos:"
        input_ids = torch.tensor([tokenizer.encode(prompt_text)], dtype=torch.long).to(device)

        output_ids = model.generate(input_ids, max_new_tokens=35)
        full_output = tokenizer.decode(output_ids[0].tolist())

        # Extract only Talos's current reply
        reply = full_output[len(prompt_text):].split("\nUser:")[0].strip()
        print(f"Talos: {reply}\n")
