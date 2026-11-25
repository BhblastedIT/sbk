import AppKit
import SwiftUI





@MainActor
enum ProvaTasti {
    static func fai() async -> Bool {
        setvbuf(stdout, nil, _IONBF, 0)
        guard Bundle.main.bundleIdentifier != "local.sbk.secondbrain" else {
            print("REFUSE: the test does not run inside the installed app")
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
            print("REFUSE: SB_ATTIVITA_DIR must point to a copy of the data")
            return false
        }

        let calendari = ProcessInfo.processInfo.environment["SB_CALENDARI_DIR"] ?? ""
        let casaVera = getpwuid(getuid()).map { String(cString: $0.pointee.pw_dir) } ?? NSHomeDirectory()
        guard !calendari.isEmpty, !Set([casaVera, NSHomeDirectory()].map { URL(fileURLWithPath: $0 + "/.sbk-data/calendars").resolvingSymlinksInPath().standardized.path })
                .contains(URL(fileURLWithPath: calendari).resolvingSymlinksInPath().standardized.path) else {
            print("REFUSE: SB_CALENDARI_DIR must point to the fake calendars")
            return false
        }
        Store.senzaCache = true
        let cacheVera = Store.impronteCacheCose()
        var ok = true
        func controlla(_ nome: String, _ cond: Bool) { print(cond ? "OK  " : "NO  ", nome); if !cond { ok = false } }
        func vedi(_ nome: String) { print("--  ", nome) }
        func aspetta(_ cond: () -> Bool) async { for _ in 0..<120 where !cond() { try? await Task.sleep(nanoseconds: 50_000_000) } }


        func giro() async {
            if let e = NSEvent.otherEvent(with: .applicationDefined, location: .zero, modifierFlags: [], timestamp: 0,
                                          windowNumber: 0, context: nil, subtype: 0, data1: 0, data2: 0) {
                NSApp.postEvent(e, atStart: false)
            }
            try? await Task.sleep(nanoseconds: 250_000_000)
            traccia("round: undo grouping level \(store.coseUndo?.groupingLevel ?? -1)")
        }

        let store = Store()

        if let f = ProcessInfo.processInfo.environment["SB_PROVA_STATO"], let dati = FileManager.default.contents(atPath: f),
           let stato = try? JSONDecoder().decode(Stato.self, from: dati) { store.stato = stato }
        store.sezione = .cose
        store.ispettore = false
        store.coseVista = "tutte"
        store.coseColonne = TableColumnCustomization<VoceCosa>()
        await store.caricaCose()
        guard let righe = store.cose?.righe, righe.count > 5 else { print("NO   no rows"); return false }

        let host = NSHostingView(rootView: Principale().environment(store).frame(width: 1174, height: 910))
        host.frame = NSRect(x: 0, y: 0, width: 1174, height: 910)
        let fin = NSWindow(contentRect: host.frame, styleMask: [.titled, .resizable], backing: .buffered, defer: false)
        fin.isReleasedWhenClosed = false
        fin.contentView = host
        Store.finestraProva = fin
        host.layoutSubtreeIfNeeded()
        try? await Task.sleep(nanoseconds: 1_500_000_000)
        host.layoutSubtreeIfNeeded()

        for _ in 0..<20 where tabella(host) == nil {
            try? await Task.sleep(nanoseconds: 300_000_000)
            host.layoutSubtreeIfNeeded()
        }
        guard let tv = tabella(host) else {
            print("NO   the table is missing · section \(store.sezione) · tables \(trovaTutti(host, NSTableView.self).map(\.tableColumns.count)) · cose \(store.cose != nil)")
            return false
        }
        let um = fin.undoManager
        vedi("window undo \(um.map { "\(ObjectIdentifier($0))" } ?? "nil"), page undo \(store.coseUndo.map { "\(ObjectIdentifier($0))" } ?? "nil"), groupsByEvent \(um?.groupsByEvent ?? false)")

        if store.coseUndo == nil { store.coseUndo = um }
        controlla("the page has an undo manager", store.coseUndo != nil)


        if let campo = trovaTutti(host, NSTextField.self).first(where: { $0.isEditable }) {
            fin.makeFirstResponder(campo)
            var fatto = false
            store.daTasto { fatto = true }
            controlla("cursor in a field (\(type(of: fin.firstResponder!))): ⌘K, ⌘⌫ and the others don't act on the tasks (B2)", !fatto)
        } else {
            controlla("a text field in the page", false)
        }
        fin.makeFirstResponder(tv)
        var fattoTabella = false
        store.daTasto { fattoTabella = true }
        controlla("with the table in front the Task menu keys act", fattoTabella)
        await bL(store: store, fin: fin, tv: tv, controlla: controlla, vedi: vedi, giro: giro)

        AperturaImpostazioni.provaImpostazioni = true
        let aperturePrima = AperturaImpostazioni.aperture
        store.apriImpostazioni("aree")
        await aspetta { AperturaImpostazioni.aperture > aperturePrima }
        await giro()
        controlla("«Edit the areas…» reaches openSettings once, on the Areas section (R9 B3, \(AperturaImpostazioni.aperture - aperturePrima) requests)",
                  AperturaImpostazioni.aperture == aperturePrima + 1 && Store.sezioneImpostazioni == "aree")
        Store.sezioneImpostazioni = "stati"


        let prima = store.righeAVista()
        guard let a = prima.first(where: { $0.priorita == 1 }) ?? prima.first else { return false }
        let pa = a.priorita ?? 2
        let nuova = pa == 3 ? 2 : 3
        store.coseScelte = [a.id]
        await giro()
        tasto(fin, "\(nuova)", nuova == 3 ? 20 : 19)
        await aspetta { store.coseIndice[a.id]?.priorita == nuova }
        controlla("the \(nuova) key on the chosen row moves it to P\(nuova)", store.coseIndice[a.id]?.priorita == nuova)
        tasto(fin, "\r", 36)
        await aspetta { store.dettaglioCose }
        controlla("↩ opens the detail", store.dettaglioCose)
        tasto(fin, "\u{1b}", 53)
        await aspetta { !store.dettaglioCose }
        controlla("Esc closes it", !store.dettaglioCose)
        fin.makeFirstResponder(tv)
        tasto(fin, String(UnicodeScalar(0xF701)!), 125, [.option, .numericPad, .function])
        await giro()
        controlla("⌥↓ selects the last row", store.coseScelte == Set([store.righeAVista().last?.id ?? "?"]))


        store.coseScelte = [a.id]
        fin.makeFirstResponder(tv)
        await giro()
        let p1 = store.coseIndice[a.id]?.priorita ?? 2
        tasto(fin, p1 == 0 ? "1" : "0", p1 == 0 ? 18 : 29)
        await aspetta { store.coseIndice[a.id]?.priorita != p1 }
        let p2 = store.coseIndice[a.id]?.priorita ?? 2
        await giro()
        tasto(fin, p2 == 2 ? "1" : "2", p2 == 2 ? 18 : 19)
        await aspetta { store.coseIndice[a.id]?.priorita != p2 }
        let p3 = store.coseIndice[a.id]?.priorita ?? 2
        controlla("two keyboard gestures in two rounds: P\(p1) → P\(p2) → P\(p3)", p1 != p2 && p2 != p3)
        await giro()
        vedi("after two gestures: undo possible \(um?.canUndo == true), name «\(um?.undoActionName ?? "")»")
        traccia("TEST first undo")
        um?.undo()
        await aspetta { store.coseIndice[a.id]?.priorita == p2 }
        controlla("first ⌘Z: back to P\(p2) (the second gesture)", store.coseIndice[a.id]?.priorita == p2)
        await giro()
        traccia("TEST second undo, P\(store.coseIndice[a.id]?.priorita ?? -1)")
        um?.undo()
        await aspetta { store.coseIndice[a.id]?.priorita == p1 }
        controlla("second ⌘Z: back to P\(p1) (the first gesture)", store.coseIndice[a.id]?.priorita == p1)
        await giro()
        vedi("before ⇧⌘Z: redo possible \(um?.canRedo == true) «\(um?.redoActionName ?? "")», undo possible \(um?.canUndo == true)")
        um?.redo()
        await aspetta { store.coseIndice[a.id]?.priorita == p2 }
        controlla("⇧⌘Z redoes the first (P\(store.coseIndice[a.id]?.priorita ?? -1), outcome «\(store.coseEsito?.testo ?? "")»)", store.coseIndice[a.id]?.priorita == p2)


        let b = prima.first(where: { $0.id != a.id }) ?? prima[1]
        store.coseScelte = [b.id]
        store.cosaAperta = b.id
        store.dettaglioCose = true
        try? await Task.sleep(nanoseconds: 900_000_000)
        host.layoutSubtreeIfNeeded()
        let segno = "Prova dei tasti \(Int(Date().timeIntervalSince1970) % 100000)"
        if let editor = trovaTutti(host, NSTextView.self).first(where: { $0.isEditable && $0.enclosingScrollView != nil && $0.bounds.height > 100 }) {
            fin.makeFirstResponder(editor)
            editor.moveToEndOfDocument(nil)
            editor.insertText(" " + segno, replacementRange: editor.selectedRange())
            await giro()
            vedi("the typed text is in the description field: \(editor.string.contains(segno))")
            vedi("in the description: undo possible \(um?.canUndo == true), name «\(um?.undoActionName ?? "")»")
            let c = prima.first(where: { $0.id != a.id && $0.id != b.id }) ?? prima[2]
            store.coseScelte = [c.id]
            store.cosaAperta = c.id
            try? await Task.sleep(nanoseconds: 900_000_000)
            await store.caricaCose()
            await aspetta { store.coseIndice[b.id]?.dettaglio.contains(segno) == true }
            controlla("changing row the typed description saves (onDisappear), outcome «\(store.coseEsito?.testo ?? "")»", store.coseIndice[b.id]?.dettaglio.contains(segno) == true)
            vedi("after saving: undo «\(um?.undoActionName ?? "")»")
            um?.undo()
            await aspetta { store.coseIndice[b.id]?.dettaglio.contains(segno) == false }
            vedi("⌘Z after saving: the description \(store.coseIndice[b.id]?.dettaglio.contains(segno) == true ? "still has" : "no longer has") the typed text")
        } else {
            controlla("the description field in the detail", false)
        }
        store.dettaglioCose = false
        await giro()


        let e2 = prima.first(where: { $0.id != a.id && $0.id != b.id && $0.dettaglio.count > 20 }) ?? prima[4]
        store.coseScelte = [e2.id]
        store.cosaAperta = e2.id
        store.dettaglioCose = true
        try? await Task.sleep(nanoseconds: 900_000_000)
        host.layoutSubtreeIfNeeded()
        let mio = "Scritto mio \(Int(Date().timeIntervalSince1970) % 100000) perché è così"
        if let editor = trovaTutti(host, NSTextView.self).first(where: { $0.isEditable && $0.enclosingScrollView != nil && $0.bounds.height > 100 }) {
            fin.makeFirstResponder(editor)
            editor.moveToEndOfDocument(nil)
            editor.insertText(" " + mio, replacementRange: editor.selectedRange())
            await giro()

            _ = await store.motore.chiedi(["cose", "descrizione", e2.id, "Cambiata da un'altra parte"], scadenza: 30)
            store.coseScelte = [a.id]
            store.cosaAperta = a.id
            try? await Task.sleep(nanoseconds: 900_000_000)
            await aspetta { store.coseConflitto != nil }
            controlla("description changed meanwhile: the typed text stays (\(store.coseConflitto?.mio.contains(mio) == true ? "with my text" : "without"))",
                      store.coseConflitto?.id == e2.id && store.coseConflitto?.mio.contains(mio) == true)
            if let c = store.coseConflitto { await store.tieniLaMia(c) }
            await aspetta { store.coseIndice[e2.id]?.dettaglio.contains(mio) == true }
            controlla("«Keep mine» writes it, accents included", store.coseIndice[e2.id]?.dettaglio.contains(mio) == true)
        } else {
            controlla("the description field in the detail (conflict)", false)
        }
        store.dettaglioCose = false
        await giro()

        let righeFile = (try? String(contentsOfFile: dir + "/eventi.jsonl", encoding: .utf8)) ?? ""
        let ultima = righeFile.split(separator: "\n").last { $0.contains(mio.prefix(18)) }.map(String.init) ?? ""
        controlla("in the file the typed text with accents is composed (NFC)", !ultima.isEmpty && ultima == ultima.precomposedStringWithCanonicalMapping
                  && !ultima.unicodeScalars.contains { $0.properties.canonicalCombiningClass != .notReordered })


        let d = prima.first(where: { $0.id != a.id && $0.id != b.id && $0.pianificata == nil }) ?? prima[3]
        um?.removeAllActions()
        await store.pianifica(ids: [d.id], quando: "2026-11-20T10:00", durata: nil)
        await aspetta { store.coseIndice[d.id]?.pianificata != nil }
        controlla("drop on an hour of the week: scheduled «\(store.coseIndice[d.id]?.inizio_breve ?? "")»", store.coseIndice[d.id]?.pianificata != nil)
        um?.undo()
        await aspetta { store.coseIndice[d.id]?.pianificata == nil }
        controlla("⌘Z removes it from the calendar", store.coseIndice[d.id]?.pianificata == nil)
        let giornoPrima = store.coseIndice[d.id]?.giorno

        _ = store.rilasciaSulGiorno([d.id], giorno: "2026-11-21", passato: false)
        await aspetta { store.coseIndice[d.id]?.giorno == "2026-11-21" }
        controlla("drop on a day of the month: due on the 21st", store.coseIndice[d.id]?.giorno == "2026-11-21")
        um?.undo()
        await aspetta { store.coseIndice[d.id]?.giorno == giornoPrima }
        controlla("⌘Z restores the previous due date", store.coseIndice[d.id]?.giorno == giornoPrima)


        if let s = store.schedaCose {
            store.impostaOrdine(s, [OrdineVista(campo: "priorita", verso: "su")])
            try? await Task.sleep(nanoseconds: 300_000_000)
            await store.inFila { () }
            await giro()
            host.layoutSubtreeIfNeeded()
            let t2 = tabella(host) ?? tv
            if let hv = t2.headerView, let i = t2.tableColumns.firstIndex(where: { MisureColonne.base($0.headerCell.stringValue) == (store.cose?.col("scadenza") ?? "?") }) {
                let r = hv.headerRect(ofColumn: i)
                let p = hv.convert(NSPoint(x: r.midX, y: r.midY), to: nil)
                if let e = NSEvent.mouseEvent(with: .leftMouseDown, location: p, modifierFlags: [.shift], timestamp: ProcessInfo.processInfo.systemUptime,
                                              windowNumber: fin.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1) {
                    NSApp.sendEvent(e)
                }
                await aspetta { store.coseOrdine.count == 2 }
                await store.inFila { () }
                await giro()
                controlla("⇧click on Due: order «\(store.paroleOrdine)»", store.coseOrdine.map(\.campo) == ["priorita", "scadenza"])
                try? await Task.sleep(nanoseconds: 800_000_000)
                vedi("before the order ⌘Z: «\(um?.undoActionName ?? "")», saved \(store.schedaCose?.livelli.map(\.campo) ?? [])")
                um?.undo()

                await aspetta { store.coseOrdine.count == 1 }
                controlla("⌘Z restores the previous order (one level): \(store.coseOrdine.map(\.campo)), outcome «\(store.coseEsito?.testo ?? "")»", store.coseOrdine.map(\.campo) == ["priorita"])
                store.impostaOrdine(s, [])
            } else {
                controlla("the Due header in the header row", false)
            }
        }

        await kR9(store: store, fin: fin, host: host, um: um, prima: prima, usate: [a.id, b.id, e2.id, d.id], dir: dir,
                  controlla: controlla, vedi: vedi, aspetta: aspetta, giro: giro)
        try? await Task.sleep(nanoseconds: 500_000_000)
        controlla("the real app's task cache did not change (D-P5-01)", Store.impronteCacheCose() == cacheVera)
        fin.close()
        print(ok ? "ALL GREEN" : "SOMETHING'S WRONG")
        return ok
    }

