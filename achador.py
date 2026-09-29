# -*- coding: utf-8 -*-
"""
Achador de Licitacoes/Dispensas em Aberto — PNCP
===================================================
Consulta a API publica do Portal Nacional de Contratacoes Publicas (PNCP)
e gera um relatorio (HTML + planilha) com as contratacoes que ainda estao
com periodo de recebimento de propostas ABERTO nos proximos dias.

Fonte oficial (publica, sem chave/login):
https://pncp.gov.br/api/consulta/swagger-ui/index.html

Pensado para rodar automaticamente via GitHub Actions (ver
.github/workflows/achador.yml) e publicar em GitHub Pages, mas roda
igualmente bem na sua maquina: python achador.py
"""

import csv
import html
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

# ======================= CONFIGURACAO =======================
# Edite esta secao com o que interessa para a sua empresa.

# Ate quantos dias a frente olhar (janela de propostas abertas).
# Pode deixar generoso aqui: o filtro fino de periodo agora e feito na
# propria pagina (o visitante escolhe o intervalo que quiser).
DIAS_A_FRENTE = 30

# Esferas: F=Federal, E=Estadual, M=Municipal, D=Distrital
ESFERAS_DESEJADAS = {"F", "E", "M"}

# UFs de interesse. Vazio [] = Brasil todo (sem filtro de UF).
UFS_DESEJADAS = ["RJ"]

# Modalidades a consultar (a API exige uma consulta por modalidade).
# Deixei aqui as modalidades mais relevantes para fornecimento de materiais/
# servicos a orgaos publicos. A escolha de QUAL modalidade ver fica na
# propria pagina (checkboxes) -- isto aqui so controla o que e BUSCADO.
# 4 Concorrencia-Eletr | 5 Concorrencia-Presencial | 6 Pregao-Eletronico
# 7 Pregao-Presencial | 8 Dispensa de Licitacao | 9 Inexigibilidade
# 12 Credenciamento
MODALIDADES = [4, 5, 6, 7, 8, 9, 12]

# Palavras-chave que devem aparecer no objeto da compra (case-insensitive).
# Vazio [] = traz tudo que bater esfera/UF/modalidade (pode vir muita coisa).
PALAVRAS_CHAVE = []  # ex.: ["material de escritorio", "epi", "informatica"]

TAMANHO_PAGINA = 50  # max 500 (limite da API)

# ======================= FIM CONFIGURACAO =======================

BASE_URL = "https://pncp.gov.br/api/consulta/v1"

NOMES_MODALIDADE = {
    1: "Leilão - Eletrônico", 2: "Diálogo Competitivo", 3: "Concurso",
    4: "Concorrência - Eletrônica", 5: "Concorrência - Presencial",
    6: "Pregão - Eletrônico", 7: "Pregão - Presencial",
    8: "Dispensa de Licitação", 9: "Inexigibilidade",
    10: "Manifestação de Interesse", 11: "Pré-qualificação",
    12: "Credenciamento", 13: "Leilão - Presencial",
}

TZ_BR = timezone(timedelta(hours=-3))

UFS_BRASIL = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
]

ESFERAS_NOMES = {"F": "Federal", "E": "Estadual", "M": "Municipal", "D": "Distrital"}


def _sem_acentos(texto):
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn"
    ).lower().strip()


def codigo_modalidade(item):
    """Identifica a modalidade pelo CODIGO numerico devolvido pela API
    (modalidadeId). So se esse campo faltar, tenta reconhecer pelo nome
    (ignorando acentos/maiusculas) — isso evita perder, por exemplo, as
    dispensas quando a API chama a modalidade 8 de 'Dispensa' em vez de
    'Dispensa de Licitacao'."""
    consultada = item.get("_cod_mod")
    if consultada is not None:
        return int(consultada)
    mid = item.get("modalidadeId")
    if mid not in (None, ""):
        try:
            return int(mid)
        except (TypeError, ValueError):
            pass
    nome = _sem_acentos(item.get("modalidadeNome"))
    if nome.startswith("dispensa"):
        return 8
    for codigo, nome_oficial in NOMES_MODALIDADE.items():
        if _sem_acentos(nome_oficial) == nome:
            return codigo
    return None


def consultar_modalidade(codigo_modalidade, data_final, uf=None):
    """Busca todas as paginas de uma modalidade na API de propostas abertas."""
    registros = []
    pagina = 1
    while True:
        params = {
            "dataFinal": data_final,
            "codigoModalidadeContratacao": codigo_modalidade,
            "pagina": pagina,
            "tamanhoPagina": TAMANHO_PAGINA,
        }
        if uf:
            params["uf"] = uf

        resp = None
        ultima_excecao = None
        for tentativa in range(8):
            try:
                resp = requests.get(
                    f"{BASE_URL}/contratacoes/proposta",
                    params=params,
                    timeout=60,
                    headers={"User-Agent": "achador-licitacoes/1.0 (uso pessoal, PNCP publico)"},
                )
            except requests.exceptions.RequestException as erro:
                ultima_excecao = erro
                espera = 10 * (tentativa + 1)
                print(f"  (erro de rede ({erro.__class__.__name__}) — esperando {espera}s e tentando de novo...)")
                time.sleep(espera)
                continue

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                espera = 8 * (tentativa + 1)
                print(f"  (PNCP respondeu com erro {resp.status_code} — esperando {espera}s e tentando de novo...)")
                time.sleep(espera)
                continue
            break
        else:
            raise ultima_excecao or RuntimeError("Falha ao consultar a API do PNCP após várias tentativas.")

        if resp.status_code == 204:
            break
        resp.raise_for_status()

        dados = resp.json()
        lote = dados.get("data", [])
        registros.extend(lote)

        total_paginas = dados.get("totalPaginas", 1)
        print(f"  modalidade {codigo_modalidade} uf={uf or 'BR'} "
              f"— pagina {pagina}/{total_paginas} ({len(lote)} registros)")

        if pagina >= total_paginas:
            break
        pagina += 1
        time.sleep(1.5)

    return registros


