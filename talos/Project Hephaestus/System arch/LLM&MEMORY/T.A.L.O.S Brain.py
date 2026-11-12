import datetime
import json
import os
import re
import subprocess
from collections import Counter

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


# ==========================================
# 1. FROM-SCRATCH BYTE-PAIR ENCODING (BPE)
# ==========================================
class TalosWordTokenizer:
    def __init__(self, num_merges=180):
        self.num_merges = num_merges
        self.merges = {}
        self.vocab = {}

    def _get_stats(self, ids):
        counts = Counter()
        for pair in zip(ids, ids[1:]):
            counts[pair] += 1
        return counts

    def _merge(self, ids, pair, idx):
        merged = []
        i = 0
        while i < len(ids):
            if i < len(ids) - 1 and ids[i] == pair[0] and ids[i + 1] == pair[1]:
                merged.append(idx)
                i += 2
            else:
                merged.append(ids[i])
                i += 1
        return merged

    def train(self, text):
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
            if not stats:
                break
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
        return {
            "num_merges": self.num_merges,
            "merges": {f"{k[0]},{k[1]}": v for k, v in self.merges.items()},
            "vocab": self.vocab,
        }

    def load_state_dict(self, state):
        self.num_merges = state["num_merges"]
        self.merges = {tuple(map(int, k.split(","))): v for k, v in state["merges"].items()}
        self.vocab = state["vocab"]


# ==========================================
# 2. MINI-GPT TRANSFORMER ARCHITECTURE
# ==========================================
class MiniTalosLLM(nn.Module):
    def __init__(self, vocab_size, embed_dim=128, num_heads=4, num_layers=3, max_len=160):
        super().__init__()
        self.config = {
            "vocab_size": vocab_size,
            "embed_dim": embed_dim,
            "num_heads": num_heads,
            "num_layers": num_layers,
            "max_len": max_len,
        }
        self.max_len = max_len
        self.token_embedding = nn.Embedding(vocab_size, embed_dim)
        self.position_embedding = nn.Embedding(max_len, embed_dim)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim,
            nhead=num_heads,
            dim_feedforward=embed_dim * 4,
            dropout=0.1,
            batch_first=True,
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
    def generate(self, idx, max_new_tokens=50, greedy=True, temperature=0.3):
        self.eval()
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.max_len:]
            logits, _ = self(idx_cond)
            last_logits = logits[:, -1, :]
            if greedy:
                next_token = torch.argmax(last_logits, dim=-1, keepdim=True)
            else:
                probs = F.softmax(last_logits / temperature, dim=-1)
                next_token = torch.multinomial(probs, num_samples=1)
            idx = torch.cat((idx, next_token), dim=1)
        return idx


# ==========================================
# 3. PURE-NUMPY LONG-TERM MEMORY SYSTEM
# ==========================================
class TalosMemory:
    def __init__(self, filepath="talos_memory.json"):
        self.filepath = filepath
        self.memories = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def add_memory(self, text):
        cleaned = text.strip()
        if cleaned and cleaned not in self.memories:
            self.memories.append(cleaned)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.memories, f, indent=2)
            return True
        return False

    def _vectorize(self, text, vocab):
        words = re.findall(r"\w+", text.lower())
        vec = np.zeros(len(vocab), dtype=np.float32)
        for w in words:
            if w in vocab:
                vec[vocab[w]] += 1.0
        return vec

    def search(self, query, top_k=2):
        if not self.memories:
            return []

        all_words = set(re.findall(r"\w+", query.lower()))
        for memory in self.memories:
            all_words.update(re.findall(r"\w+", memory.lower()))
        vocab = {w: i for i, w in enumerate(all_words)}

        q_vec = self._vectorize(query, vocab)
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return []

        scored = []
        for memory in self.memories:
            m_vec = self._vectorize(memory, vocab)
            m_norm = np.linalg.norm(m_vec)
            if m_norm > 0:
                sim = np.dot(q_vec, m_vec) / (q_norm * m_norm)
                scored.append((sim, memory))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [memory for sim, memory in scored[:top_k] if sim > 0.15]


