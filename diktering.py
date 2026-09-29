#!/usr/bin/env python3
"""
Push-to-talk diktering för macOS.

Håll ned hotkey         -> spelar in på standardspråket
Håll ned Shift + hotkey -> spelar in på det andra språket
Släpp                   -> texten skrivs in där markören står

Modell, dikteringsspråk, appens språk och avslut finns i menyraden. Valen
sparas till settings.json. En animerad ljudvåg följer muspekaren medan du
spelar in och medan texten transkriberas.

Beroenden:
    pip install faster-whisper sounddevice pynput numpy pyobjc-framework-Cocoa
"""

import json
import math
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import objc
import sounddevice as sd
from faster_whisper import WhisperModel
from pynput import keyboard

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSCompositingOperationCopy,
    NSEvent,
    NSMenu,
    NSMenuItem,
    NSPanel,
    NSPopUpMenuWindowLevel,
    NSRectFillUsingOperation,
    NSScreen,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import (
    NSInsetRect,
    NSMakeRect,
    NSObject,
    NSRunLoop,
    NSRunLoopCommonModes,
    NSTimer,
)
from PyObjCTools import AppHelper

# ---------------------------------------------------------------- konfiguration

# Höger Cmd. Byt till keyboard.Key.f18 om du mappar om Caps Lock.
HOTKEY = keyboard.Key.cmd_r

SAMPLE_RATE = 16000
BLOCK_SIZE = 800           # 50 ms per block, ger ljudvågen jämn uppdatering
PREROLL_SECONDS = 0.4      # ljud som sparas *innan* du hinner trycka
MIN_SPEECH_SECONDS = 0.4   # kortare än så = ignoreras
MAX_RECORD_SECONDS = 180   # skydd mot att en tangent fastnar

COMPUTE_TYPE = "int8"
CACHE_DIR = "cache"
SETTINGS_FILE = Path(__file__).resolve().with_name("settings.json")

# Modellstorlekar, minst till störst. Svensk modell från Kungliga biblioteket,
# engelsk från OpenAI. Etiketterna i menyn ligger i STRINGS nedan.
MODEL_SIZES = ["tiny", "base", "small", "medium", "large"]
MODELS = {
    "tiny":   ("KBLab/kb-whisper-tiny",   "tiny.en"),
    "base":   ("KBLab/kb-whisper-base",   "base.en"),
    "small":  ("KBLab/kb-whisper-small",  "small.en"),
    "medium": ("KBLab/kb-whisper-medium", "medium.en"),
    "large":  ("KBLab/kb-whisper-large",  "large-v3"),
}
DEFAULT_SIZE = "small"

# Menyradens ikoner
ICON_IDLE = "\U0001f3a4"       # 🎤  redo
ICON_RECORDING = "\U0001f534"  # 🔴  spelar in
ICON_WORKING = "⏳"        # ⏳  transkriberar
ICON_LOADING = "⬇️"  # ⬇️  laddar modell

# Ljudvågen vid muspekaren
WAVE_ENABLED = True
WAVE_BARS = 9
WAVE_BAR_WIDTH = 3.0
WAVE_BAR_GAP = 2.5
WAVE_PADDING = 11.0
WAVE_HEIGHT = 30.0
WAVE_WIDTH = 2 * WAVE_PADDING + WAVE_BARS * WAVE_BAR_WIDTH + (WAVE_BARS - 1) * WAVE_BAR_GAP
WAVE_CURSOR_OFFSET = 18.0      # avstånd från pekarens spets
WAVE_FPS = 60
# Staplarnas färg, från vänster till höger. Rött när du pratar, blålila när
# modellen arbetar.
WAVE_COLORS = {
    "recording": ((1.00, 0.33, 0.40), (1.00, 0.62, 0.30)),
    "working":   ((0.33, 0.62, 1.00), (0.72, 0.45, 1.00)),
}