def bate_filtros(item):
    esfera = (item.get("orgaoEntidade") or {}).get("esferaId")
    if ESFERAS_DESEJADAS and esfera not in ESFERAS_DESEJADAS:
        return False

    if PALAVRAS_CHAVE:
        objeto = (item.get("objetoCompra") or "").lower()
        if not any(p.lower() in objeto for p in PALAVRAS_CHAVE):
            return False

    return True


def linha(item):
    orgao = item.get("orgaoEntidade") or {}
    unidade = item.get("unidadeOrgao") or {}
    cod_mod = codigo_modalidade(item)
    return {
        "modalidade_id": cod_mod,
        "modalidade": NOMES_MODALIDADE.get(cod_mod) or item.get("modalidadeNome"),
        "situacao": item.get("situacaoCompraNome"),
        "esfera": orgao.get("esferaId"),
        "orgao": orgao.get("razaosocial"),
        "uasg_codigo": unidade.get("codigoUnidade"),
        "uasg_nome": unidade.get("nomeUnidade"),
        "uf": unidade.get("ufSigla"),
        "municipio": unidade.get("municipioNome"),
        "objeto": item.get("objetoCompra") or "",
        "valor": item.get("valorTotalEstimado"),
        "abertura": item.get("dataAberturaProposta"),
        "encerramento": item.get("dataEncerramentoProposta"),
        "numero_pncp": item.get("numeroControlePNCP"),
        "link": item.get("linkSistemaOrigem"),
        "srp": item.get("srp"),  # True/False/None (None = a API nao informou)
        "modo_disputa": item.get("modoDisputaNome") or "",
        "orgao_cnpj": orgao.get("cnpj") or "",
    }


def coletar():
    data_final = (datetime.now(TZ_BR) + timedelta(days=DIAS_A_FRENTE)).strftime("%Y%m%d")
    ufs = UFS_DESEJADAS if UFS_DESEJADAS else [None]

    todos = []
    for modalidade in MODALIDADES:
        for uf in ufs:
            print(f"Consultando {NOMES_MODALIDADE.get(modalidade, modalidade)} / UF={uf or 'BR'}...")
            lote = consultar_modalidade(modalidade, data_final, uf)
            for item in lote:
                # a consulta e feita uma modalidade por vez: guardamos qual foi
                item["_cod_mod"] = modalidade
            todos.extend(lote)

    filtrados = [linha(r) for r in todos if bate_filtros(r)]
    filtrados.sort(key=lambda r: r["encerramento"] or "")

    # Resumo de diagnostico (aparece no log do GitHub Actions)
    print("\n=== RESUMO POR MODALIDADE (brutos da API -> apos filtros) ===")
    for cod in MODALIDADES:
        brutos = [r for r in todos if codigo_modalidade(r) == cod]
        mantidos = [r for r in filtrados if r["modalidade_id"] == cod]
        por_esfera = {}
        for r in brutos:
            esf = (r.get("orgaoEntidade") or {}).get("esferaId") or "?"
            por_esfera[esf] = por_esfera.get(esf, 0) + 1
        print(f"  {cod:>2} {NOMES_MODALIDADE.get(cod, '?'):<28} {len(brutos):>4} -> {len(mantidos):>4}   esferas na API: {por_esfera}")
    sem_codigo = [r for r in todos if codigo_modalidade(r) is None]
    if sem_codigo:
        print(f"  (!) {len(sem_codigo)} registro(s) com modalidade nao reconhecida")
    return filtrados


def gerar_csv(linhas, caminho="oportunidades_abertas.csv"):
    if not linhas:
        return
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=linhas[0].keys())
        writer.writeheader()
        writer.writerows(linhas)
    print(f"CSV gerado: {caminho}")


def fmt_valor(v):
    if v is None:
        return "-"
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(v)


def fmt_data(v):
    if not v:
        return "-"
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return v


def link_pncp(numero_controle_pncp):
    """A partir do numero de controle PNCP (mascara cnpj-1-sequencial/ano),
    monta o link publico da pagina do edital no site do PNCP, onde ficam
    disponiveis para download o Aviso, o Edital, o TR, o ETP e demais
    anexos daquela contratacao."""
    if not numero_controle_pncp:
        return None
    m = re.match(r"^(\d{14})-\d+-(\d+)/(\d{4})$", numero_controle_pncp)
    if not m:
        return None
    cnpj, sequencial, ano = m.groups()
    return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{int(sequencial)}"