    static func tabella(_ v: NSView) -> NSTableView? { trovaTutti(v, NSTableView.self).first { $0.tableColumns.count > 2 } }

    static func trova<T: NSView>(_ v: NSView, _ t: T.Type) -> T? { (v as? T) ?? v.subviews.lazy.compactMap { trova($0, t) }.first }
    static func trovaTutti<T: NSView>(_ v: NSView, _ t: T.Type) -> [T] { ((v as? T).map { [$0] } ?? []) + v.subviews.flatMap { trovaTutti($0, t) } }

    static func tasto(_ fin: NSWindow, _ c: String, _ codice: UInt16, _ mod: NSEvent.ModifierFlags = []) {
        for tipo in [NSEvent.EventType.keyDown, .keyUp] {
            if let e = NSEvent.keyEvent(with: tipo, location: .zero, modifierFlags: mod, timestamp: ProcessInfo.processInfo.systemUptime,
                                        windowNumber: fin.windowNumber, context: nil, characters: c, charactersIgnoringModifiers: c,
                                        isARepeat: false, keyCode: codice) { fin.sendEvent(e) }
        }
    }
}




extension ProvaTasti {
    static func campoCon(_ v: NSView, _ segnaposto: String) -> NSTextField? {
        trovaTutti(v, NSTextField.self).first {
            $0.isEditable && ($0.placeholderString == segnaposto || $0.placeholderAttributedString?.string == segnaposto)
        }
    }


