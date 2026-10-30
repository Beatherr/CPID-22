Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appFolder = fso.GetParentFolderName(WScript.ScriptFullName)
appData = shell.ExpandEnvironmentStrings("%APPDATA%")
stateFolder = fso.BuildPath(appData, "PCActivityMonitor")
launcherLog = fso.BuildPath(stateFolder, "startup_launcher.log")
BaslangicGunluguneYaz "Başlangıç kısayolu çalıştı."

pythonwPathFile = fso.BuildPath(stateFolder, "pythonw_path.txt")
If Not fso.FileExists(pythonwPathFile) Then
    BaslangicGunluguneYaz "Python çalışma zamanı yolu bulunamadı: " & pythonwPathFile
    WScript.Quit 1
End If

On Error Resume Next
Set pythonwFile = fso.OpenTextFile(pythonwPathFile, 1, False, -1)
If Err.Number <> 0 Then
    errorMessage = Err.Description
    Err.Clear
    On Error GoTo 0
    BaslangicGunluguneYaz "Python çalışma zamanı yolu dosyası açılamadı: " & errorMessage
    WScript.Quit 1
End If
pythonw = Trim(pythonwFile.ReadAll)
pythonwFile.Close
If Err.Number <> 0 Then
    errorMessage = Err.Description
    Err.Clear
    On Error GoTo 0
    BaslangicGunluguneYaz "Python çalışma zamanı yolu dosyası okunamadı: " & errorMessage
    WScript.Quit 1
End If
On Error GoTo 0

If Not fso.FileExists(pythonw) Then
    BaslangicGunluguneYaz "Yapılandırılmış pythonw.exe bulunamadı: " & pythonw
    WScript.Quit 1
End If

shell.CurrentDirectory = appFolder
configPath = fso.BuildPath(stateFolder, "config.json")
If Not fso.FileExists(configPath) Then
    BaslangicGunluguneYaz "Yapılandırma dosyası bulunamadı: " & configPath
    WScript.Quit 1
End If

BaslangicGunluguneYaz "Hizmetleri başlatmadan önce 20 saniye bekleniyor."
WScript.Sleep 20000
servicesPath = fso.BuildPath(appFolder, "start_services.py")
On Error Resume Next
shell.Run """" & pythonw & """ """ & servicesPath & """", 0, False
If Err.Number <> 0 Then
    errorMessage = Err.Description
    Err.Clear
    On Error GoTo 0
    BaslangicGunluguneYaz "start_services.py başlatılamadı: " & errorMessage
    WScript.Quit 1
End If
On Error GoTo 0
BaslangicGunluguneYaz "start_services.py çalıştırma isteği gönderildi: " & servicesPath

Sub BaslangicGunluguneYaz(message)
    On Error Resume Next
    Set logFile = fso.OpenTextFile(launcherLog, 8, True, -1)
    If Err.Number = 0 Then
        logFile.WriteLine Now & " " & message
        logFile.Close
    End If
    Err.Clear
    On Error GoTo 0
End Sub
