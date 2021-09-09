# Canalyst-II Driver for Python

Unofficial Python userspace driver for the low cost USB analyzer "Canalyst-II" by Chuangxin Technology (创芯科技).

Uses [pyusb](https://pyusb.github.io/pyusb/) library for USB support on Windows, MacOS and Linux.

This driver is based on black box reverse engineering of the USB behaviour of the proprietary software, and reading the basic data structure layouts in the original python-can canalystii source.

Intended for use as a backend driver for [python-can](https://python-can.readthedocs.io/). However it can also be used standalone.

## Standalone Usage

```py
import canalystii

# Connect to the Canalyst-II device
# Passing a bitrate to the constructor causes both channels to be initialized and started.
dev = canalystii.CanalystDevice(bitrate=500000)

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
# Send 3 copies to channel 0
# (argument can be an instance of canalystii.Message or a list of instances)
dev.send(0, [new_message] * 3)

# Stop both channels (need to call start() again to resume capturing or send any messages)
dev.stop(0)
dev.stop(1)
```

## Limitations

Currently, the following things are not supported and may not be possible based on the known USB protocol:

* CAN bus error conditions. There is a function `get_can_status()` that seems to provide access to some internal device state, not clear if this can be used to determine when errors occured or invalid messages seen.
* Receive buffer hardware overflow detection (see Performance, below).
* ACK status of sent CAN messages.
* Failure status of sent CAN messages. If the device fails to get bus arbitration after some unknown amount of time, it will drop the message silently.
* Hardware filtering of incoming messages. There is a `filter` field of `InitCommand` structure, not clear how it works.
* Configuring whether messages are ACKed by Canalyst-II. This may be possible, see `InitCommand` `acc_code` and `acc_mask`.

## Performance

Because the Canalyst-II USB protocol requires polling, the host needs to constantly poll the device to request any new CAN messages. There is a trade-off of CPU usage against both latency and maximum receive throughput.

The hardware seems able to buffer 1000-2000 messages (possibly a little more) per channel. The maximum number seems to depend on relative timing of the messages. Therefore, if a 1Mbps (maximum speed) CAN channel is receiving the maximum possible ~7800 messages/second then software should call `receive()` at least every 100ms in order to avoid lost messages. It's not possible to tell if any messages in the hardware buffer were lost due to overflow.

Testing Linux CPython 3.9 on a i7-6500U CPU (~2016 vintage), calling `receive()` in a tight loop while receiving maximum message rate (~7800 messages/sec) on both channels (~15600 messages/sec total)  uses approximately 40% of a single CPU. Adding a 50ms delay `time.sleep(0.05)` in the loop drops CPU usage to around 10% without losing any messages. Longer sleep periods in the loop reduce CPU usage further but some messages are dropped. See the `tests/can_spammer_test.py` file for the test code.

In systems where the CAN message rate is lower than the maximum, `receive()` can be called less frequently without losing messages. In systems where the Python process may be pre-empted, it's possible for messages to be lost anyhow.
