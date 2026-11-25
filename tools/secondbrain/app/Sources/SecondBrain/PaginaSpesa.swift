import AppKit
import SwiftUI


struct PaginaSpesa: View {
    let stato: Stato

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: "Spending and keys",
                         sottotitolo: "Paid steps are chosen one by one, the keys take turns") {
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
            TitoloGruppo(titolo: "Anthropic API keys", conteggio: "\(chiavi.count)")
            VStack(spacing: 0) {
                if chiavi.isEmpty {
                    Text("No key in the queue. To add one ask Claude, it puts it in the Keychain under its name.")
                        .foregroundStyle(.secondary)
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                ForEach(Array(chiavi.enumerated()), id: \.element.id) { i, c in
                    if i > 0 { Separatore().padding(.leading, 62) }
                    HStack(spacing: 14) {
                        TesseraIcona(simbolo: "key.fill", colore: c.paga == true ? .blue : Color(nsColor: .systemGray), lato: 32)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(c.nome).font(.headline)
                            Text(c.origine.map { "Taken from \($0), kept in the Keychain" } ?? "In the Keychain")
                                .font(Testo.secondario).foregroundStyle(.secondary)
                        }
                        Spacer(minLength: Spazio.fratelli)
                        Pillola(segnale: segnale(c))
                            .fixedSize()
                        Text(uso(c))
                            .font(Testo.secondario.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .frame(minWidth: 70, idealWidth: 150, maxWidth: 150, alignment: .trailing)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }
                Separatore()

                Label("Every run that spends charges the next key. A key whose quota ran out stays idle for a day, one rejected by Anthropic stays idle until you replace it. Here you only see the names, the keys live in the Keychain.",
                      systemImage: "arrow.triangle.2.circlepath")
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
        if c.presente == false {
            return Segnale(salute: .errore, parola: "missing from the Keychain")
        }
        if let errore = c.errore {


            let altra = chiavi.contains { $0.paga == true }
            return Segnale(salute: altra ? .neutra : .attenzione, parola: "\(errore), set aside")
        }


        if c.paga == true {
            return Segnale(salute: .ok, simbolo: "arrow.right.circle.fill", parola: "its turn")
        }
        return Segnale(salute: .neutra, simbolo: "clock", parola: "reserve")
    }

    private func uso(_ c: Chiave) -> String {
        guard let t = c.ultimo_uso else { return "never used from here" }
        return "used " + Quando.frase(Quando.parser.string(from: Date(timeIntervalSince1970: t)))
    }
}