    static func scrivi(_ fin: NSWindow, _ c: NSTextField, _ t: String, tutto: Bool) async {
        fin.makeFirstResponder(c)
        try? await Task.sleep(nanoseconds: 300_000_000)
        if let ed = fin.firstResponder as? NSTextView {
            if tutto { ed.selectAll(nil) } else { ed.moveToEndOfDocument(nil) }
            ed.insertText(t, replacementRange: ed.selectedRange())
        }
    }

    static func kR9(store: Store, fin: NSWindow, host: NSView, um: UndoManager?, prima: [VoceCosa], usate: [String], dir: String,
                    controlla: (String, Bool) -> Void, vedi: (String) -> Void,
                    aspetta: (() -> Bool) async -> Void, giro: () async -> Void) async {
        guard let cose = store.cose else { controlla("K: the page", false); return }
        let liberi = prima.filter { !usate.contains($0.id) && $0.eliminata != true }
        guard liberi.count >= 6 else { controlla("K: six free rows for the tests (\(liberi.count))", false); return }
        func apri(_ id: String) async {
            store.coseScelte = [id]
            store.cosaAperta = id
            store.dettaglioCose = true
            try? await Task.sleep(nanoseconds: 900_000_000)
            host.layoutSubtreeIfNeeded()
            await giro()
            host.layoutSubtreeIfNeeded()
        }
        func segnaposti() -> String { trovaTutti(host, NSTextField.self).filter(\.isEditable).map { $0.placeholderString ?? "-" }.joined(separator: " | ") }


        let nascoste = (cose.aree_def ?? []).filter { a in
            a.tolta != true && a.unita_in == nil && a.senza != true && !cose.areeDiOwner.contains { $0.id == a.id }
        }
        controlla("areas not shown for the engine outside menu and sheet (\(nascoste.map { "\($0.nome) \($0.n ?? -1)" })), all others shown (\(cose.areeDiOwner.count) of \(cose.aree.count))",
                  nascoste.allSatisfy { ($0.n ?? 0) == 0 } && Set(cose.areeDiOwner.map(\.nome)).isSubset(of: Set(cose.aree)))


        let r1 = liberi[0], r2 = liberi[1]
        await apri(r1.id)
        await aspetta { campoCon(host, cose.t("commenta_segnaposto")) != nil }
        let bozza = "Commento a metà \(Int(Date().timeIntervalSince1970) % 100000) però"
        if let c = campoCon(host, cose.t("commenta_segnaposto")) {
            await scrivi(fin, c, bozza, tutto: false)
            await giro()
            let nelloStore = store.coseBozzeCommento[r1.id] == bozza
            await apri(r2.id)
            let altraVuota = (campoCon(host, cose.t("commenta_segnaposto"))?.stringValue ?? "?").isEmpty
            await apri(r1.id)
            await aspetta { campoCon(host, cose.t("commenta_segnaposto"))?.stringValue == bozza }
            let tornato = campoCon(host, cose.t("commenta_segnaposto"))?.stringValue == bozza
            controlla("T1 · the typed comment stays when changing row and coming back (in the Store \(nelloStore), the other row empty \(altraVuota))",
                      nelloStore && altraVuota && tornato)

            if let c2 = campoCon(host, cose.t("commenta_segnaposto")) {
                fin.makeFirstResponder(c2)
                await giro()
                tasto(fin, "\u{1b}", 53)
                await giro()
                controlla("T5 · Esc in the comment field doesn't delete the typed text", store.coseBozzeCommento[r1.id] == bozza)
            } else {
                controlla("T5 · the comment field after coming back", false)
            }
            store.coseBozzeCommento[r1.id] = nil
        } else {
            controlla("T1 · the comment field in the detail (fields: \(segnaposti()))", false)
        }
        store.dettaglioCose = false
        await giro()


        let r3 = liberi[2]
        let minuti = r3.stima_min == 45 ? 50 : 45
        await apri(r3.id)
        if let c = campoCon(host, cose.t("stima_segnaposto")) {
            await scrivi(fin, c, "\(minuti) min", tutto: true)
            await giro()
            store.dettaglioCose = false
            await giro()
            await aspetta { store.coseIndice[r3.id]?.stima_min == minuti }
            controlla("T2 · time typed and detail closed without Enter: it saves (\(store.coseIndice[r3.id]?.stima_min.map(String.init) ?? "none"))",
                      store.coseIndice[r3.id]?.stima_min == minuti)
        } else {
            controlla("T2 · the time field in the detail (fields: \(segnaposti()))", false)
        }
        store.dettaglioCose = false
        await giro()


        let r4 = liberi[3]
        await apri(r4.id)
        let chiusura = "Scritto prima di chiudere \(Int(Date().timeIntervalSince1970) % 100000)"
        if let editor = trovaTutti(host, NSTextView.self).first(where: { $0.isEditable && $0.enclosingScrollView != nil && $0.bounds.height > 100 }) {
            fin.makeFirstResponder(editor)
            editor.moveToEndOfDocument(nil)
            editor.insertText(" " + chiusura, replacementRange: editor.selectedRange())
            await giro()
            let tenuto = store.coseScrittiInCorso["\(r4.id)|descrizione"]?.testo.contains(chiusura) == true
            store.salvaScrittiAllaChiusura()
            await store.caricaCose()
            let scritto = store.coseIndice[r4.id]?.dettaglio.contains(chiusura) == true
            store.dettaglioCose = false
            await giro()
            try? await Task.sleep(nanoseconds: 600_000_000)
            let senzaDoppio = !store.coseConflitti.contains { $0.id == r4.id }
            controlla("T3 · on app close the description being written saves (kept in the Store \(tenuto), no conflict after \(senzaDoppio))",
                      tenuto && scritto && senzaDoppio)
        } else {
            controlla("T3 · the description field in the detail", false)
        }
        store.dettaglioCose = false
        await giro()


        let sc = StatoConversazione.condiviso
        let finta = "prova-k-t4"
        let risposta = "La mia risposta, non deve sparire"
        sc.risposte[finta] = risposta
        let presa = await sc.mandaRisposta(store, id: finta, argomenti: ["voce-conferma", "2026-01-01-000000-0000", "<la tua risposta>"])
        controlla("T4 · with an engine error the typed answer stays (outcome «\(store.coseEsito?.testo ?? "")»)",
                  !presa && sc.risposte[finta] == risposta)
        sc.risposte[finta] = nil


        let r5 = liberi[4], r6 = liberi[5]
        for r in [r5, r6] {
            _ = await store.motore.chiedi(["cose", "descrizione", r.id, "Cambiata altrove \(r.id.suffix(4))"], scadenza: 30)
        }
        await store.salvaScritto(id: r5.id, campo: "descrizione", testo: "Il mio primo scritto", era: r5.dettaglio)
        await store.salvaScritto(id: r6.id, campo: "descrizione", testo: "Il mio secondo scritto", era: r6.dettaglio)
        let entrambi = Set(store.coseConflitti.map(\.id)).isSuperset(of: [r5.id, r6.id])
        if let c6 = store.coseConflitti.first(where: { $0.id == r6.id }) { await store.tieniLaMia(c6) }
        await aspetta { store.coseIndice[r6.id]?.dettaglio == "Il mio secondo scritto" }
        let restaIlPrimo = store.coseConflitti.contains { $0.id == r5.id }
        controlla("T7 · two conflicting writes both stay; «Keep mine» on one doesn't lose the other",
                  entrambi && restaIlPrimo && store.coseIndice[r6.id]?.dettaglio == "Il mio secondo scritto")
        if let c5 = store.coseConflitti.first(where: { $0.id == r5.id }) { await store.tieniLaMia(c5) }


        let cart = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("prova-k-t8-\(UUID().uuidString.prefix(6))")
        try? FileManager.default.createDirectory(at: cart, withIntermediateDirectories: true)
        let audio = cart.appendingPathComponent("dettato.m4a")
        FileManager.default.createFile(atPath: audio.path, contents: Data())
        func biglietto(_ chiave: String) {
            let d = try? JSONSerialization.data(withJSONObject: ["voce": Registrazione.attivita, "chiave": chiave, "inizio": "2026-11-15T10:00:00"])
            try? d?.write(to: Registratore.biglietto(audio))
        }
        biglietto("commento-\(r1.id)")
        let conCommento = Store.argomentiDettato(audio)
        biglietto("barra")
        let senza = Store.argomentiDettato(audio)
        controlla("T8 · a leftover comment dictation is re-sent as a comment (\(conCommento.dropFirst(3).joined(separator: " ")))",
                  conCommento.firstIndex(of: "--commento").map { conCommento[$0 + 1] == r1.id } == true && !senza.contains("--commento")
                  && conCommento.contains("--una-volta"))
        try? FileManager.default.removeItem(at: cart)


        if let s = store.schedaCose {
            store.impostaOrdine(s, [OrdineVista(campo: "priorita", verso: "su")])
            await store.inFila { () }
            await giro()
            host.layoutSubtreeIfNeeded()
            if let t2 = tabella(host), let hv = t2.headerView,
               let i = t2.tableColumns.firstIndex(where: { MisureColonne.base($0.headerCell.stringValue) == cose.col("scadenza") }) {
                let r = hv.headerRect(ofColumn: i)
                let larghezze = t2.tableColumns.map(\.width)
                let p = hv.convert(NSPoint(x: r.maxX - 1, y: r.midY), to: nil)

                if let su = NSEvent.mouseEvent(with: .leftMouseUp, location: p, modifierFlags: [.shift], timestamp: ProcessInfo.processInfo.systemUptime,
                                               windowNumber: fin.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 0) {
                    NSApp.postEvent(su, atStart: false)
                }
                if let giu = NSEvent.mouseEvent(with: .leftMouseDown, location: p, modifierFlags: [.shift], timestamp: ProcessInfo.processInfo.systemUptime,
                                                windowNumber: fin.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1) {
                    NSApp.sendEvent(giu)
                }
                try? await Task.sleep(nanoseconds: 600_000_000)
                await store.inFila { () }
                await giro()
                controlla("suspicion 5 · ⇧click on the column edge doesn't add an order level (\(store.coseOrdine.map(\.campo)))",
                          store.coseOrdine.map(\.campo) == ["priorita"])
                vedi("column widths equal after the edge click: \(larghezze == t2.tableColumns.map(\.width))")
            } else {
                controlla("suspicion 5 · the Due header", false)
            }
            store.impostaOrdine(s, [])
            await store.inFila { () }
        }



        if let st = cose.stati?.first(where: { $0.tolto != true }),
           let altro = cose.scelte_colori?.map(\.id).first(where: { $0 != st.colore }) {
            await giro()
            let e = await store.gestoVista(["stato-segno", st.id, st.segno, altro], undo: um)
            controlla("suspicion 3 · a new color reaches the list observed by the circles (\(RegistroStati.condiviso.def[st.id]?.colore ?? "-"), «\(e?.errore ?? e?.riga ?? "")»)",
                      RegistroStati.condiviso.def[st.id]?.colore == altro)
            await giro()
            um?.undo()
            await aspetta { RegistroStati.condiviso.def[st.id]?.colore == st.colore }
            vedi("⌘Z restores the previous color: \(RegistroStati.condiviso.def[st.id]?.colore == st.colore)")
        } else {
            controlla("suspicion 3 · a status with another possible color", false)
        }


        let vistaPrima = store.coseVista
        for v in (["urgenti"] + (cose.schede?.map(\.id) ?? [])) {
            store.coseVista = v
            await store.caricaCose()
            if store.disposizione().count > 1 { break }
        }
        try? await Task.sleep(nanoseconds: 900_000_000)
        host.layoutSubtreeIfNeeded()
        await giro()
        host.layoutSubtreeIfNeeded()
        if store.disposizione().count > 1 {
            let t0 = TabellaCose.disegni, h0 = IntestazioneFerma.disegni
            for x in [12.0, 30.0, 55.0, 0.0] {
                ScorrimentoCose.condiviso.x = x
                await giro()
                host.layoutSubtreeIfNeeded()
            }
            let dt = TabellaCose.disegni - t0, dh = IntestazioneFerma.disegni - h0
            controlla("suspicion 2 · four side scrolls: table redrawn \(dt) times, group rows \(dh) (view \(store.coseVista))",
                      dt == 0 && dh > 0)
        } else {
            controlla("suspicion 2 · a view with groups", false)
        }
        store.coseVista = vistaPrima
        await store.caricaCose()
        await giro()


        Store.sezioneImpostazioni = "stati"
        let pannello = NSHostingView(rootView: AnyView(PannelloImpostazioniCose().environment(store).frame(width: 760, height: 560)))
        pannello.frame = NSRect(x: 0, y: 0, width: 760, height: 560)
        let fin2 = NSWindow(contentRect: pannello.frame, styleMask: [.titled], backing: .buffered, defer: false)
        fin2.isReleasedWhenClosed = false
        fin2.contentView = pannello
        try? await Task.sleep(nanoseconds: 1_000_000_000)
        pannello.layoutSubtreeIfNeeded()
        await giro()
        pannello.layoutSubtreeIfNeeded()
        if let st = store.cose?.stati?.first(where: { $0.tolto != true }),
           let c = trovaTutti(pannello, NSTextField.self).first(where: { $0.isEditable && $0.stringValue == st.nome }) {
            let nuovo = st.nome + " prova"
            await scrivi(fin2, c, nuovo, tutto: true)
            await giro()
            pannello.rootView = AnyView(Color.clear.frame(width: 760, height: 560))
            pannello.layoutSubtreeIfNeeded()
            await giro()
            await aspetta { store.cose?.stati?.first(where: { $0.id == st.id })?.nome == nuovo }
            let salvato = store.cose?.stati?.first(where: { $0.id == st.id })?.nome == nuovo
            let esito = store.coseEsitoImpostazioni?.testo ?? ""
            await giro()
            fin2.undoManager?.undo()
            await aspetta { store.cose?.stati?.first(where: { $0.id == st.id })?.nome == st.nome }
            let unaVolta = store.cose?.stati?.first(where: { $0.id == st.id })?.nome == st.nome
            controlla("T6 · a status name typed and Settings closed without Enter: saved \(salvato), one ⌘Z restores it \(unaVolta), outcome «\(esito)»",
                      salvato && unaVolta && !esito.isEmpty)
        } else {
            controlla("T6 · the status name field in Settings (fields: \(trovaTutti(pannello, NSTextField.self).filter(\.isEditable).map(\.stringValue)))", false)
        }
        fin2.close()

        await lR9(store: store, fin: fin, host: host, liberi: liberi, cose: cose, dir: dir, controlla: controlla, vedi: vedi,
                  aspetta: aspetta, giro: giro, apri: apri)
        await mFoglio(store: store, fin: fin, host: host, cose: cose, controlla: controlla, vedi: vedi, aspetta: aspetta, giro: giro)
        await pCerchio(store: store, fin: fin, host: host, controlla: controlla, vedi: vedi, aspetta: aspetta, giro: giro)
        await oSchede(store: store, fin: fin, host: host, controlla: controlla, vedi: vedi, giro: giro)

        let c = StatoConversazione.condiviso
        c.aperta = true
        await giro()
        host.layoutSubtreeIfNeeded()
        if let campo = campoCon(host, store.tv("barra_segnaposto")) {
            await scrivi(fin, campo, "una frase da non perdere", tutto: true)
            await giro()
            tasto(fin, "\u{1b}", 53)
            await giro()
            controlla("T5 · Esc in the bar closes the thread (\(!c.aperta)) and the text stays («\(c.testo)»)",
                      !c.aperta && c.testo == "una frase da non perdere")
            c.testo = ""
        } else {
            controlla("T5 · the bar field", false)
        }
    }



