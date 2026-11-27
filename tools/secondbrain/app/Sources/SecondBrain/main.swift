import AppKit
import SwiftUI











let argomenti = CommandLine.arguments
if argomenti.contains("--prova-voce") {

    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    Task { @MainActor in exit(await ProvaAttivita.voce() ? 0 : 1) }
    app.run()
} else if argomenti.contains("--prova-tasti") {

    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    Task { @MainActor in exit(await ProvaTasti.fai() ? 0 : 1) }
    app.run()
} else if argomenti.contains("--prova-attivita") {

    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    Task { @MainActor in exit(await ProvaAttivita.fai() ? 0 : 1) }
    app.run()
} else if let i = argomenti.firstIndex(of: "--istantanea"), i + 1 < argomenti.count {
    let cartella = URL(fileURLWithPath: argomenti[i + 1])
    let fileStato = argomenti.firstIndex(of: "--stato").flatMap { $0 + 1 < argomenti.count ? argomenti[$0 + 1] : nil }
    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    Task { @MainActor in
        let ok = await Istantanea.fai(in: cartella, fileStato: fileStato)
        exit(ok ? 0 : 1)
    }
    app.run()
} else {
    SBKApp.main()
}

@MainActor
enum Istantanea {
    struct Scena {
        let nome: String
        let prepara: (Store) -> Void
    }

