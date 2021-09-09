# Copyright (c) 2021 Angus Gratton
#
# SPDX-License-Identifier: Apache-2.0
#
# This module containts all of the on-the-wire USB protocol format for the Canalyst-II

from ctypes import (
    c_bool,
    c_byte,
    c_ubyte,
    c_uint16,
    c_uint32,
    LittleEndianStructure,
    sizeof,
)

USB_ID_VENDOR = 0x04D8  # This is Microchip's vendor ID, presumably licensed as Canalyst-II uses a PIC32
USB_ID_PRODUCT = 0x0053

# Possible flags for Message.send_type (can be ORed together)
SEND_TYPE_NORETRY = 1  # Drop the message if transmission fails first time
SEND_TYPE_ECHO = 2  # Echo the message back as RX (note: the TX message is echoed even if sending fails!!)


class Message(LittleEndianStructure):
    """CAN message representation"""

    _pack_ = 1
    _fields_ = [
        ("can_id", c_uint32),  # CAN ID
        ("timestamp", c_uint32),  # timestamp in units of 100us
        ("time_flag", c_byte),  # always 1?
        ("send_type", c_byte),  # ORed flag bits from SEND_TYPE_*
        ("remote", c_bool),  # Set if message is remote
        ("extended", c_bool),  # Set if CAN ID is an extended address
        ("data_len", c_byte),
        ("data", c_ubyte * 8),
    ]

    def __repr__(self):
        return f"CanalystMessage ID={self.can_id:#x} TS={self.timestamp:#x} Data={bytes(self.data).hex()}"


assert sizeof(Message) == 0x15


class MessageBuffer(LittleEndianStructure):
    """Bulk USB packet containing up to 3 messages for send/receive"""

    _pack_ = 1
    _fields_ = [
        ("count", c_byte),
        ("messages", Message * 3),
    ]


assert sizeof(MessageBuffer) == 0x40

# Command opcodes
# (Note that there are likely more opcodes than this, just not known)
#
COMMAND_INIT = 0x1  # InitCommand, no response
COMMAND_START = 0x2  # SimpleCommand, no response
COMMAND_STOP = 0x3  # SimpleCommand, no response
COMMAND_CLEAR_RX_BUFFER = 0x5  # SimpleCommand, no response
COMMAND_MESSAGE_STATUS = 0x0A  # SimpleCommand, responds MessageStatusResponse
COMMAND_CAN_STATUS = (
    0x0B  # send this in SimpleCommand, response CANStatusResponse (details unknown)
)
COMMAND_PREINIT = (
    0x13  # observed on wire with a long data payload and a response, purpose unknown
)


class SimpleCommand(LittleEndianStructure):
    """Command packet that doesn't have any associated data"""

    _pack_ = 1
    _fields_ = [
        ("command", c_uint32),  # One of COMMAND_* opcodes
        ("padding", c_uint32 * (0x10 - 0x01)),
    ]


assert sizeof(SimpleCommand) == 0x40


class InitCommand(LittleEndianStructure):
    """Packet for COMMAND_INIT opcode, sets up the CAN interface"""

    _pack_ = 1
    _fields_ = [
        ("command", c_uint32),  # COMMAND_INIT
        ("acc_code", c_uint32),  # Unknown (ACK behvaiour?), set to 0x1 by CANPro(?)
        ("acc_mask", c_uint32),  # Similar, set to 0xFFFFFFFF by CANPro
        ("unknown0", c_uint32),  # 0x0 always? maybe related to filter?
        (
            "filter",
            c_uint32,
        ),  # CANPro sets to 0x1 for "SingleFilter", 0x0 for "DualFilter" - meaning unknown
        ("unknown1", c_uint32),  # 0x0 always? maybe related to filter?
        ("timing0", c_uint32),  # BTR0
        ("timing1", c_uint32),  # BTR1
        (
            "mode",
            c_uint32,
        ),  # Unknown, set to 0x0 for now. Setting 0x1 seems to cause device to crash(?)
        ("unknown2", c_uint32),  # Always 0x1 - function unknown
        ("padding", c_uint32 * (0x10 - 0x0A)),
    ]


assert sizeof(InitCommand) == sizeof(SimpleCommand)


class MessageStatusResponse(LittleEndianStructure):
    """Response sent to the COMMAND_MESSAGE_STATUS opcode"""

    _pack_ = 1
    _fields_ = [
        ("command", c_uint32),
        ("rx_pending", c_uint32),
        ("tx_pending", c_uint16),
        # at one point this value was set to 0x1 which might have been an error condition (failed to send),
        # but might also have been a firmware bug (!). Have been unable to reproduce.
        ("unknown", c_uint16),
        ("padding", c_uint32 * (0x10 - 0x03)),
    ]


assert sizeof(MessageStatusResponse) == sizeof(SimpleCommand)


class CANStatusResponse(LittleEndianStructure):
    """Response sent to the COMMAND_CAN_STATUS opcode

    This is guesswork, mapping the names in the DLL structure to the
    fields in the packet - as this pattern also applies to the Messages,
    but maybe it's not this simple.
    """

    _pack_ = 1
    _fields_ = [
        ("command", c_uint32),
        ("err_interrupt", c_uint32),
        ("reg_mode", c_uint32),
        ("reg_status", c_uint32),
        ("reg_al_capture", c_uint32),
        ("reg_ec_capture", c_uint32),
        ("reg_ew_limit", c_uint32),
        ("reg_re_counter", c_uint32),
        ("reg_te_counter", c_uint32),
        ("padding", c_uint32 * (0x10 - 0x09)),
    ]


assert sizeof(CANStatusResponse) == sizeof(SimpleCommand)