    static func oSchede(store: Store, fin: NSWindow, host: NSView, controlla: (String, Bool) -> Void,
                        vedi: (String) -> Void, giro: () async -> Void) async {
        store.dettaglioCose = false
        store.coseFiltroAlVolo = [:]
        store.coseVista = "tutte"
        await giro()
        try? await Task.sleep(nanoseconds: 800_000_000)
        host.layoutSubtreeIfNeeded()
        host.display()
        let n = store.cose?.righe?.count ?? 0
        let passi = ["foglio", "bacheca", "calendario", "tutte", "bacheca", "foglio", "tutte"]
        var da = "tutte"
        var righe: [String] = []
        var tuttiSenzaMotore = true
        var tuttiVeloci = true
        for a in passi {
            let prima = Motore.chiamate.count
            let corpi = TabellaCose.disegni
            let t0 = ContinuousClock.now
            store.coseVista = a
            host.layoutSubtreeIfNeeded()
            host.display()

            for _ in 0..<2 {
                await withCheckedContinuation { (k: CheckedContinuation<Void, Never>) in DispatchQueue.main.async { k.resume() } }
                host.layoutSubtreeIfNeeded()
                host.display()
            }
            let durata = ContinuousClock.now - t0
            let corpiTabella = TabellaCose.disegni - corpi
            let ms = Double(durata.components.attoseconds) / 1e15 + Double(durata.components.seconds) * 1000
            await giro()
            try? await Task.sleep(nanoseconds: 700_000_000)
            let nuove = Array(Motore.chiamate.dropFirst(prima))
            righe.append("\(da)→\(a) \(Int(ms)) ms (table bodies \(corpiTabella)), engine \(nuove.count)\(nuove.isEmpty ? "" : " (\(nuove.joined(separator: ", ")))")")
            if a != "calendario" && da != "calendario" {
                if !nuove.isEmpty { tuttiSenzaMotore = false }
                if ms >= 100 { tuttiVeloci = false }
            }
            da = a
        }
        for r in righe { vedi("O · \(r)") }
        controlla("O · between Table, Sheet and Board switching tabs doesn't call the engine", tuttiSenzaMotore)

        vedi("O · with \(n) tasks all switches under 100 ms: \(tuttiVeloci)")
        store.coseVista = "tutte"
        await giro()
    }



