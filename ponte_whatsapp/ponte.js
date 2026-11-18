// Ponte local entre o script de prospecção (Python) e o WhatsApp, via Baileys.
//
// Escuta SOMENTE em 127.0.0.1 (nada fica exposto na rede). Endpoints:
//   GET  /status                      -> {conectado, numero, qr, inicio}
//   POST /verificar  {numero}         -> {existe, jid}
//   POST /enviar     {numero, texto}  -> {ok, id, jid}
//   POST /enviar-arquivo {numero, caminho, legenda?} -> {ok, id}
//   GET  /conversa?numero=...         -> {jid, mensagens: [{de_mim, quando, texto, nome}]}
//   GET  /eventos?apos=N              -> {inicio, seq, eventos: [{seq, numero, quando, texto, nome}]}
//
// A sessão fica em .auth_baileys/ e as mensagens em dados/mensagens.jsonl
// (ambos fora do git). Para conectar: `node ponte.js` e escaneie o QR Code
// (terminal ou qr.png) em WhatsApp > Aparelhos conectados.

import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  isLidUser,
  jidNormalizedUser,
  makeCacheableSignalKeyStore,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";
import pino from "pino";
import QRCode from "qrcode";
import qrTerminal from "qrcode-terminal";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const PORTA = Number(process.env.PONTE_PORTA || 8790);
const PASTA_AUTH = path.join(DIR, ".auth_baileys");
const PASTA_DADOS = path.join(DIR, "dados");
const ARQ_MENSAGENS = path.join(PASTA_DADOS, "mensagens.jsonl");
const ARQ_QR = path.join(DIR, "qr.png");
const INICIO = Date.now().toString(36); // muda a cada reinício (o Python zera o cursor)

fs.mkdirSync(PASTA_DADOS, { recursive: true });

// Com PONTE_LOG_ARQUIVO (tarefa agendada, sem console), tudo vai para esse
// arquivo em UTF-8, com data e hora em cada linha.
const ARQ_LOG = process.env.PONTE_LOG_ARQUIVO ? path.resolve(DIR, process.env.PONTE_LOG_ARQUIVO) : null;
if (ARQ_LOG) {
  const gravar = (...partes) => fs.appendFileSync(ARQ_LOG,
    `${new Date().toLocaleString("pt-BR")} ${partes.map((p) => (typeof p === "string" ? p : p?.stack || JSON.stringify(p))).join(" ")}\n`);
  console.log = gravar;
  console.error = gravar;
}
const logger = pino({ level: process.env.PONTE_LOG || "warn" },
  ARQ_LOG ? pino.destination({ dest: ARQ_LOG, append: true, sync: true }) : undefined);

// ---------------------------------------------------------------- estado ---
let sock = null;
let conectado = false;
let deslogado = false;
let qrAtual = null;
const conversas = new Map(); // dígitos do telefone -> [{id, de_mim, quando, texto, nome}]
const idsVistos = new Set();
const eventos = []; // mensagens RECEBIDAS desde que a ponte subiu
let seq = 0;
const cacheJid = new Map(); // número pedido pelo Python -> jid canônico

function digitos(jid) {
  return String(jid || "").split("@")[0].split(":")[0].replace(/\D/g, "");
}

// ------------------------------------------------- números monitorados ---
// O Python grava em dados/numeros_monitorados.json os telefones das clínicas
// (e o do operador). Só essas conversas são guardadas: as pessoais nunca vão
// para o disco. Sem o arquivo (antes do 1º vigia), guarda tudo para não
// perder nenhuma resposta; ao surgir o arquivo, o resto é apagado.
const ARQ_PERMITIDOS = path.join(PASTA_DADOS, "numeros_monitorados.json");
let permitidos = null; // Set de chaves, ou null = sem filtro ainda
let mtimePermitidos = 0;
const enviadosAgora = new Set(); // números a quem a ponte enviou nesta execução

// País + DDD + 8 últimos dígitos: tolera o 9º dígito brasileiro.
function chave(numero) {
  const n = String(numero || "").replace(/\D/g, "");
  return n.startsWith("55") && (n.length === 12 || n.length === 13) ? n.slice(0, 4) + n.slice(-8) : n;
}

function atualizarPermitidos() {
  let mtime = 0;
  try {
    mtime = fs.statSync(ARQ_PERMITIDOS).mtimeMs;
  } catch {
    return false;
  }
  if (mtime === mtimePermitidos) return false;
  try {
    const lista = JSON.parse(fs.readFileSync(ARQ_PERMITIDOS, "utf8")).numeros || [];
    permitidos = new Set(lista.map(chave));
    mtimePermitidos = mtime;
    return true;
  } catch {
    return false; // arquivo sendo gravado: tenta na próxima
  }
}

