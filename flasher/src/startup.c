/* 最小启动文件：向量表 + 复位处理 + 默认中断处理
 * 供「拖入 .c 源码直接烧」使用，不依赖 HAL / CMSIS。
 * 目标：STM32F103（Cortex-M3，128KB Flash，20KB RAM）
 */
#include <stdint.h>

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
extern int main(void);

void Reset_Handler(void);
void Default_Handler(void);

/* 系统异常 */
void NMI_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void HardFault_Handler(void)  __attribute__((weak, alias("Default_Handler")));
void MemManage_Handler(void)  __attribute__((weak, alias("Default_Handler")));
void BusFault_Handler(void)   __attribute__((weak, alias("Default_Handler")));
void UsageFault_Handler(void) __attribute__((weak, alias("Default_Handler")));
void SVC_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void)   __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void)     __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void)    __attribute__((weak, alias("Default_Handler")));

#define D Default_Handler

__attribute__((section(".isr_vector"), used))
void (* const g_vectors[76])(void) = {
    (void (*)(void))&_estack,
    Reset_Handler,
    NMI_Handler,
    HardFault_Handler,
    MemManage_Handler,
    BusFault_Handler,
    UsageFault_Handler,
    0, 0, 0, 0,
    SVC_Handler,
    DebugMon_Handler,
    0,
    PendSV_Handler,
    SysTick_Handler,
    /* 之后是 60 个外设中断，全部指向默认处理 */
    D, D, D, D, D, D, D, D, D, D,
    D, D, D, D, D, D, D, D, D, D,
    D, D, D, D, D, D, D, D, D, D,
    D, D, D, D, D, D, D, D, D, D,
    D, D, D, D, D, D, D, D, D, D,
    D, D, D, D, D, D, D, D, D, D,
};

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    uint32_t *dst = &_sdata;
    while (dst < &_edata) *dst++ = *src++;

    for (dst = &_sbss; dst < &_ebss; ) *dst++ = 0;

    main();

    for (;;) { }
}

void Default_Handler(void)
{
    for (;;) { }
}
