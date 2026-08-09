# Repeater
Safety: unsafe

A cross-platform SSH tool to automate tasks on various VMs or machines. Repeater is written in C# built on .NET Core.

Repeater is a tool that uses SSH comms to run tasks or automation on virtual or static machine nodes. Repeater can be configured for individual or global credentials to log into a system. The configuration is in JSON format and a dry-run test can be used to test out output.

<h2 style="text-align: center;">** This project is still under development **</h2>


# Current development
**This project is still under development**

Repeater works, but is in current development. Code will change, files will change, and possibly some features will be removed or improved. However, I hope the tool is useful. Releases will be in the _release_ section (soon to come). You can build this utility with build files. 

**Requirements** 
This tool was written in _Visual Studio 2022 .NET Core 5.0_ minimum. Instructions on setting up .NET Core will come later for both Windows and Linux.

Repeater uses _NewtonSoft.JSON_ and _SSH.Net_ packages. The solution build will _restore_ the packages if they are not installed. 

```
build.cmd - build file to build Repeater on _Windows_. The build will produce a Linux,
Mac, and Windows single-file distribution for easy install.
```

```
build.sh - build file to build Repeater on _Linux_. The build will produce a Linux, 
Mac, and Windows single-file distribution for easy install.
```

**Development Notes**

Look under the source directory and you'll find the _Notes_ directory. A _dev-notes.md_ file is present to show development progression.

For configuration examples, look under the _Notes/Config_ directory. There's also global files to check out if you need automation to run on many machines with same tasks.

# How to use
No install needed as this is a portable tool. Copy the EXEcutable to a tool directory. The tool doesn't do much without a configuration file, and we will now describe it. 


## The config file...
Repeater's configuration is of JSON type. It can be configured to run global options or it could be used to run through many servers, performing operations.

The basics of the config file:

```json
{
  "AppConfig": 
    {
        "DefaultUserPassword": "saDFGrhwsETUEfdnsdgRTJ4yuesdHFgjeTDYKjsdrs65",
        "DryRun": "true",
        "DefaultPort": 22,    
        "GlobalLinuxCommandFile": ".\\AllLinuxCmdsToRun.txt",
        "GlobalWinCommandFile": ".\\AllWindowsCmdsToRun.txt"
    },
  "Servers": 
  [
    {
        "Name": "Windows-2019-Server",
        "ID": "dot3",
        "User": "chris",
        "Password": "PaSSw0Rd",        
        "Cmds": 
            [
                "This is a test to @reboot. If not, then oh well. ",
                "systeminfo > C:\\Users\\Public\\Downloads\\systeminfo.log",
                "@sysinfo",
                "dir C:\\Users\\Public\\Downloads",
                "@download C:\\Users\\Public\\Downloads\\systeminfo.log C:\\mnt\\DEMO-June16\\windows\\systeminfo-remote.log",
                "@upload C:\\Users\\Public\\Downloads\\file.log C:\\mnt\\DEMO-June16\\windows\\file2.log"
            ],      
        "IPAddress": "192.168.0.25"
    },
    {
        "Name": "A-Small-Mac-Mini",
        "ID": "IH8Apple",
        "IPAddress": "192.168.0.32",
        "Delay": "0",
        "User": "chris",
        "Password": "PaSSw0Rd",        
        "Cmds": 
            [
                "df -h",
                "ls -lisa",
                "ls -lisa"
            ],  
        "NoRepeat": "false",
        "Reboot": "false"
    }
  ]
}
```

### "AppConfig" section

The _AppConfig_ section contains Repeater's settings. They can also contain global configurations to run across the server configurations. This means if you have repeated
configurations under each server and you wish to use it globally, then this area will hold
those configurations. Below, are the key/values you can use in this section:

**DefaultUserPassword** - If you use a default user and password for all servers, then configure this by using repeater to encrypt your user and password for you by conjoining the user and password with a colon.
Type _repeater --encrypt  user:password_ and Repeater will return the encrypted password to use. 
If you don't want to store the credentials in the config file, you can pass the parameters _--cred {encrypted user/password}_ to Repeater at the command prompt.



