import AppKit
import SwiftUI


struct PaginaSpesa: View {
    let stato: Stato

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: "Spending and API key",
                         sottotitolo: "Paid steps are chosen one by one, and they use your ANTHROPIC_API_KEY") {
            SchedaLottiSospesi(lotti: stato.lotti_in_sospeso ?? [])
            SchedaSpesa(stato: stato)
            SchedaChiavi(chiavi: stato.chiavi ?? [])
        }
    }
}

struct SchedaSpesa: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        let pagati = stato.stadi.filter(\.pagato)
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "Paid steps", conteggio: "\(pagati.count)") {
                Button {
                    Task { await store.preparaStima() }
                } label: {
                    Label(store.stimaInCorso ? "Counting documents…" : "Recompute", systemImage: Simbolo.aggiorna)
                }
                .buttonStyle(.bordered)
                .disabled(store.stimaInCorso || store.modoIstantanea)
                Button {
                    store.apriSpesa()
                } label: {
                    Label("Complete full run…", systemImage: Simbolo.completa)
                }
                .buttonStyle(.borderedProminent)
                .tint(.purple)
                .disabled(store.occupato)
            }
            VStack(spacing: 0) {
                ForEach(Array(pagati.enumerated()), id: \.element.id) { i, s in
                    if i > 0 { Separatore().padding(.leading, 62) }
                    let st = store.stima?.stadi.first(where: { $0.id == s.id })
                    HStack(spacing: 14) {
                        TesseraIcona(simbolo: "creditcard.fill", colore: .purple, lato: 32)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.nome).font(.headline)
                            Text(s.frase).font(Testo.secondario).foregroundStyle(.secondary).lineLimit(1)
                            if let nota = st?.nota, !nota.isEmpty {
                                Text(nota).font(Testo.secondario).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Spacer(minLength: Spazio.fratelli)

                        Pillola(segnale: .stadio(s))
                            .fixedSize()
                        VStack(alignment: .trailing, spacing: 1) {
                            Text(st?.dollari.map { "about \(Int($0.rounded())) $" } ?? (st?.errore ?? "to be computed"))
                                .font(.headline.monospacedDigit())
                            Text(st?.documenti.map { "\($0.formatted()) documents" } ?? " ")
                                .font(Testo.secondario).foregroundStyle(.secondary)
                        }
                        .frame(minWidth: 70, idealWidth: 130, maxWidth: 130, alignment: .trailing)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }
                Separatore()
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Total, if you choose them all").font(.headline)
                        Text(notaStima).font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer()
                    Cifra(testo: store.stima?.totale.map { "about \(Int($0.rounded())) $" } ?? "to be computed", dimensione: 22)
                }
                .padding(16)
                .background(Color.purple.opacity(0.06))
                if let fuori = store.stima?.fuori ?? store.stato?.fuori_stima, !fuori.isEmpty {
                    FuoriDallaStima(voci: fuori).padding(12)
                }
            }
            .scheda(interno: 0)
            .clipShape(RoundedRectangle(cornerRadius: Raggio.scheda, style: .continuous))
        }
    }

    private var notaStima: String {
        if let e = store.erroreStima { return e }
        if store.stimaInCorso { return "Counting the documents to read, without spending anything. It may take a few minutes." }
        guard let s = store.stima else {
            return "No estimate yet. It's computed by counting the documents, without spending, when the pipeline is idle."
        }
        return "Estimate \(Quando.frase(s.quando)), \(s.come ?? "with the Anthropic API key"). The real figure may change."
    }
}


struct SchedaChiavi: View {
    let chiavi: [Chiave]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "Anthropic API key", conteggio: "")
            VStack(spacing: 0) {
                if chiavi.isEmpty {
                    Text("No information about ANTHROPIC_API_KEY yet.")
                        .foregroundStyle(.secondary)
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                ForEach(chiavi) { c in
                    HStack(spacing: 14) {
                        TesseraIcona(simbolo: "key.fill", colore: c.presente == true ? .blue : Color(nsColor: .systemGray), lato: 32)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(c.nome).font(.headline)
                            Text(c.origine.map { "Set in \($0)" } ?? "Not set in .env nor in the environment")
                                .font(Testo.secondario).foregroundStyle(.secondary)
                        }
                        Spacer(minLength: Spazio.fratelli)
                        Pillola(segnale: segnale(c))
                            .fixedSize()
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }
                Separatore()

                Label("Every paid step uses this one key. Put it in .env (or in the environment) to turn the paid steps on, remove it to turn them off. Here you only see whether it is set, never its value.",
                      systemImage: "key.fill")
                    .font(Testo.secondario)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scheda(interno: 0)
        }
    }

    private func segnale(_ c: Chiave) -> Segnale {
        if c.presente == true {
            return Segnale(salute: .ok, simbolo: "checkmark.circle.fill", parola: "set")
        }
        return Segnale(salute: .errore, parola: "missing")
    }
}
