# HighLevelAnalyzer.py — Serial Monitor HLA para Saleae Logic 2
#
# Decodifica bytes UART em linhas de texto completas, com:
#   - Suporte a LF, CRLF e CR como terminadores configuráveis
#   - Filtro por substring (só exibe linhas que contenham o texto do filtro)
#   - Detecção de overflow de buffer (quando o terminador não chega)
#   - Tratamento de bytes inválidos (não-ASCII → '?')

from saleae.analyzers import (
    HighLevelAnalyzer,
    AnalyzerFrame,
    StringSetting,
    NumberSetting,
    ChoicesSetting,
)


class SerialMonitor(HighLevelAnalyzer):
    """
    High Level Analyzer que acumula bytes de um Async Serial e emite
    um AnalyzerFrame por linha completa detectada.

    Frames emitidos na timeline:
        'message'  — linha decodificada (texto completo sem terminador)
        'overflow' — quando o buffer atinge tamanho_maximo sem terminador
    """

    # ------------------------------------------------------------------
    # Configurações — aparecem como campos na UI do Logic 2
    # ------------------------------------------------------------------

    terminador = ChoicesSetting(
        label='Terminador de linha',
        choices=('LF (\\n)', 'CRLF (\\r\\n)', 'CR (\\r)'),
    )

    tamanho_maximo = NumberSetting(
        label='Tamanho máximo do buffer (bytes)',
        min_value=16,
        max_value=4096,
    )

    filtro = StringSetting(
        label='Filtro (substring; vazio = sem filtro)',
    )

    # ------------------------------------------------------------------
    # Tipos de frame → formato exibido na timeline do Logic 2
    # A sintaxe {{data.chave}} referencia o dict passado no AnalyzerFrame.
    # ------------------------------------------------------------------

    result_types = {
        'message': {
            'format': '{{data.text}}'
        },
        'overflow': {
            'format': 'BUFFER OVERFLOW'
        },
    }

    # Mapa: string da UI → bytes reais do terminador
    _TERMINADOR_MAP = {
        'LF (\\n)':      b'\n',
        'CRLF (\\r\\n)': b'\r\n',
        'CR (\\r)':      b'\r',
    }

    # ------------------------------------------------------------------
    # Inicialização
    # ------------------------------------------------------------------

    def __init__(self):
        """
        Chamado uma vez pelo Saleae ao criar a instância do analyzer.
        Converte as settings para os tipos internos e inicializa o buffer.
        """
        # Buffer de fragmentos bytes (1 byte cada) da linha em andamento
        self._buffer = []

        # Timestamp do primeiro byte da linha atual (start_time do frame)
        self._start_time = None

        # Converte escolha da UI para os bytes reais do terminador
        self._terminador = self._TERMINADOR_MAP.get(
            self.terminador, b'\n'
        )

        # NumberSetting devolve float; converte para int com fallback seguro
        try:
            self._max_size = int(self.tamanho_maximo)
        except (TypeError, ValueError):
            self._max_size = 256

        # StringSetting devolve str; strip para remover espaços acidentais
        self._filtro = str(self.filtro).strip() if self.filtro else ''

    # ------------------------------------------------------------------
    # decode() — chamado para cada byte/frame do Async Serial
    # ------------------------------------------------------------------

    def decode(self, frame: AnalyzerFrame):
        """
        Recebe um frame do analisador de baixo nível (Async Serial).

        Fluxo por byte:
          1. Ignora frames que não sejam tipo 'data'.
          2. Registra o start_time no primeiro byte da linha.
          3. Se o buffer já está cheio, emite overflow imediatamente.
          4. Adiciona o byte ao buffer.
          5. Se os bytes acumulados terminam com o terminador, emite
             o frame 'message' cobrindo desde o 1º byte até o terminador.

        O start_time e end_time do frame emitido cobrem toda a linha,
        do 1º byte útil até o último byte do terminador (inclusive).

        Retorna:
            None           — ainda acumulando, nada a exibir
            AnalyzerFrame  — linha completa ('message') ou overflow
        """
        # Só processa frames de dados UART normais
        if frame.type != 'data':
            return None

        # Extrai o byte recebido; .get com fallback seguro
        raw = frame.data.get('data', b'')
        if not raw:
            return None

        # Primeiro byte da linha: registra o timestamp de início
        if self._start_time is None:
            self._start_time = frame.start_time

        # Buffer cheio sem terminador → overflow antes de adicionar mais
        if len(self._buffer) >= self._max_size:
            return self._emitir_overflow(frame.end_time)

        # Acumula o byte
        self._buffer.append(raw)

        # Junta tudo e testa o terminador
        linha_bytes = b''.join(self._buffer)
        if linha_bytes.endswith(self._terminador):
            return self._emitir_mensagem(frame.end_time, linha_bytes)

        return None

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _emitir_mensagem(self, end_time, linha_bytes: bytes):
        """
        Decodifica os bytes acumulados, aplica o filtro e emite 'message'.

        Bytes não-ASCII são substituídos por '?' (errors='replace').
        O terminador é removido do texto exibido na timeline.

        Retorna None se o filtro não for satisfeito (sem emissão na timeline).
        """
        # Decodifica sem quebrar em bytes inválidos
        texto = linha_bytes.decode('ascii', errors='replace')

        # Remove o terminador (\r, \n ou ambos) do fim
        texto_limpo = texto.rstrip('\r\n')

        # Filtro por substring: se ativo e não encontrado, descarta silenciosamente
        if self._filtro and self._filtro not in texto_limpo:
            self._resetar_buffer()
            return None

        frame = AnalyzerFrame(
            'message',
            self._start_time,
            end_time,
            {'text': texto_limpo},
        )
        self._resetar_buffer()
        return frame

    def _emitir_overflow(self, end_time):
        """
        Emite um frame 'overflow' quando o buffer atingiu tamanho_maximo
        sem encontrar o terminador configurado.

        O texto interno registra o tamanho para facilitar diagnóstico,
        mas o que aparece na timeline é o formato definido em result_types
        ('BUFFER OVERFLOW').
        """
        n = len(self._buffer)
        frame = AnalyzerFrame(
            'overflow',
            self._start_time,
            end_time,
            {'text': f'OVERFLOW: {n} bytes sem terminador (max={self._max_size})'},
        )
        self._resetar_buffer()
        return frame

    def _resetar_buffer(self):
        """Descarta os bytes acumulados e o timestamp de início da linha."""
        self._buffer = []
        self._start_time = None
