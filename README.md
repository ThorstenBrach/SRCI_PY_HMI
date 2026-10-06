# SRCI_PY_HMI – teach pendant for setting up and teaching SRCI robots

A tablet-style web user interface (NiceGUI) on top of the Python client
[`srci`](https://github.com/ThorstenBrach/SRCI_CLIENT_PY) (SRCI_PY). It connects to the robot
through the PLC gateway, switches it on, jogs it, teaches points and runs programs made of them.

<p>
  <img src="docs/images/manual/03_jog.png" alt="Jog" width="49%">
  <img src="docs/images/manual/04_program.png" alt="Program" width="49%">
  <img src="docs/images/manual/13_io.png" alt="I/O" width="49%">
  <img src="docs/images/manual/11_measure_tool.png" alt="Measure a tool" width="49%">
</p>

```
Browser / tablet  --HTTP-->  srci-hmi (Python, NiceGUI)  --TCP-->  PLC gateway  --PROFINET-->  robot
                                     └─ or: SRCI SDK simulator (local, without a robot)
```

**Operating manual:** [docs/OPERATING_MANUAL.md](docs/OPERATING_MANUAL.md)

## Features

| Page | Content |
|---|---|
| **Connection** | Robot (IP / port / telegram length of the gateway) or SDK simulator, LifeSign timeout (100 / 250 / 500 / 1000 ms or free, remembered), robot on / off (acknowledges pending errors with GroupReset first), reset, speed override, robot data and **capabilities**: the functions the controller reports in `RCSupportedFunctions`. Functions it does not report are disabled in the user interface and never sent. Status tiles (drives, error, communication, sequence), external **operation mode** Automatic / T1 / T2 (SetOperationMode), **home position** (set, move to), **diagnostics** (on the path, secondary sequence, operating hours, last error IDs) |
| **Jog** | Jogging in joints, base or tool, continuous or in increments (0.1 / 1 / 10), jog speed. Choice of tool and frame; they are used for the TCP display, Cartesian jogging and teaching (a point remembers its tool and frame). Live position, "Teach point", **hand guiding** (FreeDrive, hold), **move to a target position**: enter joint or Cartesian values (Joint / PTP / LIN) |
| **Program** | Points (move to, teach again, edit, rename, delete) and sequence. Tapping a step opens the editor: motion type **LIN** (MoveLinearAbsolute), **PTP** (MoveDirectAbsolute, Cartesian target, joint interpolated), **Joint** (MoveAxesAbsolute, joint angles) or **CIRC** through a via point (MoveCircularAbsolute), each with exact stop or blending (modes of the spec, value before and – for "two radii" – after the point; modes the robot refused in this connection are marked), plus velocity, acceleration, deceleration and jerk in % or the default of the RC. Further step kinds: **relative** motion (MoveLinear/Direct/AxesRelative, in the tool or the frame), **wait**, **set output** (WriteDigitalOutputs), **wait for input** (ReadDigitalInputs, with timeout), **subprogram** (CallSubprogram) and **stop point**. Steps can be skipped and commented; **sequence settings** set blending and dynamics for all steps. Edit points numerically (with the forward / inverse kinematics of the RC) and **shift, mirror, rotate** them (ShiftPosition). Start, single step, **step back**, status line with progress, **pause / continue** and **return to path** (GroupInterrupt, GroupContinue, ReturnToPrimary), save and open as JSON |
| **Tools** | Read the tool table of the robot controller (ReadToolData) and write single tools (WriteToolData): X, Y, Z, Rx, Ry, Rz, load no., external TCP. Local labels like "Gripper" are stored in `programs/labels.json`. T0 (flange) is fixed. **Measure** with the RC (CalculateTool: 3, 4, 5, 6 points, 2 points + Z, ABC world, ABC 2 points); the wizard has its own jog keys, the robot is moved right in the dialog. If the robot controller does not report `CalculateTool` / `CalculateFrame` (profile Core, e.g. JAKA MiniCobo), the HMI calculates itself: tool 3 / 4 points and ABC world, frame 3, 4 and 1 point. Read and write **loads** (Read/WriteLoadData: mass, center of gravity, inertia) |
| **Frames** | Read and write frames (Read/WriteFrameData) with reference frame. "Take the actual TCP position" sets the origin of a frame to the TCP. F0 (base) is fixed. **Measure** with the RC (CalculateFrame: 3 points, 4 points with origin shift, 1 point) |
| **I/O** | Digital inputs and outputs as a grid of signals, read live (Read/WriteDigitalInputs/Outputs); tapping an output switches it. Local labels per signal. Read and write integer and real registers (Read/WriteIntegers, Read/WriteReals) |
| **System** | Default and reference dynamics (Read/WriteRobotDefault/ReferenceDynamics), software limits with bars and the actual joint position (Read/WriteRobotSWLimits, factory defaults), DH parameters, **system variables** with the standard parameter list of the specification or manufacturer parameters (Read/WriteSystemVariable), kinematics calculator (CalculateForward/InverseKinematic) |
| **Messages** | Messages of the robot controller with the time they were first seen, reset and the last error |

Always visible: the status ("Ready · On", "Moving", "Interrupted", "Fault" …), during a motion the
**Pause / Continue** key, and the red **STOP** key (GroupStop). Texts in German and English, light
and dark theme.

## Safety

- **Hold to run:** jogging, "Move to" and the program start move only while the key is held.
  The browser sends a heartbeat every 100 ms. If it is missing for 0.5 s, the robot service stops
  the motion. This also applies when the key is released, the tab is switched or the Wi-Fi drops.
- "Run without holding" can be switched on on the program page (only with a clear working area
  and the emergency stop within reach).
- SRCI is not a safety interface. Emergency stop, safeguards and safe speeds remain the task of the
  robot controller.
- By default the user interface can only be reached on the own PC (`127.0.0.1`). With
  `--host 0.0.0.0` it can be reached from a tablet as well – but then **everybody in the network
  who reaches the port can move the robot**. Use this only in an isolated cell network.

## Installation

```bat
cd D:\Projekte\SRCI\SRCI_PY_HMI
python -m venv .venv
.venv\Scripts\activate
pip install -e ..\SRCI_PY
pip install -e .[dev]
```

## Start

```bat
srci-hmi                                     :: http://127.0.0.1:8080, gateway 192.168.2.10:5000
srci-hmi --robot 192.168.2.10 --robot-port 5000 --length 256
srci-hmi --lifesign 500                      :: LifeSign timeout [ms] (else the one set last)
srci-hmi --simulator                         :: SDK simulator preselected (SRCI_SDK_SIM_LIB)
srci-hmi --log hmi.log                       :: log file with the system log of all function blocks
srci-hmi --host 0.0.0.0 --port 8080          :: reachable from a tablet (see Safety)
srci-hmi --native                            :: own window instead of the browser (pywebview)
```

`python -m srci_py_hmi` works the same way. Best start it in the folder `SRCI_PY_HMI`: programs
(`programs/`) and the browser settings (`.nicegui/`) are stored in the current folder.

Programs are JSON files in the folder `programs` (option `--programs`). They are readable and can
be versioned. Formats 1 and 2 (older versions) are still read. The home position is stored in
`programs/settings.json`, local labels (tools, frames, loads, signals) in `programs/labels.json`.

```json
{ "format": 3, "name": "Pallet",
  "points": [ { "name": "P1", "joints": [0, 30, 60, 0, 90, 0], "cartesian": [-316, -6, 208, 180, 0, 0], "tool": 0, "frame": 0, "note": "" } ],
  "steps":  [ { "point": "P1", "motion": "linear", "velocity": 50.0,
                "blending_mode": "MAX_CORNER_DEVIATION", "blending": 20.0, "blending_post": 0.0,
                "acceleration": -1.0, "deceleration": -1.0, "jerk": -1.0 },
              { "kind": "output", "signal": 3, "value": true, "note": "Close gripper" },
              { "kind": "wait_input", "signal": 5, "value": true, "timeout": 2.0 },
              { "kind": "wait", "duration": 0.5, "enabled": false } ] }
```

`motion`: `linear`, `ptp`, `joint` or `circ` (with `via`); dynamics in %, `-1` = default of the
robot controller. `kind` (missing for motions to points): `relative` (`offset`, `reference`,
`tool`, `frame`), `wait` (`duration` s), `output` / `wait_input` (`signal` = byte · 8 + bit,
`value`, `timeout`), `subprogram` (`job`, `data`), `halt`.

"Wait" waits in the HMI (not with WaitTime): this works with every robot controller, and STOP ends
it at once. Outputs, inputs, waits and subprograms run when the motions before them are done
(exact stop before).

## Operation in three steps

1. **Connection:** check robot mode and IP, tap "Connect", then "Switch robot on".
2. **Jog:** move the robot with the −/+ keys and tap "Teach point". P1, P2 … are created.
3. **Program:** tap ≡+ at a point to append it as a step. Tapping a step opens the editor (motion
   type, exact stop or blending, dynamics). "Start" (hold) runs the program; the number of a step
   selects the start step.

"+ Step" adds further step kinds (arc, relative, output, input, wait, subprogram, stop point).
While a program runs, **Pause** stops the robot; then it can be jogged away (jogging, hand
guiding), moved back to the interrupted path with **Return to path**, and the program goes on with
**Continue**. Details: [operating manual](docs/OPERATING_MANUAL.md).

## Structure

| File | Content |
|---|---|
| `src/srci_py_hmi/model.py` | points, steps, program, JSON (without robot and UI) |
| `src/srci_py_hmi/robot.py` | `RobotService`: connection, commands one after the other, STOP at once, jogging with watchdog, program run (two motions ahead for blending), tools / frames, checks against `RCSupportedFunctions` |
| `src/srci_py_hmi/app.py` | start, command line |
| `src/srci_py_hmi/ui/pendant.py` | NiceGUI page (one instance per browser tab, one robot for all tabs) |
| `src/srci_py_hmi/ui/jog_pad.py` | jog keys (jog page and dialogs) |
| `src/srci_py_hmi/ui/step_editor.py` | dialog "Edit step" (all step kinds), sequence settings |
| `src/srci_py_hmi/ui/coords.py` | pages "Tools" (with loads) and "Frames" |
| `src/srci_py_hmi/ui/calibrate.py` | wizards "Measure tool / frame" |
| `src/srci_py_hmi/ui/points.py` | edit point, shift / mirror / rotate |
| `src/srci_py_hmi/ui/io_page.py` | page "I/O" |
| `src/srci_py_hmi/ui/system_page.py` | page "System" |
| `src/srci_py_hmi/geometry.py` | measuring in the HMI (TCP least squares, frames from points), Euler angles as in the specification |
| `src/srci_py_hmi/sysvars.py` | standard parameter list of the system variables, conversion of the 4-byte values |
| `src/srci_py_hmi/ui/theme.py` | colours, CSS, JavaScript for hold to run |
| `src/srci_py_hmi/i18n.py` | texts DE / EN |

## Tests

```bat
pytest            :: model and geometry; robot service and UI against the SDK simulator if SRCI_SDK_SIM_LIB is set
ruff check . && mypy
```

The SRCI SDK is licensed and does not belong in this repository (see `.gitignore`).

## JAKA MiniCobo

Tested with a JAKA MiniCobo (controller 1.7.1, SRCI 1.1, profile Core only), see
`SRCI_PY/examples/jaka_minicobo`:

- LIN and PTP steps are sent with TurnMode FREE and ConfigMode FREE (the MiniCobo accepts TurnMode
  only as FREE, ConfigMode as SAME or FREE).
- Blending only with **MAX_CORNER_DEVIATION** (largest deviation from the corner in mm). It refuses
  other modes with `16#8E05`. The editor suggests the mode the robot accepted in the connection.
- LifeSign timeout at least 300 ms, default 500 ms. After a refused command the JAKA switches its
  drives off and sends no LifeSign for about 200 ms. "Switch robot on" acknowledges the error with
  GroupReset first (otherwise `16#8C04`).
- No CalculateTool / CalculateFrame: the HMI measures tools and frames itself.

## Roadmap

The comfort functions are planned to move from the HMI into a robot integrator for TwinCAT,
CODESYS and Python; the HMI then becomes a pure user interface over OPC UA:
[docs/PLAN_ROBOT_INTEGRATOR.md](docs/PLAN_ROBOT_INTEGRATOR.md) (in German).

## Changes

[CHANGELOG.md](CHANGELOG.md)