    static func fai(in cartella: URL, fileStato: String?) async -> Bool {
        try? FileManager.default.createDirectory(at: cartella, withIntermediateDirectories: true)
        let store = Store()


        store.modoIstantanea = true


        store.filtroInspiration = .partenza
        store.vistaInspiration = nil
        store.pannelloFiltriInspiration = false
        if let fileStato {
            guard let dati = FileManager.default.contents(atPath: fileStato),
                  let stato = try? JSONDecoder().decode(Stato.self, from: dati) else {
                FileHandle.standardError.write("error: the state in \(fileStato) can't be read\n".data(using: .utf8)!)
                return false
            }
            store.stato = stato
            store.lettoAlle = Quando.data(stato.generato)

            if let v = stato.vocabolario { Vocabolario.voci = v }
        } else {
            await store.aggiorna()
        }
        guard let stato = store.stato else {
            FileHandle.standardError.write("error: \(store.errore ?? "") \(store.dettaglioErrore ?? "")\n".data(using: .utf8)!)
            return false
        }
        let primaFonte = stato.fonti.first(where: { $0.salute != "ok" && $0.gruppo == "da_sole" })?.id
            ?? stato.fonti.first?.id ?? ""
        let scene = [
            Scena(nome: "1-panoramica") { s in
                s.sezione = .panoramica
                s.ispettore = false
            },
            Scena(nome: "2-fonti") { s in
                s.sezione = .fonti
                s.selezione = .fonte(primaFonte)
                s.ispettore = true
            },
            Scena(nome: "3-pipeline") { s in
                s.sezione = .pipeline
                s.selezione = .stadio("l3_extract_rel")
                s.ispettore = true
            },
            Scena(nome: "4-run") { s in
                s.sezione = .run
                s.ispettore = false
            },
            Scena(nome: "5-spesa-chiavi") { s in
                s.sezione = .spesa
                s.ispettore = false
            },
            Scena(nome: "9-ricerca") { s in
                s.ricerca = "drive"
                s.ispettore = false
            },

            Scena(nome: "13-regole-fonti") { s in
                s.sezione = .regole
                s.vistaRegole = .fonti
                s.regoleAperte = ["fonte:gdrive"]
                s.ispettore = false
            },
            Scena(nome: "14-regole-step") { s in
                s.sezione = .regole
                s.vistaRegole = .stadi
                s.regoleAperte = ["stadio:l2_knowledge_extract"]
                s.ispettore = false
            },
            Scena(nome: "15-regole-generali") { s in
                s.sezione = .regole
                s.vistaRegole = .generali
                s.ispettore = false
            },
            Scena(nome: "16-dettaglio-come-lavora") { s in
                s.sezione = .fonti
                s.selezione = .fonte("gdrive")
                s.ispettore = true
            },
            Scena(nome: "17-ricerca-regole") { s in
                s.ricerca = "incremental"
                s.ispettore = false
            },

            Scena(nome: "20-strumenti") { s in
                s.sezione = .strumenti
                s.ispettore = false
            },

            Scena(nome: "21-strumenti-permesso") { s in
                s.sezione = .strumenti
                s.ispettore = false
                s.permessoAvvisi = .daChiedere
            },

            Scena(nome: "23-posta") { s in
                s.sezione = .posta
                s.ispettore = false
            },

            Scena(nome: "24-firme") { s in
                s.sezione = .firme
                s.ispettore = false
            },

            Scena(nome: "25-pagine") { s in
                s.sezione = .pagine
                s.vistaPagine = .data
                s.paginaAperta = nil
                s.ispettore = false
            },
            Scena(nome: "26-pagine-account") { s in
                s.sezione = .pagine
                s.vistaPagine = .account
                s.paginaAperta = nil
                s.ispettore = false
            },
            Scena(nome: "27-pagina-aperta") { s in
                s.sezione = .pagine
                s.paginaAperta = s.pagine?.pagine.first { $0.copia != nil }
                s.ispettore = false
            },

            Scena(nome: "28-inspiration") { s in
                s.sezione = .inspiration
                s.paginaAperta = nil
                s.ispettore = false
            },

            Scena(nome: "29-spunto-lavorazione") { s in
                s.sezione = .inspiration
                s.paginaAperta = nil
                s.ispettore = false
                s.spuntoAperto = ProcessInfo.processInfo.environment["SB_SPUNTO"]
                    ?? s.inspiration?.voci.first { $0.lavorazione?.perche.c_e == true }?.id
            },

            Scena(nome: "30-bacheca-rilettura") { s in
                s.sezione = .inspiration
                s.paginaAperta = nil
                s.ispettore = false
                s.spuntoAperto = nil
                s.riletturaInspiration = Rilettura(
                    ok: true, messaggio: nil,
                    frase: "I re-read your DM, 12 messages. 2 new ideas, your new words on 1. In the background I'm downloading 2 reels, you'll see them here as soon as they land",
                    dettaglio: ["https://www.example.com/reel/EXAMPLE1/", "https://www.example.com/post/EXAMPLE2",
                                "Your new words on «an example article»"])
            },



            Scena(nome: "36-inspiration-filtri") { s in
                s.sezione = .inspiration
                s.paginaAperta = nil
                s.ispettore = false
                s.spuntoAperto = nil
                s.pannelloFiltriInspiration = true
            },

            Scena(nome: "31-cose") { s in
                s.sezione = .cose
                s.ispettore = false
                let env = ProcessInfo.processInfo.environment

                if let v = env["SB_VISTA"] { s.coseVista = v }
                else if let m = env["SB_MODO"], m != "tabella" { s.coseVista = m }

                if let id = env["SB_COSA"] { s.coseScelte = [id]; s.cosaAperta = id; s.dettaglioCose = true }
                if let ids = env["SB_SCELTE"] { s.coseScelte = Set(ids.split(separator: ",").map(String.init)) }
                if let q = env["SB_CERCA"] { s.coseCerca = q }
                if let m = env["SB_MESE"] { s.coseMese = m }


                if let f = env["SB_VOCE_FINTA"], let dati = try? Data(contentsOf: URL(fileURLWithPath: f)),
                   let v = try? JSONDecoder().decode(StatoVoce.self, from: dati) {
                    s.voceAttivita = v
                    s.voceFintaCaricata = true
                    s.voceChiuse = []
                }
                if let d = env["SB_DETTATO"], let n = Int(d) { s.voceFintaSecondi = n }

                if let f = env["SB_FILTRO"] {
                    for pezzo in f.split(separator: ";") {
                        let kv = pezzo.split(separator: "=", maxSplits: 1).map(String.init)
                        if kv.count == 2 { s.coseFiltroAlVolo[kv[0]] = kv[1].split(separator: ",").map(String.init) }
                    }
                }

                if let e = env["SB_ESITO"] { s.coseEsito = EsitoRiga(testo: e, errore: env["SB_ESITO_ERRORE"] == "1", annullabile: true) }


                if let c = env["SB_COLONNE"] { s.coseColonne = colonneDa(c) }
                if env["SB_DUE_RIGHE"] == "1" { s.coseDueRighe = true }

                if let g = env["SB_GIORNO"] { StatoSettimana.condiviso.giorno = g }

                if let c = env["SB_FOGLIO_COLONNA"] { s.coseFoglioColonna = c }

                if let id = env["SB_FOGLIO_SCRIVE"] {
                    s.coseFoglioColonna = "task"
                    s.coseFoglioModifica = id
                    s.coseFoglioBozza = env["SB_FOGLIO_BOZZA"] ?? ""
                }
            },

            Scena(nome: "32-impostazioni") { s in
                s.sezione = .cose
                s.ispettore = false
                Store.sezioneImpostazioni = ProcessInfo.processInfo.environment["SB_IMPOSTAZIONI"] ?? "stati"
            },

            Scena(nome: "33-menu") { s in
                s.sezione = .cose
                s.ispettore = false
            },

            Scena(nome: "35-impostazioni-inspiration") { s in
                s.sezione = .inspiration
                s.ispettore = false
            },

            Scena(nome: "34-plaud") { s in
                s.sezione = .plaud
                s.ispettore = false
                let env = ProcessInfo.processInfo.environment
                PlaudStore.condiviso.modulo = env["SB_PLAUD_MODULO"] ?? "quadro"
                PlaudStore.condiviso.cerca = env["SB_PLAUD_CERCA"] ?? ""
                PlaudStore.condiviso.soloIndizi = env["SB_PLAUD_INDIZI"] == "1"
            },

            Scena(nome: "19-ricerca-dati") { s in
                s.ricerca = "full Drive history"
                s.ispettore = false
            },
        ]
        let soloScena = ProcessInfo.processInfo.environment["SB_SCENE"]
        let larghezza = CGFloat(Double(ProcessInfo.processInfo.environment["SB_LARGHEZZA"] ?? "") ?? 1280)
        let altezza = CGFloat(Double(ProcessInfo.processInfo.environment["SB_ALTEZZA"] ?? "") ?? 820)
        if ProcessInfo.processInfo.environment["SB_MISURA"] == "1" {

            store.modoIstantanea = true
            func minima(_ nome: String, _ vista: some View) {
                let c = NSHostingController(rootView: vista.environment(store))
                let w = c.sizeThatFits(in: CGSize(width: 120, height: 100_000)).width
                FileHandle.standardError.write("\(nome)\t\(Int(w))\n".data(using: .utf8)!)
            }
            minima("panoramica", Panoramica(stato: stato))
            minima("fonti", PaginaFonti(stato: stato))
            minima("pipeline", PaginaPipeline(stato: stato))
            minima("run", PaginaRun(stato: stato))
            minima("spesa", PaginaSpesa(stato: stato))
            await store.caricaRegole()
            minima("regole", PaginaRegole(stato: stato))
            for (i, f) in stato.fasi.enumerated() { minima("fase-\(f.id)", SchedaFase(fase: f, numero: i + 1, stato: stato)) }
            for s in stato.stadi.prefix(14) { minima("stadio-\(s.id)", RigaStadio(stadio: s)) }
            if let r = stato.run_app ?? stato.runs.last {
                minima("scheda-run", SchedaRun(run: r, avanzamento: r.avanzamento))
                minima("passi", RiquadroPassi(avanzamento: r.avanzamento, run: r))
                minima("registro", RiquadroRegistro(run: r))
            }
            minima("da-fuori", SchedaDaFuori(daFuori: stato.da_fuori, stato: stato))
            minima("passi-da-fuori", RiquadroPassi(avanzamento: stato.da_fuori.giro, run: nil))
            minima("recenti", RunRecenti(runs: stato.runs))
            return true
        }
        var ok = true
        store.modoIstantanea = true

        let dominioIstantanea = Bundle.main.bundleIdentifier ?? ProcessInfo.processInfo.processName
        let preferenzeIstantanea = UserDefaults.standard.persistentDomain(forName: dominioIstantanea)
        defer {
            if let preferenzeIstantanea { UserDefaults.standard.setPersistentDomain(preferenzeIstantanea, forName: dominioIstantanea) }
            else { UserDefaults.standard.removePersistentDomain(forName: dominioIstantanea) }
        }
        await store.caricaRegole()
        await store.caricaSoglie()
        await store.caricaStrumenti()
        await store.caricaDrive()
        await store.caricaVerifiche()
        await store.caricaPosta()
        await store.caricaContoPosta()
        await store.caricaFirme()
        await store.caricaCose()
        await store.caricaPagine()
        await store.caricaInspiration()
        await PlaudStore.condiviso.carica(store)
        if soloScena == "19" { await store.cercaNeiDati("full Drive history") }
        if store.stima == nil {
            let ultima = await store.motore.chiedi(["stima", "--ultima"])
            store.stima = (try? JSONDecoder().decode(EsitoStima.self, from: ultima.dati))?.stima
        }
        let aMano = stato.fonti.filter { $0.gruppo == "a_mano" }
        let pagati = stato.stadi.filter(\.pagato).map(\.id)

        store.spesaScelta = Set(pagati.dropLast())
        var fogli: [(String, Foglio)] = [("6-foglio-full-free", .fullRun), ("7-foglio-completa", .completa("full_completa")),
                                         ("8-foglio-come-si-fa", .comeSiFa(aMano)), ("10-foglio-guida", .guida)]

        if let r = stato.run_app { fogli.append(("11-foglio-ferma", .ferma(r))) }
        if let r = stato.ripresa { fogli.append(("12-foglio-riprendi", .riprendi(r))) }
        fogli.append(("18-foglio-copie", .copie))

        fogli.append(("22-foglio-verifiche", .verifiche))
        for (nome, foglio) in fogli where soloScena == nil || nome.hasPrefix(soloScena! + "-") {
            if !(await disegna(FoglioView(foglio: foglio).environment(store), nome: nome, in: cartella,
                               larghezza: 600, altezza: 700)) { ok = false }
        }
        for scena in scene where soloScena == nil || scena.nome.hasPrefix(soloScena! + "-") {
            FileHandle.standardError.write("scene \(scena.nome)\n".data(using: .utf8)!)
            store.ricerca = ""
            scena.prepara(store)
            if ProcessInfo.processInfo.environment["SB_ISPETTORE"] == "0" { store.ispettore = false }
            if ProcessInfo.processInfo.environment["SB_ISPETTORE"] == "1" { store.ispettore = true }



            if let a = ProcessInfo.processInfo.environment["SB_AVVISO"] { store.avviso = a }
            store.notiziaDaIstantanea()
            if ProcessInfo.processInfo.environment["SB_AGGIORNANDO"] == "1" { store.aggiornando = true }

            if let e = ProcessInfo.processInfo.environment["SB_ERRORE"] { store.errore = e }
            if let sel = ProcessInfo.processInfo.environment["SB_SELEZIONE"] {
                let pezzi = sel.split(separator: ":").map(String.init)
                switch pezzi.first {
                case "stadio": store.selezione = .stadio(pezzi[1])
                case "fonte": store.selezione = .fonte(pezzi[1])
                case "fase": store.selezione = .fase(pezzi[1])
                default: store.selezione = nil
                }
            }

            if ProcessInfo.processInfo.environment["SB_BARRA_VERA"] == "1" {
                if !(await barraVera(store, nome: scena.nome, in: cartella, larghezza: larghezza, altezza: altezza)) { ok = false }
                continue
            }
            for aspetto in ["scuro", "chiaro"] {
                let vista = VStack(spacing: 0) {


                    BarraFinta()
                    Divider()

                    Group {
                        if scena.nome == "32-impostazioni" { PannelloImpostazioniCose() }
                        else if scena.nome == "33-menu" { ProvaMenuCose() }

                        else if scena.nome == "35-impostazioni-inspiration" { PannelloImpostazioniInspiration() }
                        else { Principale() }
                    }

                    .overlay(alignment: .top) { ApertoNellaPagina() }
                }
                .environment(store)

                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(nsColor: .windowBackgroundColor))
                let host = NSHostingView(rootView: vista)
                host.frame = NSRect(x: 0, y: 0, width: larghezza, height: altezza)

                let forte = ProcessInfo.processInfo.environment["SB_CONTRASTO"] == "1"
                host.appearance = NSAppearance(named: aspetto == "scuro" ? (forte ? .accessibilityHighContrastDarkAqua : .darkAqua)
                                                                         : (forte ? .accessibilityHighContrastAqua : .aqua))
                let finestra = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)

                finestra.isReleasedWhenClosed = false
                finestra.appearance = host.appearance
                finestra.contentView = host
                let primoDisegno = ContinuousClock.now
                host.layoutSubtreeIfNeeded()
                let tempoDisegno = ContinuousClock.now - primoDisegno
                try? await Task.sleep(nanoseconds: 1_200_000_000)
                host.layoutSubtreeIfNeeded()


                if ProcessInfo.processInfo.environment["SB_MISURA_COSE"] == "1", aspetto == "chiaro", scena.nome == "31-cose" {
                    let t0 = ContinuousClock.now
                    let gruppi = store.disposizione()
                    let tDisp = ContinuousClock.now - t0
                    func ms(_ d: Duration) -> Double { Double(d.components.seconds) * 1000 + Double(d.components.attoseconds) / 1e15 }
                    var misura: [String: Any] = [
                        "larghezza": Int(larghezza), "decodifica_ms": Store.misuraDecodifica.map { ms($0.0) } ?? -1,
                        "pagina_byte": Store.misuraDecodifica?.1 ?? -1, "disposizione_ms": ms(tDisp),
                        "righe": gruppi.reduce(0) { $0 + $1.righe.count }, "primo_disegno_ms": ms(tempoDisegno),
                    ]
                    if let t = ProvaTasti.tabella(host), let sv = t.enclosingScrollView {
                        let vede = AdattaColonne.Coordinatore.parteVisibile(sv)
                        misura["tabella"] = ["si_vede": Int(vede), "larga": Int(t.frame.width), "oltre": t.frame.width > vede + 1,
                                             "colonne": t.tableColumns.filter { !$0.isHidden }.map { c -> [String: Any] in
                                                 let r = t.rect(ofColumn: t.column(withIdentifier: c.identifier))
                                                 let serve = c.headerCell.cellSize(forBounds: NSRect(x: 0, y: 0, width: 1000, height: 30)).width
                                                 return ["titolo": c.headerCell.stringValue, "x": Int(r.minX), "larga": Int(c.width),
                                                         "intestazione_sta": serve <= c.width + 0.5]
                                             }]
                    }
                    if let dati = try? JSONSerialization.data(withJSONObject: misura), let riga = String(data: dati, encoding: .utf8) {
                        FileHandle.standardError.write(("MISURA_COSE " + riga + "\n").data(using: .utf8)!)
                    }
                }


                let env = ProcessInfo.processInfo.environment
                if env["SB_COLONNE_DOPO"] != nil || env["SB_LARGHEZZA_DOPO"] != nil || env["SB_DETTAGLIO_DOPO"] != nil
                    || env["SB_ORDINE_DOPO"] != nil {

                    if let o = env["SB_ORDINE_DOPO"] {

                        store.coseOrdine = Store.comparatori(o.split(separator: ",").map { l in
                            let p = l.split(separator: ":").map(String.init)
                            return OrdineVista(campo: p[0], verso: p.count > 1 ? p[1] : "su")
                        })
                    }
                    if let c = env["SB_COLONNE_DOPO"] { store.coseColonne = colonneDa(c) }
                    if let d = env["SB_DETTAGLIO_DOPO"] { store.dettaglioCose = d == "1" }
                    if let w = env["SB_LARGHEZZA_DOPO"].flatMap(Double.init) {
                        finestra.setContentSize(NSSize(width: CGFloat(w), height: altezza))
                        host.frame = NSRect(x: 0, y: 0, width: CGFloat(w), height: altezza)
                    }
                    host.layoutSubtreeIfNeeded()
                    try? await Task.sleep(nanoseconds: 1_200_000_000)
                    host.layoutSubtreeIfNeeded()
                }

                if let x = ProcessInfo.processInfo.environment["SB_SCORRI_X"] { scorriTabelle(host, x) }
                host.display()
                guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else {
                    ok = false
                    continue
                }
                host.cacheDisplay(in: host.bounds, to: rep)
                if ProcessInfo.processInfo.environment["SB_MISURA_TABELLA"] == "1", aspetto == "chiaro" { misuraTabelle(host) }
                let file = cartella.appendingPathComponent("\(scena.nome)-\(aspetto).png")
                if (try? rep.representation(using: .png, properties: [:])?.write(to: file)) == nil { ok = false }
                print(file.path)
                finestra.close()
            }
        }
        return ok
    }



    static func colonneDa(_ c: String) -> TableColumnCustomization<VoceCosa> {
        if c.hasPrefix("/"), let dati = try? Data(contentsOf: URL(fileURLWithPath: c)),
           let salvate = try? JSONDecoder().decode(TableColumnCustomization<VoceCosa>.self, from: dati) { return salvate }
        var nuove = TableColumnCustomization<VoceCosa>()

        let ogni = ["priorita", "scadenza", "inizio", "stima", "area", "stato", "cambio", "creata", "chiusa", "rinvii", "commenti"]
        let accese = c == "tutte" ? ogni : c.split(separator: ",").map(String.init)
        for k in ogni { nuove[visibility: k] = accese.contains(k) ? .visible : .hidden }
        return nuove
    }



    static func misuraTabelle(_ radice: NSView) {
        func tutte(_ v: NSView) -> [NSTableView] { (v as? NSTableView).map { [$0] } ?? v.subviews.flatMap(tutte) }
        for t in tutte(radice) where t.tableColumns.count > 2 {
            let clip = t.enclosingScrollView.map { AdattaColonne.Coordinatore.parteVisibile($0) } ?? -1
            let sv = t.enclosingScrollView
            var righe = "table\twide \(Int(t.frame.width))\tvisible \(Int(clip))\tstyle \(t.columnAutoresizingStyle.rawValue)"
            if let sv { let f = sv.convert(sv.bounds, to: nil); righe += "\twindow y \(Int(f.minY))-\(Int(f.maxY)) x \(Int(f.minX))-\(Int(f.maxX))" }
            righe += "\tscrolls \(sv?.hasHorizontalScroller == true ? "yes" : "no")\tspacing \(Int(t.intercellSpacing.width))\tbar \(sv?.horizontalScroller.map { $0.isHidden ? "hidden" : "\(Int($0.frame.width))x\(Int($0.frame.height)) at \(Int($0.frame.minY))" } ?? "none") style \(sv?.scrollerStyle.rawValue ?? -1)\tx \(Int(sv?.contentView.bounds.origin.x ?? 0))"
            if let b = sv?.horizontalScroller, !b.isHidden {
                let f = b.convert(b.bounds, to: nil)
                righe += "\tbar in window y \(Int(f.minY))-\(Int(f.maxY)) alpha \(b.alphaValue) knob \(String(format: "%.2f", b.knobProportion)) active \(b.isEnabled) layer \(b.layer != nil)"
            }
            if let sv {
                let v = sv.verticalScroller
                righe += "\tclip \(Int(sv.contentView.frame.minX))-\(Int(sv.contentView.frame.maxX)) insets \(Int(sv.contentInsets.left)),\(Int(sv.contentInsets.right)) bar-insets \(Int(sv.scrollerInsets.right)) vertical \(v.map { $0.isHidden ? "hidden" : "\(Int($0.frame.minX))-\(Int($0.frame.maxX))" } ?? "no") has \(sv.hasVerticalScroller) automatic \(sv.automaticallyAdjustsContentInsets)"
            }
            righe += "\tother on the right \(ScorrimentoCose.condiviso.altroADestra) vertical bar \(Int(ScorrimentoCose.condiviso.barraVerticale)) margins \(Int(ScorrimentoCose.condiviso.margini))\n"
            for c in t.tableColumns where !c.isHidden {
                let titolo = c.headerCell.stringValue
                let hc = c.headerCell
                let serve = hc.cellSize(forBounds: NSRect(x: 0, y: 0, width: 1000, height: 30)).width
                let freccia = hc.sortIndicatorRect(forBounds: NSRect(x: 0, y: 0, width: 1000, height: 30)).width
                let r = t.rect(ofColumn: t.column(withIdentifier: c.identifier))
                righe += "  \(c.identifier.rawValue.suffix(6))\t«\(titolo)»\t\(Int(c.width)) [\(Int(c.minWidth))-\(Int(min(c.maxWidth, 9999)))]"
                righe += "\tx \(Int(r.minX))-\(Int(r.maxX))\tneeds \(Int(serve))+arrow \(Int(freccia))\(serve + ((hc.font?.fontName ?? "").contains("Semibold") ? 0 : freccia) > c.width ? "\tCLIPPED" : "")"
                righe += "\tfont \((hc.font?.fontName ?? "?")) \(hc.font?.pointSize ?? 0)"
                righe += "\tsize \(Int(MisureColonne.intestazione(titolo, hc.font, freccia: ScorrimentoCose.condiviso.postoFreccia))) arrow \(Int(ScorrimentoCose.condiviso.postoFreccia))"
                righe += " cell \(type(of: hc)) state \(hc.state.rawValue)\n"
            }
            FileHandle.standardError.write(righe.data(using: .utf8)!)
        }
    }

    static func scorriTabelle(_ radice: NSView, _ quanto: String) {
        func tutte(_ v: NSView) -> [NSTableView] { (v as? NSTableView).map { [$0] } ?? v.subviews.flatMap(tutte) }
        for t in tutte(radice) where t.tableColumns.count > 2 {
            guard let sv = t.enclosingScrollView else { continue }

            let fine = max(0, t.frame.width - sv.contentView.bounds.width)
            let x = quanto == "fine" ? fine + 50 : CGFloat(Double(quanto) ?? 0)
            if let cg = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 2, wheel1: 0, wheel2: Int32(-x), wheel3: 0) {
                cg.location = CGPoint(x: 1, y: 1)
                if let e = NSEvent(cgEvent: cg) { sv.scrollWheel(with: e) }
            }
            sv.layoutSubtreeIfNeeded()
        }
    }






    static func barraVera(_ store: Store, nome: String, in cartella: URL, larghezza: CGFloat, altezza: CGFloat) async -> Bool {
        var ok = true
        for aspetto in ["scuro", "chiaro"] {
            let host = NSHostingView(rootView: Principale().environment(store).frame(maxWidth: .infinity, maxHeight: .infinity))
            host.sceneBridgingOptions = [.toolbars, .title]
            host.frame = NSRect(x: 0, y: 0, width: larghezza, height: altezza)
            host.appearance = NSAppearance(named: aspetto == "scuro" ? .darkAqua : .aqua)
            let finestra = NSWindow(contentRect: host.frame,
                                    styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                                    backing: .buffered, defer: false)
            finestra.isReleasedWhenClosed = false
            finestra.appearance = host.appearance
            finestra.toolbarStyle = .unified
            finestra.contentView = host
            host.layoutSubtreeIfNeeded()
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            host.layoutSubtreeIfNeeded()
            let tema = host.superview ?? host
            tema.layoutSubtreeIfNeeded()
            var righe = "BAR \(nome) \(aspetto) wide \(Int(larghezza))"
            if let barra = finestra.toolbar {
                let visibili = Set((barra.visibleItems ?? []).map { ObjectIdentifier($0) })
                for it in barra.items {
                    let f = it.view.map { $0.convert($0.bounds, to: nil) } ?? .zero
                    righe += "\nBAR item \(it.itemIdentifier.rawValue) priority \(it.visibilityPriority.rawValue) "
                        + "x \(Int(f.minX))-\(Int(f.maxX)) view \(it.view != nil) "
                        + (visibili.contains(ObjectIdentifier(it)) ? "visible" : "IN MENU »")
                }
                righe += "\nBAR visible \(barra.visibleItems?.count ?? -1) of \(barra.items.count)"
            } else {
                righe += "\nBAR no toolbar"
            }
            FileHandle.standardError.write((righe + "\n").data(using: .utf8)!)
            tema.display()
            if let rep = tema.bitmapImageRepForCachingDisplay(in: tema.bounds) {
                tema.cacheDisplay(in: tema.bounds, to: rep)
                let file = cartella.appendingPathComponent("\(nome)-barravera-\(aspetto).png")
                if (try? rep.representation(using: .png, properties: [:])?.write(to: file)) == nil { ok = false }
                print(file.path)
            } else {
                ok = false
            }
            finestra.close()
        }
        return ok
    }

    static func disegna(_ vista: some View, nome: String, in cartella: URL, larghezza: CGFloat,
                        altezza: CGFloat) async -> Bool {
        var ok = true
        for aspetto in ["scuro", "chiaro"] {
            let host = NSHostingView(rootView: vista.frame(width: larghezza, height: altezza, alignment: .top)
                .background(Color(nsColor: .windowBackgroundColor)))
            host.frame = NSRect(x: 0, y: 0, width: larghezza, height: altezza)
            host.appearance = NSAppearance(named: aspetto == "scuro" ? .darkAqua : .aqua)
            let finestra = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
            finestra.isReleasedWhenClosed = false
            finestra.appearance = host.appearance
            finestra.contentView = host
            host.layoutSubtreeIfNeeded()
            try? await Task.sleep(nanoseconds: 600_000_000)
            host.layoutSubtreeIfNeeded()
            host.display()
            if let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                host.cacheDisplay(in: host.bounds, to: rep)
                let file = cartella.appendingPathComponent("\(nome)-\(aspetto).png")
                if (try? rep.representation(using: .png, properties: [:])?.write(to: file)) == nil { ok = false }
                print(file.path)
            } else {
                ok = false
            }
            finestra.close()
        }
        return ok
    }
}