# Whisper hittar på undertextkrediter när ljudet är tyst. Filtrera bort dem.
HALLUCINATIONS = {
    "tack för att du tittade",
    "tack för att ni har tittat",
    "tack för att du tittade på videon",
    "undertexter av",
    "undertextning av",
    "textning av",
    "svensktextning",
    "thank you for watching",
    "thanks for watching",
    "subtitles by",
    "you",
    ".",
}

# ---------------------------------------------------------------- texter

# Allt som visas för användaren, på appens två språk.
STRINGS = {
    "sv": {
        "menu_model": "Modell",
        "menu_dictation": "Dikteringsspråk (standard)",
        "menu_shift_hint": "Håll Shift för det andra språket",
        "menu_ui": "Appens språk",
        "menu_quit": "Avsluta",
        "lang_sv": "Svenska",
        "lang_en": "Engelska",
        "model_tiny": "Tiny — snabbast, lägst noggrannhet  (~80 MB)",
        "model_base": "Base — snabb  (~150 MB)",
        "model_small": "Small — bra balans  (~500 MB)",
        "model_medium": "Medium — långsammare, noggrannare  (~1,5 GB)",
        "model_large": "Large — långsammast, bäst  (~3 GB)",
        "log_model": "🔄 Modell: {size}",
        "log_dictation_sv": "🇸🇪 Standardspråk: svenska",
        "log_dictation_en": "🇬🇧 Standardspråk: engelska",
        "log_ui": "🌐 Appens språk: svenska",
        "log_save_failed": "⚠️  Kunde inte spara inställningar: {exc}",
        "log_loading": "⏬ Laddar {size} för {language} ({name}) ...",
        "log_ready_model": "✅ {size} redo",
        "log_load_failed": "❌ Kunde inte ladda {size}: {exc}",
        "log_no_speech": "⚪️ [{language}] inget tal hittades",
        "log_failed": "❌ Fel vid transkribering: {exc}",
        "log_recording": "🔴 Spelar in ({language}) ...",
        "log_transcribing": "⏳ Transkriberar ...",
        "log_mic_failed": "❌ Kunde inte öppna mikrofonen: {exc}",
        "log_mic_hint": "   Kolla Systeminställningar > Sekretess och säkerhet > Mikrofon.",
        "log_ready": (
            "\n🎙  Redo.\n"
            "   Modell: {size}, standardspråk: {language}\n"
            "   Håll höger Cmd          -> standardspråket\n"
            "   Håll Shift + höger Cmd  -> det andra språket\n"
            "   Modell och språk byts i menyraden.\n"
        ),
    },
    "en": {
        "menu_model": "Model",
        "menu_dictation": "Dictation language (default)",
        "menu_shift_hint": "Hold Shift for the other language",
        "menu_ui": "App language",
        "menu_quit": "Quit",
        "lang_sv": "Swedish",
        "lang_en": "English",
        "model_tiny": "Tiny — fastest, lowest accuracy  (~80 MB)",
        "model_base": "Base — fast  (~150 MB)",
        "model_small": "Small — good balance  (~500 MB)",
        "model_medium": "Medium — slower, more accurate  (~1.5 GB)",
        "model_large": "Large — slowest, best  (~3 GB)",
        "log_model": "🔄 Model: {size}",
        "log_dictation_sv": "🇸🇪 Default language: Swedish",
        "log_dictation_en": "🇬🇧 Default language: English",
        "log_ui": "🌐 App language: English",
        "log_save_failed": "⚠️  Could not save settings: {exc}",
        "log_loading": "⏬ Loading {size} for {language} ({name}) ...",
        "log_ready_model": "✅ {size} ready",
        "log_load_failed": "❌ Could not load {size}: {exc}",
        "log_no_speech": "⚪️ [{language}] no speech detected",
        "log_failed": "❌ Transcription error: {exc}",
        "log_recording": "🔴 Recording ({language}) ...",
        "log_transcribing": "⏳ Transcribing ...",
        "log_mic_failed": "❌ Could not open the microphone: {exc}",
        "log_mic_hint": "   Check System Settings > Privacy & Security > Microphone.",
        "log_ready": (
            "\n🎙  Ready.\n"
            "   Model: {size}, default language: {language}\n"
            "   Hold right Cmd          -> default language\n"
            "   Hold Shift + right Cmd  -> the other language\n"
            "   Change model and languages in the menu bar.\n"
        ),
    },
}