def gerar_html(linhas, caminho="docs/index.html"):
    import json

    agora = datetime.now(TZ_BR).strftime("%d/%m/%Y às %H:%M")
    total = len(linhas)
    resumo_ufs = ", ".join(UFS_DESEJADAS) if UFS_DESEJADAS else "Brasil (todas as UFs)"

    # Prepara os dados para o navegador: datas/valores ja formatados, mas
    # tambem a data crua (AAAA-MM-DD) para o filtro de periodo funcionar.
    registros_js = []
    for r in linhas:
        esfera_nome = {"F": "Federal", "E": "Estadual", "M": "Municipal", "D": "Distrital"}.get(
            r["esfera"], r["esfera"] or "-"
        )
        enc = r["encerramento"] or ""
        registros_js.append({
            "modalidade": r["modalidade"] or "-",
            "modalidade_id": str(r["modalidade_id"]) if r.get("modalidade_id") is not None else "",
            "esfera": esfera_nome,
            "esferaRaw": r["esfera"] or "",
            "orgao": r["orgao"] or "-",
            "uasg_codigo": r.get("uasg_codigo") or "",
            "uasg_nome": r.get("uasg_nome") or "",
            "municipio": r["municipio"] or "",
            "uf": r["uf"] or "",
            "objeto": r["objeto"] or "",
            "valor_num": r["valor"] if isinstance(r["valor"], (int, float)) else None,
            "valor_fmt": fmt_valor(r["valor"]),
            "encerramento_data": enc[:10] if enc else "",  # AAAA-MM-DD, para o filtro
            "encerramento_fmt": fmt_data(enc),
            "link": r["link"] or "",
            "portal_link": link_pncp(r.get("numero_pncp")) or "",
            "srp": "Sim" if r.get("srp") is True else ("Não" if r.get("srp") is False else ""),
            "modo_disputa": r.get("modo_disputa") or "",
            "orgao_cnpj": r.get("orgao_cnpj") or "",
            "numero_pncp": r.get("numero_pncp") or "",
        })

    # Lista de modalidades exibidas como checkbox: TODAS as configuradas
    # (mesmo que hoje nao tenha vindo nenhum resultado dela) + as que
    # aparecerem nos dados. Assim, por exemplo, "Dispensa" nunca some da tela.
    codigos_lista = sorted(
        set(MODALIDADES) | {int(r["modalidade_id"]) for r in registros_js if r["modalidade_id"]}
    )
    modalidades_lista = [
        {"codigo": str(c), "nome": NOMES_MODALIDADE.get(c, f"Modalidade {c}")} for c in codigos_lista
    ]
    modalidades_json = json.dumps(modalidades_lista, ensure_ascii=False)
    dados_json = json.dumps(registros_js, ensure_ascii=False)
    nome_modalidade_json = json.dumps(
        {str(k): v for k, v in NOMES_MODALIDADE.items()}, ensure_ascii=False
    )
    ufs_json = json.dumps(UFS_DESEJADAS, ensure_ascii=False)
    todas_ufs_json = json.dumps(UFS_BRASIL, ensure_ascii=False)
    esferas_json = json.dumps(sorted(ESFERAS_DESEJADAS), ensure_ascii=False)
    esferas_nomes_json = json.dumps(ESFERAS_NOMES, ensure_ascii=False)
    palavras_json = json.dumps(PALAVRAS_CHAVE, ensure_ascii=False)

    page = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Achador de Licitações — atualizado {agora}</title>
