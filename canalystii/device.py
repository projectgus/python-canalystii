# Copyright (c) 2021 Angus Gratton
#
# SPDX-License-Identifier: Apache-2.0
#
# This module contains device-level interface to Canalyst-II
import ctypes
import logging
import usb.core
import time

from . import protocol

logger = logging.getLogger(__name__)

# "Fast" lookups to go from channel to USB endpoint number
CHANNEL_TO_COMMAND_EP = [2, 4]  # Command EP for channels 0,1
CHANNEL_TO_MESSAGE_EP = [1, 3]  # CAN Message EP for channels 0, 1


class CanalystDevice(object):
    """Encapsulates a low-level USB interface to a Canalyst-II device.

    Constructing an instance of this class will cause pyusb to acquire the
    relevant USB interface, and retain it until the object is garbage collected.

    :param device:_index if more than one Canalyst-II device is connected, this is
        the index to use in the list.
    :param usb_device: Optional argument to ignore device_index and provide an instance
        of a pyusb device object directly.
    :param bitrate: If set, both channels are initialized to the specified bitrate and
        started automatically. If unset (default) then the "init" method must be called
        before using either channel.
    :param timing0: Optional parameter to provide BTR timing directly. Either both or
        neither timing0 and timing1 must be set, and setting these arguments is mutually
        exclusive with setting bitrate. If set, both channels are initialized and started
        automatically.
    """

    # Small optimization, build common command packet one time
    COMMAND_MESSAGE_STATUS = protocol.SimpleCommand(protocol.COMMAND_MESSAGE_STATUS)

    MESSAGE_BUF_LEN = ctypes.sizeof(protocol.MessageBuffer)

    def __init__(
        self, device_index=0, usb_device=None, bitrate=None, timing0=None, timing1=None
    ):
        """Constructor function."""
        if usb_device is not None:
            self._dev = usb_device
        else:
            devices = list(
                usb.core.find(
                    idVendor=protocol.USB_ID_VENDOR,
                    idProduct=protocol.USB_ID_PRODUCT,
                    find_all=True,
                )
            )
            if not devices:
                raise ValueError("No Canalyst-II USB device found")
            if len(devices) <= device_index:
                raise ValueError(
                    f"Can't open device_index {device_index}, only {len(devices)} devices found."
                )
            self._dev = devices[device_index]
            active_config = self._dev.get_active_configuration()
            if active_config is None or active_config.bConfigurationValue != 1:
                self._dev.set_configuration(1)

            self._initialized = [False, False]
            self._started = [False, False]

            # Check this looks like the firmware we expect: as this is an unofficial driver,
            # we don't know if other versions might are out there.
            if self._dev.product != "Chuangxin Tech USBCAN/CANalyst-II":
                logger.warning(
                    f"Unexpected USB product string: {self._dev.product}. Firmware version may be unsupported."
                )
            interfaces = self._dev.get_active_configuration().interfaces()
            if len(interfaces) != 1:
                logger.warning(
                    f"Unexpected interface count {len(interfaces)}. Firmware version may be unsupported."
                )
            endpoints = interfaces[0].endpoints()
            # For whatever reason FW has 6 bidirectional BULK endpoints!
            if len(endpoints) != 12:
                logger.warning(
                    f"Unexpected endpoint count {len(endpoints)}. Firmware version mayb e unsupported."
                )

            if bitrate is not None or timing0 is not None:
                # if not specified, don't initialize yet
                self.init(0, bitrate, timing0, timing1)
                self.init(1, bitrate, timing0, timing1)

    def __del__(self):
        # In theory pyusb should manage this, but in order to allow a new device
        # object to be created later (in the same process)  it seems the device needs to be reset (which
        # calls dispose internally)
        try:
            self._dev.reset()
        except AttributeError:
            pass

    def clear_rx_buffer(self, channel):
        """Clears the device's receive buffer for the specified channel.

        Note that this doesn't seem to 100% work in the device firmware, on a busy bus
        it's possible to receive a small number of "old" messages even after calling this.

        :param channel: Channel (0 or 1) to clear the RX buffer on.
        """
        self.send_command(
            channel, protocol.SimpleCommand(protocol.COMMAND_CLEAR_RX_BUFFER)
        )

    def flush_tx_buffer(self, channel, timeout=0):
        """Check if all pending messages have left the hardware TX buffer and optionally keep polling until
        this happens or a timeout is reached.

        Note that due to hardware limitations, "no messages in TX buffer" doesn't necessarily mean
        that the messages were sent successfully - for the default send type 0 (see Message.send_type), the
        hardware will attempt bus arbitration multiple times but if it fails then it will still "send" the
        message. It also doesn't consider the ACK status of the message.

        :param channel: Channel (0 or 1) to flush the TX buffer on.
        :param timeout: Optional number of seconds to continue polling for empty TX buffer. If 0 (default),
            this function will immediately return the current status of the send buffer.
        :return: True if flush is successful (no pending messages to send), False if flushing timed out.
        """
        deadline = None
        while deadline is None or time.time() < deadline:
            if deadline is None and timeout is not None:
                deadline = time.time() + timeout

            resp = self.send_command(
                channel,
                self.COMMAND_MESSAGE_STATUS,
                protocol.MessageStatusResponse,
            )
            if resp.tx_pending == 0:
                return True
        return False  # timeout!

    def send_command(self, channel, command_packet, response_class=None):
        """Low-level function to send a command packet to the channel and optionally wait for a response.

        :param channel: Channel (0 or 1) to flush the TX buffer on.
        :param command_packet: Data to send to the channel. Usually this will be a ctypes Structure, but can be
           anything that supports a bytes buffer interface.
        :param response_class: If None (default) then this function doesn't expect to read anything back from the
           device. If not None, should be a ctypes class - 64 bytes will be read into a buffer and returned as an
           object of this type.
        """
        ep = CHANNEL_TO_COMMAND_EP[channel]
        self._dev.write(ep, memoryview(command_packet).cast("B"))
        if response_class:
            response = self._dev.read(ep | 0x80, 0x40)
            if len(response) < ctypes.sizeof(response_class):
                raise RuntimeError(
                    f"Expected response minimum {ctypes.sizeof(response_class)} bytes, got {len(response)} bytes."
                )
            return response_class.from_buffer(response)

    def init(self, channel, bitrate=None, timing0=None, timing1=None, start=True):
        """Initialize channel to a particular baud rate. This can be called more than once to change
        the channel bit rate.

        :param channel: Channel (0 or 1) to initialize.
        :param bitrate: Bitrate to set for the channel. Either this argument of both
             timing0 and timing1 must be set.
        :param timing0: Raw BTR0 timing value to determine the bitrate. If this argument is set,
             timing1 must also be set and bitrate argument must be unset.
        :param timing1: Raw BTR1 timing value to determine the bitrate. If this argument is set,
             timing0 must also be set and bitrate argument must be unset.
        :param start: If True (default) then the channel is started after being initialized.
             If set to False, the channel will not be started until the start function is called
             manually.
        """
        if bitrate is None and timing0 is None and timing1 is None:
            raise ValueError(
                "Either bitrate or both timing0/timing1 parameters are required"
            )
        if bitrate is not None:
            if timing0 is not None or timing1 is not None:
                raise ValueError(
                    "If bitrate parameter is set, both timing0 and timing1 parameters should be None"
                )
            try:
                timing0, timing1 = TIMINGS[bitrate]
            except KeyError:
                raise ValueError(f"Bitrate {bitrate} is not supported")

        if timing0 is None or timing1 is None:
            raise ValueError(
                "To set raw timings, both timing0 and timing1 parameters are required"
            )

        init_packet = protocol.InitCommand(
            command=protocol.COMMAND_INIT,
            acc_code=0x1,
            acc_mask=0xFFFFFFFF,
            filter=0x1,  # placeholder
            timing0=timing0,
            timing1=timing1,
            mode=0x0,  # placeholder
            unknown2=0x1,
        )  # placeholder
        self.send_command(channel, init_packet)
        self._initialized[channel] = True
        self.start(channel)

    def stop(self, channel):
        """Stop this channel. CAN messages won't be sent or received on this channel until it is started again.

        :param channel: Channel (0 or 1) to stop. The channel must already be initialized.
        """
        if not self._initialized[channel]:
            raise RuntimeError(f"Channel {channel} is not initialized.")
        self.send_command(channel, protocol.SimpleCommand(protocol.COMMAND_STOP))
        self._started[channel] = False

    def start(self, channel):
        """Start this channel. This allows CAN messages to be sent and received. The hardware
           will buffer received messages until the receive() function is called.

        :param channel: Channel (0 or 1) to start. The channel must already be initialized.
        """
        if not self._initialized[channel]:
            raise RuntimeError(f"Channel {channel} is not initialized.")
        self.send_command(channel, protocol.SimpleCommand(protocol.COMMAND_START))
        self._started[channel] = True

    def receive(self, channel):
        """Poll the hardware for received CAN messages and return them all as a list.

        :param channel: Channel (0 or 1) to poll. The channel must be started.
        :return: List of Message objects representing received CAN messages, in order.
        """
        if not self._initialized[channel]:
            raise RuntimeError(f"Channel {channel} is not initialized.")
        if not self._started[channel]:
            raise RuntimeError(f"Channel {channel} is stopped, can't receive messages.")
        status = self.send_command(
            channel, self.COMMAND_MESSAGE_STATUS, protocol.MessageStatusResponse
        )

        if status.rx_pending == 0:
            return []

        # Calculate how large our read should be, add one buffer to try and avoid issues
        # caused by fragmentation (sometimes the RX message is in the next buffer not the
        # current one)
        rx_buffer_num = (status.rx_pending + 2) // 3 + 1
        rx_buffer_size = rx_buffer_num * self.MESSAGE_BUF_LEN

        message_ep = CHANNEL_TO_MESSAGE_EP[channel]
        rx_data = self._dev.read(message_ep | 0x80, rx_buffer_size)

        assert len(rx_data) % self.MESSAGE_BUF_LEN == 0
        num_buffers = len(rx_data) // self.MESSAGE_BUF_LEN

        # Avoid copying data here, parse the MessageBuffer structures but return
        # a list of Message objects all pointing into the original USB data
        # buffer.  This is a little wasteful of total RAM but should be faster,
        # and we assume the caller is going to process these into another format
        # anyhow.
        result = []
        message_bufs = (protocol.MessageBuffer * num_buffers).from_buffer(rx_data)
        for buf in message_bufs:
            count = buf.count
            assert 0 <= count <= 3
            result += buf.messages[:count]

        return result

    def send(self, channel, messages, flush_timeout=None):
        """Send one or more CAN messages to the channel.

        :param channel: Channel (0 or 1) to send to. The channel must be started.
        :param messages: Either a single Message object, or a list of
              Message objects to send.
        :param flush_timeout: If set, don't return until TX buffer is flushed or timeout is
              reached.
              Setting this parameter causes the software to poll the device continuously
              for the buffer state. If None (default) then the function returns immediately,
              when some CAN messages may still be waiting to sent due to CAN bus arbitration.
              See flush_tx_buffer() function for details.
        :return: None if flush_timeout is None (default). Otherwise True if all messages sent
             (or failed), False if timeout reached.
        """
        if not self._initialized[channel]:
            raise RuntimeError(f"Channel {channel} is not initialized.")
        if not self._started[channel]:
            raise RuntimeError(f"Channel {channel} is stopped, can't send messages.")
        if isinstance(messages, protocol.Message):
            messages = [messages]
        tx_buffer_num = (len(messages) + 2) // 3
        buffers = (protocol.MessageBuffer * tx_buffer_num)()
        for idx, msg in enumerate(messages):
            buf_idx = idx // 3
            buffers[buf_idx].count += 1
            buffers[buf_idx].messages[idx % 3] = msg

        message_ep = CHANNEL_TO_MESSAGE_EP[channel]
        self._dev.write(message_ep, memoryview(buffers).cast("B"))

        if flush_timeout is not None:
            return self.flush_tx_buffer(channel, flush_timeout)

    def get_can_status(self, channel):
        """Return some internal CAN-related values. The actual meaning of these is currently unknown.

        :return: Instance of the CANStatusResponse structure. Note the field names may not be accurate.
        """
        if not self._initialized[channel]:
            logger.warning(
                f"Channel {channel} is not initialized, CAN status may be invalid."
            )
        return self.send_command(
            channel,
            protocol.SimpleCommand(protocol.COMMAND_CAN_STATUS),
            protocol.CANStatusResponse,
        )


# Lookup from bitrate to Timing0 (BTR0), Timing1 (BTR1) values
TIMINGS = {
    5000: (0xBF, 0xFF),
    10000: (0x31, 0x1C),
    20000: (0x18, 0x1C),
    33330: (0x09, 0x6F),
    40000: (0x87, 0xFF),
    50000: (0x09, 0x1C),
    66660: (0x04, 0x6F),
    80000: (0x83, 0xFF),
    83330: (0x03, 0x6F),
    100000: (0x04, 0x1C),
    125000: (0x03, 0x1C),
    200000: (0x81, 0xFA),
    250000: (0x01, 0x1C),
    400000: (0x80, 0xFA),
    500000: (0x00, 0x1C),
    666000: (0x80, 0xB6),
    800000: (0x00, 0x16),
    1000000: (0x00, 0x14),
}
