#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include <vector>
#include <MinHook.h>
#ifdef FULL_DICTIONARY
#include "dictionary_support.h"
#endif

// Experimental, exact-build only. InstallLocalization is NEVER called by
// DllMain. This file contains no loader/injector or automatic game launching.
using Layout = SIZE* (__thiscall*)(void*,SIZE*,const wchar_t*,const SIZE*,DWORD,int,const SIZE*);
static Layout originalLayout=nullptr;
static LONG enabled=0;
static LONG replacements=0;
struct Pair {const wchar_t* source;const wchar_t* target;};
static const Pair pairs[]={
    {L"どうする？",L"要怎么做？"},
    {L"どうする?",L"要怎么做？"},
    {L"教えてもらう",L"请教相关知识"},
    {L"断る",L"拒绝"}
};

static const wchar_t* translate(const wchar_t* text) {
    if(!text || !InterlockedCompareExchange(&enabled,0,0))return text;
    for(const auto& p:pairs)if(wcscmp(text,p.source)==0){InterlockedIncrement(&replacements);return p.target;}
#ifdef FULL_DICTIONARY
    const wchar_t* translated=full_dictionary::lookup(text);
    if(translated){InterlockedIncrement(&replacements);return translated;}
#endif
    return text;
}
static SIZE* __fastcall layoutHook(void* self,void*,SIZE* out,const wchar_t* text,const SIZE* scale,DWORD color,int lineHeight,const SIZE* bounds) {
    return originalLayout(self,out,translate(text),scale,color,lineHeight,bounds);
}

static DWORD installAt(void* target) {
    MH_STATUS status=MH_Initialize();
    if(status!=MH_OK)return 100+status;
    status=MH_CreateHook(target,reinterpret_cast<void*>(&layoutHook),reinterpret_cast<void**>(&originalLayout));
    if(status!=MH_OK){MH_Uninitialize();return 200+status;}
    InterlockedExchange(&enabled,1);
    status=MH_EnableHook(target);
    if(status!=MH_OK){InterlockedExchange(&enabled,0);MH_RemoveHook(target);MH_Uninitialize();return 300+status;}
    return 0;
}

#ifndef LOCALIZER_SELFTEST
static bool expectedFile(HMODULE module) {
    wchar_t path[32768]={0};
    if(!GetModuleFileNameW(module,path,32768))return false;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,0,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;
    bool success=false;
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0){
        if(BCryptCreateHash(algorithm,&hash,nullptr,0,nullptr,0,0)>=0){
            unsigned char buffer[65536],digest[32];DWORD got=0;bool valid=true;
            for(;;){if(!ReadFile(file,buffer,sizeof(buffer),&got,nullptr)){valid=false;break;}if(!got)break;if(BCryptHashData(hash,buffer,got,0)<0){valid=false;break;}}
            if(valid && BCryptFinishHash(hash,digest,sizeof(digest),0)>=0){
                const unsigned char expected[]={0xef,0x9a,0xa7,0xa8,0x32,0xc5,0xec,0xf8,0x74,0x23,0x8f,0x2e,0x4b,0x5d,0x18,0x5c,0xdb,0x6c,0x8d,0x26,0xb1,0x4c,0xba,0x71,0x02,0xd9,0x8d,0xbf,0xc8,0x21,0x16,0xae};
                success=memcmp(digest,expected,32)==0;
            }
            BCryptDestroyHash(hash);
        }
        BCryptCloseAlgorithmProvider(algorithm,0);
    }
    CloseHandle(file);return success;
}

extern "C" __declspec(dllexport) DWORD WINAPI InstallLocalization(void*) {
    if(originalLayout)return 1;
    HMODULE module=GetModuleHandleW(L"GVOnline.bin");
    if(!module || !expectedFile(module))return 2;
    auto* target=reinterpret_cast<unsigned char*>(module)+0x663a50;
    const unsigned char prologue[]={0x55,0x8b,0xec,0x6a,0xff};
    if(memcmp(target,prologue,sizeof(prologue))!=0)return 3;
    // Pin before installing: unloading a DLL with callbacks in flight is unsafe.
    HMODULE pinned=nullptr;
    if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,reinterpret_cast<LPCWSTR>(&InstallLocalization),&pinned))return 4;
#ifdef FULL_DICTIONARY
    if(!full_dictionary::initialize(pinned))return 5;
