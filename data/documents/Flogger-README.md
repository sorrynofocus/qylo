# flogger
flogger is a fluffy-weight logger for your applications.  Extreme ease of use and setup. Have a wonderful and erotic day!

flogger supports:

* Enabling/disabling logs - _stop/start logs anytime in code._
* Log difficulty levels - _debug, info, etc._
* Log with Richedit UI, files, or both - _use a Richedit UI control to obtain log or a file. If you want both, then hey... have your cake!_ 
* Date/Time Stamps - _with message separation so lines won't bunch up, confusing others._
* Log data - _send logs by simple strings or by a collection of strings... Sting!_
* Plug and Perk - _easy to plug into your code_

***

**To use flogger, follow the steps below. Reading time is /seriously/ less than five minutes.**

Begin by setting the flogger object instance:

```
ILogger.Flogger Logger = new ILogger.Flogger();
```

Set the logfile and disable it (we don't want logging to start yet)

```
Logger.LogFile = "c:\\temp\\mylogfile.txt";
Logger.EnableLogger = false;

//Enable Date/Time stamps - true
Logger.EnableDTStamps = true;
```

**IF** you want logging viewable in your UI: throw up a RichEditText, attach it to flogger, and enable it. 

_In the following exhibit, we plopped a RichEditText control onto a WinForm, naming it "richTextBoxLog"_

```
Logger.LogRichTextControl = richTextBoxLog;
Logger.EnableUILogging = true;
```

To log, you can send a collection of strings, or a simple one.

_The whole Micheal Bolton Collection example (OfficeSpace ref):_

```
 List<string> LogMesg = new List<string>
                        (
                            new string[]
                                {
                                    "Example 1",
                                    "Example 2",
                                    "Examepl 3"
                                }
                        );

 Logger.LogInfo (LogMesg);
```

_Or send a simple string:_

```
Logger.LogInfo ("Logging this to the logger);
```

With above example, all logging will log to the UI while the log file is off.

To _start logging_ in file, simply _enable_ the logger:

```
Logger.EnableLogger = false;
```

The same can be applied for the UI, you can turn it off.
