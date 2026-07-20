#!/usr/bin/env python3
"""Neko - Desktop assistant with circular character image"""

# Force X11 backend via XWayland on Wayland sessions (GNOME doesn't support Layer Shell)
import os
if os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ["GDK_BACKEND"] = "x11"

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('cairo', '1.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
import cairo
import random
import time
import threading
import subprocess
import math
from brain import NekoBrain

# ---------- Config ----------
WINDOW_SIZE = 112
CHAT_WIDTH = 320
CHAT_HEIGHT = 420
WATER_INTERVAL = 900
IDLE_INTERVAL = 120
IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

# ---------- Responses ----------
RESPONSES = {
    'hello': ['Hiii~!', 'Hey there!', 'Nyaa~ How can I help?'],
    'hi': ['Hiii~!', 'Hey hey!', 'Nyaa~'],
    'hey': ['Hey there!', 'Hiii~'],
    'yo': ['Yo yo~!', 'Hey!'],
    'how are you': ['Purring nicely, thanks~', 'Happy you\'re here!'],
    'what are you': ['I\'m Neko! Your desktop assistant~'],
    'who are you': ['The name\'s Neko! I live on your desktop~'],
    'water': ['Drink some water~!', 'Hydration is key!'],
    'drink': ['Drink some water~ Stay hydrated!'],
    'hungry': ['Grab a snack, but drink water too~'],
    'tired': ['Take a break! Stretch and drink water~'],
    'joke': [
        'Why do cats win at games? Nine lives to practice!',
        'What do cats eat? Mice Krispies!',
        'Why was the cat good at math? Purr-cent calculator!',
    ],
    'love': ['You\'re the best~!', '*purrs happily*'],
    'cute': ['No you~!', '*hides behind ears*'],
    'bored': ['Talk to me! Or show me your screen~'],
    'screen': ['Click the camera button to show me your screen~'],
    'help': ['Chat with me, ask for jokes, or show me your screen!'],
    'bye': ['Bye bye~ Stay hydrated!', 'Come back soon!'],
}
DEFAULT_RESPONSES = [
    'Meow~ Tell me more!', 'Interesting~!', 'Go on!', "I'm listening~",
    'Hehe~ Nice!', 'My cat brain is trying~', "You're fun to talk to!",
]
WATER_MESSAGES = [
    'Drink some water~!', 'Hydration time!', 'Have some water~',
    'Remember to stay hydrated!', 'Water break~', 'Drink water, friend!',
]
IDLE_MESSAGES = [
    'Meow~ Still here!', '*stretches* Nice day~',
    "Don't forget to stretch!", '*purrs* Talk to me~',
    "You're doing great!", 'Remember breaks~',
    'I like sitting on your desktop~', '*wags tail* Hey~',
]


def get_response(text):
    lower = text.lower().strip()
    for key, replies in RESPONSES.items():
        if key in lower:
            return random.choice(replies)
    return random.choice(DEFAULT_RESPONSES)


def make_circle_image(path, size):
    from PIL import Image, ImageDraw
    import io
    try:
        pil_img = Image.open(path).convert("RGBA")
    except Exception:
        pil_img = Image.new("RGBA", (size, size), (255, 179, 193, 255))
    w, h = pil_img.size
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        pil_img = pil_img.crop((left, top, left + side, top + side))
    pil_img = pil_img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    pil_img.putalpha(mask)
    draw2 = ImageDraw.Draw(pil_img)
    draw2.ellipse((0, 0, size - 1, size - 1), outline=(255, 130, 150, 255), width=3)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    loader = GdkPixbuf.PixbufLoader()
    loader.write(buf.read())
    loader.close()
    return loader.get_pixbuf()


def force_above_x11(window):
    """Force always-on-top via X11 for XWayland or native X11."""
    gdk_win = window.get_window()
    if not gdk_win:
        return
    xid = gdk_win.get_xid()
    if not xid:
        return
    # Use xdotool or wmctrl
    try:
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", str(xid)],
            timeout=2, capture_output=True
        )
    except Exception:
        pass
    # Set _NET_WM_STATE_ABOVE via xprop
    try:
        subprocess.run(
            ["xprop", "-id", str(xid),
             "-f", "_NET_WM_STATE_ABOVE", "32c",
             "-set", "_NET_WM_STATE_ABOVE", "_NET_WM_STATE_ABOVE"],
            timeout=2, capture_output=True
        )
    except Exception:
        pass
    # Also try via wmctrl
    try:
        subprocess.run(
            ["wmctrl", "-i", "-r", str(xid), "-b", "add,above"],
            timeout=2, capture_output=True
        )
    except Exception:
        pass


