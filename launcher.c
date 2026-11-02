#include <windows.h>
#include <shellapi.h>
#include <stdio.h>

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    char appDir[MAX_PATH];
    GetModuleFileNameA(NULL, appDir, MAX_PATH);
    char *lastSlash = strrchr(appDir, '\\');
    if (lastSlash) *(lastSlash + 1) = '\0';

    char serverExe[MAX_PATH];
    snprintf(serverExe, sizeof(serverExe), "%sapp_server.exe", appDir);

    char localAppData[MAX_PATH];
    GetEnvironmentVariableA("LOCALAPPDATA", localAppData, MAX_PATH);

    char dataDir[MAX_PATH];
    snprintf(dataDir, sizeof(dataDir), "%s\\FinComBooks\\data", localAppData);
    CreateDirectoryA(dataDir, NULL);

    char dataPath[MAX_PATH];
    snprintf(dataPath, sizeof(dataPath), "%s\\books.sqlite3", dataDir);

    char serverArgs[MAX_PATH * 2];
    snprintf(serverArgs, sizeof(serverArgs), "\"%s\" --port 3543 --data \"%s\"", serverExe, dataPath);

    // Launch app_server.exe
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    ZeroMemory(&pi, sizeof(pi));

    CreateProcessA(NULL, serverArgs, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, appDir, &si, &pi);

    // Allow server to bind port
    Sleep(400);

    // Launch Microsoft Edge in App mode, fallback to default browser
    char edgePath[MAX_PATH] = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
    if (GetFileAttributesA(edgePath) == INVALID_FILE_ATTRIBUTES) {
        snprintf(edgePath, sizeof(edgePath), "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe");
    }

    char profileDir[MAX_PATH];
    snprintf(profileDir, sizeof(profileDir), "%s\\FinComBooks\\profile", localAppData);
    CreateDirectoryA(profileDir, NULL);

    char browserArgs[MAX_PATH * 2];
    snprintf(browserArgs, sizeof(browserArgs), "--user-data-dir=\"%s\" --app=http://127.0.0.1:3543 --no-first-run", profileDir);

    if (GetFileAttributesA(edgePath) != INVALID_FILE_ATTRIBUTES) {
        ShellExecuteA(NULL, "open", edgePath, browserArgs, NULL, SW_SHOWNORMAL);
    } else {
        ShellExecuteA(NULL, "open", "http://127.0.0.1:3543", NULL, NULL, SW_SHOWNORMAL);
    }

    if (pi.hProcess) {
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
    return 0;
}