# Valen av appens språk står alltid på sitt eget språk, så att den som hamnat
# på fel språk ändå hittar tillbaka.
UI_LANGUAGE_NAMES = {"sv": "Svenska", "en": "English"}

# Aktuella val. Ändras via menyn och sparas till disk.
default_language = "sv"   # språket du dikterar på
ui_language = "sv"        # språket appen visar sina texter på
model_size = DEFAULT_SIZE


def t(key, **values):
    """Slår upp en text på appens språk och fyller i eventuella {fält}."""
    return STRINGS[ui_language][key].format(**values)


def load_settings():
    global default_language, ui_language, model_size
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        if data.get("language") in ("sv", "en"):
            default_language = data["language"]
        if data.get("ui_language") in STRINGS:
            ui_language = data["ui_language"]
        if data.get("model") in MODELS:
            model_size = data["model"]
    except Exception:
        pass   # ingen fil än, eller trasig - kör vidare med standardvärden


def save_settings():
    try:
        SETTINGS_FILE.write_text(
            json.dumps(
                {
                    "language": default_language,
                    "ui_language": ui_language,
                    "model": model_size,
                },
                indent=2,
            )
        )
    except Exception as exc:
        print(t("log_save_failed", exc=exc), flush=True)


def idle_title():
    return ICON_IDLE if default_language == "sv" else f"{ICON_IDLE} EN"


def recording_title(language):
    return ICON_RECORDING if language == "sv" else f"{ICON_RECORDING} EN"


# ---------------------------------------------------------------- meny


class MenuHandler(NSObject):
    """Tar emot menyklick. Metodnamn med _ blir Objective-C-selektorer med :"""

    def chooseModel_(self, sender):
        size = sender.representedObject()
        if size == model_size:
            return
        set_model_size(size)
        self.icon.refresh()
        print(t("log_model", size=size), flush=True)
        threading.Thread(target=preload, args=(size,), daemon=True).start()

    def chooseSwedish_(self, sender):
        set_language("sv")
        self.icon.refresh()
        print(t("log_dictation_sv"), flush=True)

    def chooseEnglish_(self, sender):
        set_language("en")
        self.icon.refresh()
        print(t("log_dictation_en"), flush=True)

    def chooseUiLanguage_(self, sender):
        language = sender.representedObject()
        if language == ui_language:
            return
        set_ui_language(language)
        self.icon.relabel()
        self.icon.refresh()
        print(t("log_ui"), flush=True)

    def quitApp_(self, sender):
        NSApplication.sharedApplication().terminate_(None)


