import AppKit
import SwiftUI













struct CambioProposto: Codable, Hashable {
    let id: String?
    let titolo: String?
    let cosa: String?
    let campo: String?
    let perde: String?
}



struct AperturaVoce: Codable, Hashable {
    let vista: String?
    let filtro: [String: [String]]?
    let task: String?

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: ChiaveLibera.self)
        vista = (try? c.decodeIfPresent(String.self, forKey: .init("vista"))) ?? nil
        task = (try? c.decodeIfPresent(String.self, forKey: .init("task"))) ?? nil
        if let f = try? c.decodeIfPresent([String: [String]].self, forKey: .init("filtro")) {
            filtro = f
        } else if let f = try? c.decodeIfPresent([String: String].self, forKey: .init("filtro")) {
            filtro = f.mapValues { [$0] }
        } else {
            filtro = nil
        }
    }
}


struct AnnullataPrima: Codable, Hashable {
    let id: String?
    let ok: Bool?
    let messaggio: String?
    let rimesse: Int?
}



@MainActor
@Observable
final class StatoConversazione {
    static let condiviso = StatoConversazione()


    var aperta = ProcessInfo.processInfo.environment["SB_FILO"] == "1"

    var risposte: [String: String] = [:]



    @discardableResult
    func mandaRisposta(_ store: Store, id: String, argomenti: [String]) async -> Bool {
        let t = (risposte[id] ?? "").trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return false }
        var a = argomenti.map { $0 == "<la tua risposta>" ? t : $0 }

        if a.first == "voce-testo" { a += ["--una-volta", store.chiaveVoce(id + "|" + t)] }
        guard await store.azioneVoce(a) else { return false }
        store.voceChiaviInVolo[id + "|" + t] = nil
        if risposte[id]?.trimmingCharacters(in: .whitespaces) == t { risposte[id] = nil }
        return true
    }

    @ObservationIgnored var chiedeViste: Set<String> = []

    @ObservationIgnored var apriViste: Set<String> = []
    @ObservationIgnored var apriLetto = false

    var lettoAlle = Date()
    var testo = ""
}




enum ContestoVoce {

    nonisolated(unsafe) static var argomenti: [String] = []
}

extension Store {

    var contestoVoce: [String] {


        guard voceAttivita?.contesto == true else { return [] }
        var a = ["--vista", coseVista]
        let scelte = idsAzione
        if !scelte.isEmpty { a += ["--scelte", scelte.joined(separator: ",")] }
        return a
    }



    func chiaveVoce(_ messaggio: String) -> String {
        if let k = voceChiaviInVolo[messaggio] { return k }
        let k = UUID().uuidString.lowercased()
        voceChiaviInVolo[messaggio] = k
        return k
    }

    func tv(_ chiave: String) -> String {
        voceAttivita?.testi?[chiave] ?? t(chiave)
    }



    func fraseLavoroDa(_ secondi: Int) -> String {
        let m = secondi / 60
        let chiave = m == 1 ? "lavoro_da_minuto" : "lavoro_da_minuti"
        let c = voceAttivita?.testi?[chiave] ?? cose?.testi?[chiave]
        guard secondi >= 60, let c else { return tv("lavoro_da").replacingOccurrences(of: "{n}", with: secondi.formatted()) }
        return c.replacingOccurrences(of: "{n}", with: m.formatted())
    }


    func chiediAllaLista(_ testo: String) async -> Bool {
        guard !modoIstantanea, !bloccaGesto() else { return false }


        let e = try? JSONDecoder().decode(EsitoVoce.self,
                                          from: await motore.chiedi(["cose", "voce-testo", testo] + contestoVoce + ["--una-volta", chiaveVoce(testo)], scadenza: 20).dati)
        if e?.ok == true { voceChiaviInVolo[testo] = nil }


        coseEsito = EsitoRiga(testo: e?.ok == true ? (e?.messaggio ?? "") : (e?.errore ?? t("errore_motore")), errore: e?.ok != true,
                              riprova: e == nil ? ["voce-testo", testo] : nil)
        seguiVoce()
        return e?.ok == true
    }


