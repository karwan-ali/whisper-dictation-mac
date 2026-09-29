# Whisper Dictation for Mac

Push-to-talk speech-to-text for macOS. Hold a key, speak, and release. The text is typed wherever your cursor is, in any app.

Everything runs locally on your Mac. No audio leaves the machine, and there are no API keys or per-minute costs.

- **Swedish by default**, English while holding Shift (or the other way around)
- **KB-Whisper** from the National Library of Sweden, trained on more than 50,000 hours of Swedish speech
- **Menu bar icon** that shows when the tool is recording
- **Animated sound wave next to the mouse pointer** while you speak and while the text is transcribed
- **Interface in English or Swedish**, selectable from the menu
- Starts from a double-clickable file

---

## Requirements

| | |
|---|---|
| macOS | 12 Monterey or later |
| Processor | Apple Silicon or Intel |
| Disk space | ~1 GB (models are downloaded automatically) |
| RAM | 4 GB free is plenty |
| Homebrew | [brew.sh](https://brew.sh), only needed to install Python |

---

## Installation

### 1. Install Python

```bash
brew install python@3.12
```

### 2. Clone the project and create the environment

```bash
git clone https://github.com/karwan-ali/whisper-dictation-mac.git ~/whisper-dictation-mac
cd ~/whisper-dictation-mac
python3.12 -m venv .venv
source .venv/bin/activate
pip install faster-whisper sounddevice pynput numpy pyobjc-framework-Cocoa
```

A virtual environment (`venv`) keeps the packages isolated from the rest of the system. The `source` line activates it, and you need to run it every time you open a new terminal and want to work in the project.

### 3. First run

```bash
cd ~/whisper-dictation-mac && source .venv/bin/activate
python dictation.py
```

The selected model (Small by default, ~500 MB) is now downloaded to `~/whisper-dictation-mac/cache`. The English model is only fetched the first time you dictate in English.

When you see `🎙 Ready` (or `🎙 Redo` if the app language is Swedish), continue with the permissions below.

---

## macOS permissions

This is the step that makes the tool actually work, and also where almost every problem comes from. macOS requires three separate approvals, and they are tied to **the app you launch the script from**. That means Terminal, not Python.

Open **System Settings → Privacy & Security** and add Terminal to:

| List | What it controls | Without it |
|---|---|---|
| **Microphone** | reading audio | no audio is recorded |
| **Input Monitoring** | reading key presses | the hotkey does nothing |
| **Accessibility** | sending key presses | the text is never typed |

Two things that are easy to miss:

1. **Permissions are read when the app starts.** Adding Terminal while it is running has no effect. Quit Terminal completely with **Cmd+Q** (closing the window is not enough) and start it again.
2. **Secure Keyboard Entry** in Terminal's menu at the top must be unchecked. When it is on, all simulated input is blocked regardless of permissions.

Verify with this command. Run it, immediately click into a text field, and wait:

```bash
sleep 5; osascript -e 'tell application "System Events" to keystroke "hello"'
```

If "hello" is typed, everything is set up.

---

## Usage

Double-click `start_dictation.command` in Finder. A terminal window opens and a 🎤 appears in the menu bar.

| Action | Result |
|---|---|
| Hold **right Cmd** | records in the default language |
| Hold **Shift + right Cmd** | records in the other language |
| Release the key | transcribes and types the text |

The menu bar icon shows the state: 🎤 ready, 🔴 recording, ⏳ transcribing. `🎤 EN` means English is set as the default dictation language.

A small sound wave appears next to the mouse pointer while the tool is working. While you hold the key it is red and moves with your voice; once you release and the text is being transcribed it turns blue-violet and rolls until the text has been typed. The wave never takes focus and lets clicks pass through.

Click the menu bar icon to change model, dictation language, app language, or to quit. **App language** only controls the text in the menu and the terminal; **Dictation language (default)** controls which language you transcribe to by default. The two are chosen independently.

**Tips for better results:** start speaking as soon as you press the key. The 0.4 seconds before the press are kept anyway. Hold the key until you have finished speaking, and only then release it. Speak in full sentences; the model uses context and does noticeably better with it than with isolated words.

The terminal window can be minimized. It shows the transcribed text and how long each dictation took, which is useful if you want to fine-tune the settings.

---

## Settings

All settings are at the top of `dictation.py` under `konfiguration`. Restart the tool after a change.

| Setting | Default | Comment |
|---|---|---|
| `HOTKEY` | `keyboard.Key.cmd_r` | right Cmd |
| `DEFAULT_SIZE` | `small` | model on the very first start |
| `PREROLL_SECONDS` | `0.4` | audio kept from before the key press |
| `MIN_SPEECH_SECONDS` | `0.4` | shorter recordings are ignored |
| `MAX_RECORD_SECONDS` | `180` | protection against a stuck key |
| `WAVE_ENABLED` | `True` | sound wave by the mouse pointer; `False` turns it off |

Model, dictation language and app language are changed from the menu bar, not in the code. Your choices are saved to `settings.json` next to the script and persist across restarts. Delete the file to go back to the defaults.

### Models

| Size | Download | Comment |
|---|---|---|
| Tiny | ~80 MB | fastest, lowest accuracy |
| Base | ~150 MB | fast |
| **Small** | ~500 MB | **default**, good balance |
| Medium | ~1.5 GB | slower, more accurate |
| Large | ~3 GB | slowest, best |

Swedish runs on the National Library of Sweden's [KB-Whisper](https://huggingface.co/KBLab), trained on more than 50,000 hours of Swedish speech. It is much better at Swedish than OpenAI's equivalents, and KB-Whisper Small is on par with OpenAI Large. English runs on OpenAI's English models.

If you pick a size you haven't used before it is downloaded right away, and the icon shows ⬇️ until it is done. Models you stop using are dropped from memory but stay on disk in `cache/`. Delete that folder if you want to free up space.

Each size has a Swedish and an English variant, so dictating in both languages means two downloads per size.

### Changing the hotkey

Right Cmd works well, but Caps Lock is a better choice in the long run: it's a big key that is never used. Remap it to F18:

```bash
hidutil property --set '{"UserKeyMapping":[{"HIDKeyboardModifierMappingSrc":0x700000039,"HIDKeyboardModifierMappingDst":0x70000006D}]}'
```

Then set `HOTKEY = keyboard.Key.f18` in the script. The remapping lasts until the next restart of the computer.

Avoid right Option: on the Swedish Mac layout `@`, `$`, `\`, `{}` and `[]` are behind the Option key, so you would trigger a recording every time you typed an email address.

---

## Troubleshooting

**`osascript is not allowed to send keystrokes. (1002)`**

The Accessibility permission is missing or in a broken state. Reset it and let macOS ask again:

```bash
tccutil reset Accessibility com.apple.Terminal
```

Quit Terminal with Cmd+Q, start it again, run the script, and approve the dialog that appears. Cmd+Q and restart once more afterwards, since the permission is read when the app starts.

If you launch from VS Code, iTerm or Warp, that app needs the permission instead. Replace `com.apple.Terminal` with `com.microsoft.VSCode`, `com.googlecode.iterm2` or `dev.warp.Warp-Stable` respectively.

**The hotkey does nothing**

Input Monitoring is missing. Same procedure: add the app, Cmd+Q, restart.

**`Could not open the microphone`**

The Microphone permission is missing, or another app has exclusive use of the microphone. Check under System Settings → Sound → Input that the right microphone is selected.

**The text is strange or made up**

Whisper invents subtitle credits when it gets silence. These are already filtered out through the `HALLUCINATIONS` list in the script, and you can add your own lines there. If ordinary sentences come out wrong, microphone distance is more often the cause than the model.

**It takes too long**

The terminal window shows seconds per dictation. More than a second for short sentences suggests that a heavier model has been selected, or that something else is putting a heavy load on the processor.

---

## Uninstalling

```bash
rm -rf ~/whisper-dictation-mac
```

Also remove Terminal from the three permission lists in System Settings if you don't need it there for anything else. If you remapped Caps Lock, that goes away at the next restart of the computer.

---

## How it works

```
Key listener (pynput)
        │  hold → start buffering, release → send to queue
        ▼
Microphone stream (sounddevice)
        │  the stream is always open; 0.4 s pre-roll is kept continuously
        ▼
Transcription (faster-whisper + KB-Whisper)      ← its own worker thread
        │  numpy array directly, no temporary WAV file
        ▼
Typing (System Events via osascript)
```

Three threads share the work: the audio stream callback, the key listener, and a worker thread for transcription. The main thread is reserved for the macOS event loop, which the menu bar icon and the sound wave window require.

Transcription never happens in the key listener's callback. That callback runs on the macOS event tap, and blocking it causes input lag across the whole system.

The models run on the CPU. CTranslate2, which faster-whisper is built on, has no Metal backend, so the GPU is not used. For short dictations that makes no difference.

---

## License

[MIT](LICENSE). The Whisper models are downloaded separately and come with their own licenses.
