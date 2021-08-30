// Spam messages out CAN0 as fast as the Due will allow!
//
// Use together with the can_spammer_test.py script to verify peak Canalyst-II
// receive performance.
//
// NOTE: Requires due_can library. Library v2.0.1 sometimes sends CAN frames out
// of order (or drops them, possibly?), so will give incorrect results. The
// master branch library version doesn't have this issue.
//
#include "variant.h"
#include <due_can.h>

// Leave defined if you use native port, comment if using programming port
//#define Serial SerialUSB

void setup()
{
  Serial.begin(115200);
  Can0.begin(CAN_BPS_1000K);
  Serial.println("Starting...");
}

void loop()
{
  CAN_FRAME outgoing;
  outgoing.id = 0x400;
  outgoing.length = 8;
  outgoing.data.value = 0xDEADBEEF00000000ULL;

  while(1) {
    // Sending will fail unless a device on the bus ACKs the frame
    if(Can0.sendFrame(outgoing)) {
      outgoing.data.value++;
    }

    // Every second, print an estimate of the sending rate
    static uint32_t last_seconds;
    uint32_t seconds = millis() / 1000;
    if (seconds != last_seconds) {
      uint32_t counter = outgoing.data.value; // Log the lower word only, Arduino doesn't format 64-bit integers
      static uint32_t last_counter;
      Serial.print(seconds);
      Serial.print("s ");
      Serial.print((uint32_t)counter);
      Serial.print(" msgs ");
      Serial.print(((uint32_t)counter - last_counter) / (seconds - last_seconds));
      Serial.println("msg/s");
      last_counter = counter;
      last_seconds = seconds;
    }
  }
}