<style>
  :root {{
    --bg: #f7f7f8; --card: #ffffff; --text: #1a1a1a; --muted: #666;
    --accent: #0a5f38; --border: #e4e4e4;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #111214; --card: #1b1c1e; --text: #f0f0f0; --muted: #999; --border: #2c2d30; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 1.5rem; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.2rem; }}
  .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 1.2rem; }}
  .filtros {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 1rem 1.2rem; margin-bottom: 1.2rem; display: flex; flex-wrap: wrap; gap: 1.4rem; align-items: flex-start;
  }}
  .filtros fieldset {{ border: none; padding: 0; margin: 0; min-width: 180px; }}
  .filtros legend {{ font-weight: 600; font-size: 0.85rem; margin-bottom: 0.4rem; padding: 0; }}
  .filtros label {{ display: block; font-size: 0.85rem; margin: 0.15rem 0; cursor: pointer; }}
  .filtros input[type="date"] {{
    padding: 0.35rem 0.5rem; border-radius: 6px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 0.85rem;
  }}
  .filtros .campo-data {{ display: flex; flex-direction: column; gap: 0.4rem; }}
  .grade-uf {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.1rem 0.6rem;
    max-height: 130px; overflow-y: auto; padding-right: 0.4rem; min-width: 220px;
  }}
  .grade-uf label {{ margin: 0.1rem 0; }}
  .filtros input[type="text"] {{
    padding: 0.4rem 0.6rem; border-radius: 6px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 0.85rem; width: 220px;
  }}
  .filtros button {{
    padding: 0.5rem 1rem; border-radius: 8px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); cursor: pointer; font-size: 0.85rem; height: fit-content;
  }}
  #botaoAoVivo {{ background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600; }}
  #botaoAoVivo:disabled {{ opacity: 0.6; cursor: wait; }}
  .acoes-topo {{ display: flex; flex-direction: column; gap: 0.5rem; margin-left: auto; }}
  #statusAoVivo {{ font-size: 0.8rem; color: var(--muted); max-width: 260px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th, td {{ padding: 0.7rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }}
  th {{ background: var(--bg); font-weight: 600; position: sticky; top: 0; }}
  tr:last-child td {{ border-bottom: none; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; background: var(--accent); color: #fff; font-size: 0.72rem; margin-bottom: 2px; }}
  .badge.esfera {{ background: #555; }}
  small {{ color: var(--muted); }}
  a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
  a.doc {{ color: var(--muted); font-weight: 500; }}
  .badge.srp {{ background: #b8860b; }}
  .btn-itens {{
    font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 6px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); cursor: pointer;
  }}
  .itens-resultado {{ margin-top: 0.3rem; max-width: 260px; }}
  .empty {{ padding: 2rem; text-align: center; color: var(--muted); }}
  .wrap {{ overflow-x: auto; }}
  #contador {{ font-weight: 600; }}
</style>
</head>
<body>
  <h1>📋 Achador de Licitações e Dispensas</h1>
  <div class="meta">
    Atualizado em <span id="atualizadoEm">{agora} (horário de Brasília)</span> · <span id="totalColetado">{total}</span> oportunidade(s) coletadas ·
    Esfera(s): {', '.join(sorted(ESFERAS_DESEJADAS))} · UF(s): {resumo_ufs}
  </div>

  <div class="filtros">
    <fieldset>
      <legend>Modalidade</legend>
      <div id="filtroModalidade"></div>
    </fieldset>
    <fieldset>
      <legend>Esfera</legend>
      <div id="filtroEsfera"></div>
    </fieldset>
    <fieldset>
      <legend>Estado (UF)</legend>
      <div id="filtroUf" class="grade-uf"></div>
    </fieldset>
    <fieldset>
      <legend>Encerramento da proposta</legend>
      <div class="campo-data">
        <label>De: <input type="date" id="dataDe"></label>
        <label>Até: <input type="date" id="dataAte"></label>
      </div>
    </fieldset>
    <fieldset>
      <legend>Palavra-chave no objeto</legend>
      <input type="text" id="buscaTexto" placeholder="ex: material de escritório, epi...">
      <div class="meta" style="margin:0.3rem 0 0">Separe por vírgula para buscar mais de um termo</div>
    </fieldset>
    <fieldset>
      <legend>Nome do órgão comprador</legend>
      <input type="text" id="buscaOrgao" placeholder="ex: prefeitura de niterói">
    </fieldset>
    <fieldset>
      <legend>Valor estimado (R$)</legend>
      <div class="campo-data">
        <label>Mín: <input type="number" id="valorMin" min="0" step="100" placeholder="0"></label>
        <label>Máx: <input type="number" id="valorMax" min="0" step="100" placeholder="sem limite"></label>
      </div>
    </fieldset>
    <fieldset>
      <legend>Registro de Preço (SRP)</legend>
      <div id="filtroSrp"></div>
    </fieldset>
    <fieldset>
      <legend>Modo de disputa</legend>
      <div id="filtroModoDisputa"></div>
    </fieldset>
    <button id="limparFiltros">Limpar filtros</button>
    <div class="acoes-topo">
      <button id="botaoAoVivo">🔄 Buscar agora com esses filtros</button>
      <div id="statusAoVivo"></div>
    </div>
  </div>

  <div class="meta" id="resumoModalidades"></div>
  <div class="meta">Mostrando <span id="contador">{total}</span> de <span id="totalMostrado">{total}</span> oportunidade(s)</div>

  <div class="card wrap">
    <table>
      <thead>
        <tr><th>Encerra em</th><th>Modalidade</th><th>Órgão / UASG</th><th>Objeto</th><th>Valor estimado</th><th>Ações</th></tr>
      </thead>
      <tbody id="corpoTabela"></tbody>
    </table>
    <div id="vazio" class="empty" style="display:none">Nenhuma oportunidade com os filtros escolhidos.</div>
  </div>

<script>
  const DADOS = {dados_json};
  const MODALIDADES = {modalidades_json};                // [{{"codigo": "8", "nome": "Dispensa de Licitação"}}, ...]
  const NOME_MODALIDADE = {nome_modalidade_json};       // {{"6": "Pregão - Eletrônico", ...}}
  const UFS = {ufs_json};
  const TODAS_UFS = {todas_ufs_json};
  const ESFERAS = {esferas_json};
  const NOME_ESFERA = {esferas_nomes_json};
  const PALAVRAS = {palavras_json};
  const DIAS_A_FRENTE_PADRAO = {DIAS_A_FRENTE};

  function escapeHtml(s) {{
    const d = document.createElement('div');
    d.textContent = s == null ? '' : s;
    return d.innerHTML;
  }}

  // Monta os checkboxes de modalidade. O valor de cada checkbox e o CODIGO
  // numerico da modalidade (nao o nome), para nao depender de como a API
  // escreve o nome (ex.: "Dispensa" x "Dispensa de Licitação").
  const filtroModalidadeEl = document.getElementById('filtroModalidade');
  MODALIDADES.forEach((m, i) => {{
    const id = 'mod_' + i;
    const label = document.createElement('label');
    label.innerHTML = `<input type="checkbox" class="chk-modalidade" value="${{escapeHtml(m.codigo)}}" id="${{id}}" checked> ${{escapeHtml(m.nome)}}`;
    filtroModalidadeEl.appendChild(label);
  }});

  // Checkboxes de esfera (as configuradas no robo vem marcadas)
  const filtroEsferaEl = document.getElementById('filtroEsfera');
  ['F', 'E', 'M', 'D'].forEach((esf, i) => {{
    const label = document.createElement('label');
    label.innerHTML = `<input type="checkbox" class="chk-esfera" value="${{esf}}" id="esf_${{i}}" ${{ESFERAS.includes(esf) ? 'checked' : ''}}> ${{NOME_ESFERA[esf]}}`;
    filtroEsferaEl.appendChild(label);
  }});

  // Monta os checkboxes de UF (todas as 27 unidades federativas; as
  // configuradas no robo vem pre-marcadas, as demais ficam disponiveis
  // para quem quiser ampliar a busca ao vivo para outros estados)
  const filtroUfEl = document.getElementById('filtroUf');
  const ufsPadrao = UFS.length ? UFS : TODAS_UFS;
  TODAS_UFS.forEach((uf, i) => {{
    const id = 'uf_' + i;
    const marcado = ufsPadrao.includes(uf);
    const label = document.createElement('label');
    label.innerHTML = `<input type="checkbox" class="chk-uf" value="${{uf}}" id="${{id}}" ${{marcado ? 'checked' : ''}}> ${{uf}}`;
    filtroUfEl.appendChild(label);
  }});

  const buscaTextoEl = document.getElementById('buscaTexto');
  buscaTextoEl.value = PALAVRAS.join(', ');
  const buscaOrgaoEl = document.getElementById('buscaOrgao');
  const valorMinEl = document.getElementById('valorMin');
  const valorMaxEl = document.getElementById('valorMax');

  // Checkboxes de SRP (Sim / Não / Não informado — a API nem sempre publica)
  const filtroSrpEl = document.getElementById('filtroSrp');
  ['Sim', 'Não', 'Não informado'].forEach((op, i) => {{
    const label = document.createElement('label');
    label.innerHTML = `<input type="checkbox" class="chk-srp" value="${{op === 'Não informado' ? '' : op}}" id="srp_${{i}}" checked> ${{op}}`;
    filtroSrpEl.appendChild(label);
  }});

  // Checkboxes de modo de disputa: a lista de opcoes depende do que existe
  // nos dados carregados no momento, entao e reconstruida sempre que os
  // dados mudam (carga inicial e apos cada busca ao vivo).
  const filtroModoEl = document.getElementById('filtroModoDisputa');
  function construirFiltroModoDisputa() {{
    const marcados = new Set(Array.from(document.querySelectorAll('.chk-modo:checked')).map(c => c.value));
    const jaExistia = filtroModoEl.children.length > 0;
    const modos = Array.from(new Set(DADOS.map(r => r.modo_disputa).filter(Boolean))).sort();
    filtroModoEl.innerHTML = '';
    modos.forEach((m, i) => {{
      const marcar = jaExistia ? marcados.has(m) : true;
      const label = document.createElement('label');
      label.innerHTML = `<input type="checkbox" class="chk-modo" value="${{escapeHtml(m)}}" id="modo_${{i}}" ${{marcar ? 'checked' : ''}}> ${{escapeHtml(m)}}`;
      filtroModoEl.appendChild(label);
      label.querySelector('input').addEventListener('change', render);
    }});
    if (modos.length === 0) {{
      filtroModoEl.innerHTML = '<span class="meta">Nenhuma modalidade com modo de disputa nos dados atuais (ex.: dispensa não tem)</span>';
    }}
  }}

  const corpoTabela = document.getElementById('corpoTabela');
  const contador = document.getElementById('contador');
  const totalMostrado = document.getElementById('totalMostrado');
  const totalColetado = document.getElementById('totalColetado');
  const vazioEl = document.getElementById('vazio');
  const dataDeEl = document.getElementById('dataDe');
  const dataAteEl = document.getElementById('dataAte');
  const statusEl = document.getElementById('statusAoVivo');
  const botaoAoVivo = document.getElementById('botaoAoVivo');

  function modalidadesSelecionadas() {{
    return Array.from(document.querySelectorAll('.chk-modalidade:checked')).map(c => c.value);
  }}
  function esferasSelecionadas() {{
    return Array.from(document.querySelectorAll('.chk-esfera:checked')).map(c => c.value);
  }}
  function ufsSelecionadas() {{
    return Array.from(document.querySelectorAll('.chk-uf:checked')).map(c => c.value);
  }}
  function palavrasChave() {{
    return buscaTextoEl.value.split(',').map(p => p.trim().toLowerCase()).filter(Boolean);
  }}

  function linkParticipar(r) {{
    return r.link ? `<a href="${{escapeHtml(r.link)}}" target="_blank" rel="noopener">Participar ↗</a>` : '';
  }}
  function linkDocumentos(r) {{
    return r.portal_link ? `<a class="doc" href="${{escapeHtml(r.portal_link)}}" target="_blank" rel="noopener">Edital / TR / ETP ↗</a>` : '';
  }}
  function botaoItens(r) {{
    if (!r.numero_pncp) return '';
    return `<button class="btn-itens" onclick="verItensBeta(this, '${{escapeHtml(r.numero_pncp)}}')">Ver itens (beta)</button>` +
           `<div class="itens-resultado meta"></div>`;
  }}

  // Linha de diagnostico: quantas oportunidades ha em cada modalidade
  // nos dados carregados (antes de aplicar os filtros da tela).
  function atualizarResumoModalidades() {{
    const contagem = {{}};
    DADOS.forEach(r => {{
      const chave = r.modalidade_id || '?';
      contagem[chave] = (contagem[chave] || 0) + 1;
    }});
    const partes = MODALIDADES.map(m => `${{escapeHtml(m.nome)}}: <b>${{contagem[m.codigo] || 0}}</b>`);
    document.getElementById('resumoModalidades').innerHTML = 'Dados carregados por modalidade — ' + partes.join(' · ');
  }}

  function render() {{
    const mods = new Set(modalidadesSelecionadas());
    const esfs = new Set(esferasSelecionadas());
    const ufs = new Set(ufsSelecionadas());
    const palavras = palavrasChave();
    const de = dataDeEl.value;   // "AAAA-MM-DD" ou ""
    const ate = dataAteEl.value;
    const orgaoBusca = buscaOrgaoEl.value.trim().toLowerCase();
    const vMin = valorMinEl.value !== '' ? parseFloat(valorMinEl.value) : null;
    const vMax = valorMaxEl.value !== '' ? parseFloat(valorMaxEl.value) : null;
    const srps = new Set(Array.from(document.querySelectorAll('.chk-srp:checked')).map(c => c.value));
    const modosMarcados = new Set(Array.from(document.querySelectorAll('.chk-modo:checked')).map(c => c.value));
    const temFiltroModo = document.querySelectorAll('.chk-modo').length > 0;

    const filtrados = DADOS.filter(r => {{
      if (r.modalidade_id && !mods.has(r.modalidade_id)) return false;
      if (esfs.size && r.esferaRaw && !esfs.has(r.esferaRaw)) return false;
      if (ufs.size && r.uf && !ufs.has(r.uf)) return false;
      if (de && r.encerramento_data && r.encerramento_data < de) return false;
      if (ate && r.encerramento_data && r.encerramento_data > ate) return false;
      if (palavras.length && !palavras.some(p => r.objeto.toLowerCase().includes(p))) return false;
      if (orgaoBusca && !r.orgao.toLowerCase().includes(orgaoBusca)) return false;
      if (vMin !== null && (r.valor_num === null || r.valor_num < vMin)) return false;
      if (vMax !== null && (r.valor_num === null || r.valor_num > vMax)) return false;
      if (!srps.has(r.srp)) return false;
      if (temFiltroModo && r.modo_disputa && !modosMarcados.has(r.modo_disputa)) return false;
      return true;
    }});

    corpoTabela.innerHTML = filtrados.map(r => `
      <tr>
        <td>${{escapeHtml(r.encerramento_fmt)}}</td>
        <td><span class="badge">${{escapeHtml(r.modalidade)}}</span> <span class="badge esfera">${{escapeHtml(r.esfera)}}</span>${{r.srp === 'Sim' ? ' <span class="badge srp">SRP</span>' : ''}}${{r.modo_disputa ? `<br><small>${{escapeHtml(r.modo_disputa)}}</small>` : ''}}</td>
        <td>${{escapeHtml(r.orgao)}}<br><small>UASG ${{escapeHtml(r.uasg_codigo || '-')}} · ${{escapeHtml(r.uasg_nome || '')}}</small><br><small>${{escapeHtml(r.municipio)}}/${{escapeHtml(r.uf)}}</small></td>
        <td>${{escapeHtml(r.objeto.slice(0, 220))}}${{r.objeto.length > 220 ? '…' : ''}}</td>
        <td>${{escapeHtml(r.valor_fmt)}}</td>
        <td>${{[linkParticipar(r), linkDocumentos(r), botaoItens(r)].filter(Boolean).join('<br>') || '-'}}</td>
      </tr>
    `).join('');

    contador.textContent = filtrados.length;
    totalMostrado.textContent = DADOS.length;
    vazioEl.style.display = filtrados.length === 0 ? 'block' : 'none';
    document.querySelector('table').style.display = filtrados.length === 0 ? 'none' : 'table';
    atualizarResumoModalidades();
  }}

  document.querySelectorAll('.chk-modalidade').forEach(c => c.addEventListener('change', render));
  document.querySelectorAll('.chk-esfera').forEach(c => c.addEventListener('change', render));
  document.querySelectorAll('.chk-uf').forEach(c => c.addEventListener('change', render));
  document.querySelectorAll('.chk-srp').forEach(c => c.addEventListener('change', render));
  buscaTextoEl.addEventListener('input', render);
  buscaOrgaoEl.addEventListener('input', render);
  valorMinEl.addEventListener('input', render);
  valorMaxEl.addEventListener('input', render);
  dataDeEl.addEventListener('change', render);
  dataAteEl.addEventListener('change', render);
  document.getElementById('limparFiltros').addEventListener('click', () => {{
    document.querySelectorAll('.chk-modalidade').forEach(c => c.checked = true);
    document.querySelectorAll('.chk-esfera').forEach(c => c.checked = ESFERAS.includes(c.value));
    document.querySelectorAll('.chk-uf').forEach(c => c.checked = ufsPadrao.includes(c.value));
    document.querySelectorAll('.chk-srp').forEach(c => c.checked = true);
    document.querySelectorAll('.chk-modo').forEach(c => c.checked = true);
    buscaTextoEl.value = '';
    buscaOrgaoEl.value = '';
    valorMinEl.value = '';
    valorMaxEl.value = '';
    dataDeEl.value = '';
    dataAteEl.value = '';
    render();
  }});

  // Botao "Ver itens (beta)": tenta os dois caminhos conhecidos do PNCP
  // para itens de uma contratacao. Esse endpoint e documentadamente
  // instavel (costuma responder 404 ou erro de servidor mesmo em
  // processos validos), entao isto e so uma tentativa opcional — se
  // falhar, a pessoa ainda tem o link "Edital / TR / ETP" com os itens
  // descritos no documento.
  function parseNumeroPncp(n) {{
    if (!n) return null;
    const m = n.match(/^(\\d{{14}})-\\d+-(\\d+)\\/(\\d{{4}})$/);
    if (!m) return null;
    const [, cnpj, sequencial, ano] = m;
    return {{ cnpj, ano, sequencial: parseInt(sequencial, 10) }};
  }}

  window.verItensBeta = async function(botao, numeroPncp) {{
    const destino = botao.nextElementSibling;
    const p = parseNumeroPncp(numeroPncp);
    if (!p) {{ destino.textContent = 'Não foi possível identificar este processo.'; return; }}
    botao.disabled = true;
    destino.textContent = 'Buscando itens (beta)...';
    const tentativas = [
      `https://pncp.gov.br/api/pncp/v1/orgaos/${{p.cnpj}}/compras/${{p.ano}}/${{p.sequencial}}/itens`,
      `https://pncp.gov.br/api/consulta/v1/orgaos/${{p.cnpj}}/compras/${{p.ano}}/${{p.sequencial}}/itens`,
    ];
    for (const url of tentativas) {{
      try {{
        const resp = await fetch(url);
        if (!resp.ok) continue;
        const dados = await resp.json();
        const lista = Array.isArray(dados) ? dados : (dados.data || dados.itens || []);
        if (!lista.length) {{
          destino.textContent = 'A API não devolveu itens cadastrados para este processo.';
          botao.disabled = false;
          return;
        }}
        destino.innerHTML = '<ul style="margin:0.3rem 0 0; padding-left:1.1rem">' +
          lista.slice(0, 30).map(it => {{
            const desc = it.descricao || it.materialOuServicoNome || it.descricaoItem || 'item';
            const qtd = it.quantidade != null ? ` — qtd ${{escapeHtml(String(it.quantidade))}}` : '';
            return `<li>${{escapeHtml(desc)}}${{qtd}}</li>`;
          }}).join('') + '</ul>';
        botao.disabled = false;
        return;
      }} catch (e) {{ /* tenta o proximo caminho */ }}
    }}
    destino.textContent = 'Não foi possível carregar os itens agora (esse endpoint do PNCP costuma falhar). Veja "Edital / TR / ETP" para os itens no documento.';
    botao.disabled = false;
  }};

  // ---------- Busca ao vivo direto no navegador, de acordo com a selecao ----------

  function fmtValorJS(v) {{
    if (v === null || v === undefined) return '-';
    const n = Number(v);
    if (isNaN(n)) return String(v);
    return 'R$ ' + n.toLocaleString('pt-BR', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
  }}

  function fmtDataJS(v) {{
    if (!v) return '-';
    const d = new Date(v);
    if (isNaN(d.getTime())) return v;
    return d.toLocaleString('pt-BR', {{ day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }});
  }}

  function portalLinkJS(numeroControlePncp) {{
    if (!numeroControlePncp) return '';
    const m = numeroControlePncp.match(/^(\\d{{14}})-\\d+-(\\d+)\\/(\\d{{4}})$/);
    if (!m) return '';
    const [, cnpj, sequencial, ano] = m;
    return `https://pncp.gov.br/app/editais/${{cnpj}}/${{ano}}/${{parseInt(sequencial, 10)}}`;
  }}

  function normalizar(item, codigoConsultado) {{
    const orgao = item.orgaoEntidade || {{}};
    const unidade = item.unidadeOrgao || {{}};
    const enc = item.dataEncerramentoProposta || '';
    // A consulta e feita uma modalidade por vez, entao o codigo consultado
    // e a fonte mais confiavel; o modalidadeId da API e so o plano B.
    const codigo = String(codigoConsultado || item.modalidadeId || '');
    return {{
      modalidade: NOME_MODALIDADE[codigo] || item.modalidadeNome || '-',
      modalidade_id: codigo,
      esfera: NOME_ESFERA[orgao.esferaId] || (orgao.esferaId || '-'),
      esferaRaw: orgao.esferaId || '',
      orgao: orgao.razaosocial || '-',
      uasg_codigo: unidade.codigoUnidade || '',
      uasg_nome: unidade.nomeUnidade || '',
      municipio: unidade.municipioNome || '',
      uf: unidade.ufSigla || '',
      objeto: item.objetoCompra || '',
      valor_num: typeof item.valorTotalEstimado === 'number' ? item.valorTotalEstimado : null,
      valor_fmt: fmtValorJS(item.valorTotalEstimado),
      encerramento_data: enc ? enc.slice(0, 10) : '',
      encerramento_fmt: fmtDataJS(enc),
      link: item.linkSistemaOrigem || '',
      portal_link: portalLinkJS(item.numeroControlePNCP),
      srp: item.srp === true ? 'Sim' : (item.srp === false ? 'Não' : ''),
      modo_disputa: item.modoDisputaNome || '',
      numero_pncp: item.numeroControlePNCP || '',
    }};
  }}

  function dataFinalPadrao() {{
    const d = new Date();
    d.setDate(d.getDate() + DIAS_A_FRENTE_PADRAO);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${{yyyy}}${{mm}}${{dd}}`;
  }}

  async function buscarPagina(codigoModalidade, uf, dataFinal, pagina) {{
    const params = new URLSearchParams({{
      dataFinal: dataFinal,
      codigoModalidadeContratacao: codigoModalidade,
      pagina: String(pagina),
      tamanhoPagina: '50',
    }});
    if (uf) params.set('uf', uf);
    const resp = await fetch(`https://pncp.gov.br/api/consulta/v1/contratacoes/proposta?${{params}}`);
    if (resp.status === 204) return {{ data: [], totalPaginas: 0 }};
    if (resp.status === 429 || resp.status >= 500) {{
      throw new Error('temporario:' + resp.status);
    }}
    if (!resp.ok) throw new Error('http:' + resp.status);
    return resp.json();
  }}

  async function buscarModalidadeUf(codigoModalidade, uf, dataFinal, nomeModalidade) {{
    const registros = [];
    let pagina = 1;
    let totalPaginas = 1;
    const LIMITE_PAGINAS = 25; // trava de seguranca para nao rodar pra sempre
    while (pagina <= totalPaginas && pagina <= LIMITE_PAGINAS) {{
      statusEl.textContent = `Buscando ${{nomeModalidade}} / UF=${{uf || 'BR'}} — página ${{pagina}}${{totalPaginas > 1 ? ('/' + totalPaginas) : ''}}...`;
      let tentativas = 0;
      while (true) {{
        try {{
          const dados = await buscarPagina(codigoModalidade, uf, dataFinal, pagina);
          (dados.data || []).forEach(item => registros.push(normalizar(item, codigoModalidade)));
          totalPaginas = dados.totalPaginas || 0;
          break;
        }} catch (e) {{
          tentativas++;
          if (tentativas >= 4) throw e;
          const espera = 1500 * tentativas;
          statusEl.textContent = `Instabilidade no PNCP, tentando de novo em ${{Math.round(espera / 1000)}}s...`;
          await new Promise(res => setTimeout(res, espera));
        }}
      }}
      pagina++;
    }}
    return registros;
  }}

  async function buscarAoVivo() {{
    const codigos = modalidadesSelecionadas();   // ja sao codigos numericos
    if (codigos.length === 0) {{
      statusEl.textContent = 'Selecione ao menos uma modalidade antes de buscar.';
      return;
    }}
    const ufsMarcadas = ufsSelecionadas();
    if (ufsMarcadas.length === 0) {{
      statusEl.textContent = 'Selecione ao menos um estado (UF) antes de buscar.';
      return;
    }}
    const esferasMarcadas = esferasSelecionadas();
    if (esferasMarcadas.length === 0) {{
      statusEl.textContent = 'Selecione ao menos uma esfera antes de buscar.';
      return;
    }}
    const palavras = palavrasChave();
    const ate = dataAteEl.value;
    const dataFinal = ate ? ate.replaceAll('-', '') : dataFinalPadrao();
    const listaUfs = ufsMarcadas;

    const combinacoes = codigos.length * listaUfs.length;
    botaoAoVivo.disabled = true;
    statusEl.textContent = combinacoes > 12
      ? `Iniciando busca ao vivo (${{combinacoes}} combinações de modalidade/UF — pode demorar bastante)...`
      : 'Iniciando busca ao vivo no PNCP...';

    try {{
      let todos = [];
      for (const codigo of codigos) {{
        for (const uf of listaUfs) {{
          const parciais = await buscarModalidadeUf(codigo, uf, dataFinal, NOME_MODALIDADE[codigo] || codigo);
          todos = todos.concat(parciais);
        }}
      }}

      let filtrados = todos.filter(r => esferasMarcadas.includes(r.esferaRaw));
      if (palavras.length) {{
        filtrados = filtrados.filter(r => palavras.some(p => r.objeto.toLowerCase().includes(p)));
      }}
      filtrados.sort((a, b) => (a.encerramento_data || '').localeCompare(b.encerramento_data || ''));

      DADOS.length = 0;
      DADOS.push(...filtrados);
      totalColetado.textContent = DADOS.length;
      document.getElementById('atualizadoEm').textContent =
        'agora (' + new Date().toLocaleString('pt-BR') + ') — dados ao vivo, buscados pelo seu navegador';
      statusEl.textContent = `Pronto: ${{filtrados.length}} oportunidade(s) encontradas ao vivo` +
        ` (de ${{todos.length}} devolvidas pelo PNCP antes de filtrar esfera/palavra-chave).`;
      construirFiltroModoDisputa();
      render();
    }} catch (e) {{
      console.error(e);
      statusEl.textContent = 'Não foi possível buscar ao vivo agora (rede ou bloqueio do navegador). Mostrando os dados da última atualização automática (08h).';
    }} finally {{
      botaoAoVivo.disabled = false;
    }}
  }}

  botaoAoVivo.addEventListener('click', buscarAoVivo);

  construirFiltroModoDisputa();
  render();
</script>
</body>
</html>"""

    import os
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"HTML gerado: {caminho}")


def main():
    linhas = coletar()
    print(f"\nTotal encontrado após filtros: {len(linhas)}")
    gerar_csv(linhas)
    gerar_html(linhas)


if __name__ == "__main__":
    main()
