#ifndef VM_MICOM_H
#define VM_MICOM_H
#include <stddef.h>
#include <stdint.h>

enum { MICOM_MAX_DATA = 256, MICOM_MAX_FRAME = 265, MICOM_BOOT_SIZE = 28 };
typedef struct {
    uint8_t sender, receiver, type, sequence;
    uint16_t function;
    const uint8_t *data;
    size_t size;
} MicomFrame;

/* Positive consumed length, zero for incomplete input, -1 for invalid framing. */
int micom_parse(const uint8_t *input, size_t size, MicomFrame *frame);
size_t micom_encode(uint8_t *output, size_t capacity, uint8_t sender,
                    uint8_t receiver, uint16_t function, const uint8_t *data,
                    size_t size, uint8_t sequence);
size_t micom_boot_payload(uint8_t output[MICOM_BOOT_SIZE]);
#endif
