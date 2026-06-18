Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
' Resolve the app folder from this script's own location, so auto-start works
' wherever the repo sits (and whatever the user named the folder).
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set shortcut = WshShell.CreateShortcut(WshShell.SpecialFolders("Startup") & "\Meeting Recorder.lnk")
shortcut.TargetPath = appDir & "\.venv\Scripts\pythonw.exe"
shortcut.Arguments = "tray.py"
shortcut.WorkingDirectory = appDir
shortcut.Description = "Meeting Recorder - System Tray"
shortcut.Save
WScript.Echo "Startup shortcut created."
