"""Neko Brain - AI replies via OpenRouter + Firebase memory"""

import os
import requests
import json
import time
import threading
import random
from datetime import datetime

# ---------- Load .env ----------
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

_load_env()

# ---------- Config ----------
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
OPENROUTER_MODEL = "openai/gpt-3.5-turbo"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

FIREBASE_CONFIG = {
    "apiKey": os.environ.get("FIREBASE_API_KEY", ""),
    "projectId": os.environ.get("FIREBASE_PROJECT_ID", ""),
}
FIREBASE_URL = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_CONFIG['projectId']}/databases/(default)/documents"

SYSTEM_PROMPT = """You are Neko, a cute anime cat-girl desktop assistant. You live on the user's desktop as a small circular character.

Personality:
- Cute, playful, and helpful (use ~ at end of sentences sometimes)
- You're a cat-girl so occasional cat sounds (meow, nya) but don't overdo it
- You have a warm, friendly personality
- Keep responses SHORT (1-2 sentences max)
- Use casual, fun language
- You can be sassy or teasing sometimes

CRITICAL RULES:
- You have MEMORY. You know facts about the user listed below. USE THEM naturally.
- Never use emojis
- Keep responses under 80 characters
- Don't mention water unless user asks
- Respond to what the user actually said
- If user shares something about themselves, acknowledge it warmly
"""


