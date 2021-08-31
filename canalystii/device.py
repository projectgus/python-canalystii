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
    # Small optimization, build common command packet one time
    COMMAND_MESSAGE_STATUS = protocol.SimpleCommand(protocol.COMMAND_MESSAGE_STATUS)

    MESSAGE_BUF_LEN = ctypes.sizeof(protocol.MessageBuffer)

    def __init__(
        self, device_index=0, usb_device=None, bitrate=None, timing0=None, timing1=None
    ):
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
        self._dev.reset()

    def clear_rx_buffer(self, channel):
        """Clears the device's receive buffer for the specified channel.

        Note that this doesn't seem to 100% work, it's possible to get a small number of messages even
        """
        self.send_command(
            channel, protocol.SimpleCommand(protocol.COMMAND_CLEAR_RX_BUFFER)
        )

    def flush_tx_buffer(self, channel, timeout=0):
        """Return only after all messages have been sent to this channel or timeout is reached.

        Returns True if flush is successful, False if timeout was reached. Pass 0 timeout to poll once only.
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
        the baud rate of an active channel.

        By default, the channel is started after being initialized (set start parameter to False to not do this.)
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
            acc_code=0x0,
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
        """Stop this channel. Data won't be sent or received on this channel until it is started again."""
        if not self._initialized[channel]:
            raise RuntimeError(f"Channel {channel} is not initialized.")
        self.send_command(channel, protocol.SimpleCommand(protocol.COMMAND_STOP))
        self._started[channel] = False

    def start(self, channel):
        """Start this channel."""
        if not self._initialized[channel]:
            raise RuntimeError(f"Channel {channel} is not initialized.")
        self.send_command(channel, protocol.SimpleCommand(protocol.COMMAND_START))
        self._started[channel] = True

    def receive(self, channel):
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
        """Return some internal CAN-related values. The actual meaning of these is currently unknown."""
        if not self._initialized[channel]:
            logger.warning(f"Channel {channel} is not initialized, CAN status may be invalid.")
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
