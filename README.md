# Expert RTOS — Métricas de Tempo Real com FreeRTOS no Pico 2

Lab "Expert - Firmware - RTOS" — Sistemas Embarcados (Insper).

## Seção 1 — Visão geral

### Objetivo

Medir e comparar métricas de tempo real (WCET, Jitter, Deadline Miss Rate, Stack Usage) de um pipeline de 4 tasks FreeRTOS em modo **Single Core** e **SMP (2 cores)** no Raspberry Pi Pico 2 (RP2350).

### Hardware

| Componente | Descrição |
|---|---|
| Placa | Raspberry Pi Pico 2 (RP2350, dual-core Cortex-M33) |
| IMU | MPU6050 (acelerômetro + giroscópio, I²C) |
| Analisador lógico | Saleae Logic 2 (4 canais digitais) |

### Mapeamento de pinos

| GPIO | Função |
|---|---|
| 4 | I²C SDA (MPU6050) |
| 5 | I²C SCL (MPU6050) |
| 14 | IMU VCC (saída HIGH — alimenta o MPU6050) |
| 15 | LED verde de status (PWM — brilho ∝ \|pitch\|) |
| 16 | CH3 Saleae → `pwm_task` |
| 17 | CH2 Saleae → `uart_task` |
| 18 | CH1 Saleae → `fusion_task` |
| 19 | CH0 Saleae → `mpu_task` |

### Pipeline de tasks

```
mpu_task (100 Hz)
    │  xQueueMPU (mpu_data_t)
    ▼
fusion_task (orientação Fusion AHRS)
    ├──► xQueueUart (angle_t) ──► uart_task (printf roll/pitch/yaw)
    └──► xQueuePwm  (angle_t) ──► pwm_task  (PWM LED ∝ |pitch|)
```

### Prioridades (Single Core)

| Task | Prioridade | Stack (words) |
|---|---|---|
| `mpu_task` | 3 (maior) | 1024 |
| `fusion_task` | 2 | 4096 |
| `uart_task` | 1 | 2048 |
| `pwm_task` | 1 | 1024 |
| `stats_task` | 1 | 1024 |

### Dependências

- **Pico SDK** ≥ 2.2.0
- **FreeRTOS-Kernel** (submódulo)
- **Fusion** (xioTechnologies/Fusion — incluso em `Fusion/`)

---

## Seção 2 — Como medir com o Saleae Logic 2

### Setup

1. Conecte os canais do Saleae Logic 2:

   | Canal Saleae | GPIO Pico 2 | Task |
   |---|---|---|
   | CH0 | 19 | `mpu_task` |
   | CH1 | 18 | `fusion_task` |
   | CH2 | 17 | `uart_task` |
   | CH3 | 16 | `pwm_task` |

2. Configure o Saleae Logic 2:
   - **Sample Rate**: ≥ 10 MS/s (resolução de ~100 ns)
   - **Duração**: ≥ 10 s para capturar ≥ 1000 períodos a 100 Hz
   - Threshold digital: 1,65 V (padrão 3,3 V CMOS)

3. **Antes de medir**: comentar `#define ENABLE_STACK_STATS` em `main.c` para eliminar o `printf` periódico da `stats_task`, que polui o timing das demais tasks.

### Como interpretar os sinais

Cada GPIO sobe para HIGH no início do trabalho útil da task e volta para LOW ao terminar. O período em que o sinal está HIGH representa o tempo de execução daquele ciclo.

```
          ┌──┐   ┌───┐  ┌──┐
CH0 ──────┘  └───┘   └──┘  └───  (mpu_task: pulsos a ~100 Hz)
        │←──→│            largura = tempo de execução = candidato WCET
        │←────────→│      período entre subidas
```

### Definições adotadas

| Métrica | Definição |
|---|---|
| **WCET** | Maior largura de pulso HIGH observada em N ciclos (N ≥ 1000) |
| **Jitter** | `max(período_i) − min(período_i)` medido entre bordas de subida consecutivas |
| **Deadline Miss** | Período medido > deadline esperado (10 ms para tasks a 100 Hz) |
| **Deadline Miss Rate** | `n_misses / n_períodos × 100%` |
| **Stack Usage** | `(stack_alocado − high_water_mark) / stack_alocado × 100%` |

> O `high_water_mark` do FreeRTOS é o mínimo de words livres que a stack já teve — quanto menor, mais a stack foi usada.

### Exportar CSV do Saleae

Em Logic 2: **File → Export Data → Digital Data → CSV**. O arquivo terá colunas:
```
Time [s],Channel 0,Channel 1,Channel 2,Channel 3
```

