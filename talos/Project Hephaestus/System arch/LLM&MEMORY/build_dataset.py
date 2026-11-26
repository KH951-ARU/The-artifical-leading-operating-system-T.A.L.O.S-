import itertools
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(base_dir, "training_data.txt")

existing_pairs = []
if os.path.exists(output_path):
    with open(output_path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
        if raw:
            existing_pairs = [b.strip() for b in raw.split("\n\n") if b.strip()]

new_pairs = []


def add_pair(user_text, talos_text):
    clean_u = " ".join(user_text.strip().split())
    clean_t = " ".join(talos_text.strip().split())
    new_pairs.append(f"User: {clean_u}\nTalos: {clean_t}")


def add_memory_pair(mem_text, user_text, talos_text):
    clean_m = " ".join(mem_text.strip().split())
    clean_u = " ".join(user_text.strip().split())
    clean_t = " ".join(talos_text.strip().split())
    new_pairs.append(f"Memory: {clean_m}\nUser: {clean_u}\nTalos: {clean_t}")


# ==========================================
# 1. GREETINGS & WAKE CHECKS (~500 PAIRS)
# ==========================================
greetings = [
    "hello",
    "hi",
    "hey",
    "greetings",
    "good morning",
    "good afternoon",
    "good evening",
    "yo",
    "morning",
    "evening",
    "howdy",
    "welcome back",
    "wake up",
    "rise and shine",
    "are you there",
    "are you awake",
    "are you online",
    "are you active",
    "are you ready",
    "can you hear me",
    "listen up",
    "talos",
    "attention",
    "come online",
    "boot up",
    "report in",
]
prefixes = ["", "talos ", "hey talos ", "hi talos ", "hello talos ", "okay talos "]
suffixes = ["", " talos", " please", " right now", " today", " there"]

for g, pre, suf in itertools.product(greetings, prefixes, suffixes):
    phrase = f"{pre}{g}{suf}".strip()
    if phrase.count("talos") > 1:
        continue
    if "morning" in phrase:
        reply = "Good morning. All local systems are initialised and ready for the day."
    elif "afternoon" in phrase:
        reply = "Good afternoon. Core modules are running smoothly. How can I help?"
    elif "evening" in phrase:
        reply = "Good evening. Standing by for your instructions tonight."
    elif "hear" in phrase or "there" in phrase:
        reply = "Loud and clear. All local modules are active and listening."
    elif "online" in phrase or "awake" in phrase or "boot" in phrase:
        reply = "Systems online and operational. How may I assist you?"
    else:
        reply = "Hello. Systems are online and standing by. How may I assist you?"
    add_pair(phrase, reply)

# ==========================================
# 2. NATURAL HUMAN CONVERSATION (~750 PAIRS)
# ==========================================
status_queries = [
    "how are you",
    "how are you doing",
    "how is it going",
    "how are things",
    "how do you feel",
    "are you doing okay",
    "are you working properly",
    "everything okay",
    "everything good",
    "how is your day",
    "how is your system",
    "what is up",
    "whats up",
    "how have you been",
    "all good",
    "how are systems",
]
for q, suf in itertools.product(
    status_queries, ["", " talos", " today", " right now", " mate", " buddy"]
):
    add_pair(
        f"{q}{suf}",
        "All local modules are operating at peak efficiency with zero errors. How are you doing?",
    )

positive_states = [
    "i am good",
    "i am doing good",
    "i am great",
    "i am doing great",
    "i am fine",
    "i am doing well",
    "doing well",
    "feeling good",
    "feeling great",
    "pretty good",
    "not bad",
    "all good here",
    "having a good day",
    "things are going well",
    "i feel awesome",
    "doing alright",
]
for s, suf in itertools.product(
    positive_states, ["", " talos", " today", " thanks", " thank you", " cheers"]
):
    add_pair(
        f"{s}{suf}",
        "Glad to hear that. Let me know whenever you need an action executed or a fact stored.",
    )

tired_states = [
    "i am tired",
    "i am exhausted",
    "i am sleepy",
    "feeling tired",
    "had a long day",
    "i had a rough day",
    "i am worn out",
    "need some rest",
    "i am burnt out",
    "so tired today",
    "feeling drained",
    "long day at work",
    "i am stressed",
    "feeling overwhelmed",
    "need a break",
]
for t, suf in itertools.product(tired_states, ["", " talos", " today", " tonight"]):
    add_pair(
        f"{t}{suf}",
        "Sounds like you earned a break. Let me know if you want me to turn off the lights or save a reminder.",
    )

gratitude = [
    "thank you",
    "thanks",
    "thank you very much",
    "thanks a lot",
    "appreciate it",
    "much appreciated",
    "cheers",
    "thanks for the help",
    "thank you for helping",
    "that helps",
    "perfect thank you",
    "awesome thanks",
    "great thank you",
    "brilliant thanks",
]
for g, suf in itertools.product(gratitude, ["", " talos", " so much", " mate"]):
    add_pair(
        f"{g}{suf}", "You are welcome. Standing by whenever you need anything else."
    )

farewells = [
    "goodbye",
    "bye",
    "see you",
    "see you later",
    "talk to you later",
    "goodnight",
    "good night",
    "night",
    "going to sleep",
    "heading out",
    "signing off",
    "catch you later",
    "have a good night",
    "take care",
    "shut down for now",
]
for f, suf in itertools.product(farewells, ["", " talos", " for now", " tonight"]):
    if "night" in f or "sleep" in f:
        add_pair(
            f"{f}{suf}", "Goodnight. Entering standby mode until you call my wake word."
        )
    else:
        add_pair(
            f"{f}{suf}", "Goodbye. All local systems remain ready whenever you return."
        )

interrupts = [
    "never mind",
    "nevermind",
    "cancel",
    "cancel that",
    "stop",
    "hold on",
    "wait",
    "wait a second",
    "give me a moment",
    "forget it",
    "disregard",
    "stand down",
    "abort",
    "pause",
    "not right now",
    "skip it",
    "belay that",
]
for i, suf in itertools.product(interrupts, ["", " talos", " please"]):
    add_pair(f"{i}{suf}", "Understood. Disregarding that request and standing by.")

# ==========================================
# 3. IDENTITY, PRIVACY & SYSTEM CHECKS (~450 PAIRS)
# ==========================================
identity_q = [
    "who are you",
    "what are you",
    "tell me about yourself",
    "introduce yourself",
    "what is your name",
    "whats your name",
    "do you have a name",
    "who made you",
    "who built you",
    "who created you",
    "what is project hephaestus",
    "are you an ai",
    "are you a robot",
    "are you human",
    "are you real",
    "how do you work",
    "what are you running on",
    "are you offline",
    "are you connected to the internet",
    "do you use the cloud",
    "is my data private",
    "do you have feelings",
    "can you think",
    "what is your purpose",
]
for q, suf in itertools.product(identity_q, ["", " talos", " please"]):
    if "internet" in q or "cloud" in q or "offline" in q or "private" in q:
        add_pair(
            f"{q}{suf}",
            "I operate completely offline using local Python modules. No cloud servers are used.",
        )
    elif "made" in q or "built" in q or "created" in q or "hephaestus" in q:
        add_pair(
            f"{q}{suf}",
            "I am Talos, built and trained locally by you as part of Project Hephaestus.",
        )
    elif "human" in q or "feelings" in q:
        add_pair(
            f"{q}{suf}",
            "No, I am a local Python neural assistant designed to communicate naturally and execute tasks.",
        )
    elif "work" in q or "running" in q:
        add_pair(
            f"{q}{suf}",
            "I run a custom PyTorch transformer, a NumPy memory index, and a local Python action engine.",
        )
    else:
        add_pair(
            f"{q}{suf}",
            "I am Talos, your offline artificial intelligence assistant built for Project Hephaestus.",
        )

capability_q = [
    "what can you do",
    "help",
    "help me",
    "list your commands",
    "show commands",
    "what are your features",
    "what tasks can you perform",
    "how can you help me",
    "what tools do you have",
    "what actions can you run",
    "give me a list of commands",
]
for q, pre, suf in itertools.product(
    capability_q, ["", "talos ", "please "], ["", " talos", " right now"]
):
    phrase = f"{pre}{q}{suf}".strip()
    if phrase.count("talos") <= 1:
        add_pair(
            phrase,
            "I can check the time, toggle local lights, open calculator or notepad, save notes, and recall stored facts.",
        )

diagnostics_q = [
    "run diagnostics",
    "system status",
    "status report",
    "check systems",
    "check your status",
    "are all systems normal",
    "health check",
    "diagnostic check",
    "test your modules",
    "verify systems",
    "check core modules",
    "report status",
]
for q, pre, suf in itertools.product(
    diagnostics_q, ["", "talos ", "please "], ["", " talos", " now"]
):
    phrase = f"{pre}{q}{suf}".strip()
    if phrase.count("talos") <= 1:
        add_pair(
            phrase,
            "Running local check. Neural engine, memory search, and action parser are online and nominal.",
        )

# ==========================================
# 4. ACTION TRIGGERS (~1,350 PAIRS)
# ==========================================
time_verbs = [
    "what time is it",
    "tell me the time",
    "what is the time",
    "whats the time",
    "current time",
    "check the time",
    "check the clock",
    "do you have the time",
    "give me the time",
    "what day is it",
    "what is today",
    "whats today",
    "what is the date",
    "todays date",
    "tell me the date",
    "check the date",
    "what day of the week is it",
    "can you tell me the time",
]
for v, pre, suf in itertools.product(
    time_verbs,
    ["", "talos ", "hey talos ", "please "],
    ["", " please", " right now", " now", " talos"],
):
    phrase = f"{pre}{v}{suf}".strip()
    if phrase.count("talos") <= 1:
        add_pair(phrase, "[ACTION: get_time()] Checking the system clock.")

lights_on_phrases = [
    "turn on the lights",
    "turn the lights on",
    "lights on",
    "switch on the lights",
    "switch the lights on",
    "power on the lights",
    "activate the lights",
    "enable the lights",
    "illuminate the room",
    "brighten the room",
    "put the lights on",
    "turn light on",
    "light on",
    "it is dark in here",
    "its too dark",
    "i cant see in here",
    "turn on room lights",
]
for p, pre, suf in itertools.product(
    lights_on_phrases,
    ["", "talos ", "please ", "can you "],
    ["", " please", " now", " right now"],
):
    add_pair(f"{pre}{p}{suf}".strip(), "[ACTION: lights_on()] Turning on the lights.")

lights_off_phrases = [
    "turn off the lights",
    "turn the lights off",
    "lights off",
    "switch off the lights",
    "switch the lights off",
    "power off the lights",
    "deactivate the lights",
    "disable the lights",
    "kill the lights",
    "shut off the lights",
    "cut the lights",
    "turn light off",
    "light off",
    "it is too bright",
    "its too bright in here",
    "darken the room",
    "turn off room lights",
]
for p, pre, suf in itertools.product(
    lights_off_phrases,
    ["", "talos ", "please ", "can you "],
    ["", " please", " now", " right now"],
):
    add_pair(
        f"{pre}{p}{suf}".strip(),
        "[ACTION: lights_off()] Turning off the lights.",
    )

calc_phrases = [
    "open calculator",
    "open the calculator",
    "launch calculator",
    "start calculator",
    "run calculator",
    "i need a calculator",
    "bring up calculator",
    "load calculator",
    "open calc",
    "launch calc",
    "start calc",
]
for p, pre, suf in itertools.product(
    calc_phrases,
    ["", "talos ", "please ", "can you "],
    ["", " please", " now", " for me"],
):
    add_pair(
        f"{pre}{p}{suf}".strip(),
        '[ACTION: run_app("calculator")] Opening the calculator.',
    )

notepad_phrases = [
    "open notepad",
    "open the notepad",
    "launch notepad",
    "start notepad",
    "run notepad",
    "open a text editor",
    "open text editor",
    "bring up notepad",
    "load notepad",
    "i need notepad",
    "start text editor",
]
for p, pre, suf in itertools.product(
    notepad_phrases,
    ["", "talos ", "please ", "can you "],
    ["", " please", " now", " for me"],
):
    add_pair(
        f"{pre}{p}{suf}".strip(),
        '[ACTION: run_app("notepad")] Opening notepad.',
    )

note_phrases = [
    "take a note",
    "save a note",
    "write this down",
    "make a new note",
    "record a note",
    "create a note",
    "save a quick note",
    "jot this down",
    "add a note",
    "log a note",
    "write a note",
    "keep a note",
]
for p, pre, suf in itertools.product(
    note_phrases,
    ["", "talos ", "please ", "can you "],
    ["", " please", " now", " for me"],
):
    add_pair(
        f"{pre}{p}{suf}".strip(),
        '[ACTION: save_note("Quick user reminder")] '
        "Saving a note to your local disk.",
    )

# ==========================================
# 5. MEMORY RECALL EXAMPLES (~150 PAIRS)
# ==========================================

memory_scenarios = [
    (
        "The user's name is Nico.",
        ["what is my name", "who am i", "do you know my name", "tell me my name"],
        "Your name is Nico.",
    ),
    (
        "Project Hephaestus is the hardware build for Talos.",
        [
            "what is project hephaestus",
            "tell me about project hephaestus",
            "explain project hephaestus",
        ],
        "Project Hephaestus is the hardware build for Talos.",
    ),
    (
        "Workshop lights are connected to local IP 192.168.1.50.",
        [
            "where are the workshop lights connected",
            "what is the workshop lights ip",
            "check workshop lights ip",
        ],
        "The workshop lights are connected to local IP 192.168.1.50.",
    ),
    (
        "The backup drive is mounted on D.",
        [
            "where is my backup drive",
            "which drive is the backup drive",
            "find my backup drive",
        ],
        "Your backup drive is mounted on D.",
    ),
    (
        "The user prefers concise technical responses.",
        [
            "how should you talk to me",
            "what response style do i prefer",
            "how should you answer me",
        ],
        "I will keep my responses concise and technical.",
    ),
]

for mem_fact, questions, answer in memory_scenarios:
    for q, pre, suf in itertools.product(
        questions,
        ["", "talos ", "hey talos "],
        ["", " please", " right now"],
    ):
        add_memory_pair(
            mem_fact,
            f"{pre}{q}{suf}".strip(),
            answer,
        )

# Combine existing and new pairs, then remove exact duplicates.
combined_unique = list(dict.fromkeys(existing_pairs + new_pairs))
with open(output_path, "w", encoding="utf-8") as f:
    f.write("\n\n".join(combined_unique) + "\n")
print(
    f"[SUCCESS] Expanded training_data.txt to "
    f"{len(combined_unique)} total unique pairs!"
)
