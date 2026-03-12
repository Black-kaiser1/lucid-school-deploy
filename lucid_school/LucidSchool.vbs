' LucidSchool.vbs
' Double-click this file to launch Lucid School with NO console window.
' Place this file in the same folder as launch_desktop.py

Dim WShell, ScriptDir, PyPath, Cmd
Set WShell   = CreateObject("WScript.Shell")
ScriptDir    = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Try pythonw first (no console), fall back to python
PyPath = "pythonw"
Cmd    = PyPath & " """ & ScriptDir & "\launch_desktop.py"""

' Run silently (0 = hidden window)
WShell.Run Cmd, 0, False

Set WShell = Nothing