function permitido(numero) {
  if (atualizarPermitidos()) podar();
  return permitidos === null || permitidos.has(chave(numero)) || enviadosAgora.has(chave(numero));
}

function registrar(numero, msg, persistir = true) {
  if (!numero || !msg.texto || idsVistos.has(msg.id) || !permitido(numero)) return false;
  idsVistos.add(msg.id);
  if (!conversas.has(numero)) conversas.set(numero, []);
  conversas.get(numero).push(msg);
  if (persistir) fs.appendFileSync(ARQ_MENSAGENS, JSON.stringify({ numero, ...msg }) + "\n");
  return true;
}

// Apaga da memória e do disco as conversas que não são de clínicas.
// `forcar`: regrava o arquivo mesmo sem nada a remover da memória (no início,
// as linhas pessoais já nem entraram na memória, mas continuam no disco).
function podar(forcar = false) {
  if (permitidos === null) return;
  let removidas = 0;
  for (const numero of [...conversas.keys()]) {
    if (!permitidos.has(chave(numero)) && !enviadosAgora.has(chave(numero))) {
      removidas += conversas.get(numero).length;
      conversas.delete(numero);
    }
  }
  if (!removidas && !forcar && fs.existsSync(ARQ_MENSAGENS)) return;
  const linhas = [];
  for (const [numero, lista] of conversas) for (const msg of lista) linhas.push(JSON.stringify({ numero, ...msg }));
  const tmp = ARQ_MENSAGENS + ".tmp";
  fs.writeFileSync(tmp, linhas.length ? linhas.join("\n") + "\n" : "");
  fs.renameSync(tmp, ARQ_MENSAGENS);
  if (removidas) console.log(`[PRIVACIDADE] ${removidas} mensagem(ns) de conversas pessoais apagada(s) do disco.`);
}

// Recarrega o que já foi visto (sobrevive a reinícios).
atualizarPermitidos();
if (fs.existsSync(ARQ_MENSAGENS)) {
  for (const linha of fs.readFileSync(ARQ_MENSAGENS, "utf8").split("\n")) {
    if (!linha.trim()) continue;
    try {
      const { numero, ...msg } = JSON.parse(linha);
      registrar(numero, msg, false);
    } catch {
      /* linha corrompida: ignora */
    }
  }
  const noDisco = fs.readFileSync(ARQ_MENSAGENS, "utf8").split(/\r?\n/).filter((l) => l.trim()).length;
  const guardadas = [...conversas.values()].reduce((n, l) => n + l.length, 0);
  if (permitidos !== null && noDisco !== guardadas) {
    podar(true); // o que foi gravado antes do filtro existir sai do disco agora
    console.log(`[PRIVACIDADE] ${noDisco - guardadas} mensagem(ns) de conversas pessoais apagada(s) do disco.`);
  }
}

// Texto de qualquer tipo de mensagem, inclusive menus de robô (lista/botões).
function extrairTexto(m) {
  if (!m) return "";
  const inner = m.ephemeralMessage?.message || m.viewOnceMessage?.message ||
    m.viewOnceMessageV2?.message || m.documentWithCaptionMessage?.message;
  if (inner) return extrairTexto(inner);
  const partes = [];
  const add = (t) => t && partes.push(String(t));
  add(m.conversation);
  add(m.extendedTextMessage?.text);
  add(m.imageMessage?.caption);
  add(m.videoMessage?.caption);
  add(m.documentMessage?.caption);
  const botoes = m.buttonsMessage;
  if (botoes) {
    add(botoes.contentText);
    (botoes.buttons || []).forEach((b, i) => add(`${i + 1} - ${b.buttonText?.displayText || ""}`));
  }
  const lista = m.listMessage;
  if (lista) {
    add(lista.title);
    add(lista.description);
    let n = 0;
    for (const s of lista.sections || []) for (const r of s.rows || []) add(`${++n} - ${r.title || ""}`);
  }
  const tpl = m.templateMessage?.hydratedTemplate || m.templateMessage?.hydratedFourRowTemplate;
  if (tpl) {
    add(tpl.hydratedContentText);
    (tpl.hydratedButtons || []).forEach((b, i) =>
      add(`${i + 1} - ${b.quickReplyButton?.displayText || b.urlButton?.displayText || ""}`));
  }
  const inter = m.interactiveMessage;
  if (inter) {
    add(inter.header?.title);
    add(inter.body?.text);
    add(inter.footer?.text);
  }
  add(m.buttonsResponseMessage?.selectedDisplayText);
  add(m.listResponseMessage?.title);
  // Cartão de contato ("segue o contato da nossa gestão"): vira
  // "[contato] Nome +5579..." para o Python reconhecer e avisar o operador.
  const cartoes = m.contactMessage ? [m.contactMessage] : (m.contactsArrayMessage?.contacts || []);
  for (const c of cartoes) {
    const vcard = c.vcard || "";
    const tel = (vcard.match(/waid=(\d+)/) || vcard.match(/TEL[^:]*:\s*([+\d][\d\s()-]+)/) || [])[1];
    add(`[contato] ${c.displayName || ""} ${tel ? "+" + tel.replace(/\D/g, "") : ""}`.trim());
  }
  return partes.join("\n").trim();
}