    static func mFoglio(store: Store, fin: NSWindow, host: NSView, cose: Cose, controlla: (String, Bool) -> Void,
                        vedi: (String) -> Void, aspetta: (() -> Bool) async -> Void, giro: () async -> Void) async {
        store.dettaglioCose = false
        store.coseFiltroAlVolo = [:]
        let t0 = ContinuousClock.now
        store.coseVista = "foglio"
        await store.caricaCose()
        host.layoutSubtreeIfNeeded()
        await giro()
        host.layoutSubtreeIfNeeded()
        let tApertura = ContinuousClock.now - t0
        guard let tv = tabella(host) else { controlla("M · the Sheet table", false); return }
        let righe = store.righeAVista()
        if !tv.gridStyleMask.contains(.solidVerticalGridLineMask) {
            let g0 = ContinuousClock.now
            await aspetta { tv.gridStyleMask.contains(.solidVerticalGridLineMask) }
            vedi("M · the vertical lines were missing at first glance: arrived after \(ContinuousClock.now - g0) (\(tv.gridStyleMask.contains(.solidVerticalGridLineMask)))")
        }
        controlla("M · Sheet: rows of \(Int(tv.rowHeight)) points (row 0 height \(Int(tv.rect(ofRow: 0).height))), vertical lines \(tv.gridStyleMask.contains(.solidVerticalGridLineMask)), style \(tv.style.rawValue)",
                  tv.rowHeight == 22 && tv.rect(ofRow: 0).height == 22 && tv.gridStyleMask.contains(.solidVerticalGridLineMask))
        controlla("M · no group: \(tv.numberOfRows) rows in the table, \(righe.count) tasks", tv.numberOfRows == righe.count)
        let accese = tv.tableColumns.filter { !$0.isHidden }.count
        controlla("M · all columns on at start: \(accese) (circle, Task and \(Store.colonneAccendibili.count))",
                  accese == Store.colonneAccendibili.count + 2)
        vedi("M · Sheet opening \(tApertura), \(tv.rows(in: tv.visibleRect).length) rows on screen in \(Int(tv.enclosingScrollView?.contentView.bounds.height ?? 0)) points")
        guard righe.count > 4 else { return }
        let a = righe[1], b = righe[2]
        store.coseScelte = [a.id]
        store.coseFoglioColonna = "task"
        fin.makeFirstResponder(tv)
        await giro()

        tasto(fin, String(UnicodeScalar(0xF703)!), 124, [.numericPad, .function])
        await giro()
        let dopoTask = store.coseFoglioColonna
        tasto(fin, String(UnicodeScalar(0xF703)!), 124, [.numericPad, .function])
        await giro()
        let dopoDue = store.coseFoglioColonna
        tasto(fin, String(UnicodeScalar(0xF702)!), 123, [.numericPad, .function])
        await giro()
        controlla("M · → → ← move the active cell: \(dopoTask), \(dopoDue), \(store.coseFoglioColonna)",
                  dopoTask != "task" && dopoDue != dopoTask && store.coseFoglioColonna == dopoTask)

        if let i = tv.tableColumns.firstIndex(where: { MisureColonne.base($0.headerCell.stringValue) == cose.col("area") }) {
            let r = tv.frameOfCell(atColumn: i, row: 1)
            let p = tv.convert(NSPoint(x: r.midX, y: r.midY), to: nil)
            if let su = NSEvent.mouseEvent(with: .leftMouseUp, location: p, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                           windowNumber: fin.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 0) {
                NSApp.postEvent(su, atStart: false)
            }
            if let giu = NSEvent.mouseEvent(with: .leftMouseDown, location: p, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                            windowNumber: fin.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1) {
                NSApp.sendEvent(giu)
            }
            await giro()
            controlla("M · a click on an Area cell makes it active (\(store.coseFoglioColonna)), its row selected \(store.coseScelte.contains(a.id))",
                      store.coseFoglioColonna == "area")

            store.coseScelte = [a.id]
            store.coseFoglioColonna = "area"
            await giro()
            await clicCella(fin, tv, colonna: i, riga: 1)
            await giro()
            controlla("P · a second click on an active Area opens the areas box (\(store.coseFoglioRiquadro ?? "none"))",
                      store.coseFoglioRiquadro == "\(a.id)|area")
            store.coseFoglioRiquadro = nil
            await giro()
            if let it = tv.tableColumns.firstIndex(where: { MisureColonne.base($0.headerCell.stringValue) == cose.col("task") }) {
                store.coseScelte = [a.id]
                await giro()
                await clicCella(fin, tv, colonna: it, riga: 1)
                await giro()
                let attivaTask = store.coseFoglioColonna == "task" && store.coseFoglioModifica == nil
                await clicCella(fin, tv, colonna: it, riga: 1)
                try? await Task.sleep(nanoseconds: 300_000_000)
                await giro()
                controlla("P · Task: a click makes it active (\(attivaTask)), a second click doesn't open the title (\(store.coseFoglioModifica == nil))",
                          attivaTask && store.coseFoglioModifica == nil && store.coseIndice[a.id]?.titolo == a.titolo)
            }

            let comandi = tv.subviews.flatMap { trovaTutti($0, NSControl.self) }.count
            controlla("P · in the Sheet cells no buttons, menus or fields (\(comandi) controls)", comandi == 0)

            if righe.count > 3 {
                let c3 = righe[3]
                let primaChiusa = store.coseIndice[c3.id]?.chiusaOra ?? false
                await clicCella(fin, tv, colonna: 0, riga: 3)
                await aspetta { (store.coseIndice[c3.id]?.chiusaOra ?? primaChiusa) != primaChiusa }
                let cambiata = (store.coseIndice[c3.id]?.chiusaOra ?? primaChiusa) != primaChiusa
                await giro()
                let riga3 = store.righeAVista().firstIndex { $0.id == c3.id } ?? -1
                if riga3 >= 0 { await clicCella(fin, tv, colonna: 0, riga: riga3) }
                await aspetta { store.coseIndice[c3.id]?.chiusaOra == primaChiusa }
                controlla("P · a click on the circle marks it done (\(cambiata)), another reopens it (\(store.coseIndice[c3.id]?.chiusaOra == primaChiusa))",
                          cambiata && store.coseIndice[c3.id]?.chiusaOra == primaChiusa)
                await giro()
            }

            store.coseScelte = [a.id]
            store.coseFoglioColonna = "area"
            fin.makeFirstResponder(tv)
            tasto(fin, "\r", 36)
            await giro()
            controlla("M · Enter on Area opens the areas box (\(store.coseFoglioRiquadro ?? "none"))", store.coseFoglioRiquadro == "\(a.id)|area")
            store.coseFoglioRiquadro = nil
            await giro()
        }

        store.coseFoglioColonna = "scadenza"
        fin.makeFirstResponder(tv)
        tasto(fin, "\r", 36)
        await giro()
        controlla("M · Enter on Due opens the box with the date's items (\(store.coseFoglioRiquadro ?? "none"))",
                  store.coseFoglioRiquadro == "\(a.id)|scadenza")
        store.coseFoglioRiquadro = nil
        await giro()

        let pa = store.coseIndice[a.id]?.priorita ?? 2
        let np = pa == 3 ? 2 : 3
        fin.makeFirstResponder(tv)
        tasto(fin, "\(np)", np == 3 ? 20 : 19)
        await aspetta { store.coseIndice[a.id]?.priorita == np }
        controlla("M · the \(np) key in the Sheet moves it to P\(np)", store.coseIndice[a.id]?.priorita == np)


        store.coseFoglioColonna = "task"
        let titoloA = store.coseIndice[a.id]?.titolo ?? ""
        let titoloB = store.coseIndice[b.id]?.titolo ?? ""
        store.coseScelte = [a.id]
        fin.makeFirstResponder(tv)
        await giro()
        let scelteLettera = store.coseScelte
        tasto(fin, "z", 6)
        await giro()
        tasto(fin, "Z", 6, [.shift])
        await giro()
        controlla("P · a letter on the row changes nothing: editing \(store.coseFoglioModifica ?? "closed"), title unchanged \(store.coseIndice[a.id]?.titolo == titoloA), selection unchanged \(store.coseScelte == scelteLettera), pending \(store.coseScrittiInCorso.count)",
                  store.coseFoglioModifica == nil && store.coseIndice[a.id]?.titolo == titoloA && store.coseScelte == scelteLettera
                    && store.coseScrittiInCorso["\(a.id)|titolo"] == nil)
        tasto(fin, "\r", 36)
        await aspetta { fin.firstResponder is NSTextView }
        var cursoreInFondo = false
        if let ed = fin.firstResponder as? NSTextView {
            await aspetta { ed.selectedRange().location == (ed.string as NSString).length }
            cursoreInFondo = ed.selectedRange() == NSRange(location: (ed.string as NSString).length, length: 0)
        }
        controlla("P · Enter opens the title with the whole text («\(store.coseFoglioBozza)») and the cursor at the end (\(cursoreInFondo)), nothing among the pending",
                  store.coseFoglioModifica == a.id && store.coseFoglioBozza == titoloA && cursoreInFondo
                    && store.coseScrittiInCorso["\(a.id)|titolo"] == nil)
        if let ed = fin.firstResponder as? NSTextView {
            ed.selectAll(nil)
            ed.insertText("Esempio", replacementRange: ed.selectedRange())
            await giro()
        }
        controlla("M · the typed text is among the pending (app close)", store.coseScrittiInCorso["\(a.id)|titolo"]?.testo == "Esempio")
        tasto(fin, "\t", 48)
        await aspetta { store.coseIndice[a.id]?.titolo == "Esempio" && store.coseFoglioModifica == b.id }
        controlla("M · Tab saves («\(store.coseIndice[a.id]?.titolo ?? "")») and moves to the next row in editing, with its whole title (editing \(store.coseFoglioModifica == b.id), selection \(store.coseScelte == [b.id]), draft «\(store.coseFoglioBozza.prefix(30))» vs «\(titoloB.prefix(30))»)",
                  store.coseIndice[a.id]?.titolo == "Esempio" && store.coseFoglioModifica == b.id && store.coseScelte == [b.id]
                    && store.coseFoglioBozza == titoloB)
        await aspetta { fin.firstResponder is NSTextView }
        if let ed = fin.firstResponder as? NSTextView {
            ed.selectAll(nil)
            ed.insertText("Titolo da non salvare", replacementRange: ed.selectedRange())
            await giro()
        }
        tasto(fin, "\u{1b}", 53)
        await aspetta { store.coseFoglioModifica == nil }
        try? await Task.sleep(nanoseconds: 600_000_000)
        await giro()
        controlla("P · Esc cancels: the previous title stays («\(store.coseIndice[b.id]?.titolo ?? "")»), nothing among the pending",
                  store.coseIndice[b.id]?.titolo == titoloB && store.coseFoglioModifica == nil
                    && store.coseScrittiInCorso["\(b.id)|titolo"] == nil)

        store.coseScelte = [b.id]
        fin.makeFirstResponder(tv)
        await giro()
        tasto(fin, String(UnicodeScalar(NSF2FunctionKey)!), 120, [.function])
        await aspetta { fin.firstResponder is NSTextView }
        let conF2 = store.coseFoglioModifica == b.id && store.coseFoglioBozza == titoloB
        if let ed = fin.firstResponder as? NSTextView {
            ed.selectAll(nil)
            ed.deleteBackward(nil)
            await giro()
        }
        tasto(fin, "\r", 36)
        await aspetta { store.coseFoglioModifica == nil }
        try? await Task.sleep(nanoseconds: 600_000_000)
        await giro()
        controlla("P · F2 opens the title (\(conF2)); emptied and Enter doesn't save: «\(store.coseIndice[b.id]?.titolo ?? "")» (editing \(store.coseFoglioModifica ?? "closed"), pending \(store.coseScrittiInCorso.keys.sorted()), focus \(type(of: fin.firstResponder!)))",
                  conF2 && store.coseIndice[b.id]?.titolo == titoloB && store.coseFoglioModifica == nil
                    && store.coseScrittiInCorso["\(b.id)|titolo"] == nil)
        await giro()
        store.coseUndo?.undo()
        await aspetta { store.coseIndice[a.id]?.titolo == titoloA }
        controlla("M · ⌘Z restores the previous title", store.coseIndice[a.id]?.titolo == titoloA)

        let tv2 = tabella(host) ?? tv
        controlla("M · after the gestures the rows are still \(Int(tv2.rect(ofRow: 0).height)) points", tv2.rect(ofRow: 0).height == 22)

        let tabellaPrima = store.coseColonne
        store.coseColonneFoglio[visibility: "rinvii"] = .hidden
        controlla("M · turning off a column in the Sheet doesn't touch the Table",
                  !Store.colonnaAccesa(store.coseColonneFoglio, "rinvii", tutte: true) && store.coseColonne == tabellaPrima)
        store.coseColonneFoglio = TableColumnCustomization<VoceCosa>()

        let t1 = ContinuousClock.now
        await store.gestoTask("priorita", [a.id], ["\(pa)"])
        host.layoutSubtreeIfNeeded()
        vedi("M · one gesture in the Sheet, engine and redraw: \(ContinuousClock.now - t1)")
        store.coseVista = "tutte"
        await store.caricaCose()
        await giro()
    }



