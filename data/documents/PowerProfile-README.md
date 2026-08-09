# PowerProf: Windows Power States & RTC Wake Project

A compact C++ DLL plus reference test application for scheduling sleeps and timed wakes on Windows using RTC wake timers, with helpers for Wi‑Fi reconnect, sign‑on policy, logging/rotation, and light input simulation.

Back in 2003, I wrote an application that featured scheduling S3/S4 sleeps with RTC wake timers on Windows XP. For example, I'd let the application put the system to sleep when I left home, then it woke up when I returned back to work. I'd have all the applications ready for work and the system in full response at my ready. 

Over the years, I've revisited and refined the code to handle newer Windows versions, power states, and added features. This project packages that functionality into a reusable DLL with a test application. It took me about two months to revamp and document everything properly. So, now I am sharing all this with you. 

_Note:_ 

- This README document was created with the assistance of Chat Gippity 4o and Microsoft Copilot.
- All commenting artifacts are included. I believe a good developer or a person who tinkers with technology leaves breadcrumbs for others to follow.

---

> **Status**
> * S3 (Sleep) and S4 (Hibernate) are implemented.
> * Modern Standby (S0 Low Power Idle) is **not implemented** in this release; a best‑effort fallback is invoked by Windows if selected in **Auto** mode and supported by firmware.
> * Versioning is manual for now.

---

