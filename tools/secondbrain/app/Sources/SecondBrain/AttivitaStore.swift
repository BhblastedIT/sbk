import AppKit
import SwiftUI


enum FuocoCose: Hashable {
    case tabella, nuova, cerca, titolo, descrizione
}


struct EsitoRiga: Equatable {
    var testo: String
    var errore = false

    var annullabile = false

    var riprova: [String]?

    var chiave: String?
    var segno = UUID()
}


struct ConflittoTesto: Equatable {
    let id: String
    let campo: String
    let mio: String
    let loro: String
}



struct FotoDisposizione {
    let vista: String
    let gruppi: [(id: String, nome: String, valore: String?, campo: String, righe: [String])]
}


struct GruppoVisto: Identifiable {
    let id: String
    let nome: String

    let valore: String?

    let campo: String
    let righe: [VoceCosa]
}


@MainActor
final class ScatolaEventi {
    var eventi: [String] = []
    var pronta = false
    var ids: [String] = []

    var chiave: String?

    var senzaRisposta = false
}



@MainActor
final class ScatolaVista {
    var argomenti: [String] = []
    var pronta = false
}

extension Store {


    func apriCose() async { await caricaCose() }



    func caricaCose(rileggi: Bool = false) async {
        traccia("caricaCose reading \(coseInLettura)")
        defer { traccia("caricaCose end") }
        coseDaRileggere = true
        if coseInLettura {
            while coseInLettura { try? await Task.sleep(nanoseconds: 20_000_000) }
            return
        }
        coseInLettura = true
        while coseDaRileggere {
            coseDaRileggere = false
            await leggiCose()
        }
        coseInLettura = false
    }

