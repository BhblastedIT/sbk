import AppKit
import SwiftUI



struct SBKApp: App {
    @NSApplicationDelegateAdaptor(DelegatoApp.self) private var delegato
    @State private var store = Store()

    init() {
        NSApplication.shared.setActivationPolicy(.regular)

        NSApplication.shared.disableRelaunchOnLogin()
    }

    var body: some Scene {
        Window("SBK", id: "principale") {
            Principale()
                .environment(store)


                .frame(minWidth: 1100, minHeight: 640)
                .onAppear {
                    delegato.store = store
                    store.finestraAperta = true
                    store.avvia()
                }
                .onDisappear { store.finestraAperta = false }
        }
        .defaultSize(width: 1180, height: 780)
        .commands { Comandi(store: store) }


        Settings {
            ImpostazioniApp()
                .environment(store)
        }
    }
}




@MainActor
final class DelegatoApp: NSObject, NSApplicationDelegate {
    weak var store: Store?

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {


        if DelegatoApp.aggiornamentoInCorso { return .terminateNow }
        guard let store, let r = store.runVivo else { return .terminateNow }
        let avviso = NSAlert()
        avviso.messageText = "\(r.nome ?? "A run") is running"
        avviso.informativeText = "If you close SBK the run keeps going, but the icon stays in the Dock until it finishes. "
            + "The Dock item «Stop Running in Background» would kill the run abruptly, without closing its "
            + "files properly. Better to hide the app, so it notifies you when it is done."
        avviso.addButton(withTitle: "Hide SBK")
        avviso.addButton(withTitle: "Close anyway")
        if avviso.runModal() == .alertFirstButtonReturn {
            NSApp.hide(nil)
            return .terminateCancel
        }
        return .terminateNow
    }


    static var aggiornamentoInCorso: Bool {
        let segno = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("local.sbk.secondbrain/aggiornamento-in-corso")
        guard let attributi = try? FileManager.default.attributesOfItem(atPath: segno.path),
              let quando = attributi[.modificationDate] as? Date else { return false }
        return Date().timeIntervalSince(quando) < 600
    }



    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        guard let store else { return true }
        return store.runVivo == nil && store.scarichiVivi.isEmpty && !store.lanciando
    }
}

struct Comandi: Commands {
    let store: Store

    var body: some Commands {
        CommandGroup(replacing: .appInfo) {
            Button("About SBK") { Comandi.informazioni(store: store) }
        }
        CommandGroup(replacing: .newItem) {

            Button(store.t("voce_nuova").isEmpty ? "New task" : store.t("voce_nuova")) {
                store.sezione = .cose
                store.coseFuocoChiesto = .nuova
            }
            .keyboardShortcut("n", modifiers: .command)

            Button(store.t("voce_detta").isEmpty ? "Dictate…" : store.t("voce_detta")) { store.detta() }
                .keyboardShortcut("n", modifiers: [.command, .shift])
                .disabled(store.microfonoAltrove)
        }
        CommandGroup(after: .toolbar) {
            Button("Refresh") {
                Task { await store.aggiorna(fresco: true) }

                if store.sezione == .cose { Task { await store.caricaCose(rileggi: true) } }
            }
                .keyboardShortcut("r", modifiers: .command)
            Button("Search") { NotificationCenter.default.post(name: .sbCerca, object: nil) }
                .keyboardShortcut("f", modifiers: .command)
            Button("How to read SBK") { store.foglio = .guida }


            if store.sezione != .cose {
                Button(store.ispettore ? "Hide the detail" : "Show the detail") { store.ispettore.toggle() }
                    .keyboardShortcut("i", modifiers: [.command, .option])
            }
            Divider()


            ForEach(Array(Sezione.allCases.enumerated()), id: \.element) { i, s in
                if let tasto = Comandi.tasto(s, posto: i) {
                    Button(s.nome) { store.sezione = s }
                        .keyboardShortcut(tasto.0, modifiers: tasto.1)
                } else {
                    Button(s.nome) { store.sezione = s }
                }
            }
            Button("Go to run") { store.sezione = .run }
                .keyboardShortcut("j", modifiers: .command)
            Divider()
        }
        CommandMenu(Text(store.t("menu_task").isEmpty ? "Task" : store.t("menu_task"))) {
            MenuTaskComandi(store: store)
        }
        CommandMenu("Run") {



            let altri = store.stato?.azioni.menu.filter { !["full", "full_completa"].contains($0.id) } ?? []
            Button("Full run free…") { store.foglio = .fullRun }
                .keyboardShortcut("r", modifiers: [.command, .shift])
                .disabled(store.occupato)
            ForEach(altri.filter { !$0.spesa }) { voce in
                Button("\(voce.nome)…") { store.apri(voce) }
                    .disabled(store.occupato)
            }
            Divider()
            ForEach(altri.filter(\.spesa)) { voce in
                Button("\(voce.nome)…") { store.apri(voce) }
                    .disabled(store.occupato)
            }
            Button("Full run complete…") { store.apriSpesa() }
                .disabled(store.occupato)
            Divider()
            Button("Pause") {
                if let r = store.runVivo { Task { await store.pausa(r) } }
            }
            .disabled(!(store.comandiRun?.pausa.possibile ?? false))
            Button("Continue") {
                if let r = store.runVivo { Task { await store.continua(r) } }
            }
            .disabled(!(store.comandiRun?.continua.possibile ?? false))
            Button("Resume where you left off…") {
                if let rp = store.stato?.ripresa { store.foglio = .riprendi(rp) }
            }
            .disabled(store.stato?.ripresa.map { store.fermo($0.azione) != nil } ?? true)
            Divider()
            Button("Stop the run…") {
                if let r = store.runVivo { store.foglio = .ferma(r) }
            }
            .keyboardShortcut(".", modifiers: .command)
            .disabled(store.runVivo == nil)
        }
    }


