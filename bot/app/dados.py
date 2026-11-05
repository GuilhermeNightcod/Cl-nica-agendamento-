"""
Carrega especialidades e gera os horários (vagas) do semestre a partir das
planilhas da pasta `dados/` (arquivos .csv que abrem no Excel).

  * especialidades.csv  -> codigo;nome;descricao;ativa
  * grade_horarios.csv  -> especialidade;dia_semana;hora;vagas
  * feriados.csv        -> data;descricao   (dias sem atendimento)

Pode rodar quantas vezes quiser: não duplica nada.
"""
import csv
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Especialidade, Vaga

log = logging.getLogger("dados")
PASTA = Path(__file__).resolve().parent.parent / "dados"
DIAS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "sáb": 5, "dom": 6}


def _ler(nome: str) -> list[dict]:
    arq = PASTA / nome
    if not arq.exists():
        return []
    with open(arq, encoding="utf-8-sig") as f:
        amostra = f.read(2048)
        f.seek(0)
        sep = ";" if amostra.count(";") >= amostra.count(",") else ","
        return [{k.strip().lower(): (v or "").strip() for k, v in linha.items() if k} for linha in csv.DictReader(f, delimiter=sep)]


def carregar(s: Session, inicio: date | None = None, fim: date | None = None) -> dict:
    inicio = inicio or config.SEMESTRE_INICIO
    fim = fim or config.SEMESTRE_FIM

    esps: dict[str, Especialidade] = {e.codigo: e for e in s.scalars(select(Especialidade))}
    for l in _ler("especialidades.csv"):
        cod = l["codigo"].lower()
        e = esps.get(cod) or Especialidade(codigo=cod)
        e.nome = l["nome"]
        e.descricao = l.get("descricao", "")
        e.ativa = l.get("ativa", "sim").lower() not in ("nao", "não", "n", "0", "false")
        s.add(e)
        esps[cod] = e
    s.flush()

    feriados = {date.fromisoformat(l["data"]) if "-" in l["data"] else datetime.strptime(l["data"], "%d/%m/%Y").date()
                for l in _ler("feriados.csv") if l.get("data")}

    existentes = {(v.especialidade_id, v.inicio): v for v in s.scalars(select(Vaga).where(Vaga.inicio >= datetime.combine(inicio, time())))}
    criadas = atualizadas = 0
    for l in _ler("grade_horarios.csv"):
        e = esps.get(l["especialidade"].lower())
        dia = DIAS.get(l["dia_semana"].lower()[:3])
        if not e or dia is None:
            log.warning("Linha ignorada na grade (especialidade ou dia inválido): %s", l)
            continue
        h = time.fromisoformat(l["hora"].zfill(5))
        cap = int(l.get("vagas") or 1)
        d = inicio + timedelta(days=(dia - inicio.weekday()) % 7)
        while d <= fim:
            if d not in feriados:
                quando = datetime.combine(d, h)
                v = existentes.get((e.id, quando))
                if v is None:
                    v = Vaga(especialidade_id=e.id, inicio=quando, capacidade=cap)
                    s.add(v)
                    existentes[(e.id, quando)] = v
                    criadas += 1
                elif v.capacidade != cap:
                    v.capacidade = max(cap, v.ocupadas)
                    atualizadas += 1
            d += timedelta(days=7)
    return {"especialidades": len(esps), "vagas_criadas": criadas, "vagas_atualizadas": atualizadas}