    func mandaDettatoBarra(_ r: Registrazione) async {
        _ = await mandaDettato(r)
    }


    var richiesteDelFilo: [RichiestaVoce] {
        let tutte = voceAttivita?.richieste ?? []
        let vive = tutte.filter { r in
            !voceChiuse.contains(r.id) && (r.finita != true || richiestaRecente(r) || modoIstantanea)
        }
        return vive.sorted { ($0.creata ?? $0.id) < ($1.creata ?? $1.id) }
    }


    var giriDelFilo: [(richiesta: RichiestaVoce, risposte: [RichiestaVoce])] {
        let lista = richiesteDelFilo
        let perId = Dictionary(lista.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        func radice(_ r: RichiestaVoce) -> String {
            if let f = r.filo, !f.isEmpty, f != r.id, perId[f] != nil { return f }
            var c = r
            var visti: Set<String> = [r.id]
            while let d = c.dopo, !d.isEmpty, let su = perId[d], !visti.contains(su.id) {
                visti.insert(su.id)
                c = su
            }
            return c.id
        }
        var ordine: [String] = []
        var figli: [String: [RichiestaVoce]] = [:]
        for r in lista {
            let rad = radice(r)
            if rad == r.id { ordine.append(r.id) } else { figli[rad, default: []].append(r) }
        }
        return ordine.compactMap { id in perId[id].map { (richiesta: $0, risposte: figli[id] ?? []) } }
    }


    var richiesteCheChiedono: [String] {
        richiesteDelFilo.filter { ["ti_chiede", "da_verificare"].contains($0.stato) }.map(\.id)
    }


    func applicaApri(_ a: AperturaVoce) {

        guard sezione == .cose, !coseCampoAttivo, !coseTitoloInModifica else { return }
        if let v = a.vista, cose?.schede?.contains(where: { $0.id == v }) == true || vistaSpeciale(v) { coseVista = v }
        if let f = a.filtro { coseFiltroAlVolo = f }
        if let t = a.task, coseIndice[t] != nil {
            coseScelte = [t]
            cosaAperta = t
            dettaglioCose = true
        }
    }


    func scegliDaConversazione(_ id: String?) {
        guard let id, coseIndice[id] != nil else { return }
        coseScelte = [id]
        cosaAperta = id
    }
}



extension View {


    func conVoce(store: Store) -> some View { modifier(ConVoce(store: store)) }
}

struct ConVoce: ViewModifier {
    let store: Store
    @State private var altezzaBarra: CGFloat = 52
    @State private var altezza: CGFloat = 600
    @Environment(\.accessibilityReduceMotion) private var ridotto

    func body(content: Content) -> some View {
        let c = StatoConversazione.condiviso





        VStack(spacing: 0) {
            content
            BarraVoce(store: store)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { altezzaBarra = $0 }
        }
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { altezza = $0 }
            .overlay(alignment: .bottom) {
                if c.aperta {
                    FiloVoce(store: store, altezzaMassima: max(160, (altezza - altezzaBarra) * 0.72))
                        .padding(.horizontal, 14)
                        .padding(.bottom, altezzaBarra + 4)
                        .transition(ridotto ? .opacity : .move(edge: .bottom).combined(with: .opacity))
                }
            }
            .animation(ridotto ? .easeInOut(duration: 0.15) : .smooth(duration: 0.25), value: c.aperta)
            .onChange(of: store.richiesteCheChiedono, initial: true) { _, chiedono in

                let nuove = Set(chiedono).subtracting(c.chiedeViste)
                c.chiedeViste.formUnion(chiedono)
                if !nuove.isEmpty, !store.modoIstantanea { c.aperta = true }
            }
            .onChange(of: store.voceAttivita, initial: true) { prima, v in
                c.lettoAlle = Date()



                let finite = (v?.richieste ?? []).filter { $0.finita == true && $0.apri != nil }
                if !c.apriLetto || prima == v {
                    c.apriLetto = v != nil
                    c.apriViste.formUnion(finite.map(\.id))
                    return
                }
                for r in finite where !c.apriViste.contains(r.id) {
                    c.apriViste.insert(r.id)
                    if let a = r.apri, !store.modoIstantanea { store.applicaApri(a) }
                }
            }
    }
}



struct BarraVoce: View {
    let store: Store

