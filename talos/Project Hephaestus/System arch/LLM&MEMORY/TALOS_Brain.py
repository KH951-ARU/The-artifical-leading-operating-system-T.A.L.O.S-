import datetime
import json
import os
import re
import subprocess
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.set_num_threads(os.cpu_count() or 4)
torch.set_float32_matmul_precision("high")

# ==========================================
# 1. CLEAN WORD & SYMBOL TOKENIZER
# ==========================================
class TalosWordTokenizer:
    def __init__(self):
        self.special_tokens = ["<PAD>", "<UNK>", "<END>", "\n"]
        self.stoi = {}
        self.itos = {}

    def _tokenize_text(self, text):
        return re.findall(r"\[ACTION:[^\]]+\]|<END>|\n|[a-zA-Z0-9_']+|[^\s\w]", text)

    def train(self, text):
        tokens = self._tokenize_text(text)
        unique_tokens = sorted(list(set(tokens) - set(self.special_tokens)))
        all_vocab = self.special_tokens + unique_tokens
        self.stoi = {tok: i for i, tok in enumerate(all_vocab)}
        self.itos = {i: tok for i, tok in enumerate(all_vocab)}

    def encode(self, text):
        tokens = self._tokenize_text(text)
        unk_id = self.stoi["<UNK>"]
        return [self.stoi.get(t, unk_id) for t in tokens]

    def decode(self, ids):
        pad_id = self.stoi["<PAD>"]
        end_id = self.stoi["<END>"]
        words = [self.itos.get(i, "") for i in ids if i not in (pad_id, end_id)]
        text = ""
        for w in words:
            if w == "\n":
                text += "\n"
            elif text == "" or text.endswith("\n"):
                text += w
            elif re.match(r"^[.,!?;:)\]]$", w):
                text += w
            else:
                text += " " + w
        return text.strip()

    @property
    def vocab_size(self):
        return len(self.stoi)

    def state_dict(self):
        return {"stoi": self.stoi, "itos": self.itos}

    def load_state_dict(self, state):
        self.stoi = state["stoi"]
        self.itos = {int(k): v for k, v in state["itos"].items()}