#endif
    return installAt(target);
}
extern "C" __declspec(dllexport) DWORD WINAPI DisableTranslations(void*) {
    InterlockedExchange(&enabled,0);return 0;
}
extern "C" __declspec(dllexport) DWORD WINAPI GetReplacementCount(void*) {
    return static_cast<DWORD>(InterlockedCompareExchange(&replacements,0,0));
}
BOOL WINAPI DllMain(HINSTANCE,DWORD,LPVOID){return TRUE;}
#else
static wchar_t observed[128]={0};
#ifdef LIVE_OVERLAY
static bool writeTestOverlay(const wchar_t* target) {
    const wchar_t* source=L"熱更新試験専用の未登録文";
    std::vector<unsigned char> bytes={'D','O','L','T','X','T','1',0};
    auto number=[&](uint32_t n){unsigned char raw[4];memcpy(raw,&n,4);bytes.insert(bytes.end(),raw,raw+4);};
    number(1);number(static_cast<uint32_t>(wcslen(source)));number(static_cast<uint32_t>(wcslen(target)));
    const unsigned char* a=reinterpret_cast<const unsigned char*>(source);const unsigned char* b=reinterpret_cast<const unsigned char*>(target);
    bytes.insert(bytes.end(),a,a+2*wcslen(source));bytes.insert(bytes.end(),b,b+2*wcslen(target));
    std::wstring temp=std::wstring(live_overlay::path)+L".tmp";
    HANDLE file=CreateFileW(temp.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,0,nullptr);if(file==INVALID_HANDLE_VALUE)return false;
    DWORD written=0;bool ok=WriteFile(file,bytes.data(),static_cast<DWORD>(bytes.size()),&written,nullptr)&&written==bytes.size();CloseHandle(file);
    return ok && MoveFileExW(temp.c_str(),live_overlay::path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
}
#endif
class Fixture {
public:
    __declspec(noinline) SIZE* layout(SIZE* out,const wchar_t* text,const SIZE* scale,DWORD color,int lineHeight,const SIZE* bounds) {
        wcscpy_s(observed,text?text:L"");
        out->cx=scale->cx+static_cast<LONG>(color)+bounds->cx;
        out->cy=lineHeight+scale->cy+bounds->cy;
        return out;
    }
};
int main() {
#ifdef FULL_DICTIONARY
    if(!full_dictionary::initialize(GetModuleHandleW(nullptr)))return 17;
    if(full_dictionary::entries.empty())return 18;
    full_dictionary::entries.emplace(L"これは辞書の実験です",L"这是词库替换实验");
#endif
    Fixture fixture;auto method=&Fixture::layout;void* target=nullptr;
    static_assert(sizeof(method)==sizeof(target),"Fixture member pointer must be a single x86 code address");
    memcpy(&target,&method,sizeof(target));
    SIZE scale={16,17},bounds={800,600},out={0,0};
    if(installAt(target)!=0)return 10;
    for(int i=0;i<1000;i++){
        if(fixture.layout(&out,L"教えてもらう",&scale,0x1234,24,&bounds)!=&out)return 11;
        if(wcscmp(observed,L"请教相关知识") || out.cx!=16+0x1234+800 || out.cy!=24+17+600)return 12;
    }
    fixture.layout(&out,L"未登録の文章",&scale,0,1,&bounds);
    if(wcscmp(observed,L"未登録の文章"))return 13;
#ifdef LOGGER_SELFTEST
    bool logged=false;
    for(int tries=0;tries<50&&!logged;tries++){
        HANDLE file=CreateFileW(full_dictionary::logPath,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,OPEN_EXISTING,0,nullptr);
        if(file!=INVALID_HANDLE_VALUE){
            char bytes[4096]={0};DWORD got=0;
            if(ReadFile(file,bytes,sizeof(bytes)-1,&got,nullptr)&&strstr(bytes,"未登録の文章"))logged=true;
            CloseHandle(file);
        }
        if(!logged)Sleep(20);
    }
    if(!logged)return 20;
    printf("PASS background missing-text logging verified\n");
#endif
    InterlockedExchange(&enabled,0);
    fixture.layout(&out,L"教えてもらう",&scale,0,1,&bounds);
    if(wcscmp(observed,L"教えてもらう"))return 14;
    if(replacements!=1000)return 15;
#ifdef FULL_DICTIONARY
    InterlockedExchange(&enabled,1);
    fixture.layout(&out,L"これは辞書の実験です",&scale,0,1,&bounds);
    if(wcscmp(observed,L"这是词库替换实验"))return 19;
    printf("PASS immutable dictionary loaded: %zu entries, non-hardcoded replacement verified\n",full_dictionary::entries.size());
#endif
#ifdef LIVE_OVERLAY
    const wchar_t* source=L"熱更新試験専用の未登録文";
    if(!writeTestOverlay(L"第一版热更新译文"))return 21;
    bool first=false;
    for(int i=0;i<150&&!first;i++){fixture.layout(&out,source,&scale,0,1,&bounds);first=wcscmp(observed,L"第一版热更新译文")==0;if(!first)Sleep(20);}
    if(!first)return 22;
    const wchar_t* retained=live_overlay::lookup(source);
    Sleep(30);
    if(!writeTestOverlay(L"第二版热更新译文"))return 23;
    bool second=false;
    for(int i=0;i<150&&!second;i++){fixture.layout(&out,source,&scale,0,1,&bounds);second=wcscmp(observed,L"第二版热更新译文")==0;if(!second)Sleep(20);}
    if(!second||wcscmp(retained,L"第一版热更新译文"))return 24;
    printf("PASS live overlay reload and retained string lifetime verified\n");
#endif
    if(MH_DisableHook(target)!=MH_OK || MH_Uninitialize()!=MH_OK)return 16;
    printf("PASS x86 thiscall layout hook: 1000 replacements, argument preservation, unknown pass-through, disable\n");
    return 0;
}
#endif
