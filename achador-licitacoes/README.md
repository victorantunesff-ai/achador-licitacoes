# Achador de Licitações e Dispensas (PNCP)

Todo dia às 08h (horário de Brasília), este sistema busca sozinho, na
internet, as licitações e dispensas que ainda estão abertas para proposta —
e te entrega isso numa página que você abre pelo celular ou computador.

Você não precisa saber programar. Só seguir os passos abaixo, uma vez.

---

## PASSO 1 — Criar uma conta no GitHub (se ainda não tiver)

O GitHub é o serviço gratuito que vai "hospedar" e rodar o sistema pra você,
sozinho, todo dia.

1. Acesse **github.com**
2. Clique em **Sign up** e crie sua conta (é grátis)

Se já tem conta, pule para o Passo 2.

---

## PASSO 2 — Criar o "repositório" (a pasta do projeto)

1. Já logado no GitHub, clique no **+** no canto superior direito → **New
   repository**
2. Em "Repository name", escreva: `achador-licitacoes`
3. Deixe marcado **Public**
4. **Não marque** nenhuma caixinha (Add README, .gitignore, license) —
   deixe tudo desmarcado
5. Clique no botão verde **Create repository**

Você vai cair numa página vazia, com instruções técnicas — pode ignorar,
vamos usar outro caminho no próximo passo.

---

## PASSO 3 — Subir os arquivos

1. Nessa mesma página, procure o link **"uploading an existing file"**
   (geralmente aparece escrito em azul, no meio do texto) e clique nele
2. Vai abrir uma área para arrastar arquivos
3. No seu computador, **abra a pasta que eu te entreguei** (extraia o
   arquivo `achador-licitacoes.zip` primeiro, se ainda não extraiu)
4. Selecione **todos os arquivos e pastas de dentro dela** (`achador.py`,
   `requirements.txt`, `README.md`, a pasta `.github` e a pasta `docs`) e
   arraste tudo para dentro da área do navegador
5. Espere a barra de carregamento terminar
6. Role até o final da página e clique no botão verde **Commit changes**

> ⚠️ Ponto de atenção: as pastas `.github` e `docs` às vezes ficam
> "escondidas" no seletor de arquivos do computador. Se ao arrastar elas não
> aparecerem, no Passo 3.4 arraste a pasta `achador-licitacoes` **inteira**
> de uma vez (a pasta que contém tudo) em vez de item por item.

---

## PASSO 4 — Ligar a "página" que você vai acessar todo dia

1. No repositório, clique na aba **Settings** (é uma engrenagem, fica no
   menu de cima)
2. No menu da esquerda, clique em **Pages**
3. Em "Build and deployment" → onde está escrito **Branch**, troque de
   "None" para **main**
4. Do lado, troque a pasta de "/ (root)" para **/docs**
5. Clique em **Save**
6. Espere ~1 minuto e atualize a página. Vai aparecer um link parecido com:
   `https://seu-usuario.github.io/achador-licitacoes/`
7. **Guarde/favorite esse link** — é ele que você vai abrir todo dia

---

## PASSO 5 — Rodar pela primeira vez

Por padrão o sistema só roda automaticamente às 08h. Pra não esperar até
amanhã, vamos rodar uma vez agora manualmente:

1. Clique na aba **Actions** (no menu de cima do repositório)
2. Se aparecer um botão verde "I understand my workflows, go ahead and
   enable them", clique nele
3. Clique em **"Achador de Licitações (diário)"** na lista à esquerda
4. Clique no botão **Run workflow** (à direita) → e de novo em **Run
   workflow** na caixinha que abrir
5. Espere cerca de 1 minuto, atualizando a página — vai aparecer uma bolinha
   verde ✅ quando terminar
6. Agora abra o link que você guardou no Passo 4 — as oportunidades já
   devem aparecer

---

## Pronto! O que acontece agora

A partir de hoje, **todo dia às 08h (horário de Brasília)**, o sistema roda
sozinho e atualiza essa página automaticamente. Você não precisa fazer mais
nada — nem deixar o computador ligado. É só abrir o link salvo, de manhã.

---

## Ajustando o que ele busca (opcional, depois)

Quando quiser mudar o que o sistema procura (por exemplo, focar só em
determinados produtos, ou incluir outros estados), me avise com a lista de
materiais ou CNAEs — eu ajusto o arquivo `achador.py` e te devolvo pronto
pra você repetir só o Passo 3 (subir o arquivo atualizado).