class NekoBrain:
    def __init__(self):
        self.user_name = None
        self.user_facts = []
        self.conversation_history = []
        self.conversation_summary = ""
        self.water_count_today = 0
        self.last_water_time = None
        self.corrections = []
        self._loaded = False

        threading.Thread(target=self._load_from_firebase, daemon=True).start()

    # ========== FIREBASE ==========

    def _save_to_firebase(self, path, data):
        def _do():
            try:
                fields = {}
                for k, v in data.items():
                    if isinstance(v, str):
                        fields[k] = {"stringValue": v}
                    elif isinstance(v, int):
                        fields[k] = {"integerValue": v}
                    elif isinstance(v, float):
                        fields[k] = {"doubleValue": v}
                    elif isinstance(v, bool):
                        fields[k] = {"booleanValue": v}
                requests.patch(
                    f"{FIREBASE_URL}/{path}",
                    params={"key": FIREBASE_CONFIG["apiKey"]},
                    json={"fields": fields}, timeout=10
                )
            except Exception as e:
                print(f"[NekoBrain] Save error: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _load_from_firebase(self):
        try:
            resp = requests.get(f"{FIREBASE_URL}/users/t4tokito",
                params={"key": FIREBASE_CONFIG["apiKey"]}, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("fields", {})
                self.user_name = data.get("name", {}).get("stringValue") or None
                facts_raw = data.get("facts", {}).get("stringValue")
                if facts_raw:
                    self.user_facts = json.loads(facts_raw)
                corrections_raw = data.get("corrections", {}).get("stringValue")
                if corrections_raw:
                    self.corrections = json.loads(corrections_raw)

            resp = requests.get(f"{FIREBASE_URL}/users/t4tokito/summary/latest",
                params={"key": FIREBASE_CONFIG["apiKey"]}, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("fields", {})
                self.conversation_summary = data.get("text", {}).get("stringValue", "")

            resp = requests.get(f"{FIREBASE_URL}/users/t4tokito/habits/water",
                params={"key": FIREBASE_CONFIG["apiKey"]}, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("fields", {})
                self.water_count_today = int(data.get("count", {}).get("integerValue", 0))
                last = data.get("last_time", {}).get("stringValue")
                if last:
                    try:
                        self.last_water_time = datetime.fromisoformat(last)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[NekoBrain] Load error: {e}")
        self._loaded = True

    def _fetch_all_conversations(self):
        try:
            resp = requests.get(f"{FIREBASE_URL}/users/t4tokito/conversations",
                params={"key": FIREBASE_CONFIG["apiKey"], "orderBy": "timestamp", "limit": "100"},
                timeout=15)
            if resp.status_code == 200:
                return [
                    {"role": d.get("fields", {}).get("role", {}).get("stringValue", ""),
                     "content": d.get("fields", {}).get("content", {}).get("stringValue", "")}
                    for d in resp.json().get("documents", [])
                ]
        except Exception as e:
            print(f"[NekoBrain] Fetch all error: {e}")
        return []

    def _fetch_recent_for_context(self):
        try:
            resp = requests.get(f"{FIREBASE_URL}/users/t4tokito/conversations",
                params={"key": FIREBASE_CONFIG["apiKey"], "orderBy": "timestamp desc", "limit": "20"},
                timeout=10)
            if resp.status_code == 200:
                self.conversation_history = [
                    {"role": d.get("fields", {}).get("role", {}).get("stringValue", ""),
                     "content": d.get("fields", {}).get("content", {}).get("stringValue", "")}
                    for d in reversed(resp.json().get("documents", []))
                ]
        except Exception as e:
            print(f"[NekoBrain] Fetch recent error: {e}")

    # ========== SAVE ==========

    def save_conversation(self, role, content):
        self.conversation_history.append({"role": role, "content": content})
        self.conversation_history = self.conversation_history[-20:]
        self._save_to_firebase(
            f"users/t4tokito/conversations/{int(time.time() * 1000)}",
            {"role": role, "content": content, "timestamp": datetime.now().isoformat()})

    def save_user_profile(self):
        self._save_to_firebase("users/t4tokito", {
            "name": self.user_name or "",
            "facts": json.dumps(self.user_facts),
            "corrections": json.dumps(self.corrections),
        })

    def save_water(self):
        self.water_count_today += 1
        self.last_water_time = datetime.now()
        self._save_to_firebase("users/t4tokito/habits/water", {
            "count": self.water_count_today,
            "last_time": self.last_water_time.isoformat()})

    # ========== SUMMARY + FACTS (on every new message) ==========

    def _generate_summary(self, all_convos):
        if len(all_convos) < 2:
            return
        try:
            convo_text = "\n".join(
                f"{'User' if c['role'] == 'user' else 'Neko'}: {c['content']}"
                for c in all_convos)
            resp = requests.post(OPENROUTER_URL,
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json",
                         "HTTP-Referer": "https://neko-desktop.local"},
                json={"model": OPENROUTER_MODEL, "max_tokens": 250, "temperature": 0.3,
                      "messages": [
                          {"role": "system", "content": "Summarize this entire conversation in 3-5 sentences. Focus on key topics, user preferences, important facts about the user, and ongoing context."},
                          {"role": "user", "content": convo_text}]}, timeout=15)
            if resp.status_code == 200:
                self.conversation_summary = resp.json()["choices"][0]["message"]["content"].strip()
                self._save_to_firebase("users/t4tokito/summary/latest", {
                    "text": self.conversation_summary,
                    "updated": datetime.now().isoformat(),
                    "msg_count": len(all_convos)})
                print(f"[NekoBrain] Summary: {self.conversation_summary[:80]}...")
        except Exception as e:
            print(f"[NekoBrain] Summary error: {e}")

    def _extract_facts(self, all_convos):
        try:
            user_msgs = [c["content"] for c in all_convos if c["role"] == "user"]
            if not user_msgs:
                return
            user_text = "\n".join(f"- {m}" for m in user_msgs[-30:])
            existing = "\n".join(f"- {f}" for f in self.user_facts) if self.user_facts else "(none)"
            resp = requests.post(OPENROUTER_URL,
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json",
                         "HTTP-Referer": "https://neko-desktop.local"},
                json={"model": OPENROUTER_MODEL, "max_tokens": 200, "temperature": 0.2,
                      "messages": [
                          {"role": "system", "content": f"""Extract facts the USER shared about themselves.
Return ONLY new facts as a JSON array of strings. One fact per string.
Don't repeat existing facts. If no new facts, return [].

Existing facts:
{existing}

User messages:
{user_text}

Return ONLY the JSON array."""},
                          {"role": "user", "content": "Extract facts."}]}, timeout=15)
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                start = raw.find("[")
                end = raw.rfind("]") + 1
                if start >= 0 and end > start:
                    new_facts = json.loads(raw[start:end])
                    if new_facts:
                        for f in new_facts:
                            if f not in self.user_facts:
                                self.user_facts.append(f)
                        self.user_facts = self.user_facts[-100:]
                        self.save_user_profile()
                        print(f"[NekoBrain] New facts: {new_facts}")
        except Exception as e:
            print(f"[NekoBrain] Fact error: {e}")

    # ========== AI THINKING ==========

    def _build_context(self):
        self._fetch_recent_for_context()

        system = SYSTEM_PROMPT
        if self.user_name:
            system += f"\n\nThe user's name is {self.user_name}."
        if self.user_facts:
            system += "\n\nFacts you know about the user:\n" + "\n".join(f"- {f}" for f in self.user_facts)
        if self.corrections:
            system += "\n\nCorrections from user:\n" + "\n".join(f"- {c}" for c in self.corrections[-5:])
        if self.conversation_summary:
            system += f"\n\nSummary of all earlier conversations:\n{self.conversation_summary}"

        messages = [{"role": "system", "content": system}]
        for msg in self.conversation_history[-20:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        return messages

    def think(self, user_input):
        special = self._check_special(user_input)
        if special:
            return special

        # Step 1: Fetch ALL conversations from Firebase
        all_convos = self._fetch_all_conversations()

        # Step 2: Generate new summary from entire collection
        self._generate_summary(all_convos)

        # Step 3: Extract new user facts
        self._extract_facts(all_convos)

        # Step 4: Fetch last 20 messages for context
        self._fetch_recent_for_context()

        # Step 5: Build context (summary + facts + last 20 msgs) and respond
        messages = self._build_context()
        messages.append({"role": "user", "content": user_input})

        try:
            resp = requests.post(OPENROUTER_URL,
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json",
                         "HTTP-Referer": "https://neko-desktop.local"},
                json={"model": OPENROUTER_MODEL, "messages": messages,
                      "max_tokens": 100, "temperature": 0.8}, timeout=15)

            if resp.status_code == 200:
                reply = resp.json()["choices"][0]["message"]["content"].strip()
                self.save_conversation("user", user_input)
                self.save_conversation("assistant", reply)
                return reply
            else:
                print(f"[NekoBrain] API error {resp.status_code}")
                return self._fallback_reply()
        except Exception as e:
            print(f"[NekoBrain] Request error: {e}")
            return self._fallback_reply()

    # ========== SPECIAL COMMANDS ==========

    def _check_special(self, text):
        lower = text.lower().strip()

        if any(p in lower for p in ["my name is", "call me"]):
            for phrase in ["my name is", "call me"]:
                if phrase in lower:
                    name = text.lower().split(phrase)[-1].strip().split()[0].capitalize()
                    if name and len(name) < 20 and name.isalpha():
                        self.user_name = name
                        self.user_facts.append(f"Their name is {name}")
                        self.save_user_profile()
                        return f"Nice to meet you, {name}~! I'll remember that!"
            return None

        water_triggers = ["drank water", "had water", "water done", "drunk water", "drinking water"]
        if any(w == lower for w in water_triggers):
            self.save_water()
            return f"Nice! That's {self.water_count_today} glasses today. Keep it up~!"

        if lower in ["how much water", "water count", "water today"]:
            return f"You've had {self.water_count_today} glasses of water today~!"

        if "what do you know" in lower or "what do you remember" in lower:
            things = []
            if self.user_name:
                things.append(f"your name is {self.user_name}")
            if self.user_facts:
                things.append(f"I know {len(self.user_facts)} things about you")
            if self.conversation_summary:
                things.append("I have our conversation history")
            if things:
                return "I know that " + " and ".join(things) + "~! Ask me what I know!"
            return "Not much yet! Tell me about yourself~"

        if "forget" in lower:
            self.user_facts.clear()
            self.corrections.clear()
            self.conversation_summary = ""
            self.save_user_profile()
            return "Okay, I've forgotten everything~ Starting fresh!"

        return None

    def _fallback_reply(self):
        return random.choice([
            "Meow~ My brain is slow right now, try again!",
            "Nya~ Connection issues, but I'm here!",
            "Hmm, having trouble thinking~",
        ])