class SpeechBubble(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_app_paintable(True)
        self.set_keep_above(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.label = Gtk.Label()
        self.label.set_line_wrap(True)
        self.label.set_max_width_chars(35)
        self.label.set_justify(Gtk.Justification.CENTER)
        self.label.set_markup('<span foreground="#4A3728" font_size="small">Hello!</span>')
        self.label.set_margin_start(10)
        self.label.set_margin_end(10)
        self.label.set_margin_top(6)
        self.label.set_margin_bottom(6)
        self.add(self.label)
        self.resize(200, 50)
        self.show_all()
        self.hide()
        self._timeout = None

    def show_text(self, text, duration=5000):
        if self._timeout:
            GLib.source_remove(self._timeout)
        escaped = GLib.markup_escape_text(text)
        self.label.set_markup(f'<span foreground="#4A3728" font_size="small">{escaped}</span>')
        self.show_all()
        self._timeout = GLib.timeout_add(duration, self._hide)

    def _hide(self):
        self.hide()
        self._timeout = None
        return False


class ChatWindow(Gtk.Window):
    def __init__(self, on_send):
        super().__init__(title="Neko Chat")
        self.set_default_size(CHAT_WIDTH, CHAT_HEIGHT)
        self.set_decorated(True)
        self.set_keep_above(True)
        self.set_resizable(False)
        self.on_send = on_send
        self.get_style_context().add_class('chat-window')

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Gtk.Label()
        header.set_markup('<span foreground="white" font_weight="bold">  Neko</span>')
        header.set_xalign(0)
        header.get_style_context().add_class('chat-header')
        header.set_size_request(-1, 36)
        vbox.pack_start(header, False, False, 0)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.msg_box.set_margin_start(8)
        self.msg_box.set_margin_end(8)
        self.msg_box.set_margin_top(8)
        self.msg_box.set_margin_bottom(8)
        self.scroll.add(self.msg_box)

        viewport = self.scroll.get_child()
        if viewport:
            viewport.set_shadow_type(Gtk.ShadowType.NONE)
        vbox.pack_start(self.scroll, True, True, 0)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_start(8)
        hbox.set_margin_end(8)
        hbox.set_margin_bottom(8)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Say something...")
        self.entry.set_hexpand(True)
        self.entry.connect("activate", self._on_enter)
        hbox.pack_start(self.entry, True, True, 0)

        send_btn = Gtk.Button(label=">")
        send_btn.set_size_request(36, 36)
        send_btn.connect("clicked", lambda _: self._on_enter(None))
        hbox.pack_start(send_btn, False, False, 0)

        screen_btn = Gtk.Button(label="\U0001F4F7")
        screen_btn.set_size_request(36, 36)
        screen_btn.connect("clicked", lambda _: self.on_send("__screen__"))
        hbox.pack_start(screen_btn, False, False, 0)

        vbox.pack_start(hbox, False, False, 0)
        self.add(vbox)
        self.add_message("Click me to chat! Use camera to show screen.", "system")

    def _on_enter(self, widget):
        text = self.entry.get_text().strip()
        if not text:
            return
        self.entry.set_text("")
        self.add_message(text, "user")
        self.on_send(text)

    def add_message(self, text, msg_type="neko"):
        label = Gtk.Label(label=text)
        label.set_line_wrap(True)
        label.set_max_width_chars(38)
        if msg_type == "user":
            label.set_markup(f'<span foreground="white">{GLib.markup_escape_text(text)}</span>')
            label.get_style_context().add_class('msg-user')
            label.set_xalign(1)
        elif msg_type == "system":
            label.set_markup(f'<span foreground="#aaa" font_size="small">{GLib.markup_escape_text(text)}</span>')
            label.get_style_context().add_class('msg-system')
            label.set_xalign(0.5)
        elif msg_type == "screen":
            label.set_markup(f'<span foreground="#ddd">{GLib.markup_escape_text(text)}</span>')
            label.get_style_context().add_class('msg-screen')
            label.set_xalign(0)
        else:
            label.set_markup(f'<span foreground="#eee">{GLib.markup_escape_text(text)}</span>')
            label.get_style_context().add_class('msg-neko')
            label.set_xalign(0)
        self.msg_box.pack_start(label, False, False, 0)
        self.msg_box.show_all()
        # Scroll to bottom
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper())


class NekoAssistant(Gtk.Window):
    def __init__(self):
        super().__init__(title="Neko")
        self.set_default_size(WINDOW_SIZE, WINDOW_SIZE)
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_skip_taskbar_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # Mouse events
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )

        # Image
        img_path = self._find_image()
        self.image_pixbuf = make_circle_image(img_path, WINDOW_SIZE - 10)

        # Brain
        self.brain = NekoBrain()

        # Bubble + Chat
        self.bubble = SpeechBubble()
        self.chat = ChatWindow(on_send=self._handle_chat)
        self.chat.connect("delete-event", lambda *_: (self.chat.hide(), True))

        # Drag
        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._win_start_x = 0
        self._win_start_y = 0
        self._moved = False

        # Signals
        self.connect("destroy", Gtk.main_quit)
        self.connect("button-press-event", self._on_press)
        self.connect("button-release-event", self._on_release)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("draw", self._on_draw)
        self.connect("realize", self._on_realize)

        self.show_all()

        # Position
        self._position_window()

        # Timers
        self._last_interaction = time.time()
        GLib.timeout_add(WATER_INTERVAL * 1000, self._water_reminder)
        GLib.timeout_add(IDLE_INTERVAL * 1000, self._idle_check)
        GLib.timeout_add(100, self._reposition_bubble)

        GLib.timeout_add(800, self._welcome)

    def _on_realize(self, widget):
        """After window realized, force always-on-top via X11."""
        force_above_x11(self)
        # Re-apply every 2 seconds for the first 10 seconds
        for delay in [500, 1500, 3000, 5000, 10000]:
            GLib.timeout_add(delay, lambda d=delay: force_above_x11(self))

    def _find_image(self):
        if os.path.isdir(IMG_DIR):
            for f in os.listdir(IMG_DIR):
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    return os.path.join(IMG_DIR, f)
        return ""

    def _position_window(self):
        screen = self.get_screen()
        display = screen.get_display()
        monitor = display.get_primary_monitor()
        if monitor:
            geo = monitor.get_geometry()
        else:
            geo = Gdk.Rectangle()
            geo.x, geo.y, geo.width, geo.height = 0, 0, screen.get_width(), screen.get_height()
        x = geo.x + geo.width - WINDOW_SIZE - 30
        y = geo.y + geo.height - WINDOW_SIZE - 60
        self.move(x, y)

    def _reposition_bubble(self):
        wx, wy = self.get_position()
        self.bubble.move(wx + 5, wy - 60)
        return True

    def _on_draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        img_w = self.image_pixbuf.get_width()
        img_h = self.image_pixbuf.get_height()
        x = (WINDOW_SIZE - img_w) // 2
        y = (WINDOW_SIZE - img_h) // 2
        Gdk.cairo_set_source_pixbuf(cr, self.image_pixbuf, x, y)
        cr.paint()

    # --- DRAG ---
    def _on_press(self, widget, event):
        if event.button != 1:
            return False
        self._dragging = True
        self._moved = False
        self._drag_start_x = int(event.x_root)
        self._drag_start_y = int(event.y_root)
        self._win_start_x, self._win_start_y = self.get_position()
        self._last_interaction = time.time()
        return True

    def _on_motion(self, widget, event):
        if not self._dragging:
            return False
        dx = int(event.x_root) - self._drag_start_x
        dy = int(event.y_root) - self._drag_start_y
        if abs(dx) > 2 or abs(dy) > 2:
            self._moved = True
        if self._moved:
            self.move(self._win_start_x + dx, self._win_start_y + dy)
        return True

    def _on_release(self, widget, event):
        if event.button != 1:
            return False
        self._dragging = False
        if not self._moved:
            self._toggle_chat()
        return True

    # --- CHAT ---
    def _toggle_chat(self):
        if self.chat.get_visible():
            self.chat.hide()
        else:
            wx, wy = self.get_position()
            self.chat.move(wx - CHAT_WIDTH - 10, wy)
            self.chat.show_all()
            self.chat.entry.grab_focus()
            self.chat.present()

    def _handle_chat(self, text):
        if text == "__screen__":
            self._capture_screen()
            return
        self._last_interaction = time.time()
        GLib.timeout_add(random.randint(400, 900), lambda: self._respond(text))

    def _respond(self, text):
        # Show thinking indicator
        self.bubble.show_text("hmm...", 3000)

        def do_think():
            response = self.brain.think(text)
            GLib.idle_add(self._show_response, response)

        threading.Thread(target=do_think, daemon=True).start()
        return False

    def _show_response(self, response):
        self.bubble.show_text(response, max(4000, len(response) * 80))
        self.chat.add_message(response, "neko")
        return False

    # --- SCREEN CAPTURE ---
    def _capture_screen(self):
        self.chat.add_message("Capturing your screen...", "system")
        self.bubble.show_text("Let me look~", 3000)

        def do_capture():
            try:
                import mss
                with mss.mss() as sct:
                    monitor = sct.monitors[1]
                    screenshot = sct.grab(monitor)
                    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_capture.png")
                    mss.tools.to_png(screenshot.rgb, screenshot.size, path)
                GLib.idle_add(self._show_capture_result, path)
            except Exception as e:
                GLib.idle_add(self.chat.add_message, f"Capture failed: {e}", "system")
        threading.Thread(target=do_capture, daemon=True).start()

    def _show_capture_result(self, path):
        msgs = ["I can see your screen! Looks interesting~", "Nice setup you got there~", "I see your screen! What are you working on?"]
        msg = random.choice(msgs)
        self.bubble.show_text(msg, 5000)
        self.chat.add_message(f"[Screen captured]\n{msg}", "screen")
        return False

    # --- REMINDERS ---
    def _water_reminder(self):
        count = self.brain.water_count_today
        if count > 0:
            msg = f"Time for water~! You've had {count} today, keep going!"
        else:
            msg = random.choice(WATER_MESSAGES)
        self.bubble.show_text(msg, 7000)
        self._last_interaction = time.time()
        return True

    def _idle_check(self):
        if time.time() - self._last_interaction > IDLE_INTERVAL:
            msg = random.choice(IDLE_MESSAGES)
            self.bubble.show_text(msg, 5000)
            self._last_interaction = time.time()
        return True

    def _welcome(self):
        if self.brain.user_name:
            greeting = f"Welcome back, {self.brain.user_name}~!"
        else:
            greeting = random.choice([
                'Hi there! I\'m Neko~',
                'Hiii! What\'s up?',
                'Nyaa~ How are you?',
                'Hey! Nice to see you~',
            ])
        self.bubble.show_text(greeting, 5000)
        return False


def apply_css():
    css = b"""
    .chat-window { background-color: #111; }
    .bubble { background: rgba(255, 255, 255, 0.95); border: 2px solid #FFB3C1; border-radius: 14px; }
    .chat-header { background: linear-gradient(135deg, #FF8FA0, #FF6B81); color: white; font-weight: bold; }
    .msg-user { background: #FF8FA0; border-radius: 12px; padding: 6px 10px; margin: 2px 4px; }
    .msg-neko { background: #2a2a2a; border: 1px solid #444; color: #eee; border-radius: 12px; padding: 6px 10px; margin: 2px 4px; }
    .msg-system { background: rgba(100, 100, 100, 0.4); color: #aaa; border-radius: 8px; padding: 4px 8px; margin: 2px 4px; }
    .msg-screen { background: #1a1a2e; border: 1px solid #444; color: #ddd; border-radius: 12px; padding: 6px 10px; margin: 2px 4px; }
    entry { background: #222; color: #eee; border-color: #555; border-radius: 16px; padding: 6px 10px; }
    entry:focus { border-color: #FF8FA0; }
    button { background: #FF8FA0; color: white; border-radius: 16px; }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


if __name__ == "__main__":
    apply_css()
    app = NekoAssistant()
    Gtk.main()