# ==========================================
# 4. ZERO-DEPENDENCY ACTION EXECUTION ENGINE
# ==========================================
class TalosActionEngine:
    def __init__(self):
        self.tools = {
            "get_time": self.get_time,
            "lights_on": self.lights_on,
            "lights_off": self.lights_off,
            "run_app": self.run_app,
            "save_note": self.save_note,
        }

    def get_time(self):
        now = datetime.datetime.now().strftime("%I:%M %p on %A")
        return f"Current system time is {now}."

    def lights_on(self):
        return "Local lighting relay triggered: ON."

    def lights_off(self):
        return "Local lighting relay triggered: OFF."

    def run_app(self, app_name):
        allowed = {
            "calculator": "calc.exe" if os.name == "nt" else "gnome-calculator",
            "notepad": "notepad.exe" if os.name == "nt" else "gedit",
        }
        target = allowed.get(app_name.lower())
        if not target:
            return f"Application '{app_name}' is not whitelisted."
        subprocess.Popen([target])
        return f"Launched {app_name}."

    def save_note(self, note_text):
        with open("talos_notes.txt", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] {note_text}\n")
        return "Note written to talos_notes.txt."

    def parse_and_execute(self, llm_output):
        pattern = r"\[ACTION:\s*([a-zA-Z0-9_]+)\((.*?)\)\]"
        match = re.search(pattern, llm_output)
        if not match:
            return llm_output, None

        func_name = match.group(1)
        raw_arg = match.group(2).strip().strip('"').strip("'")

        if func_name not in self.tools:
            result = f"Unknown action '{func_name}'."
        elif raw_arg:
            result = self.tools[func_name](raw_arg)
        else:
            result = self.tools[func_name]()

        spoken_reply = re.sub(pattern, "", llm_output).strip()
        return spoken_reply, result


# ==========================================
# 5. CHECKPOINTS & TRAINING SYSTEM
# ==========================================
def save_checkpoint(filepath, model, optimizer, tokenizer, dataset_list):
    torch.save(
        {
            "model_config": model.config,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "tokenizer_state": tokenizer.state_dict(),
            "dataset": dataset_list,
        },
        filepath,
    )