    var body: some View {
        let c = StatoConversazione.condiviso
        let giri = store.giriDelFilo
        let n = giri.count + store.voceNonMandati.count
        let lavora = (store.voceAttivita?.in_corso ?? 0) > 0
        let chiede = !store.richiesteCheChiedono.isEmpty
        let reg = Registratore.condiviso
        let ascolta = store.voceFintaSecondi != nil || (reg.e(Registrazione.attivita, Registrazione.attivita) && reg.stato == .registra)
        VStack(alignment: .leading, spacing: 6) {
            if let p = problemaMicrofono {
                HStack(spacing: 8) {
                    Image(systemName: Simbolo.attenzione).foregroundStyle(Salute.attenzione.colore)
                    Text(p).font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 8)
                    if Registratore.condiviso.negato {
                        Button(store.t("apri_impostazioni")) { Registratore.apriImpostazioni() }.controlSize(.small)
                    }
                    Button { Registratore.condiviso.chiudiProblema() } label: { Image(systemName: "xmark").font(.system(size: 10)) }
                        .buttonStyle(.borderless)
                }
            }
            HStack(spacing: 10) {
                CampoVoce(testo: Binding(get: { c.testo }, set: { c.testo = $0 }),
                          segnaposto: store.tv("barra_segnaposto"),
                          voce: Registrazione.attivita, chiave: Registrazione.attivita, cosa: store.t("titolo"),
                          cartella: store.cartellaDettati, cartellaRegistro: store.cartellaDettati,
                          testi: { store.tv($0) },
                          mandaTesto: { await store.chiediAllaLista($0) },
                          mandaAudio: { await store.mandaDettatoBarra($0) },
                          fintoSecondi: store.voceFintaSecondi)
                    .onChange(of: Registratore.condiviso.stato) { _, s in



                        if s == .registra { ContestoVoce.argomenti = store.contestoVoce }
                        if s == .fermo { ContestoVoce.argomenti = [] }
                    }
                    .onDisappear { if Registratore.condiviso.stato == .fermo { ContestoVoce.argomenti = [] } }
                if n > 0 {
                    Button { c.aperta.toggle() } label: {
                        HStack(spacing: 5) {
                            if lavora {
                                Image(systemName: "ellipsis").symbolEffect(.variableColor.iterative, options: .repeating)
                            } else if chiede {
                                Image(systemName: "questionmark.circle.fill").foregroundStyle(Salute.attenzione.colore)
                            }
                            Image(systemName: "chevron.up").font(.system(size: 10, weight: .semibold))
                                .rotationEffect(.degrees(c.aperta ? 180 : 0))
                            Text(n.formatted()).font(.system(size: 12, weight: .medium)).monospacedDigit()
                                .contentTransition(.numericText())
                        }
                        .padding(.horizontal, 9).padding(.vertical, 5)
                        .background(c.aperta ? Superficie.selezione : Superficie.riquadro, in: Capsule())
                        .contentShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .help(store.tv("aiuto_filo"))
                    .fixedSize()
                }
            }
        }
        .padding(.leading, 8).padding(.trailing, 10).padding(.vertical, 7)
        .modifier(FondoBarra(ascolta: ascolta))
        .padding(.horizontal, 12)
        .padding(.top, 6)
        .padding(.bottom, 8)
    }

    private var problemaMicrofono: String? {
        let r = Registratore.condiviso
        return r.problemaPer == Registrazione.attivita ? r.problema : nil
    }
}




struct FondoBarra: ViewModifier {
    let ascolta: Bool

