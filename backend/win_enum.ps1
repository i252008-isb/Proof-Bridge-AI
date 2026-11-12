Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
  public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int i);
  public struct RECT { public int L, T, R, B; }
}
"@
$found = @()
[W]::EnumWindows({ param($h, $l)
  $t = New-Object System.Text.StringBuilder 256
  [void][W]::GetWindowTextW($h, $t, 256)
  $c = New-Object System.Text.StringBuilder 256
  [void][W]::GetClassNameW($h, $c, 256)
  if ($t.ToString() -match 'ProofBridge|proofbridge') {
    $r = New-Object W+RECT
    [void][W]::GetWindowRect($h, [ref]$r)
    $ex = [W]::GetWindowLong($h, -20) -band 0x00000008
    $script:found += ('HWND={0} visible={1} iconic={2} topmost={3} rect=({4},{5},{6},{7}) class={8} title={9}' -f $h, [W]::IsWindowVisible($h), [W]::IsIconic($h), $ex, $r.L, $r.T, $r.R, $r.B, $c.ToString(), $t.ToString())
  }
  return $true
}, [IntPtr]::Zero) | Out-Null
$found
