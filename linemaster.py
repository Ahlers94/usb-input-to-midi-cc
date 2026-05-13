import evdev
import mido
import time
import sys

mido.set_backend('mido.backends.rtmidi')

# ── Config ────────────────────────────────────────────────────────────────────
DEVICE_PATH   = '/dev/input/by-id/usb-fff0_0003-event-kbd'
MIDI_PORT     = 'Midi Through:Midi Through Port-0 14:0'
MIDI_CHANNEL  = 0
RECONNECT_DELAY = 2  # seconds between reconnect attempts

# Key code → MIDI CC number
KEYMAP = {
    98: 20,
    55: 21,
    74: 22,
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


def open_device():
    """Open the USB foot switch, retrying until it appears."""
    while True:
        try:
            dev = evdev.InputDevice(DEVICE_PATH)
            print(f"[USB  ] Connected to: {dev.name}")
            return dev
        except (FileNotFoundError, OSError) as e:
            print(f"[USB  ] Waiting for Linemaster device — {e}")
            time.sleep(RECONNECT_DELAY)


def send_cc(output, channel, control, value):
    """Send a MIDI CC message, catching send errors."""
    try:
        output.send(mido.Message(
            'control_change',
            channel=channel,
            control=control,
            value=value,
        ))
    except Exception as e:
        print(f"[MIDI ] Send error — {e}")
        raise  # let the caller handle reconnection


def main():
    print("═" * 48)
    print("  Linemaster → MIDI bridge  (Ctrl-C to quit)")
    print("═" * 48)

    # Pedal toggle state — False = off (0), True = on (127)
    pedal_states = {cc: False for cc in KEYMAP.values()}

    midi_out = open_midi_output()
    device   = open_device()

    while True:
        try:
            for event in device.read_loop():
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                if event.value != 1:          # 1 = key-down only
                    continue

                cc = KEYMAP.get(event.code)
                if cc is None:
                    continue

                # Toggle
                pedal_states[cc] = not pedal_states[cc]
                midi_val = 127 if pedal_states[cc] else 0

                print(f"[PEDAL] code={event.code}  CC {cc} → {midi_val}")
                send_cc(midi_out, MIDI_CHANNEL, cc, midi_val)

        except (OSError, IOError) as e:
            # USB device lost (unplugged, kernel reset, etc.)
            print(f"\n[USB  ] Device disconnected — {e}")
            print(f"[USB  ] Reconnecting in {RECONNECT_DELAY}s …")
            time.sleep(RECONNECT_DELAY)
            device = open_device()

        except Exception as e:
            # MIDI port gone or unexpected error — reconnect everything
            print(f"\n[ERR  ] Unexpected error — {e}")
            print(f"[ERR  ] Reopening MIDI and device …")
            try:
                midi_out.close()
            except Exception:
                pass
            time.sleep(RECONNECT_DELAY)
            midi_out = open_midi_output()
            device   = open_device()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO ] Stopped.")
        sys.exit(0)