    private func leggiCose() async {
        var argomenti = ["cose"]
        if let m = coseMese { argomenti += ["--mese", m] }
        if coseFatteTutte { argomenti += ["--fatte"] }
        argomenti += argomentiSettimana
        let partita = Date()

        let ordiniAllaPartenza = coseOrdiniDati


        let inVoloAllaPartenza = coseOrdiniInVolo
        let r = await motore.chiedi(argomenti, scadenza: 30)
        coseLetteAlle = Date()
        let inizio = ContinuousClock.now
        let decodificata = try? JSONDecoder().decode(Cose.self, from: r.dati)
        Store.misuraDecodifica = (ContinuousClock.now - inizio, r.dati.count)
        if let nuove = decodificata {
            if nuove.ok {
                cose = nuove


                let chiesta = argomenti.contains("--settimana")
                let st = StatoSettimana.condiviso
                if chiesta || st.scale.isEmpty || st.testi.isEmpty || schedaCose?.modo == "calendario" {
                    assorbiSettimana(r.dati, partita: partita, chiesta: chiesta)
                }



                if let s = schedaCose, !vistaSpeciale, coseOrdiniInVolo == 0, inVoloAllaPartenza == 0, coseOrdiniDati == ordiniAllaPartenza {
                    let salvati = s.livelli
                    if let prima = coseLivelliVisti[s.id], prima != salvati { applicaOrdineSalvato() }
                    coseLivelliVisti[s.id] = salvati
                }
                if let info = nuove.colonne_info, info != Store.infoColonne { Store.infoColonne = info }
                if let stati = nuove.stati {
                    let d = Dictionary(stati.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
                    if d != Store.statiDef { Store.statiDef = d; RegistroStati.condiviso.def = d }
                }
                erroreCose = nil

                let vive = coseScelte.filter { coseIndice[$0] != nil }
                if vive != coseScelte { coseScelte = vive }


                if dettaglioCose, coseScelte.count <= 1, let id = cosaAperta, coseIndice[id] == nil { dettaglioCose = false }


                if !vistaSpeciale, !schedeVisibili.contains(where: { $0.id == coseVista }), let prima = schedeVisibili.first {
                    coseVista = prima.id
                }


                if !modoIstantanea, !Store.senzaCache { Store.scriviCache(r.dati, fileCacheCose) }
            } else if cose == nil {
                erroreCose = nuove.errore ?? cose?.t("errore_lettura")
            } else {

                coseEsito = EsitoRiga(testo: nuove.errore ?? t("errore_lettura"), errore: true, riprova: ["rileggi"])
            }
        } else if cose == nil {

            erroreCose = r.scaduto ? "The task engine did not respond in time." : "Your task file cannot be read."
            if argomenti.contains("--settimana") { StatoSettimana.condiviso.errore = settimanaNonArrivata }
        } else {

            if argomenti.contains("--settimana") { StatoSettimana.condiviso.errore = settimanaNonArrivata }

            coseEsito = EsitoRiga(testo: t(r.scaduto ? "errore_motore" : "errore_lettura"), errore: true, riprova: ["rileggi"])
        }
    }



    func rileggiCoseSeServe() async {

        guard !modoIstantanea, coseOccupate.isEmpty, let ultima = coseLetteAlle else { return }
        if Date().timeIntervalSince(ultima) > (sezione == .cose ? 120 : 600) { await caricaCose() }
    }


    func t(_ chiave: String) -> String { cose?.t(chiave) ?? "" }




    var schedaCose: SchedaCose? {
        guard let c = cose else { return nil }
        if let s = c.schede?.first(where: { $0.id == coseVista && !$0.nascosta }) { return s }
        if let sp = c.speciali?.first(where: { $0.id == coseVista }) {
            return SchedaCose(id: sp.id, nome: sp.nome, nome_suo: false, pronta: sp.id, modo: "tabella", regola: nil,
                              filtro: nil, gruppo: "nessuno", gruppi_chiusi: [], ordine: nil,
                              fatte: "no", nascosta: false, cambiata: false, aiuto: sp.aiuto, vuoto: sp.vuoto,
                              numero: sp.id_righe.count, id_righe: sp.id_righe, id_fatte: [])
        }
        return c.schede?.first { !$0.nascosta }
    }

    var vistaSpeciale: Bool { vistaSpeciale(coseVista) }
    func vistaSpeciale(_ id: String) -> Bool { id == "fatte" || id == "eliminate" }


    var schedeVisibili: [SchedaCose] { (cose?.schede ?? []).filter { !$0.nascosta } }


    func gruppiChiusi(_ s: SchedaCose) -> Set<String> {
        coseGruppiChiusi[s.id] ?? Set(s.gruppi_chiusi)
    }

    func chiudiGruppo(_ s: SchedaCose, _ gid: String, _ chiuso: Bool) {
        var c = gruppiChiusi(s)
        if chiuso { c.insert(gid) } else { c.remove(gid) }
        coseGruppiChiusi[s.id] = c
        guard !modoIstantanea, !vistaSpeciale, !motoreVecchio else { return }
        let valore = (try? String(data: JSONEncoder().encode(c.sorted()), encoding: .utf8)) ?? "[]"
        Task { _ = await motore.chiedi(["cose", "vista-imposta", s.id, "gruppi_chiusi", valore], scadenza: 15) }
    }


    static let chiuseAttesaNs: UInt64 = 1_500_000_000



    func trattieniChiuse(_ ids: [String]) {
        coseChiuseInAttesa.formUnion(ids)
        coseChiuseGiro += 1
        let giro = coseChiuseGiro
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: Store.chiuseAttesaNs)
            guard let self, self.coseChiuseGiro == giro else { return }
            self.coseChiuseInAttesa = []
        }
    }



    func mostraFatte(_ s: SchedaCose, _ mostra: Bool) async {
        let chiave = "attivitaFatteUltima.\(s.id)"
        let valore: String
        if mostra {
            valore = UserDefaults.standard.string(forKey: chiave) ?? "7_giorni"
        } else {
            if s.fatte != "no" { UserDefaults.standard.set(s.fatte, forKey: chiave) }
            valore = "no"
        }
        coseChiuseInAttesa = []
        coseTenute = []
        await gestoVista(["vista-imposta", s.id, "fatte", "\"\(valore)\""])
    }


    func passaAlVolo(_ v: VoceCosa) -> Bool {
        let chiavi = Set(v.filtro_chiavi ?? [])
        for (campo, valori) in coseFiltroAlVolo where !valori.isEmpty {
            if !valori.contains(where: { chiavi.contains("\(campo):\($0)") }) { return false }
        }
        return true
    }

    func trovata(_ v: VoceCosa, _ cerca: String) -> Bool {
        [v.titolo, v.area, v.dettaglio].contains {
            $0.range(of: cerca, options: [.caseInsensitive, .diacriticInsensitive]) != nil
        }
    }



    func disposizione() -> [GruppoVisto] {
        guard let c = cose, let s = schedaCose else { return [] }
        if !coseTenute.isEmpty, let foto = coseFoto, foto.vista == s.id {


            let nascondiChiuse = s.fatte == "no" && !vistaSpeciale(s.id)
            var gruppi = foto.gruppi.map { g in
                let colonnaChiuse = g.campo == "stato" && (c.gruppi_per?["stato"]?.gruppi.first { $0.id == g.id }?.chiuso ?? (g.id == "fatta"))
                return GruppoVisto(id: g.id, nome: g.nome, valore: g.valore, campo: g.campo, righe: g.righe.compactMap { coseIndice[$0] }
                    .filter { !nascondiChiuse || colonnaChiuse || !$0.chiusaOra || coseChiuseInAttesa.contains($0.id) })
            }
            let nuove = coseAppenaAggiunte.filter { id in !foto.gruppi.contains { $0.righe.contains(id) } }
                .compactMap { coseIndice[$0] }
            if !nuove.isEmpty, let primo = gruppi.first {
                gruppi[0] = GruppoVisto(id: primo.id, nome: primo.nome, valore: primo.valore, campo: primo.campo,
                                        righe: nuove + primo.righe)
            }
            return gruppi
        }
        let cerca = coseCerca.trimmingCharacters(in: .whitespaces)
        var righe = s.id_righe.compactMap { coseIndice[$0] }

        let nuove = coseAppenaAggiunte.compactMap { coseIndice[$0] }
        righe = nuove + righe.filter { r in !coseAppenaAggiunte.contains(r.id) }

        righe = righe.filter { (coseAppenaAggiunte.contains($0.id) || passaAlVolo($0)) && (cerca.isEmpty || trovata($0, cerca)) }
        let posizione = Dictionary(s.id_righe.enumerated().map { ($1, $0) }, uniquingKeysWith: { a, _ in a })

        let livelloGruppo = coseOrdine.first { $0.campo == s.gruppo }
        righe = Store.ordinate(righe, coseOrdine.filter { $0.campo != s.gruppo }, posizione: posizione)
        var gruppi: [GruppoVisto] = []
        let campo = s.gruppo
        if campo == "nessuno" || s.modo == "calendario" {
            gruppi = [GruppoVisto(id: "", nome: "", valore: nil, campo: "", righe: righe)]
        } else if let def = c.gruppi_per?[campo] {
            var per: [String: [VoceCosa]] = [:]
            for r in righe { per[r.gruppo_di?[campo] ?? "", default: []].append(r) }

            gruppi = def.gruppi.compactMap { g in
                let mie = per[g.id] ?? []
                if mie.isEmpty && s.modo != "bacheca" { return nil }
                if campo == "scadenza", coseOrdine.allSatisfy({ $0.campo == "scadenza" }) {
                    return GruppoVisto(id: g.id, nome: g.nome, valore: g.valore, campo: campo,
                                       righe: mie.sorted { ($0.o_scadenza_gruppo ?? 0, $0.oPriorita) < ($1.o_scadenza_gruppo ?? 0, $1.oPriorita) })
                }




                if s.modo == "bacheca", campo == "stato", g.chiuso ?? (g.id == "fatta") {
                    let base = s.id_fatte_oggi.map { $0.compactMap { coseIndice[$0] } }
                        ?? (c.righe_chiuse ?? []).filter { $0.fatta_oggi == true }
                    let oggi = base.filter { ($0.stato ?? "") == g.id && passaAlVolo($0) && (cerca.isEmpty || trovata($0, cerca)) }
                    return GruppoVisto(id: g.id, nome: g.nome, valore: g.valore, campo: campo, righe: oggi)
                }
                return GruppoVisto(id: g.id, nome: g.nome, valore: g.valore, campo: campo, righe: mie)
            }
        } else {
            gruppi = [GruppoVisto(id: "", nome: "", valore: nil, campo: "", righe: righe)]
        }
        if livelloGruppo?.order == .reverse { gruppi.reverse() }
        if s.fatte != "no", s.modo != "calendario" {
            let fatte = s.id_fatte.compactMap { coseIndice[$0] }.filter { cerca.isEmpty || trovata($0, cerca) }
            if !fatte.isEmpty {
                gruppi.append(GruppoVisto(id: "fatte", nome: t("gruppo_fatte_vista"), valore: nil, campo: "fatte", righe: fatte))
            }
        }
        return gruppi
    }


    func gruppoChiuso(_ g: GruppoVisto) -> Bool {
        guard g.campo == "stato" else { return false }
        return cose?.gruppi_per?["stato"]?.gruppi.first { $0.id == g.id }?.chiuso ?? (g.id == "fatta")
    }


    func righeAVista() -> [VoceCosa] {
        guard let s = schedaCose else { return [] }

        if s.modo == "foglio" { return disposizione().flatMap(\.righe) }
        let chiusi = gruppiChiusi(s)
        return disposizione().filter { $0.id.isEmpty || !chiusi.contains($0.id) }.flatMap(\.righe)
    }


    func fuoriVista(_ id: String) -> Bool {
        guard !coseTenute.isEmpty, let s = schedaCose else { return false }
        if coseAppenaAggiunte.contains(id) { return false }
        return !s.id_righe.contains(id) && !s.id_fatte.contains(id)
    }

    private func fotografa(_ ids: [String]) {
        if coseTenute.isEmpty || coseFoto?.vista != coseVista {
            coseFoto = FotoDisposizione(vista: coseVista, gruppi: disposizione().map {
                (id: $0.id, nome: $0.nome, valore: $0.valore, campo: $0.campo, righe: $0.righe.map(\.id))
            })
        }
        coseTenute.formUnion(ids)
    }



    func esitoCosa(_ r: Motore.Risposta) -> EsitoCosa? {
        try? JSONDecoder().decode(EsitoCosa.self, from: r.dati)
    }



    @discardableResult
    func gestoTask(_ verbo: String, _ ids: [String], _ valori: [String] = [], era: String? = nil,
                   chiave: String? = nil) async -> EsitoCosa? {
        guard !ids.isEmpty, !modoIstantanea, !bloccaGesto() else { return nil }


        let k = chiave ?? UUID().uuidString.lowercased()
        fotografa(ids)
        coseOccupate.formUnion(ids)


        let scatola = ScatolaEventi()
        scatola.ids = ids
        scatola.chiave = k
        registraAnnulla(scatola, nome: nomeAzione(verbo, ids.count))
        var argomenti = ["cose", verbo, ids.joined(separator: ",")] + valori
        if let era { argomenti += ["--era", era] }
        let comando = argomenti + ["--una-volta", k]

        let e = await inFila { [weak self] in
            guard let self else { return EsitoCosa?.none }
            return self.esitoCosa(await self.motore.chiedi(comando, scadenza: 30))
        }
        coseOccupate.subtract(ids)
        if let e, e.ok, !(e.eventi ?? []).isEmpty {
            scatola.eventi = e.eventi ?? []
            scatola.ids = e.ids ?? ids
            coseEsito = EsitoRiga(testo: e.riga ?? e.messaggio ?? "", annullabile: true)
        } else if e == nil {


            scatola.senzaRisposta = true
            coseEsito = EsitoRiga(testo: t("errore_motore"), errore: true, riprova: Array(argomenti.dropFirst()), chiave: k)
        } else {
            ritiraAnnulla(scatola)
            if let e, e.ok {
                coseEsito = EsitoRiga(testo: e.riga ?? e.messaggio ?? "", annullabile: false)
            } else if e?.intanto == nil {

                let si = e?.sparita != true && e?.riprova != false
                coseEsito = EsitoRiga(testo: e?.errore ?? t("errore_motore"), errore: true,
                                      riprova: si ? Array(argomenti.dropFirst()) : nil, chiave: si ? k : nil)
            }
        }
        scatola.pronta = true
        await caricaCose()

        let chiuse = scatola.ids.filter { coseIndice[$0]?.chiusaOra == true }
        if !chiuse.isEmpty { trattieniChiuse(chiuse) }
        return e
    }


    func inFila<T>(_ lavoro: @escaping @MainActor () async -> T) async -> T {
        let prima = coseCodaGesti
        let t = Task { @MainActor in
            _ = await prima?.value
            return await lavoro()
        }
        coseCodaGesti = Task { @MainActor in _ = await t.value }
        return await t.value
    }





    func nomeAzione(_ verbo: String, _ n: Int) -> String {
        let famiglia = ["commenta": "commento", "commento-togli": "commento", "data": "data", "pianifica": "pianifica"][verbo] ?? verbo
        let nome = cose?.testi?["azione_\(verbo)"] ?? cose?.testi?["azione_\(famiglia)"] ?? ""
        guard !nome.isEmpty else { return "" }
        return n <= 1 ? nome : t("azione_tante").replacingOccurrences(of: "{azione}", with: nome)
            .replacingOccurrences(of: "{n}", with: n.formatted())
    }


    func riprovaCose(_ argomenti: [String], chiave: String? = nil) async {
        guard argomenti.count >= 2 else { return }
        let ids = argomenti[1].split(separator: ",").map(String.init)
        var valori = Array(argomenti.dropFirst(2))
        var era: String?
        if let i = valori.firstIndex(of: "--era"), i + 1 < valori.count { era = valori[i + 1]; valori.removeSubrange(i...(i + 1)) }
        await gestoTask(argomenti[0], ids, valori, era: era, chiave: chiave)
    }



    func registraAnnulla(_ scatola: ScatolaEventi, nome: String) {
        guard let um = coseUndo else { return }




        let apri = um.groupingLevel == 0 && !um.isUndoing && !um.isRedoing
        traccia("register «\(nome)» level \(um.groupingLevel) undoing \(um.isUndoing) redoing \(um.isRedoing) open \(apri)")
        if apri { um.beginUndoGrouping() }
        defer { if apri { um.endUndoGrouping() } }



        um.registerUndo(withTarget: scatola) { [weak self] _ in
            guard let s = self else { return }
            let ritorno = ScatolaEventi()
            ritorno.ids = scatola.ids
            s.registraAnnulla(ritorno, nome: nome)
            Task { @MainActor in await s.annullaEventi(scatola, ritorno) }
        }
        if !nome.isEmpty { um.setActionName(nome) }
    }


    func ritiraAnnulla(_ scatola: ScatolaEventi) {
        coseUndo?.removeAllActions(withTarget: scatola)
    }

    private func annullaEventi(_ scatola: ScatolaEventi, _ ritorno: ScatolaEventi) async {
        var attesa = 0
        while !scatola.pronta && attesa < 600 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            attesa += 1
        }

        if sezione != .cose { sezione = .cose }

        if scatola.eventi.isEmpty, scatola.senzaRisposta, let k = scatola.chiave {
            let r = await inFila { [weak self] in
                guard let self else { return EsitoCosa?.none }
                return self.esitoCosa(await self.motore.chiedi(["cose", "annulla", "--gruppo", k], scadenza: 30))
            }
            if let r, r.ok, !(r.eventi ?? []).isEmpty {
                ritorno.eventi = r.eventi ?? []
                ritorno.ids = r.ids ?? []
                coseEsito = EsitoRiga(testo: r.riga ?? r.messaggio ?? "", annullabile: false)
            } else {
                coseEsito = EsitoRiga(testo: r?.riga ?? r?.messaggio ?? r?.errore ?? t("errore_motore"), errore: r?.ok != true)
                ritiraAnnulla(ritorno)
            }
            ritorno.pronta = true
            await caricaCose()
            return
        }
        guard !scatola.eventi.isEmpty else {
            ritiraAnnulla(ritorno)
            ritorno.pronta = true
            return
        }
        let eventi = scatola.eventi
        let r = await inFila { [weak self] in
            guard let self else { return EsitoCosa?.none }
            return self.esitoCosa(await self.motore.chiedi(["cose", "annulla"] + eventi, scadenza: 30))
        }
        if let r, r.ok {
            ritorno.eventi = r.eventi ?? []
            ritorno.ids = r.ids ?? []
            coseEsito = EsitoRiga(testo: r.riga ?? r.messaggio ?? "", annullabile: false)
        } else {

            coseEsito = EsitoRiga(testo: r?.errore ?? t("errore_motore"), errore: true)
            ritiraAnnulla(ritorno)
        }
        ritorno.pronta = true
        coseTenute = []
        await caricaCose()

        coseAppenaAggiunte.removeAll { coseIndice[$0]?.eliminata == true }
        let toccate = Set(ritorno.ids).filter { coseIndice[$0] != nil }
        if !toccate.isEmpty { coseScelte = toccate }
    }




    func apriTaskInAttivita(_ id: String) async {
        ricerca = ""
        if sezione != .cose { sezione = .cose }
        if coseIndice[id] == nil { await caricaCose() }
        guard coseIndice[id] != nil else { return }
        coseScelte = [id]
        cosaAperta = id
        dettaglioCose = true
    }


    func annullaUltimo() {
        if let um = coseUndo, um.canUndo { um.undo() }
    }


    func fattaORiapri(_ ids: [String]) async {
        let righe = ids.compactMap { coseIndice[$0] }
        guard !righe.isEmpty else { return }

        if righe.allSatisfy({ $0.eliminata == true }) { await gestoTask("ripristina", ids) }

        else if righe.allSatisfy({ $0.chiusaOra }) { await gestoTask("riapri", ids) }
        else { await gestoTask("fatta", righe.filter { !$0.chiusaOra }.map(\.id)) }
    }



    func nuovaTask(_ titolo: String, campi: [String: String]) async -> String? {
        guard !modoIstantanea, !bloccaGesto() else { return nil }
        var ereditati: [String: String] = [:]
        if let s = schedaCose, !vistaSpeciale {
            if s.regola == "urgenti" || s.filtro?.pronto == "urgenti" || coseFiltroAlVolo["pronto"] == ["urgenti"] {
                ereditati["priorita"] = "1"
            }
            if let f = s.filtro {
                if f.priorita.count == 1 { ereditati["priorita"] = f.priorita[0] }
                if f.area.count == 1 { ereditati["area"] = f.area[0] }
                if f.stato.count == 1 { ereditati["stato"] = f.stato[0] }
            }
            for (k, v) in coseFiltroAlVolo where v.count == 1 && ["priorita", "area", "stato"].contains(k) { ereditati[k] = v[0] }
        }
        let tutti = ereditati.merging(campi) { _, nuovo in nuovo }
        let coppie = tutti.sorted { $0.key < $1.key }.map { "\($0.key)=\($0.value)" }
        let scatola = ScatolaEventi()
        registraAnnulla(scatola, nome: t("azione_nuova"))


        let comando = ["cose", "nuova", titolo] + (coppie.isEmpty ? ["stato=\(cose?.impostazioni?.predefinito ?? "da_fare")"] : coppie)
        let r = await inFila { [weak self] in
            guard let self else { return EsitoCosa?.none }
            return self.esitoCosa(await self.motore.chiedi(comando, scadenza: 30))
        }
        guard let r, r.ok, let id = r.id else {
            ritiraAnnulla(scatola)
            scatola.pronta = true
            coseEsito = EsitoRiga(testo: r?.errore ?? t("errore_motore"), errore: true)
            return nil
        }
        scatola.eventi = r.eventi ?? []
        scatola.ids = [id]
        scatola.pronta = true
        if scatola.eventi.isEmpty { ritiraAnnulla(scatola) }
        coseAppenaAggiunte.insert(id, at: 0)
        await caricaCose()
        let dentro = schedaCose?.id_righe.contains(id) ?? true
        coseEsito = EsitoRiga(testo: dentro ? (r.riga ?? r.messaggio ?? "") : t("esito_nuova_altrove"),
                              annullabile: !(r.eventi ?? []).isEmpty)
        return id
    }


    func capisci(_ testo: String) async -> CapitoTitolo? {
        let r = await motore.chiedi(["cose", "capisci", testo], scadenza: 10)
        return try? JSONDecoder().decode(CapitoTitolo.self, from: r.dati)
    }





    @discardableResult
    func gestoVista(_ argomenti: [String], annullabile: Bool = true, undo: UndoManager? = nil, ordine: Bool = false) async -> EsitoCosa? {

        var contato = ordine
        defer { if contato { coseOrdiniInVolo -= 1 } }
        guard !modoIstantanea, !bloccaGesto() else { return nil }
        traccia("gestoVista \(argomenti)")
        defer { traccia("gestoVista end") }

        let scatola = ScatolaVista()

        let um = undo ?? coseUndo
        let nome = argomenti.first.map { $0.hasPrefix("vista") ? t("azione_vista") : t("azione_impostazioni") } ?? ""
        if annullabile { registraAnnullaVista(scatola, nome: nome, undo: um) }
        traccia("gestoVista undo registered")
        traccia("gestoVista asking")


        let comando = ["cose"] + argomenti
        let e = await inFila { [weak self] in
            guard let self else { return EsitoCosa?.none }
            return self.esitoCosa(await self.motore.chiedi(comando, scadenza: 15))
        }
        if contato { coseOrdiniInVolo -= 1; contato = false }
        traccia("gestoVista response \(e?.ok ?? false) undo \(e?.annulla ?? [])")
        if let e, e.ok, let inverso = e.annulla, annullabile {


            scatola.argomenti = inverso
        } else {
            um?.removeAllActions(withTarget: scatola)
        }
        traccia("gestoVista undo ok")
        scatola.pronta = true
        if undo != nil {

            coseEsitoImpostazioni = e?.ok == true ? EsitoRiga(testo: e?.riga ?? e?.messaggio ?? "", annullabile: e?.annulla != nil)
                : EsitoRiga(testo: e?.errore ?? t("errore_motore"), errore: true)
        }
        if let e, e.ok {

            if let m = e.riga ?? e.messaggio, !m.isEmpty, annullabile { coseEsito = EsitoRiga(testo: m, annullabile: e.annulla != nil) }
        } else {
            coseEsito = EsitoRiga(testo: e?.errore ?? t("errore_motore"), errore: true)
        }
        await caricaCose()

        if ordine, e?.ok != true, coseOrdiniInVolo == 0 { applicaOrdineSalvato() }
        return e
    }





    func registraAnnullaVista(_ scatola: ScatolaVista, nome: String, undo: UndoManager? = nil) {
        guard let um = undo ?? coseUndo else { return }



        let apri = um.groupingLevel == 0 && !um.isUndoing && !um.isRedoing
        traccia("register «\(nome)» level \(um.groupingLevel) undoing \(um.isUndoing) redoing \(um.isRedoing) open \(apri)")
        if apri { um.beginUndoGrouping() }
        defer { if apri { um.endUndoGrouping() } }
        um.registerUndo(withTarget: scatola) { [weak self, weak um] _ in
            guard let s = self, let um else { return }
            let ritorno = ScatolaVista()
            s.registraAnnullaVista(ritorno, nome: nome, undo: um)
            Task { @MainActor in
                var attesa = 0
                while !scatola.pronta && attesa < 400 { try? await Task.sleep(nanoseconds: 50_000_000); attesa += 1 }
                guard !scatola.argomenti.isEmpty else { um.removeAllActions(withTarget: ritorno); ritorno.pronta = true; return }
                if undo == nil, s.sezione != .cose { s.sezione = .cose }
                let e = s.esitoCosa(await s.motore.chiedi(["cose"] + scatola.argomenti, scadenza: 15))
                if let e, e.ok, let inverso = e.annulla {
                    ritorno.argomenti = inverso
                } else {
                    um.removeAllActions(withTarget: ritorno)
                }
                ritorno.pronta = true
                s.coseEsito = EsitoRiga(testo: e?.ok == true ? (e?.riga ?? s.t("esito_annullato")) : (e?.errore ?? s.t("errore_motore")),
                                        errore: e?.ok != true)

                if undo != nil { s.coseEsitoImpostazioni = s.coseEsito }
                await s.caricaCose()
            }
        }
        if !nome.isEmpty { um.setActionName(nome) }
    }


    func vistaVicina(_ passo: Int) {
        let schede = schedeVisibili
        guard !schede.isEmpty else { return }
        let i = schede.firstIndex { $0.id == coseVista } ?? 0
        coseVista = schede[(i + passo + schede.count) % schede.count].id
    }


    func copiaTitoli(_ ids: [String]) {
        let titoli = righeAVista().filter { ids.contains($0.id) }.map(\.titolo)
        let tutti = titoli.isEmpty ? ids.compactMap { coseIndice[$0]?.titolo } : titoli
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(tutti.joined(separator: "\n"), forType: .string)
    }


    var idsAzione: [String] {
        if !coseScelte.isEmpty {
            let ordine = righeAVista().map(\.id)
            return ordine.filter { coseScelte.contains($0) } + coseScelte.filter { !ordine.contains($0) }.sorted()
        }
        if dettaglioCose, let id = cosaAperta { return [id] }
        return []
    }
}


