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
import time
from datetime import datetime, timedelta, timezone

import requests

# ======================= CONFIGURACAO =======================
# Edite esta secao com o que interessa para a sua empresa.

# Ate quantos dias a frente olhar (janela de propostas abertas).
# Pode deixar generoso aqui: o filtro fino de periodo agora e feito na
# propria pagina (o visitante escolhe o intervalo que quiser).
DIAS_A_FRENTE = 30

# Esferas: F=Federal, E=Estadual, M=Municipal, D=Distrital
ESFERAS_DESEJADAS = {"F", "E"}

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
    return {
        "modalidade": item.get("modalidadeNome"),
        "situacao": item.get("situacaoCompraNome"),
        "esfera": orgao.get("esferaId"),
        "orgao": orgao.get("razaosocial"),
        "uf": unidade.get("ufSigla"),
        "municipio": unidade.get("municipioNome"),
        "objeto": item.get("objetoCompra") or "",
        "valor": item.get("valorTotalEstimado"),
        "abertura": item.get("dataAberturaProposta"),
        "encerramento": item.get("dataEncerramentoProposta"),
        "numero_pncp": item.get("numeroControlePNCP"),
        "link": item.get("linkSistemaOrigem"),
    }


def coletar():
    data_final = (datetime.now(TZ_BR) + timedelta(days=DIAS_A_FRENTE)).strftime("%Y%m%d")
    ufs = UFS_DESEJADAS if UFS_DESEJADAS else [None]

    todos = []
    for modalidade in MODALIDADES:
        for uf in ufs:
            print(f"Consultando {NOMES_MODALIDADE.get(modalidade, modalidade)} / UF={uf or 'BR'}...")
            todos.extend(consultar_modalidade(modalidade, data_final, uf))

    filtrados = [linha(r) for r in todos if bate_filtros(r)]
    filtrados.sort(key=lambda r: r["encerramento"] or "")
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
            "esfera": esfera_nome,
            "orgao": r["orgao"] or "-",
            "municipio": r["municipio"] or "",
            "uf": r["uf"] or "",
            "objeto": r["objeto"] or "",
            "valor_fmt": fmt_valor(r["valor"]),
            "encerramento_data": enc[:10] if enc else "",  # AAAA-MM-DD, para o filtro
            "encerramento_fmt": fmt_data(enc),
            "link": r["link"] or "",
        })

    modalidades_presentes = sorted({r["modalidade"] for r in registros_js})
    dados_json = json.dumps(registros_js, ensure_ascii=False)
    modalidades_json = json.dumps(modalidades_presentes, ensure_ascii=False)

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
    padding: 1rem 1.2rem; margin-bottom: 1.2rem; display: flex; flex-wrap: wrap; gap: 1.4rem;
  }}
  .filtros fieldset {{ border: none; padding: 0; margin: 0; min-width: 180px; }}
  .filtros legend {{ font-weight: 600; font-size: 0.85rem; margin-bottom: 0.4rem; padding: 0; }}
  .filtros label {{ display: block; font-size: 0.85rem; margin: 0.15rem 0; cursor: pointer; }}
  .filtros input[type="date"] {{
    padding: 0.35rem 0.5rem; border-radius: 6px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 0.85rem;
  }}
  .filtros .campo-data {{ display: flex; flex-direction: column; gap: 0.4rem; }}
  .filtros button {{
    align-self: flex-end; padding: 0.4rem 0.9rem; border-radius: 8px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); cursor: pointer; font-size: 0.85rem; height: fit-content;
  }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th, td {{ padding: 0.7rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }}
  th {{ background: var(--bg); font-weight: 600; position: sticky; top: 0; }}
  tr:last-child td {{ border-bottom: none; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; background: var(--accent); color: #fff; font-size: 0.72rem; margin-bottom: 2px; }}
  .badge.esfera {{ background: #555; }}
  small {{ color: var(--muted); }}
  a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
  .empty {{ padding: 2rem; text-align: center; color: var(--muted); }}
  .wrap {{ overflow-x: auto; }}
  #contador {{ font-weight: 600; }}
</style>
</head>
<body>
  <h1>📋 Achador de Licitações e Dispensas</h1>
  <div class="meta">
    Atualizado em {agora} (horário de Brasília) · {total} oportunidade(s) coletadas ·
    Esfera(s): {', '.join(sorted(ESFERAS_DESEJADAS))} · UF(s): {resumo_ufs}
  </div>

  <div class="filtros">
    <fieldset>
      <legend>Modalidade</legend>
      <div id="filtroModalidade"></div>
    </fieldset>
    <fieldset>
      <legend>Encerramento da proposta</legend>
      <div class="campo-data">
        <label>De: <input type="date" id="dataDe"></label>
        <label>Até: <input type="date" id="dataAte"></label>
      </div>
    </fieldset>
    <button id="limparFiltros">Limpar filtros</button>
  </div>

  <div class="meta">Mostrando <span id="contador">{total}</span> de {total} oportunidade(s)</div>

  <div class="card wrap">
    <table>
      <thead>
        <tr><th>Encerra em</th><th>Modalidade</th><th>Órgão</th><th>Objeto</th><th>Valor estimado</th><th>Link</th></tr>
      </thead>
      <tbody id="corpoTabela"></tbody>
    </table>
    <div id="vazio" class="empty" style="display:none">Nenhuma oportunidade com os filtros escolhidos.</div>
  </div>

<script>
  const DADOS = {dados_json};
  const MODALIDADES = {modalidades_json};

  function escapeHtml(s) {{
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }}

  // Monta os checkboxes de modalidade dinamicamente
  const filtroModalidadeEl = document.getElementById('filtroModalidade');
  MODALIDADES.forEach((m, i) => {{
    const id = 'mod_' + i;
    const label = document.createElement('label');
    label.innerHTML = `<input type="checkbox" class="chk-modalidade" value="${{escapeHtml(m)}}" id="${{id}}" checked> ${{escapeHtml(m)}}`;
    filtroModalidadeEl.appendChild(label);
  }});

  const corpoTabela = document.getElementById('corpoTabela');
  const contador = document.getElementById('contador');
  const vazioEl = document.getElementById('vazio');
  const dataDeEl = document.getElementById('dataDe');
  const dataAteEl = document.getElementById('dataAte');

  function modalidadesSelecionadas() {{
    return Array.from(document.querySelectorAll('.chk-modalidade:checked')).map(c => c.value);
  }}

  function render() {{
    const mods = new Set(modalidadesSelecionadas());
    const de = dataDeEl.value;   // "AAAA-MM-DD" ou ""
    const ate = dataAteEl.value;

    const filtrados = DADOS.filter(r => {{
      if (!mods.has(r.modalidade)) return false;
      if (de && r.encerramento_data && r.encerramento_data < de) return false;
      if (ate && r.encerramento_data && r.encerramento_data > ate) return false;
      return true;
    }});

    corpoTabela.innerHTML = filtrados.map(r => `
      <tr>
        <td>${{escapeHtml(r.encerramento_fmt)}}</td>
        <td><span class="badge">${{escapeHtml(r.modalidade)}}</span> <span class="badge esfera">${{escapeHtml(r.esfera)}}</span></td>
        <td>${{escapeHtml(r.orgao)}}<br><small>${{escapeHtml(r.municipio)}}/${{escapeHtml(r.uf)}}</small></td>
        <td>${{escapeHtml(r.objeto.slice(0, 220))}}${{r.objeto.length > 220 ? '…' : ''}}</td>
        <td>${{escapeHtml(r.valor_fmt)}}</td>
        <td>${{r.link ? `<a href="${{escapeHtml(r.link)}}" target="_blank" rel="noopener">Participar ↗</a>` : '-'}}</td>
      </tr>
    `).join('');

    contador.textContent = filtrados.length;
    vazioEl.style.display = filtrados.length === 0 ? 'block' : 'none';
    document.querySelector('table').style.display = filtrados.length === 0 ? 'none' : 'table';
  }}

  document.querySelectorAll('.chk-modalidade').forEach(c => c.addEventListener('change', render));
  dataDeEl.addEventListener('change', render);
  dataAteEl.addEventListener('change', render);
  document.getElementById('limparFiltros').addEventListener('click', () => {{
    document.querySelectorAll('.chk-modalidade').forEach(c => c.checked = true);
    dataDeEl.value = '';
    dataAteEl.value = '';
    render();
  }});

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
