"""Fila de processamento que preserva a ordem das mensagens de cada paciente."""
import logging
import queue
import threading
import zlib

log = logging.getLogger("fila")


class FilaPorPaciente:
    def __init__(self, funcao, trabalhadores: int = 4) -> None:
        self.funcao = funcao
        self.filas = [queue.Queue() for _ in range(trabalhadores)]
        for i, q in enumerate(self.filas):
            threading.Thread(target=self._rodar, args=(q,), daemon=True, name=f"fila-{i}").start()

    def adicionar(self, chave: str, item) -> None:
        # o mesmo paciente cai sempre na mesma fila (mesma thread) -> ordem garantida
        self.filas[zlib.crc32(chave.encode()) % len(self.filas)].put(item)

    def aguardar(self) -> None:
        for q in self.filas:
            q.join()

    def _rodar(self, q: queue.Queue) -> None:
        while True:
            item = q.get()
            try:
                self.funcao(item)
            except Exception:
                log.exception("Erro na fila")
            finally:
                q.task_done()