class StatusIcon:
    """Ikon i menyraden. Måste skapas efter NSApplication.sharedApplication()."""

    def __init__(self, wave):
        self.wave = wave
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.handler = MenuHandler.alloc().init()
        self.handler.icon = self

        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)

        # Texterna sätts i relabel(), så att de kan bytas när appens språk byts.
        self.model_header = self._header()
        menu.addItem_(self.model_header)
        self.model_items = {}
        for size in MODEL_SIZES:
            entry = self._entry("chooseModel:")
            entry.setRepresentedObject_(size)   # vilken storlek klicket gäller
            menu.addItem_(entry)
            self.model_items[size] = entry

        menu.addItem_(NSMenuItem.separatorItem())

        self.dictation_header = self._header()
        menu.addItem_(self.dictation_header)
        self.sv_item = self._entry("chooseSwedish:")
        self.en_item = self._entry("chooseEnglish:")
        menu.addItem_(self.sv_item)
        menu.addItem_(self.en_item)

        menu.addItem_(NSMenuItem.separatorItem())
        self.shift_hint = self._header()
        menu.addItem_(self.shift_hint)
        menu.addItem_(NSMenuItem.separatorItem())

        self.ui_header = self._header()
        menu.addItem_(self.ui_header)
        self.ui_items = {}
        for language, name in UI_LANGUAGE_NAMES.items():
            entry = self._entry("chooseUiLanguage:")
            entry.setTitle_(name)
            entry.setRepresentedObject_(language)
            menu.addItem_(entry)
            self.ui_items[language] = entry

        menu.addItem_(NSMenuItem.separatorItem())

        self.quit_item = self._entry("quitApp:", "q")
        menu.addItem_(self.quit_item)

        self.item.setMenu_(menu)
        self.relabel()
        self.refresh()

    @staticmethod
    def _header():
        entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, "")
        entry.setEnabled_(False)
        return entry

    def _entry(self, action, key=""):
        entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", action, key)
        entry.setTarget_(self.handler)
        return entry

    def relabel(self):
        """Sätter alla menytexter på appens aktuella språk."""
        self.model_header.setTitle_(t("menu_model"))
        for size, entry in self.model_items.items():
            entry.setTitle_(t(f"model_{size}"))
        self.dictation_header.setTitle_(t("menu_dictation"))
        self.sv_item.setTitle_(t("lang_sv"))
        self.en_item.setTitle_(t("lang_en"))
        self.shift_hint.setTitle_(t("menu_shift_hint"))
        self.ui_header.setTitle_(t("menu_ui"))
        self.quit_item.setTitle_(t("menu_quit"))

    def set(self, text):
        self.item.button().setTitle_(text)

    def refresh(self):
        """Uppdaterar bockar, ikon och ljudvåg efter läget just nu."""
        for size, entry in self.model_items.items():
            entry.setState_(1 if size == model_size else 0)
        self.sv_item.setState_(1 if default_language == "sv" else 0)
        self.en_item.setState_(1 if default_language == "en" else 0)
        for language, entry in self.ui_items.items():
            entry.setState_(1 if language == ui_language else 0)

        if recorder.recording:
            self.set(recording_title(recorder.language))
            self.wave.show("recording")
        elif jobs.unfinished_tasks:
            self.set(ICON_WORKING)
            self.wave.show("working")
        else:
            self.set(idle_title())
            self.wave.hide()


status = None


def status_set(text):
    """Får anropas från vilken tråd som helst; UI måste köra på huvudtråden."""
    if status is not None:
        AppHelper.callAfter(status.set, text)


def status_refresh():
    if status is not None:
        AppHelper.callAfter(status.refresh)


# ---------------------------------------------------------------- ljudvåg vid pekaren


def level_from_rms(rms):
    """Gör om mikrofonens RMS till 0..1 på en decibelskala, som örat hör."""
    db = 20 * math.log10(rms + 1e-9)
    return min(1.0, max(0.0, (db + 55) / 40))   # -55 dB = tyst, -15 dB = högt


def _mix(a, b, amount):
    return tuple(x + (y - x) * amount for x, y in zip(a, b))


class WaveView(NSView):
    """Ritar en mörk pille med staplar. Höjderna sätts utifrån, 0..1 per stapel."""

    def initWithFrame_(self, frame):
        self = objc.super(WaveView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.mode = "recording"
        self.heights = [0.0] * WAVE_BARS
        return self

    def isOpaque(self):
        return False

    def drawRect_(self, rect):
        bounds = self.bounds()
        NSColor.clearColor().set()
        NSRectFillUsingOperation(bounds, NSCompositingOperationCopy)

        radius = WAVE_HEIGHT / 2
        pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSInsetRect(bounds, 0.5, 0.5), radius - 0.5, radius - 0.5
        )
        NSColor.colorWithCalibratedWhite_alpha_(0.07, 0.85).setFill()
        pill.fill()
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.14).setStroke()
        pill.setLineWidth_(1.0)
        pill.stroke()

        left, right = WAVE_COLORS[self.mode]
        max_height = WAVE_HEIGHT - 12
        for i, height in enumerate(self.heights):
            bar_height = max(WAVE_BAR_WIDTH, height * max_height)
            x = WAVE_PADDING + i * (WAVE_BAR_WIDTH + WAVE_BAR_GAP)
            y = (WAVE_HEIGHT - bar_height) / 2
            red, green, blue = _mix(left, right, i / (WAVE_BARS - 1))
            NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, 1.0).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, WAVE_BAR_WIDTH, bar_height),
                WAVE_BAR_WIDTH / 2,
                WAVE_BAR_WIDTH / 2,
            ).fill()