async function numeroDoRemetente(key) {
  let jid = key.remoteJid || "";
  if (isLidUser(jid)) {
    if (key.remoteJidAlt && !isLidUser(key.remoteJidAlt)) jid = key.remoteJidAlt;
    else {
      try {
        const pn = await sock?.signalRepository?.lidMapping?.getPNForLID(jid);
        if (pn) jid = pn;
      } catch {
        /* sem mapeamento ainda */
      }
    }
  }
  if (isLidUser(jid) || !jid.endsWith("@s.whatsapp.net")) return null; // grupos, status, LID sem número
  return digitos(jid);
}

async function processarMensagem(wm, ehNova) {
  if (!wm?.key?.id || !wm.message) return;
  const numero = await numeroDoRemetente(wm.key);
  if (!numero) return;
  const texto = extrairTexto(wm.message);
  const quando = Number(wm.messageTimestamp || Date.now() / 1000);
  const msg = { id: wm.key.id, de_mim: !!wm.key.fromMe, quando, texto, nome: wm.pushName || "" };
  // Também vira evento o que chegou enquanto a ponte estava fora (histórico,
  // "append" ao reconectar), se for recente: foi assim que a resposta do
  // de um dentista (18/11, 9h51, antes da ponte subir) ficou sem ninguém ver.
  const recente = Date.now() / 1000 - quando < 48 * 3600;
  if (registrar(numero, msg) && (ehNova || recente) && !msg.de_mim) {
    eventos.push({ seq: ++seq, numero, quando, texto, nome: msg.nome });
    if (eventos.length > 2000) eventos.splice(0, eventos.length - 2000);
    console.log(`[RECEBIDA] +${numero}: ${texto.slice(0, 80).replace(/\n/g, " ")}`);
  }
}

// --------------------------------------------------------------- conexão ---
async function conectar() {
  const { state, saveCreds } = await useMultiFileAuthState(PASTA_AUTH);
  let version;
  try {
    ({ version } = await fetchLatestBaileysVersion());
  } catch {
    /* usa a versão embutida */
  }
  sock = makeWASocket({
    version,
    auth: { creds: state.creds, keys: makeCacheableSignalKeyStore(state.keys, logger) },
    logger,
    browser: Browsers.windows("Desktop"),
    markOnlineOnConnect: false, // não aparece "online" o dia todo
    syncFullHistory: false,
  });
  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      qrAtual = qr;
      console.log("\nEscaneie em WhatsApp > Aparelhos conectados > Conectar um aparelho:");
      if (!ARQ_LOG) qrTerminal.generate(qr, { small: true });
      try {
        await QRCode.toFile(ARQ_QR, qr, { width: 360 });
        console.log(`(ou abra ${ARQ_QR})`);
      } catch {
        /* só terminal */
      }
    }
    if (connection === "open") {
      conectado = true;
      deslogado = false;
      qrAtual = null;
      fs.rmSync(ARQ_QR, { force: true });
      console.log(`[OK] Conectado como +${digitos(sock.user?.id)}`);
    }
    if (connection === "close") {
      conectado = false;
      const codigo = lastDisconnect?.error?.output?.statusCode;
      if (codigo === DisconnectReason.loggedOut) {
        deslogado = true;
        console.log("[ERRO] Sessão encerrada no celular. Apague .auth_baileys/ e rode de novo para ler o QR.");
        return;
      }
      console.log(`[AVISO] Conexão caiu (código ${codigo ?? "?"}); reconectando em 5 s...`);
      setTimeout(() => conectar().catch((e) => console.error(e)), 5000);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    for (const wm of messages) await processarMensagem(wm, type === "notify");
  });
  sock.ev.on("messaging-history.set", async ({ messages }) => {
    for (const wm of messages || []) await processarMensagem(wm, false);
  });
}