def load_checkpoint(filepath, device):
    ckpt = torch.load(filepath, map_location=device, weights_only=False)
    tokenizer = ScratchBPETokenizer()
    tokenizer.load_state_dict(ckpt["tokenizer_state"])
    model = MiniTalosLLM(**ckpt["model_config"]).to(device)
    model.load_state_dict(ckpt["model_state_dict"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3)
    optimizer.load_state_dict(ckpt["optimizer_state_dict"])
    return model, optimizer, tokenizer, ckpt["dataset"]


def load_training_file(filepath="training_data.txt"):
    if not os.path.exists(filepath):
        default_data = (
            "User: Hello Talos\n"
            "Talos: Systems online. How may I assist you?\n\n"
            "User: Turn on the lights\n"
            "Talos: [ACTION: lights_on()] Turning on the lights.\n\n"
            "User: Turn off the lights\n"
            "Talos: [ACTION: lights_off()] Turning off the lights.\n\n"
            "User: What time is it\n"
            "Talos: [ACTION: get_time()] Checking the system clock.\n\n"
            "User: Open calculator\n"
            'Talos: [ACTION: run_app("calculator")] Opening calculator.\n'
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(default_data)

    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    pairs = []
    for block in raw.split("\n\n"):
        cleaned = block.strip()
        if "User:" in cleaned and "\nTalos:" in cleaned:
            pairs.append(cleaned + "\n")
    return pairs


def append_to_training_file(new_pair, filepath="training_data.txt"):
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"\n{new_pair.strip()}\n")


def train_on_corpus(model, optimizer, tokenizer, dataset_list, steps=1000, device="cpu", log_interval=200):
    formatted_pairs = [pair.strip() + "\n\n" for pair in dataset_list]
    full_text = "".join(formatted_pairs) * 20
    data_ids = torch.tensor(tokenizer.encode(full_text), dtype=torch.long)
    if len(data_ids) < 8:
        return

    block_size = min(64, len(data_ids) - 2)
    if block_size < 4:
        return

    model.train()
    for step in range(1, steps + 1):
        ix = torch.randint(len(data_ids) - block_size, (16,))
        x = torch.stack([data_ids[i : i + block_size] for i in ix]).to(device)
        y = torch.stack([data_ids[i + 1 : i + block_size + 1] for i in ix]).to(device)
        _, loss = model(x, y)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if log_interval and step % log_interval == 0:
            print(f"[TRAIN] Step {step}/{steps} | Loss: {loss.item():.4f}")


# ==========================================
# 6. MAIN INTERACTIVE ASSISTANT LOOP
# ==========================================
if __name__ == "__main__":
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ckpt_path = "talos_checkpoint.pt"
    data_path = "training_data.txt"
    memory = TalosMemory()
    actions = TalosActionEngine()

    if os.path.exists(ckpt_path):
        print("[SYSTEM] Loading Talos checkpoint...")
        model, optimizer, tokenizer, dataset = load_checkpoint(ckpt_path, device)
    else:
        print(f"[SYSTEM] Initializing from {data_path}...")
        dataset = load_training_file(data_path)
        tokenizer = TalosWordTokenizer()
        tokenizer.train("\n".join(normalize_pair(p) for p in dataset))
        model = MiniTalosLLM(vocab_size=tokenizer.vocab_size).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3)
        print(f"[SYSTEM] Training on {len(dataset)} pairs (Vocab size: {tokenizer.vocab_size})...")
        train_on_corpus(model, optimizer, tokenizer, dataset, steps=1000, device=device, log_interval=200)
        save_checkpoint(ckpt_path, model, optimizer, tokenizer, dataset)

    print("\n=== TALOS V2 PYTHON CORE ONLINE ===")
    print("Commands:")
    print("  /fix   -> Teach Talos a new reply or [ACTION: ...]")
    print("  /remember -> Save a fact to long-term NumPy memory")
    print("  /quit -> Save checkpoint and exit\n")

    last_prompt_context = ""
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue

        if user_input.lower() == "/quit":
            save_checkpoint(ckpt_path, model, optimizer, tokenizer, dataset)
            print("[SYSTEM] Checkpoint saved. Shutting down.")
            break

        if user_input.startswith("/remember "):
            fact = user_input[10:].strip()
            if memory.add_memory(fact):
                print(f"[MEMORY] Stored: '{fact}'\n")
            else:
                print("[MEMORY] Fact already exists or is empty.\n")
            continue

        if user_input.startswith("/fix "):
            if not last_prompt_context:
                print("[SYSTEM] Send a message first before using /fix.\n")
                continue

            corrected = user_input[5:].strip()
            new_pair = f"{last_prompt_context}\nTalos: {corrected}\n"
            dataset.append(new_pair)
            append_to_training_file(new_pair, data_path)

            tokenizer.train("\n".join(normalize_pair(p)for p in dataset))
            if tokenizer.vocab_size != model.config["vocab_size"]:
                model = MiniTalosLLM(vocab_size=tokenizer.vocab_size).to(device)
                optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3)
                end_id = tokenizer.stoi[""]



            print("[SYSTEM] Synced to training_data.txt. Fine-tuning...")
            train_on_corpus(model, optimizer, tokenizer, dataset, steps=400, device=device, log_interval=200)
            save_checkpoint(ckpt_path, model, optimizer, tokenizer, dataset)
            _, action_res = actions.parse_and_execute(corrected)
            if action_res:
                print(f"[ACTION EXECUTED] {action_res}")
            print(f"[SYSTEM] Learned: '{corrected}'\n")
            continue

        recalled = memory.search(user_input, top_k=2)
        if recalled:
            mem_block = "Memory: " + " | ".join(recalled) + "\n"
            print(f"[MEMORY RECALLED] {recalled}")
            last_prompt_context = f"{mem_block}User: {user_input}"
        else:
            last_prompt_context = f"User: {user_input}"

        full_prompt = f"{last_prompt_context}\nTalos:"
        input_ids = torch.tensor([tokenizer.encode(full_prompt)], dtype=torch.long).to(device)
        output_ids = model.generate(input_ids, end_id=end_id, max_new_tokens=40)

        prompt_length = input_ids.size(1)
        new_tokens = output_ids[0, prompt_length:].tolist()
        raw_reply = tokenizer.decode(new_tokens).strip()

        for stop_token in ["\nUser:", "\nMemory:"]:
            raw_reply = raw_reply.split(stop_token, 1)[0]
        raw_reply = raw_reply.strip()

        spoken_reply, action_result = actions.parse_and_execute(raw_reply)
        if action_result:
            print(f"[ACTION EXECUTED] {action_result}")
            print(f"Talos: {spoken_reply}\n")
        else:
            print(f"Talos: {raw_reply}\n")