### Analisar com o script Python

```bash
python tools/analyze_saleae.py capture.csv
python tools/analyze_saleae.py capture.csv --deadline 10,10,10,10
```

---

## Seção 3 — Tabelas de resultados

<!-- Stack high water mark: medir com ENABLE_STACK_STATS ativo e aguardar saída serial. -->

### Single Core (`configNUMBER_OF_CORES=1`)

| Métrica | `mpu_task` | `fusion_task` | `uart_task` | `pwm_task` |
|---|---|---|---|---|
| WCET (µs) | 430 | 24 | 72 | 4 |
| Jitter (µs) | 7,9 | 127,6 | 12,1 | ≈ 90 000 ⁽¹⁾ |
| Período médio (ms) | 9,999 | 9,999 | 9,999 | 11,32 ⁽¹⁾ |
| Deadline Miss Rate | ~0% | observado ⁽²⁾ | ~0% | 1 miss ⁽¹⁾ |
| Stack: alocado (words) | 1024 | 4096 | 2048 | 1024 |
| Stack: high water mark | TODO | TODO | TODO | TODO |
| Stack Usage (%) | TODO | TODO | TODO | TODO |

> ⁽¹⁾ **Anomalia `pwm_task`:** 1 período de ~100 ms detectado (fmin = 10 Hz). Causa provável: `stats_task` com `ENABLE_STACK_STATS` ativo fez `printf` durante a janela de medição, bloqueando o USB-CDC por ~100 ms e travando todas as tasks de prioridade 1. **Repetir medição com `ENABLE_STACK_STATS` comentado** para obter valores limpos.
>
> ⁽²⁾ **Deadline miss `fusion_task`:** período máximo observado = 10,062 ms (62 µs acima do deadline de 10 ms). Contagem exata requer análise do CSV com `tools/analyze_saleae.py`.

**Parâmetros da medição Single Core:**

| Canal Saleae | Task | N pulsos | ΔT (s) | fmean (Hz) | Tstd |
|---|---|---|---|---|---|
| CH0 | `mpu_task` | 305 | 3,059 | 100,001 | 0,40 µs |
| CH1 | `fusion_task` | 76 | 0,757 | 100,001 | 10,84 µs |
| CH2 | `uart_task` | 74 | 0,733 | 100,001 | 3,10 µs |
| CH3 | `pwm_task` | 69 | 0,780 | 88,31 ⁽¹⁾ | 10,91 ms ⁽¹⁾ |

### SMP — 2 cores (`configNUMBER_OF_CORES=2`, branch `feature/smp`)

| Métrica | `mpu_task` | `fusion_task` | `uart_task` | `pwm_task` |
|---|---|---|---|---|
| WCET (µs) | TODO | TODO | TODO | TODO |
| Jitter (µs) | TODO | TODO | TODO | TODO |
| Deadline Miss Rate | TODO | TODO | TODO | TODO |
| Stack: alocado (words) | TODO | TODO | TODO | TODO |
| Stack: high water mark | TODO | TODO | TODO | TODO |
| Stack Usage (%) | TODO | TODO | TODO | TODO |

**Afinidade de cores (SMP):**

| Task | Core |
|---|---|
| `mpu_task` | Core 0 |
| `fusion_task` | Core 0 |
| `uart_task` | Core 1 |
| `pwm_task` | Core 1 |

> Justificativa: `mpu_task` e `fusion_task` formam uma cadeia produtor-consumidor com dados de 12 bytes — mantê-las no mesmo core reduz latência de fila e evita transferência de dados entre caches. `uart_task` e `pwm_task` são tarefas de saída com menor exigência de latência e não compartilham estado com o par anterior.

---

## Seção 4 — Respostas das perguntas

### Pergunta 1 — Frequência máxima da `fusion_task`

A frequência máxima de operação de uma task é limitada pelo seu WCET:

```
f_max = 1 / WCET_fusion
```

Com WCET medido de **24 µs**:

```
f_max = 1 / (24 × 10⁻⁶) ≈ 41 667 Hz ≈ 41,7 kHz
```

A task está configurada a 100 Hz (10 ms). A utilização de CPU da `fusion_task` é:

```
U = WCET / período = 24 µs / 10 000 µs = 0,24%
```

Há headroom de ~417× antes de atingir o limite teórico. O gargalo real do sistema é a `mpu_task` (I²C a 400 kHz), cujo WCET de 430 µs representa 4,3% do período de 10 ms.

