import SwiftUI












extension Store {


    var avvisiInteri: Bool { sezione == .panoramica }
}



struct MenuRun: View {
    @Environment(Store.self) private var store

    var body: some View {
        if store.runVivo != nil {
            PulsantiRun()
        } else {
            Menu {
                VociMenuRun()
            } label: {
                Label(ParoleBarra.nomeFull(store.stato), systemImage: Simbolo.fullRun)
            } primaryAction: {
                store.foglio = .fullRun
            }
            .labelStyle(.titleAndIcon)
            .fixedSize()
            .disabled(store.occupato)
            .help(store.occupato ? (store.daCache ? "Checking what's running, one moment." : store.stato?.azioni.perche ?? "One run at a time.")
                                 : ParoleBarra.aiutoRun(store.stato))
        }
    }
}


struct VoceMenuRun: Identifiable {
    enum Gesto { case full, voce(VoceMenu), completa }
    let id: String
    let nome: String
    let frase: String
    let gesto: Gesto
}




struct VociMenuRun: View {
    @Environment(Store.self) private var store

    var body: some View {
        let (sopra, sotto) = ParoleBarra.vociMenu(store.stato, store)
        ForEach(sopra) { voce(for: $0) }
        Divider()
        ForEach(sotto) { voce(for: $0) }
    }

    private func voce(for v: VoceMenuRun) -> some View {
        Button {
            switch v.gesto {
            case .full: store.foglio = .fullRun
            case .voce(let m): store.apri(m)
            case .completa: store.apriSpesa()
            }
        } label: {
            Text(v.nome)
            if !v.frase.isEmpty { Text(v.frase) }
        }
    }
}


enum ParoleBarra {

    static func nomeFull(_ stato: Stato?) -> String {
        stato?.azioni.menu.first { $0.id == "full" }?.nome.nonVuoto ?? "Full run free"
    }


    static func nomeCompleta(_ stato: Stato?) -> String {
        stato?.azioni.menu.first { $0.id == "full_completa" }?.nome.nonVuoto ?? "Full run complete"
    }




    static func aiutoRun(_ stato: Stato?) -> String {
        var frase = stato?.azioni.menu.first { $0.id == "full" }?.frase.nonVuoto
            ?? "Downloads all sources, then re-reads and updates, at no cost"
        while frase.hasSuffix(".") { frase.removeLast() }
        return "\(frase) (⇧⌘R). From the arrow, the other runs and the \(nomeCompleta(stato))."
    }


    @MainActor static func vociMenu(_ stato: Stato?, _ store: Store) -> ([VoceMenuRun], [VoceMenuRun]) {
        let menu = stato?.azioni.menu ?? []
        let full = menu.first { $0.id == "full" }
        let altri = menu.filter { !["full", "full_completa"].contains($0.id) }
        var sopra = [VoceMenuRun(id: "full", nome: "\(nomeFull(stato))…",
                                 frase: full?.frase ?? "Downloads all sources, then re-reads and updates, at no cost.",
                                 gesto: .full)]
        sopra += altri.filter { !$0.spesa }.map { VoceMenuRun(id: $0.id, nome: "\($0.nome)…", frase: $0.frase, gesto: .voce($0)) }
        var sotto = altri.filter(\.spesa).map { VoceMenuRun(id: $0.id, nome: "\($0.nome)…", frase: $0.frase, gesto: .voce($0)) }
        if let stato {
            let (nome, frase) = completa(stato, store)
            sotto.append(VoceMenuRun(id: "full_completa", nome: nome, frase: frase, gesto: .completa))
        }
        return (sopra, sotto)
    }




    @MainActor static func completa(_ stato: Stato, _ store: Store) -> (String, String) {
        let stima = store.stima?.totale.map {
            stato.c("aiuto_bottone_stima", ["cifra": stato.c("cifra", ["n": Cifre.conPunti($0)])])
        } ?? ""
        guard let voce = stato.azioni.menu.first(where: { $0.id == "full_completa" }), !voce.nome.isEmpty else {
            return ("\(stato.c("bottone"))…", [stato.c("aiuto_bottone"), stima].filter { !$0.isEmpty }.joined(separator: " "))
        }
        return ("\(voce.nome)…", [voce.frase, stima].filter { !$0.isEmpty }.joined(separator: " "))
    }



    static func avvisi(_ n: Int, _ frase: String) -> String {
        let clic = n == 1 ? "Click to see it." : "Click to see them."
        return [etichettaAvvisi(n, frase), clic].joined(separator: " ")
    }



    static func etichettaAvvisi(_ n: Int, _ frase: String) -> String {
        let prima = primaFrase(frase)
        let conto = n == 1 ? "1 alert." : "\(n) alerts."
        return prima.isEmpty ? conto : "\(conto) \(prima)"
    }


