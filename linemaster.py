import evdev
import mido
import time
import sys
import threading
import queue

mido.set_backend('mido.backends.rtmidi')

# ── Config ────────────────────────────────────────────────────────────────────
MIDI_PORT       = 'Midi Through:Midi Through Port-0 14:0'
MIDI_CHANNEL    = 0
RECONNECT_DELAY = 2  # seconds between reconnect attempts

DEVICES = {
    'footswitch': {
        'path': '/dev/input/by-id/usb-fff0_0003-event-kbd',
        'keymap': {
            98: 20,
            55: 21,
            74: 22,
        },
    },
    'keypad': {
        'path': '/dev/input/by-id/YOUR-KEYPAD-DEVICE-ID',  # ← update this
        'keymap': {
            # Add your keypad key codes and desired CC numbers here, e.g.:
            # 79: 30,
            # 80: 31,
            # 81: 32,
        },
    },
}
# ─────────────────────────────────────────────────────────────────────────────

def open_midi_output():
    """Open MIDI output, retrying until it succeeds."""
    while True:
        try:
            port = mido.open_output(MIDI_PORT)
            print(f"[MIDI ] Connected to: {MIDI_PORT}")
            return port
        except Exception as e:
            print(f"[MIDI ] Waiting for MIDI port — {e}")
            time.sleep(RECONNECT_DELAY)


def open_device(name, path):
    """Open a USB input device, retrying until it appears."""
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
    Runs in its own thread. Reads events from one device and puts
    (name, code, cc) tuples onto the shared queue for the main loop.
    Reconnects automatically if the device disappears.
    """
    device = open_device(name, path)

    while not stop_event.is_set():
        try:
            for event in device.read_loop():
                if stop_event.is_set():
                    break
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                if event.value != 1:          # key-down only
                    continue
                cc = keymap.get(event.code)
                if cc is not None:
                    event_queue.put((name, event.code, cc))

        except (OSError, IOError) as e:
            print(f"\n[USB  ] {name} disconnected — {e}")
            if not stop_event.is_set():
                print(f"[USB  ] Reconnecting {name} in {RECONNECT_DELAY}s …")
                time.sleep(RECONNECT_DELAY)
                device = open_device(name, path)


def send_cc(output, channel, control, value):
    """Send a MIDI CC message."""
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

    # Collect all CC numbers across all devices for state tracking
    all_ccs = {cc for dev in DEVICES.values() for cc in dev['keymap'].values()}
    pedal_states = {cc: False for cc in all_ccs}

    midi_out    = open_midi_output()
    event_queue = queue.Queue()
    stop_event  = threading.Event()

    # Start one reader thread per device
    for name, cfg in DEVICES.items():
        t = threading.Thread(
            target=device_reader,
            args=(name, cfg['path'], cfg['keymap'], event_queue, stop_event),
            daemon=True,
            name=f"reader-{name}",
        )
        t.start()

    # Main loop — process events from the shared queue
    while True:
        try:
            try:
                name, code, cc = event_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            pedal_states[cc] = not pedal_states[cc]
            midi_val = 127 if pedal_states[cc] else 0

            print(f"[{name:<11}] code={code}  CC {cc} → {midi_val}")
            send_cc(midi_out, MIDI_CHANNEL, cc, midi_val)

        except Exception as e:
            # MIDI port lost — reopen and keep going
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