---

### Pergunta 2 — `SAMPLE_PERIOD = 0.1f` está correto?

**Resposta:** O valor `0.1f` **não** estaria correto.

`SAMPLE_PERIOD` é o intervalo de tempo em segundos entre amostras, usado pelo filtro AHRS para integrar a taxa angular do giroscópio:

```
orientação(t) = orientação(t-1) + ω × SAMPLE_PERIOD
```

- `SAMPLE_PERIOD = 0.1f` → 100 ms → 10 Hz. Mas a task lê a 100 Hz (a cada 10 ms).
- Resultado: o filtro "pensa" que cada amostra durou 100 ms quando na verdade durou 10 ms — **erro de escala 10× na integração do giroscópio**.
- Consequência prática: yaw acumula drift 10× mais rápido; roll e pitch convergem incorretamente.

**Este repositório usa `SAMPLE_PERIOD = 0.01f` (valor correto: 10 ms = 100 Hz).**

> Nota de auditoria: a versão encontrada no lab anterior (`pra-7-mpu`) já utilizava `0.01f`. O código foi preservado sem alteração e documentado aqui para registro.

---

### Pergunta 3 — Como otimizar a `uart_task`

A `uart_task` atual usa `printf`, que tem múltiplas ineficiências:

1. **Conversão de float para string** em tempo de execução (slow `ftoa`).
2. **Bloqueio no buffer USB CDC**: se o host não lê rápido o suficiente, `printf` bloqueia até o buffer drenar.
3. **Frequência desnecessariamente alta**: envia 1 pacote por amostra (100 Hz), mas o host raramente precisa de 100 Hz de texto.

**Otimizações possíveis (em ordem de impacto):**

| Otimização | Impacto |
|---|---|
| Reduzir frequência de envio (ex.: 10 Hz com decimation) | Reduz WCET e uso de CPU em ~10× |
| Usar formato binário (`memcpy` de 3 floats) | Elimina `ftoa`, reduz WCET em ~50% |
| Aumentar baudrate (UART física em vez de USB-CDC) | Reduz tempo de bloqueio no buffer |
| Buffer circular + envio em background (DMA ou IRQ) | Desacopla uart_task do tempo de transmissão |

Para este lab, a otimização de **decimation** (enviar a cada N=10 amostras) é a mais simples e eficaz:
```c
static int count = 0;
if (++count >= 10) {
    count = 0;
    printf(...);
}
```

---

### Pergunta 4 — Por que o jitter é baixo/alto

Resultados medidos (Single Core):

| Task | Jitter | Explicação |
|---|---|---|
| `mpu_task` | **7,9 µs** | `vTaskDelayUntil` compensa o tempo de execução; jitter residual vem da resolução do timer do RP2350 e da latência de ISR do tick |
| `fusion_task` | **127,6 µs** | Event-driven: depende de quando o scheduler a acorda após `mpu_task` publicar na fila. O jitter é ~16× maior porque `mpu_task` (prioridade 3) pode preemptá-la e atrasar o acordamento por até 1 tick |
| `uart_task` | **12,1 µs** | Também event-driven, mas o `printf` via USB-CDC é determinístico quando o buffer não está cheio; jitter baixo indica que o host estava lendo ativamente |
| `pwm_task` | **≈ 90 ms** | Dominado pelo evento anômalo de 100 ms (ver nota ⁽¹⁾ acima); sem a anomalia, jitter esperado similar a `uart_task` |

**Conclusão:** `mpu_task` tem o menor jitter por usar `vTaskDelayUntil` (periódico absoluto). As tasks event-driven têm jitter proporcional à latência de escalonação e à contenção de CPU com tasks de prioridade maior.

---

### Pergunta 5 — Jitter SMP vs Single Core

**TODO: preencher após medir com o Saleae em modo SMP.**

Análise esperada:

- Em SMP, `mpu_task` e `fusion_task` rodam no Core 0 sem competir com `uart_task`/`pwm_task` (Core 1) → redução do jitter para ambos os grupos.
- Possível **aumento de jitter** em `uart_task` se o mutex interno do USB CDC criar disputa entre cores (o stack USB roda em Core 0 no Pico SDK).
- Em geral, SMP reduz jitter das tasks de maior prioridade porque elimina preempção por tasks de menor prioridade em outros cores.

---

### Pergunta 6 — Deadline Miss

**TODO: preencher após medir.**

Análise:

- Se ocorrer deadline miss em `mpu_task`: investigar se o I²C está travado (timeout de `i2c_read_blocking`) ou se uma task de menor prioridade está segurando algum recurso (inversão de prioridade).
- Mitigações testadas: TODO.