**DryRun** _(true/false)_ If you wish to see a simulated run of Repeater, then this option enables that.

**DefaultPort** (integer) If all your servers have a default port, _generally "22"_, then set the default port. You don't need the Key/Value _Port_ under your server configurations.

**GlobalLinuxCommandFile**  _(Path to text file containing Linux OS commands)_
**GlobalWinCommandFile**  _(Path to text file containing Windows OS commands)_
If you want all your servers to run specific tasks predefined in a text file, you can set this option. Simply define OS  commands in your text file and Repeater will run each one sequentially. Note: Do not run graphic user interface applications as they may require user input. If this is the case, then Repeater may get stuck awaiting input.

```
See Example global commands file
```

Repeater contains custom commands you can run in your Global OS command text file. The commands start with an _@_ symbol.

These commands are listed below:

**systeminfo** - This command gets system information. You can pipe this to a text file or for output.

**reboot**  - you can reboot your server at ease.

**driveinfo** - Relays disc space inforamtion.

**upload**  _(souce local path , remote destination path)_ -  uploads a file to the server.

**download**  _(souce remote path , local destination path)_  - downloads a file to a local system

#### Example Global commands file
Here's an example global commands file to run on a Windows system:

[AppConfig]<BR>
"GlobalWinCommandFile": "C:\\temp\\apps\\repeater\\MyGlobalCommandsList.txt

```BAT
set A_VARIABLE=I_AM_A_VARIABLE
echo %A_VARIABLE%
wmic qfe list
@sysinfo
echo @echo off > c:\demo-test-batch.bat
echo wmic logicaldisk get DeviceID, FreeSpace, Size >> c:\demo-test-batch.bat
echo WE WILL NOW RUN BATCH WE HAVE CREATED
c:\demo-test-batch.bat
mkdir c:\temp
@upload C:/temp/TestSSH-Tool/getproductkey.ps1 c:/temp/getproductkey.ps1
powershell c:/temp/getproductkey.ps1
```

In this example you can see _@sysinfo_ and _@upload_ is being called inthe global commands list. These commands can be transferred to the _Cmds_ section of each server.

### "Servers" section
EAch server must be separated by  blocks{}. Repeater runs, contacting each server and processes commands either global commands file or a commands list. Once complete, Repeater checks to see if it needs to skip it next time, check its frequency, or if needs to reboot.

A typical server configuration appears like this:

```json
{
      "Name": "HomesoftServ",
      "ID": "Lev001",
      "IPAddress": "test.com",
      "Port": 22,
      "User": "user@user.com",
      "Password": "aNewPassWordT3st",
      "Cmds": [
        "dir",
        "@reboot",
        "dir /w /p"
      ],
      "Delay": "1",
      "NoRepeat": "false",
      "Reboot": "false"
}
```
    
**Name** (string - name of the server) This is the name of the server. 

**ID** - The ID of the server. This must be unique.

**IPAddress** - The IP address of the server.

**Port** - The port to configure SSH connections to the server.

**User** - user credential to use. _Use Repeater --encrypt user:password_ to encrypt.

**password** - the password to use for server.

**Cmds** [list of commands]

Example:

```
     "Cmds": 
     [
        "dir",
        "@reboot",
        "dir /w /p"
      ],
```
Commands are in a list type inside the JSON configuration. Each command is processed in a sequence. You can control the delay between commands by configuring the _Delay_ option below.
It is advised to not run UI type applications or applications that require immediate user input. This will force Repeater to remain at that process until removed. 

```
Note: To run commands on all servers, see the Global commands list file above. 
```

Repeater contains custom commands you can run. The commands start with an _@_ symbol. These commands such as @reboot or @upload provide extra features in Repeater to make your work flow faster. See the commands above for a full description.

**Delay** (integer seconds) This option allows you to run a delay between commands you call to the OS via global commands file or within each server configuration.

**NoRepeat** - Do not repeat the server during a cycle. When Repeater runs in a repeating cycle, or _monitor mode_ ,then the next cycle would skip this server configuration to process. 

```
Note: This option is currently not implemented
```

**Reboot** - reboots server after running processes and its configuration. The difference between the commands and the option is similar, but you don't have to include it in the commands. 




