# ==========================================
# 2. DECODER-ONLY TRANSFORMER
# ==========================================
class MiniTalosLLM(nn.Module):
    def __init__(
        self, vocab_size, embed_dim=128, num_heads=4, num_layers=3, max_len=128
    ):
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
            dropout=0.0,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.lm_head = nn.Linear(embed_dim, vocab_size)

    def forward(self, idx, pad_idx=0):
        B, T = idx.shape
        positions = torch.arange(0, T, device=idx.device).unsqueeze(0)
        x = self.token_embedding(idx) + self.position_embedding(positions)

        causal_mask = torch.triu(
            torch.full((T, T), float("-inf"), device=idx.device), diagonal=1
        )
        pad_mask = torch.zeros_like(idx, dtype=torch.float).masked_fill(idx == pad_idx, float("-inf"))
        x = self.transformer(x, mask=causal_mask, src_key_padding_mask=pad_mask)
        return self.lm_head(x)

    @torch.no_grad()
    def generate(self, idx, end_id, max_new_tokens=40):
        self.eval()
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.max_len :]
            logits = self(idx_cond)
            next_token = torch.argmax(logits[:, -1, :], dim=-1, keepdim=True)
            idx = torch.cat((idx, next_token), dim=1)
            if next_token.item() == end_id:
                break
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
        for m in self.memories:
            all_words.update(re.findall(r"\w+", m.lower()))
        vocab = {w: i for i, w in enumerate(all_words)}

        q_vec = self._vectorize(query, vocab)
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return []

        scored = []
        for m in self.memories:
            m_vec = self._vectorize(m, vocab)
            m_norm = np.linalg.norm(m_vec)
            if m_norm > 0:
                sim = np.dot(q_vec, m_vec) / (q_norm * m_norm)
                scored.append((sim, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for sim, m in scored[:top_k] if sim > 0.15]

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
# 5. .PT CHECKPOINTS & TRAINING SYSTEM
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
    tokenizer = TalosWordTokenizer()
    tokenizer.load_state_dict(ckpt["tokenizer_state"])
    model = MiniTalosLLM(**ckpt["model_config"]).to(device)
    model.load_state_dict(ckpt["model_state_dict"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3)
    optimizer.load_state_dict(ckpt["optimizer_state_dict"])
    return model, optimizer, tokenizer, ckpt["dataset"]


def load_training_file(filepath="training_data.txt"):
    if not os.path.exists(filepath):
        default_data = (
            "User: Hello Talos\n"
            "Talos: Systems online. How may I assist you?\n\n"
            "User: Run diagnostics\n"
            "Talos: Running local check. Neural engine, memory search, and action parser are online.\n"
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


def normalize_pair(pair_text):
    lines = pair_text.strip().split("\n")
    for i, line in enumerate(lines):
        if line.startswith("User:"):
            lines[i] = "User: " + line[5:].strip().lower()
    return "\n".join(lines) + "\n<END>"


def train_on_corpus(
    model,
    optimizer,
    tokenizer,
    dataset_list,
    steps=600,
    device="cpu",
    log_interval=150,
):
    encoded_pairs = []
    for pair in dataset_list:
        ids = tokenizer.encode(normalize_pair(pair))
        if len(ids) > 2:
            encoded_pairs.append(ids)

    if not encoded_pairs:
        return

    max_pair_len = min(model.max_len, max(len(p) for p in encoded_pairs))
    pad_id = tokenizer.stoi["<PAD>"]
    
    batch_x, batch_y = [], []
    for ids in encoded_pairs:
        seq = ids[:max_pair_len]
        padded = seq + [pad_id] * (max_pair_len - len(seq))
        batch_x.append(padded[:-1])
        batch_y.append(padded[1:])

    x_all = torch.tensor(batch_x, dtype=torch.long, device=device)
    y_all = torch.tensor(batch_y, dtype=torch.long, device=device)
    
    model.train()
    num_samples = x_all.size(0)
    batch_size = min(128, num_samples)
    for step in range(1, steps + 1):
        ix = torch.randint(0, num_samples, (batch_size,), device=device)
        x_batch = x_all[ix]
        y_batch = y_all[ix]

        # Find the longest real sequence in THIS batch and trim excess <PAD> tokens
        non_pad_lengths = (x_batch != pad_id).sum(dim=1)
        max_b_len = max(2, int(non_pad_lengths.max().item()))
        x_batch = x_batch[:, :max_b_len]
        y_batch = y_batch[:, :max_b_len]

        logits = model(x_batch, pad_idx=pad_id)
        loss = F.cross_entropy(
            logits.reshape(-1, logits.size(-1)),
            y_batch.reshape(-1),
            ignore_index=pad_id
        )
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()

        if log_interval and step % log_interval == 0:
            print(f"[TRAIN] Step {step}/{steps} | Loss: {loss.item():.4f}")


# ==========================================
# 6. MAIN INTERACTIVE ASSISTANT LOOP
# ==========================================

if __name__ == "__main__":
    device = "cuda" if torch.cuda.is_available() else "cpu"
    base_dir = os.path.dirname(os.path.abspath(__file__))
    checkpoint_path = os.path.join(base_dir, "talos_checkpoint.pt")
    data_path = os.path.join(base_dir, "training_data.txt")
    memory = TalosMemory()
    actions = TalosActionEngine()

    if os.path.exists(checkpoint_path):
        print("[SYSTEM] Loading Talos checkpoint...")
        model, optimizer, tokenizer, dataset = load_checkpoint(
            checkpoint_path,
            device,
        )
    else:
        print(f"[SYSTEM] Initializing from {data_path}...")
        dataset = load_training_file(data_path)
        tokenizer = TalosWordTokenizer()
        tokenizer.train("\n".join(normalize_pair(pair) for pair in dataset))
        model = MiniTalosLLM(vocab_size=tokenizer.vocab_size).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3)
        print(
            f"[SYSTEM] Training on {len(dataset)} pairs "
            f"(Vocab size: {tokenizer.vocab_size})..."
        )
        train_on_corpus(
            model,
            optimizer,
            tokenizer,
            dataset,
            steps=500,
            device=device,
            log_interval=100,
        )
        save_checkpoint(
            checkpoint_path,
            model,
            optimizer,
            tokenizer,
            dataset,
        )

    print("\n=== TALOS V2 PYTHON CORE ONLINE ===")
    print("Commands: '/fix ', '/remember ', '/clear', '/quit'\n")
    last_prompt_context = ""
    end_id = tokenizer.stoi["<END>"]

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue

        if user_input.lower() in ["/clear", "clear"]:
            os.system("cls" if os.name == "nt" else "clear")
            continue

        if user_input.lower() == "/quit":
            save_checkpoint(
                checkpoint_path,
                model,
                optimizer,
                tokenizer,
                dataset,
            )
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

            tokenizer.train("\n".join(normalize_pair(p) for p in dataset))
            if tokenizer.vocab_size != model.config["vocab_size"]:
                model = MiniTalosLLM(vocab_size=tokenizer.vocab_size).to(device)
                optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3)
                end_id = tokenizer.stoi["<END>"]
                # Full retrain only if a brand-new word expanded the vocabulary
                train_on_corpus(model, optimizer, tokenizer, dataset, steps=600, device=device, log_interval=200)
            else:
                # Fast targeted fine-tune on the new pair + small replay sample
                replay_sample = dataset[-64:] + ([new_pair] * 16)
                train_on_corpus(model, optimizer, tokenizer, replay_sample, steps=80, device=device, log_interval=40)

            save_checkpoint(checkpoint_path, model, optimizer, tokenizer, dataset)

            corrected = user_input[5:].strip()
            new_pair = f"{last_prompt_context}\nTalos: {corrected}\n"
            dataset.append(new_pair)
            append_to_training_file(new_pair, data_path)
            tokenizer.train("\n".join(normalize_pair(pair) for pair in dataset))

            if tokenizer.vocab_size != model.config["vocab_size"]:
                model = MiniTalosLLM(vocab_size=tokenizer.vocab_size).to(device)
                optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3)

            end_id = tokenizer.stoi["<END>"]
            print("[SYSTEM] Synced to training_data.txt. Fine-tuning...")
            train_on_corpus(
                model,
                optimizer,
                tokenizer,
                dataset,
                steps=400,
                device=device,
                log_interval=200,
            )
            save_checkpoint(
                checkpoint_path,
                model,
                optimizer,
                tokenizer,
                dataset,
            )

            _, action_result = actions.parse_and_execute(corrected)
            if action_result:
                print(f"[ACTION EXECUTED] {action_result}")
            print(f"[SYSTEM] Learned: '{corrected}'\n")
            continue

        clean_query = user_input.lower()
        recalled = memory.search(clean_query, top_k=2)

        if recalled:
            memory_block = "Memory: " + " | ".join(recalled) + "\n"
            print(f"[MEMORY RECALLED] {recalled}")
            last_prompt_context = f"{memory_block}User: {clean_query}"
        else:
            last_prompt_context = f"User: {clean_query}"

        full_prompt = f"{last_prompt_context}\nTalos:"
        input_ids = torch.tensor(
            [tokenizer.encode(full_prompt)],
            dtype=torch.long,
        ).to(device)
        output_ids = model.generate(
            input_ids,
            end_id=end_id,
            max_new_tokens=40,
        )
        prompt_length = input_ids.size(1)
        new_tokens = output_ids[0, prompt_length:].tolist()
        raw_reply = tokenizer.decode(new_tokens).strip()
        spoken_reply, action_result = actions.parse_and_execute(raw_reply)

        if action_result:
            print(f"[ACTION EXECUTED] {action_result}")
        print(f"Talos: {spoken_reply}\n")
