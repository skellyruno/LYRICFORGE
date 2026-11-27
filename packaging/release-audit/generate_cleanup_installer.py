"""Build an installer cleanup allowlist from two verified package ledgers."""
import argparse,json,re
from pathlib import Path
from cleanup_legacy_media import read,PREFIXES

EXPECTED_OLD_COUNT=253
EXPECTED_OLD_BYTES=80874948

def generate(base,old,new,out):
    old,new=read(old),read(new)
    eligible={k:v for k,v in old.items() if k not in new and k.startswith(PREFIXES)}
    if len(eligible)!=EXPECTED_OLD_COUNT or sum(v[0] for v in eligible.values())!=EXPECTED_OLD_BYTES:
        raise ValueError("Unrecognized legacy package")
    for name,(size,digest) in eligible.items():
        if not re.fullmatch(r"[A-Za-z0-9_.+/-]+",name) or not re.fullmatch(r"[0-9a-f]{64}",digest):
            raise ValueError("Unsafe cleanup allowlist entry")
    base=Path(base).read_text(encoding="utf-8")
    if "[Code]" in base or "[InstallDelete]" in base or "[UninstallDelete]" in base:raise ValueError("Unexpected installer base")
    if new.get("_internal/tools/ffprobe.exe")!=(44490240,"f04d1654ac6c2016b1654c8634cdaf39fd367b919c417b38f4d9a9913900312c"):
        raise ValueError("Wrong reconstructed FFprobe")
    code=r'''
[UninstallDelete]
Type: files; Name: "{app}\_internal\tools\ffprobe.exe"

[Code]
function GetLegacyFileAttributes(FileName: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function SafeLegacyPath(FileName: String): Boolean;
var
  P, Parent: String;
  Attr: LongWord;
begin
  Result := False;
  P := FileName;
  Attr := GetLegacyFileAttributes(P);
  if (Attr = $FFFFFFFF) or ((Attr and $10) <> 0) then Exit;
  repeat
    Attr := GetLegacyFileAttributes(P);
    if (Attr = $FFFFFFFF) or ((Attr and $400) <> 0) then Exit;
    Parent := ExtractFileDir(P);
    if (Parent = P) or (Parent = '') then Break;
    P := Parent;
  until False;
  Result := True;
end;

procedure RemoveExactLegacy(RelativeName, ExpectedHash: String);
var
  P: String;
begin
  P := ExpandConstant('{app}\') + RelativeName;
  if not SafeLegacyPath(P) then Exit;
  try
    if CompareText(GetSHA256OfFile(P), ExpectedHash) <> 0 then
    begin
      Log('Preserved changed legacy file: ' + RelativeName);
      Exit;
    end;
    if not SafeLegacyPath(P) then Exit;
    if DeleteFile(P) then
      Log('Removed exact obsolete file: ' + RelativeName)
    else
      Log('Preserved unavailable legacy file: ' + RelativeName);
  except
    Log('Preserved unreadable legacy file: ' + RelativeName);
  end;
end;

procedure CleanLegacyMedia;
begin
'''
    code+="\n".join("  RemoveExactLegacy('"+k.replace("/","\\")+"', '"+v[1]+"');" for k,v in sorted(eligible.items()))
    code+=r'''
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  ProbePath: String;
begin
  if CurStep = ssPostInstall then
  begin
    if not Exec(ExpandConstant('{app}\SkellyMotion.exe'), '--restore-ffprobe',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Unable to reconstruct the verified media probe');
    if ResultCode <> 0 then
      RaiseException('Verified media probe reconstruction failed');
    ProbePath := ExpandConstant('{app}\_internal\tools\ffprobe.exe');
    if not FileExists(ProbePath) then
      RaiseException('Verified media probe is missing');
    if CompareText(GetSHA256OfFile(ProbePath), 'f04d1654ac6c2016b1654c8634cdaf39fd367b919c417b38f4d9a9913900312c') <> 0 then
      RaiseException('Verified media probe checksum mismatch');
    { Only after the new app and exact native tool are installed. }
    CleanLegacyMedia;
  end;
end;
'''
    Path(out).write_text(base+"\n"+code,encoding="utf-8",newline="\n")
    print("Exact allowlist:",len(eligible),"files",EXPECTED_OLD_BYTES,"bytes",flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for a in ("base","old","new","out"):p.add_argument(a)
    a=p.parse_args();generate(a.base,a.old,a.new,a.out)
