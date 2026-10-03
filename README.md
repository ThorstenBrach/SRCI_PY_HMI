# SRCI Teach – Bedienoberfläche zum Teachen von SRCI-Robotern

Eine Weboberfläche im Stil eines Tablets (NiceGUI) auf Basis des Python-Clients
[`srci`](../SRCI_PY). Man verbindet sich damit über das SPS-Gateway mit dem Roboter, schaltet ihn ein,
verfährt ihn per Tippbetrieb, teacht Punkte und fährt daraus Programme ab.

```
Browser / Tablet  --HTTP-->  srci-teach (Python, NiceGUI)  --TCP-->  SPS-Gateway  --PROFINET-->  Roboter
                                     └─ oder: SRCI-SDK-Simulator (lokal, ohne Roboter)
```

## Funktionen

| Seite | Inhalt |
|---|---|
| **Verbindung** | Roboter (IP/Port/Telegrammlänge des Gateways) oder SDK-Simulator, Roboter ein/aus, Quittieren (GroupReset), Geschwindigkeits-Override, Roboterdaten |
| **Bewegen** | Tippen in Achsen, Basis oder Werkzeug, stufenlos oder in Schritten (0,1 / 1 / 10), Tippgeschwindigkeit, Live-Position (Achsen und TCP), „Punkt teachen“ |
| **Programm** | Punkte (anfahren, neu teachen, umbenennen, löschen), Ablauf aus PTP-/LIN-Schritten mit Geschwindigkeit und Überschleifen, Start, Einzelschritt, Sichern und Öffnen als JSON |
| **Meldungen** | Meldungen der Robotersteuerung und der letzte Fehler |

Immer sichtbar: der Status („Bereit · Ein“, „Fährt“, „Störung“ …) und die rote **STOPP**-Taste
(GroupStop). Texte auf Deutsch und Englisch, helles und dunkles Design.

## Sicherheit

- **Halten zum Fahren:** Tippen, „Anfahren“ und der Programmstart fahren nur, solange die Taste
  gedrückt ist. Der Browser schickt dabei alle 100 ms ein Lebenszeichen. Fehlt es 0,5 s lang,
  stoppt der Robot-Service die Bewegung. Das greift auch, wenn man loslässt, den Tab wechselt
  oder das WLAN abbricht.
- „Ohne Halten fahren“ lässt sich auf der Programmseite einschalten (nur mit freiem
  Arbeitsraum und Not-Halt in Reichweite).
- SRCI ist keine Sicherheitsschnittstelle. Not-Halt, Schutzeinrichtungen und sichere
  Geschwindigkeiten bleiben Aufgabe der Robotersteuerung.
- Standardmäßig ist die Oberfläche nur auf dem eigenen PC erreichbar (`127.0.0.1`). Mit
  `--host 0.0.0.0` erreicht man sie auch vom Tablet aus. Dann kann aber **jeder im Netz, der den
  Port erreicht, den Roboter bewegen**. Das also nur in einem abgeschotteten Zellennetz verwenden.

## Installation

```bat
cd D:\Projekte\SRCI\SRCI_TEACH
python -m venv .venv
.venv\Scripts\activate
pip install -e ..\SRCI_PY
pip install -e .[dev]
```

## Start

```bat
srci-teach                                   :: http://127.0.0.1:8080, Gateway 192.168.2.10:5000
srci-teach --robot 192.168.2.10 --robot-port 5000 --length 256
srci-teach --simulator                       :: SDK-Simulator vorausgewählt (SRCI_SDK_SIM_LIB)
srci-teach --host 0.0.0.0 --port 8080        :: vom Tablet erreichbar (siehe Sicherheit)
srci-teach --native                          :: eigenes Fenster statt Browser (pywebview)
```

Die Programme liegen als JSON im Ordner `programs` (Option `--programs`). Sie sind lesbar
und lassen sich versionieren:

```json
{ "format": 1, "name": "Palette",
  "points": [ { "name": "P1", "joints": [0, 30, 60, 0, 90, 0], "cartesian": [-316, -6, 208, 180, 0, 0], "tool": 0, "frame": 0, "note": "" } ],
  "steps":  [ { "point": "P1", "motion": "joint", "velocity": 20.0, "blending": 0.0 } ] }
```

## Bedienung in drei Schritten

1. **Verbindung:** Robotermodus und IP prüfen, „Verbinden“ tippen, dann „Roboter einschalten“.
2. **Bewegen:** Roboter mit den −/+-Tasten verfahren und „Punkt teachen“ tippen. P1, P2 …
   werden angelegt.
3. **Programm:** Bei einem Punkt auf ▸≡ tippen, um ihn als Schritt anzuhängen. Auf PTP/LIN
   tippen, um die Bewegungsart zu wechseln, und bei Bedarf Geschwindigkeit und Überschleifen
   setzen. Mit „Start“ (gedrückt halten) fährt man das Programm ab, mit der Nummer eines Schritts
   wählt man den Startschritt.

## Aufbau

| Datei | Inhalt |
|---|---|
| `src/srci_teach/model.py` | Punkte, Schritte, Programm, JSON (ohne Roboter und UI) |
| `src/srci_teach/robot.py` | `RobotService`: Verbindung, Befehle nacheinander, STOPP sofort, Tippen mit Watchdog, Programmablauf (zwei Bewegungen im Voraus für Überschleifen) |
| `src/srci_teach/ui/pendant.py` | NiceGUI-Seite (eine Instanz pro Browser-Tab, ein Roboter für alle Tabs) |
| `src/srci_teach/ui/theme.py` | Farben, CSS, JavaScript für „Halten zum Fahren“ |
| `src/srci_teach/i18n.py` | Texte DE/EN |

## Tests

```bat
pytest                                    :: Modell; Robot-Service gegen den SDK-Simulator, wenn SRCI_SDK_SIM_LIB gesetzt ist
```

Das SRCI SDK ist lizenziert und gehört nicht in dieses Repository (siehe `.gitignore`).

## JAKA MiniCobo

Lineare Schritte werden mit TurnMode FREE und ConfigMode FREE gesendet, die einzige Kombination,
die der MiniCobo annimmt (siehe `SRCI_PY/examples/jaka_minicobo`). Überschleifen
(CORNER_DISTANCE) lehnt er ab (`16#8E05`). Dort also Überschleifen 0 = Genauhalt verwenden.