async function resolverJid(numero) {
  const n = String(numero || "").replace(/\D/g, "");
  if (!n) return null;
  if (cacheJid.has(n)) return cacheJid.get(n);
  const res = await sock.onWhatsApp(n);
  const achado = res?.find((r) => r.exists);
  const jid = achado ? jidNormalizedUser(achado.jid) : null;
  cacheJid.set(n, jid);
  return jid;
}

const espera = (ms) => new Promise((r) => setTimeout(r, ms));

// "Digitando..." por um tempo proporcional ao texto (2 a 8 s): mais natural.
async function simularDigitacao(jid, texto) {
  try {
    await sock.presenceSubscribe(jid);
    await sock.sendPresenceUpdate("composing", jid);
    await espera(Math.min(8000, Math.max(2000, texto.length * 15)));
    await sock.sendPresenceUpdate("paused", jid);
  } catch {
    /* presença é só cosmética */
  }
}

// ------------------------------------------------------------------ HTTP ---
function responder(res, codigo, corpo) {
  res.writeHead(codigo, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(corpo));
}

async function lerCorpo(req) {
  let dados = "";
  for await (const parte of req) dados += parte;
  return dados ? JSON.parse(dados) : {};
}

const MIME = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
  ".pdf": "application/pdf" };

const rotas = {
  "GET /status": async () => [200, {
    conectado, deslogado, numero: conectado ? digitos(sock?.user?.id) : null, qr: qrAtual, inicio: INICIO,
  }],

  "POST /verificar": async (corpo) => {
    const jid = await resolverJid(corpo.numero);
    return [200, { existe: !!jid, jid }];
  },

  "POST /enviar": async (corpo) => {
    const texto = String(corpo.texto || "");
    if (!texto.trim()) return [400, { erro: "texto vazio" }];
    const jid = await resolverJid(corpo.numero);
    if (!jid) return [404, { erro: "sem_whatsapp" }];
    enviadosAgora.add(chave(digitos(jid))); // a resposta a este envio é guardada
    if (corpo.digitar !== false) await simularDigitacao(jid, texto);
    const enviado = await sock.sendMessage(jid, { text: texto });
    await processarMensagem(enviado, false);
    return [200, { ok: true, id: enviado?.key?.id, jid }];
  },

  "POST /enviar-arquivo": async (corpo) => {
    const caminho = String(corpo.caminho || "");
    if (!fs.existsSync(caminho)) return [400, { erro: `arquivo não encontrado: ${path.basename(caminho)}` }];
    const jid = await resolverJid(corpo.numero);
    if (!jid) return [404, { erro: "sem_whatsapp" }];
    const ext = path.extname(caminho).toLowerCase();
    const buffer = fs.readFileSync(caminho);
    const conteudo = [".png", ".jpg", ".jpeg", ".webp"].includes(ext)
      ? { image: buffer, caption: corpo.legenda || undefined }
      : { document: buffer, mimetype: MIME[ext] || "application/octet-stream",
          fileName: path.basename(caminho), caption: corpo.legenda || undefined };
    const enviado = await sock.sendMessage(jid, conteudo);
    return [200, { ok: true, id: enviado?.key?.id }];
  },

  "GET /conversa": async (_corpo, url) => {
    const pedido = (url.searchParams.get("numero") || "").replace(/\D/g, "");
    const jid = conectado ? await resolverJid(pedido).catch(() => null) : null;
    const chave = jid ? digitos(jid) : pedido;
    const mensagens = [...(conversas.get(chave) || [])].sort((a, b) => a.quando - b.quando);
    return [200, { jid, mensagens }];
  },

  "GET /eventos": async (_corpo, url) => {
    const apos = Number(url.searchParams.get("apos") || 0);
    return [200, { inicio: INICIO, seq, eventos: eventos.filter((e) => e.seq > apos) }];
  },
};

http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORTA}`);
  const rota = rotas[`${req.method} ${url.pathname}`];
  if (!rota) return responder(res, 404, { erro: "rota inexistente" });
  try {
    const corpo = req.method === "POST" ? await lerCorpo(req) : {};
    if (url.pathname !== "/status" && !conectado) return responder(res, 503, { erro: "deslogado" });
    const [codigo, saida] = await rota(corpo, url);
    responder(res, codigo, saida);
  } catch (e) {
    console.error(`[ERRO] ${req.method} ${url.pathname}:`, e?.message || e);
    responder(res, 500, { erro: String(e?.message || e) });
  }
}).listen(PORTA, "127.0.0.1", () => {
  console.log(`Ponte WhatsApp em http://127.0.0.1:${PORTA}`);
  conectar().catch((e) => {
    console.error("[ERRO] Falha ao conectar:", e);
    process.exit(1);
  });
});
