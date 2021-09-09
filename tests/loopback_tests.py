import canalystii
import gc
import pytest
import struct


@pytest.fixture()#scope="session")  # TODO: figure out how to properly GC these
def device():
    gc.collect()
    dev = canalystii.CanalystDevice(bitrate=1000000)
    dev.clear_rx_buffer(0)
    dev.clear_rx_buffer(1)
    return dev


def test_simple_loopback(device):
    msg = canalystii.Message(
        can_id=0x01,
        data_len=8,
        time_flag=1,
        data=(0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00, 0x01),
    )
    assert not device.receive(0)
    assert not device.receive(1)
    assert device.send(0, [msg], 0.1)
    assert not device.receive(0)
    rx = device.receive(1)
    assert len(rx) == 1
    assert rx[0].can_id == msg.can_id
    assert rx[0].data_len == msg.data_len
    assert bytes(rx[0].data) == bytes(msg.data)


def test_full_rxbuffer(device):
    msgs = [
        canalystii.Message(
            can_id=0x200, data_len=8, time_flag=1, data=tuple(struct.pack("<Q", idx))
        )
        for idx in range(3000)
    ]
    # allow up to 1 second to send 3000 messages
    assert device.send(0, msgs, 1.0)

    # there seems to be some amount of hardware FIFO that also needs to flush, so read twice
    rx = device.receive(1) + device.receive(1)
    assert len(rx) == 1000  # hardware buffer is 1000 messages
    assert all(c.can_id == 0x200 for c in rx)
    assert all(c.data_len == 8 for c in rx)
    for idx, c in enumerate(rx):
        if idx == 0:
            continue
        if c.timestamp < 0x00001000 and rx[idx - 1].timestmap > 0xFFFF0000:
            continue  # hardware clock wrapped
        assert c.timestamp >= rx[idx - 1].timestamp  # message timestamped in order

    # expect that older messages were dropped so we only have the latest 1000 messages we sent
    expected_msgs = msgs[-1000:]  # noqa: E203
    for r, e in zip(rx, expected_msgs):
        assert bytes(e.data) == bytes(r.data)


def test_clear_rx_buffer(device):
    msg0 = canalystii.Message(can_id=0x300, data_len=8, data=tuple(b"\xAA" * 8))
    msg1 = canalystii.Message(can_id=0x300, data_len=8, data=tuple(b"\xEE" * 8))
    assert not device.receive(0)
    assert not device.receive(1)

    # clear 0, keep 1
    assert device.send(0, msg0, 1.0)
    assert device.send(1, msg1, 1.0)
    device.clear_rx_buffer(0)
    assert not device.receive(0)
    assert device.receive(1)

    # clear 1, keep 0
    assert device.send(0, msg0, 1.0)
    assert device.send(1, msg1, 1.0)
    device.clear_rx_buffer(1)
    assert device.receive(0)
    assert not device.receive(1)

    # clear both
    assert device.send(0, msg0, 1.0)
    assert device.send(1, msg1, 1.0)
    device.clear_rx_buffer(0)
    device.clear_rx_buffer(1)
    assert not device.receive(0)
    assert not device.receive(1)


def test_bitrate_mismatch(device):
    def print_status(label, msg):
        print(f"{label}:")
        for field_name, _field_type in msg._fields_:
            if field_name != "padding":
                print(f"  {field_name}={hex(getattr(msg, field_name))} ")
        print()

    try:
        msg = canalystii.Message(can_id=0x222, data_len=8, data=tuple(b"\x33" * 8))
        device.init(1, bitrate=50000)
        # even though this won't be ACKed, the CANbus will send it anyhow
        assert device.send(0, msg, 1.0)
        assert not device.receive(1)
        assert not device.receive(0)
    finally:
        device.init(0, bitrate=1000000)
        device.init(1, bitrate=1000000)


def test_stop_receiver(device):
    msg0 = canalystii.Message(can_id=0x300, data_len=8, data=tuple(b"\xAA" * 8))

    assert device.send(0, msg0, 0.1)
    assert device.receive(1)

    device.stop(1)

    assert device.send(0, msg0, 0.1)
    with pytest.raises(RuntimeError):
        device.receive(1)

    device.start(1)

    assert device.send(0, msg0, 0.1)
    assert device.receive(1)


def test_stop_sender(device):
    msg0 = canalystii.Message(can_id=0x300, data_len=8, data=tuple(b"\xAB" * 8))

    assert device.send(0, msg0, 0.1)
    assert device.receive(1)

    device.stop(0)

    with pytest.raises(RuntimeError):
        device.send(0, msg0, 0.1)
    assert not device.receive(1)

    device.start(0)

    assert device.send(0, msg0, 0.1)
    assert device.receive(1)