    static func pCerchio(store: Store, fin: NSWindow, host: NSView, controlla: (String, Bool) -> Void, vedi: (String) -> Void,
                         aspetta: (() -> Bool) async -> Void, giro: () async -> Void) async {
        store.dettaglioCose = false
        store.coseFiltroAlVolo = [:]
        store.coseVista = "tutte"
        await store.caricaCose()
        await giro()
        func chiuse(_ ids: [String]) -> [String: Bool] {
            Dictionary(uniqueKeysWithValues: ids.map { ($0, store.coseIndice[$0]?.chiusaOra ?? false) })
        }

        if let tutte = store.schedaCose, let e = await store.gestoVista(["vista-duplica", tutte.id, "foglio"]), let nid = e.id {
            store.coseVista = nid
            await giro()
            host.layoutSubtreeIfNeeded()
            let gruppi = store.disposizione()
            if let s = store.schedaCose, s.modo == "foglio", let g0 = gruppi.first(where: { !$0.righe.isEmpty && !$0.id.isEmpty }),
               gruppi.filter({ !$0.righe.isEmpty }).count > 1 {
                store.chiudiGruppo(s, g0.id, true)
                await giro()
                host.layoutSubtreeIfNeeded()
                await giro()
                let mostrate = store.disposizione().flatMap(\.righe)
                if let tv = tabella(host), tv.numberOfRows == mostrate.count, g0.righe.count + 1 < mostrate.count {
                    let k = g0.righe.count + 1
                    tv.scrollRowToVisible(k)
                    host.layoutSubtreeIfNeeded()
                    let ids = mostrate.map(\.id)
                    let prima = chiuse(ids)
                    let atteso = mostrate[k].id
                    await clicCella(fin, tv, colonna: 0, riga: k)
                    await aspetta { store.coseIndice[atteso]?.chiusaOra != prima[atteso] }
                    try? await Task.sleep(nanoseconds: 400_000_000)
                    let dopo = chiuse(ids)
                    let cambiate = ids.filter { dopo[$0] != prima[$0] }
                    controlla("P · Sheet with the group «\(g0.nome)» closed in the middle (\(g0.righe.count) rows): the circle on row \(k) marks its task and no other (changed \(cambiate.count), the right one \(cambiate == [atteso]))",
                              cambiate == [atteso])
                    for id in cambiate { await store.fattaORiapri([id]) }
                    await aspetta { chiuse(ids) == prima }
                } else {
                    controlla("P · the duplicated Sheet table (rows \(tabella(host)?.numberOfRows ?? -1), shown \(mostrate.count))", false)
                }
                store.chiudiGruppo(s, g0.id, false)
            } else {
                controlla("P · the Sheet duplicated from All has multiple groups with rows (\(gruppi.count), mode \(store.schedaCose?.modo ?? ""))", false)
            }
            store.coseVista = "tutte"
            await giro()
            _ = await store.gestoVista(["vista-elimina", nid])
            await giro()
        } else {
            controlla("P · All duplicated as Sheet", false)
        }

        store.coseVista = "foglio"
        await giro()
        let righe = store.righeAVista()
        guard let r0 = righe.first else { return }
        store.coseScelte = [r0.id]
        store.cosaAperta = r0.id
        store.dettaglioCose = true
        let conv = StatoConversazione.condiviso
        conv.aperta = true
        await giro()
        host.layoutSubtreeIfNeeded()
        try? await Task.sleep(nanoseconds: 500_000_000)
        host.layoutSubtreeIfNeeded()
        await giro()
        if let tv = tabella(host), let cv = fin.contentView {
            let visibili = tv.rows(in: tv.visibleRect)
            var coperta: (Int, NSPoint)?
            for r in (visibili.location..<(visibili.location + visibili.length)).reversed() {
                let rr = tv.frameOfCell(atColumn: 0, row: r)
                let p = tv.convert(NSPoint(x: rr.midX, y: rr.midY), to: nil)
                let hit = cv.hitTest(cv.superview?.convert(p, from: nil) ?? p)
                if let hit, !(hit === tv || hit.isDescendant(of: tv)) { coperta = (r, p); break }
            }
            if let (r, p) = coperta, r < righe.count {
                let ids = store.righeAVista().map(\.id)
                let prima = chiuse(ids)
                let colonnaPrima = store.coseFoglioColonna
                if let su = NSEvent.mouseEvent(with: .leftMouseUp, location: p, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                               windowNumber: fin.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 0) {
                    NSApp.postEvent(su, atStart: false)
                }
                if let giu = NSEvent.mouseEvent(with: .leftMouseDown, location: p, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                                windowNumber: fin.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1) {
                    NSApp.sendEvent(giu)
                }
                try? await Task.sleep(nanoseconds: 900_000_000)
                await giro()
                let cambiate = ids.filter { chiuse(ids)[$0] != prima[$0] }
                controlla("P · a click on the item's thread over the circle on row \(r) doesn't touch the tasks (changed \(cambiate.count)) nor the active cell (\(store.coseFoglioColonna))",
                          cambiate.isEmpty && store.coseFoglioColonna == colonnaPrima)
                for id in cambiate { await store.fattaORiapri([id]) }
            } else {
                controlla("P · with the detail open the item's thread covers the circles column (rows shown \(visibili.length))", false)
            }
        }
        conv.aperta = false
        store.dettaglioCose = false
        store.coseVista = "tutte"
        await store.caricaCose()
        await giro()
    }