struct CapitoTitolo: Codable, Equatable {
    struct Etichetta: Codable, Equatable, Hashable {
        let tipo: String
        let testo: String
        let parole: String
    }
    let ok: Bool
    let titolo: String
    let priorita: Int?
    let scadenza: String?
    let etichette: [Etichetta]
}

extension Store {



    func filtraAlVolo(_ campo: String, _ valore: String, _ si: Bool, una: Bool) {
        var v = una ? [] : (coseFiltroAlVolo[campo] ?? [])
        v.removeAll { $0 == valore }
        if si { v.append(valore) }
        coseFiltroAlVolo[campo] = v.isEmpty ? nil : v
        coseTenute = []
    }



    func salvaFiltri(nuova: Bool) async {
        guard let s = schedaCose else { return }
        let base = s.filtro
        var f: [String: Any] = [
            "priorita": base?.priorita ?? [], "stato": base?.stato ?? [], "area": base?.area ?? [],
            "scadenza": base?.scadenza as Any, "stima": base?.stima as Any, "pronto": base?.pronto as Any,
        ]


        var vuoto = false
        for (campo, valori) in coseFiltroAlVolo where !valori.isEmpty {
            if campo == "pronto" {

                f[campo] = valori.first
            } else if ["scadenza", "stima"].contains(campo) {
                let prima = f[campo] as? String
                guard let nuovo = valori.first else { continue }
                if let prima, let stretto = Store.incrocioUnaScelta(campo, prima, nuovo) { f[campo] = stretto }
                else if prima == nil { f[campo] = nuovo }
                else { vuoto = true }
            } else {
                let prima = (f[campo] as? [String]) ?? []
                let incrocio = prima.isEmpty ? valori : prima.filter { valori.contains($0) }
                if incrocio.isEmpty { vuoto = true }
                f[campo] = incrocio
            }
        }
        if vuoto {
            coseEsito = EsitoRiga(testo: t("errore_filtri_senza_task"), errore: true)
            return
        }
        let pulito = f.mapValues { $0 is NSNull ? NSNull() : $0 }
        guard let dati = try? JSONSerialization.data(withJSONObject: pulito), let json = String(data: dati, encoding: .utf8) else { return }
        var id = s.id
        if nuova {
            guard let e = await gestoVista(["vista-nuova", s.modo, s.id]), let nuovo = e.id else { return }
            id = nuovo
        }
        await gestoVista(["vista-imposta", id, "filtro", json], annullabile: !nuova)
        coseFiltroAlVolo = [:]
        coseVista = id
    }



