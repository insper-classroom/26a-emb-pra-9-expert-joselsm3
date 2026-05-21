
if (NOT FREERTOS_KERNEL_PATH AND NOT DEFINED ENV{FREERTOS_KERNEL_PATH})
    message("Skipping FreeRTOS examples as FREERTOS_KERNEL_PATH not defined")
    return()
endif()

include(FreeRTOS_Kernel_import.cmake)

add_executable(pico_emb
    main.c
    )

target_include_directories(pico_emb PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}
    )

target_link_libraries(pico_emb PRIVATE
    pico_async_context_freertos
    FreeRTOS-Kernel-Heap4
    pico_stdlib
    hardware_i2c
    hardware_pwm
    hardware_gpio
    Fusion
    )

# SMP: 2 cores ativos. Core 0 = mpu+fusion, Core 1 = uart+pwm.
# Para voltar ao Single Core: trocar para configNUMBER_OF_CORES=1
target_compile_definitions(pico_emb PRIVATE
    configNUMBER_OF_CORES=2
    )

# Saida via USB-CDC (printf visivel no monitor serial)
pico_enable_stdio_usb(pico_emb 1)
pico_enable_stdio_uart(pico_emb 0)

pico_add_extra_outputs(pico_emb)

set_target_properties(pico_emb PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
