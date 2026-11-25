import SwiftUI




struct PaginaFirme: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: store.firme?.t("titolo") ?? "To sign",
                         sottotitolo: store.firme?.t("sottotitolo") ?? "") {
            if let f = store.firme {
                SchedaVerdettoFirme(firme: f)
                GruppoContratti(firme: f, titolo: f.t("tocca_a_te"), aiuto: f.t("aiuto_tocca_a_te"),
                                voci: f.tocca_a_te, togli: true)
                if !f.da_altri_account.isEmpty {
                    GruppoContratti(firme: f, titolo: f.t("da_altri_account"), aiuto: f.t("aiuto_da_altri_account"),
                                    voci: f.da_altri_account, togli: true)
                }
                if !f.dopo_gli_altri.isEmpty {
                    GruppoContratti(firme: f, titolo: f.t("dopo_gli_altri"), aiuto: f.t("aiuto_dopo_gli_altri"),
                                    voci: f.dopo_gli_altri, togli: false)
                }
                if !f.esclusi.isEmpty { GruppoEsclusi(firme: f) }
            } else if let e = store.erroreFirme {
                Text(e).foregroundStyle(.secondary).scheda()
            } else {
                ProgressView().frame(maxWidth: .infinity).scheda()
            }
        }
        .task { await store.caricaFirme() }
    }
}



struct Firme: Codable, Hashable {
    let ok: Bool
    let verdetto: String
    let da_firmare: Int
    let letto: String
    let tocca_a_te: [ContrattoFirma]
    let da_altri_account: [ContrattoFirma]
    let dopo_gli_altri: [ContrattoFirma]
    let esclusi: [ContrattoEscluso]
    let errori: [String]
    let testi: [String: String]


    func t(_ chiave: String) -> String { testi[chiave] ?? chiave }
}

struct ContrattoFirma: Codable, Hashable, Identifiable {
    let id: String
    let titolo: String
    let da: String
    let tipo: String
    let quando: String
    let frase: String
    let mail: Int
    let link: String?
}

struct ContrattoEscluso: Codable, Hashable, Identifiable {
    let id: String
    let titolo: String
    let frase: String
}



struct SchedaVerdettoFirme: View {
    let firme: Firme
    @Environment(Store.self) private var store

    var body: some View {
        let aPosto = firme.da_firmare == 0 && firme.errori.isEmpty
        HStack(spacing: 14) {
            TesseraIcona(simbolo: aPosto ? "checkmark.circle.fill" : "signature",
                         colore: aPosto ? .green : .orange, lato: 36)
                .help(firme.t("aiuto_tocca_a_te"))
            VStack(alignment: .leading, spacing: 2) {
                Text(firme.verdetto).font(Testo.nome)
                Text(([firme.letto] + firme.errori).joined(separator: " "))
                    .font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: Spazio.fratelli)
            if store.firmeInLettura {
                ProgressView().controlSize(.small).help(firme.t("aiuto_rileggi"))
            }
            Button(firme.t("rileggi")) { Task { await store.caricaFirme(rileggi: true) } }
                .disabled(store.firmeInLettura || store.modoIstantanea)
                .help(firme.t("aiuto_rileggi"))
        }
        .scheda(tinta: aPosto ? .green : .orange)
    }
}



struct GruppoContratti: View {
    let firme: Firme
    let titolo: String
    let aiuto: String
    let voci: [ContrattoFirma]

    let togli: Bool
    @State private var daTogliere: ContrattoFirma?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: titolo, conteggio: "\(voci.count)")
                .help(aiuto)
            VStack(spacing: 0) {
                ForEach(Array(voci.enumerated()), id: \.element.id) { i, c in
                    if i > 0 { Separatore().padding(.leading, 52) }
                    riga(c)
                }
                if voci.isEmpty {
                    Text(firme.t("nessuno")).font(Testo.secondario).foregroundStyle(.secondary)
                        .padding(14)
                }
            }
            .scheda(interno: 0)
        }
        .sheet(item: $daTogliere) { c in FoglioNonFirmo(firme: firme, contratto: c) }
    }

    private func riga(_ c: ContrattoFirma) -> some View {
        HStack(alignment: .top, spacing: 12) {
            TesseraIcona(simbolo: c.tipo == "dopo" ? "person.2.fill" : "signature",
                         colore: c.tipo == "dopo" ? .gray : .orange, lato: 26)
                .help(aiuto)
            VStack(alignment: .leading, spacing: 2) {
                Text(c.titolo).font(Testo.corpo).fixedSize(horizontal: false, vertical: true)
                Text([c.da, c.frase].filter { !$0.isEmpty }.joined(separator: ". "))
                    .font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: Spazio.fratelli)
            if c.mail > 0 {
                Text("\(c.mail) mail").font(Testo.cifreInColonna).foregroundStyle(.secondary)
                    .help(firme.t("aiuto_promemoria"))
            }
            if let s = c.link, let url = URL(string: s) {
                Button(firme.t("apri")) { NSWorkspace.shared.open(url) }
                    .help(firme.t("aiuto_apri"))
            } else if c.tipo != "dopo" {

                Text(firme.t("senza_mail")).font(Testo.minimo).foregroundStyle(.secondary)
            }
            if togli {
                Button(firme.t("non_firmo")) { daTogliere = c }
                    .help(firme.t("aiuto_non_firmo"))
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }
}


struct FoglioNonFirmo: View {
    let firme: Firme
    let contratto: ContrattoFirma
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi
    @State private var perche = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("\(firme.t("foglio_titolo")) \(contratto.titolo)").font(Testo.titoloSezione)
                .fixedSize(horizontal: false, vertical: true)
            TextField(firme.t("foglio_perche"), text: $perche, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...4)
            Text(firme.t("foglio_nota"))
                .font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button(firme.t("foglio_annulla"), role: .cancel) { chiudi() }
                    .keyboardShortcut(.cancelAction)
                Button(firme.t("foglio_conferma")) {
                    let c = contratto
                    let p = perche
                    chiudi()
                    Task { await store.escludiFirma(c, perche: p) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(perche.trimmingCharacters(in: .whitespaces).isEmpty)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 460)
    }
}



struct GruppoEsclusi: View {
    let firme: Firme
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: firme.t("esclusi"), conteggio: "\(firme.esclusi.count)")
                .help(firme.t("aiuto_esclusi"))
            VStack(spacing: 0) {
                ForEach(Array(firme.esclusi.enumerated()), id: \.element.id) { i, c in
                    if i > 0 { Separatore().padding(.leading, 14) }
                    HStack(alignment: .top, spacing: 12) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(c.titolo).font(Testo.corpo).fixedSize(horizontal: false, vertical: true)
                            Text(c.frase).font(Testo.secondario).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: Spazio.fratelli)
                        Button(firme.t("rimetti")) { Task { await store.riammettiFirma(c.id) } }
                            .disabled(store.modoIstantanea)
                            .help(firme.t("aiuto_rimetti"))
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                }
            }
            .scheda(interno: 0)
        }
    }
}
