/* main.c — Expert RTOS Lab
 * Raspberry Pi Pico 2 (RP2350) com FreeRTOS SMP
 * 4 tasks: mpu_task, fusion_task, uart_task, pwm_task
 *
 * Instrumentacao:
 *   GPIOs 16-19 sobem HIGH durante o trabalho util de cada task
 *   e voltam LOW ao terminar — medir com Saleae Logic 2.
 *
 * Para medir stack: #define ENABLE_STACK_STATS (ver abaixo).
 * Comentar essa linha antes de medir com o Saleae (printf polui o timing).
 */

#include <FreeRTOS.h>
#include <task.h>
#include <queue.h>

#include "pico/stdlib.h"
#include <stdio.h>
#include <math.h>

#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/pwm.h"
#include "mpu6050.h"
#include "Fusion.h"

/* -------------------------------------------------------------------------
 * SAMPLE_PERIOD: 10 ms = 100 Hz
 *
 * NOTA DE AUDITORIA: versoes anteriores deste lab podiam ter
 * SAMPLE_PERIOD = 0.1f (10 Hz), causando erro de escala 10x na integracao
 * do giroscopio (drift de yaw acelerado por fator 10).
 * Este codigo usa 0.01f — valor correto para leitura a 100 Hz.
 * Ver README, Secao 4, Pergunta 2.
 * ------------------------------------------------------------------------- */
#define SAMPLE_PERIOD   (0.01f)

/* I2C / MPU6050 ----------------------------------------------------------- */
#define MPU_ADDRESS     0x68
#define I2C_SDA_GPIO    4
#define I2C_SCL_GPIO    5
#define IMU_VCC_GPIO    14   /* IMU alimentado por GPIO — manter HIGH */

/* LED de status: duty cycle controlado pela pwm_task (brilho = |pitch|) --- */
#define LED_STATUS_PIN  15

/* Canais Saleae: HIGH durante o trabalho util da task --------------------- */
#define CH_MPU          19   /* CH0 -> mpu_task    */
#define CH_FUSION       18   /* CH1 -> fusion_task */
#define CH_UART         17   /* CH2 -> uart_task   */
#define CH_PWM          16   /* CH3 -> pwm_task    */

/* PWM --------------------------------------------------------------------- */
#define PWM_WRAP        255

/* Ativa stats_task (imprime high water mark a cada 5 s).
 * Comentar antes de medir com o Saleae para evitar interferencia do printf. */
#define ENABLE_STACK_STATS

/* -------------------------------------------------------------------------
 * Tipos de dados trocados entre tasks
 * ------------------------------------------------------------------------- */
typedef struct {
    int16_t accel[3];
    int16_t gyro[3];
} mpu_data_t;

typedef struct {
    float roll;
    float pitch;
    float yaw;
} angle_t;

/* -------------------------------------------------------------------------
 * Recursos FreeRTOS (globais por necessidade arquitetural)
 * ------------------------------------------------------------------------- */
static QueueHandle_t xQueueMPU;    /* mpu_data_t: mpu_task  -> fusion_task */
static QueueHandle_t xQueueUart;   /* angle_t:   fusion_task -> uart_task  */
static QueueHandle_t xQueuePwm;    /* angle_t:   fusion_task -> pwm_task   */

/* Handles das tasks, necessarios para uxTaskGetStackHighWaterMark() */
TaskHandle_t xMpuTask;
TaskHandle_t xFusionTask;
TaskHandle_t xUartTask;
TaskHandle_t xPwmTask;

/* -------------------------------------------------------------------------
 * Drivers MPU6050
 * ------------------------------------------------------------------------- */
static void mpu6050_init(void) {
    i2c_init(i2c_default, 400 * 1000);
    gpio_set_function(I2C_SDA_GPIO, GPIO_FUNC_I2C);
    gpio_set_function(I2C_SCL_GPIO, GPIO_FUNC_I2C);
    gpio_pull_up(I2C_SDA_GPIO);
    gpio_pull_up(I2C_SCL_GPIO);

    uint8_t buf[] = {0x6B, 0x00};
    i2c_write_blocking(i2c_default, MPU_ADDRESS, buf, 2, false);
}

/* Le 14 bytes a partir de 0x3B: 6 acel + 2 temp (descartado) + 6 gyro */
static void mpu6050_read_raw(int16_t accel[3], int16_t gyro[3]) {
    uint8_t buffer[14];
    uint8_t reg = 0x3B;

    i2c_write_blocking(i2c_default, MPU_ADDRESS, &reg, 1, true);
    i2c_read_blocking(i2c_default, MPU_ADDRESS, buffer, 14, false);

    for (int i = 0; i < 3; i++) {
        accel[i] = (int16_t)((buffer[i * 2] << 8) | buffer[(i * 2) + 1]);
    }
    for (int i = 0; i < 3; i++) {
        gyro[i] = (int16_t)((buffer[8 + i * 2] << 8) | buffer[8 + (i * 2) + 1]);
    }
}

