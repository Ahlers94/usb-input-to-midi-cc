# =============================================================================
#  USB Foot Switch + Keypad → MIDI CC Bridge
#  For use with MODEP on Patchbox OS (or any ALSA MIDI setup)
#
#  REQUIREMENTS:
#    pip install evdev mido python-rtmidi
#
#  SETUP STEPS:
#    1. Find your device paths:
#         ls /dev/input/by-id/
#       Plug each USB device in one at a time to see which entry appears.
#       Update the 'path' values in DEVICES below.
#
#    2. Find your key codes:
#         python3 -c "import evdev; d = evdev.InputDevice('/dev/input/by-id/YOUR-ID'); [print(e) for e in d.read_loop()]"
#       Run that, tap each button, and note the 'code' value in the output.
#       Update the 'keymap' dicts below with { key_code: midi_cc_number }.
#
#    3. Find your MIDI port name:
#         python3 -c "import mido; mido.set_backend('mido.backends.rtmidi'); print(mido.get_output_names())"
#       Update MIDI_PORT below with the exact string from that list.
#
#    4. Set MIDI_CHANNEL to match your MODEP plugin bindings (0 = channel 1).
#
#    5. Run:  python3 linemaster.py
# =============================================================================

import evdev
import mido
import time
import sys
import threading
import queue

mido.set_backend('mido.backends.rtmidi')

# ── Config — edit everything in this section ──────────────────────────────────

# The exact MIDI port name to send to. Run step 3 above to find yours.
MIDI_PORT = 'Midi Through:Midi Through Port-0 14:0'

# MIDI channel to send on. 0 = channel 1, 1 = channel 2, etc.
# Must match what your MODEP plugins are listening on.
MIDI_CHANNEL = 0

# How many seconds to wait before retrying a lost USB or MIDI connection.
RECONNECT_DELAY = 2

# Each entry in DEVICES is one USB input device.
# You can add, remove, or rename entries freely — the name is just a label
# used in log output. Each device needs:
#   'path'   — the /dev/input/by-id/ path for that USB device (see step 1)
#   'keymap' — a dict mapping key codes to MIDI CC numbers (see step 2)
#
# Each button toggles its CC between 0 (off) and 127 (on) on every press.
# CC numbers must be unique across all devices (0–127 are valid).
# Standard MODEP-safe range to avoid conflicts: 20–119.
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
        'path': '/dev/input/by-id/YOUR-KEYPAD-DEVICE-ID',  # ← update this (step 1)
        'keymap': {
            # key_code: cc_number
            # Find key codes by running step 2 above, then tap each button.
            # Example:
            # 79: 30,   # keypad 1 → CC 30
            # 80: 31,   # keypad 2 → CC 31
            # 81: 32,   # keypad 3 → CC 32
        },
    },
}

# ── End of config — no need to edit below this line ───────────────────────────


def open_midi_output():
    """
    Open the MIDI output port defined in MIDI_PORT.
    Retries forever if the port isn't available yet, so it's safe
    to start this script before your MIDI software is running.
    """
    while True:
        try:
            port = mido.open_output(MIDI_PORT)
            print(f"[MIDI ] Connected to: {MIDI_PORT}")
            return port
        except Exception as e:
            print(f"[MIDI ] Waiting for MIDI port — {e}")
            time.sleep(RECONNECT_DELAY)


def open_device(name, path):
    """
    Open a USB input device by its /dev/input/by-id/ path.
    Retries forever if the device isn't plugged in yet, so boot order
    and hot-plugging are both handled automatically.
    """
    while True:
        try:
            dev = evdev.InputDevice(path)
            print(f"[USB  ] {name} connected: {dev.name}")
            return dev
        except (FileNotFoundError, OSError) as e:
            print(f"[USB  ] Waiting for {name} — {e}")
            time.sleep(RECONNECT_DELAY)


