import AppKit
import SwiftUI



enum ChiRisolve {
    static func parola(_ chi: String?) -> String {
        if let p = Vocabolario.parola("chi", chi ?? "") { return p }
        return switch chi {
        case "app": "Fixed from here"
        case "tu": "Your turn"
        case "claude": "Claude fixes it"
        case "nessuno": "Nothing to do"
        default: "To review"
        }
    }

    static func simbolo(_ chi: String?) -> String {
        switch chi {
        case "app": "hand.tap.fill"
        case "tu": "person.fill"
        case "claude": "wrench.and.screwdriver.fill"
        case "nessuno": "checkmark.circle.fill"
        default: "questionmark.circle.fill"
        }
    }

    static func colore(_ chi: String?) -> Color {
        switch chi {
        case "app": .blue
        case "tu": .orange
        case "claude": .purple
        default: .secondary
        }
    }
}



struct SchedaDiagnosi: View {
    let diagnosi: Diagnosi
    let oggetto: Oggetto?

    var pulsanteFonte: Azione? = nil
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(ChiRisolve.parola(diagnosi.chi), systemImage: ChiRisolve.simbolo(diagnosi.chi))
                .font(Testo.secondario.weight(.semibold))
                .foregroundStyle(ChiRisolve.colore(diagnosi.chi))
            Text(diagnosi.causa).font(.body.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
            Text(diagnosi.rimedio).fixedSize(horizontal: false, vertical: true)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: Spazio.fratelli) { pulsanti }
                VStack(alignment: .leading, spacing: 6) { pulsanti }
            }
            DisclosureGroup("Details") {
                VStack(alignment: .leading, spacing: 6) {
                    if let riga = diagnosi.riga, !riga.isEmpty {
                        Text(riga).font(Testo.log)
                    }
                    if let nota = diagnosi.nota, !nota.isEmpty {
                        Text(nota).font(Testo.secondario).foregroundStyle(.secondary)
                    }
                    Text("entry \(diagnosi.id)" + (diagnosi.rc.map { " · exit \($0)" } ?? ""))
                        .font(Testo.log).foregroundStyle(.secondary)
                    if let log = diagnosi.log {
                        Button("Show the log in Finder") {
                            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: log)])
                        }
                        .buttonStyle(.link)
                    }
                }
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 4)
            }
            .font(Testo.secondario)
        }
        .padding(Spazio.interno)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Superficie.incasso, in: RoundedRectangle(cornerRadius: Raggio.piccolo))
    }

    @ViewBuilder private var pulsanti: some View {
        if let a = diagnosi.azione, a.tipo != "copia_per_claude", !uguale(a, pulsanteFonte) {
            if let perche = store.fermo(a) {
                Text(perche).font(Testo.secondario).foregroundStyle(.secondary)
            } else {
                Button(a.etichetta) { store.esegui(a, oggetto: oggetto) }
                    .buttonStyle(.borderedProminent)
            }
        }
        Button {
            Task { await store.apriAgente(diagnosi) }
        } label: {
            Label("Open the agent in the terminal", systemImage: "terminal")
        }
        .buttonStyle(.bordered)
        .disabled(store.apriAgenteInCorso)
        .help("Opens an agent in the terminal with the problem details and starts it")
    }


    private func uguale(_ a: Azione, _ b: Azione?) -> Bool {
        guard let b else { return false }
        return a.arg == b.arg && (a.tipo == b.tipo || (["l0", "da_sola"].contains(a.tipo) && ["l0", "da_sola"].contains(b.tipo)))
    }
}


struct DiagnosiPasso: View {
    let diagnosi: Diagnosi?
    let avvisi: [Diagnosi]
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let d = diagnosi {
                Text(d.causa).font(Testo.secondario.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
                Text(d.rimedio).font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) {
                    Label(ChiRisolve.parola(d.chi), systemImage: ChiRisolve.simbolo(d.chi))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ChiRisolve.colore(d.chi))
                    Spacer(minLength: 4)
                    if let a = d.azione, a.tipo != "copia_per_claude", store.fermo(a) == nil {
                        Button(a.etichetta) { store.esegui(a, oggetto: d.sorgente.map { Oggetto(tipo: "fonte", id: $0) }) }
                            .controlSize(.small)
                    }
                    Button {
                        Task { await store.apriAgente(d) }
                    } label: {
                        Image(systemName: "terminal")
                    }
                    .controlSize(.small)
                    .disabled(store.apriAgenteInCorso)
                    .help("Open agent in the terminal")
                    .accessibilityLabel("Open agent in the terminal")
                }
            }
            ForEach(avvisi, id: \.id) { a in
                Label {
                    Text(a.causa).font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                } icon: {
                    Image(systemName: a.gravita == "nota" ? "info.circle" : "exclamationmark.circle")
                        .foregroundStyle(a.gravita == "nota" ? Color.secondary : Salute.attenzione.colore)
                }
                .help(a.rimedio)
            }
        }
        .padding(.leading, 40)
        .padding(.trailing, 14)
        .padding(.bottom, 6)
    }
}