/* -------------------------------------------------------------------------
 * Tasks
 * ------------------------------------------------------------------------- */

/* Le MPU6050 a 100 Hz via I2C e publica dados crus em xQueueMPU.
 * Usa vTaskDelayUntil para periodo fixo independente do tempo de execucao. */
void mpu_task(void *p) {
    (void)p;
    mpu6050_init();
    TickType_t last_wake = xTaskGetTickCount();

    while (true) {
        gpio_put(CH_MPU, 1);
        mpu_data_t data;
        mpu6050_read_raw(data.accel, data.gyro);
        xQueueSend(xQueueMPU, &data, 0);
        gpio_put(CH_MPU, 0);
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(10));
    }
}

/* Recebe dados crus, roda filtro AHRS (Fusion), publica angulos em duas filas.
 * O GPIO de medicao envolve apenas o calculo (nao o bloqueio na fila). */
void fusion_task(void *p) {
    (void)p;
    FusionAhrs ahrs;
    FusionAhrsInitialise(&ahrs);
    FusionBias bias;
    FusionBiasInitialise(&bias);

    mpu_data_t data;
    while (true) {
        if (xQueueReceive(xQueueMPU, &data, portMAX_DELAY) == pdTRUE) {
            gpio_put(CH_FUSION, 1);

            FusionVector gyroscope = {
                .axis.x = data.gyro[0] / 131.0f,
                .axis.y = data.gyro[1] / 131.0f,
                .axis.z = data.gyro[2] / 131.0f,
            };
            FusionVector accelerometer = {
                .axis.x = data.accel[0] / 16384.0f,
                .axis.y = data.accel[1] / 16384.0f,
                .axis.z = data.accel[2] / 16384.0f,
            };

            gyroscope = FusionBiasUpdate(&bias, gyroscope);
            FusionAhrsUpdateNoMagnetometer(&ahrs, gyroscope, accelerometer, SAMPLE_PERIOD);
            FusionEuler euler = FusionQuaternionToEuler(FusionAhrsGetQuaternion(&ahrs));

            angle_t ang = {
                .roll  = euler.angle.roll,
                .pitch = euler.angle.pitch,
                .yaw   = euler.angle.yaw,
            };
            xQueueSend(xQueueUart, &ang, 0);
            xQueueSend(xQueuePwm,  &ang, 0);

            gpio_put(CH_FUSION, 0);
        }
    }
}

/* Recebe angulos e serializa como texto via USB-CDC.
 * O printf pode bloquear quando o buffer USB esta cheio — isso e intencional
 * e sera capturado como WCET elevado no Saleae (ver README, Secao 4, Q3). */
void uart_task(void *p) {
    (void)p;
    angle_t ang;
    while (true) {
        if (xQueueReceive(xQueueUart, &ang, portMAX_DELAY) == pdTRUE) {
            gpio_put(CH_UART, 1);
            printf("roll=%.2f pitch=%.2f yaw=%.2f\n", ang.roll, ang.pitch, ang.yaw);
            gpio_put(CH_UART, 0);
        }
    }
}

/* Recebe angulos e ajusta duty cycle do LED de status (GPIO 15).
 *
 * Logica: pega o maior |angulo| entre roll e pitch (qualquer inclinacao acende).
 * Fusion retorna graus — constantes abaixo equivalem aos rad do enunciado:
 *   DEAD_ZONE  = 3.0 deg  (~0.05 rad): sensor nivelado → LED apagado
 *   SATURATION = 29.0 deg (~0.5  rad): ~30° já satura o LED
 * Curva quadratica: variações pequenas ficam visivelmente mais responsivas.
 *
 * CH_PWM (GPIO 16) pulsa todo ciclo, independente do duty calculado,
 * para medir WCET/jitter no Saleae mesmo quando o LED esta apagado. */
