# Change Log
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased]

### Added
 - Teach pendant for SRCI robots as web UI (NiceGUI) on top of SRCI_PY (`srci-client`):
   pages Connection, Jog, Program, Tools, Frames, Messages; German / English; light / dark theme
 - Connection to the robot behind the PLC gateway or to the SDK simulator; robot data,
   speed override, acknowledge (GroupReset), STOP (GroupStop) always visible
 - Hold-to-run for jogging, "move to point" and the program start (heartbeat of the browser,
   0.5 s watchdog in the service)
 - Jogging in joints, base or tool, continuous or in steps; tool and frame for the TCP display,
   the Cartesian jog and the teaching of points
 - Tool and frame tables of the robot controller: read and write (Read/WriteToolData,
   Read/WriteFrameData), local labels, frame origin from the current TCP
 - Program steps LIN (MoveLinearAbsolute), PTP (MoveDirectAbsolute) and Joint
   (MoveAxesAbsolute), each with exact stop or blending (all blending modes of the
   specification, value before and after the point) and velocity, acceleration, deceleration
   and jerk in % or the default of the RC; step editor; programs as JSON (format 2, format 1 is
   read)
 - Capabilities of the robot from `RCSupportedFunctions`: functions the RC does not report are
   disabled in the UI and never sent; blending modes the RC accepted or refused in the
   connection are marked
 - LifeSign timeout adjustable (presets 100 / 250 / 500 / 1000 ms or free, remembered,
   `--lifesign`), default 500 ms
 - Log file with the system log of all function blocks (`--log`)
 - Tests: model, robot service and UI (simulated browser) against the SDK simulator

### Changed
 - Renamed from SRCI Teach to SRCI_PY_HMI: distribution `srci-py-hmi`, package `srci_py_hmi`,
   command `srci-hmi`. The key file of the stored settings is taken over
   (`~/.srci_teach_secret` -> `~/.srci_py_hmi_secret`)
 - Configuration of the RobotTask via `program.ParCfg` (renamed in SRCI_PY)

### Fixed
 - "Switch on" acknowledges a pending error of the RC first (EnableRobot refused with 16#8C04)
 - Jog waits until the sequence of the RC is IDLE or INTERRUPTED (GroupJog refused with 16#8F13)
 - No position polling while another command runs; tools and frames are read in the background
   after connecting

### Tested with
 - SDK simulator (automated tests)
 - JAKA MiniCobo (controller 1.7.1, SRCI 1.1, profile Core): connect, switch on, jog.
   The robot accepts only MAX_CORNER_DEVIATION for blending and needs a LifeSign timeout of
   at least 300 ms
