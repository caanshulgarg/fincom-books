<#
.SYNOPSIS
    Builds a standalone installer / distribution package for FinCom Books.
.DESCRIPTION
    Packages all required application files, assets, runtime structure, shortcuts,
    and uninstaller for FinCom Books into a standalone Windows installer (.exe).
.PARAMETER OutputDir
    Destination directory for the packaged installer build. Default is 'dist'.
.PARAMETER OutputExe
    Name of the final installer executable. Default is 'FinComBooksSetup.exe'.
.PARAMETER SkipEmbed
    Skip embedding the Python runtime directory.
#>

[CmdletBinding()]
param(
    [string]$OutputDir = "dist",
    [string]$OutputExe = "FinComBooksSetup.exe",
    [switch]$SkipEmbed
)

$ErrorActionPreference = "Stop"

$AppRoot = $PSScriptRoot
if (-not $AppRoot) { $AppRoot = (Get-Location).Path }

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " FinCom Books - Standalone Installer Packaging Tool" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Source Directory: $AppRoot"
Write-Host "Output Directory: $OutputDir"

# 1. Verify Core Application Files
$CoreFiles = @(
    "app_server.py",
    "books.py",
    "billing_rules.py",
    "interchange.py",
    "index.html",
    "fidelity.css",
    "workflows.js",
    "voucher_logic.js",
    "lookup_context.js",
    "print_view.js",
    "date_picker.js",
    "Launch.ps1",
    "Launch.vbs",
    "logo.png",
    "favicon.ico",
    "app.ico",
    "manifest.json",
    "version.json",
    "LICENSE"
)

Write-Host "`nVerifying core application assets..." -ForegroundColor Yellow
foreach ($file in $CoreFiles) {
    $fullPath = Join-Path $AppRoot $file
    if (-not (Test-Path $fullPath)) {
        throw "Missing required core asset: $file at $fullPath"
    }
    Write-Host "  [OK] $file" -ForegroundColor Green
}

# 2. Prepare Packaging Directory
$DistPath = Join-Path $AppRoot $OutputDir
$AppStage = Join-Path $DistPath "app"

if (Test-Path $DistPath) {
    Write-Host "`nCleaning existing dist folder: $DistPath" -ForegroundColor Gray
    Remove-Item -Path $DistPath -Recurse -Force
}

New-Item -Path $AppStage -ItemType Directory -Force | Out-Null
New-Item -Path (Join-Path $AppStage "data") -ItemType Directory -Force | Out-Null

# 3. Copy Application Assets or Native Compiled Binary
$NativeDist = Join-Path $AppRoot "nuitka_dist\app_server.dist"
$HasNative = (Test-Path (Join-Path $NativeDist "app_server.exe")) -and (-not $SkipNative)