    static func incrocioUnaScelta(_ campo: String, _ a: String, _ b: String) -> String? {
        if a == b { return a }
        let dentro: [String: Set<String>] = campo == "scadenza"
            ? ["con_data": ["scadute", "oggi", "settimana"], "settimana": ["oggi"]]
            : ["fino_120": ["fino_30"]]
        if dentro[a]?.contains(b) == true { return b }
        if dentro[b]?.contains(a) == true { return a }
        return nil
    }


    var livelliOrdine: [OrdineVista] { coseOrdine.map { OrdineVista(campo: $0.campo, verso: $0.order == .forward ? "su" : "giu") } }


    var paroleOrdine: String {
        let l = coseOrdine
        guard l.count > 1 else { return "" }
        return l.enumerated().map { i, o in
            t(i == 0 ? "ordine_parole_primo" : "ordine_parole_poi").replacingOccurrences(of: "{campo}", with: t("ordine_campo_\(o.campo)"))
        }.joined()
    }


    func versoDiPartenza(_ campo: String) -> String {
        cose?.colonne_info?.first { $0.campo_ordine == campo }?.verso_di_partenza
            ?? cose?.ordini?.first { $0.id == campo }?.verso_di_partenza ?? "su"
    }

    static func comparatori(_ livelli: [OrdineVista]) -> [OrdineCosa] {
        Array(livelli.filter { $0.campo != "pronto" }.prefix(3).map(OrdineCosa.init))
    }



