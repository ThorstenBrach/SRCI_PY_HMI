# Plan: Robot-Integrator für TwinCAT, CODESYS und Python – die HMI als reine Oberfläche

Stand: 2026-10-05 · Status: **Plan, noch nicht umgesetzt**

## 1. Ziel

Die Komfortfunktionen, die heute in der HMI (SRCI_PY_HMI) stecken – Programmablauf, Tippen mit
Watchdog, Pause und Rückkehr zur Bahn, Grundstellung, Vermessen, Punkte und Programme … –
gehören in die Applikation, nicht in eine Bedienoberfläche. Sie sollen in drei Welten gleich
verfügbar sein:

| Welt | SRCI-Bibliothek läuft in | Applikation |
|---|---|---|
| **TwinCAT** | der SPS | ST-Applikation in der SPS |
| **CODESYS** | der SPS | ST-Applikation in der SPS |
| **Python** | dem PC (SRCI_PY) | Python-Skript / -Dienst |

**Grundsatz:** Die HMI darf die Funktionen *nutzen*, aber nicht *implementieren*. Alles, was eine
Applikation ohne HMI auch braucht, liegt im Robot-Integrator der jeweiligen Welt und ist dort im
Applikationscode zugänglich.

## 2. Schichten und Repositories

```
┌──────────────────────────────────────────────────────────────────────┐
│ HMI (SRCI_PY_HMI)            nur Oberfläche, ein Backend: Integrator-Schnittstelle │
└──────────────────────────────────────────────────────────────────────┘
                 ▲ Integrator-Schnittstelle (OPC UA, siehe 5.)
┌──────────────────────────────┐   ┌──────────────────────────────┐
│ Robot-Integrator IEC (neu)   │   │ Robot-Integrator Python (neu)│
│ TwinCAT + CODESYS, ST        │   │ Python                       │
└──────────────────────────────┘   └──────────────────────────────┘
               ▼ nutzt     gemeinsame Spezifikation + Testfälle     ▼ nutzt
┌──────────────────────────────┐   ┌──────────────────────────────┐
│ SRCI-Bibliothek IEC          │   │ SRCI-Bibliothek Python       │
│ ThorstenBrach/SRCI           │   │ SRCI_CLIENT_PY               │
└──────────────────────────────┘   └──────────────────────────────┘
```

| Repository | Inhalt | Sprache | Status |
|---|---|---|---|
| `SRCI` | SRCI-Bibliothek: Funktionsbausteine der Spezifikation | ST (TwinCAT, CODESYS) | vorhanden |
| `SRCI_CLIENT_PY` (lokal `SRCI_PY`) | SRCI-Bibliothek für Python, Transport, Simulator | Python | vorhanden |
| `SRCI_TcpIp_Bridge` | SPS als Durchreicher für die Python-Welt | ST | vorhanden |
| `SRCI_ROBOT_INTEGRATOR` (Name offen) | Komfortfunktionen + Integrator-Schnittstelle, nutzt `SRCI` | ST (TwinCAT, CODESYS) | **neu** |
| `SRCI_ROBOT_INTEGRATOR_PY` (Name offen) | derselbe Integrator für Python (eigene Implementierung nach derselben Spezifikation) + OPC-UA-Server, nutzt `SRCI_CLIENT_PY` | Python | **neu** |
| `SRCI_PY_HMI` | Bedienoberfläche, spricht nur die Integrator-Schnittstelle | Python (NiceGUI) | vorhanden, wird schlanker |

Abhängigkeiten zeigen nur nach unten: der Integrator kennt die Bibliothek, die HMI kennt nur die
Schnittstelle des Integrators – weder die Bibliothek noch die Funktionsbausteine.

## 3. Laufzeit in den drei Welten

```
TwinCAT:  HMI ──OPC UA (TF6100)──► SPS: Integrator + SRCI ──PROFINET──► RC
CODESYS:  HMI ──OPC UA (integriert)► SPS: Integrator + SRCI ──PROFINET──► RC
Python:   HMI ──OPC UA (asyncua)──► PC: Integrator + srci ──TCP──► SPS-Bridge ──PROFINET──► RC
          (für Tests / Einzelplatz optional ohne Netzwerk: HMI ruft den Integrator im selben Prozess)
```

