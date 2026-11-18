async function chamar(caminho, opcoes) {
  const resposta = await fetch(`/api${caminho}`, opcoes);
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    throw new Error(corpo?.detail || `Erro ${resposta.status}`);
  }
  return corpo;
}

export const listarLotes = () => chamar("/lotes");
export const buscarLote = (id) => chamar(`/lotes/${id}`);
export const buscarFalhas = (id) => chamar(`/lotes/${id}/falhas`);
export const auditar = (id) => chamar(`/lotes/${id}/auditoria`);
export const reprocessar = (id) => chamar(`/lotes/${id}/reprocessar`, { method: "POST" });

export function enviarCsv(arquivo) {
  const dados = new FormData();
  dados.append("arquivo", arquivo);
  return chamar("/lotes", { method: "POST", body: dados });
}