class WaveTicker(NSObject):
    """Mål för NSTimer; skickar vidare till CursorWave.tick."""

    def tick_(self, timer):
        self.wave.tick()


class CursorWave:
    """
    Genomskinligt fönster som följer muspekaren. Det tar aldrig fokus och
    släpper igenom alla klick, så texten skrivs in i appen under som vanligt.
    Timern går bara medan vågen syns. Måste användas på huvudtråden.
    """

    def __init__(self):
        frame = NSMakeRect(0, 0, WAVE_WIDTH, WAVE_HEIGHT)
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setLevel_(NSPopUpMenuWindowLevel)   # ovanför vanliga fönster
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        panel.setAlphaValue_(0.0)
        self.view = WaveView.alloc().initWithFrame_(frame)
        panel.setContentView_(self.view)
        self.panel = panel

        self.ticker = WaveTicker.alloc().init()
        self.ticker.wave = self
        self.timer = None
        self.visible = False   # dit vi är på väg; tick() tonar in eller ut
        self.phase = 0.0
        self.level = 0.0

    def show(self, mode):
        if not WAVE_ENABLED:
            return
        self.view.mode = mode
        self.visible = True
        if self.timer is None:
            self.heights_at_rest()
            self.follow()
            self.view.display()
            self.panel.orderFrontRegardless()
            self.panel.invalidateShadow()
            self.timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / WAVE_FPS, self.ticker, "tick:", None, True
            )
            # Common modes = animationen fortsätter även när menyn är öppen.
            NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, NSRunLoopCommonModes)

    def hide(self):
        self.visible = False

    def heights_at_rest(self):
        self.level = 0.0
        self.view.heights = [0.12] * WAVE_BARS

    def tick(self):
        step = 1.0 / WAVE_FPS
        self.phase += step

        alpha = self.panel.alphaValue()
        if self.visible:
            alpha = min(1.0, alpha + step / 0.15)
        else:
            alpha -= step / 0.2
            if alpha <= 0:
                self.panel.setAlphaValue_(0.0)
                self.panel.orderOut_(None)
                self.timer.invalidate()
                self.timer = None
                return
        self.panel.setAlphaValue_(alpha)

        self.follow()
        self.animate()
        self.view.setNeedsDisplay_(True)

    def animate(self):
        # Snabb uppgång, långsam avklingning - som en VU-mätare.
        target = level_from_rms(recorder.level)
        speed = 0.45 if target > self.level else 0.12
        self.level += (target - self.level) * speed

        center = (WAVE_BARS - 1) / 2
        heights = self.view.heights
        for i in range(WAVE_BARS):
            edge = abs(i - center) / center   # 0 i mitten, 1 ytterst
            if self.view.mode == "recording":
                # Staplarna följer rösten, högst i mitten, var och en i egen takt.
                breathing = 0.06 * (0.5 + 0.5 * math.sin(self.phase * 3.0 + i * 0.6))
                wobble = 0.6 + 0.4 * math.sin(self.phase * (7.0 + i * 1.3) + i * 1.7)
                envelope = 1.0 - 0.55 * edge * edge
                goal = 0.12 + breathing + 0.82 * self.level * envelope * wobble
            else:
                # En våg som rullar från vänster till höger medan modellen arbetar.
                wave = 0.5 + 0.5 * math.sin(self.phase * 6.0 - i * 0.75)
                goal = (0.18 + 0.62 * wave) * (1.0 - 0.35 * edge)
            heights[i] += (goal - heights[i]) * 0.35   # mjuk övergång mellan lägena

    def follow(self):
        """Placerar vågen snett nedanför pekaren, men alltid inom skärmen."""
        mouse = NSEvent.mouseLocation()
        area = NSScreen.mainScreen().visibleFrame()
        for screen in NSScreen.screens():
            f = screen.frame()
            if (f.origin.x <= mouse.x <= f.origin.x + f.size.width
                    and f.origin.y <= mouse.y <= f.origin.y + f.size.height):
                area = screen.visibleFrame()
                break

        x = mouse.x + WAVE_CURSOR_OFFSET
        y = mouse.y - WAVE_CURSOR_OFFSET - WAVE_HEIGHT
        if x + WAVE_WIDTH > area.origin.x + area.size.width:
            x = mouse.x - WAVE_CURSOR_OFFSET - WAVE_WIDTH
        if y < area.origin.y:
            y = mouse.y + WAVE_CURSOR_OFFSET
        self.panel.setFrameOrigin_((x, y))