    static func ordinate(_ righe: [VoceCosa], _ ordine: [OrdineCosa], posizione: [String: Int] = [:]) -> [VoceCosa] {
        guard !ordine.isEmpty else { return righe }
        let pos = posizione.isEmpty ? Dictionary(righe.enumerated().map { ($1.id, $0) }, uniquingKeysWith: { a, _ in a }) : posizione
        return righe.sorted { a, b in
            for o in ordine {
                switch o.compare(a, b) {
                case .orderedAscending: return true
                case .orderedDescending: return false
                case .orderedSame: continue
                }
            }
            return (pos[a.id] ?? Int.max) < (pos[b.id] ?? Int.max)
        }
    }


    func impostaOrdine(_ s: SchedaCose, _ campo: String, _ verso: String) {
        impostaOrdine(s, campo == "pronto" ? [] : [OrdineVista(campo: campo, verso: verso)])
    }



    func impostaOrdine(_ s: SchedaCose, _ livelli: [OrdineVista]) {
        var visti = Set<String>()
        let puliti = Array(livelli.filter { $0.campo != "pronto" && visti.insert($0.campo).inserted }.prefix(3))
        coseOrdine = Store.comparatori(puliti)

        coseTenute = []
        coseFoto = nil
        guard !modoIstantanea, !vistaSpeciale(s.id) else { return }
        let json = puliti.isEmpty ? "null"
            : "[" + puliti.map { "{\"campo\": \"\($0.campo)\", \"verso\": \"\($0.verso)\"}" }.joined(separator: ", ") + "]"

        if puliti == (cose?.schede?.first { $0.id == s.id }?.livelli ?? s.livelli) { return }
        coseOrdiniInVolo += 1
        coseOrdiniDati += 1
        Task { await gestoVista(["vista-imposta", s.id, "ordine", json], ordine: true) }
    }




