/* 示例：拖进烧录器就能跑。
 * 不依赖任何库，直接写寄存器：PC13 与 PB0 反相闪烁。
 */
#include <stdint.h>

#define RCC_APB2ENR (*(volatile uint32_t *)0x40021018)
#define GPIOB_CRL   (*(volatile uint32_t *)0x40010C00)
#define GPIOB_ODR   (*(volatile uint32_t *)0x40010C0C)
#define GPIOC_CRH   (*(volatile uint32_t *)0x40011004)
#define GPIOC_ODR   (*(volatile uint32_t *)0x4001100C)

static void delay(volatile uint32_t n)
{
    while (n--) __asm__("nop");
}

int main(void)
{
    RCC_APB2ENR |= (1u << 3) | (1u << 4);   /* GPIOB + GPIOC 时钟 */

    GPIOC_CRH = (GPIOC_CRH & 0xFF0FFFFFu) | 0x00200000u;  /* PC13 推挽输出 2MHz */
    GPIOB_CRL = (GPIOB_CRL & 0xFFFFFFF0u) | 0x00000002u;  /* PB0  推挽输出 2MHz */

    for (;;) {
        GPIOC_ODR |= (1u << 13);    /* PC13 高 = 板载 LED 灭 */
        GPIOB_ODR |= (1u << 0);     /* PB0  高 = 外挂 LED 亮 */
        delay(200000);

        GPIOC_ODR &= ~(1u << 13);   /* PC13 低 = 板载 LED 亮 */
        GPIOB_ODR &= ~(1u << 0);    /* PB0  低 = 外挂 LED 灭 */
        delay(200000);
    }
}
