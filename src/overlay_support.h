#pragma once
#include <memory>

namespace live_overlay {
using Map=std::map<std::wstring,const wchar_t*,std::less<>>;
// The map can be replaced, but returned strings stay valid until process exit.
static SRWLOCK mapLock=SRWLOCK_INIT;
static Map current;
static std::set<std::wstring> retained;
static size_t retainedUnits=0;
static wchar_t path[32768]={0};
static FILETIME stamp={0,0};
static bool configure(const wchar_t* folder) {
    if(wcscpy_s(path,folder)!=0)return false;
#ifdef LOCALIZER_SELFTEST
    return wcscat_s(path,L"live-overlay.selftest.bin")==0;
#else
    return wcscat_s(path,L"live-overlay.bin")==0;
#endif
}
static void refresh() {
    if(!path[0])return;
    WIN32_FILE_ATTRIBUTE_DATA attributes={0};
    if(!GetFileAttributesExW(path,GetFileExInfoStandard,&attributes)||CompareFileTime(&stamp,&attributes.ftLastWriteTime)==0)return;
    if(attributes.nFileSizeHigh||attributes.nFileSizeLow<12||attributes.nFileSizeLow>1024*1024)return;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,0,nullptr);
    if(file==INVALID_HANDLE_VALUE)return;
    std::vector<unsigned char> bytes(attributes.nFileSizeLow);DWORD got=0;
    bool ok=ReadFile(file,bytes.data(),static_cast<DWORD>(bytes.size()),&got,nullptr)!=0;CloseHandle(file);
    if(!ok||got!=bytes.size()||memcmp(bytes.data(),"DOLTXT1\0",8)!=0)return;
    size_t cursor=8;
    auto number=[&](uint32_t& value)->bool{if(cursor+4>bytes.size())return false;memcpy(&value,bytes.data()+cursor,4);cursor+=4;return true;};
    uint32_t count=0;if(!number(count)||count>10000)return;
    std::map<std::wstring,std::wstring,std::less<>> parsed;
    for(uint32_t i=0;i<count;i++){
        uint32_t a=0,b=0;
        if(!number(a)||!number(b)||!a||!b||a>4096||b>4096||cursor+2*(a+b)>bytes.size())return;
        std::wstring source(a,L'\0'),target(b,L'\0');
        memcpy(&source[0],bytes.data()+cursor,a*2);cursor+=a*2;
        memcpy(&target[0],bytes.data()+cursor,b*2);cursor+=b*2;
        if(source.find(L'\0')!=std::wstring::npos||target.find(L'\0')!=std::wstring::npos||!parsed.emplace(std::move(source),std::move(target)).second)return;
    }
    if(cursor!=bytes.size())return;
    size_t extra=0;
    for(const auto& item:parsed)if(retained.find(item.second)==retained.end())extra+=item.second.size()+1;
    if(retainedUnits+extra>8*1024*1024)return;
    Map next;
    for(const auto& item:parsed){
        auto entry=retained.emplace(item.second);
        if(entry.second)retainedUnits+=entry.first->size()+1;
        next.emplace(item.first,entry.first->c_str());
    }
    AcquireSRWLockExclusive(&mapLock);current.swap(next);ReleaseSRWLockExclusive(&mapLock);
    stamp=attributes.ftLastWriteTime;
}
// Wrapped text is matched only as an ordered partition of one known source.
// Short suffixes are never installed as global dictionary keys.
static std::set<std::wstring> fragmentRetained;
static size_t fragmentUnits=0;
static const wchar_t* lookup(const wchar_t* text, const void* context=nullptr) {
    struct Pending {std::wstring source,target;const void* owner=nullptr;ULONGLONG until=0;};
    static thread_local Pending pending;
    const size_t length=wcslen(text);
    std::wstring source,target;
    AcquireSRWLockShared(&mapLock);
    auto entry=current.find(text);
    const wchar_t* exact=entry==current.end()?nullptr:entry->second;
    if(exact){ReleaseSRWLockShared(&mapLock);pending=Pending{};return exact;}
    if(pending.owner==context && GetTickCount64()<pending.until && !pending.source.empty()
        && length<=pending.source.size() && pending.source.compare(0,length,text)==0){
        source=pending.source;target=pending.target;
    } else if(length>=16) {
        // Reject ambiguous prefixes, including two entries with different tails.
        auto first=current.lower_bound(text);
        if(first!=current.end() && first->first.size()>length && first->first.compare(0,length,text)==0){
            auto next=first;++next;
            if(next==current.end() || next->first.compare(0,length,text)!=0){source=first->first;target=first->second;}
        }
    }
    // Some layout paths measure/render the final line before the first line.
    // Accept a standalone long suffix only when its whole source is unique.
    if(source.empty() && length>=8){
        const Map::value_type* match=nullptr;
        for(const auto& item:current){
            if(item.first[0]==L'\xff1a' || item.first.size()<=length)continue;
            if(item.first.compare(item.first.size()-length,length,text)!=0)continue;
            if(match){match=nullptr;break;}
            match=&item;
        }
        if(match){
            const std::wstring fullTarget=match->second;
            size_t begin=fullTarget.size()*(match->first.size()-length)/match->first.size();
            if(begin && begin<fullTarget.size() && fullTarget[begin-1]>=0xd800 && fullTarget[begin-1]<=0xdbff)--begin;
            source=text;target=fullTarget.substr(begin);
        }
    }
    ReleaseSRWLockShared(&mapLock);
    if(source.empty()){pending=Pending{};return nullptr;}
    size_t cut=length==source.size()?target.size():target.size()*length/source.size();
    if(cut==0 || cut>target.size()){pending=Pending{};return nullptr;}
    // Never cut a UTF-16 surrogate pair in half.
    if(cut<target.size() && target[cut-1]>=0xd800 && target[cut-1]<=0xdbff)--cut;
    if(!cut){pending=Pending{};return nullptr;}
    std::wstring part=target.substr(0,cut);
    pending.source=source.substr(length);pending.target=target.substr(cut);
    pending.owner=context;pending.until=GetTickCount64()+2000;
    AcquireSRWLockExclusive(&mapLock);
    const wchar_t* value=nullptr;
    if(fragmentUnits+part.size()+1<=1024*1024){
        auto saved=fragmentRetained.emplace(part);if(saved.second)fragmentUnits+=part.size()+1;
        value=saved.first->c_str();
    }
    ReleaseSRWLockExclusive(&mapLock);return value;
}
}