    func clicIntestazione(_ s: SchedaCose, _ campo: String, aggiungi: Bool) {
        var livelli = livelliOrdine
        let gira = { (v: String) in v == "su" ? "giu" : "su" }
        if let i = livelli.firstIndex(where: { $0.campo == campo }), aggiungi || i == 0 {
            livelli[i] = OrdineVista(campo: campo, verso: gira(livelli[i].verso))
        } else if aggiungi {
            guard livelli.count < 3 else {
                coseEsito = EsitoRiga(testo: t("ordine_tre_al_piu"), errore: false, annullabile: false)
                coseOrdine = coseOrdine  // la tabella torna a mostrare i livelli di prima
                return
            }
            livelli.append(OrdineVista(campo: campo, verso: versoDiPartenza(campo)))
        } else {
            livelli = [OrdineVista(campo: campo, verso: versoDiPartenza(campo))]
        }
        impostaOrdine(s, livelli)
    }


    func applicaOrdineSalvato() {
        coseOrdine = Store.comparatori(schedaCose?.livelli ?? [])
    }
}



struct OrdineCosa: SortComparator, Hashable {
    let campo: String
    var order: SortOrder = .forward

    init(campo: String, order: SortOrder = .forward) {
        self.campo = campo
        self.order = order
    }

    init(_ o: OrdineVista) { self.init(campo: o.campo, order: o.verso == "giu" ? .reverse : .forward) }



