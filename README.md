# Canalyst-II Driver for Python

Unofficial Python userspace driver for the low cost USB analyzer "Canalyst-II".

Uses [pyusb](https://pyusb.github.io/pyusb/) library for USB support, should work on Windows, MacOS and Linux.

This driver is based on black box reverse engineering and the original python-can canalystii source. It's mostly intended for use with python-can, but can also be used standalone.

## Usage

```py
import canalystii

# Connect to the Canalyst-II device
dev = canalystii.CanalystDevice(bitrate=500*1000)

# Receive all pending messages on channel 0
for msg in dev.receive(0):
    print(msg)

# The canalystii.Message class is a ctypes Structure, to minimize overhead
new_message = canalystii.Message(can_id=0x300,
                                 remote=False,
                                 extended=False,
                                 data_len=8,
                                 data=(0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08))
# Send one copy to channel 1
dev.send(1, new_message)
# Send 3 copies to channel 0 (argument can be any iterable, or single instance of canalystii.Message)
dev.send(0, [new_message] * 3)
```

## Performance

Because the Canalyst-II USB protocol requires polling, there is a trade-off between CPU usage and both latency and maximum receive throughput. The host needs to constantly poll the device to request any new CAN messages.

The hardware seems able to buffer 1000-2000 messages (possibly a little more) per channel. The maximum number seems to depend on relative timing of the messages. Therefore, a 1Mbps (maximum speed) CAN channel receiving the maximum possible ~7800 messages/second should call `receive()` at least every 100ms in order to avoid lost messages. The USB protocol doesn't provide any way to tell if any messages in the hardware buffer were lost.

Testing Linux CPython 3.9 on an older i7-6500U CPU, calling `receive()` in a tight loop while receiving maximum message rate (~7800 messages/sec) on both channels (~15600 messages/sec total)  uses approximately 40% of a single CPU. Adding a 50ms delay `time.sleep(0.05)` in the loop drops CPU usage to around 10% without losing any messages. Longer sleep periods in the loop reduce CPU usage further but some messages are dropped. See the `tests/can_spammer_test.py` file for the test code.

In systems where the CAN message rate is lower than the maximum, `receive()` can be called less frequently without losing messages. In systems where the Python process may be pre-empted, it's possible for messages to be lost anyhow.