    static func tasto(_ s: Sezione, posto: Int) -> (KeyEquivalent, EventModifiers)? {
        switch s {

        case .cose: return ("t", .command)
        case .pagine: return ("p", [.command, .shift])
        case .inspiration: return ("0", .command)
        default: return (1...9).contains(posto) ? (KeyEquivalent(Character("\(posto)")), .command) : nil
        }
    }


    @MainActor
    static func informazioni(store: Store) {
        let versione = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
        let commit = Bundle.main.object(forInfoDictionaryKey: "SBCommitApp") as? String ?? "unknown"
        let motore = store.stato?.impronta?.motore ?? "not read"
        let testo = "SBK \(versione) — built from commit \(commit). Engine at commit \(motore).\n"
            + "The Mac face of SBK. The reasoning lives in the engine, tools/secondbrain/sb-app.py."
        NSApp.orderFrontStandardAboutPanel(options: [
            .credits: NSAttributedString(
                string: testo,
                attributes: [.font: NSFont.systemFont(ofSize: 11), .foregroundColor: NSColor.secondaryLabelColor]
            )
        ])
    }
}




struct MenuTaskComandi: View {
    let store: Store

    var body: some View {
        let qui = store.sezione == .cose && !store.coseCampoAttivo && store.cose != nil
        let ids = qui ? store.idsAzione : []
        Group {
            if let c = store.cose {
                Button(c.t("voce_dettaglio")) {
                    store.daTasto {
                        if store.dettaglioCose { store.dettaglioCose = false }
                        else if let id = ids.first { store.cosaAperta = id; store.dettaglioCose = true }
                    }
                }
                .keyboardShortcut("i", modifiers: .command)
                .disabled(!qui || (ids.isEmpty && !store.dettaglioCose))
                Divider()
                VociTask(cose: c, store: store, ids: ids, tasti: true)
                    .disabled(!qui || ids.isEmpty)
                Divider()
                Button(c.t("impostazioni_apri")) { store.apriImpostazioni(Store.sezioneImpostazioni) }
                Button(c.t("voce_scegli_tutte")) { store.coseScelte = Set(store.righeAVista().map(\.id)) }
                    .disabled(!qui)
                Button(c.t("voce_deseleziona")) { store.daTasto { store.coseScelte = [] } }
                    .keyboardShortcut("a", modifiers: [.command, .shift])
                    .disabled(!qui || store.coseScelte.isEmpty)
                Button(c.t("voce_cerca")) { store.sezione = .cose; store.coseFuocoChiesto = .cerca }
                    .keyboardShortcut("f", modifiers: [.command, .option])
                    .disabled(store.coseCampoAttivo)
                Divider()
                Button(c.t("voce_vista_prima")) { store.daTasto { store.vistaVicina(-1) } }
                    .keyboardShortcut(.leftArrow, modifiers: [.command, .option])
                    .disabled(!qui)
                Button(c.t("voce_vista_dopo")) { store.daTasto { store.vistaVicina(1) } }
                    .keyboardShortcut(.rightArrow, modifiers: [.command, .option])
                    .disabled(!qui)
                Button(c.t("voce_fatte")) { store.sezione = .cose; store.coseVista = "fatte" }
                Button(c.t("voce_eliminate")) { store.sezione = .cose; store.coseVista = "eliminate" }
                Divider()
                Button(c.t("voce_rileggi")) { Task { await store.caricaCose(rileggi: true) } }
            }
        }
    }
}