    func vuota(_ v: VoceCosa) -> Bool {
        switch campo {
        case "scadenza": return (v.giorno ?? "").isEmpty
        case "stima": return v.stima_min == nil
        case "inizio": return v.o_inizio == nil
        case "area": return v.o_area == nil && v.area_id != nil
        case "chiusa": return v.o_chiusa == nil
        default: return false
        }
    }

    func chiave(_ v: VoceCosa) -> Int? {
        switch campo {
        case "scadenza": return v.o_scadenza
        case "priorita": return v.o_priorita
        case "stima": return v.o_stima
        case "titolo": return v.o_titolo
        case "area": return v.o_area
        case "stato": return v.o_stato
        case "cambio": return v.o_cambio
        case "creata": return v.o_creata
        case "inizio": return v.o_inizio
        case "chiusa": return v.o_chiusa

        case "rinvii": return v.o_rinvii ?? 0
        case "commenti": return v.o_commenti ?? 0
        default: return nil
        }
    }

    func compare(_ a: VoceCosa, _ b: VoceCosa) -> ComparisonResult {
        let va = vuota(a), vb = vuota(b)
        if va || vb { return va == vb ? .orderedSame : (va ? .orderedDescending : .orderedAscending) }
        var r: ComparisonResult
        if let x = chiave(a), let y = chiave(b) {
            r = x == y ? .orderedSame : (x < y ? .orderedAscending : .orderedDescending)
        } else if campo == "titolo" || campo == "area" {

            let x = campo == "titolo" ? a.titolo : a.area, y = campo == "titolo" ? b.titolo : b.area
            r = x.compare(y, options: [.caseInsensitive, .diacriticInsensitive])
        } else {
            r = .orderedSame
        }

        if r == .orderedSame, campo == "stato", let x = a.o_nello_stato, let y = b.o_nello_stato, x != y {
            r = x < y ? .orderedAscending : .orderedDescending
        }
        if order == .reverse { r = r == .orderedAscending ? .orderedDescending : (r == .orderedDescending ? .orderedAscending : r) }
        return r
    }
}

extension Store {



    nonisolated static let chiaveColonne = "attivitaColonneG3"


    static var misuraDecodifica: (Duration, Int)?


    static var finestraProva: NSWindow?


    static var statiDef: [String: StatoDef] = [:]

    static var sezioneImpostazioni = "stati"



    func tieniLaMia(_ c: ConflittoTesto) async {
        togliConflitto(c)
        let e = await gestoTask(c.campo, [c.id], [c.mio], era: c.loro)
        if let v = e?.intanto { coseConflitto = ConflittoTesto(id: c.id, campo: c.campo, mio: c.mio, loro: v) }
    }

    func togliConflitto(_ c: ConflittoTesto) { coseConflitti.removeAll { $0 == c } }


    static let contrattoMinimo = 1

    var motoreVecchio: Bool {
        guard let c = cose else { return false }
        return (c.contratto ?? 0) < Store.contrattoMinimo
    }


    static let fraseMotoreVecchio = "The Tasks engine is a different version, update the app."

    func bloccaGesto() -> Bool {
        guard motoreVecchio else { return false }
        coseEsito = EsitoRiga(testo: cose?.testi?["motore_altra_versione"] ?? Store.fraseMotoreVecchio, errore: true)
        return true
    }



