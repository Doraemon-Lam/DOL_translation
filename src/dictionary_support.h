#pragma once
#include <map>
#include <set>
#include <string>
#include <vector>
#include "dictionary-digest.h"
#ifdef LIVE_OVERLAY
#include "overlay_support.h"
#endif

namespace full_dictionary {
static std::map<std::wstring,std::wstring,std::less<>> entries;
static CRITICAL_SECTION queueLock;
static HANDLE wakeEvent=nullptr;
static wchar_t logPath[32768]={0};
static wchar_t queue[256][1025]={0};
static unsigned int head=0,tail=0,queued=0;
static LONG dropped=0;

static bool hasKana(const wchar_t* text) {
    for(unsigned int i=0;text && text[i] && i<1024;i++)if((text[i]>=0x3041&&text[i]<=0x3096)||(text[i]>=0x30a1&&text[i]<=0x30fa))return true;
    return false;
}
static void enqueue(const wchar_t* text) {
    if(!wakeEvent || !hasKana(text))return;
    // Never block rendering on disk I/O or a contended queue.
    if(!TryEnterCriticalSection(&queueLock)){InterlockedIncrement(&dropped);return;}
    if(queued==256){LeaveCriticalSection(&queueLock);InterlockedIncrement(&dropped);return;}
    unsigned int i=0;for(;i<1024&&text[i];i++)queue[tail][i]=text[i];queue[tail][i]=0;
    if(text[i]){LeaveCriticalSection(&queueLock);InterlockedIncrement(&dropped);return;}
    tail=(tail+1)%256;queued++;LeaveCriticalSection(&queueLock);SetEvent(wakeEvent);
}
static std::string jsonText(const wchar_t* text) {
    int bytes=WideCharToMultiByte(CP_UTF8,0,text,-1,nullptr,0,nullptr,nullptr);
    if(bytes<=0)return "";
    std::vector<char> converted(static_cast<size_t>(bytes));
    WideCharToMultiByte(CP_UTF8,0,text,-1,converted.data(),bytes,nullptr,nullptr);
    std::string out="{\"text\":\"";
    const char hex[]="0123456789abcdef";
    for(int i=0;i<bytes-1;i++){
        unsigned char c=static_cast<unsigned char>(converted[i]);
        if(c=='"'||c=='\\'){out+='\\';out+=static_cast<char>(c);}
        else if(c<32){out+="\\u00";out+=hex[c>>4];out+=hex[c&15];}
        else out+=static_cast<char>(c);
    }
    return out+"\"}\n";
}
static DWORD WINAPI logger(void*) {
    HANDLE file=CreateFileW(logPath,FILE_APPEND_DATA,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE)return 1;
    std::set<std::wstring> seen;
    for(;;){
        WaitForSingleObject(wakeEvent,1000);
#ifdef LIVE_OVERLAY
        live_overlay::refresh();
#endif
        for(;;){
            wchar_t text[1025]={0};
            EnterCriticalSection(&queueLock);
            if(!queued){LeaveCriticalSection(&queueLock);break;}
            wcscpy_s(text,queue[head]);head=(head+1)%256;queued--;LeaveCriticalSection(&queueLock);
            if(seen.size()>=10000 || !seen.emplace(text).second)continue;
            std::string line=jsonText(text);DWORD written=0;
            WriteFile(file,line.data(),static_cast<DWORD>(line.size()),&written,nullptr);
        }
    }
}
static bool initialize(HMODULE module) {
    wchar_t path[32768]={0};if(!GetModuleFileNameW(module,path,32768))return false;
    wchar_t* slash=wcsrchr(path,L'\\');if(!slash)return false;slash[1]=0;
#ifdef LIVE_OVERLAY
    if(!live_overlay::configure(path))return false;
    live_overlay::refresh();
#endif
    if(wcscpy_s(logPath,path)!=0)return false;
#ifdef LOCALIZER_SELFTEST
    if(wcscat_s(logPath,L"logger-selftest.jsonl")!=0)return false;
#else
    if(wcscat_s(logPath,L"missing-text.jsonl")!=0)return false;
#endif
    if(wcscat_s(path,L"translation-dictionary.bin")!=0)return false;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    LARGE_INTEGER size={0};bool sized=GetFileSizeEx(file,&size)!=0;
    if(!sized || size.QuadPart<12 || size.QuadPart>64*1024*1024){CloseHandle(file);return false;}
    std::vector<unsigned char> bytes(static_cast<size_t>(size.QuadPart));DWORD got=0;
    bool read=ReadFile(file,bytes.data(),static_cast<DWORD>(bytes.size()),&got,nullptr)!=0;CloseHandle(file);
    if(!read||got!=bytes.size())return false;
    BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;unsigned char digest[32]={0};bool verified=false;
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0){
        if(BCryptCreateHash(algorithm,&hash,nullptr,0,nullptr,0,0)>=0){
            verified=BCryptHashData(hash,bytes.data(),static_cast<ULONG>(bytes.size()),0)>=0 && BCryptFinishHash(hash,digest,32,0)>=0 && memcmp(digest,dictionaryDigest,32)==0;
            BCryptDestroyHash(hash);
        }
        BCryptCloseAlgorithmProvider(algorithm,0);
    }
    if(!verified || memcmp(bytes.data(),"DOLTXT1\0",8)!=0)return false;
    size_t cursor=8;
    auto number=[&](uint32_t& value)->bool{if(cursor+4>bytes.size())return false;memcpy(&value,bytes.data()+cursor,4);cursor+=4;return true;};
    uint32_t count=0;if(!number(count)||count>100000)return false;
    for(uint32_t i=0;i<count;i++){
        uint32_t a=0,b=0;if(!number(a)||!number(b)||!a||!b||a>4096||b>4096||cursor+2*(a+b)>bytes.size())return false;
        std::wstring source(a,L'\0'),target(b,L'\0');
        memcpy(&source[0],bytes.data()+cursor,a*2);cursor+=a*2;
        memcpy(&target[0],bytes.data()+cursor,b*2);cursor+=b*2;
        if(source.find(L'\0')!=std::wstring::npos||target.find(L'\0')!=std::wstring::npos||!entries.emplace(std::move(source),std::move(target)).second)return false;
    }
    if(cursor!=bytes.size())return false;
#if !defined(LOCALIZER_SELFTEST) || defined(LOGGER_SELFTEST)
#ifdef LOCALIZER_SELFTEST
    DeleteFileW(logPath); // Disposable fixture log only; never the game log.
#endif
    InitializeCriticalSection(&queueLock);
    wakeEvent=CreateEventW(nullptr,FALSE,FALSE,nullptr);if(!wakeEvent)return false;
    HANDLE worker=CreateThread(nullptr,0,logger,nullptr,0,nullptr);if(!worker){CloseHandle(wakeEvent);wakeEvent=nullptr;return false;}
    CloseHandle(worker);
#endif
    return true;
}
static const wchar_t* lookup(const wchar_t* text) {
#ifdef LIVE_OVERLAY
    const wchar_t* live=live_overlay::lookup(text);if(live)return live;
#endif
    auto found=entries.find(text);
    if(found!=entries.end())return found->second.c_str();
    enqueue(text);return nullptr;
}
}