    func body(content: Content) -> some View {
        let forma = RoundedRectangle(cornerRadius: 20, style: .continuous)
        if ascolta {
            content
                .background { ZStack { forma.fill(Superficie.scheda); forma.fill(Color.red.opacity(0.08)) } }
                .overlay(forma.strokeBorder(Color.red.opacity(0.35), lineWidth: 1))
        } else {
            content.glassEffect(.regular, in: forma)
        }
    }
}



struct FiloVoce: View {
    let store: Store
    let altezzaMassima: CGFloat

    var body: some View {
        let giri = store.giriDelFilo
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(store.tv("titolo_sezione")).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary)
                Spacer()
                Button { StatoConversazione.condiviso.aperta = false } label: { Image(systemName: "xmark").font(.system(size: 10)) }
                    .buttonStyle(.borderless).foregroundStyle(.secondary).help(store.tv("chiudi_richiesta"))
            }
            .padding(.horizontal, 14).padding(.top, 10).padding(.bottom, 4)
            .help(store.tv("aiuto_sezione"))
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(store.voceNonMandati, id: \.self) { f in SchedaDettatoRimasto(store: store, file: f) }
                    if giri.isEmpty && store.voceNonMandati.isEmpty {
                        Text(store.tv("filo_vuoto")).font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                    ForEach(giri, id: \.richiesta.id) { g in
                        GiroVoce(store: store, richiesta: g.richiesta, risposte: g.risposte)
                    }
                }
                .padding(.horizontal, 14).padding(.bottom, 12).padding(.top, 4)
            }
            .defaultScrollAnchor(.bottom)
            .scrollBounceBehavior(.basedOnSize)
        }
        .frame(maxWidth: 760)
        .frame(maxHeight: altezzaMassima, alignment: .bottom)
        .fixedSize(horizontal: false, vertical: true)
        .background(Superficie.scheda, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Superficie.bordo, lineWidth: 1))
        .shadow(color: .black.opacity(0.14), radius: 18, y: 6)
        .frame(maxWidth: .infinity)
        .onExitCommand { StatoConversazione.condiviso.aperta = false }
    }
}



struct GiroVoce: View {
    let store: Store
    let richiesta: RichiestaVoce
    var risposte: [RichiestaVoce] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TurnoVoce(store: store, richiesta: richiesta, principale: true, risposto: !risposte.isEmpty)
            if !risposte.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(risposte) { r in TurnoVoce(store: store, richiesta: r, principale: false) }
                }
                .padding(.leading, 14)
                .overlay(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 1).fill(Superficie.separatore).frame(width: 2)
                }
            }
        }
    }
}

struct TurnoVoce: View {
    let store: Store
    let richiesta: RichiestaVoce
    let principale: Bool

    var risposto = false


    private var risposta: String {
        get { StatoConversazione.condiviso.risposte[richiesta.id] ?? "" }
        nonmutating set { StatoConversazione.condiviso.risposte[richiesta.id] = newValue.isEmpty ? nil : newValue }
    }
    private var rispostaB: Binding<String> { Binding(get: { risposta }, set: { risposta = $0 }) }
    @State private var correggo = false
    @Environment(\.accessibilityReduceMotion) private var ridotto

