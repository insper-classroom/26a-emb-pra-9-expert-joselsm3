# Serial Monitor — High Level Analyzer para Saleae Logic 2

Extensão HLA que decodifica bytes UART em linhas de texto completas,
com filtro por substring e detecção de overflow de buffer.

## Como carregar no Logic 2 (modo desenvolvimento)

1. Abra o **Saleae Logic 2**.
2. Menu superior → **Extensions** (ícone de puzzle).
3. Clique em **Load Existing Extension…**
4. Navegue até esta pasta (`tools/serial-monitor-hla/`) e selecione o arquivo `extension.json`.
5. A extensão aparece listada como **SerialMonitor** na aba de Extensions.

> Após editar o `.py`, clique em **Reload** na extensão (sem precisar reiniciar o Logic).

## Como usar com um Async Serial

1. Adicione um analisador **Async Serial** no canal da UART (configure baud rate, bits, paridade).
2. Clique em **+ Add High Level Analyzer** → selecione **SerialMonitor**.
3. Em **Input Analyzer**, escolha o Async Serial criado no passo anterior.
4. Configure os parâmetros:

   | Parâmetro | Descrição | Default sugerido |
   |---|---|---|
   | Terminador de linha | LF, CRLF ou CR | `LF (\n)` |
   | Tamanho máximo do buffer | Bytes antes de forçar overflow | `256` |
   | Filtro | Substring obrigatória (vazio = tudo) | _(vazio)_ |

5. Execute a captura. Na timeline aparecem blocos:
   - **Texto da linha** — para cada `\n` (ou terminador) recebido
   - **BUFFER OVERFLOW** — se o buffer encheu sem terminador

### Exemplo com este lab

Para monitorar a saída da `uart_task` (que envia `roll=X.XX pitch=Y.YY yaw=Z.ZZ\n`):

- Terminador: `LF (\n)`
- Filtro: `roll=` (só mostra linhas de orientação)
- Tamanho máximo: `128` (a string tem ~35 bytes)

## Melhorias futuras

| Melhoria | Descrição |
|---|---|
| Timestamp por mensagem | Adicionar `start_time` e `end_time` em segundos no campo `data` para referência |
| Exportação CSV | Salvar todas as mensagens capturadas em arquivo CSV via script externo |
| Suporte a binário | Modo hex dump para protocolos binários (ex: protocolo mouse do lab anterior) |
| Contagem de linhas | Campo `data.line_number` incrementado por linha, útil para depurar drops |
| Timeout de linha | Emitir frame parcial se nenhum byte chegar por N ms (linha truncada) |
| Colorização | Usar tipos de frame diferentes por prefixo (`roll=`, `ERROR:`, etc.) para cores distintas na timeline |
