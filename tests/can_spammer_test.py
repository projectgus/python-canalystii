#!/usr/bin/env python
import canalystii
import struct
import time

CHANNELS = (0, 1)  # Which channels to test on?
TEST_SECS = 10  # How many seconds to sample for?
SLEEP_BETWEEN = 0.05  # How long to sleep between samples?


def main():
    print("Connecting to Canalyst-II device...")
    dev = canalystii.CanalystDevice(bitrate=1000000)

    print(f"Testing for {TEST_SECS} seconds...")

    deadline = time.time() + TEST_SECS
    last = [None, None]
    messages = [0, 0]
    errors = [0, 0]

    dev.clear_rx_buffer(0)
    dev.clear_rx_buffer(1)

    while time.time() < deadline:
        for ch in CHANNELS:
            for msg in dev.receive(ch):
                if last[ch] is None:
                    last[ch] = read_counter(msg)
                else:
                    messages[ch] += 1
                    (last[ch], result) = check_id(msg, last[ch])
                    if not result:
                        errors[ch] += 1
        time.sleep(0.05)

    for ch in CHANNELS:
        print(
            f"Channel {ch}: Received {messages[ch]} messages ({messages[ch]/TEST_SECS}/sec), {errors[ch]} errors"
        )


def check_id(msg, last_counter):
    msg_count = read_counter(msg)
    result = True
    if msg_count < last_counter:
        print(f"Backwards {msg_count:#x} < prev {last_counter:#x}")
        result = False
    elif msg_count != last_counter + 1:
        print(f"Unexpected {msg_count:#x} expected {last_counter + 1:#x}")
        result = False
    return (msg_count, result)


def read_counter(msg):
    return struct.unpack("<Q", bytes(msg.data))[0]


if __name__ == "__main__":
    main()
