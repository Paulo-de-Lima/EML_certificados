import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api.js";

const numero = (n) => n.toLocaleString("pt-BR");

export default function App() {
  const [lotes, setLotes] = useState([]);
  const [loteId, setLoteId] = useState(null);
  const [erro, setErro] = useState(null);

  const carregarLotes = useCallback(async () => {
    try {
      const lista = await api.listarLotes();
      setLotes(lista);
      setLoteId((atual) => atual ?? lista[0]?.id ?? null);
    } catch (e) {
      setErro(e.message);
    }
  }, []);

  useEffect(() => {
    carregarLotes();
  }, [carregarLotes]);

  function aoCriar(lote) {
    setLoteId(lote.id);
    carregarLotes();
  }

  return (
    <main>
      <header>
        <h1>Emissão de certificados em lote</h1>
        <nav>
          <a href="http://localhost:8025" target="_blank" rel="noreferrer">Caixa de e-mail (Mailpit)</a>
          <a href="http://localhost:15672" target="_blank" rel="noreferrer">Fila (RabbitMQ)</a>
          <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">API</a>
        </nav>
      </header>

      {erro && <p className="aviso erro">{erro}</p>}

      <Upload aoCriar={aoCriar} />

      {lotes.length > 1 && (
        <section className="cartao">
          <label>
            Lote:{" "}
            <select value={loteId ?? ""} onChange={(e) => setLoteId(Number(e.target.value))}>
              {lotes.map((l) => (
                <option key={l.id} value={l.id}>
                  #{l.id} · {l.nome_arquivo} · {new Date(l.criado_em).toLocaleString("pt-BR")}
                </option>
              ))}
            </select>
          </label>
        </section>
      )}

      {loteId && <Lote key={loteId} id={loteId} />}
    </main>
  );
}

function Upload({ aoCriar }) {
  const [enviando, setEnviando] = useState(false);
  const [mensagem, setMensagem] = useState(null);
  const campo = useRef(null);

  async function enviar(evento) {
    evento.preventDefault();
    const arquivo = campo.current.files[0];
    if (!arquivo) return;
    setEnviando(true);
    setMensagem(null);
    const inicio = performance.now();
    try {
      const lote = await api.enviarCsv(arquivo);
      const ms = Math.round(performance.now() - inicio);
      setMensagem({
        tipo: "ok",
        texto: `202 Accepted em ${ms} ms — lote #${lote.id} com ${numero(lote.total)} participantes entrou na fila.`,
      });
      campo.current.value = "";
      aoCriar(lote);
    } catch (e) {
      setMensagem({ tipo: "erro", texto: e.message });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="cartao">
      <h2>Novo lote</h2>
      <form onSubmit={enviar}>
        <input ref={campo} type="file" accept=".csv,text/csv" required />
        <button disabled={enviando}>{enviando ? "Enviando…" : "Enviar CSV"}</button>
      </form>
      <p className="dica">Arquivo CSV com as colunas <code>nome</code> e <code>email</code>.</p>
      {mensagem && <p className={`aviso ${mensagem.tipo}`}>{mensagem.texto}</p>}
    </section>
  );
}

function Lote({ id }) {
  const [lote, setLote] = useState(null);
  const [falhas, setFalhas] = useState([]);
  const [auditoria, setAuditoria] = useState(null);
  const [erro, setErro] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  const atualizar = useCallback(async () => {
    try {
      const [l, f] = await Promise.all([api.buscarLote(id), api.buscarFalhas(id)]);
      setLote(l);
      setFalhas(f);
      setErro(null);
      return l;
    } catch (e) {
      setErro(e.message);
      return null;
    }
  }, [id]);

  // Consulta o progresso a cada segundo enquanto o lote estiver em andamento.
  const emAndamento = !lote || lote.status === "PROCESSANDO";
  useEffect(() => {
    atualizar();
    if (!emAndamento) return;
    const timer = setInterval(atualizar, 1000);
    return () => clearInterval(timer);
  }, [atualizar, emAndamento]);

  async function executar(acao) {
    setOcupado(true);
    setErro(null);
    try {
      await acao();
    } catch (e) {
      setErro(e.message);
    } finally {
      setOcupado(false);
    }
  }

  const aoReprocessar = () =>
    executar(async () => {
      setAuditoria(null);
      setLote(await api.reprocessar(id));
    });
  const aoAuditar = () => executar(async () => setAuditoria(await api.auditar(id)));

  if (!lote) return <section className="cartao">{erro ?? "Carregando…"}</section>;

  const pct = lote.total ? (lote.processados / lote.total) * 100 : 0;
  const reprocessaveis = falhas.filter((f) => f.pode_reprocessar).length;

  return (
    <>
      <section className="cartao">
        <h2>
          Lote #{lote.id} <small>{lote.nome_arquivo}</small>
          <span className={`etiqueta ${lote.status.toLowerCase()}`}>
            {lote.status === "CONCLUIDO" ? "Concluído" : "Processando"}
          </span>
        </h2>

        <p className="progresso-texto">
          <strong>{numero(lote.processados)}</strong> de {numero(lote.total)}
        </p>
        <div className="barra" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
          <div style={{ width: `${pct}%` }} />
        </div>

        <dl className="numeros">
          <div><dt>Enviados</dt><dd className="verde">{numero(lote.enviados)}</dd></div>
          <div><dt>Falhas</dt><dd className="vermelho">{numero(lote.falhas)}</dd></div>
          <div><dt>Pendentes</dt><dd>{numero(lote.pendentes)}</dd></div>
        </dl>

        <div className="acoes">
          <button onClick={aoAuditar} disabled={ocupado}>Auditar (banco × caixa de e-mail)</button>
          <button onClick={aoReprocessar} disabled={ocupado} className="secundario">
            Reprocessar pendentes e falhas{reprocessaveis ? ` (${reprocessaveis})` : ""}
          </button>
        </div>

        {erro && <p className="aviso erro">{erro}</p>}
        {auditoria && <Auditoria dados={auditoria} />}
      </section>

      <section className="cartao">
        <h2>Falhas ({numero(lote.falhas)})</h2>
        {falhas.length === 0 ? (
          <p className="dica">Nenhuma falha.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Linha</th><th>Nome</th><th>E-mail</th><th>Motivo</th><th>Tentativas</th></tr>
            </thead>
            <tbody>
              {falhas.map((f) => (
                <tr key={f.linha}>
                  <td>{f.linha}</td>
                  <td>{f.nome || "—"}</td>
                  <td>{f.email || "—"}</td>
                  <td>{f.erro}</td>
                  <td>{f.pode_reprocessar ? f.tentativas : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

function Auditoria({ dados }) {
  return (
    <div className={`aviso ${dados.ok ? "ok" : "erro"}`}>
      <strong>{dados.ok ? "Tudo certo." : "Diferenças encontradas."}</strong>{" "}
      {numero(dados.enviados_no_banco)} enviados no banco · {numero(dados.emails_na_caixa)} e-mails na caixa ·{" "}
      {numero(dados.duplicados)} duplicados · {numero(dados.perdidos)} perdidos
      {dados.nao_registrados > 0 && (
        <> · {numero(dados.nao_registrados)} na caixa ainda sem registro no banco (tarefa em andamento)</>
      )}
      {["duplicados", "perdidos"].map(
        (tipo) =>
          dados.exemplos[tipo].length > 0 && (
            <div key={tipo}>
              {tipo}: {dados.exemplos[tipo].join(", ")}
            </div>
          )
      )}
    </div>
  );
}