if ($HasNative) {
    Write-Host "`n[NATIVE COMPILATION] Packaging compiled C machine code binary (Zero Python source files)..." -ForegroundColor Cyan
    Copy-Item -Path "$NativeDist\*" -Destination $AppStage -Recurse -Force
    $FrontendFiles = @("index.html", "fidelity.css", "workflows.js", "voucher_logic.js", "lookup_context.js", "print_view.js", "date_picker.js", "logo.png", "favicon.ico", "app.ico", "manifest.json", "version.json", "LICENSE")
    foreach ($file in $FrontendFiles) {
        Copy-Item -Path (Join-Path $AppRoot $file) -Destination $AppStage -Force
    }
    $site = (& python -c "import openpyxl,os;print(os.path.dirname(os.path.dirname(openpyxl.__file__)))" 2>$null)
    if ($site -and (Test-Path "$site\openpyxl")) {
        Copy-Item -Path "$site\openpyxl" -Destination $AppStage -Recurse -Force
        Copy-Item -Path "$site\et_xmlfile" -Destination $AppStage -Recurse -Force
        # Compile to bytecode and remove .py files so zero Python source files exist
        $destOpenpyxl = Join-Path $AppStage "openpyxl"
        $destEtXml = Join-Path $AppStage "et_xmlfile"
        & python -m compileall -b $destOpenpyxl $destEtXml | Out-Null
        Get-ChildItem -Path $destOpenpyxl, $destEtXml -Recurse -Filter "*.py" | Remove-Item -Force
    }
    Write-Host "  [OK] Native C app_server.exe and libraries included" -ForegroundColor Green
    Write-Host "  [OK] Source Python (.py) files excluded for anti-reverse engineering" -ForegroundColor Green
    # Strip unused modules to keep size ultra-compact
    Remove-Item (Join-Path $AppStage "numpy"), (Join-Path $AppStage "numpy.libs"), (Join-Path $AppStage "PIL") -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  [OK] Stripped unused modules (Numpy/PIL) for compact package" -ForegroundColor Green
} else {
    Write-Host "`nCopying application assets to staging directory..." -ForegroundColor Yellow
    foreach ($file in $CoreFiles) {
        Copy-Item -Path (Join-Path $AppRoot $file) -Destination $AppStage -Force
    }
    $RuntimeSrc = Join-Path $AppRoot "runtime"
    if ((-not $SkipEmbed) -and (Test-Path $RuntimeSrc)) {
        Write-Host "Copying embedded Python runtime (with openpyxl)..." -ForegroundColor Yellow
        Copy-Item -Path $RuntimeSrc -Destination $AppStage -Recurse -Force
        Write-Host "  [OK] Embedded runtime included" -ForegroundColor Green
    }
}

# Add installed marker
Set-Content -Path (Join-Path $AppStage "installed.marker") -Value "fincom-books-installed" -Encoding UTF8

# Portable ZIP moved to Step 7b


# 4. Generate Native Windows Launcher (FinComBooks.exe)
# gcc comes from PATH (MinGW on GitHub Actions) or GCC_DIR; no machine-specific paths.
$gccCmd = Get-Command "gcc.exe" -ErrorAction SilentlyContinue
$gccDir = if ($env:GCC_DIR) { $env:GCC_DIR } elseif ($gccCmd) { Split-Path $gccCmd.Source } else { "" }
$gccPath = if ($gccDir) { Join-Path $gccDir "gcc.exe" } else { "" }
$windresPath = if ($gccDir) { Join-Path $gccDir "windres.exe" } else { "" }
$cscPath = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$stageExe = Join-Path $AppStage "FinComBooks.exe"
$appIco = Join-Path $AppRoot "app.ico"
$launcherC = Join-Path $AppRoot "launcher.c"