    var body: some View {
        let r = richiesta
        let finita = r.finita == true
        VStack(alignment: .leading, spacing: 6) {
            fraseDiOwner
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    segno
                    if !finita, let n = r.da_secondi, r.stato == "in_elaborazione" {

                        TimelineView(.periodic(from: .now, by: 1)) { ctx in
                            let passati = Int(ctx.date.timeIntervalSince(StatoConversazione.condiviso.lettoAlle))
                            Text(store.fraseLavoroDa(n + max(0, passati)))
                                .font(.system(size: 12, weight: .semibold)).monospacedDigit()
                        }
                    } else {
                        Text(r.stato_nome ?? "").font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(coloreStato)
                    }
                    Spacer(minLength: 4)
                    if finita {
                        Button { store.voceChiuse.insert(r.id) } label: { Image(systemName: "xmark").font(.system(size: 9)) }
                            .buttonStyle(.borderless).foregroundStyle(.tertiary).help(store.t("aiuto_chiudi_richiesta"))
                    }
                }
                if !finita, let m = r.motivo, !m.isEmpty {
                    Text(m).font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                if let c = r.capito, !c.isEmpty {
                    Text(c).font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                if let g = r.gia_fatto, !g.isEmpty {
                    Text(g).font(.system(size: 12)).foregroundStyle(.secondary)
                }
                cambi

                if let risp = r.risposta, !risp.isEmpty, r.annullata != true, r.stato != "ti_chiede" || (r.domanda ?? "") != risp {
                    Text(risp).font(.system(size: 13)).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                }
                perStato
                pulsanti
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(sfondo, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }


    private var fraseDiOwner: some View {
        let r = richiesta
        let frase = (r.testo ?? "").isEmpty ? (r.detto ?? "") : (r.testo ?? "")
        return HStack(alignment: .bottom, spacing: 6) {
            Spacer(minLength: 60)
            VStack(alignment: .trailing, spacing: 3) {
                HStack(spacing: 6) {
                    if r.via == "voce" { Image(systemName: "waveform").font(.system(size: 10)).foregroundStyle(.secondary) }
                    if let t = r.commento, !t.isEmpty {
                        Image(systemName: "text.bubble").font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                    Text(r.quando ?? "").font(.system(size: 11)).foregroundStyle(.secondary)
                    if let a = r.audio, !a.isEmpty {
                        Button(store.tv("ascolta")) { NSWorkspace.shared.open(URL(fileURLWithPath: a)) }
                            .buttonStyle(.link).font(.system(size: 11)).help(store.t("aiuto_ascolta"))
                    }
                }
                if !frase.isEmpty {
                    Text(frase).font(.system(size: 13))
                        .padding(.horizontal, 11).padding(.vertical, 7)
                        .background(Color.accentColor.opacity(0.16), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                        .lineLimit(6)
                }
            }
        }
    }


    @ViewBuilder
    private var cambi: some View {
        let r = richiesta
        let gesti = r.gesti ?? []
        if let p = r.annullata_prima, let m = p.messaggio, !m.isEmpty {

            Label(m, systemImage: "arrow.uturn.backward").font(.system(size: 12))
                .foregroundStyle(p.ok == false ? Salute.attenzione.colore : .primary)
                .fixedSize(horizontal: false, vertical: true)
        }
        if gesti.isEmpty {

            if r.finita == true, r.stato == "fatta" || r.annullata_prima != nil, let f = r.frase_gesti, !f.isEmpty, f != r.annullata_prima?.messaggio {
                Text(f).font(.system(size: 12)).foregroundStyle(.secondary)
            }
        } else {
            VStack(alignment: .leading, spacing: 3) {
                ForEach(Array(gesti.enumerated()), id: \.offset) { _, g in
                    Button {
                        if let v = g.id_vista, !v.isEmpty, (g.id_task ?? "").isEmpty { store.coseVista = v } else { store.scegliDaConversazione(g.id_task) }
                    } label: {
                        Label {
                            Text(g.cosa ?? g.titolo ?? "").strikethrough(r.annullata == true)
                                .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                        } icon: {
                            Image(systemName: r.annullata == true ? "arrow.uturn.backward" : "checkmark")
                                .foregroundStyle(r.annullata == true ? Color.secondary : Salute.ok.colore)
                        }
                        .font(.system(size: 12))
                        .foregroundStyle(r.annullata == true ? .secondary : .primary)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(store.coseIndice[g.id_task ?? ""] == nil && (g.id_vista ?? "").isEmpty)
                    .help(store.tv("aiuto_gesto"))
                }
            }
        }
    }


    @ViewBuilder
    private var perStato: some View {
        let r = richiesta
        switch r.stato {
        case "ti_chiede":
            if let q = r.domanda, !q.isEmpty {
                Text(q).font(.system(size: 13, weight: .medium)).fixedSize(horizontal: false, vertical: true)
            }
            if let rispondi = r.rispondi, !risposto {
                HStack(spacing: 6) {
                    TextField(store.t("risposta_segnaposto"), text: rispostaB).textFieldStyle(.roundedBorder)
                        .onSubmit { invia(rispondi) }
                    Button(store.tv("rispondi")) { invia(rispondi) }
                        .disabled(risposta.trimmingCharacters(in: .whitespaces).isEmpty || store.modoIstantanea)
                        .help(store.tv("aiuto_rispondi"))
                }
                .controlSize(.small)
            }
        case "da_verificare":
            if let cambi = r.conferma_cambi, !cambi.isEmpty {


                if let q = domandaProposta(r, cambi), !q.isEmpty {
                    Text(q).font(.system(size: 13, weight: .medium)).fixedSize(horizontal: false, vertical: true)
                }



                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(cambi.prefix(Self.righeProposta).enumerated()), id: \.offset) { _, c in RigaProposta(store: store, cambio: c) }
                    if cambi.count > Self.righeProposta {
                        let altre = cambi.count - Self.righeProposta
                        Text(altre == 1 ? store.tv("proposta_altra") : store.tv("proposta_altre").replacingOccurrences(of: "{n}", with: altre.formatted()))
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                }
                Text(store.tv("da_confermare_aiuto")).font(.system(size: 12)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ForEach(r.dubbi ?? [], id: \.self) { d in
                    Label(d, systemImage: Simbolo.attenzione).font(.system(size: 12)).foregroundStyle(Salute.attenzione.colore)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(store.tv("da_verificare_aiuto")).font(.system(size: 12)).foregroundStyle(.secondary)
            }
            if correggo {
                HStack(spacing: 6) {
                    TextField(store.t("correggi_segnaposto"), text: rispostaB).textFieldStyle(.roundedBorder)
                        .onSubmit { if let c = r.conferma, !risposta.trimmingCharacters(in: .whitespaces).isEmpty { Task { await store.azioneVoce(c + [risposta]) } } }
                    Button(store.tv("conferma")) {
                        if let c = r.conferma { Task { await store.azioneVoce(c + [risposta]) } }
                    }
                    .disabled(risposta.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                .controlSize(.small)
            }
        case "non_riuscita", "aspetta_abbonamento":
            if r.finita == true, let m = r.motivo, !m.isEmpty {
                Text(m).font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
            }
        case "non_si_puo":
            if (r.risposta ?? "").isEmpty, let m = r.motivo, !m.isEmpty {
                Text(m).font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
            }

            if let rispondi = r.rispondi, !risposto {
                HStack(spacing: 6) {
                    TextField(store.t("risposta_segnaposto"), text: rispostaB).textFieldStyle(.roundedBorder)
                        .onSubmit { invia(rispondi) }
                    Button(store.tv("rispondi")) { invia(rispondi) }
                        .disabled(risposta.trimmingCharacters(in: .whitespaces).isEmpty || store.modoIstantanea)
                        .help(store.tv("aiuto_rispondi"))
                }
                .controlSize(.small)
            }
        default:
            EmptyView()
        }
    }



    @ViewBuilder
    private var pulsanti: some View {
        let r = richiesta
        let conferma = r.stato == "da_verificare" && !correggo ? r.conferma : nil
        let riprova = r.stato == "non_si_puo" ? nil : r.riprova
        if r.annulla != nil || conferma != nil || riprova != nil {
            HStack(spacing: 8) {
                if let c = conferma {
                    Button(store.tv("conferma")) { Task { await store.azioneVoce(c) } }.buttonStyle(.borderedProminent)
                    Button(store.tv("correggi")) { risposta = r.testo ?? ""; correggo = true }
                }
                if let rp = riprova {
                    Button(store.tv("riprova")) { Task { await store.azioneVoce(rp) } }
                }
                if let a = r.annulla {
                    Button(store.tv("annulla")) { Task { await store.azioneVoce(a) } }
                        .help(store.tv("aiuto_annulla"))
                }
            }
            .controlSize(.small)
            .disabled(store.modoIstantanea)
        }
    }

    private var sfondo: Color {
        switch richiesta.stato {
        case "ti_chiede", "da_verificare": return Salute.attenzione.colore.opacity(0.10)
        case "non_riuscita": return Salute.errore.colore.opacity(0.08)
        default: return Superficie.riquadro
        }
    }

    private var coloreStato: Color {
        switch richiesta.stato {
        case "ti_chiede", "da_verificare": return Salute.attenzione.colore
        case "non_riuscita": return Salute.errore.colore
        default: return .primary
        }
    }

    @ViewBuilder
    private var segno: some View {
        let r = richiesta
        switch r.stato {
        case "fatta":
            let simbolo = Image(systemName: r.annullata == true ? "arrow.uturn.backward.circle" : "checkmark.circle.fill")
                .foregroundStyle(r.annullata == true ? Color.secondary : Salute.ok.colore)

            if ridotto { simbolo } else { simbolo.transition(.symbolEffect(.drawOn)) }
        case "ti_chiede": Image(systemName: "questionmark.circle.fill").foregroundStyle(Salute.attenzione.colore)
        case "da_verificare":
            Image(systemName: (r.conferma_cambi ?? []).isEmpty ? "ear" : "checklist").foregroundStyle(Salute.attenzione.colore)
        case "non_riuscita": Image(systemName: Simbolo.attenzione).foregroundStyle(Salute.errore.colore)
        case "non_si_puo": Image(systemName: "hand.raised.circle").foregroundStyle(.secondary)
        default:
            Image(systemName: "sparkle")
                .foregroundStyle(Color.accentColor)
                .symbolEffect(.breathe, options: .repeating, isActive: !ridotto)
        }
    }


    static let righeProposta = 20



    private func domandaProposta(_ r: RichiestaVoce, _ cambi: [CambioProposto]) -> String? {
        if let d = r.domanda, !d.isEmpty { return d }
        let dubbi = r.dubbi ?? []
        let righe = cambi.prefix(Self.righeProposta).reduce(0) { $0 + 1 + (($1.perde ?? "").isEmpty ? 0 : 1) }
            + (cambi.count > Self.righeProposta ? 1 : 0)
        return dubbi.count == righe + 1 ? dubbi.first : nil
    }

    private func invia(_ argomenti: [String]) {
        let id = richiesta.id
        Task { await StatoConversazione.condiviso.mandaRisposta(store, id: id, argomenti: argomenti) }
    }
}



struct RigaProposta: View {
    let store: Store
    let cambio: CambioProposto

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "circle.dashed").font(.system(size: 10)).foregroundStyle(.secondary)
                Button { store.scegliDaConversazione(cambio.id) } label: {
                    Text(cambio.titolo ?? "").font(.system(size: 12, weight: .medium)).underline(store.coseIndice[cambio.id ?? ""] != nil)
                        .multilineTextAlignment(.leading).lineLimit(3)
                }
                .buttonStyle(.plain)
                .disabled(store.coseIndice[cambio.id ?? ""] == nil)
                .help(store.tv("aiuto_gesto"))
                if let c = cambio.cosa, !c.isEmpty {
                    Text(c).font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            if let p = cambio.perde, !p.isEmpty {
                Text(store.tv("proposta_perde").replacingOccurrences(of: "{testo}", with: String(p.split(whereSeparator: \.isWhitespace).joined(separator: " ").prefix(600))))
                    .font(.system(size: 11)).foregroundStyle(Salute.attenzione.colore)
                    .lineLimit(4)
                    .padding(.horizontal, 8).padding(.vertical, 5)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Salute.attenzione.colore.opacity(0.08), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                    .padding(.leading, 16)
                    .textSelection(.enabled)
            }
        }
    }
}
