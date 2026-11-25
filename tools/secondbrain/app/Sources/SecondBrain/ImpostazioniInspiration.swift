import SwiftUI







struct ImpostazioniApp: View {
    @Environment(Store.self) private var store

    var body: some View {
        @Bindable var store = store
        TabView(selection: $store.schedaImpostazioni) {
            PannelloImpostazioniCose()
                .tabItem { Label(Sezione.cose.nome, systemImage: Sezione.cose.simbolo) }
                .tag(Store.schedaAttivita)
            PannelloImpostazioniInspiration()
                .tabItem { Label(Sezione.inspiration.nome, systemImage: Sezione.inspiration.simbolo) }
                .tag(Store.schedaInspiration)
        }
    }
}





struct ImpostazioniInspiration: Codable, Hashable {
    let titolo: String
    let voci: [VoceImpostazione]

    enum CodingKeys: String, CodingKey { case titolo, voci }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        titolo = p.testo(.titolo)
        voci = (p.elenco(.voci) as [VoceImpostazione]).filter { !$0.chiave.isEmpty }
    }
}




struct VoceImpostazione: Codable, Hashable, Identifiable {
    let chiave: String
    let nome: String
    let tipo: String
    let valore: ValoreImpostazione?
    let frase: String
    let da_chi_quando: String
    let dipende: Bool
    let minimo: Int?
    let massimo: Int?
    let cambia: CambiaImpostazione?

    var id: String { chiave }
    var numero: Bool { tipo == "numero" }

    enum CodingKeys: String, CodingKey { case chiave, nome, tipo, valore, frase, da_chi_quando, dipende, minimo, massimo, cambia }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        chiave = p.testo(.chiave)
        nome = p.testo(.nome)
        tipo = p.testo(.tipo)
        valore = p.uno(.valore)
        frase = p.testo(.frase)
        da_chi_quando = p.testo(.da_chi_quando)
        dipende = p.si(.dipende)
        minimo = p.numero(.minimo)
        massimo = p.numero(.massimo)

        cambia = (p.uno(.cambia) as CambiaImpostazione?).flatMap { $0.riga.isEmpty ? nil : $0 }
    }
}


enum ValoreImpostazione: Codable, Hashable {
    case si(Bool)
    case numero(Int)

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let b = try? c.decode(Bool.self) { self = .si(b); return }
        if let n = try? c.decode(Int.self) { self = .numero(n); return }
        throw DecodingError.dataCorruptedError(in: c, debugDescription: "neither true/false nor a number")
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .si(let b): try c.encode(b)
        case .numero(let n): try c.encode(n)
        }
    }

    var acceso: Bool? { if case .si(let b) = self { return b } else { return nil } }
    var intero: Int? { if case .numero(let n) = self { return n } else { return nil } }
}


struct CambiaImpostazione: Codable, Hashable {
    let verbo: String
    let riga: String
    let parola: String
    let aiuto: String

    enum CodingKeys: String, CodingKey { case verbo, riga, parola, aiuto }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        verbo = p.testo(.verbo)
        riga = p.testo(.riga)
        parola = p.testo(.parola)
        aiuto = p.testo(.aiuto)
    }
}








struct PannelloImpostazioniInspiration: View {
    @Environment(Store.self) private var store

    @State private var inCorso: String?

    @State private var errore: ErroreVoce?

    struct ErroreVoce: Equatable {
        let chiave: String
        let testo: String
    }

    var body: some View {
        Group {
            if let imp = store.inspiration?.impostazioni {
                ScrollView {


                    VStack(alignment: .leading, spacing: 18) {
                        ForEach(imp.voci) { v in riga(v) }
                    }
                    .padding(20)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else if store.inspiration == nil {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {

                Text(store.inspiration?.t("impostazioni_mancano", o: "Inspiration settings are not coming from the engine.")
                     ?? "")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(minWidth: 640, minHeight: 460)
        .task { if store.inspiration == nil { await store.caricaInspiration(motivo: "impostazioni") } }
    }

    @ViewBuilder
    private func riga(_ v: VoceImpostazione) -> some View {
        let toccabile = v.cambia != nil
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .center, spacing: 10) {
                Text(v.nome).font(.system(size: 13, weight: .medium))
                Spacer(minLength: 12)
                if inCorso == v.chiave { ProgressView().controlSize(.small) }

                controllo(v)
                    .disabled(!toccabile || inCorso != nil)
                    .accessibilityLabel(v.nome)
            }
            Text(v.frase)
                .font(.system(size: 12)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if !v.da_chi_quando.isEmpty {
                Text(v.da_chi_quando).font(.system(size: 11)).foregroundStyle(.tertiary)
            }
            if let e = errore, e.chiave == v.chiave {
                Text(e.testo).font(.system(size: 12)).foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }

        .opacity(toccabile ? 1 : 0.55)
    }

    @ViewBuilder
    private func controllo(_ v: VoceImpostazione) -> some View {
        if v.numero {
            let basso = v.minimo ?? 1
            let alto = max(v.massimo ?? basso, basso)

            Picker("", selection: Binding(get: { v.valore?.intero ?? basso }, set: { fai(v, numero: $0) })) {
                ForEach(basso...alto, id: \.self) { n in Text(giorni(n)).tag(n) }
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .fixedSize()
        } else {
            Toggle("", isOn: Binding(get: { v.valore?.acceso == true }, set: { _ in fai(v, numero: nil) }))
                .toggleStyle(.switch)
                .labelsHidden()
        }
    }


    private func giorni(_ n: Int) -> String {
        let i = store.inspiration
        let forma = n == 1 ? (i?.t("imp_giorno", o: "{n} day") ?? "{n} day") : (i?.t("imp_giorni", o: "{n} days") ?? "{n} days")
        return forma.replacingOccurrences(of: "{n}", with: String(n))
    }



    private func fai(_ v: VoceImpostazione, numero: Int?) {
        guard let c = v.cambia, inCorso == nil else { return }
        var argomenti = c.riga.split(separator: " ").map(String.init)
        if v.numero {
            guard let n = numero, n != v.valore?.intero else { return }
            argomenti.append(String(n))
        }
        inCorso = v.chiave
        errore = nil
        Task {
            let esito = await store.azioneInspiration(argomenti)
            inCorso = nil
            if let esito { errore = ErroreVoce(chiave: v.chiave, testo: esito) }
        }
    }
}
