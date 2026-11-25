import SwiftUI



struct PulsantePausa: View {
    let run: Run
    @Environment(Store.self) private var store

    var body: some View {
        if let c = store.comandiRun ?? run.comandi, !store.fermoRichiesto.contains(run.run_id) {
            if c.continua.possibile {
                Button {
                    Task { await store.continua(run) }
                } label: {
                    Label("Continue", systemImage: "play.fill")
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
                .help("The run resumes from the step where it was waiting")
            } else if c.pausa.possibile {
                Button {
                    Task { await store.pausa(run) }
                } label: {
                    Label("Pause", systemImage: "pause.fill")
                }
                .buttonStyle(.bordered)
                .help(c.pausa.frase ?? "The current step finishes, then the run waits")
            }
        }
    }
}



struct RigaPausa: View {
    let run: Run
    @Environment(Store.self) private var store

    var body: some View {
        if let c = store.comandiRun ?? run.comandi {
            if !c.frase.isEmpty {
                Label(c.frase, systemImage: c.continua.possibile ? "pause.circle.fill" : "hourglass")
                    .foregroundStyle(c.continua.possibile ? Color.orange : .secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if !c.pausa.possibile, let perche = c.pausa.perche, !perche.isEmpty {
                Label(perche, systemImage: "pause.circle")
                    .font(Testo.secondario)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}


struct SchedaRipresa: View {
    let ripresa: Ripresa
    @Environment(Store.self) private var store

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            TesseraIcona(simbolo: "arrow.clockwise", colore: ripresa.spende ? .purple : .blue, lato: 40)
            VStack(alignment: .leading, spacing: 6) {
                Text("A full run did not finish").font(.headline)
                Text(ripresa.frase).fixedSize(horizontal: false, vertical: true)
                if let perche = store.fermo(ripresa.azione) {
                    Text(perche).font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: Spazio.fratelli)
            if store.fermo(ripresa.azione) == nil {
                Button(ripresa.azione.etichetta) { store.foglio = .riprendi(ripresa) }
                    .buttonStyle(.borderedProminent)
                    .tint(ripresa.spende ? .purple : .accentColor)
                    .controlSize(.large)
            }
        }
        .scheda(interno: 16, tinta: ripresa.spende ? .purple : .blue)
    }
}


struct SchedaLottiSospesi: View {
    let lotti: [LottoSospeso]
    @Environment(Store.self) private var store

    var body: some View {
        if !lotti.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Label("Paid batches to collect", systemImage: "shippingbox.fill")
                    .font(.headline)
                    .foregroundStyle(.purple)
                ForEach(lotti) { l in
                    Text(riga(l)).fixedSize(horizontal: false, vertical: true)
                    if l.dati_nuovi_dopo == true {
                        Label("New data has arrived since then. Before resuming, the batch ids must be fixed, otherwise the answers can end up on the wrong documents.",
                              systemImage: Simbolo.attenzione)
                            .font(Testo.secondario)
                            .foregroundStyle(.orange)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                if store.stato?.ripresa?.spende == true {
                    Text("Resume the full run to collect them without paying again.")
                        .font(Testo.secondario).foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .scheda(interno: 16, tinta: .purple)
        }
    }

    private func riga(_ l: LottoSospeso) -> String {
        guard l.leggibile, let n = l.lotti else {
            return "\(l.nome), the batch status can't be read."
        }
        let quanti = n == 1 ? "one batch already paid and not yet collected" : "\(n) batches already paid and not yet collected"
        return "\(l.nome), \(quanti), sent \(Quando.frase(l.inviati))."
    }
}
