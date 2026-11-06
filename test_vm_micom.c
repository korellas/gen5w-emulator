#include "vm_micom.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    /* OEM requestBootMode -> sendPacket: APP, 0x8a -> 0x01, function 0x0101. */
    const uint8_t request[] = {0xff,0x8a,0x01,0x01,0x01,0x01,0x00,0x01,0x00};
    MicomFrame frame;
    for (size_t n = 0; n < sizeof request; ++n)
        assert(micom_parse(request, n, &frame) == 0);
    assert(micom_parse(request, sizeof request, &frame) == sizeof request);
    assert(frame.sender == 0x8a && frame.receiver == 1 && frame.function == 0x0101);
    assert(frame.size == 0 && frame.sequence == 0);
    uint8_t corrupt[sizeof request];
    memcpy(corrupt, request, sizeof request);
    corrupt[0] = 0; assert(micom_parse(corrupt, sizeof corrupt, &frame) == -1);
    memcpy(corrupt, request, sizeof request);
    corrupt[3] = 2; assert(micom_parse(corrupt, sizeof corrupt, &frame) == -1);
    memcpy(corrupt, request, sizeof request);
    corrupt[7] = 0; assert(micom_parse(corrupt, sizeof corrupt, &frame) == -1);
    corrupt[6] = 2; assert(micom_parse(corrupt, sizeof corrupt, &frame) == -1);

    const uint8_t temperatures[] = {160,184}; /* Oil 80 C; coolant 90 C. */
    const uint8_t expected[] = {0xff,1,0x8a,1,0x81,0x78,0,3,160,184,7};
    uint8_t output[MICOM_MAX_FRAME];
    assert(micom_encode(output, sizeof output, 1,0x8a,0x8178,temperatures,2,7) == sizeof expected);
    assert(!memcmp(output, expected, sizeof expected));
    assert(micom_parse(output, sizeof expected, &frame) == sizeof expected);
    assert(frame.size == 2 && !memcmp(frame.data, temperatures, 2));
    uint8_t joined[2 * sizeof request];
    memcpy(joined, request, sizeof request); memcpy(joined + sizeof request, request, sizeof request);
    int consumed = micom_parse(joined, sizeof joined, &frame);
    assert(consumed == sizeof request);
    assert(micom_parse(joined + consumed, sizeof joined - consumed, &frame) == sizeof request);
    uint8_t data[MICOM_MAX_DATA]; memset(data,0xff,sizeof data);
    assert(micom_encode(output,sizeof output,1,0x8a,0x8144,data,sizeof data,255) == MICOM_MAX_FRAME);
    assert(micom_parse(output,sizeof output,&frame) == MICOM_MAX_FRAME && frame.size == sizeof data);
    assert(!micom_encode(output,8,1,0x8a,0x8144,data,sizeof data,0));
    assert(!micom_encode(output,sizeof output,1,0x8a,0x8144,data,sizeof data + 1,0));
    uint8_t boot[MICOM_BOOT_SIZE];
    assert(micom_boot_payload(boot) == MICOM_BOOT_SIZE);
    assert(boot[0] == 1 && boot[7] == 0xc0 && boot[8] == 2 && boot[27] == 0);
    assert(boot[15] > 0 && boot[16] > 0);
    assert(boot[5] == 2); /* SystemProtocol.AVPowerStatus.AVON, not a main-mode value. */
    puts("MICOM framing: fragmented/coalesced/max-length/malformed frames and parked fixture passed");
    return 0;
}