# ---------------------------------------------------------------- ljudinspelning


class Recorder:
    """Håller strömmen öppen hela tiden och buffrar bara när vi spelar in."""

    def __init__(self):
        self.lock = threading.Lock()
        self.recording = False
        self.language = "sv"
        self.level = 0.0     # senaste blockets RMS, läses av ljudvågen
        self.frames = []
        preroll_blocks = max(1, int(PREROLL_SECONDS * SAMPLE_RATE / BLOCK_SIZE))
        self.preroll = deque(maxlen=preroll_blocks)
        self.max_blocks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / BLOCK_SIZE)

    def callback(self, indata, frames, time_info, status_flags):
        block = indata[:, 0].copy()
        self.level = float(np.sqrt(np.mean(block * block)))
        with self.lock:
            if self.recording:
                if len(self.frames) < self.max_blocks:
                    self.frames.append(block)
            else:
                self.preroll.append(block)

    def start(self, language):
        with self.lock:
            if self.recording:
                return
            self.language = language
            self.frames = list(self.preroll)   # ta med pre-roll
            self.recording = True

    def stop(self):
        with self.lock:
            if not self.recording:
                return None, None
            self.recording = False
            audio = (
                np.concatenate(self.frames)
                if self.frames
                else np.zeros(0, dtype=np.float32)
            )
            self.frames = []
            self.preroll.clear()
            return audio, self.language


recorder = Recorder()

# ---------------------------------------------------------------- transkribering

_models = {}                 # nyckel: (storlek, språk)
_model_lock = threading.Lock()


def set_language(language):
    global default_language
    default_language = language
    save_settings()


def set_ui_language(language):
    global ui_language
    ui_language = language
    save_settings()


def set_model_size(size):
    """Byter modell och kastar de gamla, så att RAM inte växer vid varje byte."""
    global model_size
    model_size = size
    with _model_lock:
        for key in [k for k in _models if k[0] != size]:
            del _models[key]
    save_settings()


def get_model(size, language):
    key = (size, language)
    with _model_lock:
        if key not in _models:
            name = MODELS[size][0 if language == "sv" else 1]
            print(t("log_loading", size=size, language=language, name=name), flush=True)
            _models[key] = WhisperModel(
                name,
                device="cpu",              # CTranslate2 har ingen Metal-backend
                compute_type=COMPUTE_TYPE,
                download_root=CACHE_DIR,
            )
        return _models[key]


def clean(text):
    stripped = text.strip()
    if not stripped:
        return ""
    key = stripped.lower().strip(" .!?,")
    if key in HALLUCINATIONS:
        return ""
    return stripped