    static func clicCella(_ fin: NSWindow, _ tv: NSTableView, colonna: Int, riga: Int) async {
        let r = tv.frameOfCell(atColumn: colonna, row: riga)
        let p = tv.convert(NSPoint(x: r.midX, y: r.midY), to: nil)
        if let su = NSEvent.mouseEvent(with: .leftMouseUp, location: p, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                       windowNumber: fin.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 0) {
            NSApp.postEvent(su, atStart: false)
        }
        if let giu = NSEvent.mouseEvent(with: .leftMouseDown, location: p, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                        windowNumber: fin.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1) {
            NSApp.sendEvent(giu)
        }

        await withCheckedContinuation { (k: CheckedContinuation<Void, Never>) in DispatchQueue.main.async { k.resume() } }
    }




    static func bL(store: Store, fin: NSWindow, tv: NSTableView, controlla: (String, Bool) -> Void, vedi: (String) -> Void,
                   giro: () async -> Void) async {
        typealias D = Store.DecisioneTasto
        var tutti = true
        var righe: [String] = []
        for davanti in [true, false] { for riconosciuta in [true, false] { for attivita in [true, false] { for campo in [true, false] {
            let atteso: D = campo ? .alCampo : (!riconosciuta ? .agisci : (davanti && attivita ? .agisci : .niente))
            let d = Store.decidiTasto(davantiPrincipale: davanti, principaleRiconosciuta: riconosciuta, inAttivita: attivita, inUnCampo: campo)
            if d != atteso { tutti = false; righe.append("\(davanti) \(riconosciuta) \(attivita) \(campo) → \(d)") }
        } } } }
        controlla("B2 · the key rule in the sixteen cases (field first, fallback on, otherwise only main and Activity) \(righe)", tutti)
        controlla("B2 · the window with the main content has the mark (finestraPrincipale is it)", Store.finestraPrincipale === fin)
        let imp = NSHostingView(rootView: PannelloImpostazioniCose().environment(store).frame(width: 760, height: 560))
        imp.frame = NSRect(x: 0, y: 0, width: 760, height: 560)
        let finImp = NSWindow(contentRect: imp.frame, styleMask: [.titled], backing: .buffered, defer: false)
        finImp.isReleasedWhenClosed = false
        finImp.contentView = imp
        try? await Task.sleep(nanoseconds: 800_000_000)
        imp.layoutSubtreeIfNeeded()
        await giro()
        imp.layoutSubtreeIfNeeded()
        controlla("B2 · the Settings window doesn't take the mark", Store.finestraPrincipale === fin)
        var fatto = false
        fin.makeFirstResponder(tv)
        Store.finestraProva = fin
        let conPrincipale = store.daTasto { fatto = true }
        controlla("B2 · main in front, table, Activity: the keys act", conPrincipale == .agisci && fatto)
        fatto = false
        Store.finestraProva = finImp
        finImp.makeFirstResponder(nil)
        let conImp = store.daTasto { fatto = true }
        controlla("B2 · Settings in front: the keys don't touch the tasks", conImp == .niente && !fatto)
        if let campo = trovaTutti(imp, NSTextField.self).first(where: { $0.isEditable }) {
            finImp.makeFirstResponder(campo)
            let nelCampo = store.daTasto(cancella: true) { fatto = true }
            controlla("R1 · ⌘⌫ in a Settings field goes to the field (\(nelCampo)), not to the tasks", nelCampo == .alCampo && !fatto)
            finImp.makeFirstResponder(nil)
        } else {
            controlla("R1 · a field in Settings", false)
        }
        let foglio = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 300, height: 200), styleMask: [.titled], backing: .buffered, defer: false)
        foglio.isReleasedWhenClosed = false
        Store.finestraProva = foglio
        controlla("B2 · a sheet or panel in front: nothing", store.daTasto { fatto = true } == .niente && !fatto)

        Store.finestraProva = fin
        store.sezione = .panoramica
        let altraSezione = store.daTasto { fatto = true }
        store.sezione = .cose
        controlla("B2 · another section open: nothing", altraSezione == .niente && !fatto)

        let segno = Store.finestraPrincipale
        Store.finestraPrincipale = nil
        Store.finestraProva = foglio
        let ripiego = store.daTasto { fatto = true }
        Store.finestraPrincipale = segno
        Store.finestraProva = fin
        controlla("B2 · without the main's mark the keys stay on (fallback, never all off)", ripiego == .agisci && fatto)
        foglio.close()
        finImp.close()
        fin.makeFirstResponder(tv)
        vedi("to check in the real window: that the Window scene's window is the marked one and is the keyWindow when in front (gesture 1)")
    }


    static func lR9(store: Store, fin: NSWindow, host: NSView, liberi: [VoceCosa], cose: Cose, dir: String,
                    controlla: (String, Bool) -> Void, vedi: (String) -> Void, aspetta: (() -> Bool) async -> Void,
                    giro: () async -> Void, apri: (String) async -> Void) async {

        let r = liberi.count > 6 ? liberi[6] : liberi[0]
        await apri(r.id)
        let segno = "Scritto e chiuso col rosso \(Int(Date().timeIntervalSince1970) % 100000)"
        if let editor = trovaTutti(host, NSTextView.self).first(where: { $0.isEditable && $0.enclosingScrollView != nil && $0.bounds.height > 100 }) {
            fin.makeFirstResponder(editor)
            editor.moveToEndOfDocument(nil)
            editor.insertText(" " + segno, replacementRange: editor.selectedRange())
            await giro()


            let tappo = Task { await store.inFila { try? await Task.sleep(nanoseconds: 2_500_000_000) } }
            try? await Task.sleep(nanoseconds: 100_000_000)
            store.dettaglioCose = false
            host.layoutSubtreeIfNeeded()

            await aspetta { store.coseOccupate.contains(r.id) }
            let partito = store.coseOccupate.contains(r.id)
            let k = "\(r.id)|descrizione"
            let tenuto = partito && store.coseScrittiInCorso[k]?.testo.contains(segno) == true

            store.salvaScrittiAllaChiusura()
            await tappo.value
            await store.inFila { () }
            await store.caricaCose()
            try? await Task.sleep(nanoseconds: 800_000_000)
            await store.caricaCose()
            let scritto = store.coseIndice[r.id]?.dettaglio.contains(segno) == true
            let righe = ((try? String(contentsOfFile: dir + "/eventi.jsonl", encoding: .utf8)) ?? "").split(separator: "\n")
                .filter { $0.contains(segno) }
            let conflitto = store.coseConflitti.contains { $0.id == r.id }
            controlla("R4 · detail closed and app closed before the answer: pending until the answer \(tenuto), written \(scritto), \(righe.count) write, no conflict \(!conflitto)",
                      tenuto && scritto && righe.count == 1 && !conflitto)
        } else {
            controlla("R4 · the description field", false)
        }
        store.dettaglioCose = false
        await giro()


        let r5 = liberi.count > 7 ? liberi[7] : liberi[1]
        await apri(r5.id)
        if let c = campoCon(host, cose.t("stima_segnaposto")) {
            await scrivi(fin, c, "tanto", tutto: true)
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            fin.makeFirstResponder(nil)
            await giro()
            host.layoutSubtreeIfNeeded()
            let resta = campoCon(host, cose.t("stima_segnaposto"))?.stringValue
            controlla("R5 · «tanto» leaving the field stays to be corrected («\(resta ?? "")»)", resta == "tanto")
        } else {
            controlla("R5 · the time field", false)
        }
        store.dettaglioCose = false
        await giro()


        if let s = store.schedaCose {
            store.impostaOrdine(s, [])
            await store.inFila { () }
            await store.caricaCose()
            let p = OrdineVista(campo: "priorita", verso: "su"), q = OrdineVista(campo: "scadenza", verso: "su"),
                a = OrdineVista(campo: "area", verso: "su")
            store.impostaOrdine(s, [p])
            store.impostaOrdine(s, [p, q])
            store.impostaOrdine(s, [p, q, a])
            var minimo = store.coseOrdine.count
            for _ in 0..<60 {
                try? await Task.sleep(nanoseconds: 50_000_000)
                minimo = min(minimo, store.coseOrdine.count)
            }
            await store.inFila { () }
            await store.caricaCose()
            let salvati = store.schedaCose?.livelli.map(\.campo) ?? []
            controlla("R2 · three quick order clicks: never fewer than three levels shown (\(minimo)), saved \(salvati), in flight \(store.coseOrdiniInVolo)",
                      minimo == 3 && store.coseOrdine.count == 3 && salvati == ["priorita", "scadenza", "area"] && store.coseOrdiniInVolo == 0)
            store.impostaOrdine(s, [])
            await store.inFila { () }
            await store.caricaCose()
        }


        Store.sezioneImpostazioni = "aree"
        let pannello = NSHostingView(rootView: PannelloImpostazioniCose().environment(store).frame(width: 760, height: 560))
        pannello.frame = NSRect(x: 0, y: 0, width: 760, height: 560)
        let fin3 = NSWindow(contentRect: pannello.frame, styleMask: [.titled], backing: .buffered, defer: false)
        fin3.isReleasedWhenClosed = false
        fin3.contentView = pannello
        try? await Task.sleep(nanoseconds: 900_000_000)
        pannello.layoutSubtreeIfNeeded()
        await giro()
        pannello.layoutSubtreeIfNeeded()
        if let ar = store.cose?.areeDiOwner.first,
           trovaTutti(pannello, NSTextField.self).contains(where: { $0.isEditable && $0.stringValue == ar.nome }) {
            let nuovo = ar.nome + " bis"
            func campo() -> NSTextField? {
                trovaTutti(pannello, NSTextField.self).first { $0.isEditable && ($0.stringValue == ar.nome || $0.stringValue == nuovo) }
            }
            func nome() -> String? { store.cose?.aree_def?.first { $0.id == ar.id }?.nome }
            if let c = campo() { await scrivi(fin3, c, nuovo, tutto: true) }
            fin3.makeFirstResponder(nil)
            await giro()
            await aspetta { nome() == nuovo }
            let primo = nome() == nuovo
            let esitoGesto = store.coseEsitoImpostazioni?.testo ?? ""
            await giro()
            fin3.undoManager?.undo()
            await aspetta { nome() == ar.nome }
            await aspetta { store.coseEsitoImpostazioni?.testo != esitoGesto }
            let esitoAnnulla = store.coseEsitoImpostazioni?.testo ?? ""
            pannello.layoutSubtreeIfNeeded()
            await giro()
            if let c = campo() { await scrivi(fin3, c, nuovo, tutto: true) }
            fin3.makeFirstResponder(nil)
            await giro()
            await aspetta { nome() == nuovo }
            controlla("R6 · rename, ⌘Z, the same name again: it saves (\(primo), then \(nome() == nuovo))", primo && nome() == nuovo)
            controlla("R8 · after the ⌘Z the panel shows the ⌘Z outcome («\(esitoGesto)» → «\(esitoAnnulla)»)",
                      !esitoAnnulla.isEmpty && esitoAnnulla != esitoGesto)
            await giro()
            fin3.undoManager?.undo()
            await aspetta { nome() == ar.nome }
        } else {
            controlla("R6 · the area name field in Settings", false)
        }
        fin3.close()
        Store.sezioneImpostazioni = "stati"


        store.sezione = .panoramica
        await giro()
        host.layoutSubtreeIfNeeded()
        let prima = AperturaImpostazioni.aperture
        store.apriImpostazioni("stati")
        await aspetta { AperturaImpostazioni.aperture > prima }
        await giro()
        controlla("R3 · from another section the request reaches openSettings once (\(AperturaImpostazioni.aperture - prima))",
                  AperturaImpostazioni.aperture == prima + 1)
        store.sezione = .cose
        await giro()
    }
}