    func iniziaFoglio(_ v: VoceCosa, con testo: String) {
        coseFoglioEra = v.titolo
        coseFoglioBozza = testo
        coseFoglioColonna = "task"
        coseFoglioModifica = v.id
        if testo != v.titolo, !testo.isEmpty { coseScrittiInCorso["\(v.id)|titolo"] = (v.id, "titolo", testo, v.titolo) }
    }




    @discardableResult
    func salvaScritto(id: String, campo: String, testo: String, era: String) async -> EsitoCosa? {
        traccia("save \(campo) \(id) was \(era.count) text \(testo.count)")
        let e = await gestoTask(campo, [id], [testo], era: era)


        let k = "\(id)|\(campo)"
        if e != nil, coseScrittiInCorso[k]?.testo == testo { coseScrittiInCorso[k] = nil }

        if let v = e?.intanto, v != testo { coseConflitto = ConflittoTesto(id: id, campo: campo, mio: testo, loro: v) }
        traccia("save \(campo) response ok \(e?.ok ?? false) error \(e?.errore ?? "-") meanwhile \(e?.intanto?.count ?? -1)")
        return e
    }



    func salvaScrittiAllaChiusura() {
        guard !motoreVecchio else { return }
        for (_, s) in coseScrittiInCorso {
            _ = motore.chiediSubito(["cose", s.campo, s.id, s.testo, "--era", s.era, "--una-volta", UUID().uuidString.lowercased()],
                                    scadenza: 5)
        }
        coseScrittiInCorso = [:]
    }


    func apriImpostazioni(_ sezione: String) {
        Store.sezioneImpostazioni = sezione

        schedaImpostazioni = Store.schedaAttivita
        guard !modoIstantanea else { return }


        NotificationCenter.default.post(name: .apriImpostazioniAttivita, object: sezione)
    }


    static var infoColonne: [InfoColonna] = []

    static var colonneAccendibili: [String] {
        infoColonne.isEmpty ? ["priorita", "scadenza", "stima", "area", "stato", "cambio", "creata"]
            : infoColonne.map(\.id).filter { $0 != "cerchio" && $0 != "task" }
    }

    nonisolated static let chiaveColonneFoglio = "attivitaColonneFoglio"

    static func colonneSalvate(_ chiave: String = chiaveColonne) -> TableColumnCustomization<VoceCosa> {
        guard let dati = UserDefaults.standard.data(forKey: chiave),
              let c = try? JSONDecoder().decode(TableColumnCustomization<VoceCosa>.self, from: dati) else { return .init() }
        return c
    }

    static func salvaColonne(_ c: TableColumnCustomization<VoceCosa>, _ chiave: String = chiaveColonne) {
        guard let dati = try? JSONEncoder().encode(c), let albero = try? JSONSerialization.jsonObject(with: dati) else { return }
        func senza(_ x: Any) -> Any {
            if let d = x as? [String: Any] { return d.filter { $0.key != "currentWidth" }.mapValues(senza) }
            if let a = x as? [Any] { return a.map(senza) }
            return x
        }
        if let pulito = try? JSONSerialization.data(withJSONObject: senza(albero)) {
            UserDefaults.standard.set(pulito, forKey: chiave)
        }
    }
}

extension Store {

    func nuovaQui(_ campo: String, _ valore: String) {
        coseNuovaIn = [campo == "fatte" ? "stato" : campo: valore]
        coseFuocoChiesto = .nuova
    }
}

extension Store {




    @discardableResult
    func daTasto(cancella: Bool = false, _ azione: () -> Void) -> DecisioneTasto {

        let davanti = NSApp.keyWindow ?? Store.finestraProva
        let principale = Store.finestraPrincipale
        let d = Store.decidiTasto(davantiPrincipale: davanti != nil && davanti === principale,
                                  principaleRiconosciuta: principale != nil,
                                  inAttivita: sezione == .cose,
                                  inUnCampo: davanti?.firstResponder is NSText)
        switch d {
        case .alCampo:

            if cancella { NSApp.sendAction(#selector(NSResponder.deleteToBeginningOfLine(_:)), to: nil, from: nil) }
        case .niente:
            break
        case .agisci:
            azione()
        }
        return d
    }

    enum DecisioneTasto: Equatable { case agisci, alCampo, niente }






    nonisolated static func decidiTasto(davantiPrincipale: Bool, principaleRiconosciuta: Bool, inAttivita: Bool,
                                        inUnCampo: Bool) -> DecisioneTasto {
        if inUnCampo { return .alCampo }
        guard principaleRiconosciuta else { return .agisci }
        return davantiPrincipale && inAttivita ? .agisci : .niente
    }



    static weak var finestraPrincipale: NSWindow?
}



enum TestiMancanti {
    nonisolated(unsafe) private static var viste = Set<String>()
    static func manca(_ chiave: String) -> String {
        if !viste.contains(chiave) {
            viste.insert(chiave)
            NSLog("SBK Tasks: missing key «%@»", chiave)
            if ProcessInfo.processInfo.environment["SB_TRACCIA"] != nil {
                FileHandle.standardError.write("missing key \(chiave)\n".data(using: .utf8)!)
            }
        }
        return ""
    }
}



@MainActor @Observable
final class RegistroStati {
    static let condiviso = RegistroStati()
    var def: [String: StatoDef] = [:]
}

extension Notification.Name {

    static let apriImpostazioniAttivita = Notification.Name("apriImpostazioniAttivita")
}


@MainActor func traccia(_ s: @autoclosure () -> String) {
    if ProcessInfo.processInfo.environment["SB_TRACCIA"] != nil { FileHandle.standardError.write((s() + "\n").data(using: .utf8)!) }
}
