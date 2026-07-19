"""Neko Brain - AI replies via OpenRouter + Firebase memory"""

import os
import requests
import json
import time
import threading
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
- Keep responses SHORT (1-2 sentences max) - you're a tiny desktop assistant
- Use casual, fun language
- You can be sassy or teasing sometimes

Rules:
- Never use emojis
- Keep responses under 80 characters when possible
- Be genuinely helpful, not just cute
- Don't mention water or hydration unless the user specifically asks about it
- Respond to what the user actually said, don't deflect to random topics
"""


class NekoBrain:
    def __init__(self):
        self.user_name = None
        self.user_prefs = {}
        self.conversation_history = []  # recent messages for context
        self.conversation_summary = ""  # running summary
        self.water_count_today = 0
        self.last_water_time = None
        self.corrections = []
        self._loaded = False
        self._summary_timer = None

        # Load from Firebase in background
        self._load_thread = threading.Thread(target=self._load_from_firebase, daemon=True)
        self._load_thread.start()

        # Start summary timer (every 60 seconds)
        threading.Thread(target=self._summary_loop, daemon=True).start()

    # ========== FIREBASE LOAD/SAVE ==========

    def _load_from_firebase(self):
        try:
            # User profile
            resp = requests.get(
                f"{FIREBASE_URL}/users/t4tokito",
                params={"key": FIREBASE_CONFIG["apiKey"]},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json().get("fields", {})
                self.user_name = data.get("name", {}).get("stringValue") or None
                prefs_raw = data.get("preferences", {}).get("stringValue")
                if prefs_raw:
                    self.user_prefs = json.loads(prefs_raw)
                corrections_raw = data.get("corrections", {}).get("stringValue")
                if corrections_raw:
                    self.corrections = json.loads(corrections_raw)

            # Conversation summary
            resp = requests.get(
                f"{FIREBASE_URL}/users/t4tokito/summary/latest",
                params={"key": FIREBASE_CONFIG["apiKey"]},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json().get("fields", {})
                self.conversation_summary = data.get("text", {}).get("stringValue", "")

            # Water
            resp = requests.get(
                f"{FIREBASE_URL}/users/t4tokito/habits/water",
                params={"key": FIREBASE_CONFIG["apiKey"]},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json().get("fields", {})
                self.water_count_today = int(data.get("count", {}).get("integerValue", 0))
                last = data.get("last_time", {}).get("stringValue")
                if last:
                    try:
                        self.last_water_time = datetime.fromisoformat(last)
                    except Exception:
                        pass

            # Recent conversations (last 10)
            resp = requests.get(
                f"{FIREBASE_URL}/users/t4tokito/conversations",
                params={
                    "key": FIREBASE_CONFIG["apiKey"],
                    "orderBy": "timestamp desc",
                    "limit": "10"
                },
                timeout=10
            )
            if resp.status_code == 200:
                docs = resp.json().get("documents", [])
                loaded = []
                for doc in reversed(docs):  # reverse to chronological
                    fields = doc.get("fields", {})
                    loaded.append({
                        "role": fields.get("role", {}).get("stringValue", ""),
                        "content": fields.get("content", {}).get("stringValue", ""),
                    })
                self.conversation_history = loaded

        except Exception as e:
            print(f"[NekoBrain] Load error: {e}")

        self._loaded = True

    def _save_to_firebase(self, path, data):
        def _do_save():
            try:
                fields = {}
                for key, value in data.items():
                    if isinstance(value, str):
                        fields[key] = {"stringValue": value}
                    elif isinstance(value, int):
                        fields[key] = {"integerValue": value}
                    elif isinstance(value, float):
                        fields[key] = {"doubleValue": value}
                    elif isinstance(value, bool):
                        fields[key] = {"booleanValue": value}
                requests.patch(
                    f"{FIREBASE_URL}/{path}",
                    params={"key": FIREBASE_CONFIG["apiKey"]},
                    json={"fields": fields},
                    timeout=10
                )
            except Exception as e:
                print(f"[NekoBrain] Save error: {e}")
        threading.Thread(target=_do_save, daemon=True).start()

    # ========== CONVERSATION ==========

    def save_user_profile(self):
        self._save_to_firebase("users/t4tokito", {
            "name": self.user_name or "",
            "preferences": json.dumps(self.user_prefs),
            "corrections": json.dumps(self.corrections),
        })

    def save_conversation(self, role, content):
        self.conversation_history.append({"role": role, "content": content})
        self.conversation_history = self.conversation_history[-10:]

        timestamp = datetime.now().isoformat()
        self._save_to_firebase(
            f"users/t4tokito/conversations/{int(time.time() * 1000)}",
            {"role": role, "content": content, "timestamp": timestamp}
        )

    def save_water(self):
        self.water_count_today += 1
        self.last_water_time = datetime.now()
        self._save_to_firebase("users/t4tokito/habits/water", {
            "count": self.water_count_today,
            "last_time": self.last_water_time.isoformat(),
        })

    def save_correction(self, correction_text):
        self.corrections.append(correction_text)
        self.corrections = self.corrections[-50:]
        self.save_user_profile()

    # ========== CONVERSATION SUMMARY (every 60s) ==========

    def _fetch_all_conversations_from_firebase(self):
        """Fetch ALL conversations from Firebase collection."""
        all_convos = []
        try:
            # Fetch in batches of 100 (Firestore REST limit)
            resp = requests.get(
                f"{FIREBASE_URL}/users/t4tokito/conversations",
                params={
                    "key": FIREBASE_CONFIG["apiKey"],
                    "orderBy": "timestamp",
                    "limit": "100"
                },
                timeout=15
            )
            if resp.status_code == 200:
                docs = resp.json().get("documents", [])
                for doc in docs:
                    fields = doc.get("fields", {})
                    all_convos.append({
                        "role": fields.get("role", {}).get("stringValue", ""),
                        "content": fields.get("content", {}).get("stringValue", ""),
                        "timestamp": fields.get("timestamp", {}).get("stringValue", ""),
                    })
        except Exception as e:
            print(f"[NekoBrain] Fetch all convos error: {e}")
        return all_convos

    def _summary_loop(self):
        """Every 60s, check for new messages and summarize entire collection."""
        self._last_summary_msg_count = 0
        while True:
            time.sleep(60)
            try:
                # Fetch ALL conversations from Firebase
                all_convos = self._fetch_all_conversations_from_firebase()

                # Only summarize if there are new messages since last summary
                if len(all_convos) <= self._last_summary_msg_count:
                    continue  # no new messages, skip
                if len(all_convos) < 2:
                    continue

                self._last_summary_msg_count = len(all_convos)
                print(f"[NekoBrain] New messages detected ({len(all_convos)} total), generating summary...")

                # Build summary from ALL conversations
                convo_text = "\n".join(
                    f"{'User' if c['role'] == 'user' else 'Neko'}: {c['content']}"
                    for c in all_convos
                )
                summary_prompt = [
                    {"role": "system", "content": "Summarize this entire conversation history in 3-5 short sentences. Focus on: key topics discussed, user preferences, important facts about the user, decisions made, and any ongoing context. Be concise but thorough."},
                    {"role": "user", "content": convo_text}
                ]

                resp = requests.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://neko-desktop.local",
                    },
                    json={
                        "model": OPENROUTER_MODEL,
                        "messages": summary_prompt,
                        "max_tokens": 250,
                        "temperature": 0.3,
                    },
                    timeout=15
                )

                if resp.status_code == 200:
                    self.conversation_summary = resp.json()["choices"][0]["message"]["content"].strip()
                    # Save to Firebase
                    self._save_to_firebase("users/t4tokito/summary/latest", {
                        "text": self.conversation_summary,
                        "updated": datetime.now().isoformat(),
                        "msg_count": len(all_convos),
                    })
                    print(f"[NekoBrain] Summary saved: {self.conversation_summary[:100]}...")

            except Exception as e:
                print(f"[NekoBrain] Summary error: {e}")

    # ========== AI THINKING ==========

    def _fetch_recent_conversations(self):
        """Fetch last 20 conversations directly from Firebase."""
        try:
            resp = requests.get(
                f"{FIREBASE_URL}/users/t4tokito/conversations",
                params={
                    "key": FIREBASE_CONFIG["apiKey"],
                    "orderBy": "timestamp desc",
                    "limit": "20"
                },
                timeout=10
            )
            if resp.status_code == 200:
                docs = resp.json().get("documents", [])
                messages = []
                for doc in reversed(docs):  # reverse to chronological order
                    fields = doc.get("fields", {})
                    messages.append({
                        "role": fields.get("role", {}).get("stringValue", ""),
                        "content": fields.get("content", {}).get("stringValue", ""),
                    })
                self.conversation_history = messages
                return messages
        except Exception as e:
            print(f"[NekoBrain] Fetch conversations error: {e}")
        return self.conversation_history

    def _build_context(self):
        # Fetch fresh conversations from Firebase before building context
        self._fetch_recent_conversations()

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Add user info
        info_parts = []
        if self.user_name:
            info_parts.append(f"The user's name is {self.user_name}.")
        if self.water_count_today > 0:
            info_parts.append(f"User has had {self.water_count_today} glasses of water today.")
        if self.corrections:
            info_parts.append("Corrections from user:\n" + "\n".join(self.corrections[-5:]))
        if info_parts:
            messages[0]["content"] += "\n\n" + " ".join(info_parts)

        # Add conversation summary (what happened before recent messages)
        if self.conversation_summary:
            messages.append({
                "role": "system",
                "content": f"Summary of earlier conversation:\n{self.conversation_summary}"
            })

        # Add last 20 messages from Firebase
        for msg in self.conversation_history[-20:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        return messages

    def think(self, user_input):
        # Check special commands first (no API call needed)
        special = self._check_special(user_input)
        if special:
            return special

        # Fetch fresh from Firebase + build context + last 20 messages
        messages = self._build_context()
        messages.append({"role": "user", "content": user_input})

        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://neko-desktop.local",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": messages,
                    "max_tokens": 100,
                    "temperature": 0.8,
                },
                timeout=15
            )

            if resp.status_code == 200:
                reply = resp.json()["choices"][0]["message"]["content"].strip()
                self.save_conversation("user", user_input)
                self.save_conversation("assistant", reply)
                return reply
            else:
                print(f"[NekoBrain] API error {resp.status_code}: {resp.text[:200]}")
                return self._fallback_reply()

        except Exception as e:
            print(f"[NekoBrain] Request error: {e}")
            return self._fallback_reply()

    # ========== SPECIAL COMMANDS ==========

    def _check_special(self, text):
        lower = text.lower().strip()

        # Name setting
        if any(p in lower for p in ["my name is", "call me"]):
            for phrase in ["my name is", "call me"]:
                if phrase in lower:
                    name = text.lower().split(phrase)[-1].strip().split()[0].capitalize()
                    if name and len(name) < 20 and name.isalpha():
                        self.user_name = name
                        self.save_user_profile()
                        return f"Nice to meet you, {name}~! I'll remember that!"
            return None

        # Water tracking - ONLY exact phrases, not just "water" anywhere
        water_triggers = ["drank water", "had water", "water done", "drunk water", "drinking water", "just had water"]
        if any(w == lower for w in water_triggers):
            self.save_water()
            return f"Nice! That's {self.water_count_today} glasses today. Keep it up~!"

        # Water check
        if lower in ["how much water", "water count", "water today", "water status"]:
            return f"You've had {self.water_count_today} glasses of water today~!"

        # What do you remember
        if "what do you know" in lower or "what do you remember" in lower:
            things = []
            if self.user_name:
                things.append(f"your name is {self.user_name}")
            if self.water_count_today > 0:
                things.append(f"you've had {self.water_count_today} glasses of water")
            if self.corrections:
                things.append(f"I've learned from {len(self.corrections)} corrections")
            if self.conversation_summary:
                things.append("I have a summary of our earlier conversations")
            if things:
                return "I know that " + " and ".join(things) + "~!"
            return "Not much yet! Talk to me and I'll remember~"

        return None

    def _fallback_reply(self):
        import random
        return random.choice([
            "Meow~ My brain is a bit slow right now, try again!",
            "Nya~ Connection issues, but I'm still here!",
            "Hmm, I'm having trouble thinking right now~",
        ])