struct ProvaMenuCose: View {
    @Environment(Store.self) private var store
    var body: some View {
        if let c = store.cose, let id = c.righe?.first?.id {
            ScrollView {
                HStack(alignment: .top, spacing: 28) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(c.col("stato")).font(.headline)
                        VociStato(cose: c, store: store, ids: [id])
                        Divider().padding(.vertical, 6)
                        Text(c.col("stima")).font(.headline)
                        VociStima(cose: c, store: store, ids: [id])
                    }
                    .frame(width: 240, alignment: .leading)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(c.col("area")).font(.headline)
                        VociArea(cose: c, store: store, ids: [id])

                        if let pronti = c.filtri_pronti {
                            Divider().padding(.vertical, 6)
                            Text(c.t("filtri_pronti")).font(.headline)
                            ForEach(pronti) { p in
                                Toggle(c.t("filtro_scelta").replacingOccurrences(of: "{nome}", with: p.nome)
                                        .replacingOccurrences(of: "{n}", with: (p.n ?? 0).formatted()), isOn: .constant(p.id == "urgenti"))
                            }
                        }
                    }
                    .frame(width: 240, alignment: .leading)
                    VStack(alignment: .leading, spacing: 8) {
                        Text(c.t("menu_ordine")).font(.headline)
                        if let s = store.schedaCose { MenuOrdineCose(cose: c, store: store, scheda: s) }
                        Divider().padding(.vertical, 6)

                        ForEach(c.stati?.filter { $0.tolto != true } ?? []) { st in
                            HStack(spacing: 10) {
                                ForEach(c.scelte_segni?[st.tipo] ?? [], id: \.self) { Image(systemName: $0) }
                            }
                        }
                        Divider().padding(.vertical, 6)

                        ForEach(["commenta", "commento-togli", "priorita", "stima", "pianifica"], id: \.self) { v in
                            Text(store.t("annulla") + " " + store.nomeAzione(v, v == "stima" ? 1_200 : 1))
                        }
                    }
                }
                .padding(24)
            }
        }
    }
}
