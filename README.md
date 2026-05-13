# USB to MIDI CC Bridge

Converts USB foot switches and keypads into MIDI Control Change messages for use with MODEP on Patchbox OS. Supports multiple USB devices simultaneously and reconnects automatically if a device is unplugged mid-gig.

---

## Hardware

Tested with:
- **Linemaster** 3-pedal USB foot switch
- Raspberry Pi 3B+ running Patchbox OS with MODEP

Any USB device that presents as a keyboard (HID) should work.

---

## Requirements

Patchbox OS ships with Python 3. Install the two dependencies:

```bash
pip install evdev mido python-rtmidi
```

---

## Setup

### 1. Find your device paths

Plug each USB device in one at a time and run:

```bash
ls /dev/input/by-id/
```

Note the path that appears for each device. It will look something like:

```
usb-fff0_0003-event-kbd
```

Update the `'path'` values in the `DEVICES` section of `linemaster.py`.

---

### 2. Find your key codes

With the device plugged in, run:

```bash
python3 -c "import evdev; d = evdev.InputDevice('/dev/input/by-id/YOUR-DEVICE-ID'); [print(e) for e in d.read_loop()]"
```

Tap each button and look for the `code` value in the output. For example:

```
event at 1234.56, code 98, type 01, val 01
```

Update the `'keymap'` dicts in `linemaster.py` with `{ key_code: midi_cc_number }`.

---

### 3. Find your MIDI port name

```bash
python3 -c "import mido; mido.set_backend('mido.backends.rtmidi'); print(mido.get_output_names())"
```

Update `MIDI_PORT` in `linemaster.py` with the exact string from the output.

---

### 4. Set your MIDI channel

Update `MIDI_CHANNEL` to match your MODEP plugin bindings. `0` = channel 1, `1` = channel 2, etc.

---

### 5. Add your devices to the config

Open `linemaster.py` and edit the `DEVICES` section at the top. Each entry is one physical USB device:

```python
DEVICES = {
    'footswitch': {
        'path': '/dev/input/by-id/usb-fff0_0003-event-kbd',
        'keymap': {
            98: 20,   # left pedal   → CC 20
            55: 21,   # middle pedal → CC 21
            74: 22,   # right pedal  → CC 22
        },
    },
    'keypad': {
        'path': '/dev/input/by-id/YOUR-KEYPAD-DEVICE-ID',
        'keymap': {
            79: 30,   # keypad 1 → CC 30
            80: 31,   # keypad 2 → CC 31
            81: 32,   # keypad 3 → CC 32
        },
    },
}
```

You can add or remove device entries freely. CC numbers must be unique across all devices. Recommended range to avoid MODEP conflicts: **20–119**.

Each button **toggles** its CC between `0` (off) and `127` (on) on every press.

---

### 6. Run it

```bash
python3 linemaster.py
```

You should see:

```
════════════════════════════════════════════════
  Linemaster + Keypad → MIDI bridge
  (Ctrl-C to quit)
════════════════════════════════════════════════
[MIDI ] Connected to: Midi Through:Midi Through Port-0 14:0
[USB  ] footswitch connected: USB Keyboard
[USB  ] keypad connected: USB Keyboard
```

Press a button to confirm:

```
[footswitch ] code=98  CC 20 → 127
[footswitch ] code=98  CC 20 → 0
```

---

## Run on Boot (Systemd)

To start the bridge automatically when the Pi boots, create a systemd service.

Add your user to the `input` group first (required to read `/dev/input/` without sudo):

```bash
sudo usermod -aG input $USER
```

Log out and back in for the group change to take effect, then create the service file:

```bash
sudo nano /etc/systemd/system/linemaster.service
```

Paste the following (adjust the path to `linemaster.py` if needed):

```ini
[Unit]
Description=USB to MIDI CC Bridge
After=sound.target

[Service]
ExecStart=/usr/bin/python3 /home/patch/linemaster.py
Restart=always
RestartSec=5
User=patch

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl enable linemaster
sudo systemctl start linemaster
```

Check it's running:

```bash
sudo systemctl status linemaster
```

View live log output:

```bash
journalctl -u linemaster -f
```

---

## Reconnection Behaviour

The script is designed to survive a live gig without intervention:

| Event | Behaviour |
|---|---|
| USB device unplugged | That device's thread waits and reconnects automatically. The other device keeps working. |
| USB device replugged | Detected and reopened within `RECONNECT_DELAY` seconds (default: 2). |
| MIDI port drops | Main loop reopens the MIDI port. USB reader threads are unaffected. |
| Script crash | Systemd `Restart=always` relaunches it within 5 seconds. |

Toggle states are preserved across USB reconnects. A replug will not flip your CC states.

---

## Troubleshooting

**Permission denied on `/dev/input/`**
```bash
sudo usermod -aG input $USER
# then log out and back in
```

**MIDI port not found**
Run step 3 to list available ports. Make sure MODEP is running before the script starts, or just let it retry — it will connect automatically once the port appears.

**Key codes not matching**
Some keypads send different codes depending on whether Num Lock is active. Toggle Num Lock and re-run step 2 to compare.

**Device path keeps changing**
Use `/dev/input/by-id/` paths (not `/dev/input/event0` etc.) — the `by-id` paths are stable across reboots and replugs.
