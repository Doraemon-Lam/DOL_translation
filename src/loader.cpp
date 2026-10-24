#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <wchar.h>
#include <stdint.h>

// Explicit one-shot launcher, never runs as part of building the DLL.
// Requires a separate user-authorized game experiment. No game file writes.
static uintptr_t remoteModule(DWORD pid,const wchar_t* name,wchar_t* path=nullptr) {
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPMODULE|TH32CS_SNAPMODULE32,pid);
    if(snapshot==INVALID_HANDLE_VALUE)return 0;
    MODULEENTRY32W entry={0};entry.dwSize=sizeof(entry);uintptr_t result=0;
    if(Module32FirstW(snapshot,&entry))do{
        if(!_wcsicmp(entry.szModule,name)){result=reinterpret_cast<uintptr_t>(entry.modBaseAddr);if(path)wcscpy_s(path,32768,entry.szExePath);break;}
    }while(Module32NextW(snapshot,&entry));
    CloseHandle(snapshot);return result;
}
static bool run(HANDLE process,uintptr_t function,void* argument,DWORD& result) {
    HANDLE thread=CreateRemoteThread(process,nullptr,0,reinterpret_cast<LPTHREAD_START_ROUTINE>(function),argument,0,nullptr);
    if(!thread)return false;
    bool success=WaitForSingleObject(thread,15000)==WAIT_OBJECT_0 && GetExitCodeThread(thread,&result);
    CloseHandle(thread);return success;
}
int wmain(int argc,wchar_t** argv) {
    if(argc==3 && !wcscmp(argv[1],L"--selftest-dll")) {
        HMODULE module=LoadLibraryW(argv[2]);if(!module)return 20;
        auto install=reinterpret_cast<DWORD(WINAPI*)(void*)>(GetProcAddress(module,"InstallLocalization"));
        auto disable=reinterpret_cast<DWORD(WINAPI*)(void*)>(GetProcAddress(module,"DisableTranslations"));
        auto count=reinterpret_cast<DWORD(WINAPI*)(void*)>(GetProcAddress(module,"GetReplacementCount"));
        if(!install||!disable||!count || install(nullptr)!=2 || disable(nullptr)!=0 || count(nullptr)!=0)return 21;
        FreeLibrary(module);printf("PASS DLL refuses non-game host and exports are callable\n");return 0;
    }
    const bool disable=argc==4 && !wcscmp(argv[1],L"--disable-translations");
    if(argc!=4 || (!disable && wcscmp(argv[1],L"--authorized-game-experiment"))) {
        fwprintf(stderr,L"Usage: loader --authorized-game-experiment PID ABSOLUTE_DLL_PATH\n");return 2;
    }
    DWORD pid=wcstoul(argv[2],nullptr,10);
    wchar_t full[32768]={0};
    if(!pid || !GetFullPathNameW(argv[3],32768,full,nullptr))return 3;
    const wchar_t* basename=wcsrchr(full,L'\\');basename=basename?basename+1:full;
    if(_wcsicmp(basename,L"dol-localizer-experimental.dll"))return 4;
    if(!remoteModule(pid,L"gvonline.bin"))return 5;
    wchar_t existingPath[32768]={0};
    uintptr_t existing=remoteModule(pid,basename,existingPath);
    if(existing && _wcsicmp(existingPath,full))return 19;
    if(!disable && existing)return 6; // never install twice
    if(disable && !existing)return 17;
    HMODULE local=LoadLibraryExW(full,nullptr,DONT_RESOLVE_DLL_REFERENCES);
    if(!local)return 7;
    auto install=GetProcAddress(local,disable?"DisableTranslations":"InstallLocalization");
    if(!install){FreeLibrary(local);return 8;}
    uintptr_t installOffset=reinterpret_cast<uintptr_t>(install)-reinterpret_cast<uintptr_t>(local);
    FreeLibrary(local);
    if(disable){
        HANDLE process=OpenProcess(PROCESS_CREATE_THREAD|PROCESS_QUERY_INFORMATION|PROCESS_VM_OPERATION|PROCESS_VM_WRITE|PROCESS_VM_READ,FALSE,pid);
        if(!process)return 11;
        DWORD status=0;bool ok=run(process,existing+installOffset,nullptr,status);CloseHandle(process);
        printf("DisableTranslations returned %lu\n",status);return ok&&status==0?0:18;
    }
    FARPROC load=GetProcAddress(GetModuleHandleW(L"kernel32.dll"),"LoadLibraryW");
    HMODULE owner=nullptr;
    if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,reinterpret_cast<LPCWSTR>(load),&owner))return 9;
    wchar_t ownerPath[32768]={0};GetModuleFileNameW(owner,ownerPath,32768);
    const wchar_t* ownerName=wcsrchr(ownerPath,L'\\');ownerName=ownerName?ownerName+1:ownerPath;
    uintptr_t remoteOwner=remoteModule(pid,ownerName);
    if(!remoteOwner)return 10;
    uintptr_t remoteLoad=remoteOwner+reinterpret_cast<uintptr_t>(load)-reinterpret_cast<uintptr_t>(owner);
    HANDLE process=OpenProcess(PROCESS_CREATE_THREAD|PROCESS_QUERY_INFORMATION|PROCESS_VM_OPERATION|PROCESS_VM_WRITE|PROCESS_VM_READ,FALSE,pid);
    if(!process)return 11;
    SIZE_T bytes=(wcslen(full)+1)*sizeof(wchar_t),written=0;
    void* remotePath=VirtualAllocEx(process,nullptr,bytes,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if(!remotePath || !WriteProcessMemory(process,remotePath,full,bytes,&written) || written!=bytes){CloseHandle(process);return 12;}
    DWORD loaded=0;
    if(!run(process,remoteLoad,remotePath,loaded)){
        // Leave the path allocation until process exit: a timed-out loader could
        // still be using it. Never free or unload while remote code is in flight.
        CloseHandle(process);return 13;
    }
    VirtualFreeEx(process,remotePath,0,MEM_RELEASE);
    if(!loaded){CloseHandle(process);return 14;}
    DWORD status=0;
    bool success=run(process,static_cast<uintptr_t>(loaded)+installOffset,nullptr,status);
    CloseHandle(process);
    if(!success)return 15;
    printf("InstallLocalization returned %lu\n",status);
    return status==0?0:16;
}