Die HMI hat damit **ein** Backend für alle drei Welten. Der Python-Integrator stellt dieselbe
Schnittstelle über einen eigenen OPC-UA-Server bereit; der Aufruf im selben Prozess ist eine
Abkürzung für Tests und den Simulator, keine zweite Schnittstelle.

## 4. Zwei Implementierungen, eine Spezifikation

Der Integrator wird zweimal implementiert: in ST (`SRCI_ROBOT_INTEGRATOR`, läuft in TwinCAT und
CODESYS) und in Python (`SRCI_ROBOT_INTEGRATOR_PY`). Damit beide sich gleich verhalten:

- **Eine verbindliche Spezifikation** im Integrator-Repo: Funktionen, Zustände, Befehle,
  Fehler-IDs, Datenstrukturen und Grenzwerte – die Python-Implementierung richtet sich danach, nicht
  nach dem ST-Code (und umgekehrt).
- **Eine Definition der Schnittstellen-Datentypen** (z. B. eine YAML-/JSON-Datei), aus der die
  ST-Typen, die Python-Dataclasses und das OPC-UA-Informationsmodell erzeugt werden – ein kleiner,
  eigener Generator nur für die Datentypen, nicht für die Logik. So passen die Strukturen in allen
  drei Welten byte- und namensgleich zusammen.
- **Gemeinsame Testfälle** (Stil `SRCI_PY/docs/TestCases.md`, eindeutige IDs) gegen den
  SDK-Simulator, ausgeführt für TwinCAT, CODESYS und Python; ein Testfall gilt erst als erfüllt,
  wenn er in allen drei Welten grün ist.

Beide Implementierungen sind zyklisch aufgebaut (Schrittketten, keine blockierenden Aufrufe), wie
die SRCI-Bibliothek selbst – das hält sie vergleichbar. Das blockierende `execute()` der heutigen
HMI wird im Python-Integrator durch dieselben Schrittketten ersetzt.

## 5. Integrator-Schnittstelle (HMI ↔ Integrator)

Ein OPC-UA-Informationsmodell, in allen drei Welten gleich. Die Datentypen stammen aus der
gemeinsamen Definition (siehe 4.).

### 5.1 Befehle: Postfach statt Flanken

OPC UA tastet mit 50–100 ms ab – einzyklische Signale wie `Done` würden verloren gehen. Deshalb:

| Feld | Bedeutung |
|---|---|
| `Command.Id` | Befehl (Enum: Enable, Reset, Stop, Interrupt, Continue, JogStart, MoveToPoint, RunProgram, WriteTool, …) |
| `Command.Seq` | von der HMI hochgezählt: ein neuer Wert = neuer Auftrag |
| `Command.Par…` | Parameter des Befehls |
| `Reply.Seq` | vom Integrator gesetzt, wenn der Auftrag `Seq` fertig ist |
| `Reply.State` | Busy / Done / Error |
| `Reply.ErrorId` | SRCI-ErrorID bzw. Integrator-ErrorID |

**STOPP und Pause** haben ein eigenes Feld (Stop-Zähler), das nie hinter einem laufenden Auftrag
wartet.

### 5.2 Halten zum Fahren: Watchdog im Integrator

- Die HMI zählt solange eine Taste gedrückt ist alle 100 ms `Heartbeat` hoch.
- Der Integrator stoppt Tippen, Handführen und Bewegungen mit Halten, wenn sich `Heartbeat`
  länger als `HoldTimeout` (Standard 500 ms) nicht ändert – auch bei Verbindungsabbruch.
- Heute steckt dieser Watchdog in `robot.py` (`_watch`) – er **muss** in den Integrator, sonst
  stoppt der Roboter bei einer abgerissenen Verbindung nicht.

### 5.3 Status (zyklisch, als OPC-UA-Abo)

Phase, Aktivität, Antriebe ein, Fehler, Betriebsart, Override, Achs- und TCP-Position, aktives
Werkzeug/Frame, Unterbrochen / Sekundärsequenz / auf der Bahn, Haltepunkt, laufender Schritt und
Fortschritt, Robotordaten, `RCSupportedFunctions`, Meldungen (Ringpuffer mit Zeitstempel).
Entspricht dem heutigen `Snapshot` in `robot.py`.

### 5.4 Daten