def transcribe(audio, language, size):
    if len(audio) < MIN_SPEECH_SECONDS * SAMPLE_RATE:
        return ""
    model = get_model(size, language)
    segments, _info = model.transcribe(
        audio,
        language=language,
        beam_size=1,                       # girigt = snabbast, räcker för diktering
        vad_filter=True,
        condition_on_previous_text=False,  # minskar hallucinationer
        no_speech_threshold=0.6,
    )
    parts = []
    for segment in segments:               # generatorn måste konsumeras här
        if segment.no_speech_prob > 0.7:
            continue
        piece = clean(segment.text)
        if piece:
            parts.append(piece)
    return " ".join(parts)


def preload(size):
    """Laddar ned och värmer upp en modell i bakgrunden efter ett menyval."""
    language = default_language
    try:
        status_set(ICON_LOADING)
        get_model(size, language)
        transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language, size)
        print(t("log_ready_model", size=size), flush=True)
    except Exception as exc:
        print(t("log_load_failed", size=size, exc=exc), flush=True)
    finally:
        status_refresh()


# ---------------------------------------------------------------- textinjektion

_KEYSTROKE = (
    'on run argv\n'
    'tell application "System Events" to keystroke (item 1 of argv)\n'
    'end run'
)


def paste(text):
    """Skriver texten direkt där markören står, utan att röra urklippet."""
    subprocess.run(["osascript", "-e", _KEYSTROKE, text], check=True)


# ---------------------------------------------------------------- arbetartråd

jobs = queue.Queue()


def worker():
    while True:
        audio, language, size = jobs.get()
        try:
            started = time.time()
            text = transcribe(audio, language, size)
            elapsed = time.time() - started
            if text:
                paste(text)
                print(f"✅ [{language} {size} {elapsed:.2f}s] {text}", flush=True)
            else:
                print(t("log_no_speech", language=language), flush=True)
        except Exception as exc:
            print(t("log_failed", exc=exc), flush=True)
        finally:
            # Först när jobbet är avbockat kan refresh() se att kön är tom
            # och släcka ljudvågen.
            jobs.task_done()
            status_refresh()


# ---------------------------------------------------------------- hotkey

SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
shift_down = False


def on_press(key):
    global shift_down
    if key in SHIFT_KEYS:
        shift_down = True
    elif key == HOTKEY and not recorder.recording:
        other = "en" if default_language == "sv" else "sv"
        language = other if shift_down else default_language
        recorder.start(language)
        status_refresh()
        print(t("log_recording", language=language), flush=True)


def on_release(key):
    global shift_down
    if key in SHIFT_KEYS:
        shift_down = False
    elif key == HOTKEY and recorder.recording:
        audio, language = recorder.stop()
        if audio is not None:
            # Aldrig transkribera här - den här callbacken kör på macOS event tap
            # och blockerar du den får du inputlagg i hela systemet.
            # Storleken låses vid inspelningens slut, så att ett menyval mitt i
            # en pågående transkribering inte byter modell under fötterna.
            jobs.put((audio, language, model_size))
            status_refresh()
            print(t("log_transcribing"), flush=True)


# ---------------------------------------------------------------- main


def main():
    global status

    load_settings()
    threading.Thread(target=worker, daemon=True).start()

    # Värm upp vald modell så första riktiga dikteringen inte blir seg.
    get_model(model_size, default_language)
    transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), default_language, model_size)

    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=recorder.callback,
        )
        stream.start()
    except Exception as exc:
        print(t("log_mic_failed", exc=exc))
        print(t("log_mic_hint"))
        sys.exit(1)

    # Accessory = ingen ikon i Docken och appen tar aldrig fokus.
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    status = StatusIcon(CursorWave())

    # Listener.start() kör i egen tråd, så huvudtråden är fri åt Cocoa.
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    print(t("log_ready", size=model_size, language=default_language))

    try:
        AppHelper.runEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        stream.stop()
        stream.close()


if __name__ == "__main__":
    main()
