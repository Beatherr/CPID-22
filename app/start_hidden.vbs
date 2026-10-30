Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appFolder = fso.GetParentFolderName(WScript.ScriptFullName)
appData = shell.ExpandEnvironmentStrings("%APPDATA%")
stateFolder = fso.BuildPath(appData, "PCActivityMonitor")
launcherLog = fso.BuildPath(stateFolder, "startup_launcher.log")
LogStartup "Startup shortcut ran."

pythonwPathFile = fso.BuildPath(stateFolder, "pythonw_path.txt")
If Not fso.FileExists(pythonwPathFile) Then
    LogStartup "Python runtime path file was not found: " & pythonwPathFile
    WScript.Quit 1
End If

On Error Resume Next
Set pythonwFile = fso.OpenTextFile(pythonwPathFile, 1, False, -1)
If Err.Number <> 0 Then
    errorMessage = Err.Description
    Err.Clear
    On Error GoTo 0
    LogStartup "Could not open the Python runtime path file: " & errorMessage
    WScript.Quit 1
End If
pythonw = Trim(pythonwFile.ReadAll)
pythonwFile.Close
If Err.Number <> 0 Then
    errorMessage = Err.Description
    Err.Clear
    On Error GoTo 0
    LogStartup "Could not read the Python runtime path file: " & errorMessage
    WScript.Quit 1
End If
On Error GoTo 0

If Not fso.FileExists(pythonw) Then
    LogStartup "Configured pythonw.exe was not found: " & pythonw
    WScript.Quit 1
End If

shell.CurrentDirectory = appFolder
configPath = fso.BuildPath(stateFolder, "config.json")
If Not fso.FileExists(configPath) Then
    LogStartup "Configuration file was not found: " & configPath
    WScript.Quit 1
End If

LogStartup "Waiting 20 seconds before starting services."
WScript.Sleep 20000
servicesPath = fso.BuildPath(appFolder, "start_services.py")
On Error Resume Next
shell.Run """" & pythonw & """ """ & servicesPath & """", 0, False
If Err.Number <> 0 Then
    errorMessage = Err.Description
    Err.Clear
    On Error GoTo 0
    LogStartup "Could not launch start_services.py: " & errorMessage
    WScript.Quit 1
End If
On Error GoTo 0
LogStartup "Requested start_services.py to run: " & servicesPath

Sub LogStartup(message)
    On Error Resume Next
    Set logFile = fso.OpenTextFile(launcherLog, 8, True, -1)
    If Err.Number = 0 Then
        logFile.WriteLine Now & " " & message
        logFile.Close
    End If
    Err.Clear
    On Error GoTo 0
End Sub
