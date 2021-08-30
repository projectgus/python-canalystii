# Tests

Some basic automated tests for Canalyst-II Behaviour.

## loopback_test.py

Expects channel 0 & 1 to be joined together (low to low and high to high), with termination set correctly.

This is a pytest module, run as `pytest loopback_test.py`

## can_spammer_test.py

Expects an Arduino Due running the "CAN_Spammer.ino" sketch to be attached to either Channel 0, Chanel 1, or both.

Tests throughput receiving messages from the spammer. Prints throughput rate for messages received, and any unexpected messages that may indicate dropped frames.

This is an ordinary script, doesn't print any pass/fail result just a throughput rate and an error count.

Note that when the firmware clears the RX buffer it may still keep one message somehow (firmware bug?), so 1 error per channel is possible on any run.

