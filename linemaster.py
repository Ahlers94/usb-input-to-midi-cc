import evdev
import mido
import time

mido.set_backend('mido.backends.rtmidi')

# 1. Setup states

pedal_states = {20: False, 21: False, 22: False}

def get_device():
    path = '/dev/input/by-id/usb-fff0_0003-event-kbd'
    while True:
        try:
            return evdev.InputDevice(path)
        except (FileNotFoundError, OSError):
            print("Waiting for Linemaster USB device...")
            time.sleep(2)

device = get_device()

# CHANGE: Open the system's 'Midi Through' port instead of a virtual one
# This uses the built-in ALSA through-port (usually 14:0)
output = mido.open_output('Midi Through:Midi Through Port-0 14:0')

print(f"--- Connected to {device.name} ---")
print("Sending MIDI to: Midi Through Port-0")

for event in device.read_loop():
    if event.type == evdev.ecodes.EV_KEY and event.value == 1:
        cc = None
        if event.code == 98:   cc = 20
        elif event.code == 55: cc = 21
        elif event.code == 74: cc = 22

        if cc is not None:
            pedal_states[cc] = not pedal_states[cc]
            midi_val = 127 if pedal_states[cc] else 0
            print(f"Stomp CC {cc} -> {midi_val}")
            output.send(mido.Message('control_change', channel=0, control=cc, value=midi_val))