if ($gccPath -and (Test-Path $gccPath) -and (Test-Path $launcherC)) {
    Write-Host "`nCompiling clean native Win32 C launcher with GCC (FinComBooks.exe)..." -ForegroundColor Cyan
    $fso = New-Object -ComObject Scripting.FileSystemObject
    $shortGcc = $fso.GetFile($gccPath).ShortPath
    $shortWindres = $fso.GetFile($windresPath).ShortPath

    Push-Location $DistPath
    if ($windresPath -and (Test-Path $windresPath) -and (Test-Path $appIco)) {
        Set-Content -Path "app.rc" -Value '1 ICON "../app.ico"' -Encoding Ascii
        & $shortWindres --preprocessor="$shortGcc -E -xc-header -DRC_INVOKED" -i app.rc -o app_res.o
        & $shortGcc -O2 -mwindows -o $stageExe $launcherC "app_res.o"
        Remove-Item "app.rc", "app_res.o" -ErrorAction SilentlyContinue
    } else {
        & $shortGcc -O2 -mwindows -o $stageExe $launcherC
    }
    Pop-Location
    Copy-Item $stageExe -Destination (Join-Path $AppRoot "FinComBooks.exe") -Force
    Write-Host "  [OK] Clean Native C FinComBooks.exe generated successfully" -ForegroundColor Green
} elseif (Test-Path $cscPath) {
    Write-Host "`nCompiling native Windows launcher (FinComBooks.exe)..." -ForegroundColor Yellow
    $launcherCs = @"
using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Threading;

namespace FinComBooksLauncher
{
    class Program
    {
        static bool IsPortListening(string host, int port)
        {
            try
            {
                using (var client = new TcpClient())
                {
                    var result = client.BeginConnect(host, port, null, null);
                    bool success = result.AsyncWaitHandle.WaitOne(80);
                    return success && client.Connected;
                }
            }
            catch { return false; }
        }

        static void Main(string[] args)
        {
            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            int port = 3543;
            string url = "http://127.0.0.1:" + port;

            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string userDir = Path.Combine(localAppData, "FinComBooks", "data");
            try { if (!Directory.Exists(userDir)) Directory.CreateDirectory(userDir); } catch { }
            string dataPath = Path.Combine(userDir, "books.sqlite3");

            if (!IsPortListening("127.0.0.1", port))
            {
                string nativeServer = Path.Combine(appDir, "app_server.exe");
                if (File.Exists(nativeServer))
                {
                    var startInfo = new ProcessStartInfo
                    {
                        FileName = nativeServer,
                        Arguments = string.Format("--port {0} --data \"{1}\"", port, dataPath),
                        WorkingDirectory = appDir,
                        CreateNoWindow = true,
                        UseShellExecute = false,
                        WindowStyle = ProcessWindowStyle.Hidden
                    };
                    try { Process.Start(startInfo); }
                    catch { }
                }
                else
                {
                    string pythonw = Path.Combine(appDir, "runtime", "pythonw.exe");
                    if (!File.Exists(pythonw))
                    {
                        string localPython = Path.Combine(localAppData, "Programs", "Python", "Python39", "pythonw.exe");
                        if (File.Exists(localPython)) pythonw = localPython;
                        else pythonw = "pythonw.exe";
                    }

                    string serverScript = Path.Combine(appDir, "app_server.py");
                    var startInfo = new ProcessStartInfo
                    {
                        FileName = pythonw,
                        Arguments = string.Format("-E -s \"{0}\" --port {1} --data \"{2}\"", serverScript, port, dataPath),
                        WorkingDirectory = appDir,
                        CreateNoWindow = true,
                        UseShellExecute = false,
                        WindowStyle = ProcessWindowStyle.Hidden
                    };

                    try { Process.Start(startInfo); }
                    catch { }
                }

                for (int i = 0; i < 30; i++)
                {
                    if (IsPortListening("127.0.0.1", port)) break;
                    Thread.Sleep(150);
                }
            }

            string profileDir = Path.Combine(localAppData, "FinComBooks", "profile");
            try { if (!Directory.Exists(profileDir)) Directory.CreateDirectory(profileDir); } catch { }

            string[] candidateBrowsers = new string[]
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Microsoft", "Edge", "Application", "msedge.exe"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Microsoft", "Edge", "Application", "msedge.exe"),
                Path.Combine(localAppData, "Microsoft", "Edge", "Application", "msedge.exe"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Google", "Chrome", "Application", "chrome.exe"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Google", "Chrome", "Application", "chrome.exe"),
                Path.Combine(localAppData, "Google", "Chrome", "Application", "chrome.exe")
            };

            string browserPath = null;
            foreach (var b in candidateBrowsers)
            {
                if (File.Exists(b)) { browserPath = b; break; }
            }

            if (browserPath != null)
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = browserPath,
                    Arguments = string.Format("--user-data-dir=\"{0}\" --app=\"{1}\" --no-first-run --no-default-browser-check --start-maximized", profileDir, url),
                    UseShellExecute = true
                });
            }
            else
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = url,
                    UseShellExecute = true
                });
            }
        }
    }
}
"@
    $launcherCsFile = Join-Path $DistPath "Launcher.cs"
    Set-Content -Path $launcherCsFile -Value $launcherCs -Encoding UTF8
    
    $stageExe = Join-Path $AppStage "FinComBooks.exe"
    $appIco = Join-Path $AppRoot "app.ico"
    if (Test-Path $appIco) {
        & $cscPath /target:winexe /optimize+ /win32icon:$appIco /out:$stageExe $launcherCsFile
    } else {
        & $cscPath /target:winexe /optimize+ /out:$stageExe $launcherCsFile
    }
    Copy-Item $stageExe -Destination (Join-Path $AppRoot "FinComBooks.exe") -Force
    Remove-Item $launcherCsFile -Force
    Write-Host "  [OK] FinComBooks.exe generated successfully with custom icon" -ForegroundColor Green
}