void pwm_task(void *p) {
    (void)p;
    gpio_set_function(LED_STATUS_PIN, GPIO_FUNC_PWM);
    uint slice = pwm_gpio_to_slice_num(LED_STATUS_PIN);
    pwm_set_wrap(slice, PWM_WRAP);
    pwm_set_gpio_level(LED_STATUS_PIN, 0);
    pwm_set_enabled(slice, true);

    const float DEAD_ZONE  = 3.0f;   /* graus — abaixo disso LED apagado */
    const float SATURATION = 29.0f;  /* graus — acima disso LED no maximo */

    angle_t ang;
    while (true) {
        if (xQueueReceive(xQueuePwm, &ang, portMAX_DELAY) == pdTRUE) {
            gpio_put(CH_PWM, 1);   /* toggle fora do if — pulsa todo ciclo */

            float roll_mag  = fabsf(ang.roll);
            float pitch_mag = fabsf(ang.pitch);
            float mag = (roll_mag > pitch_mag) ? roll_mag : pitch_mag;

            if (mag < DEAD_ZONE) {
                pwm_set_gpio_level(LED_STATUS_PIN, 0);
            } else {
                float norm = (mag - DEAD_ZONE) / (SATURATION - DEAD_ZONE);
                if (norm > 1.0f) norm = 1.0f;
                uint16_t duty = (uint16_t)(norm * norm * 255.0f);
                pwm_set_gpio_level(LED_STATUS_PIN, duty);
            }

            gpio_put(CH_PWM, 0);
        }
    }
}

/* Imprime high water mark de stack das 4 tasks a cada 5 s.
 * Desabilitar (comentar ENABLE_STACK_STATS) antes de medir com o Saleae. */
#ifdef ENABLE_STACK_STATS
void stats_task(void *p) {
    (void)p;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(5000));
        printf("\n=== Stack High Water Mark (words livres) ===\n");
        printf("  mpu_task:    %lu\n", (uint32_t)uxTaskGetStackHighWaterMark(xMpuTask));
        printf("  fusion_task: %lu\n", (uint32_t)uxTaskGetStackHighWaterMark(xFusionTask));
        printf("  uart_task:   %lu\n", (uint32_t)uxTaskGetStackHighWaterMark(xUartTask));
        printf("  pwm_task:    %lu\n", (uint32_t)uxTaskGetStackHighWaterMark(xPwmTask));
    }
}
#endif

/* Chamado pelo FreeRTOS ao detectar estouro de stack (configCHECK_FOR_STACK_OVERFLOW=2) */
void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName) { // cppcheck-suppress constParameterPointer
    (void)xTask;
    printf("STACK OVERFLOW: %s\n", pcTaskName);
    for (;;);
}

/* -------------------------------------------------------------------------
 * main
 * ------------------------------------------------------------------------- */
int main(void) {
    stdio_init_all();

    /* Alimenta o IMU via GPIO 14 (ANTES de inicializar o I2C na mpu_task) */
    gpio_init(IMU_VCC_GPIO);
    gpio_set_dir(IMU_VCC_GPIO, GPIO_OUT);
    gpio_put(IMU_VCC_GPIO, 1);

    /* GPIOs de medicao Saleae: saidas, inicialmente LOW */
    const uint saleae_pins[] = {CH_MPU, CH_FUSION, CH_UART, CH_PWM};
    for (int i = 0; i < 4; i++) {
        gpio_init(saleae_pins[i]);
        gpio_set_dir(saleae_pins[i], GPIO_OUT);
        gpio_put(saleae_pins[i], 0);
    }

    /* Filas */
    xQueueMPU  = xQueueCreate(16, sizeof(mpu_data_t));
    xQueueUart = xQueueCreate(8,  sizeof(angle_t));
    xQueuePwm  = xQueueCreate(8,  sizeof(angle_t));

    /* Criacao das tasks com afinidade de core (SMP).
     * Assinatura: xTaskCreateAffinitySet(func, nome, stack, param, prio, mask, handle)
     *
     * Core 0 (mask = 1<<0): mpu_task + fusion_task
     *   Cadeia produtor-consumidor via xQueueMPU. Manter no mesmo core
     *   elimina transferencia de dados entre caches e reduz latencia de fila.
     *
     * Core 1 (mask = 1<<1): uart_task + pwm_task
     *   Tarefas de saida (USB-CDC e PWM). Isoladas do pipeline de sensor,
     *   nao competem com mpu/fusion pelo tempo de CPU do Core 0.
     *
     * stats_task: mask = (1<<0)|(1<<1) — sem preferencia de core. */
    xTaskCreateAffinitySet(mpu_task,    "mpu",    1024, NULL, 3, (1 << 0), &xMpuTask);
    xTaskCreateAffinitySet(fusion_task, "fusion", 4096, NULL, 2, (1 << 0), &xFusionTask);
    xTaskCreateAffinitySet(uart_task,   "uart",   2048, NULL, 1, (1 << 1), &xUartTask);
    xTaskCreateAffinitySet(pwm_task,    "pwm",    1024, NULL, 1, (1 << 1), &xPwmTask);

#ifdef ENABLE_STACK_STATS
    xTaskCreateAffinitySet(stats_task, "stats", 1024, NULL, 1,
                           (1 << 0) | (1 << 1), NULL);
#endif

    vTaskStartScheduler();
    for (;;);
}
