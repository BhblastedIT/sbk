import AppKit
import SwiftUI



struct PaginaFonti: View {
    let stato: Stato

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: "Sources", sottotitolo: sottotitolo) {
            ForEach(stato.gruppi_fonti) { gruppo in
                let fonti = stato.fonti.filter { $0.gruppo == gruppo.id }
                if !fonti.isEmpty {
                    GruppoDiFonti(gruppo: gruppo, fonti: fonti)
                }
            }
        }
    }

    private var sottotitolo: String {
        let vive = stato.fonti.filter { ["a_mano", "da_sole", "inventari"].contains($0.gruppo) }
        let ok = vive.filter { ["ok", "in_corso"].contains($0.salute) }.count
        return "\(ok) of \(vive.count) up to date, \(stato.fonti.count) total"
    }
}

struct GruppoDiFonti: View {
    let gruppo: GruppoFonti
    let fonti: [Fonte]
    @Environment(Store.self) private var store
    @Environment(\.accessibilityReduceMotion) private var ridotto

    var body: some View {
        let aperto = !gruppo.chiuso || store.gruppiAperti.contains(gruppo.id)
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: gruppo.nome, conteggio: "\(fonti.count)") {
                Text(gruppo.nota).font(.callout).foregroundStyle(.secondary)
                if gruppo.chiuso {
                    Button(aperto ? "Hide" : "Show") {
                        withAnimation(Movimento.cambio(ridotto)) {
                            if aperto { store.gruppiAperti.remove(gruppo.id) } else { store.gruppiAperti.insert(gruppo.id) }
                        }
                    }
                    .buttonStyle(.link)
                }
            }
            if aperto {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 250), spacing: 12)], spacing: 12) {
                    ForEach(fonti) { f in SchedaFonte(fonte: f) }
                }
                .transition(.opacity)
            }
        }
    }
}

struct SchedaFonte: View {
    let fonte: Fonte
    @Environment(Store.self) private var store
    @State private var sopra = false

    private var scelta: Bool { store.selezione == .fonte(fonte.id) }
    private var spenta: Bool { ["chiuse", "da_collegare"].contains(fonte.gruppo) }

    var body: some View {
        Button {
            store.selezione = .fonte(fonte.id)
            store.ispettore = true
        } label: {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    IconaFonte(fonte: fonte, lato: 32)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(fonte.nome).font(.headline).lineLimit(1)
                        Text(fonte.descrizione).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                HStack(spacing: 8) {

                    Pillola(segnale: .fonte(fonte))
                        .fixedSize()
                    Spacer(minLength: 4)
                    if !spenta {
                        Text(Quando.breve(fonte.dato_del))
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }


            }
            .scheda(interno: 14)
            .overlay {
                RoundedRectangle(cornerRadius: Raggio.scheda, style: .continuous)
                    .strokeBorder(Color.accentColor, lineWidth: scelta ? 2 : 0)
            }
            .opacity(spenta ? 0.75 : 1)
            .contentShape(RoundedRectangle(cornerRadius: Raggio.scheda))
        }
        .buttonStyle(.plain)
        .help(fonte.aiuto ?? fonte.parola)
        .onHover { sopra = $0 }
        .overlay(alignment: .topTrailing) {
            if sopra, let azione = fonte.azione, mostraAzione(azione) {
                Button {
                    store.esegui(azione, oggetto: Oggetto(tipo: "fonte", id: fonte.id))
                } label: {
                    Image(systemName: azione.tipo == "trascrivi_memo" ? "waveform.circle.fill"
                          : ["l0", "da_sola"].contains(azione.tipo) ? "arrow.down.circle.fill"
                          : azione.tipo == "copia_per_claude" ? "terminal.fill" : "questionmark.circle.fill")
                        .font(.system(size: 18))
                        .foregroundStyle(Color.accentColor)
                }
                .buttonStyle(.plain)
                .padding(10)
                .help(azione.etichetta)
            }
        }
        .contextMenu {
            if let azione = fonte.azione, mostraAzione(azione) {
                Button(azione.etichetta) { store.esegui(azione, oggetto: Oggetto(tipo: "fonte", id: fonte.id)) }
            }
            Button("Show the detail") {
                store.selezione = .fonte(fonte.id)
                store.ispettore = true
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(fonte.nome), \(fonte.parola), data from \(Quando.frase(fonte.dato_del))")
    }



    private func mostraAzione(_ azione: Azione) -> Bool {
        store.fermo(azione) == nil
    }
}