# 5. Generate Launcher Batch file as fallback
$BatchLauncherPath = Join-Path $AppStage "Launch.bat"
$BatchContent = @"
@echo off
setlocal
cd /d "%~dp0"
title FinCom Books
if exist "%~dp0FinComBooks.exe" (
    start "" "%~dp0FinComBooks.exe"
) else (
    powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0Launch.ps1"
)
"@
Set-Content -Path $BatchLauncherPath -Value $BatchContent -Encoding Ascii
Write-Host "  [OK] Generated Launch.bat fallback" -ForegroundColor Green

# 6. Generate Shortcut Creation Script (Desktop & Start Menu)
$ShortcutScriptPath = Join-Path $AppStage "create_shortcuts.ps1"
$ShortcutScriptContent = @"
`$WshShell = New-Object -ComObject WScript.Shell
`$Desktop = [System.Environment]::GetFolderPath('Desktop')
`$StartMenu = [System.Environment]::GetFolderPath('Programs')
`$TargetDir = `$PSScriptRoot
`$TargetExe = Join-Path `$TargetDir "FinComBooks.exe"
if (-not (Test-Path `$TargetExe)) { `$TargetExe = Join-Path `$TargetDir "Launch.bat" }

# Desktop Shortcut
`$DesktopShortcutPath = Join-Path `$Desktop "FinCom Books.lnk"
`$Shortcut = `$WshShell.CreateShortcut(`$DesktopShortcutPath)
`$Shortcut.TargetPath = `$TargetExe
`$Shortcut.WorkingDirectory = `$TargetDir
`$IcoPath = Join-Path `$TargetDir "app.ico"
if (Test-Path `$IcoPath) { `$Shortcut.IconLocation = "`$IcoPath,0" }
`$Shortcut.Description = "FinCom Books - Accounting"
`$Shortcut.Save()
Write-Host "Created Desktop Shortcut: `$DesktopShortcutPath" -ForegroundColor Green

# Start Menu Shortcut
`$AppStartMenuDir = Join-Path `$StartMenu "FinCom Books"
if (-not (Test-Path `$AppStartMenuDir)) {
    New-Item -Path `$AppStartMenuDir -ItemType Directory -Force | Out-Null
}
`$StartMenuShortcutPath = Join-Path `$AppStartMenuDir "FinCom Books.lnk"
`$SmShortcut = `$WshShell.CreateShortcut(`$StartMenuShortcutPath)
`$SmShortcut.TargetPath = `$TargetExe
`$SmShortcut.WorkingDirectory = `$TargetDir
if (Test-Path `$IcoPath) { `$SmShortcut.IconLocation = "`$IcoPath,0" }
`$SmShortcut.Description = "FinCom Books"
`$SmShortcut.Save()
Write-Host "Created Start Menu Shortcut: `$StartMenuShortcutPath" -ForegroundColor Green
"@
Set-Content -Path $ShortcutScriptPath -Value $ShortcutScriptContent -Encoding UTF8
Write-Host "  [OK] Generated create_shortcuts.ps1" -ForegroundColor Green

# 7. Generate Uninstaller Script
$UninstallScriptPath = Join-Path $AppStage "uninstall.ps1"
$UninstallContent = @"
`$Desktop = [System.Environment]::GetFolderPath('Desktop')
`$StartMenu = [System.Environment]::GetFolderPath('Programs')

`$DesktopShortcut = Join-Path `$Desktop "FinCom Books.lnk"
if (Test-Path `$DesktopShortcut) { Remove-Item -Path `$DesktopShortcut -Force }

`$AppStartMenu = Join-Path `$StartMenu "FinCom Books"
if (Test-Path `$AppStartMenu) { Remove-Item -Path `$AppStartMenu -Recurse -Force }

Write-Host "Shortcuts removed. To complete removal, delete directory: `$PSScriptRoot" -ForegroundColor Yellow
"@
Set-Content -Path $UninstallScriptPath -Value $UninstallContent -Encoding UTF8
Write-Host "  [OK] Generated uninstall.ps1" -ForegroundColor Green

# 7b. Build Clean Portable ZIP Package (Zero .vbs / .ps1 script files for Safe Browsing compliance)
Get-ChildItem -Path $AppStage -Include "*.vbs", "*.ps1", "*.bat" -Recurse | Remove-Item -Force -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.IO.Compression.FileSystem
$PortableZipPath = Join-Path $DistPath "FinComBooks_Portable.zip"
Write-Host "`nGenerating standalone Portable ZIP package (Clean of script files)..." -ForegroundColor Yellow
if (Test-Path $PortableZipPath) { Remove-Item $PortableZipPath -Force }
[System.IO.Compression.ZipFile]::CreateFromDirectory($AppStage, $PortableZipPath, [System.IO.Compression.CompressionLevel]::Optimal, $false)
Write-Host "  [OK] Portable ZIP created: $('{0:N2} MB' -f ((Get-Item $PortableZipPath).Length / 1MB))" -ForegroundColor Green

# 8. Compile Native Installer with NSIS (Nullsoft Scriptable Install System)
$NsisExe = "$env:LOCALAPPDATA\Programs\NSIS\makensis.exe"
if (-not (Test-Path $NsisExe)) {
    $nsisCmd = Get-Command "makensis.exe" -ErrorAction SilentlyContinue
    if ($nsisCmd) { $NsisExe = $nsisCmd.Source }
}

if (Test-Path $NsisExe) {
    Write-Host "`nCompiling NSIS-3 Installer with $NsisExe (Matches v1.0.0 clean engine)..." -ForegroundColor Cyan
    $finalExePath = Join-Path $DistPath $OutputExe
    $nsiPath = Join-Path $DistPath "installer.nsi"
    $nsiContent = @"
Unicode True
SetCompressor /SOLID lzma

Name "FinCom Books"
OutFile "$finalExePath"
InstallDir "`$LOCALAPPDATA\Programs\FinComBooks"
RequestExecutionLevel user

!include "MUI2.nsh"

!define MUI_ICON "$appIco"
!define MUI_UNICON "$appIco"
!define MUI_ABORTWARNING

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "`$INSTDIR\FinComBooks.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch FinCom Books"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "MainSection" SecMain
    SetOutPath "`$INSTDIR"
    File /r "$AppStage\*.*"
    WriteUninstaller "`$INSTDIR\uninstall.exe"

    CreateDirectory "`$SMPROGRAMS\FinCom Books"
    CreateShortcut "`$SMPROGRAMS\FinCom Books\FinCom Books.lnk" "`$INSTDIR\FinComBooks.exe" "" "`$INSTDIR\app.ico" 0
    CreateShortcut "`$SMPROGRAMS\FinCom Books\Uninstall FinCom Books.lnk" "`$INSTDIR\uninstall.exe" "" "`$INSTDIR\app.ico" 0
    CreateShortcut "`$DESKTOP\FinCom Books.lnk" "`$INSTDIR\FinComBooks.exe" "" "`$INSTDIR\app.ico" 0
SectionEnd

Section "Uninstall"
    Delete "`$DESKTOP\FinCom Books.lnk"
    RMDir /r "`$SMPROGRAMS\FinCom Books"
    RMDir /r "`$INSTDIR"
SectionEnd
"@
    Set-Content -Path $nsiPath -Value $nsiContent -Encoding Ascii
    & $NsisExe $nsiPath
    Write-Host "Successfully generated NSIS installer: $finalExePath" -ForegroundColor Green
} else {
    # Fallback to Inno Setup
    $InnoCompiler = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
    $InnoPath = if ($InnoCompiler) { $InnoCompiler.Source } elseif (Test-Path "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") { "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" } else { $null }
    if ($InnoPath) {
    Write-Host "`nCompiling Inno Setup Installer with $($InnoCompiler.Source)..." -ForegroundColor Yellow
    $IssPath = Join-Path $DistPath "installer.iss"
    $IssContent = @"
[Setup]
AppName=FinCom Books
AppVersion=1.1.0
DefaultDirName={localappdata}\Programs\FinCom Books
DefaultGroupName=FinCom Books
OutputDir=$DistPath
OutputBaseFilename=$([System.IO.Path]::GetFileNameWithoutExtension($OutputExe))
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "$AppStage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\FinCom Books"; Filename: "{app}\FinComBooks.exe"; WorkingDir: "{app}"
Name: "{group}\FinCom Books"; Filename: "{app}\FinComBooks.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall FinCom Books"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\FinComBooks.exe"; Description: "Launch FinCom Books"; Flags: postinstall nowait skipifsilent
"@
    Set-Content -Path $IssPath -Value $IssContent -Encoding Ascii
    & $InnoCompiler.Source $IssPath
    Write-Host "Successfully generated Inno Setup installer: $(Join-Path $DistPath $OutputExe)" -ForegroundColor Green
} else {
    Write-Host "`nBuilding standalone self-extracting installer executable ($OutputExe)..." -ForegroundColor Yellow
    
    # 8a. Create ZIP payload of staged app
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $PayloadZip = Join-Path $DistPath "payload.zip"
    Write-Host "Compressing application staging bundle into payload.zip..." -ForegroundColor Gray
    [System.IO.Compression.ZipFile]::CreateFromDirectory($AppStage, $PayloadZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    Write-Host "  [OK] Compressed bundle size: $('{0:N2} MB' -f ((Get-Item $PayloadZip).Length / 1MB))" -ForegroundColor Green

    # 8b. Compile Native C# Setup Executable embedding payload.zip
    $setupCs = @"
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

namespace FinComBooksSetup
{
    class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            try
            {
                string[] runningProcs = new string[] { "FinComBooks", "app_server" };
                foreach (var pName in runningProcs)
                {
                    try
                    {
                        foreach (var p in Process.GetProcessesByName(pName))
                        {
                            try { p.Kill(); p.WaitForExit(3000); } catch { }
                        }
                    }
                    catch { }
                }

                string targetDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Programs",
                    "FinComBooks"
                );

                if (!Directory.Exists(targetDir))
                {
                    Directory.CreateDirectory(targetDir);
                }

                string fullTargetDir = Path.GetFullPath(targetDir);
                if (!fullTargetDir.EndsWith(Path.DirectorySeparatorChar.ToString()))
                {
                    fullTargetDir += Path.DirectorySeparatorChar;
                }

                // Ensure persistent user data directory exists
                string persistentDataDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "FinComBooks",
                    "data"
                );
                if (!Directory.Exists(persistentDataDir))
                {
                    Directory.CreateDirectory(persistentDataDir);
                }

                // Extract embedded zip payload with Zip Slip path-traversal protection
                var asm = Assembly.GetExecutingAssembly();
                using (var stream = asm.GetManifestResourceStream("Payload"))
                {
                    if (stream != null)
                    {
                        using (var archive = new ZipArchive(stream, ZipArchiveMode.Read))
                        {
                            foreach (var entry in archive.Entries)
                            {
                                string destPath = Path.Combine(targetDir, entry.FullName);
                                string fullDestPath = Path.GetFullPath(destPath);
                                if (!fullDestPath.StartsWith(fullTargetDir, StringComparison.OrdinalIgnoreCase))
                                {
                                    throw new InvalidOperationException("Zip Slip path traversal blocked: " + entry.FullName);
                                }

                                if (string.IsNullOrEmpty(entry.Name))
                                {
                                    Directory.CreateDirectory(destPath);
                                }
                                else
                                {
                                    Directory.CreateDirectory(Path.GetDirectoryName(destPath));
                                    entry.ExtractToFile(destPath, true);
                                }
                            }
                        }
                    }
                    else
                    {
                        throw new Exception("Installation package is corrupted: payload stream not found.");
                    }
                }

                // Create Desktop Shortcut
                string desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
                string shortcutPath = Path.Combine(desktop, "FinCom Books.lnk");
                CreateShortcut(shortcutPath, Path.Combine(targetDir, "FinComBooks.exe"), targetDir, "FinCom Books - Accounting");

                // Create Start Menu Shortcut
                string programs = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                string startMenuDir = Path.Combine(programs, "FinCom Books");
                Directory.CreateDirectory(startMenuDir);
                CreateShortcut(Path.Combine(startMenuDir, "FinCom Books.lnk"), Path.Combine(targetDir, "FinComBooks.exe"), targetDir, "FinCom Books");

                // Launch App
                string exePath = Path.Combine(targetDir, "FinComBooks.exe");
                if (File.Exists(exePath))
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = exePath,
                        WorkingDirectory = targetDir
                    });
                }

                MessageBox.Show("FinCom Books has been successfully installed!\n\nA shortcut has been created on your Desktop.", "FinCom Books Setup", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show("Installation failed:\n" + ex.Message, "Installation Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        static void CreateShortcut(string shortcutPath, string targetPath, string workingDir, string description)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return;
                dynamic shell = Activator.CreateInstance(shellType);
                dynamic shortcut = shell.CreateShortcut(shortcutPath);
                shortcut.TargetPath = targetPath;
                shortcut.WorkingDirectory = workingDir;
                string ico = Path.Combine(workingDir, "app.ico");
                if (File.Exists(ico)) shortcut.IconLocation = ico + ",0";
                shortcut.Description = description;
                shortcut.Save();
            }
            catch { }
        }
    }
}
"@
    $setupCsFile = Join-Path $DistPath "Setup.cs"
    Set-Content -Path $setupCsFile -Value $setupCs -Encoding UTF8
    $finalExe = Join-Path $DistPath $OutputExe

    $appIco = Join-Path $AppRoot "app.ico"
    if (Test-Path $appIco) {
        & $cscPath /target:winexe /optimize+ /win32icon:$appIco /resource:"$PayloadZip,Payload" /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /reference:System.Windows.Forms.dll /out:$finalExe $setupCsFile
    } else {
        & $cscPath /target:winexe /optimize+ /resource:"$PayloadZip,Payload" /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /reference:System.Windows.Forms.dll /out:$finalExe $setupCsFile
    }
    
    Remove-Item $setupCsFile -Force
    Remove-Item $PayloadZip -Force

    Write-Host "Successfully generated standalone installer: $finalExe" -ForegroundColor Green
    Write-Host "  Installer size: $('{0:N2} MB' -f ((Get-Item $finalExe).Length / 1MB))" -ForegroundColor Cyan
}

}
Write-Host "`nPackaging completed successfully!" -ForegroundColor Green
return 0