## Contents
- [Architecture](#architecture)
- [Build & Toolchain](#build--toolchain)
- [Quick Start](#quick-start)
- [Concepts: Windows Power States](#concepts-windows-power-states)
- [RTC Wake Timers: How this DLL Uses Them](#rtc-wake-timers-how-this-dll-uses-them)
- [API Reference](#api-reference)
  - [Initialization & Logging](#initialization--logging)
  - [Power Capabilities & Scheduling](#power-capabilities--scheduling)
  - [Wake Timers](#wake-timers)
  - [Sign‑On Options](#sign-on-options)
  - [Wi‑Fi Helpers](#wi-fi-helpers)
  - [Utility Functions](#utility-functions)
- [Usage Examples](#usage-examples)
- [Test Application](#test-application)
- [Operational Notes & Limitations](#operational-notes--limitations)
- [Versioning](#versioning)
- [FAQ / Troubleshooting](#faq--troubleshooting)

---

## Architecture
```
powerprof/              # DLL project
  power_prof.h          # Public API header
  powerprof.cpp         # Implementation
  Logger.h/.cpp         # Rotating file logger
  framework.h           # Windows/CRT includes & defines

powerprof-test-app/     # Console app consuming the DLL (uploaded separately)
readme-original.md      # Original notes and flow sketches
```

Key ideas:
- Query firmware/OS capabilities (S3, S4, RTC wake, Modern Standby), then choose a working mode.
- Convert local `SYSTEMTIME` to absolute UTC ticks; schedule two independent waitable timers: one that triggers an APC to enter sleep, another to signal wake.
- After wake, reset execution state, optionally simulate a bit of user activity, and (optionally) reconnect Wi‑Fi.

---

## Build & Toolchain
### Prereqs
- **Windows 10/11 x64**, Visual Studio 2022 (MSVC), Windows SDK.
- Optional: **GNU Make** (Win32 build of `make`) for simple targets.

### Build with `make`

 Install make: 
 1. https://gnuwin32.sourceforge.net/packages/make.htm
 2. Choose complete setup package installer.
 3. Add `C:\Program Files (x86)\GnuWin32\bin` to PATH
 4. Open dev tools prompt `C:\Program Files\Microsoft Visual Studio\2022\Enterprise\Common7\Tools\VsDevCmd.bat`

```bash
# in a VS 2022 Developer Command Prompt
make release        # x64-Release (default)
make build          # alias for x64-Release
make debug          # x64-Debug
make clean          # clean current CONFIG/PLATFORM
# full clean (both configs):
make clean CONFIG=Release PLATFORM=x64 && make clean CONFIG=Debug PLATFORM=x64
# dry-run clean
make -n delcache
```
> If you don’t have `make`, install GnuWin32’s package and add it to `PATH`, then launch `VsDevCmd.bat` from Visual Studio so MSVC/SDK are available.

### Building in Visual Studio
- Open the solution (or create a new one and add the `powerprof` project).
- Configurations: **Debug** and **Release**, platform **x64**.
- Language: C++17 or later recommended.

---

## Quick Start
```cpp
#include "power_prof.h"
using namespace powerprof;

int main() {
    // 1) Logging (optional but recommended)
    InitLogging(L"powerprof.log");
    SetLogRotationSize(10);     // MB
    SetMaxArchivedLogs(5);

    // 2) Inspect capabilities
    auto caps = GetSupportedPowerStates();

    // 3) Ensure wake timers & (optionally) hibernate
    SetWakeTimerStatus(1, /*both AC/DC*/ 2);
    EnsureHibernateEnabled(true);

    // 4) Choose times
    SYSTEMTIME sleepAt = {/* fill with local time */};
    SYSTEMTIME wakeAt  = {/* fill with local time */};

    // 5) Schedule
    if (!ScheduleSleepThenWake(sleepAt, wakeAt)) {
        LogError(L"Failed to schedule timers");
    }
}
```

---

## Concepts: Windows Power States
- **S3 — Sleep:** CPU off, DRAM self‑refresh; quick resume; requires power. Good match for short naps.
- **S4 — Hibernate:** Memory image written to `hiberfil.sys`; zero power; longer resume; requires hiberfile and firmware support.
- **Modern Standby (S0ix):** Newer, always‑on‑like model on supported hardware; *not implemented* in this DLL—Auto mode falls back to S4→S3 if Modern Standby isn’t available.

> The DLL’s **Auto** mode prefers **S4 → S3 → Modern**, based on detected support, and calls Windows to enter the selected state.

---

## RTC Wake Timers: How this DLL Uses Them
- Converts local `SYSTEMTIME` to a UTC `LARGE_INTEGER` tick value for each target time.
- Creates two waitable timers:
  - **Sleep timer** with an APC (`SleepAPC`) that elevates shutdown privilege and invokes the selected sleep state.
  - **Wake timer** marked as resume‑capable so the RTC alarm wakes the machine at the target time.
- After wake, resets `ES_SYSTEM_REQUIRED`/`ES_AWAYMODE_REQUIRED` (as applicable), optionally simulates input, and cleans up timers.

**Important:** Your active power plan’s **Wake Timers** policy must allow timers (Enabled or Important‑only, depending on scenario). If they’re disabled on battery/AC, scheduled sleeps/wakes will fail or be suppressed by the OS.

---

## API Reference
Below is the public surface exposed by `power_prof.h`. Functions are exported with `__declspec(dllexport)` from the DLL and imported by consumers.

### Initialization & Logging
- `InitLogging(const wchar_t* path)` – initialize file logging (rotating log writer).
- `SetLogRotationSize(std::size_t mb)` – max size before rotation.
- `SetMaxArchivedLogs(std::size_t count)` – number of rotated logs kept.
- `LogInfo/LogWarn/LogError/LogDebug(const wchar_t* fmt, ...)` – leveled logging.
- `Logger::Instance().EnableConsole(bool)` – toggle console echo.

### Power Capabilities & Scheduling
- `SupportedPowerStates GetSupportedPowerStates()` – returns flags for Modern Standby, S3, S4, and RTC wake presence.
- `bool CheckHibernateSupport()` – checks firmware + OS hibernate readiness.
- `bool EnsureHibernateEnabled(bool enable)` – toggles hibernate (creates/removes `hiberfil.sys`).
- `bool ScheduleSleepThenWake(const SYSTEMTIME& sleepLocal, const SYSTEMTIME& wakeLocal)` – schedules the two timers and blocks until wake.
- `VOID CALLBACK SleepAPC(...)` – APC invoked by the sleep timer; selects mode using `g_preferredMode` or Auto fallback.
- `bool SystemTimeToAbsolute(const SYSTEMTIME& local, LARGE_INTEGER& outUtc)` – helper conversion.

### Wake Timers
- `bool SetWakeTimerStatus(int option, int optionACDC)` – set plan policy for **Allow wake timers**:
  - `option`: 0=Disabled, 1=Enabled, 2=Important‑only
  - `optionACDC`: 0=AC only, 1=DC only, 2=Both
- `void GetWakeTimerStatus()` – print current AC/DC settings for wake timers.

### Sign‑On Options
- `bool SetSignOnOption(bool enable, int optionACDC)` – toggle **Require password on wake** via power policy GUIDs for AC/DC/both.
- `int  GetSignOnOption(int optionACDC)` – read current state.

### Wi‑Fi Helpers
- `std::tuple<std::wstring, bool> GetCurrentWiFiSSID()` – returns currently connected SSID and connection state.
- `void ReconnectWiFi(const std::wstring& ssid)` – attempts to reconnect to a previously‑profiled SSID using Native Wifi (WLAN API).

### Utility Functions
- `void JiggleMouse(int times=5, bool click=false, int pixels=50)` – small mouse jitters (optional click).
- `void UserActivitySimulation()` – keystroke wiggle as “last resort” activity.
- `void LogLastError(const wchar_t* context)` – dump `GetLastError()` info.
- `std::wstring FormatFileSize(ULONGLONG)` – helper for readable sizes.
- `void SendKeyString(const std::string& str, bool sendCtrlAlt=true, bool sendEnter=true)` – simulated typing with modifiers.

---

## Usage Examples
### 1) Inspect capabilities & schedule a nap
```cpp
InitLogging(L"nap.log");
SetWakeTimerStatus(1, 2);   // Enable on AC & DC

SYSTEMTIME sleepAt = {/* today 01:05 local */};
SYSTEMTIME wakeAt  = {/* today 01:10 local */};

EnsureHibernateEnabled(true); // if you intend to use S4

bool ok = ScheduleSleepThenWake(sleepAt, wakeAt);
if (!ok) LogError(L"ScheduleSleepThenWake failed");
```

### 2) Reconnect Wi‑Fi after wake
```cpp
auto [ssid, connected] = GetCurrentWiFiSSID();
if (!connected && !ssid.empty()) {
    ReconnectWiFi(ssid);
}
```

### 3) Disable sign‑on after wake on AC only
```cpp
// Choose AC only; leave battery as‑is
SetSignOnOption(/*enable=*/false, /*ACDC=*/1);
```

---

## Test Application
A simple console program demonstrates argument parsing, capability checks, wake‑timer setup, scheduling, and optional Wi‑Fi reconnect.

### CLI
```
TTimeObject.exe --mode=<auto|modern|s3|s4> --test           (sleep now, wake in 60s)
TTimeObject.exe --mode=<auto|modern|s3|s4> <start> <end>    (YYYY-MM-DD_HH:MM)
TTimeObject.exe -h | --help                                 (show help)
TTimeObject.exe -d | --dump                                 (dump system power capabilities)
TTimeObject.exe -n | --hibernateoff                         (turn OFF hibernate S4)
TTimeObject.exe -o | --hibernateon                          (turn ON hibernate S4)
TTimeObject.exe -2 | --acimportantwaketimersonly            (AC: Important wake timers only)
TTimeObject.exe -1 | --acwaketimerson                       (AC: Enable wake timers)
TTimeObject.exe -e | --showsignon                           (show sign‑on option)
TTimeObject.exe -s | --enablesignon                         (enable sign‑on on AC)
TTimeObject.exe -q | --disablesignon                        (disable sign‑on on AC)
TTimeObject.exe -t | --enablesignondc                       (enable sign‑on on DC)
TTimeObject.exe -u | --disablesignondc                      (disable sign‑on on DC)
```

**Modes**
- `auto` – pick best available (S4→S3→Modern)
- `modern` – Modern Standby (S0 idle) *(not implemented; OS may handle)*
- `s3` – Sleep (suspend to RAM)
- `s4` – Hibernate (suspend to disk)

**Examples**
```
# 5‑minute nap in S3
powerprof-test-app.exe --mode=s3 2025-05-24_00:15 2025-05-24_00:20

# Immediate sleep; wake in 60s
powerprof-test-app.exe --mode=auto --test
```

### Flow

#### `Typical flow (using example application):`

```
+--------------------------+
|      Application Start        |
+------------+-------------+
             |
             v
+--------------------------+
|       InitLogging()             |
+------------+-------------+
             |
             v
+--------------------------+
|      Argument Parsing      |
|       (ParseModeCmd)      |
+------------+-------------+
             |
             v
+------------------------------+
| GetSupportedPowerStates()|
+------------+----------------+
             |
             v
+----------------------------+
|   Check Power Support      |
| (S3, S4, Modern Standby)  |
+------------+---------------+
             |
             v
+--------------------------+
|   SetWakeTimerStatus()   |
+------------+-------------+
             |
             v
+-----------------------------+
| ScheduleSleepThenWake()  |
+------------+----------------+
             |
             v
+-------------------------------+
|        Sleep (S3)                        |
| (Scheduled by SYSTEMTIME) |
+------------+-----------------+
             |
             v
+--------------------------+
|        Wake Up                   |
+------------+-------------+
             |
             v
+--------------------------+
|      ReconnectWiFi()         |
+------------+-------------+
             |
             v
+--------------------------+
|      Logging Completion  |
|          (LogInfo)                 |
+--------------------------+
             |
             v
+--------------------------+
|        Application              |
|          End                        |
+--------------------------+
```

---

## Operational Notes & Limitations
- **Modern Standby**: not implemented; Auto mode prefers S4 → S3 and only attempts Modern when supported.
- **Wake Timers policy** must allow timers for the power source you’re on; otherwise the OS can suppress your alarms.
- **Hibernate** requires *both* firmware support **and** a present `hiberfil.sys` file.
- **Wi‑Fi reconnect** expects the target SSID to be previously profiled on the machine (credentials stored by Windows).
- **Sign‑on policy** changes may be blocked by org policy; use with care.
- **User input simulation** is intentionally minimal and should not be relied on for kiosk/interactive automation.

---

## C# P/Invoke quick‑start
You can call the DLL directly from .NET (C#) using `DllImport`. The DLL uses wide strings and `__declspec(dllexport)`, so specify `CharSet.Unicode`.

```csharp
using System;
using System.Runtime.InteropServices;

internal static class PowerProf
{
    private const string Dll = "powerprof.dll";

    public enum SleepMode { Auto = 0, Modern = 1, S3 = 2, S4 = 3 }

    [StructLayout(LayoutKind.Sequential)]
    public struct SYSTEMTIME
    {
        public ushort wYear, wMonth, wDayOfWeek, wDay, wHour, wMinute, wSecond, wMilliseconds;
    }

    [DllImport(Dll, CharSet = CharSet.Unicode, ExactSpelling = true)]
    public static extern void InitLogging(string path);

    [DllImport(Dll, ExactSpelling = true)]
    public static extern void SetLogRotationSize(UIntPtr mb);

    [DllImport(Dll, ExactSpelling = true)]
    public static extern void SetMaxArchivedLogs(UIntPtr count);

    [DllImport(Dll, CharSet = CharSet.Unicode, ExactSpelling = true)]
    public static extern void LogInfo(string fmt);

    [DllImport(Dll, ExactSpelling = true)]
    public static extern bool EnsureHibernateEnabled(bool enable);

    [DllImport(Dll, ExactSpelling = true)]
    public static extern bool CheckHibernateSupport();

    [DllImport(Dll, ExactSpelling = true)]
    public static extern int GetSignOnOption(int optionACDC);

    [DllImport(Dll, ExactSpelling = true)]
    public static extern bool SetSignOnOption(bool enable, int optionACDC);

    [DllImport(Dll, ExactSpelling = true)]
    public static extern bool SetWakeTimerStatus(int option, int optionACDC);

    [DllImport(Dll, ExactSpelling = true, EntryPoint = "ScheduleSleepThenWake")]
    [return: MarshalAs(UnmanagedType.I1)]
    public static extern bool ScheduleSleepThenWake(ref SYSTEMTIME sleepAt, ref SYSTEMTIME wakeAt);
}
```

**Minimal C# usage**
```csharp
var log = System.IO.Path.Combine(AppContext.BaseDirectory, "nap.log");
PowerProf.InitLogging(log);
PowerProf.SetLogRotationSize((UIntPtr)10);   // MB
PowerProf.SetMaxArchivedLogs((UIntPtr)5);

var now = DateTime.Now;
var sleep = new PowerProf.SYSTEMTIME { wYear=(ushort)now.Year, wMonth=(ushort)now.Month, wDay=(ushort)now.Day, wHour=(ushort)now.Hour, wMinute=(ushort)now.Minute };
var wake  = new PowerProf.SYSTEMTIME { wYear=(ushort)now.Year, wMonth=(ushort)now.Month, wDay=(ushort)now.Day, wHour=(ushort)now.AddMinutes(5).Hour, wMinute=(ushort)now.AddMinutes(5).Minute };

PowerProf.EnsureHibernateEnabled(true);
PowerProf.SetWakeTimerStatus(1, 2); // Enable wake timers on AC & DC

if(!PowerProf.ScheduleSleepThenWake(ref sleep, ref wake))
    Console.Error.WriteLine("Failed to schedule timers");
```

> Notes: `bool` return values from native code are marshalled as 4‑byte `int` by default; use `[return: MarshalAs(UnmanagedType.I1)]` where needed. Wide strings are Unicode. The `SYSTEMTIME` definition matches Win32.

---

## Scenarios
**1) 10‑minute maintenance nap (S3)**
- Enable wake timers on both AC/DC.
- Sleep in 2 minutes; wake 8 minutes later to resume tasks.

**2) Overnight hibernate (S4) with morning wake**
- Ensure hibernate is enabled and supported.
- Schedule `sleep=23:30`, `wake=07:00`.

**3) Battery‑preserving travel mode**
- On DC, keep sign‑on required; on AC at destination, disable sign‑on to auto‑resume into a kiosk app.

**4) Wi‑Fi resiliency after wake**
- On resume, attempt reconnect to the last known SSID (saved profile required).

**5) Test run / smoke check**
- Use `--test` to verify timers, logging, and policy tweaks without picking date math.

---

## Troubleshooting Matrix
| Symptom | Likely Cause | Fix |
|---|---|---|
| Sleep didn’t happen | Wake time ≤ sleep time; policy blocking suspend | Verify timestamps; enable wake timers for the active source; check logs for `Invalid SYSTEMTIME` or `Wake time <= sleep time`. |
| Didn’t wake | Wake timers disabled for current power source; firmware doesn’t support RTC alarm | Enable wake timers for AC/DC; check `--dump` for `rtcWake=Yes`; some desktops disable RTC in BIOS/UEFI. |
| S4 unavailable | `hiberfil.sys` missing; firmware/OS policy disables hibernate | Call `EnsureHibernateEnabled(true)`; rerun `--dump`. |
| Modern mode does nothing | Modern Standby not implemented here | Use `--mode=s4` or `--mode=s3`, or `auto` for fallback. |
| Wi‑Fi didn’t reconnect | SSID profile not present; WLAN service disabled | Ensure network is saved; `ReconnectWiFi` depends on existing profile and `WlanConnect`. |
| Password prompt on wake when disabled | Org policy overrides console‑lock setting | Use `--showsignon` to inspect; AC/DC may be enforced by policy. |
| “Failed to create timers” | Insufficient privileges / handle creation failed | Run elevated; ensure security software isn’t blocking `CreateWaitableTimer`. |
| “SetWaitableTimer” error in logs | Invalid times or resume privilege not granted | Confirm `SYSTEMTIME` is valid local time; OS converts to UTC internally; ensure process token has shutdown privilege (Sleep APC enables it).

---

## Versioning
Versioning is manual for now (see project `Version/CustomProductVersionInfo.ver`). Add your preferred scheme when you automate releases.

- Semantic version is stored in each project under `Version/CustomProductVersionInfo.ver`.
- No automation yet; update manually as part of your release process.

---

## FAQ / Troubleshooting
**Sleep didn’t happen or didn’t wake.**
- Check wake timers policy for the current power source (AC/DC). Ensure `Enabled`.
- Verify wake time is *after* the sleep time and both are valid local times.
- Verify RTC wake support in capabilities; some desktops disable it in firmware.

**Hibernate not available.**
- Firmware may disable S4, or `hiberfil.sys` may be missing/disabled. Use `EnsureHibernateEnabled(true)` and recheck.

**Wi‑Fi didn’t reconnect.**
- Ensure the SSID has a saved profile on the machine. The helper uses `WlanConnect` with `wlan_connection_mode_profile`.

**I don’t want to require a password after wake on AC.**
- Use `SetSignOnOption(false, 1)`.

---

## License
*MIT* - use it freely, modify, distribute, etc. Attribution appreciated but not required.