    static func primaFrase(_ testo: String) -> String {
        let t = testo.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return "" }
        let prima = t.range(of: ". ").map { String(t[..<$0.lowerBound]) } ?? t
        return prima.hasSuffix(".") ? prima : prima + "."
    }
}

extension String {

    var nonVuoto: String? { isEmpty ? nil : self }
}





struct SegnoAvvisi: View {
    @Environment(Store.self) private var store

    @AppStorage("lavoriNascosti") private var nascosti = ""
    @State private var aperto = false

    var body: some View {
        if !store.avvisiInteri, let stato = store.stato {
            let avvisi = Fasce.avvisi(stato, store, nascoste: Set(nascosti.split(separator: "\n").map(String.init)))
            if let peggiore = Salute.peggiore(avvisi.map(\.salute)),
               let primo = avvisi.first(where: { $0.salute == peggiore }) {
                let corto = avvisi.count == 1 ? primo.corto : nil
                Button { aperto.toggle() } label: {
                    HStack(spacing: 5) {
                        Image(systemName: peggiore.simbolo).foregroundStyle(peggiore.colore)


                        Text(corto ?? "\(avvisi.count)").monospacedDigit().foregroundStyle(.primary)
                    }
                    .font(.callout.weight(.semibold))
                    .lineLimit(1)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(peggiore.colore.opacity(0.14), in: Capsule())
                }
                .buttonStyle(.plain)

                .fixedSize()
                .help(ParoleBarra.avvisi(avvisi.count, primo.frase))
                .accessibilityLabel(ParoleBarra.etichettaAvvisi(avvisi.count, primo.frase))
                .popover(isPresented: $aperto, arrowEdge: .bottom) {
                    ElencoAvvisi(stato: stato)
                        .environment(store)
                }


                .onChange(of: store.sezione) { aperto = false }
            }
        }
    }
}


struct ElencoAvvisi: View {
    let stato: Stato

    var body: some View {


        Fasce(stato: stato, quali: .segno, pulsantiSotto: true)
            .padding(14)
            .frame(width: 560)
    }
}

extension Salute {

    static func peggiore(_ elenco: [Salute]) -> Salute? {
        let ordine: [Salute] = [.errore, .attenzione, .inCorso, .neutra, .ok]
        return ordine.first { elenco.contains($0) }
    }
}





struct BarraFinta: View {
    @Environment(Store.self) private var store

    var body: some View {
        HStack(spacing: Spazio.griglia) {
            Text("SBK").font(.headline).frame(width: 200, alignment: .leading)
            Spacer()
            HStack(spacing: Spazio.fratelli) {
                Capsula().fixedSize()
                SegnoAvvisi()
            }
            Spacer()
            MenuRun()
            Image(systemName: Simbolo.ispettore).foregroundStyle(.secondary)

            PulsanteCompleta()
        }
        .padding(.horizontal, Spazio.margine)
        .padding(.vertical, 10)
        .background(Superficie.pagina)
    }
}



struct ApertoNellaPagina: View {
    @Environment(Store.self) private var store

    var body: some View {
        let env = ProcessInfo.processInfo.environment
        if env["SB_MENU_RUN"] == "1" {
            VStack(alignment: .leading, spacing: 0) {
                MenuDisegnato()
            }
            .frame(width: 360, alignment: .leading)
            .padding(.vertical, 6)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).strokeBorder(Superficie.separatore))
            .shadow(color: .black.opacity(0.18), radius: 12, y: 4)
            .frame(maxWidth: .infinity, alignment: .trailing)

            .padding(.trailing, destraMenuDisegnato)
            .padding(.top, 2)
        } else if env["SB_AVVISI_APERTI"] == "1", let stato = store.stato {
            ElencoAvvisi(stato: stato)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Superficie.separatore))
                .shadow(color: .black.opacity(0.18), radius: 12, y: 4)
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.top, 2)
        }
    }
}




private let destraMenuDisegnato: CGFloat = 161


private struct MenuDisegnato: View {
    @Environment(Store.self) private var store

    var body: some View {
        let (sopra, sotto) = ParoleBarra.vociMenu(store.stato, store)
        ForEach(sopra) { voce($0.nome, $0.frase) }

        Rectangle().fill(Color.primary.opacity(0.15)).frame(height: 1).padding(.vertical, 4).padding(.horizontal, 10)
        ForEach(sotto) { voce($0.nome, $0.frase) }
    }

    private func voce(_ nome: String, _ frase: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(nome).font(.body)
            if !frase.isEmpty { Text(frase).font(.caption).foregroundStyle(.secondary).lineLimit(3) }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