---

### Pergunta 7 — Como o jitter foi medido

1. Captura com Saleae Logic 2 por ≥ 10 s a 10 MS/s.
2. Export: **File → Export Data → Digital Data → CSV**.
3. Script `tools/analyze_saleae.py` detecta bordas de subida de cada canal.
4. Para cada canal: `timestamps_rising[i+1] - timestamps_rising[i]` → lista de períodos.
5. Jitter = `max(períodos) - min(períodos)`.

Fórmula:
```
jitter = max({ T_i+1 - T_i | i = 1..N-1 }) - min({ T_i+1 - T_i | i = 1..N-1 })
```

---

### Pergunta 8 — Prioridade vs Afinidade de core

**TODO: preencher com dados comparativos.**

Análise esperada:

- **Prioridade** controla quem preempta quem em Single Core. Aumentar prioridade de `mpu_task` reduz seu jitter mas pode aumentar o jitter de tasks de baixa prioridade.
- **Afinidade** em SMP elimina a migração entre cores, reduzindo o custo de context switch e a disputa de cache L1. Para tarefas computacionalmente intensas (como `fusion_task`), a afinidade tende a ter impacto maior que a prioridade sozinha.
- Resultado empírico esperado: afinidade tem maior impacto em throughput; prioridade tem maior impacto em latência de resposta.

---

### Pergunta 9 — Regra dos 80% (Stack)

Stack alocado deve ser tal que o uso medido (`stack_alocado - high_water_mark`) fique ≤ 80% do total (sobra ≥ 20% de margem).

<!-- Preencher após medir high water mark com ENABLE_STACK_STATS ativo -->

| Task | Stack alocado (words) | High Water Mark (words livres) | Uso (words) | Uso (%) | Ajuste necessário? |
|---|---|---|---|---|---|
| `mpu_task` | 1024 | TODO | TODO | TODO | TODO |
| `fusion_task` | 4096 | TODO | TODO | TODO | TODO |
| `uart_task` | 2048 | TODO | TODO | TODO | TODO |
| `pwm_task` | 1024 | TODO | TODO | TODO | TODO |

**Fórmula:** `uso% = (stack_alocado - high_water_mark) / stack_alocado × 100`

**Critério:** se `uso% > 80%`, aumentar o stack. Se `uso% < 40%`, considerar reduzir para liberar heap.

---

## Seção 5 — Estrutura de pastas e como buildar

### Estrutura

```
26a-emb-pra-9-expert-joselsm3/
├── CMakeLists.txt           # Raiz CMake: SDK + Fusion + main
├── pico_sdk_import.cmake
├── pico_extras_import_optional.cmake
│
├── Fusion/                  # Biblioteca AHRS (xioTechnologies/Fusion)
│   ├── CMakeLists.txt
│   ├── Fusion.h
│   ├── FusionAhrs.[ch]
│   ├── FusionBias.[ch]
│   └── ...
│
├── main/
│   ├── CMakeLists.txt       # Executável pico_emb
│   ├── FreeRTOSConfig.h     # Configuração FreeRTOS (tick 1kHz, heap 128KB)
│   ├── main.c               # 4 tasks + instrumentação Saleae
│   ├── mpu6050.h            # Mapa de registradores MPU6050
│   └── pins.h               # Mapeamento de GPIOs
│
├── tools/
│   └── analyze_saleae.py    # Script de análise de métricas
│
├── FreeRTOS-Kernel/         # Submódulo FreeRTOS
└── pico-sdk/                # Submódulo Pico SDK
```

### Build

```bash
# Configurar (primeira vez)
cmake -B build -DCMAKE_BUILD_TYPE=Release

# Compilar
cmake --build build -j$(nproc)

# O binário gerado é:
build/pico_emb.uf2
```

Copiar `pico_emb.uf2` para o Pico 2 no modo BOOTSEL.

### Ativar/desativar `stats_task`

Em `main/main.c`, linha 1:
```c
// Ativo — imprime stack a cada 5s (usar para medir high water mark):
#define ENABLE_STACK_STATS

// Inativo — comentar antes de medir com o Saleae:
// #define ENABLE_STACK_STATS
```

### Branch SMP

```bash
git checkout feature/smp
```

O branch SMP difere do `main` em:
- `configNUMBER_OF_CORES=2` no `main/CMakeLists.txt`
- `xTaskCreate` substituído por `xTaskCreateAffinitySet` com afinidades definidas