def device_reader(name, path, keymap, event_queue, stop_event):
    """
    Runs in its own background thread — one thread per physical device.

    Watches the device for key-down events, looks up the key code in the
    keymap, and if there's a match puts a (name, code, cc) tuple onto the
    shared event_queue for the main loop to process.

    If the device disconnects (e.g. cable pulled mid-gig), it waits and
    reconnects automatically without affecting the other device's thread.

    stop_event is a threading.Event used to shut all threads down cleanly
    on Ctrl-C.
    """
    device = open_device(name, path)

    while not stop_event.is_set():
        try:
            for event in device.read_loop():
                if stop_event.is_set():
                    break

                # Ignore anything that isn't a key press
                if event.type != evdev.ecodes.EV_KEY:
                    continue

                # event.value: 1 = key down, 0 = key up, 2 = key held
                # We only want a single trigger on press, not on release or hold
                if event.value != 1:
                    continue

                # Look up this key code in the device's keymap
                cc = keymap.get(event.code)
                if cc is not None:
                    # Pass the event to the main loop via the shared queue
                    event_queue.put((name, event.code, cc))

        except (OSError, IOError) as e:
            # Device was unplugged or lost by the kernel
            print(f"\n[USB  ] {name} disconnected — {e}")
            if not stop_event.is_set():
                print(f"[USB  ] Reconnecting {name} in {RECONNECT_DELAY}s …")
                time.sleep(RECONNECT_DELAY)
                device = open_device(name, path)


def send_cc(output, channel, control, value):
    """Send a single MIDI Control Change message."""
    output.send(mido.Message(
        'control_change',
        channel=channel,
        control=control,
        value=value,
    ))


def main():
    print("═" * 48)
    print("  Linemaster + Keypad → MIDI bridge")
    print("  (Ctrl-C to quit)")
    print("═" * 48)

    # Build a toggle-state dict for every CC number across all devices.
    # False = off (will send 0), True = on (will send 127).
    # Stored here in main() so state survives a USB reconnect.
    all_ccs = {cc for dev in DEVICES.values() for cc in dev['keymap'].values()}
    pedal_states = {cc: False for cc in all_ccs}

    midi_out    = open_midi_output()
    event_queue = queue.Queue()   # shared between all reader threads and main
    stop_event  = threading.Event()  # set on Ctrl-C to shut threads down cleanly

    # Spawn one background reader thread per device.
    # daemon=True means threads are killed automatically when main() exits.
    for name, cfg in DEVICES.items():
        t = threading.Thread(
            target=device_reader,
            args=(name, cfg['path'], cfg['keymap'], event_queue, stop_event),
            daemon=True,
            name=f"reader-{name}",
        )
        t.start()

    # Main loop: pull events off the queue and send MIDI.
    # All USB reading happens in the background threads above;
    # this loop only deals with MIDI output so a MIDI error
    # doesn't take down the USB readers and vice versa.
    while True:
        try:
            try:
                # Block for up to 0.5s so Ctrl-C stays responsive
                name, code, cc = event_queue.get(timeout=0.5)
            except queue.Empty:
                continue  # nothing arrived, loop back and wait again

            # Toggle the state for this CC and compute the MIDI value
            pedal_states[cc] = not pedal_states[cc]
            midi_val = 127 if pedal_states[cc] else 0

            print(f"[{name:<11}] code={code}  CC {cc} → {midi_val}")
            send_cc(midi_out, MIDI_CHANNEL, cc, midi_val)

        except Exception as e:
            # Most likely the MIDI port dropped (software restart, etc.)
            # Reopen it and carry on — USB reader threads are unaffected.
            print(f"\n[ERR  ] MIDI error — {e}")
            print(f"[ERR  ] Reopening MIDI port …")
            try:
                midi_out.close()
            except Exception:
                pass
            time.sleep(RECONNECT_DELAY)
            midi_out = open_midi_output()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO ] Stopped.")
        sys.exit(0)
