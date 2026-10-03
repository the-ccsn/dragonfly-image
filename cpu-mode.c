#include <cpuid.h>
#include <stdint.h>
#include <stdio.h>

/* Match the x86-64-v3 baseline, including OS support for AVX register state. */
static int supports_v3(void) {
    unsigned int eax, ebx, ecx, edx;
    const uint32_t leaf1 = (1u << 0) | (1u << 9) | (1u << 12) | (1u << 13)
        | (1u << 19) | (1u << 20) | (1u << 22) | (1u << 23) | (1u << 26)
        | (1u << 27) | (1u << 28) | (1u << 29);
    const uint32_t leaf7 = (1u << 3) | (1u << 5) | (1u << 8);
    if (!__get_cpuid(1, &eax, &ebx, &ecx, &edx) || (ecx & leaf1) != leaf1) {
        return 0;
    }
    /* XGETBV is only legal after checking XSAVE and OSXSAVE above. */
    __asm__ volatile ("xgetbv" : "=a"(eax), "=d"(edx) : "c"(0));
    if ((eax & 6u) != 6u) {
        return 0;
    }
    if (!__get_cpuid_count(7, 0, &eax, &ebx, &ecx, &edx)
        || (ebx & leaf7) != leaf7) {
        return 0;
    }
    if (!__get_cpuid(0x80000001, &eax, &ebx, &ecx, &edx)
        || (ecx & ((1u << 0) | (1u << 5))) != ((1u << 0) | (1u << 5))) {
        /* LAHF/SAHF and LZCNT */
        return 0;
    }
    return 1;
}

int main(void) {
    puts(supports_v3() ? "avx2" : "generic");
    return 0;
}