@MainActor
enum ProvaAttivita {
    static func fai() async -> Bool {
        setvbuf(stdout, nil, _IONBF, 0)


        guard Bundle.main.bundleIdentifier != "local.sbk.secondbrain" else {
            print("REFUSED: the self-test doesn't run inside the installed app")
            return false
        }
        let dominio = Bundle.main.bundleIdentifier ?? ProcessInfo.processInfo.processName
        let preferenze = UserDefaults.standard.persistentDomain(forName: dominio)
        defer {
            if let preferenze { UserDefaults.standard.setPersistentDomain(preferenze, forName: dominio) }
            else { UserDefaults.standard.removePersistentDomain(forName: dominio) }
        }
        let dir = ProcessInfo.processInfo.environment["SB_ATTIVITA_DIR"] ?? ""
        let vera = NSHomeDirectory() + "/.sbk-data/attivita"

        guard !dir.isEmpty, URL(fileURLWithPath: dir).resolvingSymlinksInPath().standardized.path
                != URL(fileURLWithPath: vera).resolvingSymlinksInPath().standardized.path else {
            print("REFUSED: SB_ATTIVITA_DIR must point to a copy of the data")
            return false
        }

        Store.senzaCache = true
        let cacheVera = Store.impronteCacheCose()
        let store = Store()
        let um = UndoManager()
        um.groupsByEvent = false
        store.coseUndo = um
        store.coseVista = "tutte"
        await store.caricaCose()
        var ok = true
        func controlla(_ nome: String, _ cond: Bool) { print(cond ? "OK  " : "NO  ", nome); if !cond { ok = false } }
        func aspetta(_ cond: () -> Bool) async { for _ in 0..<300 where !cond() { try? await Task.sleep(nanoseconds: 50_000_000) } }
        guard let righe = store.cose?.righe, righe.count >= 3 else { print("NO   niente righe"); return false }
        let a = righe[0], b = righe[1], c = righe[2]
        let pa = a.priorita ?? 2
        let nuova = pa == 0 ? "3" : "0"
        um.beginUndoGrouping()
        let e = await store.gestoTask("priorita", [a.id], [nuova])
        um.endUndoGrouping()
        controlla("priority changed and result row «\(store.coseEsito?.testo ?? "")»", store.coseIndice[a.id]?.priorita == Int(nuova) && e?.ok == true)
        controlla("the row stays held until the selection moves", store.coseTenute.contains(a.id))
        controlla("undo registered with the name «\(um.undoActionName)»", um.canUndo && !um.undoActionName.isEmpty)
        um.undo()
        await aspetta { store.coseIndice[a.id]?.priorita == pa }
        controlla("⌘Z restores P\(pa)", store.coseIndice[a.id]?.priorita == pa)
        controlla("⇧⌘Z available", um.canRedo)
        um.redo()
        await aspetta { store.coseIndice[a.id]?.priorita == Int(nuova) }
        controlla("⇧⌘Z redoes P\(nuova)", store.coseIndice[a.id]?.priorita == Int(nuova))
        um.undo()
        await aspetta { store.coseIndice[a.id]?.priorita == pa }
        controlla("⌘Z again restores P\(pa)", store.coseIndice[a.id]?.priorita == pa)

        let ids = [b.id, c.id]
        let prima = ids.map { store.coseIndice[$0]?.giorno }
        um.beginUndoGrouping()
        await store.gestoTask("data", ids, ["2027-01-15"])
        um.endUndoGrouping()
        controlla("date on two rows", ids.allSatisfy { store.coseIndice[$0]?.giorno == "2027-01-15" })
        um.undo()
        await aspetta { ids.map { store.coseIndice[$0]?.giorno } == prima }
        controlla("one ⌘Z restores both dates", ids.map { store.coseIndice[$0]?.giorno } == prima)

        um.beginUndoGrouping()
        await store.fattaORiapri([b.id])
        um.endUndoGrouping()
        controlla("done: among the closed, stays visible struck through", store.coseIndice[b.id]?.stato == "fatta" && store.righeAVista().contains { $0.id == b.id })
        um.undo()
        await aspetta { store.coseIndice[b.id]?.stato != "fatta" }
        controlla("⌘Z reopens it", store.coseIndice[b.id]?.stato != "fatta")

        um.beginUndoGrouping()
        await store.gestoTask("elimina", [c.id])
        um.endUndoGrouping()
        controlla("deleted, among the deleted", store.coseIndice[c.id]?.eliminata == true)
        um.undo()
        await aspetta { store.coseIndice[c.id]?.eliminata == false }
        controlla("⌘Z restores it", store.coseIndice[c.id]?.eliminata == false)

        store.coseVista = "foglio"
        store.filtraAlVolo("pronto", "veloci", true, una: true)
        store.coseScelte = []
        um.beginUndoGrouping()
        let id = await store.nuovaTask("Test B1 of the new task", campi: ["priorita": "3"])
        um.endUndoGrouping()
        controlla("new task at the top of the Sheet with Quick on the fly «\(store.coseEsito?.testo ?? "")»", id != nil && store.righeAVista().first?.id == id)
        um.undo()
        await aspetta { store.coseIndice[id ?? ""]?.eliminata == true }
        controlla("⌘Z removes the new task (among the deleted)", store.coseIndice[id ?? ""]?.eliminata == true)
        controlla("and it doesn't stay at the top of the view (R6, 6)", !store.coseAppenaAggiunte.contains(id ?? "") && !store.righeAVista().contains { $0.id == id })
        store.coseFiltroAlVolo = [:]

        let t0 = store.coseIndice[a.id]?.titolo ?? ""
        let r = await store.gestoTask("titolo", [a.id], [t0 + " (prova)"], era: "a title that doesn't exist")
        controlla("title not written if it changed in the meantime", r?.ok == false && r?.intanto == t0)

        um.beginUndoGrouping()
        await store.gestoVista(["vista-nascondi", "bacheca"])
        um.endUndoGrouping()
        controlla("view hidden", store.cose?.schede?.first { $0.id == "bacheca" }?.nascosta == true)
        um.undo()
        await aspetta { store.cose?.schede?.first { $0.id == "bacheca" }?.nascosta == false }
        controlla("⌘Z restores it among the views", store.cose?.schede?.first { $0.id == "bacheca" }?.nascosta == false)

        store.coseVista = "tutte"
        store.filtraAlVolo("priorita", "1", true, una: false)
        store.filtraAlVolo("scadenza", "scadute", true, una: true)
        let filtrate = store.righeAVista().count
        controlla("on-the-fly filter P1 overdue: \(filtrate) rows", filtrate > 0 && store.righeAVista().allSatisfy { $0.priorita == 1 && $0.tono_breve == "scaduta" })
        um.beginUndoGrouping()
        await store.salvaFiltri(nuova: true)
        um.endUndoGrouping()
        let nuovaVista = store.schedaCose
        controlla("saved as a new view «\(nuovaVista?.nome ?? "")» with \(nuovaVista?.numero ?? -1) tasks", nuovaVista?.pronta == nil && nuovaVista?.numero == filtrate && store.coseFiltroAlVolo.isEmpty)
        if let v = nuovaVista {
            store.impostaOrdine(v, "titolo", "su")
            try? await Task.sleep(nanoseconds: 600_000_000)
            await store.caricaCose()
            controlla("sort by title saved in the view", store.schedaCose?.ordine?.campo == "titolo")
            um.beginUndoGrouping()
            await store.gestoVista(["vista-imposta", v.id, "gruppo", "\"area\""])
            um.endUndoGrouping()
            controlla("group by area", store.schedaCose?.gruppo == "area" && store.disposizione().count > 1)
            um.beginUndoGrouping()
            await store.gestoVista(["vista-nome", v.id, "My overdue P1s"])
            um.endUndoGrouping()
            controlla("renamed", store.schedaCose?.nome == "My overdue P1s")
            um.undo()
            await aspetta { store.schedaCose?.nome != "My overdue P1s" }
            controlla("⌘Z restores the name «\(store.schedaCose?.nome ?? "")»", store.schedaCose?.nome != "My overdue P1s")
            um.beginUndoGrouping()
            await store.gestoVista(["vista-elimina", v.id])
            um.endUndoGrouping()
            controlla("view deleted (among the deleted)", store.cose?.schede_eliminate?.contains { $0.id == v.id } == true)
            um.undo()
            await aspetta { store.cose?.schede?.contains { $0.id == v.id } == true }
            controlla("⌘Z restores it", store.cose?.schede?.contains { $0.id == v.id } == true)
            try? await Task.sleep(nanoseconds: 500_000_000)
            await store.caricaCose()
            controlla("and in the file it's no longer deleted", store.cose?.schede_eliminate?.contains { $0.id == v.id } != true)
        }

        store.coseVista = "tutte"
        await store.fattaORiapri([c.id])
        um.beginUndoGrouping()
        await store.gestoTask("elimina", [c.id])
        um.endUndoGrouping()
        await store.fattaORiapri([c.id])
        controlla("the circle on a deleted one that was done restores it (R6, 7)", store.coseIndice[c.id]?.eliminata == false)

        um.removeAllActions()
        let pa2 = store.coseIndice[a.id]?.priorita ?? 2
        um.beginUndoGrouping()
        await store.gestoTask("priorita", [a.id], [pa2 == 0 ? "3" : "0"])
        um.endUndoGrouping()
        um.beginUndoGrouping()
        await store.gestoTask("stima", [b.id], ["45"])
        um.endUndoGrouping()
        _ = await store.motore.chiedi(["cose", "stima", b.id, "120"])
        store.coseEsito = nil
        um.undo()
        await aspetta { store.coseEsito?.errore == true }
        controlla("undo refused: «\(store.coseEsito?.testo ?? "")»", store.coseEsito?.errore == true)
        controlla("but the earlier history stays (R6, 3)", um.canUndo)
        um.undo()
        await aspetta { store.coseIndice[a.id]?.priorita == pa2 }
        controlla("and ⌘Z still undoes the earlier action", store.coseIndice[a.id]?.priorita == pa2)

        store.coseVista = "bacheca"
        um.beginUndoGrouping()
        await store.gestoVista(["vista-nascondi", "bacheca"])
        um.endUndoGrouping()
        controlla("the open view hidden, «\(store.schedaCose?.nome ?? "")» opens (R6, 5)",
                  store.coseVista == store.schedeVisibili.first?.id && store.coseVista != "bacheca")
        await store.gestoVista(["vista-mostra", "bacheca"], annullabile: false)

        var inOrdine = 0
        for _ in 0..<5 {

            let uno = Task { @MainActor in await store.gestoTask("priorita", [a.id], ["1"]) }
            let due = Task { @MainActor in await store.gestoTask("priorita", [a.id], ["3"]) }
            _ = await (uno.value, due.value)
            if store.coseIndice[a.id]?.priorita == 3 { inOrdine += 1 }
            _ = await store.gestoTask("priorita", [a.id], ["2"])
        }
        controlla("two actions at once on the same row: the last one wins \(inOrdine) times out of 5 (R6, 4)", inOrdine == 5)

        store.coseVista = "tutte"
        if let s = store.schedaCose {
            func gruppiInFila() -> Bool {
                store.disposizione().allSatisfy { g in g.righe.map(\.id) == Store.ordinate(g.righe, store.coseOrdine).map(\.id) }
            }
            for campo in ["area", "stato"] {
                store.impostaOrdine(s, campo, "giu")
                try? await Task.sleep(nanoseconds: 300_000_000)
                await store.caricaCose()
                let tiene = store.coseOrdine.first.map { $0.campo == campo && $0.order == .reverse } ?? false
                controlla("click on «\(campo)»: the sort stays even after a reload (P1 §3.1, 1)", tiene && gruppiInFila())
            }

            if let pr = store.righeAVista().first {
                store.coseScelte = [pr.id]
                _ = await store.gestoTask("priorita", [pr.id], [pr.priorita == 3 ? "2" : "3"])
                let tenuta = !store.coseTenute.isEmpty
                store.impostaOrdine(s, "titolo", "su")
                controlla("after an action (row held \(tenuta)) the new sort shows immediately (P1 §3.1, 2)",
                          tenuta && store.coseTenute.isEmpty && gruppiInFila())
                _ = await store.gestoTask("priorita", [pr.id], [String(pr.priorita ?? 2)])
            }
            let vuote: [(String, (VoceCosa) -> Bool)] = [("scadenza", { ($0.giorno ?? "").isEmpty }), ("stima", { $0.stima_min == nil })]
            for (campo, vuota) in vuote {
                store.impostaOrdine(s, campo, "giu")

                var vuoteN = 0
                let inFondo = store.disposizione().allSatisfy { g in
                    let i = g.righe.firstIndex(where: vuota) ?? g.righe.count
                    vuoteN += g.righe.count - i
                    return !g.righe[i...].contains { !vuota($0) }
                }
                controlla("«\(campo)» descending: the empty ones at the bottom of each group (P1 §3.1, 3), \(vuoteN) empty", inFondo && vuoteN > 0)
            }
            store.impostaOrdine(s, "pronto", "su")
        }

        if store.cose?.stati != nil, let s = store.schedaCose, let t = store.righeAVista().first {
            um.removeAllActions()

            await store.inFila { () }
            try? await Task.sleep(nanoseconds: 500_000_000)
            await store.caricaCose()
            let ordinePrima = store.cose?.schede?.first { $0.id == s.id }?.livelli ?? []
            store.impostaOrdine(s, [OrdineVista(campo: "priorita", verso: "su"), OrdineVista(campo: "scadenza", verso: "giu")])
            try? await Task.sleep(nanoseconds: 800_000_000)
            await store.caricaCose()
            controlla("two-level sort saved: «\(store.schedaCose?.ordine_parole ?? "")»", store.schedaCose?.livelli.count == 2)
            um.undo()
            await aspetta { store.schedaCose?.livelli == ordinePrima }
            try? await Task.sleep(nanoseconds: 300_000_000)
            await store.caricaCose()
            controlla("⌘Z restores the earlier sort \(ordinePrima.map(\.campo)) (result «\(store.coseEsito?.testo ?? "")»)", store.schedaCose?.livelli == ordinePrima)

            controlla("⌘Z also restores the visible sort \(store.livelliOrdine.map(\.campo))", store.livelliOrdine == ordinePrima)
            await store.gestoTask("stima", [t.id], ["1h30"])
            controlla("time written «1h30» = \(store.coseIndice[t.id]?.stima_min ?? -1) minutes, «\(store.coseIndice[t.id]?.stima_breve ?? "")»", store.coseIndice[t.id]?.stima_min == 90)
            await store.gestoTask("area", [t.id], ["Test area"])
            controlla("«New area…»: «\(store.coseIndice[t.id]?.area ?? "")»", store.coseIndice[t.id]?.area == "Test area")
            await store.gestoTask("commenta", [t.id], ["Test comment"])
            controlla("comment written: commenti_n \(store.coseIndice[t.id]?.commenti_n ?? 0)", (store.coseIndice[t.id]?.commenti_n ?? 0) >= 1)
            um.removeAllActions()
            let nomeStato = "Test status \(Int(Date().timeIntervalSince1970) % 100000)"
            await store.gestoVista(["stato-nuovo", nomeStato, "aspetta"])
            controlla("new status among the settings", store.cose?.stati?.contains { $0.nome == nomeStato } == true)
            um.undo()
            await aspetta { store.cose?.stati?.contains { $0.nome == nomeStato && $0.tolto != true } != true }
            controlla("⌘Z removes it (result «\(store.coseEsito?.testo ?? "")»)", store.cose?.stati?.contains { $0.nome == nomeStato && $0.tolto != true } != true)
            um.redo()
            await aspetta { store.cose?.stati?.contains { $0.nome == nomeStato && $0.tolto != true } == true }
            controlla("⇧⌘Z restores it (redo from the response, D-S08-01)", store.cose?.stati?.contains { $0.nome == nomeStato && $0.tolto != true } == true)

            if let ns = store.cose?.stati?.first(where: { $0.tipo == "non_serve" }) {
                await store.gestoTask("stato", [t.id], [ns.id])
                await store.fattaORiapri([t.id])
                controlla("the circle on «\(ns.nome)» reopens it in the status \(store.coseIndice[t.id]?.stato_nome ?? "")", store.coseIndice[t.id]?.chiusaOra == false)
            }
        }

        do {
            let prima = Motore.chiamate.count
            for v in ["foglio", "bacheca", "tutte", "foglio", "tutte"] {
                store.coseVista = v
                try? await Task.sleep(nanoseconds: 200_000_000)
            }
            let nuove = Array(Motore.chiamate.dropFirst(prima))
            controlla("O · five view switches among Table, Sheet and Board: \(nuove.count) engine calls \(nuove)", nuove.isEmpty)
        }


        StatoSettimana.condiviso.errore = nil
        store.assorbiSettimana(Data(#"{"ok": true}"#.utf8), chiesta: true)
        controlla("D-T4-04 · week requested and not arrived: «\(StatoSettimana.condiviso.errore ?? "")»",
                  StatoSettimana.condiviso.errore == store.settimanaNonArrivata && !(StatoSettimana.condiviso.errore ?? "").isEmpty)
        StatoSettimana.condiviso.errore = nil

        do {
            let f = DateFormatter()
            f.calendar = Calendar(identifier: .gregorian)
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = TimeZone(identifier: "UTC")
            f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            let unOraFa = f.string(from: Date().addingTimeInterval(-3600))
            let dueGiorniFa = f.string(from: Date().addingTimeInterval(-50 * 3600))
            func richiesta(_ c: String) -> RichiestaVoce? {
                try? JSONDecoder().decode(RichiestaVoce.self, from: Data(#"{"id": "r", "creata": "\#(c)", "stato": "fatta", "finita": true}"#.utf8))
            }
            if let r1 = richiesta(unOraFa), let r2 = richiesta(dueGiorniFa) {
                controlla("D-T3-02 · a request finished an hour ago stays visible, one from two days ago doesn't",
                          store.richiestaRecente(r1) && !store.richiestaRecente(r2))
            } else {
                controlla("D-T3-02 · a fake request can be read", false)
            }
        }

        do {
            let cart = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("prova-n-t309-\(UUID().uuidString.prefix(6))")
            try? FileManager.default.createDirectory(at: cart, withIntermediateDirectories: true)
            let a = cart.appendingPathComponent("stesso.m4a")
            FileManager.default.createFile(atPath: a.path, contents: Data([1]))
            Store.segnaDettatoMandato(a)
            FileManager.default.createFile(atPath: a.path, contents: Data([2]))
            Store.segnaDettatoMandato(a)
            let mandati = (try? FileManager.default.contentsOfDirectory(atPath: cart.appendingPathComponent("mandati").path)) ?? []
            controlla("D-T3-09 · two dictations with the same name: both among the sent (\(mandati.count)), none left",
                      mandati.count == 2 && !FileManager.default.fileExists(atPath: a.path))
            try? FileManager.default.removeItem(at: cart)
        }

        store.cosaAperta = "non-esiste-xyz"
        store.coseScelte = []
        store.dettaglioCose = true
        await store.caricaCose()
        controlla("D-T1-04 · detail on a task the page doesn't have: it closes", !store.dettaglioCose)

        if let vecchia = try? JSONDecoder().decode(Cose.self, from: Data(#"{"ok": true, "righe": [], "testi": {}}"#.utf8)) {
            let buona = store.cose
            store.cose = vecchia
            let r = await store.gestoTask("priorita", [a.id], ["0"])
            let n = await store.nuovaTask("Must not be created", campi: [:])
            controlla("§15 · engine without contract: no action, «\(store.coseEsito?.testo ?? "")»", r == nil && n == nil && store.coseEsito?.errore == true)
            store.cose = buona
            await store.caricaCose()
            controlla("§15 · with the current engine (contract \(store.cose?.contratto ?? -1)) actions resume", !store.motoreVecchio)
        } else {
            controlla("§15 · an earlier page can be read", false)
        }

        store.coseFiltroAlVolo = [:]
        await store.caricaCose()
        let aVista = store.schedeVisibili.map(\.id)
        let pronte = aVista.filter { ["tutte", "foglio", "bacheca", "calendario", "urgenti", "veloci", "attese"].contains($0) }
        controlla("M · the ready views shown: Table, Sheet, Board, Calendar, in order; the filtered ones not \(pronte)",
                  pronte == ["tutte", "foglio", "bacheca", "calendario"])
        controlla("M · the Show ▸ Mode menu offers the Sheet \(store.cose?.idModi ?? [])", store.cose?.idModi.contains("foglio") == true)
        let pronti = store.cose?.filtri_pronti ?? []
        controlla("M · three ready filters from the engine \(pronti.map(\.id))", pronti.map(\.id) == ["urgenti", "veloci", "attese"])
        store.coseVista = "foglio"
        await store.caricaCose()
        let tutteF = store.righeAVista().count
        controlla("M · the Sheet has all open ones in a row, no groups (\(tutteF) rows, \(store.disposizione().count) groups)",
                  tutteF == (store.schedaCose?.numero ?? -1) && store.schedaCose?.gruppo == "nessuno")
        if let urg = pronti.first(where: { $0.id == "urgenti" }) {
            store.filtraAlVolo("pronto", "urgenti", true, una: true)
            let nu = store.righeAVista().count
            controlla("M · Urgent on the fly on the Sheet: \(nu) rows, the engine counts \(urg.n ?? -1)", nu == urg.n)
            store.filtraAlVolo("pronto", "veloci", true, una: true)
            controlla("M · one ready filter at a time: Quick takes the place of Urgent", store.coseFiltroAlVolo["pronto"] == ["veloci"])
            store.filtraAlVolo("pronto", "urgenti", true, una: true)
            store.filtraAlVolo("stima", "fino_30", true, una: true)
            let attese = (store.cose?.righe ?? []).filter { r in
                let k = Set(r.filtro_chiavi ?? [])
                return k.contains("pronto:urgenti") && k.contains("stima:fino_30") && r.aperta != false && r.eliminata != true
            }.count
            let incrocio = store.righeAVista().count
            controlla("M · Urgent and «Up to half an hour» together: \(incrocio) rows, expected \(attese)", incrocio == attese)
            store.coseFiltroAlVolo = [:]

            store.filtraAlVolo("pronto", "urgenti", true, una: true)
            let idN = await store.nuovaTask("Test M urgent", campi: [:])
            controlla("M · new task with Urgent on the fly: P\(store.coseIndice[idN ?? ""]?.priorita ?? -1)", store.coseIndice[idN ?? ""]?.priorita == 1)
            if let idN { await store.gestoTask("elimina", [idN]) }

            await store.salvaFiltri(nuova: true)
            let nuovaId = store.coseVista
            controlla("M · «Save as new view» with Urgent: view filter «\(store.schedaCose?.filtro?.pronto ?? "nessuno")», mode \(store.schedaCose?.modo ?? "")",
                      store.schedaCose?.filtro?.pronto == "urgenti" && store.schedaCose?.modo == "foglio" && store.coseFiltroAlVolo.isEmpty)
            controlla("M · and shows the urgent ones (\(store.righeAVista().count))", store.righeAVista().count == urg.n)
            if nuovaId != "foglio" { await store.gestoVista(["vista-elimina", nuovaId], annullabile: false) }
        }

        store.sezione = .cose
        store.coseVista = "tutte"
        store.coseFiltroAlVolo = [:]
        if let a = try? JSONDecoder().decode(AperturaVoce.self, from: Data(#"{"filtro": {"pronto": "urgenti"}}"#.utf8)) {
            store.applicaApri(a)
            controlla("M · the voice applies Urgent on the fly to the open view \(store.coseFiltroAlVolo)", store.coseVista == "tutte" && store.coseFiltroAlVolo["pronto"] == ["urgenti"])
        }
        store.coseFiltroAlVolo = [:]

        if let e = await store.gestoVista(["vista-nuova", "foglio"], annullabile: false), let nid = e.id {
            controlla("M · «+» ▸ Sheet makes a view in sheet mode (\(store.cose?.schede?.first { $0.id == nid }?.modo ?? ""))",
                      store.cose?.schede?.first { $0.id == nid }?.modo == "foglio")
            await store.gestoVista(["vista-elimina", nid], annullabile: false)
        }

        controlla("the real app's task cache hasn't changed (D-P5-01)", Store.impronteCacheCose() == cacheVera)
        print(ok ? "ALL GREEN" : "SOMETHING'S OFF")
        return ok
    }
}

extension Store {

    static func impronteCacheCose() -> String {
        let f = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("local.sbk.secondbrain/ultime-cose.json")
        guard let dati = try? Data(contentsOf: f) else { return "nessuna" }
        let data = (try? FileManager.default.attributesOfItem(atPath: f.path))?[.modificationDate] as? Date
        return "\(dati.count)·\(dati.hashValue)·\(data?.timeIntervalSince1970 ?? 0)"
    }
}

extension ProvaAttivita {


    static func voce() async -> Bool {
        setvbuf(stdout, nil, _IONBF, 0)


        guard Bundle.main.bundleIdentifier != "local.sbk.secondbrain" else {
            print("REFUSED: the self-test doesn't run inside the installed app")
            return false
        }
        let dominio = Bundle.main.bundleIdentifier ?? ProcessInfo.processInfo.processName
        let preferenze = UserDefaults.standard.persistentDomain(forName: dominio)
        defer {
            if let preferenze { UserDefaults.standard.setPersistentDomain(preferenze, forName: dominio) }
            else { UserDefaults.standard.removePersistentDomain(forName: dominio) }
        }
        let env = ProcessInfo.processInfo.environment
        let dir = env["SB_ATTIVITA_DIR"] ?? ""
        guard dir.contains("prova"), env["SBK_APP_CLAUDE"] == "0",
              env["SB_ATTIVITA_TRASCRIVI"]?.contains("non-esiste") == true else {
            print("REFUSED: needs a copy of the data, SBK_APP_CLAUDE=0 and a fake recipe")
            return false
        }

        Store.senzaCache = true
        let store = Store()
        var ok = true
        func controlla(_ nome: String, _ cond: Bool) { print(cond ? "OK  " : "NO  ", nome); if !cond { ok = false } }
        await store.caricaCose()

        let preso = await store.mandaTestoVoce("move the test to Monday")
        controlla("voce-testo taken: «\(store.coseEsito?.testo ?? "")»", preso)

        let chiaveDoppia = UUID().uuidString.lowercased()
        let uno = try? JSONDecoder().decode(EsitoVoce.self, from: await store.motore.chiedi(["cose", "voce-testo", "double-send test", "--una-volta", chiaveDoppia], scadenza: 20).dati)
        let due = try? JSONDecoder().decode(EsitoVoce.self, from: await store.motore.chiedi(["cose", "voce-testo", "double-send test", "--una-volta", chiaveDoppia], scadenza: 20).dati)
        controlla("§16 · two Enters with the same key make one request (\(uno?.id ?? "-") and \(due?.id ?? "-"), «\(due?.messaggio ?? "")»)",
                  uno?.ok == true && due?.ok == true && uno?.id != nil && uno?.id == due?.id)
        let k1 = store.chiaveVoce("a message"), k2 = store.chiaveVoce("a message"), k3 = store.chiaveVoce("another")
        controlla("§16 · the same un-taken message keeps its key, another has its own", k1 == k2 && k1 != k3)
        for _ in 0..<200 where store.voceAttivita?.richieste?.first?.finita != true {
            try? await Task.sleep(nanoseconds: 100_000_000)
            await store.caricaVoce()
        }
        let r1 = store.voceAttivita?.richieste?.first
        controlla("the written request stops without your consent to Claude Code sessions: «\(r1?.stato_nome ?? "") · \(r1?.motivo ?? "")»", r1?.stato == "non_riuscita")
        controlla("has the Retry button from the engine: \(r1?.riprova ?? [])", r1?.riprova?.first == "voce-riprova")
        controlla("shows among the page's requests", store.richiesteAVista.contains { $0.id == r1?.id })

        let audio = URL(fileURLWithPath: store.cartellaDettati).appendingPathComponent("audio/prova-b1.m4a")
        try? FileManager.default.createDirectory(at: audio.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? Data(repeating: 0, count: 2048).write(to: audio)
        let reg = Registrazione(file: audio, voce: Registrazione.attivita, chiave: Registrazione.attivita, cosa: "", esito: "",
                                cartella: store.cartellaDettati, cartellaRegistro: store.cartellaDettati, secondi: 4)
        let ad = reg.argomentiAttivita
        controlla("dictation args: \(ad.prefix(1)) … --durata 4 … --una-volta audio-…", ad.first == "voce" && ad.contains("--durata")
                  && ad[(ad.firstIndex(of: "--durata") ?? 0) + 1] == "4" && ad.suffix(2).first == "--una-volta" && ad.last == "audio-" + audio.lastPathComponent)
        let errore = await store.mandaRegistrazione(reg)
        controlla("mandaRegistrazione delivered it to the voice engine (no error)", errore == nil)
        for _ in 0..<200 where store.voceAttivita?.richieste?.first?.via != "voce" || store.voceAttivita?.richieste?.first?.finita != true {
            try? await Task.sleep(nanoseconds: 100_000_000)
            await store.caricaVoce()
        }
        let r2 = store.voceAttivita?.richieste?.first
        controlla("the dictation is a voice request: «\(r2?.stato_nome ?? "") · \(r2?.motivo ?? "")»", r2?.via == "voce" && r2?.finita == true)
        controlla("the engine has its own copy of the audio", (r2?.audio ?? "").hasSuffix(".m4a") && FileManager.default.fileExists(atPath: r2?.audio ?? ""))
        let mandato = audio.deletingLastPathComponent().appendingPathComponent("mandati").appendingPathComponent(audio.lastPathComponent)
        controlla("the app's audio, taken by the engine, is among the sent (R6, F2)", FileManager.default.fileExists(atPath: mandato.path) && !FileManager.default.fileExists(atPath: audio.path))

        let rimasto = audio.deletingLastPathComponent().appendingPathComponent("rimasto-b1.m4a")
        try? Data(repeating: 0, count: 2048).write(to: rimasto)
        try? FileManager.default.setAttributes([.modificationDate: Date().addingTimeInterval(-60)], ofItemAtPath: rimasto.path)
        store.cercaDettatiNonMandati()
        controlla("the leftover dictation shows among the cards", store.voceNonMandati.contains(rimasto))
        await store.mandaDettatoRimasto(rimasto)
        controlla("«Send it»: taken by the engine and moved among the sent", store.voceNonMandati.isEmpty && !FileManager.default.fileExists(atPath: rimasto.path))

        if let rp = r1?.riprova { await store.azioneVoce(rp) }
        controlla("Retry accepted: «\(store.coseEsito?.testo ?? "")»", store.coseEsito?.errore == false)

        if let id = r1?.id { store.voceChiuse.insert(id) }
        controlla("closed, no longer visible", !store.richiesteAVista.contains { $0.id == r1?.id })
        if let id = r1?.id { store.voceChiuse.remove(id) }
        print(ok ? "ALL GREEN" : "SOMETHING'S OFF")
        return ok
    }
}
