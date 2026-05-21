#ifndef PINS_H
#define PINS_H

/* I2C / MPU6050 */
#define I2C_SDA_GPIO    4
#define I2C_SCL_GPIO    5
#define IMU_VCC_GPIO    14   /* IMU alimentado via GPIO — manter HIGH */

/* LED de status (PWM pela pwm_task: brilho proporcional a |pitch|) */
#define LED_STATUS_PIN  15

/* Canais Saleae Logic 2 — GPIOs de instrumentacao
 * Sobe HIGH durante o trabalho util da task, volta LOW ao terminar.
 * Usar sample rate >= 10 MS/s para resolucao de ~100 ns. */
#define CH_MPU          19   /* CH0 -> mpu_task    (periodo 10 ms) */
#define CH_FUSION       18   /* CH1 -> fusion_task (acionada por fila) */
#define CH_UART         17   /* CH2 -> uart_task   (acionada por fila) */
#define CH_PWM          16   /* CH3 -> pwm_task    (acionada por fila) */

#endif /* PINS_H */
