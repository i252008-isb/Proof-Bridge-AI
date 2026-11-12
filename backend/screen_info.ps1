Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
Write-Output ("Primary screen: " + $b.Width + "x" + $b.Height)
Write-Output "--- windows ---"
Get-Process | Where-Object { $_.MainWindowTitle -ne '' } | Select-Object ProcessName, Id, MainWindowTitle | Format-Table -AutoSize | Out-String -Width 220
