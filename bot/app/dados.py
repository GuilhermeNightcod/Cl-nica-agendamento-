"""
Carrega os dados iniciais das planilhas da pasta `dados/` (abrem no Excel).

  * especialidades.csv   -> codigo;nome;descricao;ativa;mostrar_no_bot
  * procedimentos.csv    -> especialidade;procedimento
  * sessoes_clinica.csv  -> grade das turmas (só é importada se o sistema ainda não
                            tiver nenhuma sessão; depois disso use a tela "Clínicas")
  * feriados.csv         -> data;descricao  (dias sem atendimento)

Pode rodar quantas vezes quiser: não duplica nada.
"""
import csv
import logging
from datetime import date, datetime, time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agenda import gerar_vagas
from .models import EspacoClinico, Especialidade, Etiqueta, Procedimento, SessaoClinica, Setor

log = logging.getLogger("dados")
PASTA = Path(__file__).resolve().parent.parent / "dados"
DIAS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "sáb": 5, "dom": 6}
NAO = ("nao", "não", "n", "0", "false")


def _ler(nome: str) -> list[dict]:
    arq = PASTA / nome
    if not arq.exists():
        return []
    with open(arq, encoding="utf-8-sig") as f:
        amostra = f.read(2048)
        f.seek(0)
        sep = ";" if amostra.count(";") >= amostra.count(",") else ","
        return [
            {k.strip().lower(): (v or "").strip() for k, v in linha.items() if k}
            for linha in csv.DictReader(f, delimiter=sep)
        ]


def _data(txt: str) -> date:
    return date.fromisoformat(txt) if "-" in txt else datetime.strptime(txt, "%d/%m/%Y").date()


def _int(txt: str) -> int | None:
    return int(txt) if txt and txt.strip().isdigit() else None


def feriados() -> set[date]:
    return {_data(l["data"]) for l in _ler("feriados.csv") if l.get("data")}


def carregar(s: Session) -> dict:
    esps: dict[str, Especialidade] = {e.codigo: e for e in s.scalars(select(Especialidade))}
    for l in _ler("especialidades.csv"):
        cod = l["codigo"].lower()
        e = esps.get(cod) or Especialidade(codigo=cod)
        e.nome = l["nome"]
        e.descricao = l.get("descricao", "")
        e.ativa = l.get("ativa", "sim").lower() not in NAO
        e.mostrar_no_bot = l.get("mostrar_no_bot", "sim").lower() not in NAO
        s.add(e)
        esps[cod] = e
    s.flush()

    existentes = {(p.especialidade_id, p.nome.lower()) for p in s.scalars(select(Procedimento))}
    for l in _ler("procedimentos.csv"):
        e = esps.get(l["especialidade"].lower())
        if e and (e.id, l["procedimento"].lower()) not in existentes:
            s.add(Procedimento(especialidade_id=e.id, nome=l["procedimento"]))
            existentes.add((e.id, l["procedimento"].lower()))

    setores = {x.nome: x for x in s.scalars(select(Setor))}
    for l in _ler("setores.csv"):
        x = setores.get(l["nome"]) or Setor(nome=l["nome"])
        x.cor = l.get("cor") or x.cor or "#0f5c8c"
        x.padrao = l.get("padrao", "nao").lower() not in NAO
        s.add(x)
        setores[x.nome] = x
    if not setores:
        s.add(Setor(nome="Recepção", padrao=True))
    etiquetas = {x.nome for x in s.scalars(select(Etiqueta))}
    for l in _ler("etiquetas.csv"):
        if l["nome"] not in etiquetas:
            s.add(Etiqueta(nome=l["nome"], cor=l.get("cor") or "#6b7280"))
            etiquetas.add(l["nome"])

    espacos = {x.nome: x for x in s.scalars(select(EspacoClinico))}
    for l in _ler("espacos.csv"):
        if l["nome"] not in espacos:
            espacos[l["nome"]] = EspacoClinico(nome=l["nome"], boxes=_int(l.get("boxes", "")))
            s.add(espacos[l["nome"]])
    s.flush()

    importadas = 0
    if not s.scalar(select(func.count(SessaoClinica.id))):
        for l in _ler("sessoes_clinica.csv"):
            dia = DIAS.get(l["dia_semana"].lower()[:3])
            areas = [esps[c.strip().lower()] for c in l["especialidades"].split(",") if c.strip().lower() in esps]
            if dia is None or not areas:
                log.warning("Sessão ignorada (dia ou especialidade inválidos): %s", l)
                continue
            s.add(
                SessaoClinica(
                    turma=l["turma"],
                    nome=l.get("nome_clinica", ""),
                    dia_semana=dia,
                    hora_inicio=time.fromisoformat(l["inicio"].zfill(5)),
                    hora_fim=time.fromisoformat(l["fim"].zfill(5)),
                    professor=l.get("professor", ""),
                    procedimentos_texto=l.get("procedimentos", ""),
                    vagas=_int(l.get("vagas", "")) or 10,
                    idade_min=_int(l.get("idade_min", "")),
                    idade_max=_int(l.get("idade_max", "")),
                    especialidades=areas,
                    espaco=espacos.get(l.get("espaco", "")),
                    alunos=_int(l.get("alunos", "")),
                    pacientes_por_dupla=_int(l.get("pacientes_por_dupla", "")) or 1,
                    alunos_por_box=_int(l.get("alunos_por_box", "")) or 2,
                )
            )
            s.flush()
        for se in s.scalars(select(SessaoClinica)):
            se.recalcular_vagas()
            importadas += 1
        s.flush()

    return {"especialidades": len(esps), "sessoes_importadas": importadas, **gerar_vagas(s, feriados())}