Werkzeuge, Frames, Lasten, Grundstellung, Punkte und Programme liegen **im Integrator**
(SPS: Struktur-Arrays fester Größe; Python: dieselben Strukturen). Die HMI liest und schreibt sie
über die Schnittstelle. Größen (max. Punkte, Schritte, Programme) sind Konstanten des Integrators,
wie die Anwenderkonstanten des SIMATIC Robot Integrator.

### 5.5 Sonstiges

- **Versionierung:** `Interface.Version` (Major.Minor); die HMI prüft sie beim Verbinden.
- **Rechte:** OPC-UA-Benutzer, z. B. Beobachter (nur lesen), Bediener (fahren), Einrichter
  (Werkzeuge, Endschalter, Systemvariablen schreiben).
- **Mehrere Roboter:** ein Integrator-Objekt je Roboter im Informationsmodell.

## 6. Was heute in der HMI steckt und wohin es wandert

Stand Branch `feature/library-functions`.

| Heute (SRCI_PY_HMI) | Was | Wohin |
|---|---|---|
| `robot.py` `connect`, `_open`, `_start_position`, `_poll_position` | Verbindung, LifeSign, Position zyklisch oder per Polling | Integrator (Python: Transport; SPS: RobotTask-Konfiguration) |
| `robot.py` `set_enabled` | Einschalten mit GroupReset vorab (JAKA: 16#8C04) | Integrator |
| `robot.py` `stop`, `interrupt`, `resume`, `return_to_primary`, `program_paused` | STOPP, Pause, Fortsetzen, Rückkehr zur Bahn, Befehle während einer Pause | Integrator |
| `robot.py` `jog_press`, `_jog_off`, Warten auf RA-Sequenz IDLE (16#8F13) | Tippen | Integrator |
| `robot.py` `_watch`, `alive`, `release`, `_start_hold` | **Watchdog Halten zum Fahren** | Integrator (Pflicht, siehe 5.2) |
| `robot.py` `free_drive_press`, `_free_off` | Handführen | Integrator |
| `robot.py` `move_to`, `run_program`, `_run_action`, `_wait_motion`, `_motion_block`, `_absolute_block`, `_relative_block` | Punkt anfahren, Programmablauf mit Vorausschau (2 Bewegungen fürs Überschleifen), Warten, Ausgang, Eingang, Unterprogramm, Haltepunkt, Fortschritt | Integrator (Schrittkette) |
| `robot.py` `blending_results`, `BLENDING_NOT_SUPPORTED` | Merken, welche BlendingModes die RC ablehnt (16#8E05) | Integrator |
| `robot.py` `_free_config` | Roboter-Eigenheiten (JAKA: TurnMode / ConfigMode FREE) | Integrator, als Konfiguration je Roboter |
| `robot.py` `require`, `can`, `supported` | Prüfen gegen `RCSupportedFunctions` | Integrator (meldet Fähigkeiten weiter; die HMI blendet nur aus) |
| `robot.py` `read/write_tools/frames/loads`, `read_dynamics`, `write_*_dynamics`, `read/write_sw_limits`, `read_dh` | Daten der RC | Integrator |
| `robot.py` `read_io`, `write_output`, `_io_index`, `_output_block`, `read/write_registers` | E/A, Bitmaske, Register | Integrator |
| `robot.py` `read/write_system_variable` + `sysvars.py` | Systemvariablen, Standard-Parameterliste, 4-Byte-Umrechnung | Integrator (Liste + Umrechnung); die HMI behält nur die Texte |
| `robot.py` `forward/inverse_kinematics`, `calculate_tool/frame`, `shift_position`, `call_subprogram`, `set_operation_mode` | Berechnungen und Befehle der RC | Integrator (dünne Hülle) |
| `geometry.py` | Vermessen ohne CalculateTool/Frame (TCP-Ausgleichsrechnung, Frames aus Punkten, Euler R = Rz·Ry·Rx) | Integrator (ST und Python, als Ersatz wenn die RC nicht rechnet) |
| `model.py` | Punkte, Schritte, Programme, Validierung | Integrator (Strukturen + Prüfung); Dateiformat JSON bleibt als Import/Export in der HMI |
| `ui/pendant.py` Grundstellung (`settings.json`), `move_home` | Grundstellung | Integrator |
| `ui/pendant.py` `step_back` | Schritt zurück | Integrator (Befehl „vorheriger Bewegungsschritt“) |
| `ui/step_editor.py` `path_settings` | Ablauf-Einstellungen für alle Schritte | bleibt in der HMI (reine Bearbeitung der Daten) |
| `labels.json` (Namen von Werkzeugen, Frames, Lasten, Signalen) | Bezeichnungen | Integrator (gehören zur Anlage, nicht zum Bediengerät) |

## 7. Was in der HMI bleibt

- Seiten, Dialoge, Texte DE/EN, helles und dunkles Design.
- Halten zum Fahren auf **Bedienseite**: Herzschlag senden, solange eine Taste gedrückt ist.
- Ein- und Ausblenden nach den Fähigkeiten, die der Integrator meldet.
- Programme bearbeiten (Editor) und als JSON importieren / exportieren.
- **Ein** Backend: Integrator-Schnittstelle über OPC UA (plus Aufruf im selben Prozess für Tests).

Abnahme dafür: die HMI importiert nichts mehr aus `srci` (kein `srci.fb`, kein `srci.types`).

## 8. Umsetzung in Phasen

| Phase | Inhalt | Fertig, wenn |
|---|---|---|
| **0 Spezifikation** | Spezifikation (4.) und Informationsmodell (5.): Postfach, Herzschlag, Fehler-IDs, Version; Definition der Datentypen + Generator für ST, Python, OPC UA; erste Testfälle | Dokumente und erzeugte Typen in beiden Integrator-Repos |
| **1 HMI entkoppeln** | `RobotBackend`-Schnittstelle aus `RobotService` herausziehen, die heutige Implementierung dahinter (`SrciBackend`) | alle heutigen Tests grün, Oberfläche unverändert |
| **2 Integrator Core (ST)** | Verbinden, Ein/Aus, Quittieren, STOPP, Tippen mit Watchdog, Punkt anfahren, Position, Werkzeuge/Frames, Meldungen | läuft in TwinCAT und CODESYS gegen den SDK-Simulator (`python -m srci.sim.server`) |
| **3 Integrator Python** | Umfang von Phase 2 in Python, OPC-UA-Server (asyncua) | dieselben Testfälle grün wie in der SPS |
| **4 HMI auf die Schnittstelle** | `OpcUaBackend`; `SrciBackend` entfällt | Bewegen, Teachen, Werkzeuge, Koordinatensysteme über alle drei Welten |
| **5 Programme & Komfort** | Punkte/Programme im Integrator, Programmablauf, Pause/Rückkehr, Grundstellung, Vermessen, E/A, System | Funktionsumfang wie heute, ohne Logik in der HMI |

**Tests:** ein gemeinsamer Satz Testfälle (Stil `SRCI_PY/docs/TestCases.md`) gegen den
SDK-Simulator, ausgeführt für TwinCAT, CODESYS und Python.

## 9. Offene Entscheidungen

1. **Namen** der neuen Repositories.
2. **Format der Datentyp-Definition** (YAML, JSON, …) und wo der Generator liegt.
3. **OPC UA auch für Python** oder nur im selben Prozess? Empfehlung: beides, OPC UA als Normalfall.
4. **TwinCAT:** OPC UA (TF6100, Lizenz) oder zusätzlich ADS? Empfehlung: OPC UA, damit es ein Backend bleibt.
5. **Größen** im Integrator: Anzahl Punkte, Schritte, Programme, Meldungen.
6. **Programmablage in der SPS:** remanent / persistent oder Datei auf der SPS.
7. **Mehrere Roboter** je SPS / Integrator-Instanz von Anfang an?
8. **Rechte / Benutzer** für OPC UA.

## 10. Risiken

- **Aufwand:** Der größte Teil ist ST-Code im Integrator (Schrittketten für Programmablauf,
  Pause/Rückkehr, Vermessung). Die HMI wird dabei kleiner, nicht größer.
- **Zwei Implementierungen laufen auseinander:** Gegenmittel sind die verbindliche Spezifikation,
  die erzeugten Datentypen und die gemeinsamen Testfälle in allen drei Welten (siehe 4.).
- **Latenz:** OPC UA 50–100 ms – unkritisch, solange Watchdog und Zeitlogik im Integrator laufen.
- **Lizenz TwinCAT TF6100** für den OPC-UA-Server.
- **Übergang:** Bis Phase 4 laufen `SrciBackend` und Integrator parallel; Funktionen werden in der
  HMI nicht mehr erweitert, nur noch in den Integrator verschoben.
